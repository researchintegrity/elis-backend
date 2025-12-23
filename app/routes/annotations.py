"""
Annotation routes for image annotations
"""
from fastapi import APIRouter, Depends, status, Query
from typing import List
from bson import ObjectId
from datetime import datetime

from app.schemas import AnnotationResponse, AnnotationCreate
from app.db.mongodb import get_annotations_collection, get_images_collection
from app.utils.security import get_current_user
from app.services.resource_helpers import get_owned_resource

router = APIRouter(prefix="/annotations", tags=["annotations"])


@router.post("", response_model=AnnotationResponse, status_code=status.HTTP_201_CREATED)
async def create_annotation(
    annotation_data: AnnotationCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new annotation for an image
    
    Args:
        annotation_data: Annotation data (image_id, text, coords)
        current_user: Current authenticated user
        
    Returns:
        AnnotationResponse with annotation info
        
    Raises:
        HTTP 404: If image not found
        HTTP 403: If image doesn't belong to user
    """
    user_id_str = str(current_user["_id"])
    
    # Verify image exists and belongs to user
    await get_owned_resource(
        get_images_collection,
        annotation_data.image_id,
        user_id_str,
        "Image"
    )
    
    # Create annotation document
    annotations_col = get_annotations_collection()
    annotation_doc = {
        "user_id": user_id_str,
        "image_id": annotation_data.image_id,
        "text": annotation_data.text,
        "coords": annotation_data.coords.dict(exclude_none=True),
        "type": annotation_data.type or "manipulation",
        "group_id": annotation_data.group_id,
        "shape_type": annotation_data.shape_type or "rectangle",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = annotations_col.insert_one(annotation_doc)
    annotation_doc["_id"] = str(result.inserted_id)
    
    return AnnotationResponse(**annotation_doc)


@router.get("", response_model=List[AnnotationResponse])
async def list_annotations(
    image_id: str = Query(..., description="Image ID to get annotations for"),
    current_user: dict = Depends(get_current_user),
    limit: int = 100,
    offset: int = 0
):
    """
    Get all annotations for a specific image
    
    Args:
        image_id: Image ID to get annotations for
        current_user: Current authenticated user
        limit: Maximum number of annotations to return
        offset: Number of annotations to skip
        
    Returns:
        List of AnnotationResponse objects
    """
    annotations_col = get_annotations_collection()
    user_id_str = str(current_user["_id"])
    
    # Get annotations for this image (and verify user ownership)
    annotations = list(
        annotations_col.find({
            "user_id": user_id_str,
            "image_id": image_id
        })
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    
    # Convert ObjectId to string
    responses = []
    for anno in annotations:
        anno["_id"] = str(anno["_id"])
        responses.append(AnnotationResponse(**anno))
    
    return responses


@router.get("/{annotation_id}", response_model=AnnotationResponse)
async def get_annotation(
    annotation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a specific annotation
    
    Args:
        annotation_id: Annotation ID
        current_user: Current authenticated user
        
    Returns:
        AnnotationResponse
        
    Raises:
        HTTP 404: If annotation not found
        HTTP 403: If annotation doesn't belong to user
    """
    user_id_str = str(current_user["_id"])
    
    annotation = await get_owned_resource(
        get_annotations_collection,
        annotation_id,
        user_id_str,
        "Annotation"
    )
    
    annotation["_id"] = str(annotation["_id"])
    return AnnotationResponse(**annotation)


@router.delete("/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_annotation(
    annotation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete an annotation
    
    Args:
        annotation_id: Annotation ID to delete
        current_user: Current authenticated user
        
    Raises:
        HTTP 404: If annotation not found
        HTTP 403: If annotation doesn't belong to user
    """
    user_id_str = str(current_user["_id"])
    
    # Verify annotation exists and belongs to user
    await get_owned_resource(
        get_annotations_collection,
        annotation_id,
        user_id_str,
        "Annotation"
    )
    
    annotations_col = get_annotations_collection()
    result = annotations_col.delete_one({
        "_id": ObjectId(annotation_id),
        "user_id": user_id_str
    })
