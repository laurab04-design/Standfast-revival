from fastapi import FastAPI
import json
import asyncio
import base64
import os
import re
import subprocess
from pathlib import Path
import hashlib
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import httpx

from brazenbeacon_critiques_scraper import scrape_brazenbeacon_critiques

app = FastAPI()

BASE_URL = "https://www.thekennelclub.org.uk"
JUDGE_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)&SelectedChampionshipActivities=&SelectedNonChampionshipActivities=&SelectedPanelAFieldTrials=&SelectedPanelBFieldTrials=&SelectedSearchOptions=&SelectedSearchOptionsNotActivity=Dog+showing&Championship=False&NonChampionship=False&PanelA=False&PanelB=False&Distance=15&TotalResults=0&SearchProfile=True&SelectedBestInBreedGroups=&SelectedBestInSubGroups="

# Playwright path fix (Render specific)
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
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

        force_reupload = False
        if existing["files"]:
            file_id = existing["files"][0]["id"]
            existing_metadata = drive_service.files().get(fileId=file_id, fields="size, md5Checksum").execute()
            local_md5 = generate_md5(local_path)
            if existing_metadata.get("md5Checksum") == local_md5:
                print(f"[INFO] Skipped uploading {fname} — identical to existing file in Drive.")
                return
            print(f"[INFO] {fname} exists but content changed — overwriting.")
            try:
                drive_service.files().update(
                    fileId=file_id,
                    media_body=MediaFileUpload(local_path, mimetype=mime_type)
                ).execute()
                print(f"[INFO] Updated {fname} in Drive.")
            except Exception as update_error:
                if "File not found" in str(update_error):
                    print(f"[WARN] Ghost file detected for {fname}. Deleting and re-uploading...")
                    try:
                        drive_service.files().delete(fileId=file_id).execute()
                        force_reupload = True
                    except Exception as delete_error:
                        print(f"[ERROR] Could not delete ghost file {fname}: {delete_error}")
                        return
                else:
                    print(f"[ERROR] Update failed for {fname}: {update_error}")
                    return
        else:
            force_reupload = True

        if force_reupload:
            new_file = drive_service.files().create(
                body={"name": fname, "parents": [folder_id]},
                media_body=MediaFileUpload(local_path, mimetype=mime_type),
                fields="id, webViewLink"
            ).execute()
            print(f"[INFO] Uploaded {fname} to Drive.")
            print(f"[LINK] {new_file['webViewLink']}")

    except Exception as e:
        print(f"[ERROR] Failed to upload {fname}: {e}")

def generate_md5(file_path):
    md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5.update(chunk)
        return md5.hexdigest()
    except Exception as e:
        print(f"[WARNING] Could not hash {file_path}: {e}")
        return None

# API endpoints
@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

@app.get("/run")
async def run():
    await scrape_brazenbeacon_critiques()
    return {"message": "Critiques scrape complete"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        reload=False
    )
