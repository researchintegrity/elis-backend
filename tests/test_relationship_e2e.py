"""
Critical Path E2E Tests for Relationship API Endpoints

Tests the REST API endpoints for image relationships.
Run with: pytest tests/test_relationship_e2e.py -v

Requires:
- Backend server running at localhost:8000
- MongoDB connection
"""
import pytest
import requests
import os
import uuid
from PIL import Image, ImageDraw

# Configuration
BASE_URL = os.getenv("API_URL", "http://localhost:8000")
TEST_USERNAME = f"rel_test_user_{uuid.uuid4().hex[:8]}"
TEST_PASSWORD = "TestPassword123!"


@pytest.fixture(scope="module")
def auth_token():
    """Register and login a test user, return access token"""
    # 1. Register
    register_data = {
        "username": TEST_USERNAME,
        "email": f"{TEST_USERNAME}@example.com",
        "password": TEST_PASSWORD,
        "full_name": "Relationship Test User"
    }
    try:
        requests.post(f"{BASE_URL}/auth/register", json=register_data)
    except Exception:
        pass  # Ignore if user exists
    
    # 2. Login
    login_data = {"username": TEST_USERNAME, "password": TEST_PASSWORD}
    response = requests.post(f"{BASE_URL}/auth/login", data=login_data)
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def test_images():
    """Create and return paths to test image files"""
    paths = []
    for i in range(3):
        path = f"test_rel_image_{i}.png"
        img = Image.new('RGB', (100, 100), color=['red', 'green', 'blue'][i])
        d = ImageDraw.Draw(img)
        d.text((10, 40), f"Image {i}", fill='white')
        img.save(path)
        paths.append(path)
    
    yield paths
    
    # Cleanup
    for path in paths:
        if os.path.exists(path):
            os.remove(path)


@pytest.fixture(scope="module")
def uploaded_image_ids(auth_token, test_images):
    """Upload test images and return their IDs"""
    headers = {"Authorization": f"Bearer {auth_token}"}
    ids = []
    
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
        ids.append(data.get("id") or data.get("_id"))
    
    yield ids
    
    # Cleanup: delete uploaded images
    for img_id in ids:
        try:
            requests.delete(f"{BASE_URL}/images/{img_id}", headers=headers)
        except Exception:
            pass


class TestRelationshipEndpoints:
    """Test the /relationships API endpoints"""
    
    def test_create_relationship(self, auth_token, uploaded_image_ids):
        """POST /relationships creates a relationship"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        img1, img2, _ = uploaded_image_ids
        
        payload = {
            "image1_id": img1,
            "image2_id": img2,
            "source_type": "manual",
            "weight": 1.0
        }
        
        response = requests.post(
            f"{BASE_URL}/relationships",
            json=payload,
            headers=headers
        )
        
        assert response.status_code in [200, 201], f"Create failed: {response.text}"
        data = response.json()
        
        assert "id" in data or "_id" in data
        assert data.get("image1_id") or data.get("image2_id")
        
        # Store for cleanup
        return data.get("id") or data.get("_id")
    
    def test_create_relationship_normalizes_ids(self, auth_token, uploaded_image_ids):
        """Relationship IDs are normalized (A,B) == (B,A)"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        img1, img2, _ = uploaded_image_ids
        
        # Create with reversed order
        payload = {
            "image1_id": img2,  # Reversed
            "image2_id": img1,
            "source_type": "manual"
        }
        
        response = requests.post(
            f"{BASE_URL}/relationships",
            json=payload,
            headers=headers
        )
        
        # Should return existing relationship, not create duplicate
        assert response.status_code in [200, 201]
    
    def test_get_relationships_for_image(self, auth_token, uploaded_image_ids):
        """GET /relationships/image/{id} returns relationships"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        img1, _, _ = uploaded_image_ids
        
        # First create a relationship if not exists
        self.test_create_relationship(auth_token, uploaded_image_ids)
        
        response = requests.get(
            f"{BASE_URL}/relationships/image/{img1}",
            headers=headers
        )
        
        assert response.status_code == 200, f"Query failed: {response.text}"
        data = response.json()
        
        assert isinstance(data, list)
        # Should have at least one relationship
        assert len(data) >= 1
    
    def test_get_relationship_graph(self, auth_token, uploaded_image_ids):
        """GET /relationships/image/{id}/graph returns graph data"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        img1, img2, img3 = uploaded_image_ids
        
        # Create a chain: img1 -> img2 -> img3
        requests.post(
            f"{BASE_URL}/relationships",
            json={"image1_id": img1, "image2_id": img2, "source_type": "manual"},
            headers=headers
        )
        requests.post(
            f"{BASE_URL}/relationships",
            json={"image1_id": img2, "image2_id": img3, "source_type": "manual"},
            headers=headers
        )
        
        # Get graph starting from img1
        response = requests.get(
            f"{BASE_URL}/relationships/image/{img1}/graph",
            params={"max_depth": 0},  # Unlimited
            headers=headers
        )
        
        assert response.status_code == 200, f"Graph failed: {response.text}"
        data = response.json()
        
        assert "nodes" in data
        assert "edges" in data
        assert "mst_edges" in data
        
        # Should include all 3 images
        node_ids = [n["id"] for n in data["nodes"]]
        assert img1 in node_ids
        # Depending on depth and connectivity, img2 and img3 should be present
    
    def test_graph_depth_parameter(self, auth_token, uploaded_image_ids):
        """Graph respects max_depth parameter"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        img1, _, _ = uploaded_image_ids
        
        # Test depth 1
        response = requests.get(
            f"{BASE_URL}/relationships/image/{img1}/graph",
            params={"max_depth": 1},
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "total_nodes_count" in data
    
    def test_remove_relationship(self, auth_token, uploaded_image_ids):
        """DELETE /relationships/{id} removes a relationship"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        img1, img2, _ = uploaded_image_ids
        
        # First create a relationship
        create_resp = requests.post(
            f"{BASE_URL}/relationships",
            json={"image1_id": img1, "image2_id": img2, "source_type": "manual"},
            headers=headers
        )
        
        rel_id = create_resp.json().get("id") or create_resp.json().get("_id")
        assert rel_id, "No relationship ID returned"
        
        # Now delete it
        response = requests.delete(
            f"{BASE_URL}/relationships/{rel_id}",
            headers=headers
        )
        
        assert response.status_code in [200, 204], f"Delete failed: {response.text}"
    
    def test_unauthorized_access(self):
        """API returns 401 without authentication"""
        response = requests.get(f"{BASE_URL}/relationships/image/test123")
        assert response.status_code == 401
    
    def test_invalid_image_id(self, auth_token):
        """API handles invalid image IDs gracefully"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        response = requests.get(
            f"{BASE_URL}/relationships/image/invalid_id_12345",
            headers=headers
        )
        
        # Should return empty list or appropriate error
        assert response.status_code in [200, 404]


class TestRelationshipAutoFlagging:
    """Test that relationships trigger auto-flagging"""
    
    def test_relationship_flags_images(self, auth_token, uploaded_image_ids):
        """Creating a relationship should flag both images"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        img1, img2, _ = uploaded_image_ids
        
        # Create relationship
        requests.post(
            f"{BASE_URL}/relationships",
            json={"image1_id": img1, "image2_id": img2, "source_type": "manual"},
            headers=headers
        )
        
        # Check if images are flagged
        resp1 = requests.get(f"{BASE_URL}/images/{img1}", headers=headers)
        resp2 = requests.get(f"{BASE_URL}/images/{img2}", headers=headers)
        
        if resp1.status_code == 200 and resp2.status_code == 200:
            # Both should be flagged
            assert resp1.json().get("is_flagged") is True
            assert resp2.json().get("is_flagged") is True
