"""
CBIR (Content-Based Image Retrieval) API Client

This module provides functions to interact with the CBIR microservice
for image similarity search and indexing.
"""
import logging
import requests
from typing import Tuple, Dict, List, Optional, Any
from app.config.settings import (
    is_container_path,
    get_container_path_length,
    WORKSPACE_ROOT,
    CBIR_SERVICE_URL,
    CBIR_TIMEOUT,
    CONTAINER_WORKSPACE_PATH,
)

logger = logging.getLogger(__name__)


def _convert_path_for_cbir(file_path: str) -> str:
    """
    Convert a file path to the format expected by the CBIR service.
    
    The CBIR service expects paths relative to its /workspace mount point.
    
    Args:
        file_path: The file path (can be container path or host path)
        
    Returns:
        Path that CBIR can access via its /workspace mount
    """
    # If it's a container path (/workspace/...), convert to /workspace/...
    if is_container_path(file_path):
        rel_path = file_path[get_container_path_length():]  # Remove /workspace
        return f"{CONTAINER_WORKSPACE_PATH}{rel_path}"
    
    # If it's a workspace path (workspace/...), convert to /workspace/...
    if file_path.startswith("workspace/"):
        rel_path = file_path[len("workspace"):]  # Remove 'workspace'
        return f"{CONTAINER_WORKSPACE_PATH}{rel_path}"
    
    # If it's an absolute workspace path, extract relative part
    if WORKSPACE_ROOT and file_path.startswith(WORKSPACE_ROOT):
        rel_path = file_path[len(WORKSPACE_ROOT):]
        return f"{CONTAINER_WORKSPACE_PATH}{rel_path}"
    
    # Assume it's already in the correct format
    return file_path


def _convert_cbir_path_to_response(cbir_path: str, user_id: str) -> str:
    """
    Convert a CBIR path back to the format used by our backend.
    
    Args:
        cbir_path: Path from CBIR (e.g., /workspace/user_id/images/...)
        user_id: User ID for validation
        
    Returns:
        Path in backend format (workspace/user_id/...)
    """
    if cbir_path.startswith("/workspace/"):
        return f"workspace{cbir_path[len('/workspace'):]}"
    return cbir_path


def check_cbir_health() -> Tuple[bool, str]:
    """
    Check if the CBIR service is healthy.
    
    Returns:
        Tuple (healthy, message)
    """
    try:
        response = requests.get(
            f"{CBIR_SERVICE_URL}/health",
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("model") and data.get("database"):
                return True, "CBIR service is healthy"
            return False, f"CBIR service partially initialized: {data}"
        return False, f"CBIR service returned status {response.status_code}"
    except requests.RequestException as e:
        return False, f"Failed to connect to CBIR service: {str(e)}"


def index_image(
    user_id: str,
    image_path: str,
    labels: Optional[List[str]] = None
) -> Tuple[bool, str, Dict]:
    """
    Index a single image in the CBIR system.
    
    Args:
        user_id: User ID for multi-tenancy isolation
        image_path: Path to the image file
        labels: Optional list of image class labels (e.g., ['Western Blot', 'Microscopy'])
        
    Returns:
        Tuple (success, message, result_data)
    """
    cbir_path = _convert_path_for_cbir(image_path)
    
    payload = {
        "user_id": user_id,
        "image_path": cbir_path,
        "labels": labels or []
    }
    
    logger.info(f"Indexing image for user {user_id}: {cbir_path}")
    
    try:
        response = requests.post(
            f"{CBIR_SERVICE_URL}/index",
            json=payload,
            timeout=CBIR_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            return True, "Image indexed successfully", data
        else:
            error_detail = response.json().get("detail", response.text)
            logger.error(f"CBIR index failed: {error_detail}")
            return False, f"Index failed: {error_detail}", {}
            
    except requests.RequestException as e:
        logger.error(f"CBIR service request failed: {e}")
        return False, f"CBIR service error: {str(e)}", {}


def index_images_batch(
    user_id: str,
    image_items: List[Dict[str, Any]]
) -> Tuple[bool, str, Dict]:
    """
    Index multiple images in batch.
    
    Args:
        user_id: User ID for multi-tenancy isolation
        image_items: List of dicts with 'image_path' and optional 'labels'
                    e.g., [{"image_path": "/path/to/img.jpg", "labels": ["Western Blot"]}]
        
    Returns:
        Tuple (success, message, result_data)
    """
    # Convert paths for CBIR
    items = []
    for item in image_items:
        cbir_path = _convert_path_for_cbir(item["image_path"])
        items.append({
            "image_path": cbir_path,
            "labels": item.get("labels", [])
        })
    
    payload = {
        "user_id": user_id,
        "items": items
    }
    
    logger.info(f"Batch indexing {len(items)} images for user {user_id}")
    
    try:
        response = requests.post(
            f"{CBIR_SERVICE_URL}/index/batch",
            json=payload,
            timeout=CBIR_TIMEOUT * 2  # Longer timeout for batch
        )
        
        if response.status_code == 200:
            data = response.json()
            return True, f"Indexed {data.get('indexed_count', 0)} images", data
        else:
            error_detail = response.json().get("detail", response.text)
            logger.error(f"CBIR batch index failed: {error_detail}")
            return False, f"Batch index failed: {error_detail}", {}
            
    except requests.RequestException as e:
        logger.error(f"CBIR service request failed: {e}")
        return False, f"CBIR service error: {str(e)}", {}


def search_similar_images(
    user_id: str,
    image_path: str,
    top_k: int = 10,
    labels: Optional[List[str]] = None
) -> Tuple[bool, str, List[Dict]]:
    """
    Search for similar images using a query image path.
    
    Args:
        user_id: User ID for multi-tenancy isolation
        image_path: Path to the query image
        top_k: Number of similar images to return
        labels: Optional list of labels to filter results
        
    Returns:
        Tuple (success, message, results)
        results is a list of dicts with id, distance, image_path, labels
    """
    cbir_path = _convert_path_for_cbir(image_path)
    
    payload = {
        "user_id": user_id,
        "image_path": cbir_path,
        "top_k": top_k,
        "labels": labels
    }
    
    logger.info(f"Searching similar images for user {user_id}, top_k={top_k}")
    
    try:
        response = requests.post(
            f"{CBIR_SERVICE_URL}/search",
            json=payload,
            timeout=CBIR_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            # Convert paths back to our format
            results = []
            for item in data.get("results", []):
                result = {
                    "id": item.get("id"),
                    "distance": item.get("distance"),
                    "image_path": _convert_cbir_path_to_response(item.get("image_path", ""), user_id),
                    "labels": item.get("labels", [])
                }
                results.append(result)
            return True, f"Found {len(results)} similar images", results
        else:
            error_detail = response.json().get("detail", response.text)
            logger.error(f"CBIR search failed: {error_detail}")
            return False, f"Search failed: {error_detail}", []
            
    except requests.RequestException as e:
        logger.error(f"CBIR service request failed: {e}")
        return False, f"CBIR service error: {str(e)}", []


def search_similar_images_upload(
    user_id: str,
    image_data: bytes,
    filename: str = "query.jpg",
    top_k: int = 10,
    labels: Optional[List[str]] = None
) -> Tuple[bool, str, List[Dict]]:
    """
    Search for similar images by uploading image data directly.
    
    Args:
        user_id: User ID for multi-tenancy isolation
        image_data: Raw image bytes
        filename: Filename for the upload
        top_k: Number of similar images to return
        labels: Optional list of labels to filter results
        
    Returns:
        Tuple (success, message, results)
    """
    # Build query params
    params = {
        "user_id": user_id,
        "top_k": top_k
    }
    if labels:
        params["labels"] = labels
    
    files = {
        "file": (filename, image_data)
    }
    
    logger.info(f"Searching similar images (upload) for user {user_id}, top_k={top_k}")
    
    try:
        response = requests.post(
            f"{CBIR_SERVICE_URL}/search/upload",
            params=params,
            files=files,
            timeout=CBIR_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            # Convert paths back to our format
            results = []
            for item in data.get("results", []):
                result = {
                    "id": item.get("id"),
                    "distance": item.get("distance"),
                    "image_path": _convert_cbir_path_to_response(item.get("image_path", ""), user_id),
                    "labels": item.get("labels", [])
                }
                results.append(result)
            return True, f"Found {len(results)} similar images", results
        else:
            error_detail = response.json().get("detail", response.text)
            logger.error(f"CBIR search upload failed: {error_detail}")
            return False, f"Search failed: {error_detail}", []
            
    except requests.RequestException as e:
        logger.error(f"CBIR service request failed: {e}")
        return False, f"CBIR service error: {str(e)}", []


def delete_image_from_index(
    user_id: str,
    image_path: str
) -> Tuple[bool, str]:
    """
    Delete an image from the CBIR index.
    
    Args:
        user_id: User ID for multi-tenancy isolation
        image_path: Path to the image to delete
        
    Returns:
        Tuple (success, message)
    """
    cbir_path = _convert_path_for_cbir(image_path)
    
    payload = {
        "user_id": user_id,
        "image_path": cbir_path
    }
    
    logger.info(f"Deleting image from CBIR index: {cbir_path}")
    
    try:
        response = requests.post(
            f"{CBIR_SERVICE_URL}/delete",
            json=payload,
            timeout=CBIR_TIMEOUT
        )
        
        if response.status_code == 200:
            return True, "Image deleted from index"
        else:
            error_detail = response.json().get("detail", response.text)
            return False, f"Delete failed: {error_detail}"
            
    except requests.RequestException as e:
        logger.error(f"CBIR service request failed: {e}")
        return False, f"CBIR service error: {str(e)}"


def delete_images_batch(
    user_id: str,
    image_paths: List[str]
) -> Tuple[bool, str, Dict]:
    """
    Delete multiple images from the CBIR index.
    
    Args:
        user_id: User ID for multi-tenancy isolation
        image_paths: List of image paths to delete
        
    Returns:
        Tuple (success, message, result_data)
    """
    cbir_paths = [_convert_path_for_cbir(p) for p in image_paths]
    
    payload = {
        "user_id": user_id,
        "image_paths": cbir_paths
    }
    
    logger.info(f"Batch deleting {len(cbir_paths)} images from CBIR index")
    
    try:
        response = requests.post(
            f"{CBIR_SERVICE_URL}/delete/batch",
            json=payload,
            timeout=CBIR_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            return True, f"Deleted {data.get('deleted_count', 0)} images", data
        else:
            error_detail = response.json().get("detail", response.text)
            return False, f"Batch delete failed: {error_detail}", {}
            
    except requests.RequestException as e:
        logger.error(f"CBIR service request failed: {e}")
        return False, f"CBIR service error: {str(e)}", {}


def delete_user_data(user_id: str) -> Tuple[bool, str]:
    """
    Delete all images for a user from the CBIR index.
    
    Args:
        user_id: User ID whose data to delete
        
    Returns:
        Tuple (success, message)
    """
    payload = {
        "user_id": user_id,
        "image_path": ""  # Not used for user deletion
    }
    
    logger.info(f"Deleting all CBIR data for user {user_id}")
    
    try:
        response = requests.post(
            f"{CBIR_SERVICE_URL}/delete/user",
            json=payload,
            timeout=CBIR_TIMEOUT
        )
        
        if response.status_code == 200:
            return True, f"Deleted all data for user {user_id}"
        else:
            error_detail = response.json().get("detail", response.text)
            return False, f"User data delete failed: {error_detail}"
            
    except requests.RequestException as e:
        logger.error(f"CBIR service request failed: {e}")
        return False, f"CBIR service error: {str(e)}"


def check_images_indexed(
    user_id: str,
    image_paths: List[str]
) -> Tuple[bool, str, Dict[str, bool]]:
    """
    Check which images are already indexed in the CBIR system.
    
    Args:
        user_id: User ID for multi-tenancy isolation
        image_paths: List of image paths to check
        
    Returns:
        Tuple (success, message, visibility_dict)
        visibility_dict maps image_path -> bool (True if indexed)
    """
    cbir_paths = [_convert_path_for_cbir(p) for p in image_paths]
    
    payload = {
        "user_id": user_id,
        "image_paths": cbir_paths
    }
    
    logger.info(f"Checking {len(cbir_paths)} images indexed status")
    
    try:
        response = requests.post(
            f"{CBIR_SERVICE_URL}/check_visibility",
            json=payload,
            timeout=CBIR_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            # Map back original paths
            visibility = {}
            cbir_to_original = dict(zip(cbir_paths, image_paths))
            for cbir_path, indexed in data.get("visibility", {}).items():
                original_path = cbir_to_original.get(cbir_path, cbir_path)
                visibility[original_path] = indexed
            return True, f"Checked {data.get('total_checked', 0)} images", visibility
        else:
            error_detail = response.json().get("detail", response.text)
            return False, f"Check visibility failed: {error_detail}", {}
            
    except requests.RequestException as e:
        logger.error(f"CBIR service request failed: {e}")
        return False, f"CBIR service error: {str(e)}", {}
