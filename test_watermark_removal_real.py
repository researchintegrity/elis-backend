#!/usr/bin/env python3
"""
E2E Watermark Removal Test Script

This script simulates an end-to-end watermark removal test using a real PDF file.
It performs the following steps:
1. Register/login a test user
2. Upload the specified PDF file
3. Initiate watermark removal with specified aggressiveness mode
4. Poll for completion
5. Display results and download the cleaned PDF

Usage:
    python test_watermark_removal_real.py /path/to/document.pdf [aggressiveness_mode]
    aggressiveness_mode: 1, 2, or 3 (default: 2)
"""

import requests
import json
import time
import sys
import os
from pathlib import Path

# Configuration
API_BASE_URL = "http://localhost:8000"
TEST_USERNAME = "watermark_test_user_real"
TEST_PASSWORD = "TestPassword123"
TEST_EMAIL = "watermark_test_real@example.com"

def register_user():
    """Register a test user"""
    print("🔐 Registering test user...")
    response = requests.post(
        f"{API_BASE_URL}/auth/register",
        json={
            "username": TEST_USERNAME,
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "full_name": "Watermark Removal Test User"
        }
    )

    if response.status_code == 200:
        print("✅ User registered successfully")
        return response.json()["user"]["_id"]
    elif response.status_code == 400 and ("already exists" in response.text or "already registered" in response.text):
        print("ℹ️  User already exists, proceeding with login")
        return None
    else:
        print(f"❌ Failed to register user: {response.status_code} - {response.text}")
        return None

def login_user():
    """Login and get access token"""
    print("🔑 Logging in...")
    response = requests.post(
        f"{API_BASE_URL}/auth/login",
        data={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        }
    )

    if response.status_code == 200:
        token = response.json()["access_token"]
        user_id = response.json()["user"]["_id"]
        print("✅ Login successful")
        return token, user_id
    else:
        print(f"❌ Failed to login: {response.status_code} - {response.text}")
        return None, None

def upload_pdf(pdf_path, token):
    """Upload a PDF file"""
    print(f"📤 Uploading PDF: {pdf_path}")

    if not os.path.exists(pdf_path):
        print(f"❌ PDF file not found: {pdf_path}")
        return None

    filename = os.path.basename(pdf_path)

    with open(pdf_path, 'rb') as f:
        files = {"file": (filename, f, "application/pdf")}
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.post(
            f"{API_BASE_URL}/documents/upload",
            files=files,
            headers=headers
        )

    if response.status_code == 201:
        doc_data = response.json()
        print(f"📄 Upload response: {json.dumps(doc_data, indent=2)}")
        doc_id = doc_data.get("id") or doc_data.get("_id") or doc_data.get("document", {}).get("_id")
        if not doc_id:
            print(f"❌ Unexpected response format: {doc_data}")
            return None
        print(f"✅ PDF uploaded successfully, ID: {doc_id}")
        print(f"📄 Filename: {doc_data.get('filename', 'N/A')}")
        print(f"📏 Size: {doc_data.get('file_size', 0)} bytes")
        return doc_id
    else:
        print(f"❌ Failed to upload PDF: {response.status_code} - {response.text}")
        return None

def initiate_watermark_removal(doc_id, token, aggressiveness_mode=2):
    """Initiate watermark removal"""
    print(f"\n🔍 Initiating watermark removal for document: {doc_id}")
    print(f"🎯 Aggressiveness mode: {aggressiveness_mode}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        f"{API_BASE_URL}/documents/{doc_id}/remove-watermark",
        json={"aggressiveness_mode": aggressiveness_mode},
        headers=headers
    )

    if response.status_code == 202:
        data = response.json()
        task_id = data["task_id"]
        print(f"✅ Watermark removal initiated, task ID: {task_id}")
        return task_id
    else:
        print(f"❌ Failed to initiate watermark removal: {response.status_code} - {response.text}")
        return None

def poll_watermark_removal_status(doc_id, token):
    """Poll for watermark removal completion"""
    print(f"\n⏳ Polling watermark removal status for document: {doc_id}")

    headers = {"Authorization": f"Bearer {token}"}
    max_attempts = 60  # 5 minutes max
    attempt = 0

    while attempt < max_attempts:
        response = requests.get(
            f"{API_BASE_URL}/documents/{doc_id}/watermark-removal/status",
            headers=headers
        )

        if response.status_code == 200:
            status_data = response.json()
            status = status_data["status"]

            if status == "completed":
                print("✅ Watermark removal completed!")
                print(f"📄 Cleaned PDF: {status_data.get('output_filename', 'N/A')}")
                print(f"📏 Size: {status_data.get('output_size', 0)} bytes")
                print(f"🆔 Cleaned document ID: {status_data.get('cleaned_document_id', 'N/A')}")
                return status_data
            elif status == "failed":
                print(f"❌ Watermark removal failed: {status_data.get('error', 'Unknown error')}")
                return None
            elif status == "processing":
                print(f"🔄 Processing... ({status_data.get('progress', 'N/A')}%)")
            elif status == "queued":
                print("⏳ Queued for processing...")
            else:
                print(f"⏳ Status: {status}")

        else:
            print(f"❌ Failed to get status: {response.status_code} - {response.text}")
            return None

        time.sleep(5)  # Wait 5 seconds between polls
        attempt += 1

    print("⏰ Timeout: Watermark removal took too long")
    return None

def download_cleaned_pdf(cleaned_doc_id, token, output_path=None):
    """Download the cleaned PDF"""
    if not cleaned_doc_id:
        print("❌ No cleaned document ID provided")
        return None

    print(f"\n📥 Downloading cleaned PDF: {cleaned_doc_id}")

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(
        f"{API_BASE_URL}/documents/{cleaned_doc_id}/download",
        headers=headers
    )

    if response.status_code == 200:
        if not output_path:
            output_path = f"cleaned_{cleaned_doc_id}.pdf"

        with open(output_path, 'wb') as f:
            f.write(response.content)

        file_size = len(response.content)
        print(f"✅ Cleaned PDF downloaded successfully: {output_path} ({file_size} bytes)")
        return output_path
    else:
        print(f"❌ Failed to download cleaned PDF: {response.status_code} - {response.text}")
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_watermark_removal_real.py <pdf_path> [aggressiveness_mode]")
        print("Example: python test_watermark_removal_real.py /path/to/document.pdf 2")
        print("aggressiveness_mode: 1=explicit watermarks only, 2=text+graphics (default), 3=all graphics")
        sys.exit(1)

    pdf_path = sys.argv[1]
    aggressiveness_mode = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    if aggressiveness_mode not in [1, 2, 3]:
        print("❌ Invalid aggressiveness mode. Must be 1, 2, or 3")
        sys.exit(1)

    print("🚀 Starting E2E Watermark Removal Test")
    print(f"📁 PDF: {pdf_path}")
    print(f"🎯 Aggressiveness Mode: {aggressiveness_mode}")
    print(f"🌐 API: {API_BASE_URL}")
    print("-" * 50)

    # Step 1: Register/Login user
    user_id = register_user()
    if user_id is None:
        user_id = None  # Will get from login

    token, user_id = login_user()
    if not token:
        print("❌ Authentication failed")
        sys.exit(1)

    print(f"👤 User ID: {user_id}")
    print("-" * 50)

    # Step 2: Upload PDF
    doc_id = upload_pdf(pdf_path, token)
    if not doc_id:
        print("❌ PDF upload failed")
        sys.exit(1)

    print("-" * 50)

    # Step 3: Initiate watermark removal
    task_id = initiate_watermark_removal(doc_id, token, aggressiveness_mode)
    if not task_id:
        print("❌ Watermark removal initiation failed")
        sys.exit(1)

    print("-" * 50)

    # Step 4: Poll for completion
    status_result = poll_watermark_removal_status(doc_id, token)
    if not status_result:
        print("❌ Watermark removal monitoring failed")
        sys.exit(1)

    print("-" * 50)

    # Step 5: Download cleaned PDF
    cleaned_doc_id = status_result.get("cleaned_document_id")
    if cleaned_doc_id:
        download_path = download_cleaned_pdf(cleaned_doc_id, token)
        if download_path:
            print("\n" + "=" * 50)
            print("🎉 E2E Watermark Removal Test Completed Successfully!")
            print(f"📊 Summary:")
            print(f"  📁 Original PDF: {pdf_path}")
            print(f"  🧹 Aggressiveness Mode: {aggressiveness_mode}")
            print(f"  📄 Cleaned PDF: {download_path}")
            print(f"  📏 Original Size: {status_result.get('original_size', 'N/A')} bytes")
            print(f"  📏 Cleaned Size: {status_result.get('output_size', 'N/A')} bytes")
            print(f"  📈 Size Reduction: {(status_result.get('original_size', 0) - status_result.get('output_size', 0))} bytes")
        else:
            print("❌ Failed to download cleaned PDF")
    else:
        print("❌ No cleaned document ID in status response")

if __name__ == "__main__":
    main()