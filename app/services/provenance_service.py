"""
Provenance Service Module

Provides high-level operations for Provenance Analysis,
bridging the database and the microservice.
"""
import logging
from typing import List, Dict, Optional, Any, Tuple
from bson import ObjectId

from app.db.mongodb import get_images_collection
from app.utils.docker_provenance import analyze_provenance

logger = logging.getLogger(__name__)


def get_user_images_for_provenance(
    user_id: str,
    image_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Get images from the database formatted for provenance analysis.
    
    Args:
        user_id: User ID to filter images
        image_ids: Optional list of specific image IDs to include
        
    Returns:
        List of dicts with id, path, label
    """
    images_col = get_images_collection()
    
    query = {"user_id": user_id}
    if image_ids:
        query["_id"] = {"$in": [ObjectId(id) for id in image_ids]}
    
    # Fetch images
    images = list(images_col.find(query, {"file_path": 1, "filename": 1, "image_type": 1}))
    
    items = []
    for img in images:
        # Use filename or image_type as label
        label = img.get("filename", "")
        if img.get("image_type"):
            types = img["image_type"]
            if isinstance(types, list) and types:
                label = f"{label} ({', '.join(types)})"
            elif isinstance(types, str):
                label = f"{label} ({types})"
                
        items.append({
            "id": str(img["_id"]),
            "path": img["file_path"],
            "label": label
        })
    
    return items


def run_provenance_analysis(
    user_id: str,
    query_image_id: str,
    search_image_ids: Optional[List[str]] = None,
    k: int = 10,
    q: int = 5,
    max_depth: int = 3,
    descriptor_type: str = "cv_rsift"
) -> Tuple[bool, str, Dict]:
    """
    Run provenance analysis for a query image.
    
    Args:
        user_id: User ID
        query_image_id: ID of the query image
        search_image_ids: Optional list of image IDs to include in analysis
        k: Top-K candidates
        q: Top-Q expansion
        max_depth: Expansion depth
        descriptor_type: Descriptor type
        
    Returns:
        Tuple (success, message, result_data)
    """
    # 1. Get the query image
    images_col = get_images_collection()
    query_img_doc = images_col.find_one({
        "_id": ObjectId(query_image_id),
        "user_id": user_id
    })
    
    if not query_img_doc:
        return False, "Query image not found", {}
        
    query_image = {
        "id": str(query_img_doc["_id"]),
        "path": query_img_doc["file_path"],
        "label": query_img_doc.get("filename", "Query Image")
    }
    
    # 2. Get images for analysis (filtered if search_image_ids provided)
    # If search_image_ids is None or empty, all user images will be used
    images = get_user_images_for_provenance(user_id, image_ids=search_image_ids)
    
    # 3. Call microservice
    return analyze_provenance(
        user_id=user_id,
        images=images,
        query_image=query_image,
        k=k,
        q=q,
        max_depth=max_depth,
        descriptor_type=descriptor_type
    )
