"""
Docker-based Copy-Move Detection using copy-move-detection container
"""
import subprocess
import os
import logging
from typing import Tuple, Dict
from app.config.settings import (
    is_container_path,
    get_container_path_length,
    convert_container_path_to_host,
    COPY_MOVE_DETECTION_DOCKER_IMAGE,
    COPY_MOVE_DETECTION_TIMEOUT,
)
from app.utils.file_storage import get_analysis_output_path
from app.schemas import AnalysisType

logger = logging.getLogger(__name__)


def run_copy_move_detection_with_docker(
    analysis_id: str,
    analysis_type: str,
    user_id: str,
    image_path: str,
    target_image_path: str = None,
    method: int = 2,
    docker_image: str = None
) -> Tuple[bool, str, Dict]:
    """Run copy-move detection on an image using Docker.

    Args:
        analysis_id: ID of the analysis
        analysis_type: Type of analysis (single or cross)
        user_id: ID of the user
        image_path: Absolute path to the source image file
        target_image_path: Absolute path to the target image file (for cross-image)
        method: Detection method (1-5)
        docker_image: Optional custom docker image name

    Returns:
        Tuple (success, message, results)
        results is a dict containing paths to the generated images
    """
    results = {}
    
    if docker_image is None:
        docker_image = COPY_MOVE_DETECTION_DOCKER_IMAGE

    if not os.path.exists(image_path):
        return False, f"Source image file not found: {image_path}", results
    
    if target_image_path and not os.path.exists(target_image_path):
        return False, f"Target image file not found: {target_image_path}", results

    # Ensure absolute path for correct container path detection
    image_path = os.path.abspath(image_path)
    if target_image_path:
        target_image_path = os.path.abspath(target_image_path)

    # Setup paths
    image_dir = os.path.dirname(image_path)
    image_filename = os.path.basename(image_path)
    
    target_image_dir = None
    target_image_filename = None
    if target_image_path:
        target_image_dir = os.path.dirname(target_image_path)
        target_image_filename = os.path.basename(target_image_path)
    
    # Get dedicated output directory: workspace/{user_id}/analyses/{type}/{analysis_id}
    try:
        output_dir_relative = get_analysis_output_path(user_id, analysis_id, analysis_type)
        output_dir_path = os.path.abspath(output_dir_relative)
    except Exception as e:
        return False, f"Failed to create output directory: {str(e)}", results

    # Handle Docker path conversion (Host vs Container)
    host_image_dir = image_dir
    host_target_image_dir = target_image_dir
    host_output_dir = output_dir_path
    
    # If path starts with /app/workspace, we're in the worker container
    workspace_path = os.getenv("WORKSPACE_PATH")
    container_path_len = get_container_path_length()
    
    if is_container_path(image_dir):
        logger.info(f"Detected container environment. Converting paths for host Docker daemon")
        
        if not workspace_path:
            return False, "WORKSPACE_PATH environment variable not set", results
        
        # Convert input path: /app/workspace/... -> /host/path/workspace/...
        rel_path = image_dir[container_path_len:]
        # Ensure workspace_path doesn't end with / and rel_path starts with /
        host_image_dir = workspace_path.rstrip('/') + '/' + rel_path.lstrip('/')
        
        if target_image_dir:
            if is_container_path(target_image_dir):
                rel_target_path = target_image_dir[container_path_len:]
                host_target_image_dir = workspace_path.rstrip('/') + '/' + rel_target_path.lstrip('/')
            else:
                # If target is not in workspace (unlikely but possible), keep as is?
                # Assuming all images are in workspace for now
                host_target_image_dir = target_image_dir
        
        # Convert output path: /app/workspace/... -> /host/path/workspace/...
        # Note: output_dir_path is absolute, so it starts with /app/workspace if in container
        if is_container_path(output_dir_path):
            rel_out_path = output_dir_path[container_path_len:]
            host_output_dir = workspace_path.rstrip('/') + '/' + rel_out_path.lstrip('/')

    # Construct Docker command
    # We mount:
    # 1. Input directory (read-only recommended but script might not care) -> /input_vol
    # 2. Output directory -> /output_vol
    # 3. Target directory (if cross) -> /target_vol
    
    container_input_path = f"/input_vol/{image_filename}"
    container_output_path = "/output_vol"
    
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{host_image_dir}:/input_vol",
        "-v", f"{host_output_dir}:/output_vol"
    ]
    
    if target_image_path:
        # If target is in same dir as source, we can reuse input_vol, but safer to mount separately
        # in case they are in different folders
        cmd.extend(["-v", f"{host_target_image_dir}:/target_vol"])
        container_target_path = f"/target_vol/{target_image_filename}"
    
    cmd.append(docker_image)
    
    # Input arguments
    cmd.append("--input")
    cmd.append(container_input_path)
    if target_image_path:
        cmd.append(container_target_path)
        
    cmd.extend([
        "--output", container_output_path,
        "--method", str(method),
        "--timeout", str(COPY_MOVE_DETECTION_TIMEOUT)
    ])

    logger.info(f"Running copy-move detection: {' '.join(cmd)}")

    try:
        # Run Docker command
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=COPY_MOVE_DETECTION_TIMEOUT + 30 # Add buffer
        )

        if process.returncode != 0:
            logger.error(f"Docker command failed: {process.stderr}")
            return False, f"Detection failed: {process.stderr}", results

        # Check if output files exist
        # The script generates {basename}_matches.png and {basename}_clusters.png
        # inside the output directory.
        
        source_base = os.path.splitext(image_filename)[0]
        
        if target_image_filename:
            target_base = os.path.splitext(target_image_filename)[0]
            base_name = f"{source_base}_vs_{target_base}"
        else:
            base_name = source_base

        matches_filename = f"{base_name}_matches.png"
        clusters_filename = f"{base_name}_clusters.png"
        
        matches_path = os.path.join(output_dir_path, matches_filename)
        clusters_path = os.path.join(output_dir_path, clusters_filename)
        
        if os.path.exists(matches_path):
            # Convert absolute container path to relative workspace path
            # e.g. /app/workspace/user/cmfd/img.png -> workspace/user/cmfd/img.png
            results['matches_image'] = convert_container_path_to_host(matches_path)
        
        if os.path.exists(clusters_path):
            results['clusters_image'] = convert_container_path_to_host(clusters_path)
            
        if not results:
             return False, "Analysis completed but no output files were found.", results

        return True, "Analysis completed successfully", results

    except subprocess.TimeoutExpired:
        return False, "Detection timed out", results
    except Exception as e:
        logger.exception("Unexpected error during copy-move detection")
        return False, f"System error: {str(e)}", results
