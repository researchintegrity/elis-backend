"""
Document service for handling document operations
Provides business logic for document CRUD operations
"""

from pathlib import Path
from bson import ObjectId
from app.db.mongodb import (
    get_documents_collection,
    get_images_collection,
    get_annotations_collection
)
from app.utils.file_storage import (
    delete_file,
    delete_directory,
    update_user_storage_in_db
)
from app.tasks.cbir import cbir_delete_image
import logging

logger = logging.getLogger(__name__)


async def delete_document_and_artifacts(
    document_id: str,
    user_id: str
) -> dict:
    """
    Delete a document and all its associated artifacts (files, images, annotations)
    
    This is the single source of truth for document deletion logic.
    Called by both REST endpoints and can be imported by other services.
    
    Args:
        document_id: Document ID to delete
        user_id: User ID (as string) who owns the document
        
    Returns:
        Dictionary with deletion results
        
    Raises:
        ValueError: If document not found
        Exception: If deletion fails
    """
    documents_col = get_documents_collection()
    images_col = get_images_collection()
    annotations_col = get_annotations_collection()
    
    # Verify document belongs to user
    try:
        doc_oid = ObjectId(document_id)
    except Exception:
        raise ValueError("Invalid document ID format")
    
    doc = documents_col.find_one({
        "_id": doc_oid,
        "user_id": user_id
    })
    
    if not doc:
        raise ValueError("Document not found")
    
    # Delete PDF file from disk
    
    success, error = delete_file(doc["file_path"])
   

    if not success:
        raise Exception(f"Failed to delete PDF file: {error}")
    
    
    # Delete extraction directory
    extraction_dir = Path(doc["file_path"]).parent.parent / Path(f"images/extracted/{document_id}")
    success, error = delete_directory(str(extraction_dir))
    # Note: Directory might not exist, that's OK - we still proceed with DB cleanup
    if not success and "Directory not found" not in error:
        raise Exception(f"Failed to delete extraction directory: {error}")
    
    # Get all extracted image IDs for this document (with full data for CBIR cleanup)
    extracted_images = list(images_col.find({
        "document_id": document_id,
        "user_id": user_id,
        "source_type": "extracted"
    }, {"_id": 1, "file_path": 1, "cbir_indexed": 1}))
    
    image_ids = [str(img["_id"]) for img in extracted_images]
    
    # Queue CBIR deletion for indexed images
    cbir_deletion_count = 0
    for img in extracted_images:
        if img.get("cbir_indexed"):
            try:
                cbir_delete_image.delay(
                    user_id=user_id,
                    image_id=str(img["_id"]),
                    image_path=img["file_path"]
                )
                cbir_deletion_count += 1
            except Exception as e:
                logger.warning(f"Failed to queue CBIR deletion for image {img['_id']}: {e}")
                # Continue with document deletion even if CBIR deletion fails to queue
    
    if cbir_deletion_count > 0:
        logger.info(f"Queued CBIR deletion for {cbir_deletion_count} images from document {document_id}")
    
    # Delete annotations for all extracted images
    annotations_deleted = 0
    if image_ids:
        result = annotations_col.delete_many({
            "image_id": {"$in": image_ids},
            "user_id": user_id
        })
        annotations_deleted = result.deleted_count
    
    # Delete extracted images from MongoDB
    images_deleted_result = images_col.delete_many({
        "document_id": document_id,
        "user_id": user_id,
        "source_type": "extracted"
    })
    
    # Delete document record
    documents_col.delete_one({"_id": doc_oid})
    
    # Update user storage in database
    update_user_storage_in_db(user_id)
    
    return {
        "deleted_id": document_id,
        "annotations_deleted": annotations_deleted,
        "images_deleted": images_deleted_result.deleted_count
    }
