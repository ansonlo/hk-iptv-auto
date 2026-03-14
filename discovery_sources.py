import requests, re, os, logging, time, urllib3
from urllib.parse import urlparse
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# --- 屏蔽警告 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 500000 
cc = OpenCC('s2t')

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
    
    # --- 第一步：讀取現有文件，保留手動部分 ---
    fixed_content = []
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                # 只要見到呢個標籤，就停止讀取，下面嘅嘢交畀腳本更新
                if "# --- AUTO DISCOVERED" in line:
                    break
                fixed_content.append(line.strip())
    
    # 如果文件係空嘅或者冇標籤，確保最後一行唔係空行
    if not fixed_content:
        fixed_content = ["# MY MANUAL SOURCES", "翡翠台,http://xxx.xxx # 手動"]

    logging.info(f"🚀 啟動全量掃描，目標上限 {MAX_AUTO_KEEP} 條...")

    # --- 第二步：抓取新數據 ---
    raw_results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(get_filtered_links, url) for url in BASE_DISCOVERY_URLS]
        for f in tqdm(as_completed(futures), total=len(BASE_DISCOVERY_URLS), desc="🔍 執行中"):
            raw_results.extend(f.result())

    total_scanned = len(raw_results)

    # --- 第三步：打掃去重 ---
    name_ip_map = {}
    final_output = []
    duplicate_count = 0

    for name, url, label in reversed(raw_results):
        ip = extract_ip(url)
        unique_key = f"{name}_{ip}"
        if unique_key not in name_ip_map:
            final_output.append(f"{name},{url} # {label}")
            name_ip_map[unique_key] = True
        else:
            duplicate_count += 1

    # --- 第四步：重新組合寫入 ---
    final_list = final_output[:MAX_AUTO_KEEP]
    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        # 先寫回手動部分
        for line in fixed_content:
            f.write(line + "\n")
        
        # 寫入標籤
        f.write("\n# --- AUTO DISCOVERED & CLEANED SOURCES ---\n")
        
        # 寫入自動掃描部分
        for line in reversed(final_list):
            f.write(line + "\n")
    
    logging.info("-" * 30)
    logging.info(f"📊 報告：掃描 {total_scanned}，去重 {duplicate_count}，保留自動源 {len(final_list)}")
    logging.info(f"✅ 已保護手動源，並更新自動源至 {SOURCE_FILE}")

if __name__ == "__main__":
    main()
