import requests, os, logging, time
from concurrent.futures import ThreadPoolExecutor
from opencc import OpenCC

# --- 【1. 配置】 ---
SOURCE_FILE = "sources.txt"
MY_PRIVATE_M3U = "my_private_list.m3u"  # 你自己私人用嘅檔名
cc = OpenCC('s2t')

# 定義你私人名單嘅過濾標準 (確保只留精華)
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "翡翠", "明珠", "港台", "廣東", "澳門", "CCTV"]
BLACK_LIST = ["ADULT", "PORN", "SHOPPING", "購物", "遊戲", "浙江", "湖南", "湖北", "江蘇", "福建", "杭州"]

logging.basicConfig(level=logging.INFO, format='%(message)s')

def get_speed(url):
    """測速函數：返還延遲毫秒數"""
    try:
        start = time.time()
        # 只取頭部信息，快好多
        r = requests.head(url, timeout=2, verify=False)
        if r.status_code < 400:
            return int((time.time() - start) * 1000)
    except:
        pass
    return 9999

def run_audit_and_test():
    """執行本地庫審核並輸出你想要嘅報告格式"""
    if not os.path.exists(SOURCE_FILE):
        logging.info(f"❌ 錯誤：搵唔到 {SOURCE_FILE}")
        return

    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    total_count = 0
    white_list = []
    black_names = []

    # 1. 審核內容
    for line in lines:
        line = line.strip()
        if "," in line and "://" in line:
            total_count += 1
            name, url = line.split(',', 1)
            name = cc.convert(name)
            combined = (name + url).upper()

            if any(b.upper() in combined for b in BLACK_LIST):
                black_names.append(name)
            elif any(k.upper() in combined for k in KEYWORDS):
                white_list.append({"name": name, "url": url})
            else:
                # 唔喺黑名單亦唔喺關鍵字，可以當普通台放入去，或者直接唔要
                white_list.append({"name": name, "url": url})

    # --- 輸出你指定嘅詳細報告格式 ---
    logging.info(f"\n✅ 報告: 本地私人庫審核 ({SOURCE_FILE})")
    logging.info(f" ┣ [源頭掃描] 總台數: {total_count}")
    logging.info(f" ┗ [內容過濾] 採納: {len(white_list)} | 剔除: {len(black_names)}")
    
    if black_names:
        logging.info(f" ┗ [🚫 黑名單細節]:")
        # 顯示頭 40 個被剔除嘅名，每 5 個一行
        for i in range(0, min(len(black_names), 40), 5):
            logging.info("      " + ", ".join(black_names[i:i+5]))

    # 2. 開始測速 (私人用，速度最緊要)
    logging.info(f"\n🚀 正在為 {len(white_list)} 個採納頻道進行私人測速...")
    
    def task(item):
        delay = get_speed(item['url'])
        if delay < 5000: # 只留 5 秒內有反應嘅
            return {"name": item['name'], "url": item['url'], "speed": delay}
        return None

    with ThreadPoolExecutor(max_workers=20) as executor:
        valid_results = list(filter(None, executor.map(task, white_list)))

    # 按速度排列，最快擺上面
    valid_results.sort(key=lambda x: x['speed'])

    # 3. 生成私人 M3U 檔案
    with open(MY_PRIVATE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for res in valid_results:
            f.write(f"#EXTINF:-1, {res['name']} [{res['speed']}ms]\n{res['url']}\n")

    logging.info(f"\n🎉 私人列表已更新: {MY_PRIVATE_M3U}")
    logging.info(f"📊 最終精選: {len(valid_results)} 台 (已排好序)")

if __name__ == "__main__":
    run_audit_and_test()
