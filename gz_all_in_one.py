import requests, datetime, time, logging, re, sys, os, urllib3, random
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# --- 【初始化配置】 ---
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

KEYWORDS = ["廣州", "珠江", "廣東", "大灣區", "南方", "深圳", "翡翠", "VIU", "HOY", "RTHK", "港台", "明珠", "無線", "鳳凰", "澳視", "澳門", "TDM", "CCTV", "台灣", "TVBS", "三立"]
BLOCK_KEYWORDS = ["*SG", "redirect", "酒店", "TEST", "測試", "購物", "延時", "8K", "UHD"]

FEATURES = {
    "移动": ["120.196.", "120.197.", "183.232.", "183.235.", "gdmcc", "2409:"], 
    "电信": ["gdct", "113.108.", "125.88.", "14.215.", "240e:"],
    "联通": ["gdcu", "121.32.", "121.33.", "2408:"],
    "广电": ["gdtv", "guangdong", "240a:"]
}

# --- 【IP 池工具】 ---
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
    import ipaddress  # Python 內建，唔使另外裝
    
    name_map = {"移动": ["移动", "移動"], "电信": ["电信", "電信"], "联通": ["联通", "聯通"], "广电": ["广电", "廣電"]}
    target_names = name_map.get(provider_name, [provider_name])
    
    raw_ip_list = []
    for name in target_names:
        if name in pool_cache:
            raw_ip_list.extend(pool_cache[name])
    
    if not raw_ip_list:
        return None
        
    choice = random.choice(raw_ip_list)
    
    # 🌟 新增邏輯：判斷係咪網段 (CIDR)
    if "/" in choice:
        try:
            net = ipaddress.ip_network(choice, strict=False)
            # 喺網段入面隨機抽一個 IP
            # 避開第一個(網絡號)同最後一個(廣播號)，所以 +1 同 -1
            random_ip = str(net.network_address + random.randint(1, net.num_addresses - 2))
            return random_ip
        except:
            return choice.split('/')[0] # 出錯就攞返前面個 IP
    return choice

def get_headers_with_mask(provider_name, pool_cache):
    headers = {'User-Agent': 'Mozilla/5.0 (Linux; Android 10; Mobile) IPTV/1.0'}
    mask_ip = get_mask_ip(provider_name, pool_cache)
    if mask_ip:
        headers.update({'X-Forwarded-For': mask_ip, 'X-Real-IP': mask_ip, 'Client-IP': mask_ip})
    return headers, mask_ip

# --- 【通用工具】 ---
def load_sources(file_path="sources.txt"):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return []

def get_speed(url, custom_headers, current_session): 
    try:
        start = time.time()
        # 優化：timeout 2.0s 兼顧穩定性與效率
        r = current_session.get(url, timeout=2.0, headers=custom_headers, stream=True, verify=False)
        if r.status_code < 400: 
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

# --- 【核心測試】 ---

def crawl_and_test(provider_name, source_list, ip_cache):
    test_session = requests.Session()
    test_session.mount('http://', adapter)
    test_session.mount('https://', adapter)
    
    current_headers, mask_ip = get_headers_with_mask(provider_name, ip_cache)
    provider_results = {}
    
    if not mask_ip:
        for key in ['X-Forwarded-For', 'X-Real-IP', 'Client-IP']: current_headers.pop(key, None)
        logging.info(f"⚠️  {provider_name} 無面具，用原生 IP")
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
                    name = cc.convert(raw_name).strip().upper() 
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
                            pbar.set_postfix_str(f"台: {item['name'][:4]}")
                            
                            if s < 5.0:
                                summary['online'] += 1
                                is_white = any(k in item['name'] for k in KEYWORDS)
                                is_black = any(b in item['name'] for b in BLOCK_KEYWORDS)
                                
                                if is_white and not is_black:
                                    summary['white'] += 1
                                    fs = s 
                                    feat_list = FEATURES.get(provider_name, [])
                                    # 🌟 舊 Code 魂：ISP 置頂邏輯
                                    if any(feat.lower() in item['url'].lower() for feat in feat_list):
                                        fs -= 10.0 
                                        
                                    item['speed'], item['display_speed'] = fs, s
                                    summary['items'].append(item)
                                elif is_black:
                                    summary['black'] += 1
                            else:
                                summary['offline'] += 1
                        except:
                            summary['offline'] += 1
                        finally:
                            pbar.update(1)
                    pbar.close() # 🌟 確保在有進度條的情況下才關閉
            
            provider_results[u] = summary
            status_icon = "✅" if summary['online'] > 0 else "💀"
            logging.info(f"{status_icon} 報告: {u} (連通: {summary['online']}/{summary['total']})")
        except Exception as e:
            logging.info(f"💀 出錯: {u} ({str(e)[:20]})")
            provider_results[u] = summary
            
    return provider_results

# --- 【診斷入口】 ---
def diagnosis(ip_cache):
    sources = load_sources("sources.txt")
    if not sources: return {}
    all_res = {p: crawl_and_test(p, sources, ip_cache) for p in ["移动", "电信", "联通", "广电", "通用"]}

    logging.info("\n📊 --- 【直播源五線連通性終極報告】 ---")
    dead_sources = []
    for url in sources:
        total_online = 0
        common_data = all_res.get("通用", {}).get(url, {}) or all_res.get("移动", {}).get(url, {})
        stats = []
        for p in ["移动", "电信", "联通", "广电", "通用"]:
            online = all_res[p].get(url, {}).get('online', 0)
            total_online += online
            stats.append(f"{p}: {online}")
        logging.info(f"源: {url}\n┗ 總量: {common_data.get('total', 0)} | " + " | ".join(stats))
        if total_online == 0:
            dead_sources.append(url)
            logging.info(f"   ⚠️  建議移除。")

    final_data = {p: [] for p in ["移动", "电信", "联通", "广电"]}
    for p in final_data.keys():
        merged = []
        for src_data in all_res[p].values(): merged.extend(src_data['items'])
        final_data[p] = sorted(merged, key=lambda x: x.get('speed', 999))
    return final_data

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
    
    # 🌟 增加保護：確保數據唔係空嘅
    valid_providers = {k: v for k, v in all_provider_final_data.items() if v}
    if not valid_providers:
        logging.info("❌ 冇任何有效線路數據，停止生成。")
        return
        
    best_p_key = max(valid_providers, key=lambda k: len(valid_providers[k]))
    best_isp_all_data = valid_providers[best_p_key]

    for provider, (filename, desc) in files_map.items():
        current_isp_data = all_provider_final_data.get(provider, [])
        _, mask_ip = get_headers_with_mask(provider, ip_cache)
        
        try:
            with open(filename, "w", encoding="utf-8") as f:
                epg_sources = [
                    "https://epg.112114.xyz/pp.xml",           # 內地/廣東台主力
                    "https://epg.pw/xmltv/feed/subscription/free/hk.xml",  # 香港/國際台主力
                    "https://epg.pw/xmltv/feed/subscription/free/tw.xml"   # 台灣台補充
                ]
                f.write(f'#EXTM3U x-tvg-url="{",".join(epg_sources)}"\n')
    
                black_hole_url = "http://10.255.255.1/info.ts"
                f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="更", 更{update_time} \n')
                f.write(f'{black_hole_url}\n')
                
                f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="伪", 伪{mask_ip or "原生"} \n')
                f.write(f'{black_hole_url}\n')

                f.write(f'#EXTINF:-1 group-title="{desc}" tvg-name="查我IP",  您屋企粒真實IP\n')
                f.write(f'http://mirror.leaseweb.com/speedtest/10mb.bin\n') # 呢條係大型檔案，會令播放器慢慢 Load，唔會跳
                
                for target_group in ["廣東", "香港", "澳門", "台灣", "特色", "其他"]:
                    group_items = []
                    # 1. 放入原生 ISP 數據
                    local_items = [item for item in current_isp_data if get_group(item["name"]) == target_group]
                    for x in local_items:
                        x['final_group'] = target_group
                        group_items.append(x)
                        
                    # 2. 放入補償數據
                    if provider != best_p_key:
                        local_urls = {li['url'] for li in local_items}
                        for x in best_isp_all_data:
                            if get_group(x["name"]) == target_group and x['url'] not in local_urls:
                                x_copy = x.copy()
                                # 🌟 修正：確保 display_name 標籤正確生成
                                original_name = x_copy.get('name', 'UNKNOWN')
                                x_copy['display_name'] = f"{original_name} ({best_p_key})"
                                x_copy['final_group'] = target_group
                                group_items.append(x_copy)
                    
                    # 3. 按測速排序
                    group_items.sort(key=lambda x: x.get('speed', 999))
                    
                    for item in group_items:
                        display_name = item.get('display_name', item['name'])
                        f.write(f'#EXTINF:-1 group-title="{item["final_group"]}" tvg-name="{item["name"]}", {display_name}\n{item["url"]}\n')
            logging.info(f"💾 檔案已保存: {filename}")
        except IOError as e:
            logging.info(f"❌ 無法寫入檔案 {filename}: {e}")

    print(f"🏁 任務完成！最強線路：{best_p_key}")

if __name__ == "__main__":
    main()
