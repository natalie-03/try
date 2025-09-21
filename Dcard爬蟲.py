!pip uninstall undetected-chromedriver -y
!pip install selenium webdriver-manager

%pip install undetected-chromedriver

import pandas as pd

%pip install keyboard

import subprocess
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from datetime import datetime, timedelta
from tqdm import tqdm

# ----------------------------
# 配置參數
# ----------------------------
CONFIG = {
    "wait_timeout": 1,       # 顯式等待超時 (秒)
    "short_wait": 1,         # 短暫等待 (秒)
    "medium_wait": 1,        # 中等等待 (秒)
    "max_workers": 5,        # 最大並發線程數
    "max_scroll": 1000,      # 最多滾動次數
}

# ----------------------------
# 自動偵測 Chrome 主版本
# ----------------------------
def get_chrome_version():
    try:
        version = subprocess.check_output(
            r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version',
            shell=True
        ).decode("utf-8").strip().split()[-1]
        return int(version.split(".")[0])
    except Exception as e:
        print("❌ 無法檢查 Chrome 版本，請確認已安裝 Chrome")
        raise e

chrome_major_version = get_chrome_version()
print(f"✅ 偵測到 Chrome 主版本號: {chrome_major_version}")

# ----------------------------
# 啟動瀏覽器
# ----------------------------
options = uc.ChromeOptions()
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--window-size=1920,1080")
options.add_argument("--incognito")
options.add_argument("--blink-settings=imagesEnabled=false")  # 禁用圖片
options.add_experimental_option("prefs", {
    "profile.managed_default_content_settings.images": 2,
    "profile.default_content_setting_values.notifications": 2
})
driver = uc.Chrome(version_main=chrome_major_version, options=options)

processed_links = set()

# ----------------------------
# 抓取文章連結 (直到三年前)
# ----------------------------
def get_article_links(driver, board_name, max_scroll=CONFIG["max_scroll"]):
    article_links, seen_links = [], set()
    driver.get(f"https://www.dcard.tw/f/{board_name}")
    try:
        WebDriverWait(driver, CONFIG["wait_timeout"]).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        sleep(CONFIG["medium_wait"])
    except TimeoutException:
        print(f"⚠️ {board_name} 頁面加載超時")

    cutoff_date = datetime.now() - timedelta(days=365*10)  # ✅ 十年前
    for i in range(max_scroll):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        sleep(CONFIG["short_wait"])

        posts = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")
        for post in posts:
            link = post.get_attribute("href")
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            # 嘗試抓文章日期
            try:
                time_el = post.find_element(By.XPATH, ".//time")
                date_text = time_el.get_attribute("datetime") or time_el.text
                post_date = datetime.fromisoformat(date_text.replace("Z", "+00:00")).replace(tzinfo=None)
            except:
                post_date = datetime.now()

            if post_date >= cutoff_date:
                article_links.append(link)
            else:
                print("⚠️ 已經遇到超過十年的文章 → 停止滾動")
                return article_links
    return article_links

# ----------------------------
# 抓取文章內容 (含評論)
# ----------------------------
def get_article_content(url):
    if url in processed_links:
        return None
    try:
        driver.get(url)
        wait = WebDriverWait(driver, CONFIG["wait_timeout"])

        # 標題
        title = ""
        for selector in ["h1", "[data-testid='article-title']", "title"]:
            try:
                if selector == "title":
                    raw = driver.title
                    if raw and "Dcard" in raw:
                        title = raw.replace(" | Dcard", "").replace("- Dcard", "").strip()
                else:
                    title_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    t = title_element.text.strip()
                    if t and t != "請稍候...":
                        title = t
                if title:
                    break
            except Exception:
                continue

        # 內容
        content = ""
        for selector in ["div[data-testid='post-content']", "article", ".content"]:
            try:
                content_element = wait.until(
                    lambda d: d.find_element(By.CSS_SELECTOR, selector)
                    if d.find_element(By.CSS_SELECTOR, selector).text.strip() != "請稍候..." else False
                )
                text = content_element.text.strip()
                if text and text != "請稍候..." and len(text) > 10:
                    content = text
                    break
            except Exception:
                continue

        # 日期
        try:
            date_element = driver.find_element(By.CSS_SELECTOR, 'time, [data-testid="post-date"]')
            date_text = date_element.get_attribute("datetime") or date_element.text
            post_date = datetime.fromisoformat(date_text.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            post_date = datetime.now()

        # 三年內文章
        if post_date < datetime.now() - timedelta(days=365*3):
            return None

        # 抓評論
        comments = []
        try:
            comment_elements = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="comment"]')
            for c in comment_elements:
                txt = c.text.strip()
                if txt:
                    comments.append(txt)
        except Exception:
            pass

        processed_links.add(url)
        return {
            "標題": title,
            "內容": content,
            "連結": url,
            "日期": post_date.strftime("%Y-%m-%d"),
            "評論": " || ".join(comments) if comments else ""
        }
    except Exception:
        return None

# ----------------------------
# 爬取多個看板
# ----------------------------
def crawl_all_boards(boards):
    all_links = {}
    for board_name in boards.keys():
        links = get_article_links(driver, board_name, CONFIG["max_scroll"])
        print(f"✅ {board_name} 共獲取 {len(links)} 篇文章連結")
        all_links[board_name] = links

    data_by_board = {b: [] for b in boards.keys()}
    total_links = sum(len(v) for v in all_links.values())

    with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
        futures = []
        for board_name, links in all_links.items():
            for link in links:
                futures.append((board_name, executor.submit(get_article_content, link)))

        for board_name, future in tqdm(futures, total=total_links, desc="抓取文章進度"):
            result = future.result()
            if result:
                data_by_board[board_name].append(result)

    for board_name, filename in boards.items():
        if data_by_board[board_name]:
            pd.DataFrame(data_by_board[board_name]).to_csv(filename, index=False, encoding="utf-8-sig")
            print(f"📂 {filename} 已保存 {len(data_by_board[board_name])} 篇文章")

# ----------------------------
# 主程式
# ----------------------------
boards = {
    "travel": "旅遊.csv",
     "food": "美食.csv",
     "job": "工作.csv",
     "graduate_school": "研究所.csv",
     "exam": "考試.csv"
}

try:
    crawl_all_boards(boards)
except Exception as e:
    print(f"❌ 主程式錯誤: {e}")
finally:
    driver.quit()
    print("🛑 瀏覽器已關閉")


import pandas as pd
import os

# ----------------------------
# 看板對應檔名
# ----------------------------
boards = {
    "travel": "旅遊.csv",
     "food": "美食.csv",
     "job": "工作.csv",
    "graduate_school": "研究所.csv",
     "exam": "考試.csv"
}

# ----------------------------
# 要清除的 Dcard 系統字樣
# ----------------------------
remove_phrases = [
    "Dcard 需要確認您的連線是安全的"
]

# ----------------------------
# CSV 清理函數
# ----------------------------
def clean_csv(file_path, output_path):
    # 嘗試讀取 CSV，即使欄位數不齊也讀進來
    df = pd.read_csv(file_path, on_bad_lines="skip")

    # 移除「連結」欄位
    df_cleaned = df.drop(columns=["連結"], errors="ignore").copy()

    # 移除舊的「編號」欄位（若存在）
    if "編號" in df_cleaned.columns:
        df_cleaned = df_cleaned.drop(columns=["編號"])

    # 去掉 NaN 列（缺欄位、空值）
    df_cleaned = df_cleaned.dropna(how="any")

    # 清理「標題」「內容」
    # 移除「請稍候...」的列
    for col in ["標題", "內容"]:
        if col in df_cleaned.columns:
            df_cleaned = df_cleaned[df_cleaned[col].str.strip() != "請稍候..."]

            df_cleaned[col] = (
                df_cleaned[col]
                .astype(str)
                .str.replace(r"\s+", " ", regex=True)  # 移除多餘空白
                .apply(lambda x: "".join(x.replace(p, "") for p in remove_phrases))
                .str.strip()
            )

    # 移除清理後變成空字串的列
    if "標題" in df_cleaned.columns and "內容" in df_cleaned.columns:
        df_cleaned = df_cleaned[
            (df_cleaned["標題"].str.strip() != "") &
            (df_cleaned["內容"].str.strip() != "")
        ]

    # 重新生成流水編號
    df_cleaned.insert(0, "編號", range(1, len(df_cleaned) + 1))

    # 輸出清理後的檔案
    df_cleaned.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"✅ 已處理完成: {output_path}")

# ----------------------------
# 批次處理
# ----------------------------
for board, filename in boards.items():
    if os.path.exists(filename):
        output_file = f"{os.path.splitext(filename)[0]}.csv"
        clean_csv(filename, output_file)
    else:
        print(f"⚠️ 找不到檔案: {filename}")



if __name__ == "__main__":
    # 這裡可以放主要執行的函式或流程
    # 例如 main() 或其他啟動程式碼
    print("Dcard爬蟲開始執行...")
