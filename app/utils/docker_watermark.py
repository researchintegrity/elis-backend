"""
Docker-based PDF watermark removal using pdf-watermark-removal container
"""
import subprocess
import os
import logging
from typing import Tuple, Dict
from app.config.settings import (
    DOCKER_EXTRACTION_TIMEOUT,
    is_container_path,
    get_container_path_length,
    PDF_WATERMARK_REMOVAL_DOCKER_IMAGE,
    WATERMARK_REMOVAL_OUTPUT_SUFFIX_TEMPLATE,
    WATERMARK_REMOVAL_DOCKER_WORKDIR,
    resolve_workspace_path,
    CONTAINER_WORKSPACE_PATH,
)

logger = logging.getLogger(__name__)


def remove_watermark_with_docker(
    doc_id: str,
    user_id: str,
    pdf_file_path: str,
    aggressiveness_mode: int = 2,
    docker_image: str = None
) -> Tuple[bool, str, Dict]:
    """Remove watermark from PDF using Docker container.

    Runs the ``pdf-watermark-removal`` Docker container to remove watermarks from a
    PDF file. The container will process the PDF and save the cleaned version to the
    output directory.

    Docker command example::

        docker run \
            -v $(pwd):/workspace \
            pdf-watermark-removal:latest \
            -i /workspace/input.pdf \
            -o /workspace/output.pdf \
            -m 2

    Args:
        doc_id: Document ID for tracking
        user_id: User ID for workspace organization
        pdf_file_path: Full path to the PDF file
        aggressiveness_mode: Watermark removal aggressiveness (1, 2, or 3)
            1 = explicit watermarks only
            2 = text + repeated graphics (default)
            3 = all graphics (most aggressive)
        docker_image: Docker image to use (if not provided, uses configured default)

    Returns:
        Tuple of (success, status_message, output_file_info)
        - success: Boolean indicating if removal was successful
        - status_message: Human-readable status or error message
        - output_file_info: Dict with file info {filename, path, size, status}

    Notes:
        Errors are returned in the tuple instead of being raised so callers can
        handle failures consistently.
    """
    output_file_info = {}
    
    # Use default Docker image if not specified
    if docker_image is None:
        docker_image = PDF_WATERMARK_REMOVAL_DOCKER_IMAGE
    
    # Validate aggressiveness mode
    if aggressiveness_mode not in [1, 2, 3]:
        error_msg = f"Invalid aggressiveness mode: {aggressiveness_mode}. Must be 1, 2, or 3."
        logger.error(error_msg)
        return False, error_msg, output_file_info
    
    try:
        # Validate PDF file exists
        if not os.path.exists(pdf_file_path):
            # Try to resolve path using centralized utility
            resolved_path = resolve_workspace_path(pdf_file_path)
            if os.path.exists(resolved_path):
                pdf_file_path = resolved_path
            else:
                error_msg = f"PDF file not found: {pdf_file_path}"
                logger.error(error_msg)
                return False, error_msg, output_file_info
        
        # Convert to absolute paths for Docker
        pdf_file_path = os.path.abspath(pdf_file_path)
        
        # Get output filename (add suffix to avoid replacing original)
        pdf_filename = os.path.basename(pdf_file_path)
        pdf_name_without_ext = os.path.splitext(pdf_filename)[0]
        # Use suffix template from settings so filename patterns are configurable
        output_filename = f"{pdf_name_without_ext}{WATERMARK_REMOVAL_OUTPUT_SUFFIX_TEMPLATE.format(mode=aggressiveness_mode)}"
        
        # Output will be in same directory as input
        output_dir = os.path.dirname(pdf_file_path)
        output_file_path = os.path.join(output_dir, output_filename)
        
        logger.info(
            f"Watermark removal starting for doc_id={doc_id}, user_id={user_id}\n"
            f"  Input PDF path: {pdf_file_path}\n"
            f"  Output PDF path: {output_file_path}\n"
            f"  Aggressiveness mode: {aggressiveness_mode}\n"
            f"  Docker image: {docker_image}\n"
            f"  is_container_path: {is_container_path(output_dir)}\n"
            f"  CONTAINER_WORKSPACE_PATH: {CONTAINER_WORKSPACE_PATH}"
        )
        
        # Get the directory containing the PDF
        pdf_dir = os.path.dirname(pdf_file_path)
        
        # Handle Docker running inside a container vs on the host:
        # 
        # In host environment:
        #   - pdf_file_path will be relative or absolute to host
        #   - We pass it directly to Docker since Docker daemon is on same host
        #
        # In container environment (Celery worker in Docker):
        #   - pdf_file_path will be like "/workspace/user/pdfs/file.pdf"
        #   - Docker daemon is on the host, needs the actual host path
        #   - We need to convert using HOST_WORKSPACE_PATH environment variable
        
        host_pdf_dir = pdf_dir
        
        # If path starts with /workspace, we're in the worker container
        host_workspace_path = os.getenv("HOST_WORKSPACE_PATH")
        container_path_len = get_container_path_length()
        
        if is_container_path(pdf_dir):
            # We're running in the worker container, need to convert paths for Docker daemon on host
            logger.info(f"Detected container environment. Converting paths for host Docker daemon")
            
            if not host_workspace_path:
                error_msg = "HOST_WORKSPACE_PATH environment variable not set"
                logger.error(error_msg)
                return False, error_msg, output_file_info
            
            # Convert: /workspace/user_id/pdfs/... → /host/path/workspace/user_id/pdfs/...
            rel_path = pdf_dir[container_path_len:]  # Remove /workspace prefix
            host_pdf_dir = host_workspace_path + rel_path
            
            logger.debug(
                f"Container path conversion:\n"
                f"  Original PDF dir: {pdf_dir}\n"
                f"  Relative path: {rel_path}\n"
                f"  HOST_WORKSPACE_PATH: {host_workspace_path}\n"
                f"  Host PDF dir: {host_pdf_dir}"
            )
        
        # Construct Docker command (mount host pdf_dir to container workdir)
        docker_command = [
            "docker",
            "run",
            "--rm",
            "-v", f"{host_pdf_dir}:{WATERMARK_REMOVAL_DOCKER_WORKDIR}",
            docker_image,
            "-i", f"{WATERMARK_REMOVAL_DOCKER_WORKDIR}/{pdf_filename}",
            "-o", f"{WATERMARK_REMOVAL_DOCKER_WORKDIR}/{output_filename}",
            "-m", str(aggressiveness_mode)
        ]
        
        logger.info(f"Docker command: {' '.join(docker_command)}")
        
        # Execute Docker command
        try:
            result = subprocess.run(
                docker_command,
                timeout=DOCKER_EXTRACTION_TIMEOUT,
                capture_output=True,
                text=True,
                check=False  # Don't raise exception on non-zero exit
            )
            
            logger.info(f"Docker stdout: {result.stdout}")
            if result.stderr:
                logger.warning(f"Docker stderr: {result.stderr}")
            
            # Check if output file was created
            if os.path.exists(output_file_path):
                output_file_size = os.path.getsize(output_file_path)
                
                output_file_info = {
                    "filename": output_filename,
                    "path": output_file_path,
                    "size": output_file_size,
                    "status": "completed",
                    "aggressiveness_mode": aggressiveness_mode
                }
                
                success_msg = (
                    f"Watermark removal successful for doc_id={doc_id}. "
                    f"Output: {output_filename} ({output_file_size} bytes)"
                )
                logger.info(success_msg)
                return True, success_msg, output_file_info
            else:
                error_msg = f"Docker did not produce output file: {output_file_path}"
                logger.error(error_msg)
                logger.error(f"Docker exit code: {result.returncode}")
                return False, error_msg, output_file_info
        
        except subprocess.TimeoutExpired:
            error_msg = (
                f"Watermark removal timed out after {DOCKER_EXTRACTION_TIMEOUT} seconds "
                f"for doc_id={doc_id}"
            )
            logger.error(error_msg)
            return False, error_msg, output_file_info
        
        except Exception as e:
            error_msg = f"Docker execution error for doc_id={doc_id}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, output_file_info
    
    except Exception as e:
        error_msg = f"Unexpected error during watermark removal for doc_id={doc_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg, output_file_info
