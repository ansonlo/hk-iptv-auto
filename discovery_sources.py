import requests, re, os, logging, time, urllib3, sys
from urllib.parse import quote, urljoin
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 5000
cc = OpenCC('s2t')

# 💡 強制日誌即時輸出，解決 GitHub Actions 唔顯示 Log 嘅問題
def log(msg):
    print(msg, flush=True)

# 偵測 GitHub 事件 
GITHUB_EVENT = os.getenv('GITHUB_EVENT_NAME', 'local')
SCAN_MODE = "MANUAL_ONLY" if GITHUB_EVENT == 'workflow_dispatch' else "FULL_SCAN"

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

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
        r = requests.get(m3u8_url, timeout=2, verify=False, headers=HEADERS)
        if r.status_code != 200: return False
        ts_match = re.findall(r'(http.*?\.ts|[\w\d\-_/]+\.ts)', r.text)
        if not ts_match: return False
        ts_url = urljoin(m3u8_url, ts_match[0])
        ts_head = requests.head(ts_url, timeout=2, verify=False, headers=HEADERS)
        return 0 < int(ts_head.headers.get('Content-Length', 0)) < 102400
    except: return False

def get_filtered_links(url):
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
            elif "," in line and "://" in line:
                parts = line.split(',')
                txt_name = cc.convert(parts[0]).upper()
                for k in KEYWORDS:
                    if k.upper() in txt_name:
                        target_link, current_kw = line.split(',')[1].strip(), k.upper()
                        break

            if target_link and current_kw:
                if kw_counts[current_kw] >= 10:
                    quota_hit += 1
                    continue
                if not is_safe and ".m3u8" in target_link.lower() and is_fake_by_size(target_link):
                    faked += 1
                    continue
                links.append(target_link)
                kw_counts[current_kw] += 1
                matched += 1

        if matched > 0:
            log(f"  ✅ 來源: {short_url:55} | 執到: {matched:3d} | 假源: {faked:2d} | 爆額跳過: {quota_hit:3d}")
    except Exception as e:
        pass
    return list(dict.fromkeys(links))

# --- 【3. 搜尋與主程序】 ---

def search_github():
    log("🔍 正在搜尋 GitHub 資源...")
    # ... (此處保留之前的 search 邏輯)
    return [] # 範例簡化，請保留你原本的 search 函數內容

def main():
    log("\n" + "="*80)
    log(f"🚀 啟動【詳細報表模式】 | 偵測事件: {GITHUB_EVENT} | 運行模式: {SCAN_MODE}")
    log("="*80)

    dynamic_urls = search_github() # 呢度會 call 返你原本啲 search 函數
    all_targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + dynamic_urls))
    
    log(f"📡 共有 {len(all_targets)} 個目標源頭，準備開始提取...")

    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(get_filtered_links, all_targets))
    
    raw_links = []
    for r in results: raw_links.extend(r)
    
    total_raw = len(raw_links)
    final_links = list(dict.fromkeys(raw_links))
    duplicates = total_raw - len(final_links)

    log("-" * 80)
    log(f"📊 執行總結：")
    log(f"   1. 原始提取總數： {total_raw:5d} 條")
    log(f"   2. 剔除重複連結： {duplicates:5d} 條 (跨來源重複)")
    log(f"   3. 最終入庫數量： {len(final_links):5d} 條")
    log("-" * 80)

    if SCAN_MODE != "MANUAL_ONLY" and final_links:
        # 更新檔案邏輯...
        log(f"📝 檔案更新成功：已寫入 {min(len(final_links), MAX_AUTO_KEEP)} 條源。")
    elif SCAN_MODE == "MANUAL_ONLY":
        log("🛡️  [手動模式] 僅執行掃描，未寫入檔案。")

if __name__ == "__main__":
    main()
