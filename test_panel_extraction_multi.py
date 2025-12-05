#!/usr/bin/env python3
"""
E2E Panel Extraction Test Script

This script simulates an end-to-end panel extraction test using real image files.
It performs the following steps:
1. Register/login a test user
2. Upload multiple image files
3. Initiate panel extraction for all images in a single request
4. Poll for completion
5. Display results for each image

Usage:
    python test_panel_extraction_real.py /path/to/image1.jpg /path/to/image2.jpg ...
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

def upload_multiple_images(image_paths, token):
    """Upload multiple image files"""
    image_ids = []
    for i, image_path in enumerate(image_paths, 1):
        print(f"\n--- Uploading Image {i}/{len(image_paths)} ---")
        image_id = upload_image(image_path, token)
        if image_id:
            image_ids.append(image_id)
        else:
            print(f"❌ Failed to upload {image_path}, skipping...")

    return image_ids

def initiate_panel_extraction(image_ids, token):
    """Initiate panel extraction for multiple images"""
    print(f"\n🔍 Initiating panel extraction for {len(image_ids)} images: {image_ids}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        f"{API_BASE_URL}/images/extract-panels",
        json={"image_ids": image_ids},
        headers=headers
    )

    if response.status_code == 202:
        data = response.json()
        task_id = data["task_id"]
        print(f"✅ Panel extraction initiated, task ID: {task_id}")
        print(f"📋 Processing images: {data.get('image_ids', [])}")
        return task_id
    else:
        print(f"❌ Failed to initiate panel extraction: {response.status_code} - {response.text}")
        return None

def poll_extraction_status(task_id, token):
    """Poll for extraction completion"""
    print(f"\n⏳ Polling extraction status for task: {task_id}")

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
                progress = status_data.get('progress', 'N/A')
                print(f"🔄 Processing... ({progress}%)")
            else:
                print(f"⏳ Status: {status}")

        else:
            print(f"❌ Failed to get status: {response.status_code} - {response.text}")
            return None

        time.sleep(5)  # Wait 5 seconds between polls
        attempt += 1

    print("⏰ Timeout: Panel extraction took too long")
    return None

def get_extracted_panels_for_image(image_id, token):
    """Get the extracted panels for a specific source image"""
    print(f"\n📋 Getting extracted panels for image: {image_id}")

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

        return panels
    else:
        print(f"❌ Failed to get panels: {response.status_code} - {response.text}")
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_panel_extraction_real.py <image_path1> <image_path2> ...")
        print("Example: python test_panel_extraction_real.py /path/to/image1.jpg /path/to/image2.jpg")
        sys.exit(1)

    image_paths = sys.argv[1:]

    print("🚀 Starting E2E Panel Extraction Test")
    print(f"📁 Images: {', '.join(image_paths)}")
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

    # Step 2: Upload multiple images
    image_ids = upload_multiple_images(image_paths, token)
    if not image_ids:
        print("❌ No images were uploaded successfully")
        sys.exit(1)

    print(f"\n📊 Successfully uploaded {len(image_ids)}/{len(image_paths)} images")
    print(f"🆔 Image IDs: {image_ids}")
    print("-" * 50)

    # Step 3: Initiate panel extraction for all images
    task_id = initiate_panel_extraction(image_ids, token)
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

    # Step 5: Get results for each image
    total_panels = 0
    for i, image_id in enumerate(image_ids, 1):
        print(f"\n=== Results for Image {i}/{len(image_ids)} (ID: {image_id}) ===")
        panels = get_extracted_panels_for_image(image_id, token)
        if panels:
            total_panels += len(panels)
        else:
            print("❌ Failed to retrieve panel results for this image")

    print("\n" + "=" * 50)
    print("🎉 E2E Panel Extraction Test Completed Successfully!")
    print(f"📊 Summary: {total_panels} total panels extracted from {len(image_ids)} images")
    print(f"🖼️  Images processed: {len(image_ids)}")
    print(f"🔍 Average panels per image: {total_panels/len(image_ids):.1f}")

if __name__ == "__main__":
    main()