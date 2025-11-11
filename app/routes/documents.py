"""
Document upload routes for PDF file management
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from fastapi.responses import FileResponse
from typing import List
from bson import ObjectId
from datetime import datetime
from pathlib import Path

from app.schemas import DocumentResponse, ImageResponse
from app.db.mongodb import get_documents_collection, get_images_collection
from app.utils.security import get_current_user
from app.utils.file_storage import (
    validate_pdf,
    save_pdf_file,
    get_extraction_output_path,
    figure_extraction_hook,
    delete_directory,
    delete_file,
    check_storage_quota,
    get_quota_status
)
from app.config.storage_quota import DEFAULT_USER_STORAGE_QUOTA

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
        
        # Trigger figure extraction hook (placeholder)
        try:
            extracted_count, extraction_errors = figure_extraction_hook(
                doc_id=doc_id,
                user_id=user_id_str,
                pdf_file_path=file_path
            )
            
            # Determine extraction status
            if extraction_errors:
                extraction_status = "completed" if extracted_count > 0 else "failed"
            else:
                extraction_status = "completed"
            
            # Update document with extraction results
            documents_col.update_one(
                {"_id": ObjectId(doc_id)},
                {
                    "$set": {
                        "extraction_status": extraction_status,
                        "extracted_image_count": extracted_count,
                        "extraction_errors": extraction_errors
                    }
                }
            )
        
        except Exception as e:
            # Log extraction error but don't fail the upload
            documents_col.update_one(
                {"_id": ObjectId(doc_id)},
                {
                    "$set": {
                        "extraction_status": "failed",
                        "extraction_errors": [f"Extraction error: {str(e)}"]
                    }
                }
            )
        
        # Retrieve and return updated document with quota info
        doc_record = documents_col.find_one({"_id": ObjectId(doc_id)})
        doc_record["_id"] = doc_id  # Ensure _id is set for response
        
        # Add quota information to response
        quota_status = get_quota_status(user_id_str, user_quota)
        doc_record["user_storage_used"] = quota_status["used_bytes"]
        doc_record["user_storage_remaining"] = quota_status["remaining_bytes"]
        
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
    
    # Get quota info
    quota_status = get_quota_status(user_id_str, user_quota)
    
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
        doc["user_storage_used"] = quota_status["used_bytes"]
        doc["user_storage_remaining"] = quota_status["remaining_bytes"]
        responses.append(DocumentResponse(**doc))
    
    return responses


@router.get("/{doc_id}", response_model=DocumentResponse)
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
    documents_col = get_documents_collection()
    user_id_str = str(current_user["_id"])
    user_quota = current_user.get("storage_limit_bytes", DEFAULT_USER_STORAGE_QUOTA)
    
    try:
        doc = documents_col.find_one({
            "_id": ObjectId(doc_id),
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
    
    doc["_id"] = doc_id
    
    # Add quota information
    quota_status = get_quota_status(user_id_str, user_quota)
    doc["user_storage_used"] = quota_status["used_bytes"]
    doc["user_storage_remaining"] = quota_status["remaining_bytes"]
    
    return DocumentResponse(**doc)


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
    # Verify document belongs to user
    documents_col = get_documents_collection()
    try:
        doc = documents_col.find_one({
            "_id": ObjectId(doc_id),
            "user_id": str(current_user["_id"])
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
    
    # Get images for this document
    images_col = get_images_collection()
    images = list(
        images_col.find({
            "document_id": doc_id,
            "user_id": str(current_user["_id"]),
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
    documents_col = get_documents_collection()
    
    # Verify document belongs to user
    try:
        doc = documents_col.find_one({
            "_id": ObjectId(doc_id),
            "user_id": str(current_user["_id"])
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
    Delete a document and its associated extracted images
    
    Args:
        doc_id: Document ID
        current_user: Current authenticated user
    """
    documents_col = get_documents_collection()
    images_col = get_images_collection()
    
    # Verify document belongs to user
    try:
        doc = documents_col.find_one({
            "_id": ObjectId(doc_id),
            "user_id": str(current_user["_id"])
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
    
    try:
        # Delete PDF file
        delete_file(doc["file_path"])
        
        # Delete extraction directory
        extraction_dir = f"uploads/{current_user['_id']}/images/extracted/{doc_id}"
        delete_directory(extraction_dir)
        
        # Delete extracted images from MongoDB
        images_col.delete_many({
            "document_id": doc_id,
            "user_id": str(current_user["_id"]),
            "source_type": "extracted"
        })
        
        # Delete document record
        documents_col.delete_one({"_id": ObjectId(doc_id)})
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(e)}"
        )
