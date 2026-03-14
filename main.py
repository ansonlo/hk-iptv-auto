import requests, datetime, time, logging, re, sys, os, urllib3
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# --- 【1. 初始化工具】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
cc = OpenCC('s2t')

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

# --- 【2. 核心配置】 ---
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

BLOCK_KEYWORDS = ["FOX", "UHD", "8K", "浙江", "杭州", "深圳", "延时", "測試", "購物", "福建", "江蘇", "湖南", "湖北"]

# 💡 中國特色源關鍵字 (不測速直接保留)
INTERNAL_DOMAINS = ['chinamobile.com', 'cmvideo.cn', 'unicom', 'telecom', 'ottrrs', 'dbiptv', '10.255.', '172.16.']

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

# --- 【工具函數】 ---
def load_sources(file_path="sources.txt"):
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
    try:
        start = time.time()
        r = session.get(url, timeout=1.5, headers=HEADERS, stream=True, verify=False)
        if r.status_code < 400: return time.time() - start
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

# --- 【3. 診斷報告函數】 ---
def diagnose_report(u):
    count_total = 0
    count_online = 0
    count_white = 0
    count_black = 0
    all_raw_items = []
    born_list = []
    black_detail_names = []

    try:
        r = session.get(u, timeout=25, headers=HEADERS, verify=False) # 下載源列表
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

        if all_raw_items:
            test_items = []    # 海外環境需要測速的
            special_items = [] # 中國特色源 (直接過)

            for x in all_raw_items:
                # 判斷係咪內網/特色源
                if any(domain in x['url'].lower() for domain in INTERNAL_DOMAINS):
                    x['speed'] = 1.0  # 給予預設速度
                    special_items.append(x)
                else:
                    test_items.append(x)

            # 💡 只有 test_items 入 ThreadPool 測速
            speeds = []
            if test_items:
                with ThreadPoolExecutor(max_workers=50) as ex:
                    futures = [ex.submit(get_speed, x['url']) for x in test_items]
                    for f in tqdm(futures, desc=f"⚡ 測速: {u[:15]}...", unit="link", ncols=80, leave=False):
                        speeds.append(f.result())

            # 處理測速結果
            for i, s in enumerate(speeds):
                item = test_items[i]
                if s < 5.0:
                    count_online += 1
                    upper_name = item['name'].upper()
                    if any(b in upper_name for b in BLOCK_KEYWORDS):
                        count_black += 1
                        black_detail_names.append(item['name'])
                    elif any(k in upper_name for k in KEYWORDS):
                        count_white += 1
                        item['speed'] = s
                        born_list.append(item)
            
            # 💡 處理直接放行的特殊源
            for item in special_items:
                upper_name = item['name'].upper()
                if any(k in upper_name for k in KEYWORDS) and not any(b in upper_name for b in BLOCK_KEYWORDS):
                    count_white += 1
                    born_list.append(item)

        # 報告輸出
        status = "✅" if born_list else "💀"
        logging.info(f"{status} 報告: {u} | 採納: {len(born_list)} | 跳過內網: {len(special_items)}")
        return born_list, len(born_list) > 0

    except Exception as e:
        logging.info(f"❌ 錯誤: {u} ({e})")
        return [], False

# --- 【4. 主流程】 ---
def main():
    RAW_SOURCES = load_sources("sources.txt")
    if not RAW_SOURCES: return

    all_channels = []
    current_urls = list(dict.fromkeys(RAW_SOURCES))
    
    for url in current_urls:
        data, is_alive = diagnose_report(url)
        if is_alive: all_channels.extend(data)

    if not all_channels: return

    # 去重與排序
    channel_groups = {}
    for item in sorted(all_channels, key=lambda x: x['speed']):
        if item['name'] not in channel_groups:
            channel_groups[item['name']] = []
        if item['url'] not in [x['url'] for x in channel_groups[item['name']]]:
            channel_groups[item['name']].append(item)

    # 寫入輸出 A: 自己睇嘅 hk_live.m3u
    with open("hk_live.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write(f'#EXTINF:-1 group-title="最後更新", 🔄 {update_time}\nhttp://127.0.0.1/time.mp4\n')
        for target in ["廣東", "香港", "台灣", "澳門", "特色", "其他"]:
            for name, items in channel_groups.items():
                if get_group(name) == target:
                    for line in items:
                        f.write(f'#EXTINF:-1 group-title="{target}" tvg-name="{name}", {name}\n{line["url"]}\n')

    # 寫入輸出 B: 畀廣州朋友用嘅 user_result.m3u (全量精選)
    with open("user_result.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, items in channel_groups.items():
            for line in items:
                f.write(f'#EXTINF:-1, {name}\n{line["url"]}\n')

    logging.info(f"🏁 完工！已生成 hk_live.m3u 及 user_result.m3u")

if __name__ == "__main__":
    main()
