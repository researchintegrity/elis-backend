"""
Frontend-specific API routes for dashboard, documents, and images
Provides unified endpoints with pagination, filtering, and standardized responses
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from datetime import datetime
from typing import Optional, List
from app.schemas import ApiResponse, PaginatedResponse
from app.db.mongodb import get_database, get_users_collection, get_documents_collection, get_images_collection
from app.utils.security import get_current_user
from bson import ObjectId

router = APIRouter(prefix="/api", tags=["api"])


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get(
    "/health",
    response_model=ApiResponse,
    summary="Health Check",
    description="Check if the API is running and responsive"
)
async def health_check():
    """
    Health check endpoint to verify API is operational
    """
    return ApiResponse(
        success=True,
        message="API is healthy and operational",
        data={"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    )


# ============================================================================
# DASHBOARD ENDPOINTS
# ============================================================================

@router.get(
    "/dashboard/stats",
    response_model=ApiResponse,
    summary="Get Dashboard Statistics",
    description="Retrieve overall system statistics for the dashboard"
)
async def get_dashboard_stats(current_user: dict = Depends(get_current_user)):
    """
    Get dashboard statistics including document count, image count, and storage usage
    
    Args:
        current_user: Currently authenticated user
        
    Returns:
        Dashboard statistics with success status
    """
    try:
        user_id = str(current_user.get("_id"))
        
        # Get document count
        doc_collection = get_documents_collection()
        doc_count = doc_collection.count_documents({"user_id": user_id})
        
        # Get image count
        img_collection = get_images_collection()
        img_count = img_collection.count_documents({"user_id": user_id})
        
        # Get user storage info
        user_collection = get_users_collection()
        user = user_collection.find_one({"_id": ObjectId(user_id)})
        
        storage_used = user.get("storage_used", 0) if user else 0
        storage_limit = 1073741824  # 1 GB default limit
        storage_remaining = max(0, storage_limit - storage_used)
        
        return ApiResponse(
            success=True,
            message="Dashboard statistics retrieved successfully",
            data={
                "total_documents": doc_count,
                "total_images": img_count,
                "storage_used": storage_used,
                "storage_limit": storage_limit,
                "storage_remaining": storage_remaining,
                "storage_percent_used": round((storage_used / storage_limit) * 100, 2)
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DOCUMENTS ENDPOINTS
# ============================================================================

@router.get(
    "/documents",
    response_model=PaginatedResponse,
    summary="List User Documents",
    description="Retrieve paginated list of user's documents with optional filtering"
)
async def list_documents(
    current_user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number starting from 1"),
    per_page: int = Query(10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("uploaded_date", description="Sort field: uploaded_date, filename"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    search: Optional[str] = Query(None, description="Search in filename")
):
    """
    List documents with pagination and filtering
    
    Args:
        current_user: Currently authenticated user
        page: Page number (1-indexed)
        per_page: Items per page (1-100)
        sort_by: Field to sort by
        order: Sort order (asc/desc)
        search: Optional search term for filename
        
    Returns:
        Paginated list of documents
    """
    try:
        user_id = str(current_user.get("_id"))
        collection = get_documents_collection()
        
        # Build filter
        filter_query = {"user_id": user_id}
        if search:
            filter_query["filename"] = {"$regex": search, "$options": "i"}
        
        # Get total count
        total_items = collection.count_documents(filter_query)
        total_pages = (total_items + per_page - 1) // per_page
        
        # Validate pagination
        if page > total_pages and total_pages > 0:
            page = total_pages
        
        # Calculate skip
        skip = (page - 1) * per_page
        
        # Build sort order
        sort_order = -1 if order.lower() == "desc" else 1
        
        # Query documents
        documents = list(collection.find(filter_query)
                        .sort(sort_by, sort_order)
                        .skip(skip)
                        .limit(per_page))
        
        # Convert ObjectId to string for JSON serialization
        for doc in documents:
            doc["_id"] = str(doc["_id"])
            if "user_id" in doc:
                doc["user_id"] = str(doc["user_id"])
        
        return PaginatedResponse(
            success=True,
            message="Documents retrieved successfully",
            data=documents,
            pagination={
                "current_page": page,
                "total_pages": total_pages,
                "page_size": per_page,
                "total_items": total_items
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/documents/{document_id}",
    response_model=ApiResponse,
    summary="Get Document Details",
    description="Retrieve detailed information about a specific document"
)
async def get_document_detail(
    document_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get detailed information about a specific document including associated images
    
    Args:
        document_id: Document ID
        current_user: Currently authenticated user
        
    Returns:
        Document details with associated images
    """
    try:
        user_id = str(current_user.get("_id"))
        collection = get_documents_collection()
        
        try:
            doc_oid = ObjectId(document_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid document ID format")
        
        document = collection.find_one({"_id": doc_oid, "user_id": user_id})
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Convert ObjectId to string
        document["_id"] = str(document["_id"])
        
        # Get associated images
        img_collection = get_images_collection()
        images = list(img_collection.find({"document_id": document_id}))
        for img in images:
            img["_id"] = str(img["_id"])
        
        document["associated_images"] = images
        
        return ApiResponse(
            success=True,
            message="Document retrieved successfully",
            data=document
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/documents/{document_id}",
    response_model=ApiResponse,
    summary="Delete Document",
    description="Delete a document and its associated images"
)
async def delete_document(
    document_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a document and all its associated images
    
    Args:
        document_id: Document ID to delete
        current_user: Currently authenticated user
        
    Returns:
        Success message
    """
    try:
        user_id = str(current_user.get("_id"))
        
        try:
            doc_oid = ObjectId(document_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid document ID format")
        
        doc_collection = get_documents_collection()
        document = doc_collection.find_one({"_id": doc_oid, "user_id": user_id})
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Delete associated images
        img_collection = get_images_collection()
        img_collection.delete_many({"document_id": document_id})
        
        # Delete document
        result = doc_collection.delete_one({"_id": doc_oid})
        
        return ApiResponse(
            success=True,
            message="Document and associated images deleted successfully",
            data={"deleted_id": document_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# IMAGES ENDPOINTS
# ============================================================================

@router.get(
    "/images",
    response_model=PaginatedResponse,
    summary="List User Images",
    description="Retrieve paginated list of user's images with optional filtering"
)
async def list_images(
    current_user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number starting from 1"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("uploaded_date", description="Sort field"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    source_type: Optional[str] = Query(None, description="Filter by source type: uploaded, extracted"),
    document_id: Optional[str] = Query(None, description="Filter by document ID")
):
    """
    List images with pagination and filtering
    
    Args:
        current_user: Currently authenticated user
        page: Page number (1-indexed)
        per_page: Items per page (1-100)
        sort_by: Field to sort by
        order: Sort order (asc/desc)
        source_type: Optional filter by source type
        document_id: Optional filter by document ID
        
    Returns:
        Paginated list of images
    """
    try:
        user_id = str(current_user.get("_id"))
        collection = get_images_collection()
        
        # Build filter
        filter_query = {"user_id": user_id}
        if source_type:
            filter_query["source_type"] = source_type
        if document_id:
            filter_query["document_id"] = document_id
        
        # Get total count
        total_items = collection.count_documents(filter_query)
        total_pages = (total_items + per_page - 1) // per_page
        
        # Validate pagination
        if page > total_pages and total_pages > 0:
            page = total_pages
        
        # Calculate skip
        skip = (page - 1) * per_page
        
        # Build sort order
        sort_order = -1 if order.lower() == "desc" else 1
        
        # Query images
        images = list(collection.find(filter_query)
                     .sort(sort_by, sort_order)
                     .skip(skip)
                     .limit(per_page))
        
        # Convert ObjectId to string
        for img in images:
            img["_id"] = str(img["_id"])
            if "user_id" in img:
                img["user_id"] = str(img["user_id"])
        
        return PaginatedResponse(
            success=True,
            message="Images retrieved successfully",
            data=images,
            pagination={
                "current_page": page,
                "total_pages": total_pages,
                "page_size": per_page,
                "total_items": total_items
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/images/{image_id}",
    response_model=ApiResponse,
    summary="Get Image Details",
    description="Retrieve detailed information about a specific image"
)
async def get_image_detail(
    image_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get detailed information about a specific image
    
    Args:
        image_id: Image ID
        current_user: Currently authenticated user
        
    Returns:
        Image details
    """
    try:
        user_id = str(current_user.get("_id"))
        collection = get_images_collection()
        
        try:
            img_oid = ObjectId(image_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid image ID format")
        
        image = collection.find_one({"_id": img_oid, "user_id": user_id})
        
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        
        # Convert ObjectId to string
        image["_id"] = str(image["_id"])
        
        return ApiResponse(
            success=True,
            message="Image retrieved successfully",
            data=image
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/images/{image_id}",
    response_model=ApiResponse,
    summary="Delete Image",
    description="Delete a specific image"
)
async def delete_image(
    image_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a specific image
    
    Args:
        image_id: Image ID to delete
        current_user: Currently authenticated user
        
    Returns:
        Success message
    """
    try:
        user_id = str(current_user.get("_id"))
        collection = get_images_collection()
        
        try:
            img_oid = ObjectId(image_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid image ID format")
        
        image = collection.find_one({"_id": img_oid, "user_id": user_id})
        
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        
        result = collection.delete_one({"_id": img_oid})
        
        return ApiResponse(
            success=True,
            message="Image deleted successfully",
            data={"deleted_id": image_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SEARCH ENDPOINTS
# ============================================================================

@router.get(
    "/search",
    response_model=PaginatedResponse,
    summary="Global Search",
    description="Search across documents and images"
)
async def global_search(
    query: str = Query(..., min_length=1, description="Search query"),
    current_user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number starting from 1"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page")
):
    """
    Global search across documents and images
    
    Args:
        query: Search query string
        current_user: Currently authenticated user
        page: Page number (1-indexed)
        per_page: Items per page (1-100)
        
    Returns:
        Paginated search results
    """
    try:
        user_id = str(current_user.get("_id"))
        
        # Search documents
        doc_collection = get_documents_collection()
        documents = list(doc_collection.find({
            "user_id": user_id,
            "filename": {"$regex": query, "$options": "i"}
        }))
        
        # Search images
        img_collection = get_images_collection()
        images = list(img_collection.find({
            "user_id": user_id,
            "filename": {"$regex": query, "$options": "i"}
        }))
        
        # Combine results
        results = []
        for doc in documents:
            doc["_id"] = str(doc["_id"])
            doc["type"] = "document"
            results.append(doc)
        
        for img in images:
            img["_id"] = str(img["_id"])
            img["type"] = "image"
            results.append(img)
        
        # Sort by uploaded_date (newest first)
        results.sort(key=lambda x: x.get("uploaded_date", datetime.utcnow()), reverse=True)
        
        # Paginate
        total_items = len(results)
        total_pages = (total_items + per_page - 1) // per_page
        
        if page > total_pages and total_pages > 0:
            page = total_pages
        
        skip = (page - 1) * per_page
        paginated_results = results[skip:skip + per_page]
        
        return PaginatedResponse(
            success=True,
            message=f"Found {total_items} results for '{query}'",
            data=paginated_results,
            pagination={
                "current_page": page,
                "total_pages": total_pages,
                "page_size": per_page,
                "total_items": total_items
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
