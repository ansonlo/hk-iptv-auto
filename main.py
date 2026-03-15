import requests, datetime, time, logging, re, sys, os, urllib3
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# --- 【1. 初始化工具】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
cc = OpenCC('s2t')

# 優化 Session 參數
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
session = requests.Session()
session.mount('http://', adapter)
session.mount('https://', adapter)

update_time = datetime.datetime.now().strftime("%m%d %H:%M")

# 🌟 設定追加日誌模式，並加入時間戳
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"), 
        logging.StreamHandler()
    ]
)

# 🌟 定義即時刷新函數
def log_info(msg):
    logging.info(msg)
    for handler in logging.getLogger().handlers:
        handler.flush()

# --- 【工具函數】 ---
def load_sources(file_path="sources.txt"):
    """從外部檔案讀取源網址"""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
                log_info(f"✅ [通用讀取] 已從 {file_path} 加載 {len(urls)} 個源")
                return urls
        except Exception as e:
            log_info(f"❌ [通用讀取] 錯誤: {e}")
    return []

def get_speed(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for _ in range(2): 
        try:
            start = time.time()
            with session.get(url, timeout=3.0, headers=headers, stream=True, verify=False) as r:
                if r.status_code < 400:
                    return time.time() - start
        except:
            time.sleep(0.5)
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

BLOCK_KEYWORDS = ["FOX", "UHD", "8K", "浙江", "杭州", "深圳", "延時", "測試", "購物", "福建", "江蘇", "湖南", "湖北"]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# --- 【3. 簡化版診斷函數 (只負責通用掃描) 】 ---
def diagnose_report(u):
    all_raw_items = []
    try:
        r = session.get(u, timeout=20, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return [], False
        
        name = ""
        for line in r.text.split('\n'):
            line = line.strip()
            if line.startswith("#EXTINF"):
                raw_name = cc.convert(line.split(',')[-1]).replace('臺', '台').strip()
                name = re.sub(r'\[.*?\]', '', raw_name).strip()
            elif line.startswith("http") and name:
                all_raw_items.append({'name': name, 'url': line.split('$')[0].strip()})
                name = ""

        born_list = []
        if all_raw_items:
            with ThreadPoolExecutor(max_workers=100) as ex:
                futures = [ex.submit(get_speed, x['url']) for x in all_raw_items]
                speeds = [f.result() for f in tqdm(futures, desc=f"⚡ 測速中...", unit="link", ncols=80, leave=False)]
                
                for i, s in enumerate(speeds):
                    item = all_raw_items[i]
                    if s < 5.0:
                        upper_name = item['name'].upper()
                        if not any(b in upper_name for b in BLOCK_KEYWORDS):
                            if any(k in upper_name for k in KEYWORDS):
                                item['speed'] = s
                                born_list.append(item)

        # 🌟 簡潔輸出，唔好重疊診斷細節
        status = "✅" if born_list else "💀"
        log_info(f"[{status}] 通用源掃描: {u} (獲取 {len(born_list)} 個有效台)")

        return born_list, len(born_list) > 0
    except Exception as e:
        log_info(f"❌ 通用源失敗: {u} ({e})")
        return [], False

# --- 【4. 主流程】 ---
def main():
    log_info("\n" + "="*20 + " 2. 開始執行 main.py (通用自用版) " + "="*20)
    
    RAW_SOURCES = load_sources("sources.txt")
    if not RAW_SOURCES:
        log_info("⚠️ 無源可讀")
        return

    all_channels = []
    current_urls = list(dict.fromkeys(RAW_SOURCES))
    
    for url in current_urls:
        data, is_alive = diagnose_report(url)
        if is_alive: all_channels.extend(data)

    if not all_channels:
        log_info("❌ 全軍覆沒，無法更新 hk_live.m3u")
        return

    # 按速度排序去重，每個台最多攞 5 條線路
    channel_groups = {}
    for item in sorted(all_channels, key=lambda x: x['speed']):
        if item['name'] not in channel_groups:
            channel_groups[item['name']] = []
        if item['url'] not in [x['url'] for x in channel_groups[item['name']]]:
            if len(channel_groups[item['name']]) < 5:
                channel_groups[item['name']].append(item)

    # 寫入 M3U (hk_live.m3u)
    with open("hk_live.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write(f'#EXTINF:-1 group-title="最後更新", 更{update_time}\nhttp://127.0.0.1/time.mp4\n')
        
        for target in ["廣東", "香港", "台灣", "澳門", "特色", "其他"]:
            for name in sorted(channel_groups.keys()):
                if get_group(name) == target:
                    for line in channel_groups[name]:
                        f.write(f'#EXTINF:-1 group-title="{target}" tvg-name="{name}", {name}\n{line["url"]}\n')

    log_info(f"🏁 main.py 完工！精選 {len(channel_groups)} 個頻道，共 {sum(len(v) for v in channel_groups.values())} 條線路")

if __name__ == "__main__":
    main()
