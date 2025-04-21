from fastapi import FastAPI
import json
import asyncio
import base64
import os
import re
import subprocess
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = FastAPI()

BASE_URL = "https://www.thekennelclub.org.uk"
JUDGE_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)&SelectedChampionshipActivities=&SelectedNonChampionshipActivities=&SelectedPanelAFieldTrials=&SelectedPanelBFieldTrials=&SelectedSearchOptions=&SelectedSearchOptionsNotActivity=Dog+showing&Championship=False&NonChampionship=False&PanelA=False&PanelB=False&Distance=15&TotalResults=0&SearchProfile=True&SelectedBestInBreedGroups=&SelectedBestInSubGroups="

# Set Playwright path (retained in case reused)
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

# Chromium install (left as-is in case needed for fallback)
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
    try:
        resp = httpx.get(JUDGE_URL, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to load judge list page: {e}")
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.select("a.m-judge-card__link")
    judge_links = [BASE_URL + link["href"] for link in links if "judge-profile" in link["href"]]

    with open("judge_profile_links.json", "w") as f:
        json.dump(judge_links, f, indent=2)

    print(f"[INFO] Extracted {len(judge_links)} judge profile links.")
    upload_to_drive("judge_profile_links.json")

    await scrape_appointments_from_html(judge_links)

async def scrape_appointments_from_html(judge_links):
    async with httpx.AsyncClient(timeout=10) as client:
        for link in judge_links:
            try:
                resp = await client.get(link)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                judge_id_match = re.search(r'judgeid=([a-f0-9\-]+)', link, re.IGNORECASE)
                if not judge_id_match:
                    print(f"[ERROR] Could not extract judge ID from: {link}")
                    continue
                judge_id = judge_id_match.group(1)

                name_tag = soup.select_one("h1.o-page-title")
                judge_name = name_tag.get_text(strip=True) if name_tag else "Unknown"

                appointments = []
                for block in soup.select(".m-judge-profile__appointment"):
                    breed = block.get_text().lower()
                    if "golden" not in breed:
                        continue
                    appointments.append({
                        "date": block.select_one(".m-appointment-date").get_text(strip=True)
                                if block.select_one(".m-appointment-date") else None,
                        "club_name": block.select_one(".m-appointment-club").get_text(strip=True)
                                    if block.select_one(".m-appointment-club") else None,
                        "breed_average": block.select_one(".m-appointment-breed-average").get_text(strip=True)
                                         if block.select_one(".m-appointment-breed-average") else None,
                        "dogs_judged": block.select_one(".m-appointment-dogs").get_text(strip=True)
                                       if block.select_one(".m-appointment-dogs") else None,
                    })

                # Calculate metadata
years_active = set()
clubs_judged = set()
other_breeds = set()

for appt in appointments:
    # Extract year from date string if available
    if appt.get("date"):
        year_match = re.search(r"\b(\d{4})\b", appt["date"])
        if year_match:
            years_active.add(int(year_match.group(1)))

    # Collect club names
    if appt.get("club_name"):
        clubs_judged.add(appt["club_name"])

        # Collect other breeds judged (if not Golden)
        if appt.get("club_name") and "golden" not in appt["club_name"].lower():
            breed_match = re.findall(
                r"\b(?:retriever|spaniel|setter|terrier|hound|pointer|poodle|collie|mastiff|bulldog|boxer|dobermann|whippet|beagle|ridgeback|shi[h|t]zu|labrador|golden)\b",
                appt["club_name"].lower()
            )
            for breed in breed_match:
                if "golden" not in breed:
                    other_breeds.add(breed.title())

        # Build result with metadata
        result = {
            "judge_name": judge_name,
            "judge_id": judge_id,
            "total_appointments": len(appointments),
            "years_active": sorted(list(years_active)),
            "clubs_judged": sorted(list(clubs_judged)),
            "golden_only": len(other_breeds) == 0,
            "other_breeds": sorted(list(other_breeds)),
            "appointments": appointments,
            "last_appointment": max(
                (appt.get("date") for appt in appointments if appt.get("date")),
                default=None
            )
        }

        with open(f"judge_{judge_id}_appointments.json", "w") as f:
            json.dump(result, f, indent=2)

        print(f"[INFO] Scraped {len(appointments)} appointments for {judge_name}.")
        upload_to_drive(f"judge_{judge_id}_appointments.json")
# --- Routes ---

@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

@app.get("/run")
async def run():
    await fetch_golden_judges()
    return {"message": "Scrape run complete"}
