import requests, datetime, time, logging, re, sys, os, urllib3, random, json
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# --- 【1. 初始化配置】 ---
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

# 💡 偵測模式邏輯 (透過 GitHub Actions 環境變量)
# 如果唔係喺 GitHub 行，預設會係 FULL_SCAN
GITHUB_EVENT = os.getenv('GITHUB_EVENT_NAME', 'local')
if GITHUB_EVENT == 'workflow_dispatch':
    RUN_MODE = "MANUAL_ONLY"
    logging.info(">>> 偵測到手動撳制：啟動 MANUAL_ONLY 模式 (只跑專屬源) <<<")
else:
    RUN_MODE = "FULL_SCAN"
    logging.info(">>> 偵測到定時任務：啟動 FULL_SCAN 模式 (全量掃描) <<<")

# 關鍵字過濾
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
    """🌟 修改後的加載邏輯：區分定時與手動模式"""
    if not os.path.exists(file_path):
        return []
    
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if RUN_MODE == "MANUAL_ONLY":
        # 核心邏輯：只抓取 # MY MANUAL SOURCES 標籤下面的網址
        manual_urls = []
        is_manual_section = False
        for line in lines:
            line = line.strip()
            # 搵到標籤就開始紀錄
            if "# MY MANUAL SOURCES" in line.upper():
                is_manual_section = True
                continue
            # 遇到下一個標題或其他非 URL 行可以根據需要停止，呢度簡單處理攞晒下面所有 http
            if is_manual_section:
                if line.startswith("http"):
                    manual_urls.append(line)
                elif line.startswith("#") and "MY MANUAL SOURCES" not in line.upper():
                    # 遇到其他 # 標籤就停止 (可選)
                    # is_manual_section = False 
                    pass
        logging.info(f"🚀 [手動模式] 已從專屬區域加載 {len(manual_urls)} 個測試源")
        return manual_urls
    else:
        # 定時模式：掃描全部（排除掉 # 註釋掉的行）
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
                    if len(parts) > 1:
                        cache[parts[0]] = [ip for ip in parts[1:] if ip]
        except Exception as e:
            logging.info(f"⚠️ 讀取 IP_Pool 出錯: {e}")
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
            random_ip = str(net.network_address + random.randint(1, net.num_addresses - 2))
            return random_ip
        except: return choice.split('/')[0]
    return choice

def get_headers_with_mask(provider_name, pool_cache):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    mask_ip = None
    if provider_name != "通用":
        mask_ip = get_mask_ip(provider_name, pool_cache)
        if mask_ip:
            headers.update({'X-Forwarded-For': mask_ip, 'X-Real-IP': mask_ip, 'Client-IP': mask_ip})
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
    try:
        if os.path.exists("sources.txt"):
            with open("sources.txt", "r", encoding="utf-8") as f:
                lines = f.readlines()
            with open("sources.txt", "w", encoding="utf-8") as f:
                for line in lines:
                    if url.strip() in line and not line.strip().startswith("#"):
                        f.write(f"# {line}")
                    else:
                        f.write(line)
            logging.info(f"✅ 成功喺 sources.txt 標記封印: {url[:40]}...")
    except Exception as e:
        logging.error(f"❌ 標記封印失敗: {e}")

# --- 【3. 核心測試流程】 ---

def crawl_and_test(provider_name, source_list, ip_cache):
    test_session = requests.Session()
    test_session.mount('http://', adapter)
    test_session.mount('https://', adapter)
    
    current_headers, mask_ip = get_headers_with_mask(provider_name, ip_cache)
    
    if provider_name == "通用":
        mask_ip = None
        for key in ['X-Forwarded-For', 'X-Real-IP', 'Client-IP']:
            current_headers.pop(key, None)
        logging.info(f"🌐 【通用】線路：執行原生模式")
    elif not mask_ip:
        logging.info(f"⚠️  {provider_name} 無面具")
    else:
        logging.info(f"🎭 【{provider_name}】面具: {mask_ip}")

    provider_results = {}
    for u in source_list:
        summary = {'total': 0, 'online': 0, 'items': []}
        try:
            r = test_session.get(u, timeout=7, headers=current_headers, verify=False)
            r.encoding = 'utf-8'
            lines = r.text.splitlines()
            name, current_raw = "", []
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#EXTM3U"): continue
                if line.startswith("#EXTINF"):
                    summary['total'] += 1
                    parts = line.split(',')
                    name = cc.convert(parts[-1]).strip().upper() if parts else "UNKNOWN"
                elif (line.startswith("http") or line.startswith("rtmp")) and name:
                    clean_url = line.split('$')[0].split('#')[0].split('|')[0].replace(' ', '').strip()
                    current_raw.append({'name': name, 'url': clean_url})
                    name = ""

            if current_raw:
                with ThreadPoolExecutor(max_workers=150) as ex:
                    futures = {ex.submit(get_speed, x['url'], current_headers, test_session): x for x in current_raw}
                    pbar = tqdm(total=len(futures), desc=f"⏳ 分析【{provider_name}】", unit="link", ncols=100, leave=False)
                    for f in futures:
                        item = f.result()
                        target_item = futures[f]
                        if item < 5.0:
                            summary['online'] += 1
                            if any(k in target_item['name'] for k in KEYWORDS) and not any(b in target_item['name'] for b in BLOCK_KEYWORDS):
                                fs = item
                                feat_list = FEATURES.get(provider_name, [])
                                if any(feat.lower() in target_item['url'].lower() for feat in feat_list): fs -= 10.0
                                target_item['speed'] = fs
                                summary['items'].append(target_item)
                        pbar.update(1)
                    pbar.close()
            provider_results[u] = summary
        except: provider_results[u] = summary
    return provider_results

def diagnosis(ip_cache):
    sources = load_sources("sources.txt")
    if not sources: return {}
    
    all_res = {p: crawl_and_test(p, sources, ip_cache) for p in ["移动", "电信", "联通", "广电", "通用"]}

    # --- 15 天日期追蹤邏輯 (只喺 FULL_SCAN 模式下進行封印判斷) ---
    tracker_file = "fail_tracker.json"
    today_obj = datetime.datetime.now()
    today_str = today_obj.strftime("%Y-%m-%d")
    
    if os.path.exists(tracker_file):
        try:
            with open(tracker_file, "r", encoding="utf-8") as f: tracker = json.load(f)
        except: tracker = {}
    else: tracker = {}

    logging.info("\n📊 --- 【連通性診斷報告】 ---")
    for url in sources:
        total_online = sum(all_res[p].get(url, {}).get('online', 0) for p in ["移动", "电信", "联通", "广电", "通用"])
        
        if RUN_MODE == "FULL_SCAN":
            if total_online == 0:
                if url not in tracker:
                    tracker[url] = today_str
                else:
                    try:
                        start_date = datetime.datetime.strptime(tracker[url], "%Y-%m-%d")
                        days_diff = (today_obj - start_date).days
                        if days_diff >= 15:
                            mark_source_as_deleted(url)
                            del tracker[url]
                    except: tracker[url] = today_str
            else:
                if url in tracker: del tracker[url]

    if RUN_MODE == "FULL_SCAN":
        with open(tracker_file, "w", encoding="utf-8") as f:
            json.dump(tracker, f, indent=4)

    final_data = {p: [] for p in ["移动", "电信", "联通", "广电"]}
    for p in final_data.keys():
        merged = []
        for src_data in all_res[p].values(): merged.extend(src_data['items'])
        for src_data in all_res["通用"].values(): merged.extend(src_data['items'])
        unique_items = {x['url']: x for x in merged}
        final_data[p] = sorted(unique_items.values(), key=lambda x: x.get('speed', 999))
    return final_data

# --- 【4. 主程序入口】 ---

def main():
    ip_cache = load_ip_pool()
    all_provider_final_data = diagnosis(ip_cache) 
    if not all_provider_final_data: return

    update_time = datetime.datetime.now().strftime("%m%d %H:%M")
    # 如果係手動模式，檔名加個 manual 區分 (可選)
    suffix = "_manual" if RUN_MODE == "MANUAL_ONLY" else ""
    files_map = {
        "移动": (f"gz_live{suffix}.m3u", "廣州移動"),
        "电信": (f"gz_dxlive{suffix}.m3u", "廣州電訊"),
        "联通": (f"gz_ltlive{suffix}.m3u", "廣州聯通"),
        "广电": (f"gz_gdlive{suffix}.m3u", "廣州廣電")
    }
    
    valid_providers = {k: v for k, v in all_provider_final_data.items() if v}
    if not valid_providers: return
    best_p_key = max(valid_providers, key=lambda k: len(valid_providers[k]))
    best_isp_all_data = valid_providers[best_p_key]

    for provider, (filename, desc) in files_map.items():
        current_isp_data = all_provider_final_data.get(provider, [])
        _, mask_ip = get_headers_with_mask(provider, ip_cache)
        try:
            with open(filename, "w", encoding="utf-8") as f:
                epg_sources = ["https://epg.112114.xyz/pp.xml", "https://epg.pw/xmltv/feed/subscription/free/hk.xml", "https://epg.pw/xmltv/feed/subscription/free/tw.xml"]
                f.write(f'#EXTM3U x-tvg-url="{",".join(epg_sources)}"\n')
                f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="更", 更{update_time} \nhttp://10.255.255.1/info.ts\n')
                f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="模", 模式：{RUN_MODE} \nhttp://10.255.255.1/info.ts\n')
                
                for target_group in ["廣東", "香港", "澳門", "台灣", "特色", "其他"]:
                    group_items = []
                    local_items = [item for item in current_isp_data if get_group(item["name"]) == target_group]
                    for x in local_items:
                        x['final_group'] = target_group
                        group_items.append(x)
                    
                    if provider != best_p_key:
                        local_urls = {li['url'] for li in local_items}
                        for x in best_isp_all_data:
                            if get_group(x["name"]) == target_group and x['url'] not in local_urls:
                                x_copy = x.copy()
                                x_copy['display_name'] = f"{x_copy.get('name', 'UNKNOWN')} ({best_p_key})"
                                x_copy['final_group'] = target_group
                                group_items.append(x_copy)
                    
                    group_items.sort(key=lambda x: x.get('speed', 999))
                    for item in group_items:
                        display_name = item.get('display_name', item['name'])
                        f.write(f'#EXTINF:-1 group-title="{item["final_group"]}" tvg-name="{item["name"]}", {display_name}\n{item["url"]}\n')
            logging.info(f"💾 檔案已保存: {filename}")
        except: pass
    print(f"🏁 {RUN_MODE} 任務完成！")

if __name__ == "__main__":
    main()
