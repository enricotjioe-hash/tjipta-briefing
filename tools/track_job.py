import os
import sys
import json
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import anthropic
from googleapiclient.discovery import build
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from tools.auth_google import get_google_credentials

def fetch_job_posting(url):
    print(f"Fetching job posting from: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        lines = [line for line in text.split('\n') if line.strip()]
        clean_text = '\n'.join(lines[:200])
        return clean_text
    except Exception as e:
        return f"Error fetching URL: {e}"

def analyse_job_with_claude(job_text, url):
    print("Analysing job with Claude...")
    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    prompt = f"""You are analysing a job posting for Enrico, a UBC Sauder student majoring in Global Supply Chain.

Enrico's profile:
- Indonesian, grew up in Singapore, now in Vancouver at UBC Sauder
- Major: Global Supply Chain Management
- Family business background: wood products (MDF, particleboard, OSB), paper, corrugated packaging - has real factory floor experience
- Looking for: supply chain, operations, or logistics internships
- Location preference: Vancouver first, Hong Kong second, Singapore third
- Languages: English (fluent), Mandarin + Fujian (intermediate), Indonesian (basic)
- Key strength: real hands-on operational experience most students lack

Job posting text:
{job_text}

Return ONLY a JSON object with these exact fields:
{{
    "company": "company name",
    "role_title": "exact job title",
    "location": "city, country",
    "salary": "salary or stipend if mentioned, otherwise Unknown",
    "deadline": "application deadline if mentioned, otherwise Unknown",
    "score": <number 1-10>,
    "score_reason": "2-3 sentences explaining the score and fit for Enrico specifically",
    "status": "To Apply"
}}

Scoring guide:
- 9-10: Perfect fit - supply chain/operations role in Vancouver/HK/SG, directly relevant
- 7-8: Strong fit - related field or good location match
- 5-6: Moderate fit - transferable experience but not ideal
- 3-4: Weak fit - different field but some relevance
- 1-2: Poor fit - irrelevant role or location

Return only the JSON, no other text."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()
    if response_text.startswith('```'):
        response_text = response_text.split('```')[1]
        if response_text.startswith('json'):
            response_text = response_text[4:]
        response_text = response_text.strip()
    job_data = json.loads(response_text)
    return job_data

def add_to_google_sheet(job_data, url):
    print("Adding to Google Sheet...")
    creds = get_google_credentials()
    service = build('sheets', 'v4', credentials=creds)
    sheet_id = os.getenv('GOOGLE_SHEET_ID')

    row = [
        datetime.now().strftime('%Y-%m-%d'),
        job_data.get('company', 'Unknown'),
        job_data.get('role_title', 'Unknown'),
        job_data.get('location', 'Unknown'),
        url,
        job_data.get('salary', 'Unknown'),
        job_data.get('deadline', 'Unknown'),
        job_data.get('score', 0),
        job_data.get('score_reason', ''),
        job_data.get('status', 'To Apply')
    ]

    body = {'values': [row]}
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range='Sheet1!A:J',
        valueInputOption='RAW',
        body=body
    ).execute()

    print(f"Added: {job_data.get('company')} - {job_data.get('role_title')}")
    return row

def track_job(url):
    print(f"\n=== Tracking Job ===")
    print(f"URL: {url}\n")

    job_text = fetch_job_posting(url)
    if job_text.startswith("Error"):
        print(job_text)
        return None

    job_data = analyse_job_with_claude(job_text, url)
    row = add_to_google_sheet(job_data, url)

    print(f"\n=== Job Tracked Successfully ===")
    print(f"Company:    {job_data.get('company')}")
    print(f"Role:       {job_data.get('role_title')}")
    print(f"Location:   {job_data.get('location')}")
    print(f"Score:      {job_data.get('score')}/10")
    print(f"Reason:     {job_data.get('score_reason')}")
    print(f"Status:     {job_data.get('status')}")
    print(f"\nAdded to your Google Sheet.")

    return job_data

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 tools/track_job.py <job_url>")
        sys.exit(1)
    url = sys.argv[1]
    track_job(url)
