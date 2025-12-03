"""
Application-wide configuration settings

This module centralizes all hardcoded configuration values to make the
application more maintainable and configurable. All magic numbers and
strings are defined here as constants.

To customize settings:
1. Modify the constants below
2. Import from this module in your code
3. No need to change multiple files
"""

import os
from pathlib import Path

# ============================================================================
# FILE STORAGE SETTINGS
# ============================================================================

# Base directory for all user uploads and workspace files
UPLOAD_DIR = Path("workspace")

# ============================================================================
# EXTRACTION SETTINGS
# ============================================================================

# Docker image for PDF extraction
PDF_EXTRACTOR_DOCKER_IMAGE = "pdf-extractor:latest"

# Docker image for PDF watermark removal (system_modules/watermark-removal)
PDF_WATERMARK_REMOVAL_DOCKER_IMAGE = "pdf-watermark-removal:latest"

# Template for output filename suffix when creating watermark-removed PDFs.
# Use format placeholder `{mode}` for aggressiveness mode.
WATERMARK_REMOVAL_OUTPUT_SUFFIX_TEMPLATE = "_watermark_removed_m{mode}.pdf"

# Working directory inside the watermark-removal Docker container
WATERMARK_REMOVAL_DOCKER_WORKDIR = "/workspace"

# Docker image for panel extraction (system_modules/panel-extractor)
PANEL_EXTRACTOR_DOCKER_IMAGE = "panel-extractor:latest"

# Working directory inside the panel-extractor Docker container
PANEL_EXTRACTION_DOCKER_WORKDIR = "/workspace"

# Panel extraction settings
PANEL_EXTRACTION_TIMEOUT = 600  # 10 minutes (panel extraction can take longer)
MAX_IMAGES_PER_EXTRACTION = 20  # Maximum number of images to process in one batch

# Docker image for Copy-Move Detection (system_modules/copy-move-detection)
COPY_MOVE_DETECTION_DOCKER_IMAGE = "copy-move-detection:latest"
COPY_MOVE_DETECTION_TIMEOUT = 600  # 10 minutes
COPY_MOVE_DETECTION_DOCKER_WORKDIR = "/workspace"

# Docker image for TruFor Detection (system_modules/TruFor)
TRUFOR_DOCKER_IMAGE = "trufor:latest"
TRUFOR_TIMEOUT = 600  # 10 minutes
TRUFOR_DOCKER_WORKDIR = "/workspace"
TRUFOR_USE_GPU = os.getenv("TRUFOR_USE_GPU", "true").lower() == "true"

# ============================================================================
# CBIR (Content-Based Image Retrieval) SETTINGS
# ============================================================================
# When running inside Docker, use container name 'cbir-service'
# When running locally, use 'localhost:8001'
# The CBIR_SERVICE_HOST is the hostname/IP of the CBIR microservice
CBIR_SERVICE_HOST = os.getenv("CBIR_SERVICE_HOST", "localhost")
CBIR_SERVICE_PORT = int(os.getenv("CBIR_SERVICE_PORT", "8001"))
CBIR_SERVICE_URL = os.getenv(
    "CBIR_SERVICE_URL",
    f"http://{CBIR_SERVICE_HOST}:{CBIR_SERVICE_PORT}"
)
CBIR_TIMEOUT = int(os.getenv("CBIR_TIMEOUT", "120"))  # 2 minutes default

# ============================================================================
# PROVENANCE ANALYSIS SETTINGS
# ============================================================================
# When running inside Docker, use container name 'provenance-service'
# When running locally, use 'localhost:8002'
PROVENANCE_SERVICE_HOST = os.getenv("PROVENANCE_SERVICE_HOST", "localhost")
PROVENANCE_SERVICE_PORT = int(os.getenv("PROVENANCE_SERVICE_PORT", "8002"))
PROVENANCE_SERVICE_URL = os.getenv(
    "PROVENANCE_SERVICE_URL",
    f"http://{PROVENANCE_SERVICE_HOST}:{PROVENANCE_SERVICE_PORT}"
)
PROVENANCE_TIMEOUT = int(os.getenv("PROVENANCE_TIMEOUT", "600"))  # 10 minutes default

# Extraction timeouts (in seconds)
DOCKER_EXTRACTION_TIMEOUT = 300  # 5 minutes
DOCKER_COMPOSE_EXTRACTION_TIMEOUT = 300  # 5 minutes
DOCKER_IMAGE_CHECK_TIMEOUT = 10  # Check if image exists

# Path constants
APP_WORKSPACE_PREFIX = "/app/workspace"
EXTRACTION_SUBDIRECTORY = "images/extracted"

# ============================================================================
# CELERY TASK SETTINGS
# ============================================================================

# Task timing (in seconds)
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes soft limit
CELERY_TASK_DEFAULT_RETRY_DELAY = 60  # 1 minute

# Task retries
CELERY_MAX_RETRIES = 3
CELERY_RETRY_BACKOFF_BASE = 2  # Exponential backoff multiplier

# Result settings
CELERY_RESULT_EXPIRES = 3600  # 1 hour

# Redis connection timeouts
CELERY_REDIS_SOCKET_CONNECT_TIMEOUT = 5
CELERY_REDIS_SOCKET_TIMEOUT = 5

# ============================================================================
# FILE STORAGE SETTINGS
# ============================================================================

# Workspace root directory (can be overridden by environment variable)
WORKSPACE_ROOT = os.getenv("WORKSPACE_PATH", os.path.abspath("workspace"))

# Supported image file extensions for extraction
SUPPORTED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.tiff', '.bmp')

# MIME type mappings for extracted images
IMAGE_MIME_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.tiff': 'image/tiff',
    '.bmp': 'image/bmp'
}

# ============================================================================
# USER VALIDATION SETTINGS
# ============================================================================

# Username constraints
USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 50

# Password constraints
PASSWORD_MIN_LENGTH = 4

# Full name constraints
FULL_NAME_MAX_LENGTH = 100

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_extraction_path_template() -> str:
    """
    Get the path template for extracted images
    
    Returns:
        Template string: {user_id}/images/extracted/{doc_id}/{filename}
    """
    return f"{{user_id}}/{EXTRACTION_SUBDIRECTORY}/{{doc_id}}/{{filename}}"


def get_container_path_prefix() -> str:
    """
    Get the prefix used for container paths (for path detection)
    
    Returns:
        Container path prefix: /app/workspace
    """
    return APP_WORKSPACE_PREFIX


def is_container_path(path: str) -> bool:
    """
    Check if a path is running inside a container
    
    Args:
        path: File path to check
        
    Returns:
        True if path starts with container prefix, False otherwise
    """
    return path.startswith(APP_WORKSPACE_PREFIX)


def get_container_path_length() -> int:
    """
    Get the length of the container path prefix (for string slicing)
    
    Returns:
        Length of /app/workspace
    """
    return len(APP_WORKSPACE_PREFIX)


def convert_container_path_to_host(container_path: str) -> str:
    """
    Convert a container path to a relative workspace path.
    
    Args:
        container_path: Path inside container (starts with /app/workspace)
        
    Returns:
        Relative path from workspace root (without WORKSPACE_ROOT prefix)
        
    Examples:
        /app/workspace/user_id/images/... → workspace/user_id/images/...
    """
    if is_container_path(container_path):
        # Remove /app/workspace prefix, leaving just the relative path
        rel_path = container_path[get_container_path_length():]  # Removes /app/workspace
        # Add 'workspace' prefix back to create workspace-relative path
        return "workspace" + rel_path
    return container_path
