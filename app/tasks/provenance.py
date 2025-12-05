"""
Provenance Analysis Tasks

Celery tasks for handling background provenance analysis.
"""
from app.celery_config import celery_app
from app.db.mongodb import get_analyses_collection
from app.services.provenance_service import run_provenance_analysis
from app.schemas import AnalysisStatus
from app.config.settings import CELERY_MAX_RETRIES
from bson import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.provenance_analysis")
def provenance_analysis_task(
    self,
    analysis_id: str,
    user_id: str,
    query_image_id: str,
    k: int = 10,
    q: int = 5,
    max_depth: int = 3,
    descriptor_type: str = "cv_rsift"
):
    """
    Run provenance analysis asynchronously.
    
    Args:
        analysis_id: MongoDB analysis ID
        user_id: User ID
        query_image_id: Query image ID
        k: Top-K candidates
        q: Top-Q expansion
        max_depth: Expansion depth
        descriptor_type: Descriptor type
    """
    analyses_col = get_analyses_collection()
    
    try:
        # Update status to processing
        analyses_col.update_one(
            {"_id": ObjectId(analysis_id)},
            {
                "$set": {
                    "status": AnalysisStatus.PROCESSING,
                    "status_message": "Running provenance analysis...",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Starting provenance analysis {analysis_id} for user {user_id}")
        
        success, message, result = run_provenance_analysis(
            user_id=user_id,
            query_image_id=query_image_id,
            k=k,
            q=q,
            max_depth=max_depth,
            descriptor_type=descriptor_type
        )
        
        if success:
            # Store results
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.COMPLETED,
                        "status_message": "Completed",
                        "results": result,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            logger.info(f"Provenance analysis {analysis_id} completed successfully")
            return {"status": "completed", "result": result}
        else:
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
            logger.error(f"Provenance analysis {analysis_id} failed: {message}")
            return {"status": "failed", "error": message}
            
    except Exception as e:
        logger.error(f"Error in provenance analysis {analysis_id}: {e}")
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
        raise self.retry(exc=e, countdown=60)
