import asyncio
from playwright.async_api import async_playwright
import json
import os
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

BASE_URL = "https://kcjudgescritiques.org.uk"
SEARCH_TERM = "Brazenbeacon Artemis"
OUTPUT_FILE = "brazenbeacon_critiques.json"
SEEN_FILE = "brazenbeacon_critiques_seen.json"

def upload_to_drive(local_path, mime_type="application/json"):
    SCOPES = ["https://www.googleapis.com/auth/drive.file"]
    creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    drive_service = build("drive", "v3", credentials=creds)

    fname = os.path.basename(local_path)
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not os.path.exists(local_path) or not folder_id:
        print(f"[ERROR] Missing file or GDRIVE_FOLDER_ID: {local_path}")
        return

    try:
        res = drive_service.files().list(
            q=f"name='{fname}' and trashed=false and '{folder_id}' in parents",
            spaces="drive",
            fields="files(id, name)"
        ).execute()

        if res["files"]:
            file_id = res["files"][0]["id"]
            drive_service.files().update(
                fileId=file_id,
                media_body=MediaFileUpload(local_path, mimetype=mime_type)
            ).execute()
            print(f"[INFO] Updated {fname} on Google Drive.")
        else:
            file = drive_service.files().create(
                body={"name": fname, "parents": [folder_id]},
                media_body=MediaFileUpload(local_path, mimetype=mime_type),
                fields="id, webViewLink"
            ).execute()
            print(f"[INFO] Uploaded {fname}. Link: {file['webViewLink']}")
    except Exception as e:
        print(f"[ERROR] Google Drive upload failed: {e}")

async def extract_critique_with_retry(context, url, max_retries=1):
    for attempt in range(max_retries + 1):
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_selector("div.node__content", timeout=8000)

            data = {
                "url": url,
                "scraped_at": datetime.utcnow().isoformat(),
                "show_name": await page.inner_text("h1.page-title"),
                "breed": await page.inner_text("div.field--name-field-breed span"),
                "judge": await page.inner_text("div.field--name-field-judge span"),
                "show_date": await page.inner_text("div.field--name-field-date span"),
                "published_date": await page.inner_text("div.field--name-field-published span"),
                "critique": (await page.inner_text("div.field--name-body")).strip()
            }

            await page.close()
            return data
        except Exception as e:
            print(f"[WARN] Error fetching {url} (attempt {attempt + 1}): {e}")
            if attempt == max_retries:
                return None

async def scrape_brazenbeacon_critiques():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("[INFO] Visiting site...")
        await page.goto(f"{BASE_URL}/critique-listing/", wait_until="domcontentloaded")

        # Handle Quantcast cookie overlay
        try:
            await page.wait_for_selector('#qc-cmp2-ui', timeout=5000)
            await page.click('button[mode="primary"]', timeout=3000)
            print("[INFO] Accepted cookie overlay.")
        except Exception:
            print("[INFO] No cookie overlay detected.")

        # Accept T&Cs modal
        try:
            await page.wait_for_selector("#TermsAndConditionsModal", timeout=5000)
            checkbox = await page.query_selector('#TermsAndConditionsModal input[type="checkbox"]')
            if checkbox:
                await checkbox.check()
                await page.click('#TermsAndConditionsModal button.btn-primary')
                print("[INFO] Accepted T&Cs modal.")
        except Exception:
            print("[INFO] No T&Cs modal shown.")

        # Fill in search and submit using accurate HTML selectors
        await page.fill('input[name="Keyword"]', SEARCH_TERM)
        await page.click('input[type="submit"][value="Search"]')
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector("div.views-row", timeout=5000)

        # Load seen URLs
        seen_urls = set()
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                seen_urls = set(json.load(f))
            print(f"[INFO] Loaded {len(seen_urls)} previously saved critique URLs.")

        # Scrape
        results = []
        entries = await page.query_selector_all("div.views-row")
        print(f"[INFO] Found {len(entries)} search results.")

        for entry in entries:
            try:
                a_tag = await entry.query_selector("a")
                relative_url = await a_tag.get_attribute("href")
                full_url = BASE_URL + relative_url

                if full_url in seen_urls:
                    print(f"[SKIP] Already saved: {full_url}")
                    continue

                print(f"[SCRAPING] {full_url}")
                detail = await extract_critique_with_retry(context, full_url)
                if detail:
                    results.append(detail)
                    seen_urls.add(full_url)
                else:
                    print(f"[ERROR] Failed permanently: {full_url}")

            except Exception as e:
                print(f"[ERROR] Failed parsing entry block: {e}")

        # Load existing JSON
        existing = []
        if os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)

        combined = existing + results

        # Write data
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(combined, f, indent=2, ensure_ascii=False)

        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(seen_urls), f, indent=2)

        print(f"[DONE] Total saved: {len(combined)} critiques.")
        upload_to_drive(OUTPUT_FILE, "application/json")
        upload_to_drive(SEEN_FILE, "application/json")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_brazenbeacon_critiques())
