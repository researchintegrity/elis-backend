"""
Image upload routes for extracted and user-uploaded image management
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query
from fastapi.responses import FileResponse
from typing import List
from bson import ObjectId
from datetime import datetime
from pathlib import Path

from app.schemas import ImageResponse
from app.db.mongodb import get_images_collection, get_documents_collection
from app.utils.security import get_current_user
from app.utils.file_storage import (
    validate_image,
    save_image_file,
    delete_file,
    check_storage_quota,
    get_quota_status,
    update_user_storage_in_db
)
from app.config.storage_quota import DEFAULT_USER_STORAGE_QUOTA

router = APIRouter(prefix="/images", tags=["images"])


@router.post("/upload", response_model=ImageResponse, status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile = File(...),
    document_id: str = Query(None, description="Optional document ID if image is related to a document"),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload an image file (for user-uploaded images)
    
    - Validates image file
    - Checks storage quota before saving
    - Saves to disk in user's images/uploaded/ directory
    - Creates image record in MongoDB
    - Optionally links to a document
    
    Args:
        file: Image file to upload
        document_id: Optional document ID to link image to
        current_user: Current authenticated user
        
    Returns:
        ImageResponse with image info
        
    Raises:
        HTTP 413: If storage quota would be exceeded
    """
    try:
        # Read file content
        content = await file.read()
        file_size = len(content)
        
        # Validate image
        is_valid, error_msg = validate_image(file.filename, file_size)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        
        user_id_str = str(current_user["_id"])
        
        # Check storage quota BEFORE saving file
        user_quota = current_user.get("storage_limit_bytes", DEFAULT_USER_STORAGE_QUOTA)
        quota_ok, quota_error = check_storage_quota(user_id_str, file_size, user_quota)
        if not quota_ok:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=quota_error
            )
        
        # Save image file
        try:
            file_path, saved_size = save_image_file(
                user_id_str,
                content,
                file.filename,
                doc_id=None  # User-uploaded, not extracted
            )
        except IOError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file: {str(e)}"
            )
        
        # If document_id provided, verify it belongs to user
        if document_id:
            documents_col = get_documents_collection()
            try:
                doc = documents_col.find_one({
                    "_id": ObjectId(document_id),
                    "user_id": user_id_str
                })
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid document ID"
                )
            
            if not doc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found"
                )
        
        # Create image record in MongoDB
        images_col = get_images_collection()
        
        img_data = {
            "user_id": user_id_str,
            "filename": file.filename,
            "file_path": file_path,
            "file_size": saved_size,
            "source_type": "uploaded",
            "document_id": document_id,  # Can be None for user-uploaded
            "uploaded_date": datetime.utcnow()
        }
        
        result = images_col.insert_one(img_data)
        img_id = str(result.inserted_id)
        
        # Retrieve and return created image with quota info
        img_record = images_col.find_one({"_id": ObjectId(img_id)})
        img_record["_id"] = img_id
        
        # Add quota information to response
        quota_status = get_quota_status(user_id_str, user_quota)
        img_record["user_storage_used"] = quota_status["used_bytes"]
        img_record["user_storage_remaining"] = quota_status["remaining_bytes"]
        
        # Update user storage in database for easy access
        update_user_storage_in_db(user_id_str)
        
        return ImageResponse(**img_record)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.get("", response_model=List[ImageResponse])
async def list_images(
    current_user: dict = Depends(get_current_user),
    source_type: str = Query(None, description="Filter by 'extracted' or 'uploaded'"),
    document_id: str = Query(None, description="Filter by document ID"),
    limit: int = 50,
    offset: int = 0
):
    """
    List all images uploaded by current user
    
    Args:
        current_user: Current authenticated user
        source_type: Optional filter - 'extracted' or 'uploaded'
        document_id: Optional filter by document ID
        limit: Maximum number of images to return
        offset: Number of images to skip
        
    Returns:
        List of ImageResponse objects with storage quota info
    """
    images_col = get_images_collection()
    user_id_str = str(current_user["_id"])
    user_quota = current_user.get("storage_limit_bytes", DEFAULT_USER_STORAGE_QUOTA)
    
    # Get quota info
    quota_status = get_quota_status(user_id_str, user_quota)
    
    # Build query
    query = {"user_id": user_id_str}
    
    if source_type:
        if source_type not in ["extracted", "uploaded"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source_type must be 'extracted' or 'uploaded'"
            )
        query["source_type"] = source_type
    
    if document_id:
        query["document_id"] = document_id
    
    # Query images
    images = list(
        images_col.find(query)
        .sort("uploaded_date", -1)
        .skip(offset)
        .limit(limit)
    )
    
    # Convert to response models with quota info
    responses = []
    for img in images:
        img["_id"] = str(img["_id"])
        img["user_storage_used"] = quota_status["used_bytes"]
        img["user_storage_remaining"] = quota_status["remaining_bytes"]
        responses.append(ImageResponse(**img))
    
    return responses


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(
    image_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a specific image by ID
    
    Args:
        image_id: Image ID
        current_user: Current authenticated user
        
    Returns:
        ImageResponse with storage quota info
    """
    images_col = get_images_collection()
    user_id_str = str(current_user["_id"])
    user_quota = current_user.get("storage_limit_bytes", DEFAULT_USER_STORAGE_QUOTA)
    
    try:
        img = images_col.find_one({
            "_id": ObjectId(image_id),
            "user_id": user_id_str
        })
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image ID"
        )
    
    if not img:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    img["_id"] = image_id
    
    # Add quota information
    quota_status = get_quota_status(user_id_str, user_quota)
    img["user_storage_used"] = quota_status["used_bytes"]
    img["user_storage_remaining"] = quota_status["remaining_bytes"]
    
    return ImageResponse(**img)


@router.get("/{image_id}/download")
async def download_image(
    image_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Download an image file
    
    Args:
        image_id: Image ID
        current_user: Current authenticated user
        
    Returns:
        FileResponse with image file
    """
    images_col = get_images_collection()
    
    # Verify image belongs to user
    try:
        img = images_col.find_one({
            "_id": ObjectId(image_id),
            "user_id": str(current_user["_id"])
        })
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image ID"
        )
    
    if not img:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    # Check if file exists
    file_path = img["file_path"]
    if not Path(file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk"
        )
    
    # Determine media type from file extension
    file_ext = Path(file_path).suffix.lower()
    media_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp"
    }
    media_type = media_type_map.get(file_ext, "application/octet-stream")
    
    # Return file
    return FileResponse(
        path=file_path,
        filename=img["filename"],
        media_type=media_type
    )


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(
    image_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete an image file (user-uploaded only)
    
    Args:
        image_id: Image ID
        current_user: Current authenticated user
    """
    images_col = get_images_collection()
    
    # Get image
    try:
        img = images_col.find_one({
            "_id": ObjectId(image_id),
            "user_id": str(current_user["_id"])
        })
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image ID"
        )
    
    if not img:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    # Check if extracted - cannot delete extracted images directly
    if img.get("source_type") == "extracted":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete extracted images directly. Delete the document instead."
        )
    
    try:
        # Delete image file from disk
        delete_file(img["file_path"])
        
        # Delete image record from MongoDB
        images_col.delete_one({"_id": ObjectId(image_id)})
        
        # Update user storage in database
        update_user_storage_in_db(str(current_user["_id"]))
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete image: {str(e)}"
        )
