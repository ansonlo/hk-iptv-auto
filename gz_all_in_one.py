import requests, datetime, time, logging, re, os, urllib3, random
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# --- 【1. 初始化工具】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
cc = OpenCC('s2t')
# 增大連線池，應對 150+ 的線程並發
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
BLOCK_KEYWORDS = ["*SG", "redirect", "酒店", "TEST", "測試", "購物", "延時", "8K", "UHD"]

# 廣東移動、電信等本地 ISP 特徵，用於權重排序
FEATURES = {
    "移动": ["120.196.", "120.197.", "183.232.", "183.235.", "gdmcc", "2409:"], 
    "电信": ["gdct", "113.108.", "125.88.", "14.215.", "240e:"],
    "联通": ["gdcu", "121.32.", "121.33.", "2408:"],
    "广电": ["gdtv", "guangdong", "240a:"]
}

# --- 【2. 強化版工具函數】 ---

def clean_name(raw_name):
    # 如果名字入面包含更新日期標籤，直接保留
    if any(x in raw_name for x in ["更", "📅"]):
        return raw_name.strip()
        
    name = cc.convert(raw_name).replace('臺', '台').upper().strip()
    # 移除括號內容
    name = re.sub(r'\[.*?\]|\(.*?\)|\（.*?\）', '', name)
    # 移除畫質標籤
    suffixes = ["超清", "高清", "藍光", "標清", "頻道", "1080P", "720P", "4K", "HD", "SD", "FHD", "BD"]
    for s in suffixes:
        name = name.replace(s, "")
    return name.strip("-").strip("_").strip()

def get_speed(url, custom_headers, current_session): 
    """優化：使用隨機 UA 同埋 with 語句確保連線釋放"""
    custom_headers['User-Agent'] = random.choice([
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Linux; Android 11; Pixel 5)',
        'OTT-Player/1.1'
    ])
    for i in range(2):
        try:
            start = time.time()
            # stream=True 配合 with，攞到頭部即刻斷開
            with current_session.get(url, timeout=1.5, headers=custom_headers, stream=True, verify=False) as r:
                if r.status_code < 400: 
                    return time.time() - start
        except:
            if i == 0: time.sleep(0.3)
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

# --- 【4. 核心測試邏輯】 ---

def crawl_and_test(provider_name, source_list, ip_cache):
    test_session = requests.Session()
    test_session.mount('http://', adapter)
    test_session.mount('https://', adapter)
    
    current_headers, mask_ip = get_headers_with_mask(provider_name, ip_cache)
    provider_results = {}
    
    if mask_ip: logging.info(f"🎭 【{provider_name}】戴上偽裝面具: {mask_ip}")

    for u in source_list:
        summary = {'items': []}
        try:
            r = test_session.get(u, timeout=7, headers=current_headers, verify=False)
            r.encoding = 'utf-8'
            lines = r.text.splitlines()
            
            name, current_raw = "", []
            for line in lines:
                line = line.strip()
                if line.startswith("#EXTINF"):
                    parts = line.split(',')
                    name = clean_name(parts[-1]) if parts else "UNKNOWN"
                elif (line.startswith("http") or line.startswith("rtmp")) and name:
                    clean_url = line.split('$')[0].split('#')[0].split('|')[0].strip()
                    current_raw.append({'name': name, 'url': clean_url})
                    name = ""

            if current_raw:
                with ThreadPoolExecutor(max_workers=150) as ex:
                    futures = {ex.submit(get_speed, x['url'], current_headers, test_session): x for x in current_raw}
                    for f in futures:
                        item = futures[f]
                        try:
                            s = f.result()
                            if s < 5.0:
                                is_white = any(k in item['name'] for k in KEYWORDS)
                                is_black = any(b in item['name'] for b in BLOCK_KEYWORDS)
                                if is_white and not is_black:
                                    # ISP 權重優化：本地源在排序上獲取優勢
                                    feat_list = FEATURES.get(provider_name, [])
                                    if any(feat.lower() in item['url'].lower() for feat in feat_list):
                                        s -= 10.0 
                                    item['speed'] = s
                                    summary['items'].append(item)
                        except: pass
            
            provider_results[u] = summary
            logging.info(f"✅ 掃描完成: {u[:40]}... (搵到 {len(summary['items'])} 條有效線)")
        except Exception as e:
            logging.warning(f"💀 出錯: {u[:40]} ({str(e)[:20]})")
    return provider_results

# --- 【5. 主流程：文件生成與最終去重】 ---

def main():
    ip_cache = load_ip_pool()
    sources = []
    if os.path.exists("sources.txt"):
        with open("sources.txt", "r", encoding="utf-8") as f:
            sources = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    if not sources: 
        logging.error("❌ 找不到 sources.txt")
        return

    # 分 ISP 進行測速
    all_provider_final_data = {}
    for p in ["移动", "电信", "联通", "广电"]:
        all_res = crawl_and_test(p, sources, ip_cache)
        merged = []
        for src_data in all_res.values(): merged.extend(src_data['items'])
        all_provider_final_data[p] = sorted(merged, key=lambda x: x.get('speed', 999))

    update_time = datetime.datetime.now().strftime("%m%d %H:%M")
    files_map = {
        "移动": ("gz_live.m3u", "廣州移動"), 
        "电信": ("gz_dxlive.m3u", "廣州電訊"), 
        "联通": ("gz_ltlive.m3u", "廣州聯通"), 
        "广电": ("gz_gdlive.m3u", "廣州廣電")
    }
    
    # 搵出資源最豐富嘅 ISP 作為補償
    valid_providers = {k: v for k, v in all_provider_final_data.items() if v}
    if not valid_providers: return
    best_p_key = max(valid_providers, key=lambda k: len(valid_providers[k]))
    best_isp_all_data = valid_providers[best_p_key]

    for provider, (filename, desc) in files_map.items():
        current_isp_data = all_provider_final_data.get(provider, [])
        
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f'#EXTM3U x-tvg-url="https://epg.112114.xyz/pp.xml"\n')
                
                f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="更新時間", 更{update_time}\nhttp://10.255.255.1/info.ts\n')
                
                for target_group in ["廣東", "香港", "澳門", "台灣", "特色", "其他"]:
                    group_items = []
                    # 1. 加入本地 ISP 優先數據
                    local_items = [item for item in current_isp_data if get_group(item["name"]) == target_group]
                    group_items.extend(local_items)
                        
                    # 2. 加入補償數據 (跨 ISP 借用)
                    if provider != best_p_key:
                        local_urls = {li['url'] for li in local_items}
                        for x in best_isp_all_data:
                            if get_group(x["name"]) == target_group and x['url'] not in local_urls:
                                group_items.append(x)
                    
                    # 3. 排序與去重合併
                    group_items.sort(key=lambda x: x.get('speed', 999))
                    
                    final_unique_items = []
                    seen_urls = set()
                    channel_count = {} # 每個頻道限流 8 條

                    for item in group_items:
                        u = item['url']
                        c_name = item['name']
                        # 過濾掉垃圾標籤
                        if any(x in c_name for x in ["更", "📅", "偽", "查我IP"]): continue
                        
                        if u not in seen_urls:
                            channel_count[c_name] = channel_count.get(c_name, 0) + 1
                            if channel_count[c_name] <= 8:
                                final_unique_items.append(item)
                                seen_urls.add(u)
                    
                    # 4. 寫入該分組
                    for item in final_unique_items:
                        f.write(f'#EXTINF:-1 group-title="{target_group}" tvg-name="{item["name"]}", {item["name"]}\n{item["url"]}\n')

            logging.info(f"💾 產出完成: {filename} (分組: {target_group})")
        except Exception as e: logging.error(f"❌ 寫入錯誤 {filename}: {e}")

    logging.info(f"🏁 任務結束！")

if __name__ == "__main__":
    main()
