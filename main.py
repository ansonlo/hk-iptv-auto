import requests, datetime, time, logging, re, sys, os, urllib3
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# --- 【1. 初始化工具】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
cc = OpenCC('s2t')

# 優化 Session 參數，增加連線池大小
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
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
    """從外部檔案讀取源網址"""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
                logging.info(f"✅ [數據讀取] 已從 {file_path} 加載 {len(urls)} 個源")
                return urls
        except Exception as e:
            logging.error(f"❌ [數據讀取] 錯誤: {e}")
    return []

def get_speed(url):
    """優化 1：快速測速邏輯 (使用 stream=True 攞到 Header 即停)"""
    try:
        start = time.time()
        # 唔需要下載成個 TS 檔案，只要對方 Server 有回應（Header）就計算延遲
        with session.get(url, timeout=1.5, headers=HEADERS, stream=True, verify=False) as r:
            if r.status_code < 400:
                return time.time() - start
    except:
        pass
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
            # 增加測速線程到 100，速度更快
            with ThreadPoolExecutor(max_workers=100) as ex:
                futures = [ex.submit(get_speed, x['url']) for x in all_raw_items]
                speeds = []
                for f in tqdm(futures, desc=f"⚡ 測速中...", unit="link", ncols=80, leave=False):
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

        # 輸出詳細報告
        status = "✅" if born_list else "💀"
        logging.info(f"\n{status} 報告: {u}")
        logging.info(f"   ┣ [源頭掃描] 總台數: {count_total}")
        logging.info(f"   ┣ [網絡狀況] 連通數: {count_online} | 唔通數: {count_total - count_online}")
        logging.info(f"   ┗ [內容過濾] 中白名單: {count_white} (採納) | 中黑名單: {count_black} (剔除)")
        
        if black_detail_names:
            logging.info("   ┗ [🚫 黑名單細節]:")
            for i in range(0, min(len(black_detail_names), 40), 5):
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
    logging.info(f"📅 更新時間：{update_time}")
    logging.info("=" * 65)

    for url in current_urls:
        data, is_alive = diagnose_report(url)
        if is_alive: all_channels.extend(data)

    if not all_channels:
        logging.error("❌ 全軍覆沒")
        return

    # 優化 2：數據精簡與去重
    channel_groups = {}
    # 先按速度排序，確保之後攞親嘅頭 5 條都係最快嘅
    for item in sorted(all_channels, key=lambda x: x['speed']):
        if item['name'] not in channel_groups:
            channel_groups[item['name']] = []
        
        # 檢查 URL 是否重複，並且每個台最多留 5 條線路
        if item['url'] not in [x['url'] for x in channel_groups[item['name']]]:
            if len(channel_groups[item['name']]) < 5:
                channel_groups[item['name']].append(item)

    # 寫入 M3U
    with open("hk_live.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        # 標記最後更新時間，方便喺播放器入面睇
        f.write(f'#EXTINF:-1 group-title="最後更新", 更{update_time}\nhttp://127.0.0.1/time.mp4\n')
        
        for target in ["廣東", "香港", "台灣", "澳門", "特色", "其他"]:
            for name in channel_groups:
                if get_group(name) == target:
                    items = channel_groups[name]
                    for line in items:
                        # 保持頻道名純淨，實現播放器自動合併線路
                        f.write(f'#EXTINF:-1 group-title="{target}" tvg-name="{name}", {name}\n{line["url"]}\n')

    logging.info("-" * 65)
    logging.info(f"🏁 完工！精選 {len(channel_groups)} 個頻道，共 {sum(len(v) for v in channel_groups.values())} 條優質線路")

if __name__ == "__main__":
    main()
