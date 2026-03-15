import requests, re, os, logging, time
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置】 ---
SOURCE_FILE = "sources.txt"
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")
MAX_AUTO_KEEP = 5000  # 自動區保留上限
cc = OpenCC('s2t')

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "翡翠", "明珠", "港台", "廣東", "澳門", "CCTV"]
BLACK_LIST = ["ADULT", "PORN", "SHOPPING", "購物", "遊戲"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'}

logging.basicConfig(level=logging.INFO, format='%(message)s', handlers=[logging.StreamHandler()])

# --- 【2. 核心過濾】 ---
def analyze_source(url):
    links = []
    try:
        r = requests.get(url, timeout=15, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return links
        
        temp_name = ""
        for line in r.text.split('\n'):
            line = line.strip()
            if line.startswith("#EXTINF"):
                temp_name = cc.convert(line.split(',')[-1]).strip()
            elif "://" in line:
                name = temp_name if temp_name else "Unknown"
                link = line.strip()
                combined = (name + link).upper()
                if not any(b.upper() in combined for b in BLACK_LIST):
                    if any(k.upper() in combined for k in KEYWORDS):
                        links.append(link.split('$')[0].split('#')[0].strip())
                temp_name = ""
    except: pass
    return list(dict.fromkeys(links))

# --- 【3. 主程序】 ---
def main():
    logging.info(f"🚀 當前模式: {SCAN_MODE}")

    fixed_content = []      # 存放 # MY MANUAL SOURCES 內容
    old_auto_links = []     # 存放原本自動區嘅內容
    is_auto_zone = False

    # 1. 分割讀取現有的 sources.txt
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                # 碰到自動區標記，開始切換
                if "--- AUTO DISCOVERED" in line or "AUTO_UPDATE" in line:
                    is_auto_zone = True
                    continue
                
                if not is_auto_zone:
                    fixed_content.append(line)
                else:
                    if "://" in line:
                        link = line.split(',')[-1].strip()
                        old_auto_links.append(link)

    # 2. 獲取手動區所有現成嘅 URL (用嚟去重)
    manual_urls_only = set(re.findall(r'https?://[^\s,]+', "".join(fixed_content)))

    # 3. 全網搜刮新源
    targets = list(dict.fromkeys(BASE_DISCOVERY_URLS)) # 呢度可以加埋 search_github()
    new_found_links = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(analyze_source, targets))
        for links in results:
            new_found_links.extend(links)

    # 4. 合併舊自動區 + 新搵到嘅 Link，並進行去重
    # 去重原則：如果手動區已經有嘅，自動區就唔再重複收錄
    combined_auto = []
    seen = manual_urls_only.copy()
    
    # 優先保留舊嘅自動源，再加新源
    for l in (old_auto_links + new_found_links):
        if l not in seen:
            combined_auto.append(l)
            seen.add(l)

    # 5. 寫入文件 (僅限 FULL_SCAN)
    if SCAN_MODE == "FULL_SCAN":
        final_auto = combined_auto[-MAX_AUTO_KEEP:] # 保持數量限制
        with open(SOURCE_FILE, "w", encoding="utf-8") as f:
            # 寫入固定嘅手動區
            f.writelines([l.rstrip() + "\n" for l in fixed_content])
            # 寫入自動區標題
            f.write("\n# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---\n")
            # 寫入合併後嘅自動源
            for idx, link in enumerate(final_auto, 1):
                f.write(f"NEW_SOURCE_{idx},{link}\n")
        
        logging.info(f"✅ 更新成功！手動區保留，自動區現有 {len(final_auto)} 個源。")
    else:
        logging.info(f"✨ 報告：今日全網發現 {len(new_found_links)} 個新源，手動區有 {len(manual_urls_only)} 個源。")

if __name__ == "__main__":
    main()
