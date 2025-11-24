from fastapi import APIRouter, Depends, HTTPException, status
from app.utils.security import get_current_user
from app.db.mongodb import get_analyses_collection, get_images_collection
from app.schemas import (
    AnalysisResponse,
    CrossImageAnalysisCreate,
    AnalysisType,
    AnalysisStatus
)
from app.tasks.copy_move_detection import detect_copy_move
from app.services.resource_helpers import get_owned_resource
from datetime import datetime
from bson import ObjectId

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

@router.post("/copy-move/cross", status_code=status.HTTP_202_ACCEPTED, response_model=dict)
async def analyze_copy_move_cross(
    request: CrossImageAnalysisCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Start cross-image copy-move detection analysis.
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
        "method": request.method
    }
    result = analyses_col.insert_one(analysis_doc)
    analysis_id = str(result.inserted_id)
    
    # Update both Image documents with analysis_id
    images_col = get_images_collection()
    images_col.update_many(
        {"_id": {"$in": [ObjectId(request.source_image_id), ObjectId(request.target_image_id)]}},
        {"$addToSet": {"analysis_ids": analysis_id}}
    )
    
    # Trigger task (reusing the same task, it handles both types now via run_copy_move_detection_with_docker)
    # Wait, I need to update the task signature to accept target_image_path or create a new task.
    # The current task `detect_copy_move` accepts `image_path`.
    # I should probably update `detect_copy_move` to be generic or create a wrapper.
    # Let's create a new task `detect_copy_move_cross` for clarity and to match the Todo list.
    
    from app.tasks.copy_move_detection import detect_copy_move_cross
    
    detect_copy_move_cross.delay(
        analysis_id=analysis_id,
        source_image_id=request.source_image_id,
        target_image_id=request.target_image_id,
        user_id=user_id_str,
        source_image_path=source_image["file_path"],
        target_image_path=target_image["file_path"],
        method=request.method
    )
    
    return {
        "message": "Cross-image copy-move analysis started",
        "analysis_id": analysis_id
    }
