import requests, datetime, time, logging, re, sys, os, urllib3, random, json
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# --- 【1. 初始化與模式偵測】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
cc = OpenCC('s2t')
adapter = requests.adapters.HTTPAdapter(pool_connections=200, pool_maxsize=200)

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"), 
        logging.StreamHandler()
    ]
)

# 偵測 GitHub Actions 觸發事件 MANUAL_ONLY
GITHUB_EVENT = os.getenv('GITHUB_EVENT_NAME', 'local')
if GITHUB_EVENT == 'workflow_dispatch':
    RUN_MODE = "FULL_SCAN"   
    logging.info(">>> 偵測到手動撳制：啟動 MANUAL_ONLY 模式 <<<")
else:
    RUN_MODE = "FULL_SCAN"
    logging.info(">>> 偵測到定時任務：啟動 FULL_SCAN 模式 (全量掃描) <<<")

# 配置與過濾關鍵字
KEYWORDS = ["廣州", "珠江", "廣東", "大灣區", "南方", "深圳", "翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線", "鳳凰", "澳視", "澳門", "TDM", "CCTV", "台灣", "TVBS", "三立"]
BLOCK_KEYWORDS = ["*SG", "redirect", "酒店", "TEST", "測試", "購物", "延時", "8K", "UHD"]

FEATURES = {
    "移动": ["120.196.", "120.197.", "183.232.", "183.235.", "gdmcc", "2409:"], 
    "电信": ["gdct", "113.108.", "125.88.", "14.215.", "240e:"],
    "联通": ["gdcu", "121.32.", "121.33.", "2408:"],
    "广电": ["gdtv", "guangdong", "240a:"]
}

# --- 【2. 工具函數】 ---

def load_sources(file_path="sources.txt"):
    """
    🌟 精確範圍控制加載：
    - MANUAL_ONLY: 只掃描 # MY MANUAL SOURCES 到 # --- AUTO DISCOVERED... 之間
    - FULL_SCAN: 掃描全份文件（排除註釋行）
    """
    if not os.path.exists(file_path):
        return []
    
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if RUN_MODE == "MANUAL_ONLY":
        manual_urls = []
        is_capture_zone = False
        for line in lines:
            line = line.strip()
            # 1. 定義起點
            if "# MY MANUAL SOURCES" in line.upper():
                is_capture_zone = True
                continue
            # 2. 定義終點
            if "# --- AUTO DISCOVERED SOURCES ---" in line.upper():
                is_capture_zone = False
                break
            # 3. 區間內提取 URL
            if is_capture_zone and line.startswith("http"):
                clean_url = line.split('#')[0].split('$')[0].strip()
                if clean_url: manual_urls.append(clean_url)
        logging.info(f"🚀 [手動模式] 鎖定測試區間，共加載 {len(manual_urls)} 個源")
        return manual_urls
    else:
        all_urls = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        logging.info(f"📅 [定時模式] 全量加載 {len(all_urls)} 個源")
        return all_urls

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
        except: pass
    return cache

def get_mask_ip(provider_name, pool_cache):
    import ipaddress
    name_map = {"移动": ["移动", "移動"], "电信": ["电信", "電信"], "联通": ["联通", "聯通"], "广电": ["广电", "廣電"]}
    target_names = name_map.get(provider_name, [provider_name])
    raw_ip_list = []
    for name in target_names:
        if name in pool_cache: raw_ip_list.extend(pool_cache[name])
    if not raw_ip_list: return None
    choice = random.choice(raw_ip_list)
    if "/" in choice:
        try:
            net = ipaddress.ip_network(choice, strict=False)
            return str(net.network_address + random.randint(1, net.num_addresses - 2))
        except: return choice.split('/')[0]
    return choice

def get_headers_with_mask(provider_name, pool_cache):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    mask_ip = None
    if provider_name != "通用":
        mask_ip = get_mask_ip(provider_name, pool_cache)
        if mask_ip: headers.update({'X-Forwarded-For': mask_ip, 'X-Real-IP': mask_ip, 'Client-IP': mask_ip})
    return headers, mask_ip

def get_speed(url, custom_headers, current_session): 
    try:
        start = time.time()
        r = current_session.get(url, timeout=1.5, headers=custom_headers, stream=True, verify=False)
        if r.status_code < 400:
            content = b""
            for chunk in r.iter_content(chunk_size=1024):
                content += chunk
                if len(content) >= 1024 * 100: break
            return time.time() - start
    except: pass
    return 999

def get_group(name):
    check_name = name.upper().replace(" ", "")
    if any(x in check_name for x in ["廣東", "珠江", "廣州", "大灣區", "南方", "深圳"]): return "廣東"
    if any(x in check_name for x in ["翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線"]): return "香港"
    if any(x in check_name for x in ["東森", "三立", "中視", "公視", "TVBS", "緯來"]): return "台灣"
    if any(x in check_name for x in ["澳視", "澳門", "TDM", "澳亞"]): return "澳門"
    if "CCTV" in check_name: return "特色"
    return "其他"

def mark_source_as_deleted(url):
    """將失效源在 sources.txt 中註釋掉"""
    try:
        if os.path.exists("sources.txt"):
            with open("sources.txt", "r", encoding="utf-8") as f:
                lines = f.readlines()
            with open("sources.txt", "w", encoding="utf-8") as f:
                for line in lines:
                    if url.strip() in line and not line.strip().startswith("#"):
                        f.write(f"# {line}")
                    else: f.write(line)
            logging.info(f"✅ 已封印失效源: {url[:40]}...")
    except: pass

# --- 【3. 診斷與測試邏輯】 ---

def crawl_and_test(provider_name, source_list, ip_cache):
    test_session = requests.Session()
    test_session.mount('http://', adapter)
    test_session.mount('https://', adapter)
    current_headers, mask_ip = get_headers_with_mask(provider_name, ip_cache)
    
    if provider_name == "通用":
        for key in ['X-Forwarded-For', 'X-Real-IP', 'Client-IP']: current_headers.pop(key, None)

    provider_results = {}
    for u in source_list:
        summary = {'total': 0, 'online': 0, 'items': []}
        try:
            r = test_session.get(u, timeout=7, headers=current_headers, verify=False)
            r.encoding = 'utf-8'
            name, current_raw = "", []
            for line in r.text.splitlines():
                line = line.strip()
                if line.startswith("#EXTINF"):
                    summary['total'] += 1
                    parts = line.split(',')
                    name = cc.convert(parts[-1]).strip().upper() if parts else "UNKNOWN"
                elif line.startswith("http") and name:
                    clean_url = line.split('$')[0].split('#')[0].split('|')[0].strip()
                    current_raw.append({'name': name, 'url': clean_url})
                    name = ""

            if current_raw:
                with ThreadPoolExecutor(max_workers=70) as ex:
                    futures = {ex.submit(get_speed, x['url'], current_headers, test_session): x for x in current_raw}
                    for f in as_completed(futures):
                        speed = f.result()
                        item = futures[f]
                        if speed < 5.0:
                            summary['online'] += 1
                            if any(k in item['name'] for k in KEYWORDS) and not any(b in item['name'] for b in BLOCK_KEYWORDS):
                                if any(feat.lower() in item['url'].lower() for feat in FEATURES.get(provider_name, [])): 
                                    speed -= 10.0
                                item['speed'] = speed
                                summary['items'].append(item)
            provider_results[u] = summary
        except: provider_results[u] = summary
    return provider_results

def diagnosis(ip_cache):
    sources = load_sources("sources.txt")
    if not sources: return {}
    
    all_res = {}
    target_isps = ["移动", "电信", "联通", "广电", "通用"]
    logging.info(f"🚀 開始併發診斷 {len(target_isps)} 個網絡...")

    # 正確的併發提交
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_p = {executor.submit(crawl_and_test, p, sources, ip_cache): p for p in target_isps}
        
        for future in tqdm(as_completed(future_to_p), total=len(target_isps), desc="🌐 網絡全量診斷"):
            p = future_to_p[future]
            try:
                all_res[p] = future.result()
            except Exception as e:
                logging.error(f"❌ {p} 測試崩潰: {e}")
                all_res[p] = {}
                
    # --- 🌟 15 天失效封印 (僅在 FULL_SCAN 模式執行) ---
    if RUN_MODE == "FULL_SCAN":
        tracker_file = "fail_tracker.json"
        today_obj = datetime.datetime.now()
        today_str = today_obj.strftime("%Y-%m-%d")
        
        try:
            with open(tracker_file, "r", encoding="utf-8") as f: tracker = json.load(f)
        except: tracker = {}

        logging.info("\n📊 --- 【失效追蹤診斷】 ---")
        for url in sources:
            total_online = sum(all_res.get(p, {}).get(url, {}).get('online', 0) for p in ["移动", "电信", "联通", "广电", "通用"])
            if total_online == 0:
                if url not in tracker:
                    tracker[url] = today_str
                    logging.info(f"📍 首次失效: {url[:50]}...")
                else:
                    start_date = datetime.datetime.strptime(tracker[url], "%Y-%m-%d")
                    days_diff = (today_obj - start_date).days
                    if days_diff >= 15:
                        logging.warning(f"🚫 失效滿 {days_diff} 天，執行標記註釋。")
                        mark_source_as_deleted(url)
                        del tracker[url]
                    else: logging.info(f"⏳ 失效 {days_diff} 天 (未滿 15 天)")
            elif url in tracker: del tracker[url]

        with open(tracker_file, "w", encoding="utf-8") as f: json.dump(tracker, f, indent=4)

    # 數據整理
    final_data = {p: [] for p in ["移动", "电信", "联通", "广电"]}
    for p in final_data.keys():
        merged = []  # <--- 確保呢度開始有正確縮進
        # 攞所屬 ISP 嘅結果
        for src_data in all_res.get(p, {}).values():
            merged.extend(src_data.get('items', []))
        # 攞「通用」線路嘅結果
        for src_data in all_res.get("通用", {}).values():
            merged.extend(src_data.get('items', []))
        
        unique_items = {x['url']: x for x in merged}
        final_data[p] = sorted(unique_items.values(), key=lambda x: x.get('speed', 999))
    return final_data

# --- 【4. 主程序】 ---

def main():
    ip_cache = load_ip_pool()
    all_provider_final_data = diagnosis(ip_cache) 
    if not all_provider_final_data: return

    update_time = datetime.datetime.now().strftime("%m%d %H:%M")
    suffix = "_manual" if RUN_MODE == "MANUAL_ONLY" else ""
    files_map = {"移动": (f"gz_live{suffix}.m3u", "廣州移動"), "电信": (f"gz_dxlive{suffix}.m3u", "廣州電訊"), 
                 "联通": (f"gz_ltlive{suffix}.m3u", "廣州聯通"), "广电": (f"gz_gdlive{suffix}.m3u", "廣州廣電")}
    
    valid_providers = {k: v for k, v in all_provider_final_data.items() if v}
    if not valid_providers: return
    best_p_key = max(valid_providers, key=lambda k: len(valid_providers[k]))
    best_isp_all_data = valid_providers[best_p_key]

    for provider, (filename, desc) in files_map.items():
        current_isp_data = all_provider_final_data.get(provider, [])
        with open(filename, "w", encoding="utf-8") as f:
            f.write('#EXTM3U x-tvg-url="https://epg.112114.xyz/pp.xml"\n')
            f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="更", 更{update_time} | {RUN_MODE}\nhttp://10.255.255.1/info.ts\n')
            
            for target_group in ["廣東", "香港", "澳門", "台灣", "特色", "其他"]:
                group_items = []
                local_items = [item for item in current_isp_data if get_group(item["name"]) == target_group]
                for x in local_items:
                    x['final_group'] = target_group
                    group_items.append(x)
                
                if provider != best_p_key:
                    local_urls = {li['url'] for li in local_items}
                    for x in best_isp_all_data:
                        # 修正：確保唔好重複加，同埋 group 匹配
                        if get_group(x["name"]) == target_group and x['url'] not in local_urls:
                            x_copy = dict(x)
                            x_copy['display_name'] = f"{x['name']} ({best_p_key})"
                            x_copy['final_group'] = target_group
                            # 補償源速度增加 5 秒，確保排喺本地源後面
                            x_copy['speed'] = x.get('speed', 0) + 5.0 
                            group_items.append(x_copy)
                
                group_items.sort(key=lambda x: x.get('speed', 999))
                for item in group_items:
                    display_title = item.get("display_name", item["name"])
                    f.write(f'#EXTINF:-1 group-title="{item["final_group"]}" tvg-name="{item["name"]}", {display_title}\n{item["url"]}\n')
        logging.info(f"💾 檔案已保存: {filename}")
    print(f"🏁 {RUN_MODE} 任務完成！")

if __name__ == "__main__":
    main()
