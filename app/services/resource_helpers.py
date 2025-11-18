"""
Resource helper functions for common validation and resource retrieval patterns
Eliminates code duplication across routes for resource ownership validation
"""

from bson import ObjectId
from typing import Callable, Dict, Any, Optional
from fastapi import HTTPException, status


async def get_owned_resource(
    collection_getter: Callable,
    resource_id: str,
    user_id: str,
    resource_name: str = "Resource"
) -> Dict[str, Any]:
    """
    Retrieve a resource from a collection while verifying it belongs to the user.
    
    This is a single source of truth for resource ownership validation.
    Called by routes to eliminate duplicate ObjectId validation and ownership checks.
    
    Args:
        collection_getter: Function that returns the MongoDB collection (e.g., get_images_collection)
        resource_id: Resource ID to retrieve (as string)
        user_id: User ID (as string) who should own the resource
        resource_name: Human-readable name for error messages (e.g., "Image", "Document", "Annotation")
        
    Returns:
        Document dictionary from MongoDB
        
    Raises:
        HTTPException 400: If resource_id is not a valid ObjectId format
        HTTPException 404: If resource not found or doesn't belong to user
    """
    # Validate ObjectId format
    try:
        resource_oid = ObjectId(resource_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {resource_name.lower()} ID format"
        )
    
    # Retrieve resource with ownership check
    collection = collection_getter()
    resource = collection.find_one({
        "_id": resource_oid,
        "user_id": user_id
    })
    
    if not resource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource_name} not found or doesn't belong to you"
        )
    
    return resource


async def get_resource_by_id(
    collection_getter: Callable,
    resource_id: str,
    resource_name: str = "Resource"
) -> Dict[str, Any]:
    """
    Retrieve a resource by ID without ownership check (use cautiously).
    
    Useful for admin operations or when user_id isn't available.
    Prefer get_owned_resource for user-scoped operations.
    
    Args:
        collection_getter: Function that returns the MongoDB collection
        resource_id: Resource ID to retrieve (as string)
        resource_name: Human-readable name for error messages
        
    Returns:
        Document dictionary from MongoDB
        
    Raises:
        HTTPException 400: If resource_id is not a valid ObjectId format
        HTTPException 404: If resource not found
    """
    try:
        resource_oid = ObjectId(resource_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {resource_name.lower()} ID format"
        )
    
    collection = collection_getter()
    resource = collection.find_one({"_id": resource_oid})
    
    if not resource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource_name} not found"
        )
    
    return resource


def convert_objectid_to_string(resource: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert MongoDB ObjectId to string for JSON serialization.
    
    Args:
        resource: Dictionary potentially containing ObjectId
        
    Returns:
        Dictionary with ObjectId fields converted to strings
    """
    if isinstance(resource.get("_id"), ObjectId):
        resource["_id"] = str(resource["_id"])
    return resource
