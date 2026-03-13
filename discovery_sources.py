import requests, re, os, logging, time
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 1500  # 既然係精準抓藥，保留 1500 條精華已經好夠用
cc = OpenCC('s2t')

# 核心白名單 (同你 main.py 保持一致)
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

# 基礎掃描清單
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

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.FileHandler("auto_repair.log", mode='a', encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# --- 【2. 搜尋引擎函數】 ---

def search_github():
    """搜尋 GitHub 最近更新的 IPTV 倉庫"""
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
    """搜尋 Gitee 相關項目"""
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

# --- 【3. 核心過濾抓取邏輯】 ---

def get_filtered_links(url):
    """提取並根據白名單過濾鏈接"""
    links = []
    try:
        # 增加 timeout 防止死卡
        r = requests.get(url, timeout=20, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        lines = r.text.split('\n')
        
        temp_name = ""
        for line in lines:
            line = line.strip()
            # 處理 M3U 格式
            if line.startswith("#EXTINF"):
                # 轉繁體並提取台名
                raw_name = cc.convert(line.split(',')[-1]).strip()
                temp_name = raw_name.upper()
            elif line.startswith("http") and temp_name:
                # 檢查是否在白名單內
                if any(k.upper() in temp_name for k in KEYWORDS):
                    clean_url = line.split('$')[0].split('#')[0].strip()
                    links.append(clean_url)
                temp_name = ""
            # 處理 TXT 格式 (台名,網址)
            elif "," in line and "://" in line:
                parts = line.split(',')
                txt_name = cc.convert(parts[0]).upper()
                if any(k.upper() in txt_name for k in KEYWORDS):
                    links.append(parts[1].strip())
    except:
        pass
    return list(dict.fromkeys(links))

# --- 【4. 主程序】 ---

def main():
    logging.info("\n" + "="*60)
    logging.info(f"🚀 啟動【精準抓藥模式】：僅保留白名單頻道 (MAX:{MAX_AUTO_KEEP})")
    logging.info("="*60)

    fixed_content = []
    auto_links = []
    is_auto_zone = False

    # 1. 讀取並保護手動區
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                raw_line = line.strip()
                if "--- AUTO DISCOVERED SOURCES ---" in raw_line:
                    is_auto_zone = True
                    continue
                
                if is_auto_zone:
                    if raw_line and not raw_line.startswith("#"):
                        auto_links.append(raw_line)
                else:
                    fixed_content.append(line)

    # 建立現有 Link 集合，避免重複
    current_all_set = set([l.strip() for l in auto_links])
    for line in fixed_content:
        if line.strip().startswith("http"):
            current_all_set.add(line.strip())

    # 2. 收集目標網址
    targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + search_github() + search_gitee()))
    new_discovered = []
    
    # 3. 並行掃描 (提高效率)
    logging.info(f"📡 開始掃描 {len(targets)} 個源頭...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(get_filtered_links, targets))
    
    for found_links in results:
        for l in found_links:
            if l not in current_all_set:
                new_discovered.append(l)
                current_all_set.add(l)

    # 4. 末位淘汰與合併
    combined_auto = auto_links + new_discovered
    final_auto = combined_auto[-MAX_AUTO_KEEP:] if len(combined_auto) > MAX_AUTO_KEEP else combined_auto

    # 5. 寫回檔案
    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        # 先寫入原本手動保留嘅內容
        for line in fixed_content:
            f.write(line)
        
        # 確保同自動區之間有換行
        if fixed_content and not fixed_content[-1].endswith("\n"):
            f.write("\n")
            
        f.write("\n# --- AUTO DISCOVERED SOURCES ---\n")
        
        # 寫入精選自動抓取嘅 Link
        for link in final_auto:
            if link.strip():
                f.write(f"{link.strip()}\n")
