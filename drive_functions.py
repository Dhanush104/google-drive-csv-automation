import io
import os
import pandas as pd
import json

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload


SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_folder_id(url):
    return url.split("/folders/")[1].split("?")[0]

def get_csv_files(drive, folder_id):

    files = []
    page_token = None

    while True:

        result = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType, version)",
            pageSize=1000,
            pageToken=page_token
        ).execute()

        files.extend(
            file for file in result.get("files", [])
            if file["name"].lower().endswith(".csv")
            and file["mimeType"] == "text/csv"
        )

        page_token = result.get("nextPageToken")

        if not page_token:
            break

    return files


def find_file(drive, filename, folder_id):

    result = drive.files().list(
        q=f"name = '{filename}' "
          f"and '{folder_id}' in parents "
          f"and trashed = false",
        fields="files(id, name)"
    ).execute()

    files = result.get("files", [])

    if files:
        return files[0]["id"]

    return None


def login(token_file):
    creds = None

    if token_file == "source_token.json":
        token_json = os.environ.get("SOURCE_TOKEN")
    else:
        token_json = os.environ.get("DESTINATION_TOKEN")

    if token_json:
        creds = Credentials.from_authorized_user_info(
            json.loads(token_json),
            SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if os.path.exists(token_file):
                creds = Credentials.from_authorized_user_file(
                    token_file,
                    SCOPES
                )
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json",
                    SCOPES
                )
                creds = flow.run_local_server(port=0)

    return build("drive", "v3", credentials=creds)


def download_csv(drive, file_id):

    request = drive.files().get_media(fileId=file_id)

    data = io.BytesIO()

    downloader = MediaIoBaseDownload(data, request)

    done = False

    while not done:
        _, done = downloader.next_chunk()

    data.seek(0)

    return pd.read_csv(data)


def upload_csv(drive, row, filename, folder_id):

    data = io.BytesIO()

    row.to_frame().T.to_csv(
        data,
        index=False
    )

    data.seek(0)

    file_id = find_file(
        drive,
        filename,
        folder_id
    )

    media = MediaIoBaseUpload(
        data,
        mimetype="text/csv"
    )

    if file_id:

        drive.files().update(
            fileId=file_id,
            media_body=media
        ).execute()

        print(f"Updated: {filename}")

    else:

        file = {
            "name": filename,
            "parents": [folder_id]
        }

        drive.files().create(
            body=file,
            media_body=media
        ).execute()

        print(f"Created: {filename}")
    

def load_processed():

    if not os.path.exists("processed.json"):
        return {}

    with open("processed.json", "r") as file:
        return json.load(file)


def save_processed(data):

    with open("processed.json", "w") as file:
        json.dump(data, file, indent=4)


source_url = input("Enter Source Folder URL: ")
destination_url = input("Enter Destination Folder URL: ")

source_id = get_folder_id(source_url)
destination_id = get_folder_id(destination_url)

source_drive = login("source_token.json")
destination_drive = login("destination_token.json")

processed = load_processed()

files = get_csv_files(
    source_drive,
    source_id
)

for file in files:

    file_id = file["id"]
    filename = file["name"]
    version = file["version"]

    old_version = processed.get(file_id)

    if old_version == version:

        print(f"Skipped: {filename} - no changes")
        continue

    print(f"Processing: {filename}")

    df = download_csv(
        source_drive,
        file_id
    )

    for _, row in df.iterrows():

        product_id = row["Product id"]

        upload_csv(
            destination_drive,
            row,
            f"{product_id}.csv",
            destination_id
        )

    processed[file_id] = version

    save_processed(processed)

print("Finished!")
