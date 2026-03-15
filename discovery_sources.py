import requests, re, os, logging, time
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
SOURCE_FILE = "sources.txt"
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")
MAX_AUTO_KEEP = 5000  
cc = OpenCC('s2t')

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV", "HK", "TW", "GD", "CANTON"]

BLACK_LIST = ["ADULT", "PORN", "SEX", "SHOPPING", "MALL", "TEST", "DEMO", "GAME", "RADIO", "廣播", "購物", "遊戲"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

logging.basicConfig(level=logging.INFO, format='%(message)s', 
                    handlers=[logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"), 
                              logging.StreamHandler()])

# --- 【2. 核心分析邏輯】 ---
def analyze_source(url):
    stats = {"total": 0, "online": 0, "white": 0, "black": 0, "links": []}
    try:
        r = requests.get(url, timeout=20, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return stats
        
        lines = r.text.split('\n')
        temp_name = ""
        for line in lines:
            line = line.strip()
            if not line: continue
            
            name, link = "", ""
            if line.startswith("#EXTINF"):
                temp_name = cc.convert(line.split(',')[-1]).strip()
                continue 
            elif "://" in line:
                if "," in line and not line.startswith("http"):
                    parts = line.split(',')
                    name = cc.convert(parts[0]).strip()
                    link = parts[1].strip()
                else:
                    name = temp_name
                    link = line.strip()
            
            if link:
                stats["total"] += 1
                combined = (str(name) + str(link)).upper()
                if any(b.upper() in combined for b in BLACK_LIST):
                    stats["black"] += 1
                elif any(k.upper() in combined for k in KEYWORDS):
                    stats["white"] += 1
                    stats["links"].append(link.split('$')[0].split('#')[0].strip())
                temp_name = ""
        stats["online"] = stats["total"]
    except: pass
    return stats

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

# --- 【4. 主程序】 ---
def main():
    logging.info("\n" + "="*60)
    if SCAN_MODE == "MANUAL_ONLY":
        logging.info("🎯 【手動報告模式】（全網搜刮，但不改動 sources.txt）")
    else:
        logging.info("🌐 【自動更新模式】（全網搜刮，並保存結果）")
    logging.info("="*60)

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

    # 獲取所有掃描目標
    targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + search_github() + search_gitee()))
    logging.info(f"🔎 正在對全網 {len(targets)} 個源進行深度掃描...")

    new_discovered = []
    
    # 執行掃描 (ThreadPoolExecutor)
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(analyze_source, targets))
        
    for report in results:
        if report["white"] > 0:
            for l in report["links"]:
                if l not in current_all_set:
                    new_discovered.append(l)
                    current_all_set.add(l)

    # --- 最終決定邏輯 ---
    if SCAN_MODE == "FULL_SCAN":
        final_auto = (auto_links + new_discovered)[-MAX_AUTO_KEEP:]
        with open(SOURCE_FILE, "w", encoding="utf-8") as f:
            f.writelines([l.rstrip() + "\n" for l in fixed_content])
            f.write("\n# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---\n")
            for idx, link in enumerate(final_auto, 1):
                f.write(f"NEW_SOURCE_{idx},{link}\n")
        
        logging.info(f"\n✅ 自動更新完畢：新增 {len(new_discovered)} 個優質源。")
        logging.info(f"📊 數據已寫入 {SOURCE_FILE}。")
    else:
        logging.info(f"\n✨ 模擬掃描完畢！")
        logging.info(f"📢 今日全網發現新源：{len(new_discovered)} 個")
        logging.info(f"📝 提示：當前為 MANUAL 模式，所有新源只記錄在日誌，【未】寫入 sources.txt。")
        logging.info(f"💡 如果你想更新文件，請喺 GitHub Actions 選擇 FULL_SCAN 模式執行。")

if __name__ == "__main__":
    main()
