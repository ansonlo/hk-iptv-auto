import os
import requests
import re

# ================= 設定區 =================
SOURCE_FILE = "sources.txt"
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")

# --- 喺呢度填寫最大容納/保留數 ---
MAX_RETAIN_NEW_SOURCES = 5000  # 最終寫入 sources.txt 的新發現源上限
# ==========================================

def get_target_urls():
    """從 sources.txt 提取需要掃描的起始連結"""
    target_urls = []
    if not os.path.exists(SOURCE_FILE): return target_urls
    
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start_collecting = False
    for line in lines:
        line = line.strip()
        if SCAN_MODE == "MANUAL_ONLY":
            if "# MY MANUAL SOURCES" in line:
                start_collecting = True
                continue
            if "# --- AUTO DISCOVERED" in line: break
            if start_collecting and line.startswith("http"):
                target_urls.append(line)
        else:
            if line.startswith("http"): target_urls.append(line)
    return target_urls

def discover_and_filter(urls):
    """掃描並提取頻道，去重後返回"""
    new_discovered_channels = []
    seen_urls = set()
    
    print(f"🔍 開始掃描 {len(urls)} 個來源...")
    
    for url in urls:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                # 簡單 Regex 提取連結 (例如 http...m3u8)
                found = re.findall(r'https?://[^\s,]+(?:\.m3u8|\.ts|\.mp4)', response.text)
                for link in found:
                    if link not in seen_urls:
                        new_discovered_channels.append(link)
                        seen_urls.add(link)
                        # 如果搜到足夠數量，可以提早停止掃描以節省時間
                        if len(new_discovered_channels) >= 1000: break 
        except:
            continue
            
    return new_discovered_channels

def update_source_file(new_sources):
    """將結果寫回 sources.txt，但限制數量"""
    if not new_sources:
        print("ℹ️ 冇新發現嘅源，唔更新文件。")
        return

    # 1. 限制保留數量
    final_list = new_sources[:MAX_RETAIN_NEW_SOURCES]
    print(f"♻️ 從搜到的 {len(new_sources)} 個源中，精選前 {len(final_list)} 個寫入文件。")

    # 2. 讀取原有內容，保留 # MY MANUAL SOURCES 區塊
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # 3. 搵到自動更新標籤嘅位置並截斷，重新寫入
    base_content = content.split("# --- AUTO DISCOVERED")[0].strip()
    
    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        f.write(base_content + "\n\n")
        f.write("# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---\n")
        for idx, url in enumerate(final_list, 1):
            f.write(f"NEW_SOURCE_{idx},{url}\n")
    
    print(f"✅ 已更新 {SOURCE_FILE}，新增了 {len(final_list)} 條數據。")

if __name__ == "__main__":
    # 1. 獲取掃描目標
    targets = get_target_urls()
    
    # 2. 搜刮新源
    found_sources = discover_and_filter(targets)
    
    # 3. 根據模式決定點處理
    if SCAN_MODE == "MANUAL_ONLY":
        print(f"\n📊 [手動報告] 搜到 {len(found_sources)} 個潛在源。")
        print("📝 手動模式下唔會寫入檔案，請查看 Log。")
        for s in found_sources[:10]: print(f"  - 發現: {s}") # 只列出前10個參考
    else:
        # 只有全量/例行模式先會寫入並限制 100 個
        update_source_file(found_sources)
