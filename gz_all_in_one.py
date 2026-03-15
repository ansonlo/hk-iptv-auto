import requests, datetime, time, logging, re, sys, os, urllib3, random
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
        logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"), 
        logging.StreamHandler()
    ]
)

KEYWORDS = ["廣州", "珠江", "廣東", "大灣區", "南方", "深圳", "翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線", "鳳凰", "澳視", "澳門", "TDM", "澳亞", "CCTV", "台灣", "TVBS", "三立"]
BLOCK_KEYWORDS = ["*SG", "redirect", "酒店", "TEST", "測試", "購物", "延時", "8K", "UHD"]

FEATURES = {
    "移动": ["120.196.", "120.197.", "183.232.", "183.235.", "gdmcc", "2409:"], 
    "电信": ["gdct", "113.108.", "125.88.", "14.215.", "240e:"],
    "联通": ["gdcu", "121.32.", "121.33.", "2408:"],
    "广电": ["gdtv", "guangdong", "240a:"]
}

# --- 【2. 強化版工具函數】 ---

def clean_name(raw_name):
    """強效歸一化：確保翡翠台HD、翡翠台(超清)都變成『翡翠台』"""
    # 基礎轉換：繁轉簡、統一台字、轉大寫
    name = cc.convert(raw_name).replace('臺', '台').upper().strip()
    # 移除括號內容 [xxx], (xxx), （xxx）
    name = re.sub(r'\[.*?\]|\(.*?\)|\（.*?\）', '', name)
    # 移除畫質同干擾後綴
    suffixes = ["超清", "高清", "藍光", "標清", "頻道", "1080P", "720P", "4K", "HD", "SD", "FHD", "BD"]
    for s in suffixes:
        name = name.replace(s, "")
    return name.strip("-").strip("_").strip()

def get_speed(url, custom_headers, current_session): 
    """強化版測速：加入 2 次重試機制，對抗網絡抖動"""
    for i in range(2):
        try:
            start = time.time()
            r = current_session.get(url, timeout=2.0, headers=custom_headers, stream=True, verify=False)
            if r.status_code < 400: 
                return time.time() - start
        except:
            if i == 0: time.sleep(0.5)
            continue
    return 999

def get_group(name):
    check_name = name.upper().replace(" ", "")
    if any(x in check_name for x in ["廣東", "珠江", "廣州", "大灣區", "南方", "深圳"]): return "廣東"
    if any(x in check_name for x in ["翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線"]): return "香港"
    if any(x in check_name for x in ["東森", "三立", "中視", "公視", "TVBS", "緯來"]): return "台灣"
    if any(x in check_name for x in ["澳視", "澳門", "TDM", "澳亞"]): return "澳門"
    if "CCTV" in check_name: return "特色"
    return "其他"

# --- 【3. IP 池與面具邏輯 (保留你的原創)】 ---

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
    headers = {'User-Agent': 'Mozilla/5.0 (Linux; Android 10; Mobile) IPTV/1.0'}
    mask_ip = get_mask_ip(provider_name, pool_cache)
    if mask_ip: headers.update({'X-Forwarded-For': mask_ip, 'X-Real-IP': mask_ip, 'Client-IP': mask_ip})
    return headers, mask_ip

# --- 【4. 核心測試邏輯】 ---

def crawl_and_test(provider_name, source_list, ip_cache):
    test_session = requests.Session()
    test_session.mount('http://', adapter)
    test_session.mount('https://', adapter)
    
    current_headers, mask_ip = get_headers_with_mask(provider_name, ip_cache)
    provider_results = {}
    
    if not mask_ip:
        for key in ['X-Forwarded-For', 'X-Real-IP', 'Client-IP']: current_headers.pop(key, None)
        logging.info(f"⚠️ {provider_name} 無面具用原生 IP")
    else:
        logging.info(f"🎭 【{provider_name}】戴上面具: {mask_ip}")

    for u in source_list:
        summary = {'total': 0, 'online': 0, 'offline': 0, 'white': 0, 'black': 0, 'items': []}
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
                    raw_name = parts[-1] if parts else "UNKNOWN"
                    # --- ✅ 調用歸一化函數 ---
                    name = clean_name(raw_name)
                elif (line.startswith("http") or line.startswith("rtmp")) and name:
                    clean_url = line.split('$')[0].split('#')[0].split('|')[0].replace(' ', '').strip()
                    current_raw.append({'name': name, 'url': clean_url})
                    name = ""

            if current_raw:
                with ThreadPoolExecutor(max_workers=150) as ex:
                    futures = {ex.submit(get_speed, x['url'], current_headers, test_session): x for x in current_raw}
                    pbar = tqdm(total=len(futures), desc=f"⏳ 分析【{provider_name}】", unit="link", ncols=100, leave=False)
                    for f in futures:
                        item = futures[f]
                        try:
                            s = f.result()
                            if s < 5.0:
                                summary['online'] += 1
                                is_white = any(k in item['name'] for k in KEYWORDS)
                                is_black = any(b in item['name'] for b in BLOCK_KEYWORDS)
                                if is_white and not is_black:
                                    summary['white'] += 1
                                    fs = s 
                                    feat_list = FEATURES.get(provider_name, [])
                                    # ISP 權重優化：本地 ISP 源置頂
                                    if any(feat.lower() in item['url'].lower() for feat in feat_list):
                                        fs -= 10.0 
                                    item['speed'], item['display_speed'] = fs, s
                                    summary['items'].append(item)
                                elif is_black: summary['black'] += 1
                            else: summary['offline'] += 1
                        except: summary['offline'] += 1
                        finally: pbar.update(1)
                    pbar.close()
            
            provider_results[u] = summary
            logging.info(f"✅ 報告: {u} (連通: {summary['online']}/{summary['total']})")
        except Exception as e:
            logging.info(f"💀 出錯: {u} ({str(e)[:20]})")
            provider_results[u] = summary
    return provider_results

# --- 【5. 診斷入口】 ---

def diagnosis(ip_cache):
    sources = []
    if os.path.exists("sources.txt"):
        with open("sources.txt", "r", encoding="utf-8") as f:
            sources = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    if not sources: return {}
    all_res = {p: crawl_and_test(p, sources, ip_cache) for p in ["移动", "电信", "联通", "广电", "通用"]}

    final_data = {p: [] for p in ["移动", "电信", "联通", "广电"]}
    for p in final_data.keys():
        merged = []
        for src_data in all_res[p].values(): merged.extend(src_data['items'])
        # 全局排序
        final_data[p] = sorted(merged, key=lambda x: x.get('speed', 999))
    return final_data

# --- 【6. 主流程：文件生成與最終去重】 ---

def main():
    ip_cache = load_ip_pool()
    all_provider_final_data = diagnosis(ip_cache) 
    if not all_provider_final_data: return

    update_time = datetime.datetime.now().strftime("%m%d %H:%M")
    files_map = {
        "移动": ("gz_live.m3u", "廣州移動"), 
        "电信": ("gz_dxlive.m3u", "廣州電訊"), 
        "联通": ("gz_ltlive.m3u", "廣州聯通"), 
        "广电": ("gz_gdlive.m3u", "廣州廣電")
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
                f.write(f'#EXTM3U x-tvg-url="https://epg.112114.xyz/pp.xml,https://epg.pw/xmltv/feed/subscription/free/hk.xml"\n')
                f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="更", 更{update_time} \nhttp://10.255.255.1/info.ts\n')
                
                for target_group in ["廣東", "香港", "澳門", "台灣", "特色", "其他"]:
                    group_items = []
                    # 1. 加入原生 ISP 數據
                    local_items = [item for item in current_isp_data if get_group(item["name"]) == target_group]
                    for x in local_items:
                        x['final_group'] = target_group
                        group_items.append(x)
                        
                    # 2. 加入補償數據 (跨 ISP 借用)
                    if provider != best_p_key:
                        local_urls = {li['url'] for li in local_items}
                        for x in best_isp_all_data:
                            if get_group(x["name"]) == target_group and x['url'] not in local_urls:
                                x_copy = x.copy()
                                x_copy['display_name'] = f"{x['name']} ({best_p_key})"
                                x_copy['final_group'] = target_group
                                group_items.append(x_copy)
                    
                    # --- ✅ 3. 排序與「Base URL」二次去重 ---
                    group_items.sort(key=lambda x: x.get('speed', 999))
                    final_unique_items = []
                    seen_urls = set()
                    
                    for item in group_items:
                        # 提取網址真身去重
                        base_url = item['url'].split('?')[0].split('#')[0].split('$')[0].strip()
                        unique_key = f"{item['name']}_{base_url}"
                        
                        if unique_key not in seen_urls:
                            final_unique_items.append(item)
                            seen_urls.add(unique_key)
                    
                    # 4. 寫入文件
                    for item in final_unique_items:
                        # 🌟 核心改動：跳過所有舊嘅功能性標籤（如 main.py 產生嘅時間）
                        # 咁樣就唔會出現重複嘅「更」，亦唔會出現「更 (移动)」
                        if any(x in item['name'] for x in ["更", "伪", "查我IP"]):
                            continue
                            
                        d_name = item.get('display_name', item['name'])
                        f.write(f'#EXTINF:-1 group-title="{item["final_group"]}" tvg-name="{item["name"]}", {d_name}\n{item["url"]}\n')

            logging.info(f"💾 檔案已保存: {filename}")
        except Exception as e: logging.info(f"❌ 寫入錯誤 {filename}: {e}")

    print(f"🏁 任務完成！最強線路：{best_p_key}")

if __name__ == "__main__":
    main()
