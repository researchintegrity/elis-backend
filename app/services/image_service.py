"""
Image service for handling image operations
Provides business logic for image CRUD operations including cascade deletion and listing
"""

from typing import List, Dict, Any, Optional
from bson import ObjectId
from app.db.mongodb import (
    get_images_collection,
    get_annotations_collection
)
from app.utils.file_storage import (
    delete_file,
    update_user_storage_in_db
)
from app.tasks.cbir import cbir_delete_image
import logging

logger = logging.getLogger(__name__)


async def delete_image_and_artifacts(
    image_id: str,
    user_id: str
) -> dict:
    """
    Delete an image and all its associated artifacts (file and annotations)
    
    This is the single source of truth for image deletion logic.
    Called by both REST endpoints and can be imported by other services.
    
    Args:
        image_id: Image ID to delete
        user_id: User ID (as string) who owns the image
        
    Returns:
        Dictionary with deletion results
        
    Raises:
        ValueError: If image not found, invalid ID, or image type restriction
        Exception: If deletion fails
    """
    images_col = get_images_collection()
    
    # Verify image belongs to user
    try:
        img_oid = ObjectId(image_id)
    except Exception:
        raise ValueError("Invalid image ID format")
    
    img = images_col.find_one({
        "_id": img_oid,
        "user_id": user_id
    })
    
    if not img:
        raise ValueError("Image not found")
    
    # Check if extracted - cannot delete extracted images directly
    if img.get("source_type") == "extracted":
        raise ValueError("Cannot delete extracted images directly. Delete the document instead.")
    
    # Delete from CBIR index if it was indexed
    if img.get("cbir_indexed"):
        try:
            cbir_delete_image.delay(
                user_id=user_id,
                image_id=image_id,
                image_path=img["file_path"]
            )
            logger.info(f"Queued CBIR deletion for image {image_id}")
        except Exception as e:
            logger.warning(f"Failed to queue CBIR deletion for image {image_id}: {e}")
            # Continue with deletion even if CBIR deletion fails to queue
    
    # Delete image file from disk
    success, error = delete_file(img["file_path"])
    if not success:
        raise Exception(f"Failed to delete image file: {error}")
    
    # Delete associated annotations
    annotations_col = get_annotations_collection()
    annotations_deleted = 0
    
    result = annotations_col.delete_many({
        "image_id": image_id,
        "user_id": user_id
    })
    annotations_deleted = result.deleted_count
    
    # Delete image record from MongoDB
    images_col.delete_one({"_id": img_oid})
    
    # Update user storage in database
    update_user_storage_in_db(user_id)
    
    return {
        "deleted_id": image_id,
        "annotations_deleted": annotations_deleted
    }


async def list_images(
    user_id: str,
    source_type: Optional[str] = None,
    document_id: Optional[str] = None,
    image_type: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "uploaded_date",
    sort_order: int = -1
) -> Dict[str, Any]:
    """
    List images for a user with optional filtering and pagination.
    
    This is the single source of truth for image listing logic.
    Called by route handlers which map results to appropriate API response models.
    
    Args:
        user_id: User ID (as string) who owns the images
        source_type: Optional filter - "extracted" or "uploaded"
        document_id: Optional filter by document ID
        image_type: Optional list of image types/tags to filter by (matches any)
        date_from: Optional ISO date string to filter images uploaded on or after
        date_to: Optional ISO date string to filter images uploaded on or before
        search: Optional search string for filename (case-insensitive)
        limit: Maximum number of images to return
        offset: Number of images to skip
        sort_by: Field to sort by (default: "uploaded_date")
        sort_order: Sort order - 1 for ascending, -1 for descending (default: -1)
        
    Returns:
        Dictionary with keys:
        - images: List of image documents from MongoDB
        - total: Total count of images matching the query
        - returned: Number of images returned in this query
        
    Raises:
        ValueError: If source_type is invalid
    """
    from datetime import datetime
    
    images_col = get_images_collection()
    
    # Validate source_type if provided
    if source_type and source_type not in ["extracted", "uploaded", "panel"]:
        raise ValueError("source_type must be 'extracted', 'uploaded', or 'panel'")
    
    # Build query
    query = {"user_id": user_id}
    
    if source_type:
        query["source_type"] = source_type
    
    if document_id:
        query["document_id"] = document_id
    
    # Image type filter - match any of the provided types
    if image_type:
        query["image_type"] = {"$in": image_type}
    
    # Date range filter
    if date_from or date_to:
        date_query = {}
        if date_from:
            try:
                parsed_from = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                date_query["$gte"] = parsed_from
            except ValueError:
                pass  # Invalid date format, skip this filter
        if date_to:
            try:
                parsed_to = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                # Set to end of day
                parsed_to = parsed_to.replace(hour=23, minute=59, second=59, microsecond=999999)
                date_query["$lte"] = parsed_to
            except ValueError:
                pass  # Invalid date format, skip this filter
        if date_query:
            query["uploaded_date"] = date_query
    
    # Search filter - case-insensitive regex on filename
    if search:
        query["filename"] = {"$regex": search, "$options": "i"}
    
    # Get total count before pagination
    total_count = images_col.count_documents(query)
    
    # Query images with pagination
    images = list(
        images_col.find(query)
        .sort(sort_by, sort_order)
        .skip(offset)
        .limit(limit)
    )
    
    # Convert ObjectId to string for each image
    for img in images:
        img["_id"] = str(img["_id"])
    
    return {
        "images": images,
        "total": total_count,
        "returned": len(images)
    }
