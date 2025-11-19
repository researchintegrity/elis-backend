"""
Panel extraction tasks for async processing
"""
import csv
import os
import logging
from typing import Dict, List, Any
from datetime import datetime
from pathlib import Path
from celery import current_task
from celery.exceptions import SoftTimeLimitExceeded
from bson import ObjectId
from app.celery_config import celery_app
from app.db.mongodb import get_images_collection
from app.utils.docker_panel_extractor import extract_panels_with_docker
from app.utils.file_storage import get_panel_output_path
from app.config.settings import CELERY_MAX_RETRIES, CELERY_RETRY_BACKOFF_BASE

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=CELERY_MAX_RETRIES, name="tasks.extract_panels")
def extract_panels_from_images(
    self,
    image_ids: List[str],
    user_id: str,
    image_paths: List[str]
):
    """
    Extract panels from images asynchronously

    This task:
    1. Validates all images exist and belong to user
    2. Calls Docker panel extraction
    3. Parses PANELS.csv output
    4. Creates MongoDB documents for each extracted panel
    5. Stores panel images in workspace
    6. Retries on failure (up to 3 times)

    Args:
        image_ids: List of MongoDB image document IDs
        user_id: User who owns the images
        image_paths: List of full paths to image files

    Returns:
        Dict with panel extraction results {
            task_id, status, image_ids, extracted_panels_count, result_panel_ids
        }

    Raises:
        Retries automatically with exponential backoff on failure
    """
    images_col = get_images_collection()
    task_id = self.request.id

    try:
        logger.info(
            f"Starting panel extraction for user_id={user_id}, "
            f"task_id={task_id}, image_count={len(image_ids)}"
        )

        # Validate all images exist and belong to user
        for img_id in image_ids:
            try:
                image_doc = images_col.find_one({"_id": ObjectId(img_id), "user_id": user_id})
                if not image_doc:
                    error_msg = f"Image not found or does not belong to user: {img_id}"
                    logger.error(error_msg)
                    return _handle_panel_extraction_failure(
                        task_id, image_ids, user_id, error_msg
                    )
            except Exception as e:
                error_msg = f"Error validating image {img_id}: {str(e)}"
                logger.error(error_msg)
                return _handle_panel_extraction_failure(
                    task_id, image_ids, user_id, error_msg
                )

        # Validate image files exist
        for img_path in image_paths:
            if not os.path.exists(img_path):
                error_msg = f"Image file not found: {img_path}"
                logger.error(error_msg)
                return _handle_panel_extraction_failure(
                    task_id, image_ids, user_id, error_msg
                )

        # Run panel extraction using Docker
        success, status_message, output_info = extract_panels_with_docker(
            image_ids=image_ids,
            user_id=user_id,
            image_paths=image_paths
        )

        if not success:
            logger.error(f"Panel extraction failed: {status_message}")
            return _handle_panel_extraction_failure(
                task_id, image_ids, user_id, status_message
            )

        # Parse PANELS.csv and create MongoDB documents
        panels_data = output_info.get("panels_data", [])
        panels_count = len(panels_data)
        output_dir = output_info.get("output_dir")

        logger.info(f"Panel extraction completed. Processing {panels_count} panels...")

        result_panel_ids = []

        for panel_info in panels_data:
            try:
                # Create MongoDB document for this panel
                panel_doc = _create_panel_document(
                    panel_info=panel_info,
                    user_id=user_id,
                    output_dir=output_dir
                )

                # Insert into MongoDB
                result = images_col.insert_one(panel_doc)
                panel_id = str(result.inserted_id)
                result_panel_ids.append(panel_id)

                logger.info(f"Created panel document: {panel_id} from {panel_info['panel_id']}")

            except Exception as e:
                error_msg = f"Error creating panel document for {panel_info.get('panel_id')}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                # Continue processing other panels instead of failing entirely

        if not result_panel_ids:
            error_msg = "No panel documents were successfully created"
            logger.error(error_msg)
            return _handle_panel_extraction_failure(
                task_id, image_ids, user_id, error_msg
            )

        # Success
        result = {
            "task_id": task_id,
            "status": "completed",
            "image_ids": image_ids,
            "extracted_panels_count": panels_count,
            "result_panel_ids": result_panel_ids,
            "message": f"Panel extraction successful. Created {len(result_panel_ids)} panel documents",
            "error": None
        }

        logger.info(f"Panel extraction completed: {result['message']}")
        return result

    except SoftTimeLimitExceeded:
        error_msg = f"Panel extraction task timed out for user_id={user_id}"
        logger.error(error_msg)
        return _handle_panel_extraction_failure(task_id, image_ids, user_id, error_msg)

    except Exception as e:
        error_msg = f"Unexpected error during panel extraction for user_id={user_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)

        # Retry with exponential backoff
        retry_delay = CELERY_RETRY_BACKOFF_BASE ** self.request.retries
        try:
            raise self.retry(exc=e, countdown=retry_delay)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for panel extraction task {task_id}")
            return _handle_panel_extraction_failure(task_id, image_ids, user_id, error_msg)


def _create_panel_document(
    panel_info: Dict[str, Any],
    user_id: str,
    output_dir: str
) -> Dict[str, Any]:
    """Create a MongoDB document for an extracted panel.

    Args:
        panel_info: Dict with panel data from PANELS.csv parsing
        user_id: User who owns this panel
        output_dir: Directory where panel image is stored

    Returns:
        MongoDB document ready to insert
    """
    panel_id = panel_info["panel_id"]
    image_id = panel_info["image_id"]
    panel_type = panel_info["panel_type"]
    bbox = panel_info["bbox"]
    figname = panel_info["figname"]

    # Construct panel image filename and path
    # Panel images are typically named like panel_00001.png from the Docker container
    # But we should also check if the actual file exists
    panel_filename = f"{panel_id}.png"
    panel_file_path = os.path.join(output_dir, panel_filename)

    # Get file size if it exists
    file_size = 0
    if os.path.exists(panel_file_path):
        file_size = os.path.getsize(panel_file_path)
    else:
        # Try alternative naming
        panel_filename = f"panel_{panel_id.split('_')[-1]}.png"
        panel_file_path = os.path.join(output_dir, panel_filename)
        if os.path.exists(panel_file_path):
            file_size = os.path.getsize(panel_file_path)

    panel_doc = {
        "user_id": user_id,
        "filename": panel_filename,
        "file_path": panel_file_path,
        "file_size": file_size,
        "source_type": "panel",
        "source_image_id": image_id,
        "panel_id": panel_id,
        "panel_type": panel_type,
        "bbox": bbox,
        "uploaded_date": datetime.utcnow(),
        "created_at": datetime.utcnow()
    }

    return panel_doc


def _handle_panel_extraction_failure(
    task_id: str,
    image_ids: List[str],
    user_id: str,
    error_message: str
) -> Dict[str, Any]:
    """Handle panel extraction failure.

    Args:
        task_id: Celery task ID
        image_ids: Image IDs that were being processed
        user_id: User ID
        error_message: Error message

    Returns:
        Standardized failure response dict
    """
    logger.error(f"Panel extraction failed for user {user_id}: {error_message}")

    return {
        "task_id": task_id,
        "status": "failed",
        "image_ids": image_ids,
        "extracted_panels_count": 0,
        "result_panel_ids": [],
        "message": f"Panel extraction failed",
        "error": error_message
    }
