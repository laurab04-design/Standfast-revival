import asyncio
from playwright.async_api import async_playwright
import json
import csv
import os
import re
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
        # Check if file exists in Google Drive
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

# URL of the page listing Golden Retriever judges
JUDGE_LIST_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)"
BASE_URL = "https://www.thekennelclub.org.uk"

async def fetch_golden_judges():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("[INFO] Navigating to judge list...")
        await page.goto(JUDGE_LIST_URL, wait_until="networkidle")
        await page.wait_for_selector(".search-judge__item", timeout=10000)

        items = await page.query_selector_all(".search-judge__item")
        judges = []

        # Fetch judge names, locations, and profile URLs
        for item in items:
            name_el = await item.query_selector(".search-judge__title")
            region_el = await item.query_selector(".search-judge__subtitle")
            link_el = await item.query_selector("a")

            name = (await name_el.inner_text()).strip() if name_el else None
            location = (await region_el.inner_text()).strip() if region_el else None
            href = await link_el.get_attribute("href") if link_el else None
            profile_url = BASE_URL + href if href else None

            print(f"[INFO] Judge: {name} ({location}) — {profile_url}")
            judge_data = {
                "name": name,
                "location": location,
                "profile_url": profile_url,
                "appointments": []
            }

            if profile_url:
                judge_page = await context.new_page()
                try:
                    # Visit the judge's profile page
                    await judge_page.goto(profile_url, wait_until="networkidle")
                    await judge_page.wait_for_selector(".m-judge-profile", timeout=5000)
                    
                    # Extracting appointment information for each judge
                    rows = await judge_page.query_selector_all('.m-judge-profile__appointment')
                    for row in rows:
                        date = await row.query_selector('.m-appointment-date')
                        club_name = await row.query_selector('.m-appointment-club')
                        breed_average = await row.query_selector('.m-appointment-breed-average')
                        dogs_judged = await row.query_selector('.m-appointment-dogs')

                        appointment = {
                            "date": await date.inner_text() if date else None,
                            "club_name": await club_name.inner_text() if club_name else None,
                            "breed_average": await breed_average.inner_text() if breed_average else None,
                            "dogs_judged": await dogs_judged.inner_text() if dogs_judged else None
                        }

                        judge_data["appointments"].append(appointment)
                except Exception as e:
                    print(f"[WARN] Failed to parse {profile_url}: {e}")
                await judge_page.close()

            # Add the judge data to the list of judges
            judges.append(judge_data)

        await browser.close()

        # Save the results as JSON
        with open("golden_judges.json", "w") as jf:
            json.dump(judges, jf, indent=2)

        # Save the results as CSV
        with open("golden_judges.csv", "w", newline="") as cf:
            writer = csv.writer(cf)
            writer.writerow(["Name", "Location", "Profile URL", "Appointments"])
            for j in judges:
                # Writing each judge's details and their appointments
                appointments = "; ".join([f"{a['date']} ({a['club_name']})" for a in j["appointments"]])
                writer.writerow([j["name"], j["location"], j["profile_url"], appointments])

        print(f"[INFO] Saved {len(judges)} judges to golden_judges.json and golden_judges.csv")

        # Upload to Google Drive
        upload_to_drive("golden_judges.json", "application/json")
        upload_to_drive("golden_judges.csv", "text/csv")

# Run the scraping function if this script is executed directly
if __name__ == "__main__":
    asyncio.run(fetch_golden_judges())
