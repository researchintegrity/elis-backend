import pytest
import requests
import time
import os
from pathlib import Path

# Configuration
BASE_URL = os.getenv("API_URL", "http://localhost:8000")
USERNAME = "test_trufor_user"
PASSWORD = "TestPassword123"
TEST_IMAGE_PATH = "test_trufor_image.jpg"

@pytest.fixture(scope="module")
def auth_token():
    """Register and login a test user, return access token"""
    # 1. Register
    register_data = {
        "username": USERNAME,
        "email": f"{USERNAME}@example.com",
        "password": PASSWORD,
        "full_name": "TruFor Test User"
    }
    try:
        requests.post(f"{BASE_URL}/auth/register", json=register_data)
        # Ignore error if user already exists
    except Exception:
        pass

    # 2. Login
    login_data = {
        "username": USERNAME,
        "password": PASSWORD
    }
    response = requests.post(f"{BASE_URL}/auth/login", data=login_data)
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]

@pytest.fixture(scope="module")
def test_image_file():
    """Create a dummy image file for testing"""
    if not os.path.exists(TEST_IMAGE_PATH):
        from PIL import Image, ImageDraw
        # Create a slightly larger image to ensure it works fine
        img = Image.new('RGB', (256, 256), color = 'blue')
        d = ImageDraw.Draw(img)
        d.text((50,50), "TruFor Test", fill=(255,255,255))
        img.save(TEST_IMAGE_PATH)
    
    yield TEST_IMAGE_PATH
    
    # Cleanup
    if os.path.exists(TEST_IMAGE_PATH):
        os.remove(TEST_IMAGE_PATH)

@pytest.fixture(scope="module")
def uploaded_image_id(auth_token, test_image_file):
    """Upload an image and return its ID"""
    headers = {"Authorization": f"Bearer {auth_token}"}
    with open(test_image_file, "rb") as f:
        files = {"file": (os.path.basename(test_image_file), f, "image/jpeg")}
        response = requests.post(
            f"{BASE_URL}/images/upload",
            headers=headers,
            files=files
        )
    assert response.status_code == 201, f"Upload failed: {response.text}"
    data = response.json()
    return data.get("id") or data.get("_id")

def poll_analysis(auth_token, analysis_id, timeout=600):
    """Helper to poll analysis status"""
    headers = {"Authorization": f"Bearer {auth_token}"}
    start_time = time.time()
    while time.time() - start_time < timeout:
        response = requests.get(f"{BASE_URL}/analyses/{analysis_id}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        status = data.get("status")
        
        if status == "completed":
            return data
        if status == "failed":
            pytest.fail(f"Analysis failed: {data.get('error')}")
            
        time.sleep(2)
    pytest.fail(f"Analysis timed out after {timeout} seconds")

def test_trufor_detection(auth_token, uploaded_image_id):
    """Test TruFor forgery detection"""
    headers = {"Authorization": f"Bearer {auth_token}"}
    payload = {"image_id": uploaded_image_id}
    
    # 1. Trigger Analysis
    response = requests.post(
        f"{BASE_URL}/analyses/trufor",
        json=payload,
        headers=headers
    )
    assert response.status_code == 202, f"Analysis trigger failed: {response.text}"
    data = response.json()
    analysis_id = data.get("analysis_id")
    assert analysis_id is not None
    
    print(f"Analysis started with ID: {analysis_id}")
    
    # 2. Poll for completion
    result = poll_analysis(auth_token, analysis_id)
    
    # 3. Verify results
    assert result["status"] == "completed"
    assert "results" in result
    results = result["results"]
    
    # Check for visualization output
    assert "visualization" in results
    assert results["visualization"] is not None
    assert results["visualization"].endswith(".png")
    assert "/trufor/" in results["visualization"]
    
    print(f"TruFor analysis completed successfully. Visualization: {results['visualization']}")
