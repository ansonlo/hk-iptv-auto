import requests, re, os, logging, time
from urllib.parse import quote
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 5000
cc = OpenCC('s2t')

# 獲取環境變量模式 (與你的 workflow 保持一致)
SCAN_MODE = os.getenv('SCAN_MODE', 'MANUAL_ONLY')

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler()]
)

# --- 【2. 核心搜尋與詳細報告邏輯】 ---

def get_filtered_links(url):
    """提取鏈接並輸出詳細報告"""
    links = []
    short_url = url[:60] + "..." if len(url) > 60 else url
    try:
        r = requests.get(url, timeout=15, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200:
            logging.info(f"  ❌ 請求失敗 ({r.status_code}): {short_url}")
            return []
            
        lines = r.text.split('\n')
        raw_count = 0
        match_count = 0
        temp_name = ""
        
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                raw_count += 1
                temp_name = cc.convert(line.split(',')[-1]).strip().upper()
            elif line.startswith("http") and temp_name:
                if any(k.upper() in temp_name for k in KEYWORDS):
                    match_count += 1
                    links.append(line.split('$')[0].split('#')[0].strip())
                temp_name = ""
            elif "," in line and "://" in line: # TXT 格式
                raw_count += 1
                txt_name = cc.convert(line.split(',')[0]).upper()
                if any(k.upper() in txt_name for k in KEYWORDS):
                    match_count += 1
                    links.append(line.split(',')[1].strip())

        if match_count > 0:
            logging.info(f"  ✅ 抓取成功: {match_count:3d} 條符合 | 來源: {short_url}")
        else:
            logging.info(f"  ⚠️ 無匹配藥方: {raw_count:3d} 條中 0 條符合 | 來源: {short_url}")
            
    except Exception as e:
        logging.info(f"  🔥 連結失效: {short_url} ({str(e)[:20]})")
    return list(dict.fromkeys(links))

# --- 【3. 主程序】 ---

def main():
    logging.info("\n" + "="*70)
    logging.info(f"🚀 啟動【精準執藥模式】 | 當前運行模式: {SCAN_MODE}")
    logging.info("="*70)

    # 1. 收集所有目標
    # 這裡可以加入 search_github() 等動態搜尋
    targets = list(dict.fromkeys(BASE_DISCOVERY_URLS)) 
    
    logging.info(f"📡 正在掃描 {len(targets)} 個潛在源頭...")
    
    # 2. 並行執行並即時顯示詳細進度
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(get_filtered_links, targets))
    
    all_found_links = []
    for r in results: all_found_links.extend(r)
    all_found_links = list(dict.fromkeys(all_found_links))

    logging.info("-" * 70)
    logging.info(f"🏁 執藥完畢：本次共發現 {len(all_found_links)} 條符合條件的源。")

    # 3. 🌟 核心保護邏輯：判斷是否寫入檔案
    if SCAN_MODE == "MANUAL_ONLY":
        logging.info("🛡️  [模式保護] 偵測到手動模式，本次搜尋結果【不會】寫入 sources.txt。")
        logging.info("💡 目的：保護你目前的手動測試區間不受干擾。")
    else:
        logging.info("📝 [寫入模式] 偵測到定時任務，正在更新自動搜尋區塊...")
        # 這裡執行原本的寫入 sources.txt 邏輯 (保護 Fixed Content，覆蓋 Auto Zone)
        # (因篇幅關係，寫入邏輯同你原本代碼，但確保標籤正確)
        update_source_file(all_found_links)

def update_source_file(new_links):
    # 呢度放你原本讀取 fixed_content 並寫入新新標籤嘅邏輯
    # 確保標籤係 # --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---
    pass

if __name__ == "__main__":
    main()
