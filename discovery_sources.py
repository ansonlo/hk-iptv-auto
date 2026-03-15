import requests, re, os, logging, time
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置】 ---
SOURCE_FILE = "sources.txt"
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")
MAX_AUTO_KEEP = 5000
cc = OpenCC('s2t')

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "翡翠", "明珠", "港台", "廣東", "澳門", "CCTV"]
BLACK_LIST = ["ADULT", "PORN", "SHOPPING", "購物", "遊戲"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'}

# 淨係顯示重要資訊
logging.basicConfig(level=logging.INFO, format='%(message)s')

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
                name = temp_name if temp_name else ""
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
    fixed_content = []
    old_auto_links = []
    is_auto_zone = False

    # 1. 讀取現有資料
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if "--- AUTO DISCOVERED" in line:
                    is_auto_zone = True
                    continue
                if not is_auto_zone:
                    fixed_content.append(line)
                else:
                    if "://" in line:
                        old_auto_links.append(line.split(',')[-1].strip())

    manual_urls = set(re.findall(r'https?://[^\s,]+', "".join(fixed_content)))

    # 2. 執行掃描
    targets = list(dict.fromkeys(BASE_DISCOVERY_URLS))
    new_found_links = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(analyze_source, targets))
        for links in results:
            new_found_links.extend(links)

    # 3. 去重與合併
    new_discovered = [l for l in set(new_found_links) if l not in manual_urls and l not in old_auto_links]
    
    # 4. 根據模式輸出結果 (淨係講發現咗幾個新源)
    if SCAN_MODE == "FULL_SCAN":
        final_auto = (old_auto_links + new_discovered)[-MAX_AUTO_KEEP:]
        with open(SOURCE_FILE, "w", encoding="utf-8") as f:
            f.writelines([l.rstrip() + "\n" for l in fixed_content])
            f.write("\n# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---\n")
            for idx, link in enumerate(final_auto, 1):
                f.write(f"NEW_SOURCE_{idx},{link}\n")
        
        logging.info(f"✅ 自動更新完畢：全網發現 {len(new_discovered)} 個新源，已寫入 sources.txt。")
    else:
        # 手動模式只會噴呢一句
        logging.info(f"✨ 模擬掃描完畢：全網發現 {len(new_discovered)} 個新源！")
        logging.info(f"📝 提示：當前係 MANUAL 模式，呢 {len(new_discovered)} 個新源【冇】寫入 sources.txt。")

if __name__ == "__main__":
    main()
