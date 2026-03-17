import requests, datetime, time, logging, re, sys, os, urllib3
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm  # 引入進度條

# --- 【1. 初始化工具與模式偵測】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
cc = OpenCC('s2t')

# 💡 新增：偵測 GitHub Actions 觸發事件
GITHUB_EVENT = os.getenv('GITHUB_EVENT_NAME', 'local')
if GITHUB_EVENT == 'workflow_dispatch':
    RUN_MODE = "MANUAL_ONLY"
else:
    RUN_MODE = "FULL_SCAN"

adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50)
session = requests.Session()
session.mount('http://', adapter)
session.mount('https://', adapter)

update_time = datetime.datetime.now().strftime("%m%d %H:%M")

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.FileHandler("auto_repair.log", mode='w', encoding="utf-8"), 
        logging.StreamHandler()
    ]
)

# --- 【工具函數】 ---
def load_sources(file_path="sources.txt"):
    """
    🌟 同步區間控制邏輯：
    - MANUAL_ONLY: 只掃描 # MY MANUAL SOURCES 到自動更新標籤之間
    - FULL_SCAN: 掃描全份文件
    """
    if not os.path.exists(file_path):
        return []
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if RUN_MODE == "MANUAL_ONLY":
            manual_urls = []
            is_capture_zone = False
            for line in lines:
                line = line.strip()
                if "# MY MANUAL SOURCES" in line.upper():
                    is_capture_zone = True
                    continue
                if "# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---" in line.upper():
                    is_capture_zone = False
                    break
                if is_capture_zone and line.startswith("http"):
                    clean_url = line.split('#')[0].strip()
                    if clean_url: manual_urls.append(clean_url)
            
            logging.info(f">>> 偵測到手動撳制：啟動 MANUAL_ONLY 模式 <<<")
            logging.info(f"🚀 [手動模式] 鎖定測試區間，共加載 {len(manual_urls)} 個源")
            return manual_urls
        else:
            # FULL_SCAN: 正常讀取所有非註釋行
            urls = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
            logging.info(f"✅ [數據讀取] 已從 {file_path} 加載 {len(urls)} 個源")
            return urls
    except Exception as e:
        logging.error(f"❌ [數據讀取] 錯誤: {e}")
    return []

def get_speed(url):
    try:
        start = time.time()
        # verify=False 配合靜音警告
        r = session.get(url, timeout=1.5, headers=HEADERS, stream=True, verify=False)
        if r.status_code < 400:
            # 讀取一小塊確保流是通的
            for _ in r.iter_content(chunk_size=1024):
                break
            return time.time() - start
    except: pass
    return 999

def get_group(name):
    check_name = name.upper().replace(" ", "")
    if "CCTV" in check_name: return "特色"
    if any(x in name for x in ["翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線", "有線", "J2", "J5", "鳳凰"]): return "香港"
    if any(x in name for x in ["東森", "三立", "中視", "公視", "TVBS", "緯來", "民視", "年代", "中天", "非凡", "台視"]): return "台灣"
    if any(x in name for x in ["廣東", "珠江", "廣州", "大灣區", "南方", "深圳"]): return "廣東"
    if any(x in name for x in ["澳視", "澳門", "TDM", "澳亞"]): return "澳門"
    return "其他"

# --- 【2. 核心配置】 ---
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

BLOCK_KEYWORDS = ["FOX", "UHD", "8K", "浙江", "杭州", "深圳", "延时", "測試", "購物", "福建", "江蘇", "湖南", "湖北"]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- 【3. 診斷報告函數】 ---
def diagnose_report(u):
    count_total = 0
    count_online = 0
    count_white = 0
    count_black = 0
    all_raw_items = []
    
    try:
        r = session.get(u, timeout=20, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return [], False
        
        name = ""
        for line in r.text.split('\n'):
            line = line.strip()
            if line.startswith("#EXTINF"):
                count_total += 1
                raw_name = cc.convert(line.split(',')[-1]).replace('臺', '台').strip()
                name = re.sub(r'\[.*?\]', '', raw_name).strip()
            elif line.startswith("http") and name:
                all_raw_items.append({'name': name, 'url': line.split('$')[0].strip()})
                name = ""

        born_list, black_detail_names = [], []
        if all_raw_items:
            with ThreadPoolExecutor(max_workers=50) as ex:
                futures = [ex.submit(get_speed, x['url']) for x in all_raw_items]
                speeds = []
                for f in tqdm(futures, desc=f"⚡ 測速: {u[:20]}...", unit="link", ncols=80, leave=False):
                    speeds.append(f.result())
                
                for i, s in enumerate(speeds):
                    item = all_raw_items[i]
                    if s < 5.0:
                        count_online += 1
                        upper_name = item['name'].upper()
                        is_black = any(b in upper_name for b in BLOCK_KEYWORDS)
                        is_white = any(k in upper_name for k in KEYWORDS)
                        
                        if is_black:
                            count_black += 1
                            black_detail_names.append(item['name'])
                        elif is_white:
                            count_white += 1
                            item['speed'] = s
                            born_list.append(item)

        status = "✅" if born_list else "💀"
        logging.info(f"{status} 報告: {u}")
        logging.info(f"   ┣ [源頭掃描] 總台數: {count_total}")
        logging.info(f"   ┣ [網絡狀況] 連通數: {count_online} | 唔通數: {count_total - count_online}")
        logging.info(f"   ┗ [內容過濾] 中白名單: {count_white} (採納) | 中黑名單: {count_black} (剔除)")
        
        if black_detail_names:
            logging.info("   ┗ [🚫 黑名單細節]:")
            for i in range(0, len(black_detail_names), 5):
                chunk = black_detail_names[i:i+5]
                logging.info(f"      {', '.join(chunk)}")

        return born_list, len(born_list) > 0

    except Exception as e:
        logging.info(f"❌ 錯誤: {u} ({e})")
        return [], False

# --- 【4. 主流程】 ---
def main():
    RAW_SOURCES = load_sources("sources.txt")
    if not RAW_SOURCES:
        logging.warning("⚠️ 無源可讀")
        return

    all_channels = []
    current_urls = list(dict.fromkeys(RAW_SOURCES))
    
    logging.info("=" * 65)
    logging.info(f"📅 更新時間：{update_time} | 模式：{RUN_MODE}")
    logging.info("=" * 65)

    for url in current_urls:
        data, is_alive = diagnose_report(url)
        if is_alive: all_channels.extend(data)

    if not all_channels:
        logging.error("❌ 全軍覆沒")
        return

    channel_groups = {}
    for item in sorted(all_channels, key=lambda x: x['speed']):
        if item['name'] not in channel_groups:
            channel_groups[item['name']] = []
        if item['url'] not in [x['url'] for x in channel_groups[item['name']]]:
            channel_groups[item['name']].append(item)

    with open("hk_live.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write(f'#EXTINF:-1 group-title="最後更新", 🔄 {update_time} ({RUN_MODE})\nhttp://127.0.0.1/time.mp4\n')
        for target in ["廣東", "香港", "台灣", "澳門", "特色", "其他"]:
            for name, items in channel_groups.items():
                if get_group(name) == target:
                    for line in items:
                        f.write(f'#EXTINF:-1 group-title="{target}" tvg-name="{name}", {name}\n{line["url"]}\n')

    logging.info("-" * 65)
    logging.info(f"🏁 完工！共處理 {len(channel_groups)} 個頻道")

if __name__ == "__main__":
    main()
