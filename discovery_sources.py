import requests, re, os, logging, time, urllib3
from urllib.parse import quote, urljoin
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 5000
cc = OpenCC('s2t')

# 💡 確保呢段喺 main 之外，等所有 function 都用到 SCAN_MODE MANUAL_ONLY
GITHUB_EVENT = os.getenv('GITHUB_EVENT_NAME', 'local')
if GITHUB_EVENT == 'workflow_dispatch':
    SCAN_MODE = "FULL_SCAN"
else:
    SCAN_MODE = "FULL_SCAN"

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

WHITELIST_DOMAINS = ["raw.githubusercontent.com", "gitee.com", "hacks.tools", "gitlab.com", "githubusercontent.com"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

logging.basicConfig(level=logging.INFO, format='%(message)s', handlers=[logging.StreamHandler()])

# --- 【2. 核心邏輯】 ---

def is_fake_by_size(m3u8_url):
    try:
        r = requests.get(m3u8_url, timeout=2, verify=False, headers=HEADERS)
        if r.status_code != 200: return False
        ts_match = re.findall(r'(http.*?\.ts|[\w\d\-_/]+\.ts)', r.text)
        if not ts_match: return False
        ts_url = ts_match[0]
        if not ts_url.startswith("http"):
            ts_url = urljoin(m3u8_url, ts_url)
        ts_head = requests.head(ts_url, timeout=2, verify=False, headers=HEADERS)
        f_size = int(ts_head.headers.get('Content-Length', 0))
        return 0 < f_size < 102400
    except: return False

def get_filtered_links(url):
    links = []
    short_url = url[:60] + "..." if len(url) > 60 else url
    try:
        is_safe_source = any(dom in url for dom in WHITELIST_DOMAINS)
        r = requests.get(url, timeout=15, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return []
        
        lines = r.text.split('\n')
        match_count = 0
        temp_name = ""
        
        for line in lines:
            line = line.strip()
            target_link = ""
            if line.startswith("#EXTINF"):
                temp_name = cc.convert(line.split(',')[-1]).strip().upper()
                continue
            elif line.startswith("http") and temp_name:
                if any(k.upper() in temp_name for k in KEYWORDS):
                    target_link = line.split('$')[0].split('#')[0].strip()
                temp_name = ""
            elif "," in line and "://" in line:
                parts = line.split(',')
                txt_name = cc.convert(parts[0]).upper()
                if any(k.upper() in txt_name for k in KEYWORDS):
                    target_link = parts[1].strip()

            if target_link:
                # 💡 修正邏輯：無論如何都 match_count+1，只有非安全源先驗證體積
                if not is_safe_source and ".m3u8" in target_link.lower():
                    if is_fake_by_size(target_link):
                        continue
                links.append(target_link)
                match_count += 1

        if match_count > 0:
            logging.info(f"  ✅ 成功執到 {match_count:4d} 條藥方 | 來源: {short_url}")
    except: pass
    return list(dict.fromkeys(links))

# --- 【3. 搜尋模組】 ---

def search_github():
    query = quote("iptv gd m3u")
    api_url = f"https://api.github.com/search/repositories?q={query}&sort=updated"
    discovered = []
    try:
        r = requests.get(api_url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            for repo in r.json().get('items', []):
                name = repo.get('full_name')
                discovered.append(f"https://raw.githubusercontent.com/{name}/main/live.m3u")
                discovered.append(f"https://raw.githubusercontent.com/{name}/master/live.m3u")
    except: pass
    return discovered

def search_gitee():
    discovered = []
    try:
        r = requests.get("https://gitee.com/search?q=iptv%20gd&type=repositories", headers=HEADERS, timeout=10)
        for p in re.findall(r'href="/([^/"]+/[^/"]+)"', r.text):
            if not any(x in p.lower() for x in ['search', 'explore', 'help']):
                discovered.append(f"https://gitee.com/{p}/raw/main/live.m3u")
    except: pass
    return list(set(discovered))

# --- 【4. 檔案與主程序】 ---

def update_source_file(new_links):
    fixed_content = []
    target_tag = "# --- AUTO DISCOVERED SOURCES ---"
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if target_tag in line: break
                fixed_content.append(line)
    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        for line in fixed_content: f.write(line)
        f.write(f"\n{target_tag}\n")
        count = 0
        for link in new_links[:MAX_AUTO_KEEP]:
            f.write(f"{link}\n")
            count += 1
    logging.info(f"📝 檔案更新成功：已寫入 {count} 條新源。")

def main():
    logging.info("\n" + "="*75)
    logging.info(f"🚀 啟動【智能加速模式】 | 模式: {SCAN_MODE}")
    logging.info("="*75)

    dynamic_urls = search_github() + search_gitee()
    all_targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + dynamic_urls))
    
    logging.info(f"📡 鎖定 {len(all_targets)} 個源頭，準備提取...")

    with ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(get_filtered_links, all_targets))
    
    final_links = []
    for r in results: final_links.extend(r)
    final_links = list(dict.fromkeys(final_links))

    logging.info("-" * 75)
    logging.info(f"🏁 執藥完畢：本次共發現 {len(final_links)} 條符合要求嘅源。")

    if SCAN_MODE != "MANUAL_ONLY" and final_links:
        update_source_file(final_links)

if __name__ == "__main__":
    main()
