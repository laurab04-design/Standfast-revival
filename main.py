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

           # Get existing file metadata for comparison
            existing_metadata = drive_service.files().get(fileId=file_id, fields="size, md5Checksum").execute()
            local_md5 = generate_md5(local_path)

            if existing_metadata.get("md5Checksum") == local_md5:
                print(f"[INFO] Skipped uploading {fname} — identical to existing file in Drive.")
                return  # Stop here, no need to update
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

def generate_data_hash(data: str) -> str:
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def generate_md5(file_path):
    """Generate an MD5 hash for a given file (to match Google Drive's checksum)."""
    md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5.update(chunk)
        return md5.hexdigest()
    except Exception as e:
        print(f"[WARNING] Could not hash {file_path}: {e}")
        return None

def should_update_file(local_path, new_data):
    if not os.path.exists(local_path):
        return True  # No file yet
    try:
        with open(local_path, 'r') as f:
            existing_data = json.load(f)
        return existing_data != new_data  # Only update if the content has changed
    except Exception as e:
        print(f"[WARNING] Could not read existing file {local_path}: {e}")
        return True  # If unreadable, play it safe and overwrite

# ---------------------------------------------
# FETCH JUDGE LINKS WITH PLAYWRIGHT ONLY
# ---------------------------------------------
async def fetch_golden_judges():
    print("[INFO] Launching Playwright to fetch filtered judge list...")
    judge_links = set()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(JUDGE_URL, wait_until="networkidle")

            # Scroll until all judge cards are loaded
            previous_height = None
            while True:
                current_height = await page.evaluate("document.body.scrollHeight")
                if previous_height == current_height:
                    break
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                previous_height = current_height

            # Filter: profile links only
            elements = await page.query_selector_all("a.m-judge-card__link")
            for el in elements:
                href = await el.get_attribute("href")
                if href and "judge-profile/" in href and "judge-appointment" not in href:
                    judge_links.add(BASE_URL + href)

            await browser.close()

        judge_links = sorted(judge_links)
        with open("judge_profile_links.json", "w") as f:
            json.dump(judge_links, f, indent=2)

        print(f"[INFO] Extracted {len(judge_links)} filtered Golden Retriever judge links.")
        upload_to_drive("judge_profile_links.json")
        await scrape_appointments_from_html(judge_links)

    except Exception as e:
        print(f"[ERROR] Playwright judge fetch failed: {e}")

# ---------------------------------------------
# SCRAPE APPOINTMENTS FOR FILTERED JUDGES ONLY
# ---------------------------------------------
async def scrape_appointments_from_html(judge_links):
    PROCESSED_FILE = "processed_judges.json"
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            processed_judges = json.load(f)
    else:
        processed_judges = {}

    async with httpx.AsyncClient(timeout=10) as client:
        for profile_url in judge_links:
            try:
                judge_id_match = re.search(r'judgeid=([a-f0-9\-]+)', profile_url, re.IGNORECASE)
                if not judge_id_match:
                    print(f"[ERROR] Could not extract judge ID from: {profile_url}")
                    continue
                judge_id = judge_id_match.group(1)

                profile_resp = await client.get(profile_url)
                profile_resp.raise_for_status()
                profile_soup = BeautifulSoup(profile_resp.text, "html.parser")
                current_data_hash = generate_data_hash(profile_resp.text)

                if judge_id in processed_judges:
                    if processed_judges[judge_id].get("data_hash") == current_data_hash:
                        print(f"[INFO] Skipping unchanged judge: {judge_id}")
                        continue

                name_tag = profile_soup.select_one("div.t-judge-profile__name")
                raw_name = name_tag.get_text(strip=True) if name_tag else ""
                match = re.match(r"^(.*?)(?:\s*Breed Judge ID\s*(\d+))?$", raw_name)
                judge_name = match.group(1).strip() if match else "Unknown"
                breed_judge_id = match.group(2) if match else None

                address_tag = profile_soup.select_one("dt:contains('Address') + dd")
                address = address_tag.get_text(separator=", ", strip=True) if address_tag else None

                approved_breeds = []
                group_headers = profile_soup.select("h4")
                for group in group_headers:
                    group_name = group.get_text(strip=True)
                    ul = group.find_next_sibling("ul", class_="t-judge-profile__long-list")
                    if ul:
                        for li in ul.find_all("li"):
                            breed = li.find("a") or li.find("label")
                            level = li.find_all("label")[-1]
                            if breed and level:
                                approved_breeds.append({
                                    "group": group_name,
                                    "breed": breed.get_text(strip=True),
                                    "level": level.get_text(strip=True)
                                })

                appt_url = f"{BASE_URL}/search/find-a-judge/judge-profile/judge-appointment/?JudgeId={judge_id}&SelectedBreed=14feb8f2-55ee-e811-a8a3-002248005d25"
                appt_resp = await client.get(appt_url)
                appt_resp.raise_for_status()
                appt_soup = BeautifulSoup(appt_resp.text, "html.parser")

                appointments = []
                rows = appt_soup.select("table.a-table__table tbody tr")
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    if len(cols) < 5:
                        continue
                    sex_icon = cols[2].find("svg")
                    sex = None
                    if sex_icon:
                        if "a-icon--female" in sex_icon.get("class", []):
                            sex = "Bitch"
                        elif "a-icon--male" in sex_icon.get("class", []):
                            sex = "Dog"
                    appointments.append({
                        "date": cols[0].get_text(strip=True),
                        "club_name": cols[1].get_text(strip=True),
                        "sex_judged": sex,
                        "dogs_judged": cols[3].get_text(strip=True),
                        "breed_average": cols[4].get_text(strip=True)
                    })

                result = {
                    "judge_name": judge_name,
                    "judge_id": judge_id,
                    "breed_judge_id": breed_judge_id,
                    "address": address,
                    "approved_breeds": approved_breeds,
                    "total_appointments": len(appointments),
                    "years_active": sorted({
                        int(m.group(1)) for a in appointments if (m := re.search(r"\b(\d{4})\b", a["date"]))
                    }),
                    "clubs_judged": sorted({a["club_name"] for a in appointments if a.get("club_name")}),
                    "golden_only": True,
                    "other_breeds": [],
                    "appointments": appointments,
                    "last_appointment": max((a["date"] for a in appointments if a.get("date")), default=None)
                }

                fname = f"judge_{judge_id}_appointments.json"
                if should_update_file(fname, result):
                    with open(fname, "w") as f:
                        json.dump(result, f, indent=2)
                    print(f"[INFO] Scraped {len(appointments)} appointments for {judge_name} (Breed Judge ID: {breed_judge_id}).")
                    upload_to_drive(fname)
                else:
                    print(f"[INFO] Skipped updating {fname} — no changes detected.")

                processed_judges[judge_id] = {"data_hash": current_data_hash}
                if should_update_file(PROCESSED_FILE, processed_judges):
                    with open(PROCESSED_FILE, "w") as f:
                        json.dump(processed_judges, f, indent=2)
                    upload_to_drive(PROCESSED_FILE)
                else:
                    print(f"[INFO] Skipped updating {PROCESSED_FILE} — no changes detected.")

            except Exception as e:
                print(f"[ERROR] Failed to process judge: {profile_url}\nReason: {e}")

    with open(PROCESSED_FILE, "w") as f:
        json.dump(processed_judges, f, indent=2)
    upload_to_drive(PROCESSED_FILE)
# API endpoints
@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

@app.get("/run")
async def run():
    await fetch_golden_judges()
    return {"message": "Scrape run complete"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),  # Use Render's assigned port, fallback to 10000 for local testing
        reload=False
    )
