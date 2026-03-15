import requests, os, logging, time
from concurrent.futures import ThreadPoolExecutor
from opencc import OpenCC

# --- 【1. 配置】 ---
SOURCE_FILE = "sources.txt"
MY_PRIVATE_M3U = "hk_live.m3u"  # 👈 已改為你指定嘅檔名
cc = OpenCC('s2t')

# 關鍵字：確保 hk_live.m3u 入面都係你想要嘅精華
KEYWORDS = ["ViuTV", "HOY", "RTHK", "Jade", "Pearl", "J2", "J5", "Now", "無線", "翡翠", "明珠", "港台", "廣東", "澳門", "CCTV"]
BLACK_LIST = ["ADULT", "PORN", "SHOPPING", "購物", "遊戲", "浙江", "湖南", "湖北", "江蘇", "福建", "杭州"]

logging.basicConfig(level=logging.INFO, format='%(message)s')

def get_speed(url):
    """測速函數"""
    try:
        start = time.time()
        # 使用 head 請求快速測試連通性
        r = requests.head(url, timeout=2, verify=False)
        if r.status_code < 400:
            return int((time.time() - start) * 1000)
    except:
        pass
    return 9999

def run_main_process():
    """執行審核、測速並生成 hk_live.m3u"""
    if not os.path.exists(SOURCE_FILE):
        logging.info(f"❌ 錯誤：搵唔到原材料庫 {SOURCE_FILE}")
        return

    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    total_count = 0
    white_list = []
    black_names = []

    # 1. 內容審計
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
                # 其他未分類但唔喺黑名單嘅，一樣採納入私人名單
                white_list.append({"name": name, "url": url})

    # --- 輸出詳細報告 ---
    logging.info(f"\n✅ 報告: {MY_PRIVATE_M3U} 數據庫審計")
    logging.info(f" ┣ [源頭掃描] 總台數: {total_count}")
    logging.info(f" ┗ [內容過濾] 採納: {len(white_list)} | 剔除: {len(black_names)}")
    
    if black_names:
        logging.info(f" ┗ [🚫 黑名單細節]:")
        # 顯示頭 40 個被剔除嘅名，方便 debug
        for i in range(0, min(len(black_names), 40), 5):
            logging.info("      " + ", ".join(black_names[i:i+5]))

    # 2. 私人專線測速
    logging.info(f"\n🚀 正在為 {len(white_list)} 個精選頻道進行測速排序...")
    
    def task(item):
        delay = get_speed(item['url'])
        if delay < 5000: # 剔除超過 5 秒都冇反應嘅死鏈
            return {"name": item['name'], "url": item['url'], "speed": delay}
        return None

    with ThreadPoolExecutor(max_workers=25) as executor:
        results = list(filter(None, executor.map(task, white_list)))

    # 按延遲排序，越快越好
    results.sort(key=lambda x: x['speed'])

    # 3. 產出最終的 hk_live.m3u
    with open(MY_PRIVATE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for res in results:
            # 將延遲標記喺名後面，方便播放器顯示
            f.write(f"#EXTINF:-1, {res['name']} [{res['speed']}ms]\n{res['url']}\n")

    logging.info(f"\n🎉 成功生成私人名單: {MY_PRIVATE_M3U}")
    logging.info(f"📊 最終收錄: {len(results)} 條優質線路")

if __name__ == "__main__":
    run_main_process()
