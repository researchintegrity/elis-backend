"""
Copy-Move Detection tasks for async processing
"""
from celery import current_task
from app.celery_config import celery_app
from app.db.mongodb import get_analyses_collection
from app.utils.docker_copy_move import run_copy_move_detection_with_docker
from app.config.settings import CELERY_MAX_RETRIES
from app.schemas import AnalysisStatus, AnalysisType
from bson import ObjectId
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.detect_copy_move")
def detect_copy_move(
    self,
    analysis_id: str,
    image_id: str,
    user_id: str,
    image_path: str,
    method: int = 2
):
    """
    Run copy-move detection on an image asynchronously.
    
    Args:
        analysis_id: MongoDB ID of the analysis document
        image_id: MongoDB ID of the image
        user_id: User ID
        image_path: Path to the image file
        method: Detection method (1-5)
    """
    analyses_col = get_analyses_collection()
    
    try:
        # Update status to processing
        analyses_col.update_one(
            {"_id": ObjectId(analysis_id)},
            {
                "$set": {
                    "status": AnalysisStatus.PROCESSING,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Starting copy-move detection for analysis {analysis_id} (image {image_id}) with method {method}")
        
        # Run detection
        success, message, results = run_copy_move_detection_with_docker(
            analysis_id=analysis_id,
            analysis_type=AnalysisType.SINGLE_IMAGE_COPY_MOVE,
            user_id=user_id,
            image_path=image_path,
            method=method
        )
        
        if success:
            # Update with results
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.COMPLETED,
                        "results": {
                            "method": method,
                            "timestamp": datetime.utcnow(),
                            "matches_image": results.get('matches_image'),
                            "clusters_image": results.get('clusters_image')
                        },
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            logger.info(f"Copy-move detection completed for analysis {analysis_id}")
            return {"status": "completed", "results": results}
        else:
            # Update with failure
            logger.error(f"Copy-move detection failed for analysis {analysis_id}: {message}")
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.FAILED,
                        "error": message,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            return {"status": "failed", "error": message}

    except Exception as e:
        logger.exception(f"Error in copy-move detection task for analysis {analysis_id}")
        try:
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.FAILED,
                        "error": str(e),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        except Exception as db_error:
            logger.error(f"Failed to update analysis status to failed: {db_error}")
        
        # Retry task if appropriate
        raise self.retry(exc=e)

@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.detect_copy_move_cross")
def detect_copy_move_cross(
    self,
    analysis_id: str,
    source_image_id: str,
    target_image_id: str,
    user_id: str,
    source_image_path: str,
    target_image_path: str,
    method: int = 2
):
    """
    Run cross-image copy-move detection asynchronously.
    
    Args:
        analysis_id: MongoDB ID of the analysis document
        source_image_id: MongoDB ID of the source image
        target_image_id: MongoDB ID of the target image
        user_id: User ID
        source_image_path: Path to the source image file
        target_image_path: Path to the target image file
        method: Detection method (1-5)
    """
    analyses_col = get_analyses_collection()
    
    try:
        # Update status to processing
        analyses_col.update_one(
            {"_id": ObjectId(analysis_id)},
            {
                "$set": {
                    "status": AnalysisStatus.PROCESSING,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Starting cross-image copy-move detection for analysis {analysis_id} (source: {source_image_id}, target: {target_image_id}) with method {method}")
        
        # Run detection
        success, message, results = run_copy_move_detection_with_docker(
            analysis_id=analysis_id,
            analysis_type=AnalysisType.CROSS_IMAGE_COPY_MOVE,
            user_id=user_id,
            image_path=source_image_path,
            target_image_path=target_image_path,
            method=method
        )
        
        if success:
            # Update with results
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.COMPLETED,
                        "results": {
                            "method": method,
                            "timestamp": datetime.utcnow(),
                            "matches_image": results.get('matches_image'),
                            "clusters_image": results.get('clusters_image')
                        },
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            logger.info(f"Cross-image copy-move detection completed for analysis {analysis_id}")
            return {"status": "completed", "results": results}
        else:
            # Update with failure
            logger.error(f"Cross-image copy-move detection failed for analysis {analysis_id}: {message}")
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.FAILED,
                        "error": message,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            return {"status": "failed", "error": message}

    except Exception as e:
        logger.exception(f"Error in cross-image copy-move detection task for analysis {analysis_id}")
        try:
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.FAILED,
                        "error": str(e),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        except Exception as db_error:
            logger.error(f"Failed to update analysis status to failed: {db_error}")
        
        # Retry task if appropriate
        raise self.retry(exc=e)
