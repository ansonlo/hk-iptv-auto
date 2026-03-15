import requests, re, os, logging, time
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
SOURCE_FILE = "sources.txt"
# 從 YAML 環境變數讀取模式，預設為 FULL_SCAN
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")
MAX_AUTO_KEEP = 5000  # 自動區最多條精華
cc = OpenCC('s2t')

# ⚪ 白名單 (KEYWORDS)：符合呢啲字眼先會執入去
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV", "HK", "TW", "GD", "CANTON"]

# ⚫ 黑名單 (BLACK_LIST)：中咗即踢，保證無垃圾
BLACK_LIST = ["ADULT", "PORN", "SEX", "SHOPPING", "MALL", "TEST", "DEMO", "GAME", "RADIO", "廣播", "購物", "遊戲"]

# 🚀 精簡保底源：只留最穩定、高質嘅兩大龍頭，確保唔會斷糧
BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u",
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# 設定日誌，同時輸出到文件同螢幕
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# --- 【2. 核心過濾函數】 ---

def is_useful(name, url):
    """結合黑白名單判斷是否為優質源"""
    combined_text = (str(name) + str(url)).upper()
    if any(black.upper() in combined_text for black in BLACK_LIST):
        return False
    if any(key.upper() in combined_text for key in KEYWORDS):
        return True
    return False

# --- 【3. 全網搜尋引擎】 ---

def search_github():
    """去 GitHub 搵最近更新嘅 IPTV 項目"""
    query = quote("iptv gd m3u")
    api_url = f"https://api.github.com/search/repositories?q={query}&sort=updated"
    discovered = []
    try:
        r = requests.get(api_url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            repos = r.json().get('items', [])
            for repo in repos:
                name = repo.get('full_name')
                discovered.append(f"https://raw.githubusercontent.com/{name}/main/live.m3u")
                discovered.append(f"https://raw.githubusercontent.com/{name}/master/iptv.m3u")
    except: pass
    return discovered

def search_gitee():
    """去 Gitee 搵國內嘅 IPTV 項目"""
    search_url = "https://gitee.com/search?q=iptv%20gd&type=repositories"
    discovered = []
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=15)
        paths = re.findall(r'href="/([^/"]+/[^/"]+)"', r.text)
        for p in paths:
            if any(x in p.lower() for x in ['search', 'explore', 'help']): continue
            discovered.append(f"https://gitee.com/{p}/raw/main/live.m3u")
            discovered.append(f"https://gitee.com/{p}/raw/master/iptv.m3u")
    except: pass
    return list(set(discovered))

def get_filtered_links(url):
    """下載並過濾單個來源內嘅連結"""
    links = []
    try:
        r = requests.get(url, timeout=20, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        lines = r.text.split('\n')
        temp_name = ""
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                temp_name = cc.convert(line.split(',')[-1]).strip()
            elif line.startswith("http") and temp_name:
                if is_useful(temp_name, line):
                    clean_url = line.split('$')[0].split('#')[0].strip()
                    links.append(clean_url)
                temp_name = ""
            elif "," in line and "://" in line:
                parts = line.split(',')
                txt_name = cc.convert(parts[0]).strip()
                txt_url = parts[1].strip()
                if is_useful(txt_name, txt_url):
                    links.append(txt_url)
    except: pass
    return list(dict.fromkeys(links))

# --- 【4. 主程序邏輯】 ---

def main():
    logging.info("\n" + "="*60)
    logging.info(f"🚀 啟動【精準穩定模式】 | 模式: {SCAN_MODE}")
    logging.info("="*60)

    fixed_content = []
    auto_links = []
    is_auto_zone = False

    # 1. 讀取 sources.txt，保護手動區，分離自動區
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                raw_line = line.strip()
                if any(x in raw_line for x in ["--- AUTO DISCOVERED", "AUTO_UPDATE"]):
                    is_auto_zone = True
                    continue
                if is_auto_zone:
                    if "://" in raw_line:
                        auto_links.append(raw_line.split(',')[-1].strip())
                else:
                    fixed_content.append(line)

    # 2. 跨區去重準備
    manual_urls = set(re.findall(r'https?://[^\s,]+', "".join(fixed_content)))
    current_all_set = manual_urls.union(set(auto_links))

    # 3. 根據模式決定掃描路徑
    if SCAN_MODE == "MANUAL_ONLY":
        # 手動模式：快速檢測手動區現有連結
        targets = list(manual_urls)
    else:
        # 星期一全量模式：保底源 + GitHub + Gitee
        targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + search_github() + search_gitee()))

    # 4. 並行掃描 (10線程)
    new_discovered = []
    logging.info(f"📡 正在從 {len(targets)} 個來源中執藥...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(get_filtered_links, targets))
    
    for found_links in results:
        for l in found_links:
            if l not in current_all_set:
                new_discovered.append(l)
                current_all_set.add(l)

    # 5. 更新檔案 (僅在 FULL_SCAN 模式寫入)
    if SCAN_MODE == "FULL_SCAN":
        combined_auto = auto_links + new_discovered
        # 末位淘汰，保留最新 1500 條
        final_auto = combined_auto[-MAX_AUTO_KEEP:] if len(combined_auto) > MAX_AUTO_KEEP else combined_auto
        
        with open(SOURCE_FILE, "w", encoding="utf-8") as f:
            for line in fixed_content:
                f.write(line.rstrip() + "\n")
            f.write("\n# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---\n")
            for idx, link in enumerate(final_auto, 1):
                f.write(f"NEW_SOURCE_{idx},{link}\n")
        
        logging.info(f"✅ 更新成功！新增 {len(new_discovered)} 條，自動區總數: {len(final_auto)}")
    else:
        logging.info(f"📊 [報告] 掃描完成。發現新源 {len(new_discovered)} 個。手動模式不改動檔案。")

if __name__ == "__main__":
    main()
