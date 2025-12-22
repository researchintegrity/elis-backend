from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from app.utils.security import get_current_user
from app.db.mongodb import get_analyses_collection, get_images_collection
from app.schemas import (
    AnalysisResponse,
    CrossImageAnalysisCreate,
    SingleImageAnalysisCreate,
    AnalysisType,
    AnalysisStatus,
)
from app.services.resource_helpers import get_owned_resource
from app.config.settings import convert_container_path_to_host, is_container_path
from datetime import datetime
from bson import ObjectId
from pathlib import Path
import os
from app.tasks.copy_move_detection import detect_copy_move

router = APIRouter(
    prefix="/analyses",
    tags=["Analyses"]
)

@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get analysis details by ID.
    """
    user_id_str = str(current_user["_id"])
    analyses_col = get_analyses_collection()
    
    analysis = analyses_col.find_one({"_id": ObjectId(analysis_id)})
    
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found"
        )
        
    if analysis["user_id"] != user_id_str:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this analysis"
        )
        
    return analysis


@router.get("/{analysis_id}/results/{result_type}/download")
async def download_analysis_result(
    analysis_id: str,
    result_type: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Download an analysis result image file.
    
    Args:
        analysis_id: Analysis ID
        result_type: Type of result to download ('matches' or 'clusters')
        current_user: Current authenticated user
        
    Returns:
        FileResponse with the result image
    """
    user_id_str = str(current_user["_id"])
    
    # Validate result_type
    if result_type not in ("matches", "clusters"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid result type. Must be 'matches' or 'clusters'"
        )
    
    analyses_col = get_analyses_collection()
    analysis = analyses_col.find_one({"_id": ObjectId(analysis_id)})
    
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found"
        )
        
    if analysis["user_id"] != user_id_str:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this analysis"
        )
    
    # Get the result file path
    results = analysis.get("results", {})
    result_key = f"{result_type}_image"
    file_path = results.get(result_key)
    
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {result_type} result available for this analysis"
        )
    
    # Check if file exists (path is already container path, which is mounted)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Result file not found on disk: {file_path}"
        )
    
    # Return the file
    return FileResponse(
        path=file_path,
        filename=os.path.basename(file_path),
        media_type="image/png"
    )


@router.post("/copy-move/single", status_code=status.HTTP_202_ACCEPTED, response_model=dict)
async def analyze_copy_move_single(
    request: SingleImageAnalysisCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Start single-image copy-move detection analysis.
    
    Supports two detection methods:
    - 'keypoint': Advanced keypoint-based detection (recommended)
    - 'dense': Block-based dense matching
    """
    user_id_str = str(current_user["_id"])
    
    # Verify ownership
    image = await get_owned_resource(
        get_images_collection,
        request.image_id,
        user_id_str,
        "Image"
    )
    
    # Create Analysis document
    analyses_col = get_analyses_collection()
    analysis_doc = {
        "type": AnalysisType.SINGLE_IMAGE_COPY_MOVE,
        "user_id": user_id_str,
        "source_image_id": request.image_id,
        "status": AnalysisStatus.PENDING,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "method": request.method.value,  # Store as string value
        "dense_method": request.dense_method if request.method.value == "dense" else None
    }
    result = analyses_col.insert_one(analysis_doc)
    analysis_id = str(result.inserted_id)
    
    # Update Image document with analysis_id
    images_col = get_images_collection()
    images_col.update_one(
        {"_id": ObjectId(request.image_id)},
        {"$addToSet": {"analysis_ids": analysis_id}}
    )
    
    # Trigger task with analysis_id
    detect_copy_move.delay(
        analysis_id=analysis_id,
        image_id=request.image_id,
        user_id=user_id_str,
        image_path=image["file_path"],
        method=request.method.value,
        dense_method=request.dense_method
    )
    
    return {
        "message": "Single-image copy-move analysis started",
        "analysis_id": analysis_id
    }


@router.post("/copy-move/cross", status_code=status.HTTP_202_ACCEPTED, response_model=dict)
async def analyze_copy_move_cross(
    request: CrossImageAnalysisCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Start cross-image copy-move detection analysis.
    
    Detects if content from source image was copied to target image.
    
    Supports two detection methods:
    - 'keypoint': Advanced keypoint-based detection (recommended for cross-image)
      - Supports descriptor types: cv_sift, cv_rsift (default), vlfeat_sift_heq
    - 'dense': Block-based dense matching (methods 1-5)
    """
    user_id_str = str(current_user["_id"])
    
    # Verify ownership of both images
    source_image = await get_owned_resource(
        get_images_collection,
        request.source_image_id,
        user_id_str,
        "Source Image"
    )
    
    target_image = await get_owned_resource(
        get_images_collection,
        request.target_image_id,
        user_id_str,
        "Target Image"
    )
    
    # Create Analysis document
    analyses_col = get_analyses_collection()
    analysis_doc = {
        "type": AnalysisType.CROSS_IMAGE_COPY_MOVE,
        "user_id": user_id_str,
        "source_image_id": request.source_image_id,
        "target_image_id": request.target_image_id,
        "status": AnalysisStatus.PENDING,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "method": request.method.value,  # Store as string value
        "dense_method": request.dense_method if request.method.value == "dense" else None,
        "descriptor": request.descriptor.value if request.method.value == "keypoint" else None
    }
    result = analyses_col.insert_one(analysis_doc)
    analysis_id = str(result.inserted_id)
    
    # Update both Image documents with analysis_id
    images_col = get_images_collection()
    images_col.update_many(
        {"_id": {"$in": [ObjectId(request.source_image_id), ObjectId(request.target_image_id)]}},
        {"$addToSet": {"analysis_ids": analysis_id}}
    )
    
    from app.tasks.copy_move_detection import detect_copy_move_cross
    
    detect_copy_move_cross.delay(
        analysis_id=analysis_id,
        source_image_id=request.source_image_id,
        target_image_id=request.target_image_id,
        user_id=user_id_str,
        source_image_path=source_image["file_path"],
        target_image_path=target_image["file_path"],
        method=request.method.value,
        dense_method=request.dense_method,
        descriptor=request.descriptor.value
    )
    
    return {
        "message": "Cross-image copy-move analysis started",
        "analysis_id": analysis_id
    }

@router.post("/trufor", status_code=status.HTTP_202_ACCEPTED, response_model=dict)
async def analyze_trufor(
    request: SingleImageAnalysisCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Start TruFor forgery detection analysis.
    """
    user_id_str = str(current_user["_id"])
    
    # Verify ownership
    image = await get_owned_resource(
        get_images_collection,
        request.image_id,
        user_id_str,
        "Image"
    )
    
    # Create Analysis document
    analyses_col = get_analyses_collection()
    analysis_doc = {
        "type": AnalysisType.TRUFOR,
        "user_id": user_id_str,
        "source_image_id": request.image_id,
        "status": AnalysisStatus.PENDING,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    result = analyses_col.insert_one(analysis_doc)
    analysis_id = str(result.inserted_id)
    
    # Update Image document
    images_col = get_images_collection()
    images_col.update_one(
        {"_id": ObjectId(request.image_id)},
        {"$addToSet": {"analysis_ids": analysis_id}}
    )
    
    # Trigger task
    from app.tasks.trufor import detect_trufor
    detect_trufor.delay(
        analysis_id=analysis_id,
        image_id=request.image_id,
        user_id=user_id_str,
        image_path=image["file_path"]
    )
    
    return {"message": "TruFor analysis started", "analysis_id": analysis_id}
