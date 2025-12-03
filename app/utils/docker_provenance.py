"""
Provenance Analysis API Client

This module provides functions to interact with the Provenance Analysis microservice.
"""
import logging
import requests
from typing import Tuple, Dict, List, Optional, Any
from app.config.settings import (
    PROVENANCE_SERVICE_URL,
    PROVENANCE_TIMEOUT,
    is_container_path,
    get_container_path_length,
    WORKSPACE_ROOT,
)

logger = logging.getLogger(__name__)


def _convert_path_for_provenance(file_path: str) -> str:
    """
    Convert a file path to the format expected by the Provenance service.
    
    The Provenance service expects paths relative to its /workspace mount point.
    
    Args:
        file_path: The file path (can be container path or host path)
        
    Returns:
        Path that Provenance can access via its /workspace mount
    """
    # If it's a container path (/app/workspace/...), convert to /workspace/...
    if is_container_path(file_path):
        rel_path = file_path[get_container_path_length():]  # Remove /app/workspace
        return f"/workspace{rel_path}"
    
    # If it's a workspace path (workspace/...), convert to /workspace/...
    if file_path.startswith("workspace/"):
        rel_path = file_path[len("workspace"):]  # Remove 'workspace'
        return f"/workspace{rel_path}"
    
    # If it's an absolute workspace path, extract relative part
    if WORKSPACE_ROOT and file_path.startswith(WORKSPACE_ROOT):
        rel_path = file_path[len(WORKSPACE_ROOT):]
        return f"/workspace{rel_path}"
    
    # Assume it's already in the correct format
    return file_path


def check_provenance_health() -> Tuple[bool, str]:
    """
    Check if the Provenance service is healthy.
    
    Returns:
        Tuple (healthy, message)
    """
    try:
        response = requests.get(
            f"{PROVENANCE_SERVICE_URL}/health",
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return True, f"Provenance service is healthy (CBIR connected: {data.get('cbir_connected')})"
        return False, f"Provenance service returned status {response.status_code}"
    except requests.RequestException as e:
        return False, f"Failed to connect to Provenance service: {str(e)}"


def analyze_provenance(
    user_id: str,
    images: List[Dict[str, Any]],
    query_image: Dict[str, Any],
    k: int = 10,
    q: int = 5,
    max_depth: int = 3,
    descriptor_type: str = "cv_rsift",
    max_workers: int = 4
) -> Tuple[bool, str, Dict]:
    """
    Analyze provenance for a query image against a set of available images.
    
    Args:
        user_id: User ID for CBIR multi-tenant isolation
        images: List of available images (id, path, label)
        query_image: The query image (id, path, label)
        k: Number of top candidates from initial CBIR search
        q: Number of candidates for expansion
        max_depth: Maximum expansion depth
        descriptor_type: Keypoint descriptor type
        max_workers: Parallel workers for extraction
        
    Returns:
        Tuple (success, message, result_data)
    """
    # Convert paths
    processed_images = []
    for img in images:
        processed_images.append({
            "id": str(img["id"]),
            "path": _convert_path_for_provenance(img["path"]),
            "label": img.get("label", "")
        })
        
    processed_query = {
        "id": str(query_image["id"]),
        "path": _convert_path_for_provenance(query_image["path"]),
        "label": query_image.get("label", "")
    }
    
    payload = {
        "user_id": user_id,
        "images": processed_images,
        "query_image": processed_query,
        "k": k,
        "q": q,
        "max_depth": max_depth,
        "descriptor_type": descriptor_type,
        "max_workers": max_workers
    }
    
    logger.info(f"Starting provenance analysis for user {user_id}, query {query_image['id']}")
    
    try:
        response = requests.post(
            f"{PROVENANCE_SERVICE_URL}/analyze",
            json=payload,
            timeout=PROVENANCE_TIMEOUT
        )
        
        if response.status_code == 200:
            return True, "Analysis completed successfully", response.json()
        else:
            error_detail = response.json().get("detail", response.text)
            logger.error(f"Provenance analysis failed: {error_detail}")
            return False, f"Analysis failed: {error_detail}", {}
            
    except requests.RequestException as e:
        logger.error(f"Provenance service request failed: {e}")
        return False, f"Provenance service error: {str(e)}", {}
