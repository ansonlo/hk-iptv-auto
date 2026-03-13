import requests, re, os, logging, time, random
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 【1. 配置與初始化】 ---
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 1500  
cc = OpenCC('s2t')

# 核心白名單
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "深圳", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

# 🚫 新增：排除黑名單（過濾垃圾源）
BLOCK_KEYWORDS = ["購物", "測試", "TEST", "SHOP", "廣告", "酒店", "福利", "PREVIEW"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u",
]

# 優化 Session，增加重試機制
def get_session():
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=50, pool_maxsize=50)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

session = get_session()

def get_random_headers():
    versions = ["120.0.0.0", "121.0.0.0", "122.0.0.0"]
    return {
        'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.choice(versions)} Safari/537.36'
    }

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# --- 【2. 搜尋引擎函數】 ---

def search_github():
    query = quote("iptv gd m3u")
    api_url = f"https://api.github.com/search/repositories?q={query}&sort=updated"
    discovered = []
    try:
        r = session.get(api_url, headers=get_random_headers(), timeout=10)
        if r.status_code == 200:
            repos = r.json().get('items', [])
            for repo in repos:
                name = repo.get('full_name')
                branch = repo.get('default_branch', 'main')
                # 增加多幾個常見路徑
                discovered.append(f"https://raw.githubusercontent.com/{name}/{branch}/live.m3u")
                discovered.append(f"https://raw.githubusercontent.com/{name}/{branch}/tv.m3u")
                discovered.append(f"https://raw.githubusercontent.com/{name}/{branch}/iptv.m3u")
    except: pass
    return discovered

# --- 【3. 核心過濾抓取邏輯】 ---

def get_filtered_links(url):
    links = []
    try:
        r = session.get(url, timeout=15, headers=get_random_headers(), verify=False)
        r.encoding = 'utf-8'
        lines = r.text.split('\n')
        
        temp_name = ""
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # M3U 格式處理
            if line.startswith("#EXTINF"):
                raw_name = cc.convert(line.split(',')[-1]).strip().upper()
                # 🌟 優化：同時檢查白名單同埋避開黑名單
                if any(k.upper() in raw_name for k in KEYWORDS) and not any(b in raw_name for b in BLOCK_KEYWORDS):
                    temp_name = raw_name
                else:
                    temp_name = ""
            elif (line.startswith("http") or line.startswith("rtmp")) and temp_name:
                clean_url = line.split('$')[0].split('#')[0].split('|')[0].strip()
                # 只保留常見嘅直播流後綴
                if any(ext in clean_url.lower() for ext in [".m3u8", ".ts", ".flv", "/info.ts", "m3u8"]):
                    links.append(clean_url)
                temp_name = ""
                
            # TXT 格式處理 (台名,網址)
            elif "," in line and "://" in line:
                parts = line.split(',')
                txt_name = cc.convert(parts[0]).upper()
                if any(k.upper() in txt_name for k in KEYWORDS) and not any(b in txt_name for b in BLOCK_KEYWORDS):
                    u = parts[1].strip().split('#')[0].split('$')[0]
                    links.append(u)
    except:
        pass
    return list(dict.fromkeys(links))

# --- 【4. 主程序】 ---

def main():
    logging.info("\n" + "="*60)
    logging.info(f"🚀 啟動【超高效精準抓藥模式】 (MAX:{MAX_AUTO_KEEP})")
    logging.info("="*60)

    fixed_content = []
    auto_links = []
    is_auto_zone = False

    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                raw_line = line.strip()
                if "--- AUTO DISCOVERED SOURCES ---" in raw_line:
                    is_auto_zone = True
                    continue
                if is_auto_zone:
                    if raw_line and not raw_line.startswith("#"):
                        auto_links.append(raw_line)
                else:
                    fixed_content.append(line)

    # 排除重複
    current_all_set = set([l.strip() for l in auto_links])
    for line in fixed_content:
        if line.strip().startswith("http"):
            current_all_set.add(line.strip().split('$')[0])

    # 收集目標
    targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + search_github()))
    new_discovered = []
    
    logging.info(f"📡 正在從 {len(targets)} 個源頭掃描精華資源...")
    
    # 🌟 優化：增加 Workers 數量至 30，加快掃描速度
    with ThreadPoolExecutor(max_workers=30) as executor:
        results = list(executor.map(get_filtered_links, targets))
    
    for found_links in results:
        for l in found_links:
            if l not in current_all_set:
                new_discovered.append(l)
                current_all_set.add(l)

    # 合併與末位淘汰
    combined_auto = auto_links + new_discovered
    final_auto = combined_auto[-MAX_AUTO_KEEP:] if len(combined_auto) > MAX_AUTO_KEEP else combined_auto

    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        for line in fixed_content:
            f.write(line)
        if fixed_content and not fixed_content[-1].endswith("\n"):
            f.write("\n")
        f.write("\n# --- AUTO DISCOVERED SOURCES ---\n")
        for link in final_auto:
            if link.strip():
                f.write(f"{link.strip()}\n")
    
    logging.info(f"✅ 抓藥完畢！新增: {len(new_discovered)} 條，總共自動源: {len(final_auto)} 條。")

if __name__ == "__main__":
    main()
