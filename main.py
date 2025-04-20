from fastapi import FastAPI
import json
import asyncio
import base64
import os
import re
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = FastAPI()

BASE_URL = "https://www.thekennelclub.org.uk"
JUDGE_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)"

# Set Playwright path
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

# Chromium install if needed
if not Path("/opt/render/.cache/ms-playwright/chromium").exists():
    print("Chromium not found, installing...")
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        print(f"Chromium install error: {e}")
else:
    print("Chromium is installed.")

# Google Drive setup
creds_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_BASE64")
if creds_b64:
    with open("credentials.json", "wb") as f:
        f.write(base64.b64decode(creds_b64))
else:
    print("GOOGLE_SERVICE_ACCOUNT_BASE64 is not set.")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
credentials = service_account.Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
drive_service = build("drive", "v3", credentials=credentials)

def upload_to_drive(local_path, mime_type="application/json"):
    fname = os.path.basename(local_path)
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not os.path.exists(local_path):
        print(f"[ERROR] File not found: {local_path}")
        return
    if not folder_id:
        print("[ERROR] GDRIVE_FOLDER_ID not set.")
        return
    try:
        existing = drive_service.files().list(
            q=f"name='{fname}' and trashed=false and '{folder_id}' in parents",
            spaces="drive",
            fields="files(id)"
        ).execute()
        if existing["files"]:
            file_id = existing["files"][0]["id"]
            drive_service.files().update(
                fileId=file_id,
                media_body=MediaFileUpload(local_path, mimetype=mime_type)
            ).execute()
            print(f"[INFO] Updated {fname} in Drive.")
        else:
            new_file = drive_service.files().create(
                body={"name": fname, "parents": [folder_id]},
                media_body=MediaFileUpload(local_path, mimetype=mime_type),
                fields="id, webViewLink"
            ).execute()
            print(f"[INFO] Uploaded {fname} to Drive.")
            print(f"[LINK] {new_file['webViewLink']}")
    except Exception as e:
        print(f"[ERROR] Failed to upload {fname}: {e}")

# --- Scraper functions ---

async def fetch_golden_judges():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.route("**/*", lambda r, req: r.abort() if req.resource_type in ["image", "stylesheet", "font"] else r.continue_())
        page = await context.new_page()
        await page.goto(JUDGE_URL, wait_until="networkidle")
        await page.wait_for_selector("a.m-judge-card__link", timeout=10000)

        items = await page.query_selector_all("a.m-judge-card__link")
        judge_links = []

        for item in items:
            href = await item.get_attribute("href")
            if href and "judge-profile" in href and "judgeId=" in href:
                judge_links.append(BASE_URL + href)

        await browser.close()

        with open("judge_profile_links.json", "w") as f:
            json.dump(judge_links, f, indent=2)

        print(f"[INFO] Extracted {len(judge_links)} judge profile links.")
        upload_to_drive("judge_profile_links.json")

        await scrape_appointments_from_html(judge_links)

async def scrape_appointments_from_html(judge_links):
    import httpx
    from bs4 import BeautifulSoup

    for link in judge_links:
        try:
            resp = httpx.get(link, timeout=10)
            resp.raise_for_status()
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            judge_id = re.search(r'judgeId=([a-f0-9\-]+)', link).group(1)
            judge_name_tag = soup.select_one(".m-judge-card__title")
            judge_name = judge_name_tag.get_text(strip=True) if judge_name_tag else "Unknown"

            appointments = []
            for block in soup.select(".m-judge-profile__appointment"):
                appointments.append({
                    "date": block.select_one(".m-appointment-date")?.get_text(strip=True),
                    "club_name": block.select_one(".m-appointment-club")?.get_text(strip=True),
                    "breed_average": block.select_one(".m-appointment-breed-average")?.get_text(strip=True),
                    "dogs_judged": block.select_one(".m-appointment-dogs")?.get_text(strip=True),
                })

            result = {
                "judge_name": judge_name,
                "judge_id": judge_id,
                "appointments": appointments
            }

            with open(f"judge_{judge_id}_appointments.json", "w") as f:
                json.dump(result, f, indent=2)

            print(f"[INFO] Scraped {len(appointments)} appointments for {judge_name}.")
            upload_to_drive(f"judge_{judge_id}_appointments.json")

        except Exception as e:
            print(f"[ERROR] Failed to process judge page: {link} — {e}")
            continue

# --- Routes ---

@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

@app.get("/run")
async def run():
    await fetch_golden_judges()
    return {"message": "Scrape run complete"}
