import requests, logging, os, urllib3

# --- 【初始化】 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 第一份腳本，負責 mode='w' 清空日誌
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("auto_repair.log", mode='w', encoding="utf-8"), 
        logging.StreamHandler()
    ]
)

def log_info(msg):
    logging.info(msg)
    for handler in logging.getLogger().handlers:
        handler.flush()

def main():
    log_info("="*20 + " 1. 執行 discovery_sources (執藥) " + "="*20)
    
    # 這裡放你原本抓取網上直播源網址的邏輯
    # 假設你有一堆 URL 要寫入 sources.txt
    new_sources = [
        "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/user_result.m3u",
        "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
        "https://iptv.hacks.tools/m3u/all.m3u",
        "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
        "https://gitee.com/fomm/live/raw/main/tv/m3u/ipv6.m3u"
    ]
    
    # 寫入 sources.txt
    with open("sources.txt", "w", encoding="utf-8") as f:
        for s in new_sources:
            f.write(f"{s}\n")
    
    log_info(f"✅ [執藥完成] 已更新 sources.txt，共 {len(new_sources)} 個源網址")

if __name__ == "__main__":
    main()
