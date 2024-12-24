import os
from requests import Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
import pandas as pd
from openpyxl import load_workbook
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from flask import Flask, jsonify 
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path="../env/.env")

# Retrieve environment variables
api_key = os.getenv("api_key")
service_account_json = "../Credentials.json"  # Path to your service account credentials
parent_folder = os.getenv("parent_folder")

app = Flask(__name__)

def handler(request, context):
    return app(request.environ, start_response)


# Helper functions
def fetch_add_to_excel(api_key, limit=50):
    """Fetch and sort cryptocurrency data from the CoinMarketCap API."""
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    parameters = {
        "start": "1",  # Starting rank
        "limit": limit,  # Number of cryptocurrencies to fetch
        "convert": "USD",  # Convert prices to USD
    }
    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": api_key,  # API key header
    }

    session = Session()
    session.headers.update(headers)

    try:
        response = session.get(url, params=parameters)
        data = response.json()

        if response.status_code != 200:
            return {"error": data.get("status", {}).get("error_message", "Unknown error")}, 500

        crypto_data = [
            {
                "Name": coin["name"],
                "Symbol": coin["symbol"],
                "Price (USD)": coin["quote"]["USD"]["price"],
                "24h Trading Volume (USD)": coin["quote"]["USD"]["volume_24h"],
                "Market Cap (USD)": coin["quote"]["USD"]["market_cap"],
                "24h % Change": coin["quote"]["USD"]["percent_change_24h"],
            }
            for coin in data["data"]
        ]
        return sorted(crypto_data, key=lambda x: x["Price (USD)"], reverse=True)
    except (ConnectionError, Timeout, TooManyRedirects) as e:
        return {"error": str(e)}, 500

def authenticate_google_drive(service_account_json):
    """Authenticate the service account and create the Google Drive service client."""
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file(service_account_json, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def upload_or_update_file(file_path, drive_service, parent_folder):
    """Upload a new file to Google Drive or update if it exists."""
    file_name = os.path.basename(file_path)
    query = f"'{parent_folder}' in parents and name = '{file_name}'"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    media = MediaFileUpload(file_path, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if files:
        file_id = files[0]['id']
        drive_service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {'name': file_name, 'parents': [parent_folder]}
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()

@app.route("/", methods=["GET"])
def fetch_and_upload():
    crypto_data_sorted = fetch_add_to_excel(api_key, limit=50)
    if isinstance(crypto_data_sorted, tuple):
        return jsonify(crypto_data_sorted[0]), crypto_data_sorted[1]

    df = pd.DataFrame(crypto_data_sorted)
    output_file = "crypto_data.xlsx"
    percentage_change_file = "percentage_change.xlsx"

    df.to_excel(output_file, index=False, engine="openpyxl")
    percentage_change_sorted = df.sort_values(by="24h % Change", ascending=False)
    percentage_change_sorted.to_excel(percentage_change_file, index=False, engine="openpyxl")

    # Authenticate Google Drive and upload files
    try:
        drive_service = authenticate_google_drive(service_account_json)
        upload_or_update_file(output_file, drive_service, parent_folder)
        upload_or_update_file(percentage_change_file, drive_service, parent_folder)
    except Exception as e:
        return jsonify({"error": f"Failed to upload to Google Drive: {str(e)}"}), 500

    return jsonify({"message": "Data fetched and uploaded successfully!"})

if __name__ == "__main__":
    app.run(debug=True)
