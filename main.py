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
                        raise Exception("Force reupload after deletion")
                    except Exception as delete_error:
                        print(f"[ERROR] Could not delete ghost file {fname}: {delete_error}")
                        return
                else:
                    print(f"[ERROR] Update failed for {fname}: {update_error}")
                    return

        if not existing["files"] or "Force reupload" in str(update_error):
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
        for profile_url in judge_links:
            try:
                # Extract judgeId
                judge_id_match = re.search(r'judgeid=([a-f0-9\-]+)', profile_url, re.IGNORECASE)
                if not judge_id_match:
                    print(f"[ERROR] Could not extract judge ID from: {profile_url}")
                    continue
                judge_id = judge_id_match.group(1)

                # Fetch profile page
                profile_resp = await client.get(profile_url)
                profile_resp.raise_for_status()
                profile_soup = BeautifulSoup(profile_resp.text, "html.parser")

                # Judge name
                name_tag = profile_soup.select_one("h1.o-page-title")
                judge_name = name_tag.get_text(strip=True) if name_tag else "Unknown"

                # Judge address
                address = None
                address_tag = profile_soup.select_one("p:has(strong:-soup-contains('Address'))")
                if address_tag:
                    address = address_tag.get_text(separator=" ").strip()

                # Breed Judge ID
                breed_judge_id = None
                breed_id_tag = profile_soup.find("p", string=re.compile("Breed Judge ID", re.IGNORECASE))
                if breed_id_tag:
                    match = re.search(r'Breed Judge ID\s*:\s*(\d+)', breed_id_tag.get_text())
                    if match:
                        breed_judge_id = match.group(1)

                # Approved breeds and levels
                approved_breeds = []
                breed_section = profile_soup.find("h2", string="Breeds:")
                if breed_section:
                    ul = breed_section.find_next_sibling("ul")
                    if ul:
                        for li in ul.find_all("li"):
                            text = li.get_text(separator="|")
                            parts = text.split("|")
                            if len(parts) == 2:
                                approved_breeds.append({
                                    "breed": parts[0].strip(),
                                    "level": parts[1].strip()
                                })

                # Fetch Golden Retriever appointments
                appt_url = f"{BASE_URL}/search/find-a-judge/judge-profile/judge-appointment/?JudgeId={judge_id}&SelectedBreed=14feb8f2-55ee-e811-a8a3-002248005d25"
                appt_resp = await client.get(appt_url)
                appt_resp.raise_for_status()
                appt_soup = BeautifulSoup(appt_resp.text, "html.parser")

                appointments = []
                for block in appt_soup.select(".m-judge-profile__appointment"):
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

                years_active = set()
                clubs_judged = set()
                for appt in appointments:
                    if appt.get("date"):
                        m = re.search(r"\b(\d{4})\b", appt["date"])
                        if m:
                            years_active.add(int(m.group(1)))
                    if appt.get("club_name"):
                        clubs_judged.add(appt["club_name"])

                result = {
                    "judge_name": judge_name,
                    "judge_id": judge_id,
                    "breed_judge_id": breed_judge_id,
                    "address": address,
                    "approved_breeds": approved_breeds,
                    "total_appointments": len(appointments),
                    "years_active": sorted(list(years_active)),
                    "clubs_judged": sorted(list(clubs_judged)),
                    "golden_only": True,
                    "other_breeds": [],
                    "appointments": appointments,
                    "last_appointment": max((a.get("date") for a in appointments if a.get("date")), default=None)
                }

                fname = f"judge_{judge_id}_appointments.json"
                with open(fname, "w") as f:
                    json.dump(result, f, indent=2)
                print(f"[INFO] Scraped {len(appointments)} appointments for {judge_name}.")
                upload_to_drive(fname)

            except Exception as e:
                print(f"[ERROR] Failed to process judge: {profile_url}\nReason: {e}")
                continue
# --- Routes ---

@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

@app.get("/run")
async def run():
    await fetch_golden_judges()
    return {"message": "Scrape run complete"}
