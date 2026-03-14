import requests, re, os, logging, time, urllib3
from urllib.parse import urlparse
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# --- 屏蔽警告 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 150000  # 提升上限，容納更多唔同 IP 嘅源
cc = OpenCC('s2t')

# 關鍵字：保留你想睇嘅台
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "深圳", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

# 過濾：徹底踢走唔想睇嘅嘢
BLOCK_KEYWORDS = ["購物", "測試", "TEST", "SHOP", "廣告", "酒店", "福利", "PREVIEW", "廣播", "電台", "GOUWU", "GDT"]

# 源頭網址
BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u",
]

def get_filtered_links(url):
    results = []
    # 提取來源標籤
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
                # 簡化台名，方便去重（統一 CCTV11-高清 同 CCTV11）
                clean_name = re.sub(r'\[.*?\]|\(.*?\)|-.*|HD|SD|高清|超清|頻道', '', raw_name).strip()
                if any(k.upper() in clean_name for k in KEYWORDS) and not any(b in clean_name for b in BLOCK_KEYWORDS):
                    temp_name = clean_name
                else: temp_name = ""
            elif (line.startswith("http") or line.startswith("rtmp")) and temp_name:
                u = line.split('$')[0].split('#')[0].split('|')[0].strip()
                # 打掃邏輯：踢走內網 IP
                if any(x in u for x in ["127.0.0.1", "localhost", "192.168.", "10."]):
                    temp_name = ""
                    continue
                results.append((temp_name, u, label))
                temp_name = ""
    except: pass
    return results

def extract_ip(url):
    """提取網址嘅伺服器地址/域名"""
    try: 
        return urlparse(url).netloc
    except: 
        return url

def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logging.info(f"🚀 啟動【全量掃描 + 深度打掃】，上限 {MAX_AUTO_KEEP} 條...")

    # 1. 抓取數據
    raw_results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(get_filtered_links, url) for url in BASE_DISCOVERY_URLS]
        for f in tqdm(as_completed(futures), total=len(BASE_DISCOVERY_URLS), desc="🔍 掃描中"):
            raw_results.extend(f.result())

    # 2. 聰明去重：同台名且同IP只留一個，確保 sources.txt 唔會被同一個伺服器嘅重複 Link 塞爆
    name_ip_map = {}
    final_output = []

    # 倒序處理，保留最新掃描到嘅 Key
    for name, url, label in reversed(raw_results):
        ip = extract_ip(url)
        unique_key = f"{name}_{ip}"
        
        if unique_key not in name_ip_map:
            final_output.append(f"{name},{url} # {label}")
            name_ip_map[unique_key] = True

    # 3. 寫入 sources.txt
    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        f.write("# --- AUTO DISCOVERED & CLEANED SOURCES ---\n")
        # 攞最新嘅 MAX_AUTO_KEEP 條
        final_list = final_output[:MAX_AUTO_KEEP]
        for line in reversed(final_list):
            f.write(line + "\n")
    
    logging.info(f"✅ 搞掂！已清理重複 IP 冗餘。")
    logging.info(f"📊 最終 sources.txt 收錄唯一源數量: {len(final_list)}")

if __name__ == "__main__":
    main()
