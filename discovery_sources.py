import requests, re, os, logging, time, random
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 【1. 配置與初始化】 ---
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 1000  # 稍微放寬少少，等 main.py 有更多種子去測速
cc = OpenCC('s2t')

# 核心白名單
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "深圳", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

# 排除黑名單
BLOCK_KEYWORDS = ["購物", "測試", "TEST", "SHOP", "廣告", "酒店", "福利", "PREVIEW", "杭州", "兵", "廣播", "電台"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u",
]

# 優化 Session
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
    return {'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.choice(versions)} Safari/537.36'}

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"), logging.StreamHandler()]
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
                full_name = repo.get('full_name')
                branch = repo.get('default_branch', 'main')
                discovered.append(f"https://raw.githubusercontent.com/{full_name}/{branch}/live.m3u")
                discovered.append(f"https://raw.githubusercontent.com/{full_name}/{branch}/tv.m3u")
    except: pass
    return list(set(discovered))

# --- 【3. 核心抓取與過濾邏輯】 ---
def get_filtered_links(url):
    """抓取並回傳格式為 '台名,URL' 的列表"""
    results = []
    try:
        r = session.get(url, timeout=15, headers=get_random_headers(), verify=False)
        r.encoding = 'utf-8'
        lines = r.text.split('\n')
        
        temp_name = ""
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # M3U 處理
            if line.startswith("#EXTINF"):
                raw_name = cc.convert(line.split(',')[-1]).strip().upper()
                # 清洗台名杂质
                clean_name = re.sub(r'\[.*?\]|\(.*?\)|-.*|HD|SD|高清|超清|频道|频道', '', raw_name).strip()
                
                # 白名單 + 黑名單過濾
                if any(k.upper() in clean_name for k in KEYWORDS) and not any(b in clean_name for b in BLOCK_KEYWORDS):
                    temp_name = clean_name
                else:
                    temp_name = ""
            elif (line.startswith("http") or line.startswith("rtmp")) and temp_name:
                clean_url = line.split('$')[0].split('#')[0].split('|')[0].strip()
                if any(ext in clean_url.lower() for ext in [".m3u8", ".ts", ".flv", "m3u8"]):
                    results.append(f"{temp_name},{clean_url}")
                temp_name = ""
                
            # TXT 處理
            elif "," in line and "://" in line:
                parts = line.split(',')
                raw_name = cc.convert(parts[0]).upper()
                clean_name = re.sub(r'\[.*?\]|\(.*?\)|-.*|HD|SD|高清|超清', '', raw_name).strip()
                if any(k.upper() in clean_name for k in KEYWORDS) and not any(b in clean_name for b in BLOCK_KEYWORDS):
                    u = parts[1].strip().split('#')[0].split('$')[0]
                    results.append(f"{clean_name},{u}")
    except: pass
    return results

# --- 【4. 主程序】 ---
def main():
    logging.info("\n" + "="*60)
    logging.info(f"🚀 啟動【台名綁定模式】 (自動源上限:{MAX_AUTO_KEEP})")
    logging.info("="*60)

    fixed_content = []
    auto_lines = [] # 儲存 "台名,URL"
    is_auto_zone = False

    # 讀取現有檔案
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if "--- AUTO DISCOVERED SOURCES ---" in line:
                    is_auto_zone = True
                    continue
                if is_auto_zone:
                    if "," in line: auto_lines.append(line.strip())
                else:
                    fixed_content.append(line)

    # 建立 URL 去重集合
    existing_urls = set()
    for line in auto_lines:
        if "," in line: existing_urls.add(line.split(',')[1])
    for line in fixed_content:
        if "," in line: existing_urls.add(line.split(',')[1])

    # 執行抓取
    targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + search_github()))
    logging.info(f"📡 正在從 {len(targets)} 個源頭掃描...")

    new_discovered_count = 0
    with ThreadPoolExecutor(max_workers=30) as executor:
        all_results = list(executor.map(get_filtered_links, targets))
    
    for found_list in all_results:
        for item in found_list:
            name, url = item.split(',', 1)
            if url not in existing_urls:
                auto_lines.append(item)
                existing_urls.add(url)
                new_discovered_count += 1

    # 末位淘汰 (保持新鮮度)
    final_auto = auto_lines[-MAX_AUTO_KEEP:] if len(auto_lines) > MAX_AUTO_KEEP else auto_lines

    # 寫入檔案
    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        for line in fixed_content:
            f.write(line.strip() + "\n")
        f.write("\n# --- AUTO DISCOVERED SOURCES ---\n")
        for line in final_auto:
            f.write(line + "\n")
    
    logging.info(f"✅ 完成！新增: {new_discovered_count} 條，目前 sources.txt 總自動源: {len(final_auto)} 條。")

if __name__ == "__main__":
    main()
