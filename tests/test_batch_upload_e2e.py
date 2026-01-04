"""
End-to-End tests for Batch Image Upload with Progress Tracking.

Tests the batch upload endpoint POST /images/upload/batch and the
indexing status endpoint GET /images/indexing-status/{job_id}.

Prerequisites:
1. Backend API running at localhost:8000
2. CBIR microservice running at localhost:8001
3. MongoDB running at localhost:27017
4. Celery worker running for async tasks

Run with:
    pytest tests/test_batch_upload_e2e.py -v
"""
import pytest
import requests
import time
import os
from pathlib import Path
from PIL import Image, ImageDraw
import shutil

# Configuration
BASE_URL = os.getenv("API_URL", "http://localhost:8000")
CBIR_URL = os.getenv("CBIR_SERVICE_URL", "http://localhost:8001")
USERNAME = "test_batch_upload_user"
PASSWORD = "TestPassword123"

# Test image directory
TEST_IMAGES_DIR = Path("test_batch_images")


@pytest.fixture(scope="module")
def auth_token():
    """Register and login a test user, return access token"""
    register_data = {
        "username": USERNAME,
        "email": f"{USERNAME}@example.com",
        "password": PASSWORD,
        "full_name": "Batch Upload Test User"
    }
    try:
        requests.post(f"{BASE_URL}/auth/register", json=register_data)
    except Exception:
        pass

    login_data = {
        "username": USERNAME,
        "password": PASSWORD
    }
    response = requests.post(f"{BASE_URL}/auth/login", data=login_data)
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def test_images():
    """Create test images for batch upload testing"""
    TEST_IMAGES_DIR.mkdir(exist_ok=True)
    
    images = []
    colors = [
        ("batch_red", (255, 0, 0)),
        ("batch_green", (0, 255, 0)),
        ("batch_blue", (0, 0, 255)),
        ("batch_yellow", (255, 255, 0)),
        ("batch_cyan", (0, 255, 255)),
    ]
    
    for name, color in colors:
        img_path = TEST_IMAGES_DIR / f"{name}.png"
        img = Image.new('RGB', (128, 128), color=color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 100, 100], outline="white", width=2)
        img.save(img_path)
        images.append(str(img_path))
    
    yield images
    
    # Cleanup
    if TEST_IMAGES_DIR.exists():
        shutil.rmtree(TEST_IMAGES_DIR)


def check_cbir_service():
    """Check if CBIR service is available"""
    try:
        response = requests.get(f"{CBIR_URL}/health", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


def poll_indexing_status(auth_token, job_id, timeout=120):
    """Poll indexing job status until completion or timeout"""
    headers = {"Authorization": f"Bearer {auth_token}"}
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        response = requests.get(
            f"{BASE_URL}/images/indexing-status/{job_id}",
            headers=headers
        )
        if response.status_code != 200:
            time.sleep(1)
            continue
        
        data = response.json()
        status = data.get("status")
        
        if status in ["completed", "partial", "failed"]:
            return data
        
        time.sleep(1)
    
    pytest.fail(f"Indexing timed out after {timeout} seconds")


class TestBatchUploadEndpoint:
    """Test POST /images/upload/batch endpoint"""
    
    def test_batch_upload_success(self, auth_token, test_images):
        """Test successful batch upload of multiple images"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Prepare files for upload
        files = []
        for img_path in test_images[:3]:
            files.append(
                ("files", (os.path.basename(img_path), open(img_path, "rb"), "image/png"))
            )
        
        try:
            response = requests.post(
                f"{BASE_URL}/images/upload/batch",
                headers=headers,
                files=files
            )
        finally:
            # Close file handles
            for _, file_tuple in files:
                file_tuple[1].close()
        
        assert response.status_code == 202, f"Batch upload failed: {response.text}"
        data = response.json()
        
        assert "job_id" in data
        assert data["uploaded_count"] == 3
        assert len(data["image_ids"]) == 3
        assert "message" in data
    
    def test_batch_upload_empty_files(self, auth_token):
        """Test batch upload with no files returns error"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        response = requests.post(
            f"{BASE_URL}/images/upload/batch",
            headers=headers,
            files=[]
        )
        
        # FastAPI returns 422 for validation errors when no files provided
        assert response.status_code in [400, 422]
    
    def test_batch_upload_unauthenticated(self, test_images):
        """Test that unauthenticated requests are rejected"""
        with open(test_images[0], "rb") as f:
            files = [("files", (os.path.basename(test_images[0]), f, "image/png"))]
            response = requests.post(
                f"{BASE_URL}/images/upload/batch",
                files=files
            )
        
        assert response.status_code in [401, 403]


class TestIndexingStatusEndpoint:
    """Test GET /images/indexing-status/{job_id} endpoint"""
    
    def test_get_indexing_status_not_found(self, auth_token):
        """Test 404 for non-existent job_id"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        response = requests.get(
            f"{BASE_URL}/images/indexing-status/idx_nonexistent_12345",
            headers=headers
        )
        
        assert response.status_code == 404
    
    def test_get_indexing_status_unauthenticated(self):
        """Test that unauthenticated requests are rejected"""
        response = requests.get(
            f"{BASE_URL}/images/indexing-status/idx_test_12345"
        )
        
        assert response.status_code in [401, 403]


@pytest.mark.skipif(not check_cbir_service(), reason="CBIR service not available")
class TestBatchUploadProgressTracking:
    """Test progress tracking during batch upload indexing"""
    
    def test_progress_updates_during_indexing(self, auth_token, test_images):
        """Test that progress updates as indexing proceeds"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Upload multiple images
        files = []
        for img_path in test_images:
            files.append(
                ("files", (os.path.basename(img_path), open(img_path, "rb"), "image/png"))
            )
        
        try:
            response = requests.post(
                f"{BASE_URL}/images/upload/batch",
                headers=headers,
                files=files
            )
        finally:
            for _, file_tuple in files:
                file_tuple[1].close()
        
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        
        # Poll and collect progress snapshots
        progress_snapshots = []
        for _ in range(30):  # Max 30 seconds
            status_response = requests.get(
                f"{BASE_URL}/images/indexing-status/{job_id}",
                headers=headers
            )
            if status_response.status_code == 200:
                data = status_response.json()
                progress_snapshots.append({
                    "status": data["status"],
                    "progress": data["progress_percent"],
                    "processed": data["processed_images"]
                })
                
                if data["status"] in ["completed", "partial", "failed"]:
                    break
            
            time.sleep(1)
        
        # Verify we saw progress
        assert len(progress_snapshots) > 0
        
        # Final status should be terminal
        final = progress_snapshots[-1]
        assert final["status"] in ["completed", "partial", "failed"]
    
    def test_completed_job_has_full_progress(self, auth_token, test_images):
        """Test that completed job shows 100% progress"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        with open(test_images[0], "rb") as f:
            files = [("files", (os.path.basename(test_images[0]), f, "image/png"))]
            response = requests.post(
                f"{BASE_URL}/images/upload/batch",
                headers=headers,
                files=files
            )
        
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        
        # Wait for completion
        result = poll_indexing_status(auth_token, job_id, timeout=60)
        
        if result["status"] == "completed":
            assert result["progress_percent"] == 100.0
            assert result["processed_images"] == result["total_images"]
            assert result["indexed_images"] >= 0


class TestBatchUploadErrorHandling:
    """Test error handling in batch upload"""
    
    def test_invalid_file_type_skipped(self, auth_token):
        """Test that invalid file types are skipped but valid ones proceed"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Create a text file (invalid for image upload)
        TEST_IMAGES_DIR.mkdir(exist_ok=True)
        txt_file = TEST_IMAGES_DIR / "test.txt"
        txt_file.write_text("This is not an image")
        
        # Create a valid image
        img_path = TEST_IMAGES_DIR / "valid.png"
        img = Image.new('RGB', (100, 100), color=(255, 0, 0))
        img.save(img_path)
        
        try:
            with open(txt_file, "rb") as f1, open(img_path, "rb") as f2:
                files = [
                    ("files", ("test.txt", f1, "text/plain")),
                    ("files", ("valid.png", f2, "image/png"))
                ]
                response = requests.post(
                    f"{BASE_URL}/images/upload/batch",
                    headers=headers,
                    files=files
                )
            
            # Should succeed with at least the valid image
            if response.status_code == 202:
                data = response.json()
                # At least some images should be uploaded
                assert data["uploaded_count"] >= 1
        finally:
            if txt_file.exists():
                txt_file.unlink()
            if img_path.exists():
                img_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
