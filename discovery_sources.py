import requests, re, os, logging, time, urllib3
from urllib.parse import urlparse
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# --- 屏蔽警告 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 5000 
cc = OpenCC('s2t')

# 關鍵字與過濾邏輯保留
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "深圳", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

BLOCK_KEYWORDS = ["購物", "測試", "TEST", "SHOP", "廣告", "酒店", "福利", "PREVIEW", "廣播", "電台", "GOUWU", "GDT"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u",
]

def extract_ip(url):
    try: return urlparse(url).netloc
    except: return url

def get_filtered_links(url):
    results = []
    parsed = urlparse(url)
    label = url.split('/')[3] if "githubusercontent.com" in url else parsed.netloc
    try:
        r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'}, verify=False)
        r.encoding = 'utf-8'
        lines = r.text.split('\n')
        temp_name = ""
        for line in lines:
            line = line.strip()
            if not line: continue
            if line.startswith("#EXTINF"):
                raw_name = cc.convert(line.split(',')[-1]).strip().upper()
                clean_name = re.sub(r'\[.*?\]|\(.*?\)|-.*|HD|SD|高清|超清|頻道', '', raw_name).strip()
                if any(k.upper() in clean_name for k in KEYWORDS) and not any(b in clean_name for b in BLOCK_KEYWORDS):
                    temp_name = clean_name
                else: temp_name = ""
            elif (line.startswith("http") or line.startswith("rtmp")) and temp_name:
                u = line.split('$')[0].split('#')[0].split('|')[0].strip()
                if any(x in u for x in ["127.0.0.1", "localhost", "192.168.", "10."]):
                    temp_name = ""
                    continue
                results.append((temp_name, u, label))
                temp_name = ""
    except: pass
    return results

def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    # --- 關鍵：保護手動源 ---
    manual_content = []
    if os.path.exists(SOURCE_FILE):
        logging.info(f"📁 正在掃描 {SOURCE_FILE} 搵返手動源...")
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                # 只要見到呢個自動標籤，就停止讀取，下面嘅嘢交畀腳本更新
                if "# --- AUTO DISCOVERED" in line:
                    break
                if line.strip(): # 唔要空行
                    manual_content.append(line.strip())
    
    if not manual_content:
        # 如果原本乜都冇，至少幫你留個頭
        manual_content = ["# --- MY MANUAL SOURCES (PERMANENT) ---"]

    logging.info(f"🚀 啟動全量掃描，目標上限 {MAX_AUTO_KEEP} 條...")

    # --- 抓取新數據 ---
    raw_results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(get_filtered_links, url) for url in BASE_DISCOVERY_URLS]
        for f in tqdm(as_completed(futures), total=len(BASE_DISCOVERY_URLS), desc="🔍 執行中"):
            raw_results.extend(f.result())

    # --- 打掃去重 ---
    name_ip_map = {}
    final_output = []
    for name, url, label in reversed(raw_results):
        ip = extract_ip(url)
        unique_key = f"{name}_{ip}"
        if unique_key not in name_ip_map:
            final_output.append(f"{name},{url} # {label}")
            name_ip_map[unique_key] = True

    # --- 重新寫入（補返手動源） ---
    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        # 1. 寫回手動部分（補返你原本啲源）
        for line in manual_content:
            f.write(line + "\n")
        
        # 2. 寫入自動區間分隔線
        f.write("\n# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---\n")
        
        # 3. 寫入自動掃描部分
        for line in reversed(final_output[:MAX_AUTO_KEEP]):
            f.write(line + "\n")
    
    logging.info(f"✅ 搞掂！更新咗自動源。")

if __name__ == "__main__":
    main()
