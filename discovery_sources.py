import requests, re, os, logging, time
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 5000
cc = OpenCC('s2t')

GITHUB_EVENT = os.getenv('GITHUB_EVENT_NAME', 'local')

if GITHUB_EVENT == 'workflow_dispatch':
    SCAN_MODE = "MANUAL_ONLY"
else:
    # 只要唔係手動撳掣（例如定時任務 schedule），就全量更新
    SCAN_MODE = "FULL_SCAN"

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

# 固定優質源頭清單
BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler()]
)

# --- 【2. 跨平台搜尋模組】 ---

def search_github():
    """搜尋 GitHub 最新更新項目"""
    query = quote("iptv gd m3u")
    api_url = f"https://api.github.com/search/repositories?q={query}&sort=updated"
    discovered = []
    try:
        r = requests.get(api_url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            repos = r.json().get('items', [])
            for repo in repos:
                name = repo.get('full_name')
                discovered.append(f"https://raw.githubusercontent.com/{name}/main/live.m3u")
                discovered.append(f"https://raw.githubusercontent.com/{name}/master/iptv.m3u")
    except: pass
    return discovered

def search_gitee():
    """搜尋 Gitee 項目"""
    discovered = []
    search_url = "https://gitee.com/search?q=iptv%20gd&type=repositories"
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        paths = re.findall(r'href="/([^/"]+/[^/"]+)"', r.text)
        for p in paths:
            if any(x in p.lower() for x in ['search', 'explore', 'help']): continue
            discovered.append(f"https://gitee.com/{p}/raw/main/live.m3u")
            discovered.append(f"https://gitee.com/{p}/raw/master/iptv.m3u")
    except: pass
    return list(set(discovered))

def search_gitcode():
    """搜尋 GitCode (CSDN) 項目"""
    discovered = []
    search_url = "https://gitcode.com/explore/search?q=iptv%20gd"
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        paths = re.findall(r'href="/([^/"]+/[^/"]+)"', r.text)
        for p in paths:
            if any(x in p.lower() for x in ['explore', 'help', 'search', 'topic']): continue
            discovered.append(f"https://gitcode.com/{p}/raw/main/live.m3u")
            discovered.append(f"https://gitcode.com/{p}/raw/master/iptv.m3u")
    except: pass
    return list(set(discovered))

# --- 【3. 核心過濾與詳細報告邏輯】 ---

def get_filtered_links(url):
    """提取網址，並喺 Log 輸出詳細結果"""
    links = []
    short_url = url[:60] + "..." if len(url) > 60 else url
    try:
        r = requests.get(url, timeout=12, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return []
            
        lines = r.text.split('\n')
        match_count = 0
        temp_name = ""
        
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                temp_name = cc.convert(line.split(',')[-1]).strip().upper()
            elif line.startswith("http") and temp_name:
                if any(k.upper() in temp_name for k in KEYWORDS):
                    match_count += 1
                    links.append(line.split('$')[0].split('#')[0].strip())
                temp_name = ""
            elif "," in line and "://" in line: # TXT 格式
                txt_name = cc.convert(line.split(',')[0]).upper()
                if any(k.upper() in txt_name for k in KEYWORDS):
                    match_count += 1
                    links.append(line.split(',')[1].strip())

        if match_count > 0:
            logging.info(f"  ✅ 成功執到 {match_count:3d} 條藥方 | 來源: {short_url}")
            
    except: pass
    return list(dict.fromkeys(links))

# --- 【4. 主程序與檔案寫入邏輯】 ---

def update_source_file(new_links):
    """將新搵到嘅源寫入自動區，對齊最新長標籤"""
    fixed_content = []
    # 🌟 已經改為你指定嘅最新長標籤
    target_tag = "# --- AUTO DISCOVERED SOURCES ---"

    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if target_tag in line: break # 遇到自動區標籤就停止，保留上面嘅固定區
                fixed_content.append(line)

    try:
        with open(SOURCE_FILE, "w", encoding="utf-8") as f:
            for line in fixed_content: f.write(line)
            if fixed_content and not fixed_content[-1].endswith("\n"): f.write("\n")
            
            f.write(f"\n{target_tag}\n") # 寫入標籤
            
            count = 0
            for link in new_links[:MAX_AUTO_KEEP]:
                if link.strip():
                    f.write(f"{link.strip()}\n")
                    count += 1
        logging.info(f"📝 檔案更新成功：已寫入 {count} 條新源。")
    except Exception as e:
        logging.error(f"❌ 寫入檔案失敗: {e}")

def main():
    logging.info("\n" + "="*75)
    logging.info(f"🚀 啟動【全平台執藥模式】 | 模式: {SCAN_MODE}")
    logging.info("="*75)

    # 1. 跨平台搜刮入口
    logging.info("🔍 正在掃描 GitHub, Gitee, GitCode 的最新項目...")
    dynamic_urls = search_github() + search_gitee() + search_gitcode()
    all_targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + dynamic_urls))
    
    logging.info(f"📡 鎖定 {len(all_targets)} 個潛在源頭，準備精準提取...")

    # 2. 多線程執藥
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(get_filtered_links, all_targets))
    
    final_links = []
    for r in results: final_links.extend(r)
    final_links = list(dict.fromkeys(final_links))

    logging.info("-" * 75)
    logging.info(f"🏁 執藥完畢：本次共發現 {len(final_links)} 條符合白名單嘅源。")

    # 3. 核心保護邏輯
    if SCAN_MODE == "MANUAL_ONLY":
        logging.info("🛡️  [手動保護] 本次發現嘅新源【唔會】寫入檔案，僅供日誌參考。")
    else:
        update_source_file(final_links)

if __name__ == "__main__":
    main()
