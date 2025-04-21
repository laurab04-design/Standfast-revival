import asyncio
from playwright.async_api import async_playwright
import json
import httpx
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

# Google Drive upload function
def upload_to_drive(local_path, mime_type="application/json"):
    SCOPES = ["https://www.googleapis.com/auth/drive.file"]
    creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    drive_service = build("drive", "v3", credentials=creds)

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
            print(f"[INFO] Updated {fname} in Google Drive.")
        else:
            file = drive_service.files().create(
                body={"name": fname, "parents": [folder_id]},
                media_body=MediaFileUpload(local_path, mimetype=mime_type),
                fields="id, webViewLink"
            ).execute()
            print(f"[INFO] Uploaded {fname} to Google Drive.")
            print(f"[LINK] View: {file['webViewLink']}")

    except Exception as e:
        print(f"[ERROR] Failed to upload {fname}: {e}")

# URLs
BASE_URL = "https://www.thekennelclub.org.uk"
JUDGE_LIST_URL = "JUDGE_LIST_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)&SelectedChampionshipActivities=&SelectedNonChampionshipActivities=&SelectedPanelAFieldTrials=&SelectedPanelBFieldTrials=&SelectedSearchOptions=&SelectedSearchOptionsNotActivity=Dog+showing&Championship=False&NonChampionship=False&PanelA=False&PanelB=False&Distance=15&TotalResults=0&SearchProfile=True&SelectedBestInBreedGroups=&SelectedBestInSubGroups="

# Scrape the judge profile links
async def fetch_judge_profile_urls():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("[INFO] Navigating to judge list...")
        await page.goto(JUDGE_LIST_URL, wait_until="networkidle")

        link_els = await page.query_selector_all("a.m-judge-card__link")
        profile_urls = []

        for link in link_els:
            href = await link.get_attribute("href")
            if href and "judge-profile" in href and "judgeId=" in href:
                full_url = BASE_URL + href
                profile_urls.append(full_url)
                print(f"[FOUND] {full_url}")

        await browser.close()

        with open("judge_profile_urls.json", "w") as f:
            json.dump(profile_urls, f, indent=2)

        print(f"[DONE] Saved {len(profile_urls)} judge profile URLs to judge_profile_urls.json")
        upload_to_drive("judge_profile_urls.json", "application/json")

# Entrypoint
if __name__ == "__main__":
    asyncio.run(fetch_judge_profile_urls())
