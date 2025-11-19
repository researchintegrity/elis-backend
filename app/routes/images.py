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
    check_storage_quota,
    update_user_storage_in_db
)
from app.config.storage_quota import DEFAULT_USER_STORAGE_QUOTA
from app.services.image_service import delete_image_and_artifacts, list_images as list_images_service
from app.services.resource_helpers import get_owned_resource
from app.services.quota_helpers import augment_with_quota
from app.schemas import (
    PanelExtractionRequest,
    PanelExtractionInitiationResponse,
    PanelExtractionStatusResponse
)
from app.services.panel_extraction_service import (
    initiate_panel_extraction,
    get_panel_extraction_status,
    get_panels_by_source_image
)

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
        img_record = augment_with_quota(img_record, user_id_str, user_quota)
        
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
    user_id_str = str(current_user["_id"])
    user_quota = current_user.get("storage_limit_bytes", DEFAULT_USER_STORAGE_QUOTA)
    
    try:
        # Use service to get images
        result = await list_images_service(
            user_id=user_id_str,
            source_type=source_type,
            document_id=document_id,
            limit=limit,
            offset=offset
        )
        
        # Map to response models with quota info
        responses = []
        for img in result["images"]:
            img = augment_with_quota(img, user_id_str, user_quota)
            responses.append(ImageResponse(**img))
        
        return responses
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


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
    user_id_str = str(current_user["_id"])
    user_quota = current_user.get("storage_limit_bytes", DEFAULT_USER_STORAGE_QUOTA)
    
    img = await get_owned_resource(
        get_images_collection,
        image_id,
        user_id_str,
        "Image"
    )
    
    img["_id"] = image_id
    
    # Add quota information
    img = augment_with_quota(img, user_id_str, user_quota)
    
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
    user_id_str = str(current_user["_id"])
    
    # Verify image belongs to user
    img = await get_owned_resource(
        get_images_collection,
        image_id,
        user_id_str,
        "Image"
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
    try:
        await delete_image_and_artifacts(
            image_id=image_id,
            user_id=str(current_user["_id"])
        )
    except ValueError as e:
        error_msg = str(e)
        if "Invalid image ID" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        elif "not found" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg
            )
        elif "Cannot delete" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_msg
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete image: {str(e)}"
        )


# ============================================================================
# Panel Extraction Endpoints
# ============================================================================

@router.post(
    "/extract-panels",
    response_model=PanelExtractionInitiationResponse,
    status_code=status.HTTP_202_ACCEPTED
)
async def initiate_panel_extraction_endpoint(
    request: PanelExtractionRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Initiate panel extraction from selected images
    
    Queues a Celery task to extract individual panels from the provided images.
    Returns a task_id for polling extraction status.
    
    - Validates all image IDs belong to current user
    - Validates images are extractable (extracted or uploaded type)
    - Queues Celery task for asynchronous processing
    - Returns task ID for status polling
    
    Args:
        request: Panel extraction request with image_ids
        current_user: Current authenticated user
        
    Returns:
        PanelExtractionInitiationResponse with task_id
        
    Raises:
        HTTP 400: If validation fails
        HTTP 404: If image not found
    """
    try:
        user_id = current_user.get("_id")
        
        # Validate request
        if not request.image_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one image ID is required"
            )
        
        # Initiate extraction
        result = initiate_panel_extraction(
            image_ids=request.image_ids,
            user_id=str(user_id)
        )
        
        return PanelExtractionInitiationResponse(
            task_id=result["task_id"],
            status=result["status"],
            image_ids=result["image_ids"],
            message=result["message"]
        )
        
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg or "does not belong" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate panel extraction: {str(e)}"
        )


@router.get(
    "/extract-panels/status/{task_id}",
    response_model=PanelExtractionStatusResponse,
    status_code=status.HTTP_200_OK
)
async def get_panel_extraction_status_endpoint(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get status of a panel extraction task
    
    Polls for the status of a queued or running panel extraction task.
    When completed, returns the list of extracted panels.
    
    - Returns current task status
    - Returns extracted panels when task completes
    - Returns error details if task fails
    
    Args:
        task_id: Celery task ID from extraction initiation
        current_user: Current authenticated user
        
    Returns:
        PanelExtractionStatusResponse with task status and panels (if completed)
    """
    try:
        user_id = current_user.get("_id")
        
        result = get_panel_extraction_status(
            task_id=task_id,
            user_id=str(user_id)
        )
        
        return PanelExtractionStatusResponse(
            task_id=result["task_id"],
            status=result["status"],
            image_ids=result.get("image_ids", []),
            extracted_panels_count=result.get("extracted_panels_count", 0),
            extracted_panels=result.get("extracted_panels"),
            message=result.get("message"),
            error=result.get("error")
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get extraction status: {str(e)}"
        )


@router.get(
    "/{image_id}/panels",
    response_model=List[ImageResponse],
    status_code=status.HTTP_200_OK
)
async def get_panels_from_image(
    image_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get all panels extracted from a specific source image
    
    Returns a list of all panel images that were extracted from the
    specified source image, including their metadata and bounding boxes.
    
    Args:
        image_id: MongoDB ID of the source image
        current_user: Current authenticated user
        
    Returns:
        List of ImageResponse objects for all panels from this source image
        
    Raises:
        HTTP 404: If source image not found
    """
    try:
        user_id = str(current_user.get("_id"))
        
        # Verify source image exists and belongs to user
        images_col = get_images_collection()
        source_image = images_col.find_one(
            {"_id": ObjectId(image_id), "user_id": user_id}
        )
        
        if not source_image:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source image not found: {image_id}"
            )
        
        # Get all panels from this source image
        panels = get_panels_by_source_image(
            source_image_id=image_id,
            user_id=user_id
        )
        
        # Convert to response format
        response_panels = []
        for panel_doc in panels:
            response_panels.append(ImageResponse(
                _id=str(panel_doc.get("_id")),
                user_id=panel_doc.get("user_id"),
                filename=panel_doc.get("filename"),
                file_path=panel_doc.get("file_path"),
                file_size=panel_doc.get("file_size"),
                source_type=panel_doc.get("source_type"),
                document_id=panel_doc.get("document_id"),
                source_image_id=panel_doc.get("source_image_id"),
                panel_id=panel_doc.get("panel_id"),
                panel_type=panel_doc.get("panel_type"),
                bbox=panel_doc.get("bbox"),
                uploaded_date=panel_doc.get("uploaded_date")
            ))
        
        return response_panels
        
    except Exception as e:
        # Check if it's an invalid ObjectId
        if "invalid ObjectId" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid image ID: {image_id}"
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve panels: {str(e)}"
        )
