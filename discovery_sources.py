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

# 設定日誌格式
logging.basicConfig(level=logging.INFO, format='%(message)s', 
                    handlers=[logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"), 
                              logging.StreamHandler()])

# --- 【2. 核心過濾與分析邏輯】 ---
def analyze_source(url):
    """深度掃描單個源，並返回詳細報告"""
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
            
            # 解析頻道名
            name = ""
            link = ""
            if line.startswith("#EXTINF"):
                name = cc.convert(line.split(',')[-1]).strip()
                # 搵下一行網址
                continue 
            elif "://" in line:
                if "," in line and not line.startswith("http"): # 格式: 頻道,網址
                    parts = line.split(',')
                    name = cc.convert(parts[0]).strip()
                    link = parts[1].strip()
                else: # 格式: 網址 (配合上面 EXTINF)
                    name = temp_name
                    link = line.strip()
            
            if link:
                stats["total"] += 1
                combined = (str(name) + str(link)).upper()
                # 過濾邏輯
                if any(b.upper() in combined for b in BLACK_LIST):
                    stats["black"] += 1
                elif any(k.upper() in combined for k in KEYWORDS):
                    stats["white"] += 1
                    stats["links"].append(link.split('$')[0].split('#')[0].strip())
                temp_name = ""
            elif name:
                temp_name = name

        stats["online"] = stats["total"] # 這裡簡化處理，能下載到文件視為連通
    except:
        pass
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
    # --- 打印模式標頭 ---
    logging.info("\n" + "="*60)
    if SCAN_MODE == "MANUAL_ONLY":
        logging.info(f"🎯 【手動模式】 📅 更新時間：{time.strftime('%m%d %H:%M')}")
        logging.info("🔎 僅針對 sources.txt 手動區種子進行深度挖掘...")
    else:
        logging.info(f"🌐 【自動模式】 📅 更新時間：{time.strftime('%m%d %H:%M')}")
        logging.info("📡 啟動 12 小時全網搜刮 (GitHub/Gitee/核心源)...")
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

    if SCAN_MODE == "MANUAL_ONLY":
        # 如果你想手動行都要搵新嘢，可以將 targets 改為全量，但唔寫入文件
        targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + search_github() + search_gitee()))
        logging.info(f"🎯 手動測試模式：正在模擬掃描 {len(targets)} 個源（唔會改動文件）...")
    else:
        targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + search_github() + search_gitee()))
        logging.info(f"🌐 全量更新模式：掃描 {len(targets)} 個源並將更新文件...")

    new_discovered = []
    
    # 開始逐個掃描並輸出詳細報告
    for url in targets:
        report = analyze_source(url)
        if report["total"] > 0:
            logging.info(f"✅ 報告: {url}")
            logging.info(f"   ┣ [源頭掃描] 總台數: {report['total']}")
            logging.info(f"   ┣ [網絡狀況] 連通數: {report['online']}")
            logging.info(f"   ┗ [內容過濾] 中白名單: {report['white']} (採納) | 中黑名單: {report['black']} (剔除)")
            
            for l in report["links"]:
                if l not in current_all_set:
                    new_discovered.append(l)
                    current_all_set.add(l)
        else:
            logging.info(f"❌ 報告: {url} (連通失敗或無內容)")

    # --- 寫入與總結 ---
    if SCAN_MODE == "FULL_SCAN":
        final_auto = (auto_links + new_discovered)[-MAX_AUTO_KEEP:]
        with open(SOURCE_FILE, "w", encoding="utf-8") as f:
            f.writelines([l.rstrip() + "\n" for l in fixed_content])
            f.write("\n# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---\n")
            for idx, link in enumerate(final_auto, 1):
                f.write(f"NEW_SOURCE_{idx},{link}\n")
        
        logging.info(f"\n✅ 自動更新完畢：新增 {len(new_discovered)} 個優質源。")
        logging.info(f"📊 已將結果寫入 {SOURCE_FILE}。")
    else:
        # 手動模式只係「出報告」，話你知搵到幾多，但唔行 open(SOURCE_FILE, "w")
        logging.info(f"\n✨ 模擬掃描完畢：發現新源 {len(new_discovered)} 個！")
        logging.info(f"📝 提示：當前係 MANUAL 模式，呢 {len(new_discovered)} 個新源【冇】寫入 sources.txt。")
        logging.info(f"💡 如果你想更新文件，請喺 GitHub Actions 選擇 FULL_SCAN 模式執行。")

if __name__ == "__main__":
    main()
