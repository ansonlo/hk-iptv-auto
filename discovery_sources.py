import requests, re, os, logging, time, urllib3
from urllib.parse import quote, urljoin
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor

# --- 【1. 配置與初始化】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SOURCE_FILE = "sources.txt"
MAX_AUTO_KEEP = 5000
cc = OpenCC('s2t')

GITHUB_EVENT = os.getenv('GITHUB_EVENT_NAME', 'local')
SCAN_MODE = "MANUAL_ONLY" if GITHUB_EVENT == 'workflow_dispatch' else "FULL_SCAN"

KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "有線", "翡翠", "明珠", "港台", "廣東",
            "珠江", "廣州", "大灣區", "南方", "鳳凰", "民視", "東森", "三立", "中視", "公視", "TVBS", "緯來", "年代",
            "中天", "非凡", "澳視", "澳門", "TDM", "澳亞", "CCTV"]

# 這些是已知優質源，唔需要浪費時間校驗體積
WHITELIST_DOMAINS = ["raw.githubusercontent.com", "gitee.com", "hacks.tools", "gitlab.com"]

BASE_DISCOVERY_URLS = [
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://iptv.hacks.tools/m3u/all.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

logging.basicConfig(level=logging.INFO, format='%(message)s', handlers=[logging.StreamHandler()])

# --- 【2. 核心過濾與深度校驗邏輯】 ---

def is_fake_by_size(m3u8_url):
    """🚀 快速校驗：只針對懷疑對象"""
    try:
        # 縮短 timeout，唔好等咁耐
        r = requests.get(m3u8_url, timeout=2, verify=False, headers=HEADERS)
        if r.status_code != 200: return False
        
        ts_match = re.findall(r'(http.*?\.ts|[\w\d\-_/]+\.ts)', r.text)
        if not ts_match: return False
        
        ts_url = ts_match[0]
        if not ts_url.startswith("http"):
            ts_url = urljoin(m3u8_url, ts_url)
            
        ts_head = requests.head(ts_url, timeout=2, verify=False, headers=HEADERS)
        f_size = int(ts_head.headers.get('Content-Length', 0))
        
        # 100KB 以下通常係廣告或報錯片
        return 0 < f_size < 102400
    except:
        return False

def get_filtered_links(url):
    links = []
    try:
        r = requests.get(url, timeout=10, headers=HEADERS, verify=False)
        r.encoding = 'utf-8'
        if r.status_code != 200: return []
            
        lines = r.text.split('\n')
        temp_name = ""
        
        for line in lines:
            line = line.strip()
            target_link = ""
            
            if line.startswith("#EXTINF"):
                temp_name = cc.convert(line.split(',')[-1]).strip().upper()
                continue
            elif line.startswith("http") and temp_name:
                if any(k.upper() in temp_name for k in KEYWORDS):
                    target_link = line.split('$')[0].split('#')[0].strip()
                temp_name = ""
            elif "," in line and "://" in line:
                txt_name = cc.convert(line.split(',')[0]).upper()
                if any(k.upper() in txt_name for k in KEYWORDS):
                    target_link = line.split(',')[1].strip()

            if target_link:
                # 💡 關鍵優化：判斷是否需要進行體積校驗
                # 1. 唔喺白名單域名入面
                # 2. 或者網址入面有明顯嘅假源特徵 (freetv, stream1, 長亂碼)
                needs_check = not any(domain in target_link for domain in WHITELIST_DOMAINS)
                is_suspicious = "freetv" in target_link or "stream1" in target_link or len(re.findall(r'[a-f0-9]{32,}', target_link)) > 0
                
                if (needs_check or is_suspicious) and ".m3u8" in target_link.lower():
                    if is_fake_by_size(target_link):
                        continue
                
                links.append(target_link)
        
        if links:
            logging.info(f"  ✅ 提取完成 | 數量: {len(links):3d} | 來源: {url[:50]}...")
            
    except: pass
    return list(dict.fromkeys(links))

# --- 【3. 搜尋與寫入模組 (略，保持不變但建議加大線程)】 ---
# (請保留你原本的 search_github, search_gitee, search_gitcode, update_source_file 函數)

def main():
    logging.info("\n" + "="*75)
    logging.info(f"🚀 啟動【加速過濾模式】 | 模式: {SCAN_MODE}")
    logging.info("="*75)
    
    # 搜尋動態源
    dynamic_urls = [] # 這裡放入你原本的搜尋函數結果
    all_targets = list(dict.fromkeys(BASE_DISCOVERY_URLS + dynamic_urls))
    
    # 💡 提升併發數量到 100
    with ThreadPoolExecutor(max_workers=100) as executor:
        results = list(executor.map(get_filtered_links, all_targets))
    
    final_links = []
    for r in results: final_links.extend(r)
    final_links = list(dict.fromkeys(final_links))
    
    logging.info("-" * 75)
    logging.info(f"🏁 執藥完畢：本次共發現 {len(final_links)} 條符合要求嘅源。")
    if SCAN_MODE != "MANUAL_ONLY":
        # 這裡呼叫你原本的 update_source_file
        pass 

if __name__ == "__main__":
    main()
