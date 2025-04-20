import os
import json
import base64
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Decode and write credentials from env
creds_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_BASE64")
if creds_b64:
    with open("credentials.json", "wb") as f:
        f.write(base64.b64decode(creds_b64))

# Build Drive service
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
credentials = service_account.Credentials.from_service_account_file(
    "credentials.json", scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=credentials)

def upload_to_drive(local_path, mime_type):
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
            print(f"[INFO] Updated {fname} in Drive.")
        else:
            file = drive_service.files().create(
                body={"name": fname, "parents": [folder_id]},
                media_body=MediaFileUpload(local_path, mimetype=mime_type),
                fields="id, webViewLink"
            ).execute()
            print(f"[INFO] Uploaded {fname}. View: {file['webViewLink']}")
    except Exception as e:
        print(f"[ERROR] Failed to upload {fname}: {e}")
