"""
Document upload routes for PDF file management
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from fastapi.responses import FileResponse
from typing import List
from bson import ObjectId
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

from app.schemas import DocumentResponse, ImageResponse
from app.db.mongodb import get_documents_collection, get_images_collection
from app.utils.security import get_current_user
from app.utils.file_storage import (
    validate_pdf,
    save_pdf_file,
    get_extraction_output_path,
    check_storage_quota,
    update_user_storage_in_db
)
from app.config.storage_quota import DEFAULT_USER_STORAGE_QUOTA
from app.tasks.image_extraction import extract_images_from_document
from celery.result import AsyncResult
from app.celery_config import celery_app
from app.services.document_service import delete_document_and_artifacts
from app.services.resource_helpers import get_owned_resource
from app.services.quota_helpers import augment_with_quota

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a PDF document
    
    - Validates PDF file
    - Checks storage quota before saving
    - Saves to disk organized by user
    - Creates document record in MongoDB
    - Sets up extraction folder
    - Triggers figure extraction placeholder
    
    Args:
        file: PDF file to upload
        current_user: Current authenticated user
        
    Returns:
        DocumentResponse with document info
        
    Raises:
        HTTP 413: If storage quota would be exceeded
    """
    try:
        # Read file content
        content = await file.read()
        file_size = len(content)
        
        # Validate PDF
        is_valid, error_msg = validate_pdf(file.filename, file_size)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        
        # Convert user_id to string
        user_id_str = str(current_user["_id"])
        
        # Check storage quota BEFORE saving file
        user_quota = current_user.get("storage_limit_bytes", DEFAULT_USER_STORAGE_QUOTA)
        quota_ok, quota_error = check_storage_quota(user_id_str, file_size, user_quota)
        if not quota_ok:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=quota_error
            )
        
        # Save PDF file
        try:
            file_path, saved_size = save_pdf_file(
                user_id_str,
                content,
                file.filename
            )
        except IOError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file: {str(e)}"
            )
        
        # Create document record in MongoDB
        documents_col = get_documents_collection()
        
        doc_data = {
            "user_id": user_id_str,
            "filename": file.filename,
            "file_path": file_path,
            "file_size": saved_size,
            "extraction_status": "pending",
            "extracted_image_count": 0,
            "extraction_errors": [],
            "uploaded_date": datetime.utcnow()
        }
        
        result = documents_col.insert_one(doc_data)
        doc_id = str(result.inserted_id)
        
        # Create extraction output directory
        get_extraction_output_path(user_id_str, doc_id)
        
        # Convert relative path to absolute path for worker container
        # file_path is like "workspace/user_id/pdfs/file.pdf"
        # In worker container, this should be "/app/workspace/user_id/pdfs/file.pdf"
        absolute_pdf_path = f"/app/{file_path}"
        
        # ✨ QUEUE IMAGE EXTRACTION TASK (asynchronous - returns immediately)
        task = extract_images_from_document.delay(
            doc_id=doc_id,
            user_id=user_id_str,
            pdf_path=absolute_pdf_path
        )
        
        # Store task_id in document for status checking
        documents_col.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {"task_id": task.id}}
        )
        
        # Retrieve and return updated document with quota info
        doc_record = documents_col.find_one({"_id": ObjectId(doc_id)})
        doc_record["_id"] = doc_id  # Ensure _id is set for response
        
        # Add quota information to response
        doc_record = augment_with_quota(doc_record, user_id_str, user_quota)
        
        # Update user storage in database for easy access
        update_user_storage_in_db(user_id_str)
        
        return DocumentResponse(**doc_record)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.get("", response_model=List[DocumentResponse])
async def list_documents(
    current_user: dict = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0
):
    """
    List all documents uploaded by current user
    
    Args:
        current_user: Current authenticated user
        limit: Maximum number of documents to return
        offset: Number of documents to skip
        
    Returns:
        List of DocumentResponse objects with storage quota info
    """
    documents_col = get_documents_collection()
    user_id_str = str(current_user["_id"])
    user_quota = current_user.get("storage_limit_bytes", DEFAULT_USER_STORAGE_QUOTA)
    
    # Query documents for user
    documents = list(
        documents_col.find(
            {"user_id": user_id_str}
        )
        .sort("uploaded_date", -1)
        .skip(offset)
        .limit(limit)
    )
    
    # Convert to response models with quota info
    responses = []
    for doc in documents:
        doc["_id"] = str(doc["_id"])
        doc = augment_with_quota(doc, user_id_str, user_quota)
        responses.append(DocumentResponse(**doc))
    
    return responses


@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a specific document by ID
    
    Args:
        doc_id: Document ID
        current_user: Current authenticated user
        
    Returns:
        DocumentResponse with storage quota info
    """
    user_id_str = str(current_user["_id"])
    user_quota = current_user.get("storage_limit_bytes", DEFAULT_USER_STORAGE_QUOTA)
    
    # Get document with ownership validation
    doc = await get_owned_resource(
        get_documents_collection,
        doc_id,
        user_id_str,
        "Document"
    )
    
    doc["_id"] = doc_id
    
    # Add quota information
    doc = augment_with_quota(doc, user_id_str, user_quota)
    
    # Return raw dict (convert ObjectId and datetime for JSON serialization)
    from datetime import datetime as dt
    result = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, dt):
            result[key] = value.isoformat()
        else:
            result[key] = value
    
    return result


@router.get("/{doc_id}/images", response_model=List[ImageResponse])
async def get_document_images(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0
):
    """
    Get all extracted images from a specific document
    
    Args:
        doc_id: Document ID
        current_user: Current authenticated user
        limit: Maximum number of images to return
        offset: Number of images to skip
        
    Returns:
        List of ImageResponse objects (extracted images only)
    """
    user_id_str = str(current_user["_id"])
    
    # Verify document belongs to user
    await get_owned_resource(
        get_documents_collection,
        doc_id,
        user_id_str,
        "Document"
    )
    
    # Get images for this document
    images_col = get_images_collection()
    images = list(
        images_col.find({
            "document_id": doc_id,
            "user_id": user_id_str,
            "source_type": "extracted"
        })
        .sort("uploaded_date", -1)
        .skip(offset)
        .limit(limit)
    )
    
    # Convert to response models
    responses = []
    for img in images:
        img["_id"] = str(img["_id"])
        responses.append(ImageResponse(**img))
    
    return responses


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Download a document (PDF file)
    
    Args:
        doc_id: Document ID
        current_user: Current authenticated user
        
    Returns:
        FileResponse with PDF file
    """
    user_id_str = str(current_user["_id"])
    
    # Verify document belongs to user
    doc = await get_owned_resource(
        get_documents_collection,
        doc_id,
        user_id_str,
        "Document"
    )
    
    # Check if file exists
    file_path = doc["file_path"]
    if not Path(file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk"
        )
    
    # Return file
    return FileResponse(
        path=file_path,
        filename=doc["filename"],
        media_type="application/pdf"
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a document and its associated extracted images and annotations
    
    Args:
        doc_id: Document ID
        current_user: Current authenticated user
    """
    try:
        await delete_document_and_artifacts(
            document_id=doc_id,
            user_id=str(current_user["_id"])
        )
    except ValueError as e:
        if "Invalid document ID" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        elif "Document not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e)
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(e)}"
        )


# ============================================================================
# TASK STATUS ENDPOINTS
# ============================================================================

@router.get("/tasks/{task_id}", tags=["documents"])
async def get_task_status(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get status of image extraction task
    
    Query a background task's status. The status can be:
    - PENDING: Task is waiting in the queue
    - STARTED: Task has started processing
    - SUCCESS: Task completed successfully
    - FAILURE: Task failed
    - RETRY: Task is retrying after failure
    - REVOKED: Task was cancelled
    
    Returns:
        {
            "task_id": "abc-123-def",
            "status": "SUCCESS",
            "result": {
                "doc_id": "507f1f77bcf86cd799439011",
                "extracted_count": 5,
                "errors": []
            }
        }
    """
    try:
        task = AsyncResult(task_id, app=celery_app)
        
        response = {
            "task_id": task_id,
            "status": task.status,
        }
        
        if task.successful():
            response["result"] = task.result
        elif task.failed():
            response["error"] = str(task.info)
        elif task.status == "RETRY":
            response["error"] = str(task.info)
        
        return response
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve task status: {str(e)}"
        )
