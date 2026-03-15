import requests, datetime, time, logging, re, os, urllib3, random
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# --- 【1. 初始化工具】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
cc = OpenCC('s2t')
adapter = requests.adapters.HTTPAdapter(pool_connections=200, pool_maxsize=200)

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.FileHandler("gz_repair.log", mode='w', encoding="utf-8"), 
        logging.StreamHandler()
    ]
)

KEYWORDS = ["廣州", "珠江", "廣東", "大灣區", "南方", "深圳", "翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線", "鳳凰", "澳視", "澳門", "TDM", "澳亞", "CCTV", "台灣", "TVBS", "三立"]
BLOCK_KEYWORDS = ["*SG", "REDIRECT", "酒店", "TEST", "測試", "購物", "延時", "8K", "UHD"]

FEATURES = {
    "移动": ["120.196.", "120.197.", "183.232.", "183.235.", "gdmcc", "2409:"], 
    "电信": ["gdct", "113.108.", "125.88.", "14.215.", "240e:"],
    "联通": ["gdcu", "121.32.", "121.33.", "2408:"],
    "广电": ["gdtv", "guangdong", "240a:"]
}

# --- 【2. 強化版工具函數】 ---

def clean_name(raw_name):
    if any(x in raw_name for x in ["更", "📅"]): return raw_name.strip()
    name = cc.convert(raw_name).replace('臺', '台').upper().strip()
    name = re.sub(r'\[.*?\]|\(.*?\)|\（.*?\）', '', name)
    suffixes = ["超清", "高清", "藍光", "標清", "頻道", "1080P", "720P", "4K", "HD", "SD", "FHD", "BD"]
    for s in suffixes: name = name.replace(s, "")
    return name.strip("-").strip("_").strip()

def get_speed(url, custom_headers, current_session): 
    # 隨機 UA 模擬真實設備
    custom_headers['User-Agent'] = random.choice([
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Linux; Android 11; Pixel 5)',
        'OTT-Player/1.1'
    ])
    for i in range(2):
        try:
            start = time.time()
            with current_session.get(url, timeout=2.0, headers=custom_headers, stream=True, verify=False) as r:
                if r.status_code < 400: return time.time() - start
        except:
            if i == 0: time.sleep(0.3)
            continue
    return 999

def get_group(name):
    check_name = name.upper()
    if any(x in check_name for x in ["廣東", "珠江", "廣州", "大灣區", "南方", "深圳"]): return "廣東"
    if any(x in check_name for x in ["翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線"]): return "香港"
    if any(x in check_name for x in ["東森", "三立", "中視", "公視", "TVBS", "緯來"]): return "台灣"
    if any(x in check_name for x in ["澳視", "澳門", "TDM", "澳亞"]): return "澳門"
    if "CCTV" in check_name: return "特色"
    return "其他"

# --- 【3. IP 池與面具邏輯】 ---

def load_ip_pool(file_name="IP_Pool.txt"):
    cache = {}
    if os.path.exists(file_name):
        try:
            with open(file_name, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip().replace("，", ",")
                    if not line or line.startswith("#"): continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) > 1: cache[parts[0]] = [ip for ip in parts[1:] if ip]
        except Exception as e: logging.info(f"⚠️ 讀取 IP_Pool 出錯: {e}")
    return cache

def get_headers_with_mask(provider_name, pool_cache):
    headers = {'User-Agent': 'Mozilla/5.0 (Linux; Android 10; Mobile) IPTV/1.0'}
    import ipaddress
    name_map = {"移动": ["移动", "移動"], "电信": ["电信", "電信"], "联通": ["联通", "聯通"], "广电": ["广电", "廣電"]}
    target_names = name_map.get(provider_name, [provider_name])
    raw_ip_list = []
    for name in target_names:
        if name in pool_cache: raw_ip_list.extend(pool_cache[name])
    if not raw_ip_list: return headers, None
    choice = random.choice(raw_ip_list)
    mask_ip = choice
    if "/" in choice:
        try:
            net = ipaddress.ip_network(choice, strict=False)
            mask_ip = str(net.network_address + random.randint(1, net.num_addresses - 2))
        except: mask_ip = choice.split('/')[0]
    headers.update({'X-Forwarded-For': mask_ip, 'X-Real-IP': mask_ip, 'Client-IP': mask_ip})
    return headers, mask_ip

# --- 【4. 核心診斷流程 (五線連通性)】 ---

def diagnostic_and_test(source_list, ip_cache):
    test_session = requests.Session()
    test_session.mount('http://', adapter)
    test_session.mount('https://', adapter)
    
    # 統計表
    source_stats = {u: {"移动": 0, "电信": 0, "联通": 0, "广电": 0, "通用": 0, "total": 0} for u in source_list}
    provider_items = {"移动": [], "电信": [], "联通": [], "广电": []}

    # A. 專線面具測試
    for p in ["移动", "电信", "联通", "广电"]:
        headers, mask = get_headers_with_mask(p, ip_cache)
        logging.info(f"🛰️ 診斷中: 【{p}】專線模式...")
        
        for u in source_list:
            try:
                r = test_session.get(u, timeout=10, headers=headers, verify=False)
                r.encoding = 'utf-8'
                lines = r.text.splitlines()
                
                name, raw_items = "", []
                for line in lines:
                    line = line.strip()
                    if line.startswith("#EXTINF"): name = clean_name(line.split(',')[-1])
                    elif line.startswith("http") and name:
                        raw_items.append({'name': name, 'url': line.split('$')[0].strip()})
                        name = ""
                
                if raw_items:
                    source_stats[u]["total"] = len(raw_items)
                    with ThreadPoolExecutor(max_workers=100) as ex:
                        futures = {ex.submit(get_speed, x['url'], headers, test_session): x for x in raw_items}
                        for f in futures:
                            item = futures[f]
                            s = f.result()
                            if s < 5.0:
                                # 中關鍵字才存入 M3U 數據
                                if any(k in item['name'].upper() for k in KEYWORDS):
                                    # 權重優化
                                    feat_list = FEATURES.get(p, [])
                                    final_s = s - 10.0 if any(ft.lower() in item['url'].lower() for ft in feat_list) else s
                                    new_item = item.copy()
                                    new_item['speed'] = final_s
                                    provider_items[p].append(new_item)
                                    source_stats[u][p] += 1
            except: continue

    # B. 通用模式測試 (不戴面具)
    logging.info(f"🌐 診斷中: 【通用模式】測試...")
    normal_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for u in source_list:
        try:
            r = test_session.get(u, timeout=5, headers=normal_headers, verify=False)
            urls = [l for l in r.text.splitlines() if l.startswith("http")]
            if urls:
                # 抽樣 20 條測連通性
                with ThreadPoolExecutor(max_workers=40) as ex:
                    futures = [ex.submit(get_speed, url, normal_headers, test_session) for url in urls[:20]]
                    source_stats[u]["通用"] = sum(1 for f in futures if f.result() < 5.0)
        except: continue

    # 📝 輸出你想要嘅「終極報告」
    logging.info("\n📊 --- 【直播源五線連通性終極報告】 ---")
    for u, stat in source_stats.items():
        logging.info(f"源: {u}")
        logging.info(f"┗ 總量: {stat['total']} | 移动: {stat['移动']} | 电信: {stat['电信']} | 联通: {stat['联通']} | 广电: {stat['广电']} | 通用: {stat['通用']}")
    logging.info("-" * 65)
    
    return provider_items

# --- 【5. 主流程】 ---

def main():
    ip_cache = load_ip_pool()
    sources = []
    if os.path.exists("sources.txt"):
        with open("sources.txt", "r", encoding="utf-8") as f:
            sources = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    if not sources: 
        logging.error("❌ 找不到 sources.txt")
        return

    # 執行診斷與統計
    all_provider_final_data = diagnostic_and_test(sources, ip_cache)

    update_time = datetime.datetime.now().strftime("%m%d %H:%M")
    files_map = {
        "移动": ("gz_live.m3u", "廣州移動"), "电信": ("gz_dxlive.m3u", "廣州電訊"), 
        "联通": ("gz_ltlive.m3u", "廣州聯通"), "广电": ("gz_gdlive.m3u", "廣州廣電")
    }
    
    # 借用機制：搵出最好嘅 ISP 做備選
    valid_providers = {k: v for k, v in all_provider_final_data.items() if v}
    best_p_key = max(valid_providers, key=lambda k: len(valid_providers[k])) if valid_providers else None

    for provider, (filename, desc) in files_map.items():
        current_data = all_provider_final_data.get(provider, [])
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f'#EXTM3U x-tvg-url="https://epg.112114.xyz/pp.xml"\n')
                # 時間標籤歸類入 ISP 分組
                f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="更新", 📅 更新：{update_time}\nhttp://10.255.255.1/info.ts\n')
                
                for target_group in ["廣東", "香港", "澳門", "台灣", "特色", "其他"]:
                    group_items = [i for i in current_data if get_group(i["name"]) == target_group]
                    
                    # 借用補償 (如果本 ISP 冇呢個組，就去最好嗰個 ISP 借)
                    if not group_items and best_p_key and provider != best_p_key:
                        group_items = [i for i in all_provider_final_data[best_p_key] if get_group(i["name"]) == target_group]
                    
                    group_items.sort(key=lambda x: x.get('speed', 999))
                    
                    seen_urls, channel_count = set(), {}
                    for item in group_items:
                        if item['url'] not in seen_urls:
                            channel_count[item['name']] = channel_count.get(item['name'], 0) + 1
                            if channel_count[item['name']] <= 8:
                                f.write(f'#EXTINF:-1 group-title="{target_group}" tvg-name="{item["name"]}", {item["name"]}\n{item["url"]}\n')
                                seen_urls.add(item['url'])
            logging.info(f"💾 產出完成: {filename}")
        except Exception as e: logging.error(f"❌ 寫入錯誤 {filename}: {e}")

if __name__ == "__main__":
    main()
