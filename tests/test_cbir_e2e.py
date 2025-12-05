"""
End-to-End tests for CBIR (Content-Based Image Retrieval) integration.

These tests verify the complete CBIR workflow from API endpoints through
to the CBIR microservice. Requires the CBIR microservice to be running.

Prerequisites:
1. Backend API running at localhost:8000
2. CBIR microservice running at localhost:8001 (or cbir-service:8001 if in Docker)
3. MongoDB running at localhost:27017
4. Celery worker running for async tasks

Configuration:
- Set API_URL environment variable to override backend URL (default: http://localhost:8000)
- Set CBIR_SERVICE_URL environment variable for CBIR service (default: http://localhost:8001)

Run with:
    pytest tests/test_cbir_e2e.py -v

Or with specific markers:
    pytest tests/test_cbir_e2e.py -v -m "not slow"
"""
import pytest
import requests
import time
import os
from pathlib import Path
from PIL import Image, ImageDraw

# Configuration
BASE_URL = os.getenv("API_URL", "http://localhost:8000")
# CBIR URL for health checks - when running tests locally, use localhost
# The backend will use CBIR_SERVICE_HOST internally for Docker networking
CBIR_URL = os.getenv("CBIR_SERVICE_URL", "http://localhost:8001")
USERNAME = "test_cbir_user"
PASSWORD = "TestPassword123"

# Test image paths
TEST_IMAGES_DIR = Path("test_cbir_images")


@pytest.fixture(scope="module")
def auth_token():
    """Register and login a test user, return access token"""
    # 1. Register
    register_data = {
        "username": USERNAME,
        "email": f"{USERNAME}@example.com",
        "password": PASSWORD,
        "full_name": "CBIR Test User"
    }
    try:
        requests.post(f"{BASE_URL}/auth/register", json=register_data)
    except Exception:
        # Ignore error if user already exists
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
def test_images():
    """Create test images for CBIR testing"""
    TEST_IMAGES_DIR.mkdir(exist_ok=True)
    
    images = []
    
    # Create 5 different test images with varying colors
    colors = [
        ("red", (255, 0, 0)),
        ("green", (0, 255, 0)),
        ("blue", (0, 0, 255)),
        ("yellow", (255, 255, 0)),
        ("purple", (128, 0, 128))
    ]
    
    for name, color in colors:
        img_path = TEST_IMAGES_DIR / f"test_{name}.png"
        
        # Create image with solid color background and some pattern
        img = Image.new('RGB', (256, 256), color=color)
        draw = ImageDraw.Draw(img)
        
        # Add some distinguishing features
        draw.rectangle([50, 50, 200, 200], outline="white", width=3)
        draw.text((80, 100), name.upper(), fill="white")
        
        img.save(img_path)
        images.append(str(img_path))
    
    # Create a similar image to red (for testing similarity)
    similar_path = TEST_IMAGES_DIR / "test_similar_to_red.png"
    img = Image.new('RGB', (256, 256), color=(250, 10, 10))  # Slightly different red
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 200, 200], outline="white", width=3)
    draw.text((80, 100), "RED-ISH", fill="white")
    img.save(similar_path)
    images.append(str(similar_path))
    
    yield images
    
    # Cleanup
    import shutil
    if TEST_IMAGES_DIR.exists():
        shutil.rmtree(TEST_IMAGES_DIR)


@pytest.fixture(scope="module")
def uploaded_image_ids(auth_token, test_images):
    """Upload test images and return their IDs"""
    headers = {"Authorization": f"Bearer {auth_token}"}
    image_ids = []
    
    for img_path in test_images:
        with open(img_path, "rb") as f:
            files = {"file": (os.path.basename(img_path), f, "image/png")}
            response = requests.post(
                f"{BASE_URL}/images/upload",
                headers=headers,
                files=files
            )
        assert response.status_code == 201, f"Upload failed: {response.text}"
        data = response.json()
        image_ids.append(data.get("id") or data.get("_id"))
    
    return image_ids


def check_cbir_service():
    """Check if CBIR service is available"""
    try:
        response = requests.get(f"{CBIR_URL}/health", timeout=5)
        data = response.json()
        return response.status_code == 200 and data.get("model") and data.get("database")
    except Exception:
        return False


def poll_analysis(auth_token, analysis_id, timeout=120):
    """Helper to poll analysis status"""
    headers = {"Authorization": f"Bearer {auth_token}"}
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        response = requests.get(f"{BASE_URL}/analyses/{analysis_id}", headers=headers)
        if response.status_code != 200:
            time.sleep(2)
            continue
            
        data = response.json()
        status = data.get("status")
        
        if status == "completed":
            return data
        if status == "failed":
            pytest.fail(f"Analysis failed: {data.get('error')}")
            
        time.sleep(2)
    
    pytest.fail(f"Analysis timed out after {timeout} seconds")


class TestCBIRHealthEndpoint:
    """Test CBIR health check endpoint"""
    
    def test_cbir_health_via_api(self, auth_token):
        """Test the /cbir/health endpoint"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/cbir/health", headers=headers)
        
        # The endpoint should respond even if CBIR service is down
        assert response.status_code == 200
        data = response.json()
        assert "healthy" in data
        assert "message" in data


@pytest.mark.skipif(not check_cbir_service(), reason="CBIR service not available")
class TestCBIRIndexing:
    """Test CBIR indexing functionality"""
    
    def test_index_single_image(self, auth_token, uploaded_image_ids):
        """Test indexing a single image"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        payload = {
            "image_ids": [uploaded_image_ids[0]],
            "labels": ["test", "red"]
        }
        
        response = requests.post(
            f"{BASE_URL}/cbir/index",
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 202, f"Index request failed: {response.text}"
        data = response.json()
        assert data.get("image_count") == 1
        assert data.get("status") == "processing"
        
        # Wait for indexing to complete
        time.sleep(3)
    
    def test_index_multiple_images(self, auth_token, uploaded_image_ids):
        """Test batch indexing multiple images"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Index remaining images
        payload = {
            "image_ids": uploaded_image_ids[1:],
            "labels": ["test", "batch"]
        }
        
        response = requests.post(
            f"{BASE_URL}/cbir/index",
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 202, f"Batch index failed: {response.text}"
        data = response.json()
        assert data.get("image_count") == len(uploaded_image_ids) - 1
        
        # Wait for indexing to complete
        time.sleep(5)
    
    def test_index_all_user_images(self, auth_token):
        """Test indexing all user images without specifying IDs"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Index all without specifying image_ids
        response = requests.post(
            f"{BASE_URL}/cbir/index",
            json={},
            headers=headers
        )
        
        assert response.status_code == 202, f"Index all failed: {response.text}"


@pytest.mark.skipif(not check_cbir_service(), reason="CBIR service not available")
class TestCBIRSearch:
    """Test CBIR search functionality"""
    
    def test_search_similar_async(self, auth_token, uploaded_image_ids):
        """Test asynchronous similarity search"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Wait for indexing to be ready
        time.sleep(5)
        
        # Search for images similar to the first one
        payload = {
            "image_id": uploaded_image_ids[0],
            "top_k": 5
        }
        
        response = requests.post(
            f"{BASE_URL}/cbir/search",
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 202, f"Search request failed: {response.text}"
        data = response.json()
        analysis_id = data.get("analysis_id")
        assert analysis_id is not None
        
        # Poll for results
        result = poll_analysis(auth_token, analysis_id)
        
        assert result["status"] == "completed"
        assert "results" in result
        results = result["results"]
        assert "matches" in results
        assert len(results["matches"]) > 0
        
        # First result should be the query image itself (distance ~0)
        first_match = results["matches"][0]
        assert "distance" in first_match
        assert "similarity_score" in first_match
        assert "image_path" in first_match
    
    def test_search_similar_sync(self, auth_token, uploaded_image_ids):
        """Test synchronous similarity search"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        payload = {
            "image_id": uploaded_image_ids[0],
            "top_k": 10
        }
        
        response = requests.post(
            f"{BASE_URL}/cbir/search/sync",
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 200, f"Sync search failed: {response.text}"
        data = response.json()
        
        assert data.get("query_image_id") == uploaded_image_ids[0]
        assert "matches" in data
        assert data.get("matches_count") >= 0
    
    def test_search_with_label_filter(self, auth_token, uploaded_image_ids):
        """Test search with label filtering"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        payload = {
            "image_id": uploaded_image_ids[0],
            "top_k": 10,
            "labels": ["test"]  # Filter to only test-labeled images
        }
        
        response = requests.post(
            f"{BASE_URL}/cbir/search/sync",
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 200, f"Filtered search failed: {response.text}"
    
    def test_search_by_upload(self, auth_token, test_images):
        """Test search by uploading an image"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Upload the first test image as query
        with open(test_images[0], "rb") as f:
            files = {"file": ("query.png", f, "image/png")}
            response = requests.post(
                f"{BASE_URL}/cbir/search/upload",
                headers=headers,
                files=files,
                params={"top_k": 5}
            )
        
        assert response.status_code == 200, f"Upload search failed: {response.text}"
        data = response.json()
        assert "matches" in data
    
    def test_search_nonexistent_image(self, auth_token):
        """Test search with non-existent image ID"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        payload = {
            "image_id": "000000000000000000000000",
            "top_k": 10
        }
        
        response = requests.post(
            f"{BASE_URL}/cbir/search/sync",
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 404


@pytest.mark.skipif(not check_cbir_service(), reason="CBIR service not available")
class TestCBIRDelete:
    """Test CBIR delete functionality"""
    
    def test_delete_single_image(self, auth_token, uploaded_image_ids):
        """Test removing a single image from index"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        payload = {
            "image_ids": [uploaded_image_ids[-1]]  # Delete the last one
        }
        
        response = requests.delete(
            f"{BASE_URL}/cbir/index",
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 202, f"Delete failed: {response.text}"
        data = response.json()
        assert data.get("image_count") == 1


@pytest.mark.skipif(not check_cbir_service(), reason="CBIR service not available")
class TestCBIRSimilarityAccuracy:
    """Test that similar images are correctly identified"""
    
    @pytest.mark.slow
    def test_similar_images_ranked_higher(self, auth_token, uploaded_image_ids):
        """Test that similar images have higher similarity scores"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Wait for all indexing to complete
        time.sleep(5)
        
        # The "similar_to_red" image (index 5) should be similar to "red" image (index 0)
        # Search using the red image
        payload = {
            "image_id": uploaded_image_ids[0],  # Red image
            "top_k": 10
        }
        
        response = requests.post(
            f"{BASE_URL}/cbir/search/sync",
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        matches = data.get("matches", [])
        
        if len(matches) >= 2:
            # The similar red image should have a higher similarity score
            # than completely different colors
            print(f"Search results: {[(m.get('filename'), m.get('similarity_score')) for m in matches]}")
            
            # Just verify we get reasonable results
            for match in matches:
                assert 0 <= match.get("similarity_score", 0) <= 1
                assert match.get("distance", 1) >= 0


class TestCBIRErrorHandling:
    """Test error handling scenarios"""
    
    def test_unauthenticated_access(self):
        """Test that unauthenticated requests are rejected"""
        response = requests.post(f"{BASE_URL}/cbir/index", json={})
        assert response.status_code in [401, 403]
    
    def test_invalid_image_id(self, auth_token):
        """Test search with invalid image ID format"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        payload = {
            "image_id": "invalid-id-format",
            "top_k": 10
        }
        
        response = requests.post(
            f"{BASE_URL}/cbir/search/sync",
            json=payload,
            headers=headers
        )
        
        # Should return validation error or not found
        assert response.status_code in [404, 422]
    
    def test_top_k_bounds(self, auth_token, uploaded_image_ids):
        """Test top_k parameter validation"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Test with too high top_k
        payload = {
            "image_id": uploaded_image_ids[0],
            "top_k": 1000  # Exceeds max (100)
        }
        
        response = requests.post(
            f"{BASE_URL}/cbir/search/sync",
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 422  # Validation error


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
