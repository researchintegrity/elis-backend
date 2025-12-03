"""
Unit tests for CBIR (Content-Based Image Retrieval) integration.

These tests verify the CBIR utility functions and service layer
without requiring the actual CBIR microservice to be running.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from app.utils.docker_cbir import (
    _convert_path_for_cbir,
    _convert_cbir_path_to_response,
    check_cbir_health,
    index_image,
    index_images_batch,
    search_similar_images,
    search_similar_images_upload,
    delete_image_from_index,
    delete_images_batch,
    delete_user_data,
    check_images_indexed,
)


class TestPathConversion:
    """Test path conversion utilities"""
    
    def test_convert_path_for_cbir(self):
        """Test converting container path (/workspace/...) to CBIR format"""
        # Test container path
        container_path = "/workspace/user123/images/test.jpg"
        result = _convert_path_for_cbir(container_path)
        assert result == "/workspace/user123/images/test.jpg"
    
    def test_convert_workspace_path_to_cbir(self):
        """Test converting workspace path (workspace/...) to CBIR format"""
        workspace_path = "workspace/user123/images/test.jpg"
        result = _convert_path_for_cbir(workspace_path)
        assert result == "/workspace/user123/images/test.jpg"
    
    def test_convert_cbir_path_to_response(self):
        """Test converting CBIR path back to backend format"""
        cbir_path = "/workspace/user123/images/test.jpg"
        result = _convert_cbir_path_to_response(cbir_path, "user123")
        assert result == "workspace/user123/images/test.jpg"
    
    def test_path_already_in_cbir_format(self):
        """Test path that's already in CBIR format passes through"""
        cbir_path = "/workspace/user123/images/test.jpg"
        result = _convert_path_for_cbir(cbir_path)
        # Should remain unchanged or be converted consistently
        assert "/workspace/" in result


class TestCBIRHealthCheck:
    """Test CBIR health check functionality"""
    
    @patch('app.utils.docker_cbir.requests.get')
    def test_health_check_success(self, mock_get):
        """Test successful health check"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy", "model": True, "database": True}
        mock_get.return_value = mock_response
        
        healthy, message = check_cbir_health()
        
        assert healthy is True
        assert "healthy" in message.lower()
    
    @patch('app.utils.docker_cbir.requests.get')
    def test_health_check_partial_init(self, mock_get):
        """Test health check when service is partially initialized"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy", "model": False, "database": True}
        mock_get.return_value = mock_response
        
        healthy, message = check_cbir_health()
        
        assert healthy is False
        assert "partially" in message.lower()
    
    @patch('app.utils.docker_cbir.requests.get')
    def test_health_check_connection_error(self, mock_get):
        """Test health check when service is unreachable"""
        import requests
        mock_get.side_effect = requests.RequestException("Connection refused")
        
        healthy, message = check_cbir_health()
        
        assert healthy is False
        assert "failed to connect" in message.lower()


class TestIndexImage:
    """Test single image indexing"""
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_index_image_success(self, mock_post):
        """Test successful image indexing"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "id": 12345}
        mock_post.return_value = mock_response
        
        success, message, data = index_image(
            user_id="user123",
            image_path="/workspace/user123/images/test.jpg",
            labels=["Western Blot"]
        )
        
        assert success is True
        assert data.get("id") == 12345
        
        # Verify the request was made with correct data
        call_args = mock_post.call_args
        request_json = call_args.kwargs.get('json') or call_args[1].get('json')
        assert request_json["user_id"] == "user123"
        assert "labels" in request_json
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_index_image_failure(self, mock_post):
        """Test image indexing failure"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Image not found"}
        mock_post.return_value = mock_response
        
        success, message, data = index_image(
            user_id="user123",
            image_path="/workspace/user123/images/missing.jpg"
        )
        
        assert success is False
        assert "not found" in message.lower()


class TestBatchIndexing:
    """Test batch image indexing"""
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_batch_index_success(self, mock_post):
        """Test successful batch indexing"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "indexed_count": 3,
            "ids": [1, 2, 3],
            "failed_count": 0
        }
        mock_post.return_value = mock_response
        
        items = [
            {"image_path": "/path/to/img1.jpg", "labels": ["Label1"]},
            {"image_path": "/path/to/img2.jpg", "labels": ["Label2"]},
            {"image_path": "/path/to/img3.jpg", "labels": []}
        ]
        
        success, message, data = index_images_batch("user123", items)
        
        assert success is True
        assert data.get("indexed_count") == 3


class TestSearchSimilarImages:
    """Test image similarity search"""
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_search_success(self, mock_post):
        """Test successful similarity search"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "id": 1,
                    "distance": 0.1,
                    "user_id": "user123",
                    "image_path": "/workspace/user123/images/similar1.jpg",
                    "labels": ["Western Blot"]
                },
                {
                    "id": 2,
                    "distance": 0.2,
                    "user_id": "user123",
                    "image_path": "/workspace/user123/images/similar2.jpg",
                    "labels": []
                }
            ]
        }
        mock_post.return_value = mock_response
        
        success, message, results = search_similar_images(
            user_id="user123",
            image_path="/workspace/user123/images/query.jpg",
            top_k=10
        )
        
        assert success is True
        assert len(results) == 2
        assert results[0]["distance"] == 0.1
        # Check path conversion
        assert results[0]["image_path"].startswith("workspace/")
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_search_with_labels_filter(self, mock_post):
        """Test search with label filtering"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_post.return_value = mock_response
        
        success, message, results = search_similar_images(
            user_id="user123",
            image_path="/workspace/user123/images/query.jpg",
            top_k=5,
            labels=["Western Blot", "Microscopy"]
        )
        
        assert success is True
        
        # Verify labels were passed
        call_args = mock_post.call_args
        request_json = call_args.kwargs.get('json') or call_args[1].get('json')
        assert request_json["labels"] == ["Western Blot", "Microscopy"]


class TestSearchByUpload:
    """Test image search by file upload"""
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_search_upload_success(self, mock_post):
        """Test successful search by upload"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "id": 1,
                    "distance": 0.15,
                    "user_id": "user123",
                    "image_path": "/workspace/user123/images/match.jpg",
                    "labels": []
                }
            ]
        }
        mock_post.return_value = mock_response
        
        # Simulate image data
        image_data = b"fake image bytes"
        
        success, message, results = search_similar_images_upload(
            user_id="user123",
            image_data=image_data,
            filename="query.jpg",
            top_k=10
        )
        
        assert success is True
        assert len(results) == 1


class TestDeleteOperations:
    """Test delete operations"""
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_delete_single_image(self, mock_post):
        """Test deleting a single image from index"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response
        
        success, message = delete_image_from_index(
            user_id="user123",
            image_path="/workspace/user123/images/to_delete.jpg"
        )
        
        assert success is True
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_delete_batch(self, mock_post):
        """Test deleting multiple images from index"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "deleted_count": 3}
        mock_post.return_value = mock_response
        
        paths = [
            "/workspace/user123/images/img1.jpg",
            "/workspace/user123/images/img2.jpg",
            "/workspace/user123/images/img3.jpg"
        ]
        
        success, message, data = delete_images_batch("user123", paths)
        
        assert success is True
        assert data.get("deleted_count") == 3
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_delete_user_data(self, mock_post):
        """Test deleting all user data from index"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "message": "Deleted all data"}
        mock_post.return_value = mock_response
        
        success, message = delete_user_data("user123")
        
        assert success is True


class TestCheckImagesIndexed:
    """Test checking if images are already indexed"""
    
    @patch('app.utils.docker_cbir.requests.post')
    def test_check_visibility(self, mock_post):
        """Test checking which images are indexed"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "visibility": {
                "/workspace/user123/images/img1.jpg": True,
                "/workspace/user123/images/img2.jpg": False,
                "/workspace/user123/images/img3.jpg": True
            },
            "total_checked": 3,
            "indexed_count": 2
        }
        mock_post.return_value = mock_response
        
        paths = [
            "/workspace/user123/images/img1.jpg",
            "/workspace/user123/images/img2.jpg",
            "/workspace/user123/images/img3.jpg"
        ]
        
        success, message, visibility = check_images_indexed("user123", paths)
        
        assert success is True
        # Check that we get results (paths may be converted)
        assert len(visibility) == 3
