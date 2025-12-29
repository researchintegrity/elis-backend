"""
Annotation routes for image annotations
"""
from fastapi import APIRouter, Depends, status, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime

from app.schemas import AnnotationResponse, AnnotationCreate, AnnotationBatchCreate
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
        "link_id": annotation_data.link_id,
        "linked_image_id": annotation_data.linked_image_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = annotations_col.insert_one(annotation_doc)
    annotation_doc["_id"] = str(result.inserted_id)
    
    return AnnotationResponse(**annotation_doc)


@router.post("/batch", response_model=List[AnnotationResponse], status_code=status.HTTP_201_CREATED)
async def create_annotations_batch(
    batch_data: AnnotationBatchCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Create multiple annotations at once (for linked cross-image pairs)
    
    Args:
        batch_data: List of annotation data
        current_user: Current authenticated user
        
    Returns:
        List of AnnotationResponse with created annotations
    """
    user_id_str = str(current_user["_id"])
    annotations_col = get_annotations_collection()
    images_col = get_images_collection()
    
    # Collect unique image IDs to verify
    unique_image_ids = set()
    for ann_data in batch_data.annotations:
        unique_image_ids.add(ann_data.image_id)
        if ann_data.linked_image_id:
            unique_image_ids.add(ann_data.linked_image_id)
    
    # Verify all images exist and belong to user
    for img_id in unique_image_ids:
        try:
            img = images_col.find_one({
                "_id": ObjectId(img_id),
                "user_id": user_id_str
            })
            if not img:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Image {img_id} not found or not owned by user"
                )
        except Exception as e:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid image ID: {img_id}"
            )
    
    # Create all annotations
    created_annotations = []
    for ann_data in batch_data.annotations:
        annotation_doc = {
            "user_id": user_id_str,
            "image_id": ann_data.image_id,
            "text": ann_data.text,
            "coords": ann_data.coords.dict(exclude_none=True),
            "type": ann_data.type or "manipulation",
            "group_id": ann_data.group_id,
            "shape_type": ann_data.shape_type or "rectangle",
            "link_id": ann_data.link_id,
            "linked_image_id": ann_data.linked_image_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = annotations_col.insert_one(annotation_doc)
        annotation_doc["_id"] = str(result.inserted_id)
        created_annotations.append(AnnotationResponse(**annotation_doc))
    
    return created_annotations

@router.get("/linked-images/{image_id}", response_model=List[str])
async def get_linked_images(
    image_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get IDs of images linked to the specified image via annotations.
    Returns a distinct list of linked_image_id values.
    """
    annotations_col = get_annotations_collection()
    user_id_str = str(current_user["_id"])
    
    # access check: ensure image belongs to user (optional, but good practice)
    # For now, just ensuring annotations belong to user
    
    pipeline = [
        # Match annotations for this image that belong to user and have a link
        {
            "$match": {
                "image_id": image_id,
                "user_id": user_id_str,
                "linked_image_id": {"$ne": None}
            }
        },
        # Group by linked_image_id to get distinct values
        {
            "$group": {
                "_id": "$linked_image_id"
            }
        }
    ]
    
    cursor = annotations_col.aggregate(pipeline)
    linked_ids = [doc["_id"] for doc in cursor if doc["_id"]]
    
    # Also find reverse links? (Annotations on OTHER images linked TO this image)
    # Usually links are bidirectional in concept but stored on both sides/one side?
    # DualAnnotationContext saves bidirectional annotations (one on left, one on right).
    # So querying "image_id": image_id is sufficient if every link has a local annotation pointing out.
    # If the user only annotated ONE side, the link exists on that side.
    # To be safe and show ALL connections, we should query reverse too.
    
    pipeline_reverse = [
         {
            "$match": {
                "linked_image_id": image_id,
                "user_id": user_id_str
            }
        },
        {
            "$group": {
                "_id": "$image_id"
            }
        }
    ]
    cursor_reverse = annotations_col.aggregate(pipeline_reverse)
    reverse_ids = [doc["_id"] for doc in cursor_reverse if doc["_id"]]
    
    # Combine and de-duplicate
    all_ids = list(set(linked_ids + reverse_ids))
    return all_ids

@router.get("", response_model=List[AnnotationResponse])
async def list_annotations(
    image_id: Optional[str] = Query(None, description="Image ID to get annotations for"),
    link_id: Optional[str] = Query(None, description="Link ID to get cross-image annotation pairs"),
    current_user: dict = Depends(get_current_user),
    limit: int = 100,
    offset: int = 0
):
    """
    Get annotations filtered by image_id or link_id
    
    Args:
        image_id: Image ID to get annotations for
        link_id: Link ID to get cross-image annotation pairs
        current_user: Current authenticated user
        limit: Maximum number of annotations to return
        offset: Number of annotations to skip
        
    Returns:
        List of AnnotationResponse objects
    """
    annotations_col = get_annotations_collection()
    user_id_str = str(current_user["_id"])
    
    # Build query
    query = {"user_id": user_id_str}
    if image_id:
        query["image_id"] = image_id
    if link_id:
        query["link_id"] = link_id
    
    # Get annotations
    annotations = list(
        annotations_col.find(query)
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
