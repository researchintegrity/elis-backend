#!/usr/bin/env python3
"""
E2E Panel Extraction Test Script

This script simulates an end-to-end panel extraction test using a real image file.
It performs the following steps:
1. Register/login a test user
2. Upload the specified image file
3. Initiate panel extraction
4. Poll for completion
5. Display results

Usage:
    python test_panel_extraction_real.py /path/to/image.jpg
"""

import requests
import json
import time
import sys
import os
from pathlib import Path

# Configuration
API_BASE_URL = "http://localhost:8000"
TEST_USERNAME = "panel_test_user_real"
TEST_PASSWORD = "TestPassword123"
TEST_EMAIL = "panel_test_real@example.com"

def register_user():
    """Register a test user"""
    print("🔐 Registering test user...")
    response = requests.post(
        f"{API_BASE_URL}/auth/register",
        json={
            "username": TEST_USERNAME,
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "full_name": "Panel Extraction Test User"
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

def upload_image(image_path, token):
    """Upload an image file"""
    print(f"📤 Uploading image: {image_path}")

    if not os.path.exists(image_path):
        print(f"❌ Image file not found: {image_path}")
        return None

    filename = os.path.basename(image_path)

    with open(image_path, 'rb') as f:
        files = {"file": (filename, f, "image/jpeg")}
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.post(
            f"{API_BASE_URL}/images/upload",
            files=files,
            headers=headers
        )

    if response.status_code == 201:
        image_data = response.json()
        print(f"📄 Upload response: {json.dumps(image_data, indent=2)}")
        image_id = image_data.get("id") or image_data.get("_id") or image_data.get("image", {}).get("_id")
        if not image_id:
            print(f"❌ Unexpected response format: {image_data}")
            return None
        print(f"✅ Image uploaded successfully, ID: {image_id}")
        return image_id
    else:
        print(f"❌ Failed to upload image: {response.status_code} - {response.text}")
        return None

def initiate_panel_extraction(image_id, token):
    """Initiate panel extraction"""
    print(f"🔍 Initiating panel extraction for image: {image_id}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        f"{API_BASE_URL}/images/extract-panels",
        json={"image_ids": [image_id]},
        headers=headers
    )

    if response.status_code == 202:
        data = response.json()
        task_id = data["task_id"]
        print(f"✅ Panel extraction initiated, task ID: {task_id}")
        return task_id
    else:
        print(f"❌ Failed to initiate panel extraction: {response.status_code} - {response.text}")
        return None

def poll_extraction_status(task_id, token):
    """Poll for extraction completion"""
    print(f"⏳ Polling extraction status for task: {task_id}")

    headers = {"Authorization": f"Bearer {token}"}
    max_attempts = 60  # 5 minutes max
    attempt = 0

    while attempt < max_attempts:
        response = requests.get(
            f"{API_BASE_URL}/images/extract-panels/status/{task_id}",
            headers=headers
        )

        if response.status_code == 200:
            status_data = response.json()
            status = status_data["status"]

            if status == "completed":
                print("✅ Panel extraction completed!")
                return status_data
            elif status == "failed":
                print(f"❌ Panel extraction failed: {status_data.get('error', 'Unknown error')}")
                return None
            elif status == "processing":
                print(f"🔄 Processing... ({status_data.get('progress', 'N/A')}%)")
            else:
                print(f"⏳ Status: {status}")

        else:
            print(f"❌ Failed to get status: {response.status_code} - {response.text}")
            return None

        time.sleep(5)  # Wait 5 seconds between polls
        attempt += 1

    print("⏰ Timeout: Panel extraction took too long")
    return None

def get_extracted_panels(image_id, token):
    """Get the extracted panels for the source image"""
    print(f"📋 Getting extracted panels for image: {image_id}")

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(
        f"{API_BASE_URL}/images/{image_id}/panels",
        headers=headers
    )

    if response.status_code == 200:
        panels_data = response.json()
        # Handle both dict and list responses
        if isinstance(panels_data, list):
            panels = panels_data
        else:
            panels = panels_data.get("panels", [])
        
        print(f"✅ Found {len(panels)} extracted panels")

        # Display panel details
        for i, panel in enumerate(panels, 1):
            print(f"  Panel {i}:")
            print(f"    ID: {panel.get('_id', 'N/A')}")
            print(f"    Type: {panel.get('panel_type', 'N/A')}")
            print(f"    BBox: {panel.get('bbox', 'N/A')}")
            print(f"    Confidence: {panel.get('confidence', 'N/A')}")
            print()

        return panels
    else:
        print(f"❌ Failed to get panels: {response.status_code} - {response.text}")
        return None

def main():
    if len(sys.argv) != 2:
        print("Usage: python test_panel_extraction_real.py <image_path>")
        print("Example: python test_panel_extraction_real.py /path/to/figure.jpg")
        sys.exit(1)

    image_path = sys.argv[1]

    print("🚀 Starting E2E Panel Extraction Test")
    print(f"📁 Image: {image_path}")
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

    # Step 2: Upload image
    image_id = upload_image(image_path, token)
    if not image_id:
        print("❌ Image upload failed")
        sys.exit(1)

    print("-" * 50)

    # Step 3: Initiate panel extraction
    task_id = initiate_panel_extraction(image_id, token)
    if not task_id:
        print("❌ Panel extraction initiation failed")
        sys.exit(1)

    print("-" * 50)

    # Step 4: Poll for completion
    status_result = poll_extraction_status(task_id, token)
    if not status_result:
        print("❌ Panel extraction monitoring failed")
        sys.exit(1)

    print("-" * 50)

    # Step 5: Get results
    panels = get_extracted_panels(image_id, token)
    if panels is not None:
        print("🎉 E2E Panel Extraction Test Completed Successfully!")
        print(f"📊 Summary: {len(panels)} panels extracted from {image_path}")
    else:
        print("❌ Failed to retrieve panel results")

if __name__ == "__main__":
    main()