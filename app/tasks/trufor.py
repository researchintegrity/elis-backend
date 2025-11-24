"""
TruFor Detection tasks for async processing
"""
from celery import current_task
from app.celery_config import celery_app
from app.db.mongodb import get_analyses_collection
from app.utils.docker_trufor import run_trufor_detection_with_docker
from app.config.settings import CELERY_MAX_RETRIES
from app.schemas import AnalysisStatus, AnalysisType
from bson import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.detect_trufor")
def detect_trufor(
    self,
    analysis_id: str,
    image_id: str,
    user_id: str,
    image_path: str
):
    """
    Run TruFor detection on an image asynchronously.
    
    Args:
        analysis_id: MongoDB ID of the analysis document
        image_id: MongoDB ID of the image
        user_id: User ID
        image_path: Path to the image file
    """
    analyses_col = get_analyses_collection()
    
    def update_status(status_msg: str):
        """Callback to update analysis status in DB"""
        try:
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status_message": status_msg,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        except Exception as e:
            logger.error(f"Failed to update status for analysis {analysis_id}: {e}")

    try:
        # Update status to processing
        analyses_col.update_one(
            {"_id": ObjectId(analysis_id)},
            {
                "$set": {
                    "status": AnalysisStatus.PROCESSING,
                    "status_message": "Starting TruFor detection...",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Starting TruFor detection for analysis {analysis_id} (image {image_id})")
        
        # Run detection
        success, message, results = run_trufor_detection_with_docker(
            analysis_id=analysis_id,
            user_id=user_id,
            image_path=image_path,
            status_callback=update_status
        )
        
        if success:
            # Update with results
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.COMPLETED,
                        "status_message": "Completed",
                        "results": {
                            "timestamp": datetime.utcnow(),
                            "visualization": results.get('visualization'),
                            "files": results.get('files')
                        },
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            logger.info(f"TruFor detection completed for analysis {analysis_id}")
            return {"status": "completed", "results": results}
        else:
            # Update with failure
            logger.error(f"TruFor detection failed for analysis {analysis_id}: {message}")
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.FAILED,
                        "error": message,
                        "status_message": "Failed",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            return {"status": "failed", "error": message}

    except Exception as e:
        logger.exception(f"Error in TruFor detection task for analysis {analysis_id}")
        try:
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.FAILED,
                        "error": str(e),
                        "status_message": "System Error",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        except:
            pass
        raise self.retry(exc=e)
