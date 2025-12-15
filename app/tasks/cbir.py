"""
CBIR (Content-Based Image Retrieval) tasks for async processing

These tasks handle background indexing and searching operations.
"""
from app.celery_config import celery_app
from app.db.mongodb import get_images_collection, get_analyses_collection
from app.utils.docker_cbir import (
    index_image,
    index_images_batch,
    search_similar_images,
    delete_image_from_index,
    delete_user_data,
)
from app.config.settings import CELERY_MAX_RETRIES
from app.schemas import AnalysisStatus
from bson import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.cbir_index_image")
def cbir_index_image(
    self,
    user_id: str,
    image_id: str,
    image_path: str,
    labels: list = None
):
    """
    Index a single image in the CBIR system asynchronously.
    
    Args:
        user_id: User ID for multi-tenancy
        image_id: MongoDB image ID
        image_path: Path to the image file
        labels: Optional list of labels
    """
    try:
        logger.info(f"Indexing image {image_id} for user {user_id}")
        
        success, message, result = index_image(
            user_id=user_id,
            image_path=image_path,
            labels=labels or []
        )
        
        if success:
            # Update image document with CBIR status
            images_col = get_images_collection()
            images_col.update_one(
                {"_id": ObjectId(image_id)},
                {
                    "$set": {
                        "cbir_indexed": True,
                        "cbir_indexed_at": datetime.utcnow(),
                        "cbir_id": result.get("id")
                    }
                }
            )
            logger.info(f"Image {image_id} indexed successfully")
            return {"status": "success", "cbir_id": result.get("id")}
        else:
            logger.error(f"Failed to index image {image_id}: {message}")
            return {"status": "failed", "error": message}
            
    except Exception as e:
        logger.error(f"Error indexing image {image_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.cbir_index_batch")
def cbir_index_batch(
    self,
    user_id: str,
    image_items: list
):
    """
    Index multiple images in batch asynchronously.
    
    Args:
        user_id: User ID for multi-tenancy
        image_items: List of dicts with 'image_id', 'image_path', 'labels'
    """
    try:
        logger.info(f"Batch indexing {len(image_items)} images for user {user_id}")
        
        # Prepare items for CBIR
        cbir_items = [
            {"image_path": item["image_path"], "labels": item.get("labels", [])}
            for item in image_items
        ]
        
        success, message, result = index_images_batch(user_id, cbir_items)
        
        if success:
            # Update image documents with CBIR status
            images_col = get_images_collection()
            indexed_count = result.get("indexed_count", 0)
            
            # Mark all as indexed (CBIR handles duplicates internally)
            for item in image_items:
                images_col.update_one(
                    {"_id": ObjectId(item["image_id"])},
                    {
                        "$set": {
                            "cbir_indexed": True,
                            "cbir_indexed_at": datetime.utcnow()
                        }
                    }
                )
            
            logger.info(f"Batch indexed {indexed_count} images for user {user_id}")
            return {"status": "success", "indexed_count": indexed_count}
        else:
            logger.error(f"Failed to batch index for user {user_id}: {message}")
            return {"status": "failed", "error": message}
            
    except Exception as e:
        logger.error(f"Error batch indexing for user {user_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.cbir_search")
def cbir_search(
    self,
    analysis_id: str,
    user_id: str,
    query_image_id: str,
    query_image_path: str,
    top_k: int = 10,
    labels: list = None
):
    """
    Search for similar images asynchronously.
    
    Args:
        analysis_id: MongoDB analysis ID for tracking
        user_id: User ID for multi-tenancy
        query_image_id: MongoDB ID of query image
        query_image_path: Path to query image
        top_k: Number of results
        labels: Optional filter labels
    """
    analyses_col = get_analyses_collection()
    
    try:
        # Update status to processing
        analyses_col.update_one(
            {"_id": ObjectId(analysis_id)},
            {
                "$set": {
                    "status": AnalysisStatus.PROCESSING,
                    "status_message": "Searching for similar images...",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Searching similar images for analysis {analysis_id}")
        
        success, message, results = search_similar_images(
            user_id=user_id,
            image_path=query_image_path,
            top_k=top_k,
            labels=labels
        )
        
        if success:
            # Enrich results with image IDs from our database
            enriched_results = _enrich_search_results(user_id, results)
            
            analyses_col.update_one(
                {"_id": ObjectId(analysis_id)},
                {
                    "$set": {
                        "status": AnalysisStatus.COMPLETED,
                        "status_message": "Completed",
                        "results": {
                            "timestamp": datetime.utcnow(),
                            "query_image_id": query_image_id,
                            "top_k": top_k,
                            "labels_filter": labels,
                            "matches_count": len(enriched_results),
                            "matches": enriched_results
                        },
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            logger.info(f"CBIR search completed for analysis {analysis_id}, found {len(enriched_results)} matches")
            return {"status": "completed", "matches_count": len(enriched_results)}
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
            logger.error(f"CBIR search failed for analysis {analysis_id}: {message}")
            return {"status": "failed", "error": message}
            
    except Exception as e:
        logger.error(f"Error in CBIR search for analysis {analysis_id}: {e}")
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


@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.cbir_delete_image")
def cbir_delete_image(
    self,
    user_id: str,
    image_id: str,
    image_path: str
):
    """
    Delete an image from the CBIR index asynchronously.
    
    Args:
        user_id: User ID for multi-tenancy
        image_id: MongoDB image ID
        image_path: Path to the image
    """
    try:
        logger.info(f"Deleting image {image_id} from CBIR index")
        
        success, message = delete_image_from_index(user_id, image_path)
        
        if success:
            # Update image document
            images_col = get_images_collection()
            images_col.update_one(
                {"_id": ObjectId(image_id)},
                {
                    "$set": {
                        "cbir_indexed": False,
                        "cbir_id": None
                    },
                    "$unset": {
                        "cbir_indexed_at": ""
                    }
                }
            )
            logger.info(f"Image {image_id} removed from CBIR index")
            return {"status": "success"}
        else:
            logger.error(f"Failed to delete image {image_id} from CBIR: {message}")
            return {"status": "failed", "error": message}
            
    except Exception as e:
        logger.error(f"Error deleting image {image_id} from CBIR: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.cbir_delete_user_data")
def cbir_delete_user_data(self, user_id: str):
    """
    Delete all CBIR data for a user asynchronously.
    
    Args:
        user_id: User ID whose data to delete
    """
    try:
        logger.info(f"Deleting all CBIR data for user {user_id}")
        
        success, message = delete_user_data(user_id)
        
        if success:
            # Update all user's images
            images_col = get_images_collection()
            images_col.update_many(
                {"user_id": user_id},
                {
                    "$set": {"cbir_indexed": False, "cbir_id": None},
                    "$unset": {"cbir_indexed_at": ""}
                }
            )
            logger.info(f"All CBIR data deleted for user {user_id}")
            return {"status": "success"}
        else:
            logger.error(f"Failed to delete CBIR data for user {user_id}: {message}")
            return {"status": "failed", "error": message}
            
    except Exception as e:
        logger.error(f"Error deleting CBIR data for user {user_id}: {e}")
        raise self.retry(exc=e, countdown=60)


def _enrich_search_results(user_id: str, results: list) -> list:
    """
    Enrich CBIR search results with image data from MongoDB.
    
    Args:
        user_id: User ID
        results: Raw CBIR results
        
    Returns:
        Enriched results
    """
    if not results:
        return []
    
    images_col = get_images_collection()
    
    # Get all image paths
    paths = [r["image_path"] for r in results]
    
    # Query images by path
    images = list(images_col.find({
        "user_id": user_id,
        "file_path": {"$in": paths}
    }))
    
    # Create lookup by path
    path_to_image = {img["file_path"]: img for img in images}
    
    enriched = []
    for result in results:
        path = result["image_path"]
        image = path_to_image.get(path)
        
        # Note: For Inner Product (IP) metric, distance IS the similarity score (higher = more similar)
        # Our CBIR uses IP metric with normalized embeddings, so distance is cosine similarity
        raw_distance = result.get("distance", 0)
        similarity = max(0.0, min(1.0, raw_distance))  # Clamp to [0, 1] range
        
        enriched_result = {
            "cbir_id": result.get("id"),
            "distance": raw_distance,
            "similarity_score": round(similarity, 4),
            "cbir_labels": result.get("labels", []),
            "image_path": path,
        }
        
        if image:
            enriched_result.update({
                "image_id": str(image["_id"]),
                "filename": image.get("filename"),
                "file_size": image.get("file_size"),
                "source_type": image.get("source_type"),
                "document_id": image.get("document_id"),
                "image_type": image.get("image_type", []),
            })
        
        enriched.append(enriched_result)
    
    return enriched
