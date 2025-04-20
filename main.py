from fastapi import FastAPI
import json
import asyncio
import base64
from playwright.async_api import async_playwright
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import subprocess
from pathlib import Path

# FastAPI application
app = FastAPI()

# Ensure Playwright uses its vendored browsers
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

# Debug: Check if Chromium is already installed
chromium_exec = Path("/opt/render/.cache/ms-playwright/chromium")
if not chromium_exec.exists():
    print("Chromium not found, installing...")

    # Install Chromium if not found
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
        print("Chromium installation attempted.")
    except Exception as e:
        print(f"Chromium install error: {e}")
else:
    print("Chromium is installed.")

# Google Drive credentials and setup
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
        print(f"[ERROR] File not found for upload: {local_path}")
        return

    if not folder_id:
        print("[ERROR] GDRIVE_FOLDER_ID is not set.")
        return

    try:
        # Check if file already exists in the *correct* folder
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
            print(f"[INFO] Updated {fname} in shared Drive folder.")
        else:
            file = drive_service.files().create(
                body={"name": fname, "parents": [folder_id]},
                media_body=MediaFileUpload(local_path, mimetype=mime_type),
                fields="id, webViewLink"
            ).execute()
            print(f"[INFO] Uploaded {fname} to shared Drive folder.")
            print(f"[LINK] View: {file['webViewLink']}")

    except Exception as e:
        print(f"[ERROR] Failed to upload {fname}: {e}")

# ———————————————————————————————————————————
# Judge scraping logic directly in main.py
# ———————————————————————————————————————————
JUDGE_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)"

async def fetch_golden_judges():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(JUDGE_URL, wait_until="networkidle")

        await page.wait_for_selector(".search-judge__item", timeout=10000)

        items = await page.query_selector_all(".search-judge__item")
        judges = []

        for item in items:
            name = await item.query_selector(".search-judge__title")
            region = await item.query_selector(".search-judge__subtitle")
            judges.append({
                "name": (await name.inner_text()).strip() if name else None,
                "location": (await region.inner_text()).strip() if region else None,
            })

        await browser.close()

        # Save results to file
        with open("golden_judges.json", "w") as f:
            json.dump(judges, f, indent=2)

        print(f"[INFO] Extracted {len(judges)} Golden Retriever judges.")

        # Upload to Google Drive
        upload_to_drive("golden_judges.json")
        upload_to_drive("golden_judges.csv")

# Main page route
@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

# Route to trigger scraping of Golden Retriever judges
@app.get("/run")
async def run():
    # Call the judge scraping function here
    await fetch_golden_judges()  # Run the function
    return {"message": "Scrape run complete"}
