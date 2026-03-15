import requests, re, os, logging, time
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置】 ---
SOURCE_FILE = "sources.txt"
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")
MAX_AUTO_KEEP = 5000
cc = OpenCC('s2t')

# 關鍵字與黑名單
KEYWORDS = ["VIUTV", "HOY", "RTHK", "JADE", "PEARL", "J2", "J5", "NOW", "無線", "有線", "翡翠", "明珠", "港台", 
            "廣東", "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", 
            "緯來", "年代", "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]
BLACK_LIST = ["ADULT", "PORN", "SHOPPING", "購物", "遊戲", "浙江", "湖南", "湖北", "江蘇", "福建", "杭州"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'}

logging.basicConfig(level=logging.INFO, format='%(message)s')

# --- 【2. 核心過濾與報告邏輯】 ---
def analyze_source(url):
    report = {"url": url, "total": 0, "white": 0, "black": 0, "black_names": [], "links": []}
    try:
        r = requests.get(url, timeout=15, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return report
        
        temp_name = ""
        for line in r.text.split('\n'):
            line = line.strip()
            if line.startswith("#EXTINF"):
                temp_name = cc.convert(line.split(',')[-1]).strip()
            elif "://" in line:
                report["total"] += 1
                name = temp_name if temp_name else "未知"
                link = line.strip()
                combined = (name + link).upper()
                
                if any(b.upper() in combined for b in BLACK_LIST):
                    report["black"] += 1
                    report["black_names"].append(name)
                elif any(k.upper() in combined for k in KEYWORDS):
                    report["white"] += 1
                    report["links"].append(link.split('$')[0].split('#')[0].strip())
                temp_name = ""
    except: pass
    return report

# --- 【3. 主程序】 ---
def main():
    logging.info(f"\n🚀 啟動搜刮 - 模式: {SCAN_MODE}")
    
    # 1. 讀取現有庫 (用於去重)
    fixed_content, old_auto_links = [], []
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            is_auto = False
            for line in f:
                if "--- AUTO DISCOVERED" in line: is_auto = True; continue
                if not is_auto: fixed_content.append(line)
                else: 
                    if "://" in line: old_auto_links.append(line.split(',')[-1].strip())

    manual_urls = set(re.findall(r'https?://[^\s,]+', "".join(fixed_content)))
    existing_urls = manual_urls.union(set(old_auto_links))

    # 2. 執行掃描並輸出詳細樹狀報告
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(analyze_source, BASE_DISCOVERY_URLS))

    new_found_all = []
    for res in results:
        logging.info(f"\n✅ 報告: {res['url']}")
        logging.info(f" ┣ [源頭掃描] 總台數: {res['total']}")
        logging.info(f" ┗ [內容過濾] 採納: {res['white']} | 剔除: {res['black']}")
        
        if res['black_names'] and SCAN_MODE == "MANUAL_ONLY":
            logging.info(f" ┗ [🚫 黑名單細節]:")
            for i in range(0, min(len(res['black_names']), 20), 5):
                logging.info("      " + ", ".join(res['black_names'][i:i+5]))
        
        new_found_all.extend(res['links'])

    # 3. 去重：只計「庫入面完全冇」嘅新 Link
    unique_new = [l for l in set(new_found_all) if l not in existing_urls]

    # 4. 寫入與最終總結
    if SCAN_MODE == "FULL_SCAN":
        final_auto = (old_auto_links + unique_new)[-MAX_AUTO_KEEP:]
        with open(SOURCE_FILE, "w", encoding="utf-8") as f:
            f.writelines([l.rstrip() + "\n" for l in fixed_content])
            f.write("\n# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---\n")
            for idx, link in enumerate(final_auto, 1):
                f.write(f"NEW_SOURCE_{idx},{link}\n")
        logging.info(f"\n✨ 總結：全網發現 {len(unique_new)} 個全新源，已更新至 {SOURCE_FILE}")
    else:
        logging.info(f"\n✨ 總結：全網掃描完畢！發現 {len(unique_new)} 個全新源 (MANUAL 模式不寫入)")

if __name__ == "__main__":
    main()
