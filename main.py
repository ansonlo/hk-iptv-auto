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

# 中國特色源關鍵字 (不測速直接保留)
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
    is_internal = any(domain in url.lower() for domain in INTERNAL_DOMAINS) or "CCTV" in url.upper()
    current_timeout = 1.5 if is_internal else 2.5
    
    for i in range(2):
        try:
            start = time.time()
            r = session.get(url, timeout=current_timeout, headers=HEADERS, stream=True, verify=False)
            if r.status_code < 400:
                return time.time() - start
        except Exception:
            if i == 0:
                time.sleep(0.5)
            continue
    return 999

def get_group(name):
    check_name = name.upper().replace(" ", "")
    if "CCTV" in check_name: return "特色"
    if any(x in name for x in ["翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線", "有線", "J2", "J5", "鳳凰"]): return "香港"
    if any(x in name for x in ["東森", "三立", "中視", "公視", "TVBS", "緯來", "民視", "年代", "中天", "非凡", "台視"]): return "台灣"
    if any(x in name for x in ["廣東", "珠江", "廣州", "大灣區", "南方", "深圳"]): return "廣東"
    if any(x in name for x in ["澳視", "澳門", "TDM", "澳亞"]): return "澳門"
    return "其他"

def clean_name(raw_name):
    name = cc.convert(raw_name).replace('臺', '台').upper().strip()
    name = re.sub(r'\[.*?\]|\(.*?\)|\（.*?\）', '', name)
    suffixes = ["超清", "高清", "藍光", "標清", "頻道", "1080P", "720P", "4K", "HD", "SD", "FHD", "BD"]
    for s in suffixes:
        name = name.replace(s, "")
    return name.strip("-").strip("_").strip()

def diagnose_report(u):
    all_raw_items = []
    born_list = []
    try:
        r = session.get(u, timeout=25, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return [], False
        
        current_name = ""
        for line in r.text.split('\n'):
            line = line.strip()
            if line.startswith("#EXTINF"):
                raw_name = line.split(',')[-1]
                current_name = clean_name(raw_name)
            elif line.startswith("http") and current_name:
                raw_url = line.split('$')[0].strip()
                all_raw_items.append({'name': current_name, 'url': raw_url})
                current_name = ""

        if not all_raw_items: return [], False

        test_items = []
        special_items = []
        for x in all_raw_items:
            if any(domain in x['url'].lower() for domain in INTERNAL_DOMAINS):
                x['speed'] = 1.0
                special_items.append(x)
            else:
                test_items.append(x)

        if test_items:
            with ThreadPoolExecutor(max_workers=50) as ex:
                futures = {ex.submit(get_speed, x['url']): x for x in test_items}
                for f in tqdm(list(futures.keys()), desc=f"⚡ 測速: {u[:15]}...", unit="link", ncols=80, leave=False):
                    speed = f.result()
                    item = futures[f]
                    if speed < 5.0:
                        item['speed'] = speed
                        upper_name = item['name'].upper()
                        if any(k in upper_name for k in KEYWORDS) and not any(b in upper_name for b in BLOCK_KEYWORDS):
                            born_list.append(item)

        for item in special_items:
            upper_name = item['name'].upper()
            if any(k in upper_name for k in KEYWORDS) and not any(b in upper_name for b in BLOCK_KEYWORDS):
                born_list.append(item)

        return born_list, len(born_list) > 0
    except Exception as e:
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

    # --- 💡 寫入前獲取最新完工時間 ---
    final_finish_time = datetime.datetime.now().strftime("%m%d %H:%M")

    # 去重與排序
    channel_groups = {}
    for item in sorted(all_channels, key=lambda x: x['speed']):
        name = item['name']
        url = item['url']
        base_url = url.split('?')[0].split('#')[0].strip()
        if name not in channel_groups:
            channel_groups[name] = []
        existing_urls = [x['url'].split('?')[0] for x in channel_groups[name]]
        if base_url not in existing_urls:
            channel_groups[name].append(item)

    # 寫入輸出 A: hk_live.m3u (你自己用嘅總表)
    with open("hk_live.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        # 標題標籤，設為 "總表更新" 以便同 gz 分流腳本隔離
        f.write(f'#EXTINF:-1 group-title="最後更新" tvg-name="總表更新", 更：{final_finish_time}\n')
        f.write(f'http://10.255.255.1/info.ts\n')
        
        sort_order = ["廣東", "香港", "台灣", "澳門", "特色", "其他"]
        for target in sort_order:
            for name, items in channel_groups.items():
                if get_group(name) == target:
                    # 自動匹配 Logo
                    logo_url = f"https://raw.githubusercontent.com/FanMingming/live/main/tv/logo/{name}.png"
                    
                    for line in items:
                        # 🌟 徹底過濾：唔要時間標籤同埋你自己唔用嘅功能台
                        if any(x in name for x in ["更", "更新", "偽", "查我IP"]):
                            continue
                            
                        display_name = name
                        # 🌟 IPv6 識別標籤
                        if "[" in line["url"] and "]" in line["url"]:
                            display_name = f"{name} [V6]"
                        
                        f.write(f'#EXTINF:-1 group-title="{target}" tvg-name="{name}" tvg-logo="{logo_url}", {display_name}\n{line["url"]}\n')

    # 寫入輸出 B: user_result.m3u (簡潔版)
    with open("user_result.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, items in channel_groups.items():
            if any(x in name for x in ["更", "更新", "偽", "查我IP"]):
                continue
            for line in items:
                d_name = name
                if "[" in line["url"] and "]" in line["url"]:
                    d_name = f"{name} [V6]"
                f.write(f'#EXTINF:-1, {d_name}\n{line["url"]}\n')

    logging.info(f"🏁 完工！hk_live.m3u 已生成。時間：{final_finish_time}")

if __name__ == "__main__":
    main()
