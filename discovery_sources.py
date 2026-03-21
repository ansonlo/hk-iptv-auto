import requests, re, os, logging, time, urllib3, sys
from urllib.parse import quote, urljoin
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 1000
cc = OpenCC('s2t')

def log(msg):
    print(msg, flush=True)

GITHUB_EVENT = os.getenv('GITHUB_EVENT_NAME', 'local')
SCAN_MODE = "FULL_SCAN" if FULL_SCAN == 'workflow_dispatch' else "FULL_SCAN"

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

# 💡 新增：域名黑名單 (專門出廣告、404 或動態 Token 極易失效的源)
BLACKLIST_DOMAINS = [
    "freetv.fun", "m3u8.best", "akamaized.net", "livednow.com", 
    "p2p.com", "mtvnservices.com", "bitmovin.com"
]

# 💡 新增：廣告關鍵字 (頻道名包含這些字眼直接剔除)
AD_KEYWORDS = ["掃碼", "關注", "微信", "群", "福利", "加我", "支付", "APP", "提示", "廣告", "登錄"]

WHITELIST_DOMAINS = ["fanmingming", "Guovin", "hacks.tools", "gitee.com", "githubusercontent.com"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

# --- 【2. 核心過濾邏輯】 ---

def is_fake_by_size(m3u8_url):
    try:
        # 加入 allow_redirects 處理 302 跳轉源
        r = requests.get(m3u8_url, timeout=2, verify=False, headers=HEADERS, allow_redirects=True)
        if r.status_code != 200: return False
        
        ts_match = re.findall(r'(http.*?\.ts|[\w\d\-_/]+\.ts)', r.text)
        if not ts_match: return False
        
        ts_url = urljoin(m3u8_url, ts_match[0])
        ts_head = requests.head(ts_url, timeout=2, verify=False, headers=HEADERS, allow_redirects=True)
        
        size = ts_head.headers.get('Content-Length')
        if size:
            # 100KB 以下通常係廣告或錯誤提示
            return 0 < int(size) < 102400
        return False
    except: return False

def get_filtered_links(url):
    links = []
    kw_counts = {k.upper(): 0 for k in KEYWORDS}
    short_url = url[:50] + "..." if len(url) > 50 else url
    
    # 💡 檢查來源 URL 是否在黑名單
    if any(dom in url.lower() for dom in BLACKLIST_DOMAINS):
        return []

    try:
        is_safe = any(dom in url for dom in WHITELIST_DOMAINS)
        r = requests.get(url, timeout=12, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return []
            
        lines = r.text.split('\n')
        matched, faked, quota_hit, ad_blocked = 0, 0, 0, 0
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
                # temp_name 唔清空住，等下面檢查
            elif "," in line and "://" in line:
                parts = line.split(',')
                txt_name = cc.convert(parts[0]).upper()
                for k in KEYWORDS:
                    if k.upper() in txt_name:
                        target_link, current_kw = parts[1].strip(), k.upper()
                        temp_name = txt_name
                        break

            if target_link and current_kw:
                # 💡 1. 檢查頻道名或網址是否包含廣告關鍵字/黑名單域名
                if any(ad_k in temp_name for ad_k in AD_KEYWORDS) or \
                   any(dom in target_link.lower() for dom in BLACKLIST_DOMAINS):
                    ad_blocked += 1
                    temp_name = ""
                    continue

                # 2. 檢查配額 (每頻道 10 條)
                if kw_counts[current_kw] >= 10:
                    quota_hit += 1
                    temp_name = ""
                    continue

                # 3. 檢查體積 (非白名單源)
                if not is_safe and ".m3u8" in target_link.lower() and is_fake_by_size(target_link):
                    faked += 1
                    temp_name = ""
                    continue
                
                links.append(target_link)
                kw_counts[current_kw] += 1
                matched += 1
                temp_name = ""

        if matched > 0:
            log(f"  ✅ 來源: {short_url:50} | 執到: {matched:3d} | 假源: {faked:2d} | 廣告/黑名單: {ad_blocked:2d} | 爆額跳過: {quota_hit:3d}")
    except: pass
    return list(dict.fromkeys(links))

# --- 【3. 搜尋與主程序】 ---

def search_github():
    log("🔍 正在搜尋 GitHub 資源...")
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
    log("🔍 正在搜尋 Gitee 資源...")
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
    blocked_urls = set()
    target_tag = "# --- AUTO DISCOVERED SOURCES ---"
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                strip_line = line.strip()
                if strip_line.startswith("# http"):
                    url_part = strip_line.replace("#", "").strip().split('$')[0].split('#')[0]
                    blocked_urls.add(url_part)
                
                if target_tag in line: break
                fixed_content.append(line)
    
    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        for line in fixed_content: f.write(line)
        f.write(f"\n{target_tag}\n")
        count = 0
        unique_new = list(dict.fromkeys(new_links))
        for link in unique_new:
            # 💡 檢查呢條新爬返嚟嘅 link，係咪之前已經被標記為死源
            clean_link = link.split('$')[0].split('#')[0].strip()
            
            if clean_link not in blocked_urls:
                f.write(f"{link}\n")
                count += 1
            
            # 限制數量，保持檔案輕量
            if count >= MAX_AUTO_KEEP: break
            
    log(f"📝 檔案更新成功：已寫入 {count} 條新源（已避開 {len(blocked_urls)} 條封印死源）。")

def main():
    log("\n" + "="*85)
    log(f"🚀 啟動【抗廣告報表模式】 | 偵測事件: {GITHUB_EVENT} | 運行模式: {SCAN_MODE}")
    log("="*85)

    dynamic_urls = search_github() + search_gitee()
    all_targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + dynamic_urls))
    
    log(f"📡 共有 {len(all_targets)} 個目標源頭，準備開始深度過濾...")

    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(get_filtered_links, all_targets))
    
    raw_links = []
    for r in results: raw_links.extend(r)
    
    total_raw = len(raw_links)
    final_links = list(dict.fromkeys(raw_links))
    duplicates = total_raw - len(final_links)

    log("-" * 85)
    log(f"📊 執行總結：")
    log(f"   1. 原始提取總數： {total_raw:5d} 條")
    log(f"   2. 剔除重複連結： {duplicates:5d} 條 (跨來源重複)")
    log(f"   3. 最終入庫數量： {len(final_links):5d} 條")
    log("-" * 85)

    if SCAN_MODE != "MANUAL_ONLY" and final_links:
        update_source_file(final_links)
    elif SCAN_MODE == "MANUAL_ONLY":
        log("🛡️  [手動模式] 僅執行掃描，未寫入檔案。")

if __name__ == "__main__":
    main()
