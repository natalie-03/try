# ----------------------------
# Install dependencies (if running in Jupyter / Colab)
# ----------------------------
# !pip uninstall undetected-chromedriver -y
# !pip install selenium webdriver-manager
# %pip install undetected-chromedriver
# %pip install keyboard

import os
import subprocess
from time import sleep
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from tqdm import tqdm

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# ----------------------------
# CONFIG PARAMETERS
# ----------------------------
CONFIG = {
    "wait_timeout": 1,       # explicit wait timeout (seconds)
    "short_wait": 1,         # short wait (seconds)
    "medium_wait": 1,        # medium wait (seconds)
    "max_workers": 5,        # max concurrent threads
    "max_scroll": 1000,      # max scrolls
}

DATA_FOLDER = "data"
os.makedirs(DATA_FOLDER, exist_ok=True)  # create data folder if not exists

processed_links = set()

# ----------------------------
# DETECT CHROME VERSION
# ----------------------------
def get_chrome_version():
    try:
        version = subprocess.check_output(
            r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version',
            shell=True
        ).decode("utf-8").strip().split()[-1]
        return int(version.split(".")[0])
    except Exception as e:
        print("❌ Cannot detect Chrome version. Please make sure Chrome is installed.")
        raise e

chrome_major_version = get_chrome_version()
print(f"✅ Detected Chrome major version: {chrome_major_version}")

# ----------------------------
# LAUNCH BROWSER
# ----------------------------
options = uc.ChromeOptions()
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--window-size=1920,1080")
options.add_argument("--incognito")
options.add_argument("--blink-settings=imagesEnabled=false")  # disable images
options.add_experimental_option("prefs", {
    "profile.managed_default_content_settings.images": 2,
    "profile.default_content_setting_values.notifications": 2
})
driver = uc.Chrome(version_main=chrome_major_version, options=options)

# ----------------------------
# GET ARTICLE LINKS
# ----------------------------
def get_article_links(driver, board_name, max_scroll=CONFIG["max_scroll"]):
    links, seen = [], set()
    driver.get(f"https://www.dcard.tw/f/{board_name}")
    try:
        WebDriverWait(driver, CONFIG["wait_timeout"]).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        sleep(CONFIG["medium_wait"])
    except TimeoutException:
        print(f"⚠️ {board_name} page load timeout")

    cutoff_date = datetime.now() - timedelta(days=365*10)  # 10 years ago
    for _ in range(max_scroll):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        sleep(CONFIG["short_wait"])

        posts = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")
        for post in posts:
            link = post.get_attribute("href")
            if not link or link in seen:
                continue
            seen.add(link)

            # attempt to get post date
            try:
                time_el = post.find_element(By.XPATH, ".//time")
                date_text = time_el.get_attribute("datetime") or time_el.text
                post_date = datetime.fromisoformat(date_text.replace("Z", "+00:00")).replace(tzinfo=None)
            except:
                post_date = datetime.now()

            if post_date >= cutoff_date:
                links.append(link)
            else:
                print("⚠️ Encountered posts older than 10 years → stop scrolling")
                return links
    return links

# ----------------------------
# GET ARTICLE CONTENT
# ----------------------------
def get_article_content(url):
    if url in processed_links:
        return None
    try:
        driver.get(url)
        wait = WebDriverWait(driver, CONFIG["wait_timeout"])

        # Title
        title = ""
        for sel in ["h1", "[data-testid='article-title']", "title"]:
            try:
                if sel == "title":
                    raw = driver.title
                    if raw and "Dcard" in raw:
                        title = raw.replace(" | Dcard", "").replace("- Dcard", "").strip()
                else:
                    elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    t = elem.text.strip()
                    if t and t != "請稍候...":
                        title = t
                if title:
                    break
            except:
                continue

        # Content
        content = ""
        for sel in ["div[data-testid='post-content']", "article", ".content"]:
            try:
                elem = wait.until(
                    lambda d: d.find_element(By.CSS_SELECTOR, sel)
                    if d.find_element(By.CSS_SELECTOR, sel).text.strip() != "請稍候..." else False
                )
                text = elem.text.strip()
                if text and text != "請稍候..." and len(text) > 10:
                    content = text
                    break
            except:
                continue

        # Post date
        try:
            date_elem = driver.find_element(By.CSS_SELECTOR, 'time, [data-testid="post-date"]')
            date_text = date_elem.get_attribute("datetime") or date_elem.text
            post_date = datetime.fromisoformat(date_text.replace("Z", "+00:00")).replace(tzinfo=None)
        except:
            post_date = datetime.now()

        # Skip posts older than 3 years
        if post_date < datetime.now() - timedelta(days=365*3):
            return None

        # Comments
        comments = []
        try:
            comment_elems = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="comment"]')
            for c in comment_elems:
                txt = c.text.strip()
                if txt:
                    comments.append(txt)
        except:
            pass

        processed_links.add(url)
        return {
            "Title": title,
            "Content": content,
            "Link": url,
            "Date": post_date.strftime("%Y-%m-%d"),
            "Comments": " || ".join(comments) if comments else ""
        }
    except:
        return None

# ----------------------------
# CRAWL MULTIPLE BOARDS
# ----------------------------
def crawl_all_boards(boards):
    all_links = {}
    for board_name in boards.keys():
        links = get_article_links(driver, board_name, CONFIG["max_scroll"])
        print(f"✅ {board_name}: {len(links)} article links collected")
        all_links[board_name] = links

    data_by_board = {b: [] for b in boards.keys()}
    total_links = sum(len(v) for v in all_links.values())

    with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
        futures = []
        for board_name, links in all_links.items():
            for link in links:
                futures.append((board_name, executor.submit(get_article_content, link)))

        for board_name, future in tqdm(futures, total=total_links, desc="Fetching articles"):
            result = future.result()
            if result:
                data_by_board[board_name].append(result)

    for board_name, filename in boards.items():
        filepath = os.path.join(DATA_FOLDER, filename)
        if data_by_board[board_name]:
            pd.DataFrame(data_by_board[board_name]).to_csv(filepath, index=False, encoding="utf-8-sig")
            print(f"📂 Saved {len(data_by_board[board_name])} articles to {filepath}")

# ----------------------------
# CLEAN CSV FILES
# ----------------------------
remove_phrases = [
    "Dcard 需要確認您的連線是安全的"
]

def clean_csv(file_path, output_path):
    df = pd.read_csv(file_path, on_bad_lines="skip")
    df_cleaned = df.drop(columns=["Link"], errors="ignore").copy()

    if "ID" in df_cleaned.columns:
        df_cleaned = df_cleaned.drop(columns=["ID"])

    df_cleaned = df_cleaned.dropna(how="any")

    for col in ["Title", "Content"]:
        if col in df_cleaned.columns:
            df_cleaned = df_cleaned[df_cleaned[col].str.strip() != "請稍候..."]
            df_cleaned[col] = (
                df_cleaned[col]
                .astype(str)
                .str.replace(r"\s+", " ", regex=True)
                .apply(lambda x: "".join(x.replace(p, "") for p in remove_phrases))
                .str.strip()
            )

    if "Title" in df_cleaned.columns and "Content" in df_cleaned.columns:
        df_cleaned = df_cleaned[
            (df_cleaned["Title"].str.strip() != "") &
            (df_cleaned["Content"].str.strip() != "")
        ]

    df_cleaned.insert(0, "ID", range(1, len(df_cleaned) + 1))
    df_cleaned.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"✅ Cleaned CSV saved to: {output_path}")

# ----------------------------
# MAIN
# ----------------------------
if __name__ == "__main__":
    boards = {
        "travel": "travel.csv",
        "food": "food.csv",
        "job": "job.csv",
        "graduate_school": "graduate_school.csv",
        "exam": "exam.csv"
    }

    try:
        print("🚀 Dcard crawler started...")
        crawl_all_boards(boards)

        # Clean CSV files
        for board, filename in boards.items():
            filepath = os.path.join(DATA_FOLDER, filename)
            if os.path.exists(filepath):
                clean_csv(filepath, filepath)
            else:
                print(f"⚠️ File not found: {filepath}")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        print("🛑 Browser closed")
