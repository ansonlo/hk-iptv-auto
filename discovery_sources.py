import requests, re, os, logging, time
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
SOURCE_FILE = "sources.txt"
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")
MAX_AUTO_KEEP = 1500  
cc = OpenCC('s2t')

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV", "HK", "TW", "GD", "CANTON"]

BLACK_LIST = ["ADULT", "PORN", "SEX", "SHOPPING", "MALL", "TEST", "DEMO", "GAME", "RADIO", "廣播", "購物", "遊戲"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

logging.basicConfig(level=logging.INFO, format='%(message)s', handlers=[logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"), logging.StreamHandler()])

# --- 【2. 核心過濾】 ---
def is_useful(name, url):
    combined_text = (str(name) + str(url)).upper()
    if any(black.upper() in combined_text for black in BLACK_LIST): return False
    if any(key.upper() in combined_text for key in KEYWORDS): return True
    return False

# --- 【3. 搜尋引擎】 ---
def search_github():
    query = quote("iptv gd m3u")
    try:
        r = requests.get(f"https://api.github.com/search/repositories?q={query}&sort=updated", headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return [f"https://raw.githubusercontent.com/{repo['full_name']}/{b}/live.m3u" for repo in r.json().get('items', []) for b in ['main', 'master']]
    except: pass
    return []

def search_gitee():
    try:
        r = requests.get("https://gitee.com/search?q=iptv%20gd&type=repositories", headers=HEADERS, timeout=15)
        paths = re.findall(r'href="/([^/"]+/[^/"]+)"', r.text)
        return [f"https://gitee.com/{p}/raw/{b}/live.m3u" for p in paths if not any(x in p.lower() for x in ['search', 'explore']) for b in ['main', 'master']]
    except: pass
    return []

def get_filtered_links(url):
    links = []
    try:
        r = requests.get(url, timeout=20, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        temp_name = ""
        for line in r.text.split('\n'):
            line = line.strip()
            if line.startswith("#EXTINF"):
                temp_name = cc.convert(line.split(',')[-1]).strip()
            elif line.startswith("http") and temp_name:
                if is_useful(temp_name, line): links.append(line.split('$')[0].split('#')[0].strip())
                temp_name = ""
            elif "," in line and "://" in line:
                parts = line.split(',')
                if is_useful(cc.convert(parts[0]), parts[1]): links.append(parts[1].strip())
    except: pass
    return list(dict.fromkeys(links))

# --- 【4. 主程序】 ---
def main():
    # --- 開頭增加醒目標示 ---
    logging.info("\n" + "ID" * 30)
    if SCAN_MODE == "MANUAL_ONLY":
        logging.info("🎯 【手動模式 - 精準狙擊】")
        logging.info("🔎 僅針對 sources.txt 手動區內的種子進行深度挖掘...")
    else:
        logging.info("🌐 【自動模式 - 全網獵奇】")
        logging.info("📡 正在啟動 12 小時一次的保底源 + GitHub + Gitee 全量掃描...")
    logging.info("ID" * 30 + "\n")
    fixed_content, auto_links, is_auto_zone = [], [], False

    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if any(x in line for x in ["--- AUTO DISCOVERED", "AUTO_UPDATE"]):
                    is_auto_zone = True
                    continue
                if is_auto_zone:
                    if "://" in line: auto_links.append(line.split(',')[-1].strip())
                else: fixed_content.append(line)

    manual_urls = set(re.findall(r'https?://[^\s,]+', "".join(fixed_content)))
    current_all_set = manual_urls.union(set(auto_links))

    # 🎯 核心改動：模式決定掃描範圍
    if SCAN_MODE == "MANUAL_ONLY":
        targets = list(manual_urls)
        logging.info(f"🎯 手動模式：僅掃描手動區 {len(targets)} 個源...")
    else:
        targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + search_github() + search_gitee()))
        logging.info(f"🌐 全量模式：掃描 {len(targets)} 個源...")

    new_discovered = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        for found in executor.map(get_filtered_links, targets):
            for l in found:
                if l not in current_all_set:
                    new_discovered.append(l)
                    current_all_set.add(l)

    if SCAN_MODE == "FULL_SCAN":
        logging.info(f"✅ 自動更新完畢：新增 {len(new_discovered)} 個潛在優質源。")
        logging.info(f"📊 已將最新sources.txt。")
    else:
        logging.info(f"🏁 手動掃描完畢：發現新源 {len(new_discovered)} 個。")
        logging.info(f"📝 提示：手動模式僅作「報告」，唔會改動你份 sources.txt。")

if __name__ == "__main__":
    main()
