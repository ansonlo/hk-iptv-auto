import os
import requests
import re

# ================= 設定區 =================
SOURCE_FILE = "sources.txt"
# 從 GitHub Actions 獲取運行模式，預設為 FULL_SCAN
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")

def get_target_urls():
    """
    根據模式從 sources.txt 提取 URL
    """
    target_urls = []
    
    if not os.path.exists(SOURCE_FILE):
        print(f"❌ 錯誤：找不到 {SOURCE_FILE}")
        return target_urls

    print(f"🚀 當前運行模式: {SCAN_MODE}")

    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if SCAN_MODE == "MANUAL_ONLY":
        # --- 手動模式邏輯：只攞指定區間嘅 URL ---
        print("🎯 模式：僅提取 # MY MANUAL SOURCES 區塊內容")
        start_collecting = False
        for line in lines:
            line = line.strip()
            
            # 偵測起點
            if "# MY MANUAL SOURCES" in line:
                start_collecting = True
                continue
            
            # 偵測終點（遇到自動更新標籤就停）
            if "# --- AUTO DISCOVERED" in line:
                break
                
            # 收集 http 開頭嘅連結
            if start_collecting and line.startswith("http"):
                target_urls.append(line)
    else:
        # --- 全量模式邏輯：攞晒所有 URL ---
        print("🌐 模式：全量掃描 sources.txt 所有連結")
        for line in lines:
            line = line.strip()
            if line.startswith("http"):
                target_urls.append(line)

    return target_urls

def process_sources(urls):
    """
    呢度係你原本處理/掃描來源嘅核心邏輯
    (例如：下載 M3U, 提取頻道, 測試速度等)
    """
    if not urls:
        print("⚠️ 沒有可掃描的來源。")
        return

    print(f"📦 開始處理共 {len(urls)} 個來源...")
    
    for url in urls:
        print(f"🔍 正在抓取: {url}")
        try:
            # 模擬抓取動作，超時設為 10 秒
            # response = requests.get(url, timeout=10)
            # if response.status_code == 200:
            #     # 在此處加入你原本的解析代碼
            #     pass
            
            # 呢度暫時用 print 代替，你需要保留你原本 discovery_sources.py 入面嘅解析 loop
            pass
            
        except Exception as e:
            print(f"❌ 抓取失敗 {url}: {e}")

if __name__ == "__main__":
    # 1. 提取 URL
    active_urls = get_target_urls()
    
    # 2. 顯示結果摘要
    print(f"✅ 成功加載 {len(active_urls)} 個 URL")
    
    # 3. 執行原本的掃描邏輯
    process_sources(active_urls)
    
    print("🏁 所有任務已完成")
