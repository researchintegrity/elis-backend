"""
CBIR Service Module

Provides high-level operations for Content-Based Image Retrieval,
including indexing images from the database and searching.
"""
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from bson import ObjectId

from app.db.mongodb import get_images_collection
from app.utils.docker_cbir import (
    index_image,
    index_images_batch,
    search_similar_images,
    check_cbir_health,
)

logger = logging.getLogger(__name__)


def get_user_images_for_indexing(
    user_id: str,
    image_ids: Optional[List[str]] = None,
    labels: Optional[List[str]] = None
) -> List[Dict]:
    """
    Get images from the database that are ready for CBIR indexing.
    
    Args:
        user_id: User ID to filter images
        image_ids: Optional list of specific image IDs to index
        labels: Optional labels to apply to all images
        
    Returns:
        List of dicts with image_path and labels
    """
    images_col = get_images_collection()
    
    query = {"user_id": user_id}
    if image_ids:
        query["_id"] = {"$in": [ObjectId(id) for id in image_ids]}
    
    images = images_col.find(query, {"file_path": 1, "image_type": 1})
    
    items = []
    for img in images:
        # Use image_type from DB or provided labels
        img_labels = labels or img.get("image_type", [])
        items.append({
            "image_path": img["file_path"],
            "labels": img_labels if isinstance(img_labels, list) else [img_labels]
        })
    
    return items


def index_user_images(
    user_id: str,
    image_ids: Optional[List[str]] = None,
    labels: Optional[List[str]] = None
) -> Tuple[bool, str, Dict]:
    """
    Index user's images in the CBIR system.
    
    Args:
        user_id: User ID
        image_ids: Optional list of specific image IDs to index
        labels: Optional labels to apply to all images
        
    Returns:
        Tuple (success, message, result_data)
    """
    items = get_user_images_for_indexing(user_id, image_ids, labels)
    
    if not items:
        return False, "No images found to index", {}
    
    if len(items) == 1:
        # Single image indexing
        success, message, data = index_image(
            user_id=user_id,
            image_path=items[0]["image_path"],
            labels=items[0]["labels"]
        )
    else:
        # Batch indexing
        success, message, data = index_images_batch(user_id, items)
    
    return success, message, data


def search_similar_by_image_id(
    user_id: str,
    image_id: str,
    top_k: int = 10,
    labels: Optional[List[str]] = None
) -> Tuple[bool, str, List[Dict]]:
    """
    Search for similar images using an image ID from our database.
    
    Args:
        user_id: User ID for multi-tenancy
        image_id: MongoDB image ID to use as query
        top_k: Number of results to return
        labels: Optional filter by labels
        
    Returns:
        Tuple (success, message, results)
    """
    images_col = get_images_collection()
    
    # Get the query image
    image = images_col.find_one({
        "_id": ObjectId(image_id),
        "user_id": user_id
    })
    
    if not image:
        return False, "Image not found or access denied", []
    
    # Search using the image path
    return search_similar_images(
        user_id=user_id,
        image_path=image["file_path"],
        top_k=top_k,
        labels=labels
    )


def enrich_search_results(
    user_id: str,
    results: List[Dict]
) -> List[Dict]:
    """
    Enrich CBIR search results with full image data from our database.
    
    Args:
        user_id: User ID
        results: Raw CBIR search results
        
    Returns:
        Enriched results with image details
    """
    if not results:
        return []
    
    images_col = get_images_collection()
    
    # Get all image paths
    paths = [r["image_path"] for r in results]
    
    # Query images by path
    images = list(images_col.find({
        "user_id": user_id,
        "file_path": {"$in": paths}
    }))
    
    # Create lookup by path
    path_to_image = {img["file_path"]: img for img in images}
    
    enriched = []
    for result in results:
        path = result["image_path"]
        image = path_to_image.get(path)
        
        # Note: For Inner Product (IP) metric, distance IS the similarity score (higher = more similar)
        # For L2 metric, you would need: similarity = 1.0 / (1.0 + distance) or similar
        # Our CBIR uses IP metric with normalized embeddings, so distance is cosine similarity
        raw_distance = result.get("distance", 0)
        similarity = max(0.0, min(1.0, raw_distance))  # Clamp to [0, 1] range
        
        enriched_result = {
            "cbir_id": result.get("id"),
            "distance": raw_distance,
            "similarity_score": similarity,
            "cbir_labels": result.get("labels", []),
            "image_path": path,
        }
        
        if image:
            enriched_result.update({
                "image_id": str(image["_id"]),
                "filename": image.get("filename"),
                "file_size": image.get("file_size"),
                "source_type": image.get("source_type"),
                "document_id": image.get("document_id"),
                "image_type": image.get("image_type", []),
                "uploaded_date": image.get("uploaded_date"),
            })
        
        enriched.append(enriched_result)
    
    return enriched


def get_cbir_status() -> Dict:
    """
    Get CBIR service status and statistics.
    
    Returns:
        Dict with service status info
    """
    healthy, message = check_cbir_health()
    
    return {
        "service": "cbir",
        "healthy": healthy,
        "message": message,
        "timestamp": datetime.utcnow().isoformat()
    }
