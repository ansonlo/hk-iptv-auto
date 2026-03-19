import requests, re, os, logging, time, urllib3
from urllib.parse import quote, urljoin
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 5000
cc = OpenCC('s2t')

# 偵測 GitHub 事件 (手動 vs 自動) MANUAL_ONLY
GITHUB_EVENT = os.getenv('GITHUB_EVENT_NAME', 'local')
if GITHUB_EVENT == 'workflow_dispatch':
    SCAN_MODE = "FULL_SCAN"
    logging.info(">>> 偵測到手動撳掣：啟動 MANUAL_ONLY 模式 (唔會寫入檔案) <<<")
else:
    SCAN_MODE = ""
    logging.info(">>> 偵測到自動任務：啟動 FULL_SCAN 模式 <<<")

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

# 白名單：知名大佬的源，信任度高，可跳過體積校驗以加速
WHITELIST_DOMAINS = ["fanmingming", "Guovin", "hacks.tools", "gitee.com", "githubusercontent.com"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
logging.basicConfig(level=logging.INFO, format='%(message)s', handlers=[logging.StreamHandler()])

# --- 【2. 核心校驗邏輯】 ---

def is_fake_by_size(m3u8_url):
    """檢查第一個切片的 Content-Length，剔除假源"""
    try:
        r = requests.get(m3u8_url, timeout=2, verify=False, headers=HEADERS)
        if r.status_code != 200: return False
        ts_match = re.findall(r'(http.*?\.ts|[\w\d\-_/]+\.ts)', r.text)
        if not ts_match: return False
        ts_url = urljoin(m3u8_url, ts_match[0])
        ts_head = requests.head(ts_url, timeout=2, verify=False, headers=HEADERS)
        f_size = int(ts_head.headers.get('Content-Length', 0))
        return 0 < f_size < 102400  # 小於 100KB 判定為假
    except: return False

def get_filtered_links(url):
    """提取網址 + 頻道配額 + 體積校驗 + 詳細 Log"""
    links = []
    kw_counts = {k.upper(): 0 for k in KEYWORDS}
    short_url = url[:50] + "..." if len(url) > 50 else url
    
    try:
        is_safe = any(dom in url for dom in WHITELIST_DOMAINS)
        r = requests.get(url, timeout=12, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return []
            
        lines = r.text.split('\n')
        matched, faked, quota_hit = 0, 0, 0
        temp_name = ""
        
        for line in lines:
            line = line.strip()
            target_link, current_kw = "", ""
            
            if line.startswith("#EXTINF"):
                temp_name = cc.convert(line.split(',')[-1]).strip().upper()
                continue
            elif line.startswith("http") and temp_name:
                for k in KEYWORDS:
                    if k.upper() in temp_name:
                        target_link, current_kw = line.split('$')[0].split('#')[0].strip(), k.upper()
                        break
                temp_name = ""
            elif "," in line and "://" in line: # TXT 格式
                txt_name = cc.convert(line.split(',')[0]).upper()
                for k in KEYWORDS:
                    if k.upper() in txt_name:
                        target_link, current_kw = line.split(',')[1].strip(), k.upper()
                        break

            if target_link and current_kw:
                # 1. 頻道配額檢查 (每個來源每頻道限 10 條)
                if kw_counts[current_kw] >= 10:
                    quota_hit += 1
                    continue
                # 2. 體積檢查 (非安全源才驗證)
                if not is_safe and ".m3u8" in target_link.lower() and is_fake_by_size(target_link):
                    faked += 1
                    continue
                
                links.append(target_link)
                kw_counts[current_kw] += 1
                matched += 1

        if matched > 0:
            logging.info(f"  ✅ {short_url:55} | 執到: {matched:3d} | 假源: {faked:2d} | 爆額: {quota_hit:3d}")
            
    except: pass
    return list(dict.fromkeys(links))

# --- 【3. 搜尋與寫入模組】 ---

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
        r = requests.get("https://gitee.com/search?q=iptv%20gd&type=repositories", headers=HEADERS, timeout=10, verify=False)
        for p in re.findall(r'href="/([^/"]+/[^/"]+)"', r.text):
            if not any(x in p.lower() for x in ['search', 'explore', 'help']):
                discovered.append(f"https://gitee.com/{p}/raw/main/live.m3u")
    except: pass
    return list(set(discovered))

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
    logging.info(f"📝 檔案更新成功：已寫入 {count} 條精華源。")

# --- 【4. 主程序】 ---

def main():
    logging.info("\n" + "="*75)
    logging.info(f"🚀 啟動【詳細報表模式】 | 模式: {SCAN_MODE}")
    logging.info("="*75)

    dynamic_urls = search_github() + search_gitee()
    all_targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + dynamic_urls))
    
    logging.info(f"📡 鎖定 {len(all_targets)} 個源頭，執行多線程深度校驗...")

    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(get_filtered_links, all_targets))
    
    raw_links = []
    for r in results: raw_links.extend(r)
    
    total_raw = len(raw_links)
    final_links = list(dict.fromkeys(raw_links))
    duplicates = total_raw - len(final_links)

    logging.info("-" * 75)
    logging.info(f"📊 執行總結：")
    logging.info(f"   - 原始提取總數： {total_raw:5d} 條")
    logging.info(f"   - 剔除重複連結： {duplicates:5d} 條")
    logging.info(f"   - 最終入庫數量： {len(final_links):5d} 條")
    logging.info("-" * 75)

    if SCAN_MODE != "MANUAL_ONLY" and final_links:
        update_source_file(final_links)

if __name__ == "__main__":
    main()
