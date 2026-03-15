import os
import requests
import re

# 1. 獲取由 GitHub Actions 傳入的模式訊號
# 如果沒有環境變量，默認執行 FULL（全量模式）
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")

def get_manual_sources(file_path="sources.txt"):
    """
    自定義讀取邏輯：只抓取 # MY MANUAL SOURCES 標籤之後的 URL
    """
    manual_urls = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            start_collecting = False
            for line in f:
                line = line.strip()
                
                # 判斷起始標籤
                if "# MY MANUAL SOURCES" in line:
                    start_collecting = True
                    continue
                
                # 如果遇到了下一個大標籤（假設以 # 開頭且不是我們想要的），可以選擇停止
                # 如果你想收集到文件結尾，這部分可以省略
                # if start_collecting and line.startswith("#") and "MY MANUAL SOURCES" not in line:
                #     break
                
                # 收集有效 URL（排除空行和注釋）
                if start_collecting and line and not line.startswith("#"):
                    # 簡單驗證是否為 URL 格式
                    if line.startswith("http"):
                        manual_urls.append(line)
        
        print(f"📥 手動模式：已從標籤後加載 {len(manual_urls)} 個特定源")
    except FileNotFoundError:
        print("❌ 錯誤：找不到 sources.txt")
    return manual_urls

def get_all_sources(file_path="sources.txt"):
    """
    原有的全量讀取邏輯：讀取所有非注釋行
    """
    all_urls = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    all_urls.append(line)
        print(f"🌐 全量模式：已加載 {len(all_urls)} 個原始源")
    except FileNotFoundError:
        print("❌ 錯誤：找不到 sources.txt")
    return all_urls

def main():
    print(f"🚀 當前運行模式: {SCAN_MODE}")
    
    # 2. 根據模式選擇要處理的來源
    if SCAN_MODE == "MANUAL_ONLY":
        target_sources = get_manual_sources()
    else:
        target_sources = get_all_sources()

    if not target_sources:
        print("⚠️ 沒有找到可掃描的來源，程序結束。")
        return

    # 3. 這裡接你原本的掃描/處理邏輯
    # 範例：遍歷來源進行請求
    for url in target_sources:
        try:
            print(f"🔍 正在掃描: {url}")
            # res = requests.get(url, timeout=10)
            # ... 你的解析邏輯 ...
        except Exception as e:
            print(f"❌ 掃描出錯 {url}: {e}")

    print("✅ 任務執行完畢")

if __name__ == "__main__":
    main()
