import requests, datetime, time, logging, re, os, urllib3, random
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 初始化工具與統一日誌設定】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
cc = OpenCC('s2t')
adapter = requests.adapters.HTTPAdapter(pool_connections=200, pool_maxsize=200)

# 🌟 統一日誌設定：作為第一份腳本，使用 mode='w' 清空舊紀錄
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("auto_repair.log", mode='w', encoding="utf-8"), 
        logging.StreamHandler()
    ]
)

# 🌟 強制刷新函數，確保 GitHub Actions 即時噴出 Log，唔會堆埋一齊
def log_info(msg):
    logging.info(msg)
    for handler in logging.getLogger().handlers:
        handler.flush()

KEYWORDS = ["廣州", "珠江", "廣東", "大灣區", "南方", "深圳", "翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線", "鳳凰", "澳視", "澳門", "TDM", "澳亞", "CCTV", "台灣", "TVBS", "三立"]
BLOCK_KEYWORDS = ["*SG", "REDIRECT", "酒店", "TEST", "測試", "購物", "延時", "8K", "UHD"]

FEATURES = {
    "移动": ["120.196.", "120.197.", "183.232.", "183.235.", "gdmcc", "2409:"], 
    "电信": ["gdct", "113.108.", "125.88.", "14.215.", "240e:"],
    "联通": ["gdcu", "121.32.", "121.33.", "2408:"],
    "广电": ["gdtv", "guangdong", "240a:"]
}

# --- 【2. 工具函數】 ---

def clean_name(raw_name):
    if any(x in raw_name for x in ["更", "📅"]): return raw_name.strip()
    name = cc.convert(raw_name).replace('臺', '台').upper().strip()
    name = re.sub(r'\[.*?\]|\(.*?\)|\（.*?\）', '', name)
    suffixes = ["超清", "高清", "藍光", "標清", "頻道", "1080P", "720P", "4K", "HD", "SD", "FHD", "BD"]
    for s in suffixes: name = name.replace(s, "")
    return name.strip("-").strip("_").strip()

def get_speed(url, custom_headers, current_session): 
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

# --- 【3. IP 池與偽裝邏輯】 ---

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
        except Exception as e: log_info(f"⚠️ 讀取 IP_Pool 錯誤: {e}")
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

# --- 【4. 核心診斷與測速】 ---

def diagnostic_and_test(source_list, ip_cache):
    test_session = requests.Session()
    test_session.mount('http://', adapter)
    test_session.mount('https://', adapter)
    
    source_stats = {u: {"移动": 0, "电信": 0, "联通": 0, "广电": 0, "通用": 0, "total": 0} for u in source_list}
    provider_items = {"移动": [], "电信": [], "联通": [], "广电": []}

    # 專線模式診斷
    for p in ["移动", "电信", "联通", "广电"]:
        headers, mask = get_headers_with_mask(p, ip_cache)
        log_info(f"🛰️ 診斷中: 【{p}】專線模式 (Mask: {mask})...")
        
        for u in source_list:
            try:
                r = test_session.get(u, timeout=10, headers=headers, verify=False)
                r.encoding = 'utf-8'
                name, raw_items = "", []
                for line in r.text.splitlines():
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
                            item, s = futures[f], f.result()
                            if s < 5.0:
                                if any(k in item['name'].upper() for k in KEYWORDS):
                                    feat_list = FEATURES.get(p, [])
                                    final_s = s - 10.0 if any(ft in item['url'].lower() for ft in feat_list) else s
                                    new_item = item.copy()
                                    new_item['speed'] = final_s
                                    provider_items[p].append(new_item)
                                    source_stats[u][p] += 1
            except: continue

    # 通用模式診斷
    log_info(f"🌐 診斷中: 【通用模式】直連測試...")
    normal_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for u in source_list:
        try:
            r = test_session.get(u, timeout=5, headers=normal_headers, verify=False)
            urls = [l for l in r.text.splitlines() if l.startswith("http")]
            if urls:
                with ThreadPoolExecutor(max_workers=40) as ex:
                    futures = [ex.submit(get_speed, url, normal_headers, test_session) for url in urls[:20]]
                    source_stats[u]["通用"] = sum(1 for f in futures if f.result() < 5.0)
        except: continue

    log_info("\n📊 --- 【直播源五線連通性終極報告】 ---")
    for u, stat in source_stats.items():
        log_info(f"源: {u}")
        log_info(f"┗ 總量: {stat['total']} | 移动: {stat['移动']} | 电信: {stat['电信']} | 联通: {stat['联通']} | 广电: {stat['广电']} | 通用: {stat['通用']}")
    log_info("-" * 65)
    return provider_items

# --- 【5. 主流程】 ---

def main():
    log_info("\n" + "="*25 + " 廣州專線 & 五線診斷啟動 " + "="*25)
    
    ip_cache = load_ip_pool()
    sources = []
    if os.path.exists("sources.txt"):
        with open("sources.txt", "r", encoding="utf-8") as f:
            sources = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    if not sources: 
        log_info("❌ 無法讀取 sources.txt")
        return

    all_provider_final_data = diagnostic_and_test(sources, ip_cache)
    update_time = datetime.datetime.now().strftime("%m%d %H:%M")
    
    files_map = {
        "移动": ("gz_live.m3u", "廣州移動"), "电信": ("gz_dxlive.m3u", "廣州電訊"), 
        "联通": ("gz_ltlive.m3u", "廣州聯通"), "广电": ("gz_gdlive.m3u", "廣州廣電")
    }
    
    valid_providers = {k: v for k, v in all_provider_final_data.items() if v}
    best_p_key = max(valid_providers, key=lambda k: len(valid_providers[k])) if valid_providers else None

    for provider, (filename, desc) in files_map.items():
        current_data = all_provider_final_data.get(provider, [])
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f'#EXTM3U x-tvg-url="https://epg.112114.xyz/pp.xml"\n')
                f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="更新", 📅 更新：{update_time}\nhttp://10.255.255.1/info.ts\n')
                
                for target_group in ["廣東", "香港", "澳門", "台灣", "特色", "其他"]:
                    group_items = [i for i in current_data if get_group(i["name"]) == target_group]
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
            log_info(f"💾 產出完成: {filename}")
        except Exception as e: log_info(f"❌ 寫入錯誤 {filename}: {e}")
    
    log_info("🏁 廣州診斷任務結束！")

if __name__ == "__main__":
    main()
