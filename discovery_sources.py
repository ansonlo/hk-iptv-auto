import os
import requests
import re

# ================= 設定區 =================
SOURCE_FILE = "sources.txt"
# 從 GitHub Actions 獲取運行模式 (MANUAL_ONLY 或 FULL_SCAN)
SCAN_MODE = os.getenv("SCAN_MODE", "FULL_SCAN")

# 最終寫入 sources.txt 的新發現源上限
MAX_RETAIN_NEW_SOURCES = 10000 
# ==========================================

def get_target_urls():
    """從 sources.txt 提取需要掃描的起始連結"""
    target_urls = []
    if not os.path.exists(SOURCE_FILE):
        print(f"❌ 錯誤：找不到 {SOURCE_FILE}")
        return target_urls
    
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if SCAN_MODE == "MANUAL_ONLY":
        print("🎯 [模式: 手動] 僅提取 # MY MANUAL SOURCES 區間")
        start_collecting = False
        for line in lines:
            line = line.strip()
            if "# MY MANUAL SOURCES" in line:
                start_collecting = True
                continue
            if "# --- AUTO DISCOVERED" in line:
                break
            if start_collecting and line.startswith("http"):
                target_urls.append(line)
    else:
        print("🌐 [模式: 全量] 提取所有連結進行深度搜尋")
        for line in lines:
            line = line.strip()
            if line.startswith("http"):
                target_urls.append(line)
    
    return target_urls

def discover_sources(urls):
    """掃描並提取頻道連結"""
    found_urls = []
    seen = set()
    
    print(f"🔍 開始掃描 {len(urls)} 個來源...")
    for url in urls:
        try:
            # 增加 timeout 防止卡死
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                # 匹配常見的直播流格式
                links = re.findall(r'https?://[^\s,]+(?:\.m3u8|\.ts|\.mp4|\.m3u)', response.text)
                for link in links:
                    if link not in seen:
                        found_urls.append(link)
                        seen.add(link)
                print(f"✅ 掃描成功: {url}")
        except:
            print(f"❌ 掃描跳過 (連線超時/錯誤): {url}")
            continue
    return found_urls

def update_source_file(new_sources):
    """將結果去重並限額寫回 sources.txt"""
    if not new_sources:
        print("ℹ️ 冇新發現嘅源，唔更新文件。")
        return

    # 1. 讀取現有內容，拆分出「手動區」
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        full_content = f.read()
    
    manual_part = full_content.split("# --- AUTO DISCOVERED")[0].strip()
    
    # 2. 獲取手動區已有的 URL (用作跨區去重)
    existing_urls = set(re.findall(r'https?://[^\s,]+', manual_part))

    # 3. 過濾並限額
    final_list = []
    for s in new_sources:
        if s not in existing_urls:
            final_list.append(s)
        if len(final_list) >= MAX_RETAIN_NEW_SOURCES:
            break

    # 4. 寫入文件
    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        f.write(manual_part + "\n\n")
        f.write("# --- AUTO DISCOVERED & CLEANED SOURCES (DYNAMIC UPDATE) ---\n")
        for idx, url in enumerate(final_list, 1):
            # 格式：名稱,URL (保持你原本的格式)
            f.write(f"NEW_SOURCE_{idx},{url}\n")
    
    print(f"✅ 文件已更新！新增了 {len(final_list)} 條唯一數據。")

if __name__ == "__main__":
    # 1. 獲取掃描目標
    targets = get_target_urls()
    print(f"📦 已識別 {len(targets)} 個起始目標")
    
    # 2. 搜尋新源
    found = discover_sources(targets)
    
    # 3. 根據模式執行
    if SCAN_MODE == "MANUAL_ONLY":
        print(f"\n📊 [手動模式報告] 總共搜刮到 {len(found)} 個唯一連結。")
        print("📝 注意：手動執行不會更改 sources.txt，僅供 Log 參考。")
        # 列出前 5 個作為範例
        for s in found[:5]:
            print(f"  > 發現源: {s}")
    else:
        # 定時執行（星期一）會寫入並限制數量
        update_source_file(found)
    
    print("\n🏁 任務完成。")
