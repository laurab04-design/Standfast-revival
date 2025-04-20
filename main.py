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
import re

# FastAPI application
app = FastAPI()

BASE_URL = "https://www.thekennelclub.org.uk"

# Ensure Playwright uses its vendored browsers
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

# Debug: Check if Chromium is already installed
chromium_exec = Path("/opt/render/.cache/ms-playwright/chromium")
if not chromium_exec.exists():
    print("Chromium not found, installing...")
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

# Judge scraping logic
JUDGE_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)&SelectedChampionshipActivities=&SelectedNonChampionshipActivities=&SelectedPanelAFieldTrials=&SelectedPanelBFieldTrials=&SelectedSearchOptions=&SelectedSearchOptionsNotActivity=Dog+showing&Championship=False&NonChampionship=False&PanelA=False&PanelB=False&Distance=15&TotalResults=0&SearchProfile=True&SelectedBestInBreedGroups=&SelectedBestInSubGroups="

async def fetch_golden_judges():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.route("**/*", lambda route, request: route.abort()
                            if request.resource_type in ["image", "stylesheet", "font"]
                            else route.continue_())

        page = await context.new_page()
        await page.goto(JUDGE_URL, wait_until="networkidle")
        await page.wait_for_selector("a.m-judge-card__link", timeout=10000)

        items = await page.query_selector_all("a.m-judge-card__link")
        judge_links = []

        for item in items:
            href = await item.get_attribute("href")
            if href and "judge-profile" in href and "judgeId=" in href:
                full_url = BASE_URL + href
                judge_links.append(full_url)

        await browser.close()

        with open("judge_profile_links.json", "w") as f:
            json.dump(judge_links, f, indent=2)

        print(f"[INFO] Extracted {len(judge_links)} Golden Retriever judge profile links.")
        upload_to_drive("judge_profile_links.json")

        await fetch_judge_appointments(judge_links)

async def fetch_judge_appointments(judge_links):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        # Block unnecessary resources
        await context.route("**/*", lambda route, request: route.abort()
                            if request.resource_type in ["image", "stylesheet", "font"]
                            else route.continue_())

        page = await context.new_page()

        for link in judge_links:
            try:
                await page.goto(link, wait_until="networkidle")

                # Extract judge ID from URL
                judge_id_match = re.search(r'judgeId=([a-f0-9\-]+)', link)
                if not judge_id_match:
                    print(f"[WARN] Skipping malformed judge link: {link}")
                    continue
                judge_id = judge_id_match.group(1)

                # Scrape raw HTML
                html = await page.content()

                # Parse judge name from raw HTML
                name_match = re.search(r'<h1[^>]*class="m-judge-card__title"[^>]*>(.*?)</h1>', html)
                judge_name = name_match.group(1).strip() if name_match else "Unknown"

                # Extract appointments
                appointments = []
                blocks = re.findall(r'<div class="m-judge-profile__appointment">(.*?)</div>', html, re.DOTALL)
                for block in blocks:
                    date = re.search(r'<div[^>]*class="m-appointment-date"[^>]*>(.*?)</div>', block)
                    club = re.search(r'<div[^>]*class="m-appointment-club"[^>]*>(.*?)</div>', block)
                    avg = re.search(r'<div[^>]*class="m-appointment-breed-average"[^>]*>(.*?)</div>', block)
                    dogs = re.search(r'<div[^>]*class="m-appointment-dogs"[^>]*>(.*?)</div>', block)

                    appointments.append({
                        "date": date.group(1).strip() if date else None,
                        "club_name": club.group(1).strip() if club else None,
                        "breed_average": avg.group(1).strip() if avg else None,
                        "dogs_judged": dogs.group(1).strip() if dogs else None
                    })

                # Save to file
                judge_details = {
                    "judge_name": judge_name,
                    "judge_id": judge_id,
                    "appointments": appointments
                }

                with open(f"judge_{judge_id}_appointments.json", "w") as f:
                    json.dump(judge_details, f, indent=2)

                print(f"[INFO] Scraped {len(appointments)} appointments for judge {judge_name} ({judge_id}).")
                upload_to_drive(f"judge_{judge_id}_appointments.json")

            except Exception as e:
                print(f"[ERROR] Failed to process judge page: {link}\nReason: {e}")
                continue

        await browser.close()

# Main page route
@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

@app.get("/run")
async def run():
    await fetch_golden_judges()
    return {"message": "Scrape run complete"}
