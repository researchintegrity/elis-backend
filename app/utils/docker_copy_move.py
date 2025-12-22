"""
Docker-based Copy-Move Detection supporting both Dense and Keypoint methods.

Dense Method: Uses block-matching algorithm (copy-move-detection container)
Keypoint Method: Uses keypoint-based matching (copy-move-detection-keypoint container)
"""
import subprocess
import os
import logging
from typing import Tuple, Dict
from pathlib import Path
from app.config.settings import (
    convert_host_path_to_container,
    is_container_path,
    convert_container_path_to_host,
    COPY_MOVE_DETECTION_DOCKER_IMAGE,
    COPY_MOVE_DETECTION_TIMEOUT,
    COPY_MOVE_KEYPOINT_DOCKER_IMAGE,
    COPY_MOVE_KEYPOINT_TIMEOUT,
    CONTAINER_WORKSPACE_PATH,
    HOST_WORKSPACE_PATH
)
from app.utils.file_storage import get_analysis_output_path

logger = logging.getLogger(__name__)

# Detection method constants
METHOD_DENSE = "dense"
METHOD_KEYPOINT = "keypoint"


def _setup_paths(
    user_id: str,
    analysis_id: str,
    analysis_type: str,
    image_path: str,
    target_image_path: str = None
) -> Tuple[bool, str, Dict]:
    """
    Setup and validate paths for copy-move detection.
    
    Returns:
        Tuple (success, error_message, paths_dict)
    """
    paths = {}
    
    if not os.path.exists(image_path):
        return False, f"Source image file not found: {image_path}", paths
    
    if target_image_path and not os.path.exists(target_image_path):
        return False, f"Target image file not found: {target_image_path}", paths
    
    # Ensure absolute paths
    image_path = os.path.abspath(image_path)
    if target_image_path:
        target_image_path = os.path.abspath(target_image_path)
    
    # Setup path info
    paths['image_path'] = image_path
    paths['image_dir'] = os.path.dirname(image_path)
    paths['image_filename'] = os.path.basename(image_path)
    
    if target_image_path:
        paths['target_image_path'] = target_image_path
        paths['target_image_dir'] = os.path.dirname(target_image_path)
        paths['target_image_filename'] = os.path.basename(target_image_path)
    
    # Get dedicated output directory
    try:
        output_dir_relative = get_analysis_output_path(user_id, analysis_id, analysis_type)
        paths['output_dir_path'] = os.path.abspath(output_dir_relative)
    except Exception as e:
        return False, f"Failed to create output directory: {str(e)}", paths
    
    # Handle Docker path conversion (Host vs Container)
    paths['host_image_dir'] = paths['image_dir']
    paths['host_target_image_dir'] = paths.get('target_image_dir')
    paths['host_output_dir'] = paths['output_dir_path']
    
    # Check if we are running in a container environment
    is_container_env = (
        is_container_path(Path(paths['image_dir'])) or
        (str(HOST_WORKSPACE_PATH) and paths['image_dir'].startswith(str(CONTAINER_WORKSPACE_PATH)))
    )
    
    if is_container_env:
        logger.info("Detected container environment. Converting paths for host Docker daemon")
        
        if not str(HOST_WORKSPACE_PATH):
            if paths['image_dir'].startswith(str(CONTAINER_WORKSPACE_PATH)):
                return False, "HOST_WORKSPACE_PATH environment variable not set", paths
        
        # Convert container paths to host paths
        if is_container_path(Path(paths['image_dir'])):
            paths['host_image_dir'] = str(convert_container_path_to_host(Path(paths['image_dir'])))
        
        if paths.get('target_image_dir') and is_container_path(Path(paths['target_image_dir'])):
            paths['host_target_image_dir'] = str(convert_container_path_to_host(Path(paths['target_image_dir'])))
        
        if is_container_path(Path(paths['output_dir_path'])):
            paths['host_output_dir'] = str(convert_container_path_to_host(Path(paths['output_dir_path'])))
    
    # Ensure output directory exists
    os.makedirs(paths['output_dir_path'], exist_ok=True)
    
    return True, "", paths


def _build_dense_docker_command(
    paths: Dict,
    docker_image: str,
    dense_method: int,
    timeout: int
) -> list:
    """Build Docker command for dense method detection."""
    container_input_path = f"/input_vol/{paths['image_filename']}"
    container_output_path = "/output_vol"
    
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{paths['host_image_dir']}:/input_vol",
        "-v", f"{paths['host_output_dir']}:/output_vol"
    ]
    
    if paths.get('target_image_filename'):
        cmd.extend(["-v", f"{paths['host_target_image_dir']}:/target_vol"])
        container_target_path = f"/target_vol/{paths['target_image_filename']}"
    
    cmd.append(docker_image)
    
    # Input arguments
    cmd.extend(["--input", container_input_path])
    if paths.get('target_image_filename'):
        cmd.append(container_target_path)
    
    cmd.extend([
        "--output", container_output_path,
        "--method", str(dense_method),
        "--timeout", str(timeout)
    ])
    
    return cmd


def _build_keypoint_docker_command(
    paths: Dict,
    docker_image: str,
    timeout: int
) -> list:
    """Build Docker command for keypoint method detection."""
    container_input_path = f"/input_vol/{paths['image_filename']}"
    container_output_path = "/output_vol"
    
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{paths['host_image_dir']}:/input_vol",
        "-v", f"{paths['host_output_dir']}:/output_vol"
    ]
    
    if paths.get('target_image_filename'):
        cmd.extend(["-v", f"{paths['host_target_image_dir']}:/target_vol"])
        container_target_path = f"/target_vol/{paths['target_image_filename']}"
    
    cmd.append(docker_image)
    
    # Input arguments - keypoint uses slightly different CLI
    cmd.extend(["--input", container_input_path])
    if paths.get('target_image_filename'):
        cmd.append(container_target_path)
    
    cmd.extend([
        "--output", container_output_path,
        "--timeout", str(timeout)
    ])
    
    return cmd


def _run_docker_detection(
    cmd: list,
    timeout: int,
    paths: Dict
) -> Tuple[bool, str, Dict]:
    """Execute Docker detection command and process results."""
    results = {}
    
    logger.info(f"Running copy-move detection: {' '.join(cmd)}")
    
    try:
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 30  # Add buffer
        )
        
        if process.returncode != 0:
            logger.error(f"Docker command failed: {process.stderr}")
            return False, f"Detection failed: {process.stderr}", results
        
        # Parse output files
        source_base = os.path.splitext(paths['image_filename'])[0]
        
        if paths.get('target_image_filename'):
            target_base = os.path.splitext(paths['target_image_filename'])[0]
            base_name = f"{source_base}_vs_{target_base}"
        else:
            base_name = source_base
        
        matches_filename = f"{base_name}_matches.png"
        clusters_filename = f"{base_name}_clusters.png"
        
        matches_path = os.path.join(paths['output_dir_path'], matches_filename)
        clusters_path = os.path.join(paths['output_dir_path'], clusters_filename)
        
        if os.path.exists(matches_path):
            results['matches_image'] = str(convert_host_path_to_container(matches_path))
        
        if os.path.exists(clusters_path):
            results['clusters_image'] = str(convert_host_path_to_container(clusters_path))
        
        if not results:
            return False, "Analysis completed but no output files were found.", results
        
        return True, "Analysis completed successfully", results
    
    except subprocess.TimeoutExpired:
        return False, "Detection timed out", results
    except Exception as e:
        logger.exception("Unexpected error during copy-move detection")
        return False, f"System error: {str(e)}", results


def run_copy_move_detection_with_docker(
    analysis_id: str,
    analysis_type: str,
    user_id: str,
    image_path: str,
    target_image_path: str = None,
    method: str = METHOD_KEYPOINT,
    dense_method: int = 2,
    docker_image: str = None
) -> Tuple[bool, str, Dict]:
    """Run copy-move detection on an image using Docker.

    Supports two detection methods:
    - 'keypoint': Advanced keypoint-based detection (recommended for cross-image)
    - 'dense': Block-based dense matching (original method)

    Args:
        analysis_id: ID of the analysis
        analysis_type: Type of analysis (single or cross)
        user_id: ID of the user
        image_path: Absolute path to the source image file
        target_image_path: Absolute path to the target image file (for cross-image)
        method: Detection method ('keypoint' or 'dense')
        dense_method: Sub-method for dense detection (1-5), only used when method='dense'
        docker_image: Optional custom docker image name (overrides method selection)

    Returns:
        Tuple (success, message, results)
        results is a dict containing paths to the generated images
    """
    # Setup and validate paths
    success, error_msg, paths = _setup_paths(
        user_id, analysis_id, analysis_type, image_path, target_image_path
    )
    if not success:
        return False, error_msg, {}
    
    # Determine Docker image and timeout based on method
    if docker_image is not None:
        # Custom image override
        selected_image = docker_image
        timeout = COPY_MOVE_DETECTION_TIMEOUT
    elif method == METHOD_KEYPOINT:
        selected_image = COPY_MOVE_KEYPOINT_DOCKER_IMAGE
        timeout = COPY_MOVE_KEYPOINT_TIMEOUT
    else:  # METHOD_DENSE
        selected_image = COPY_MOVE_DETECTION_DOCKER_IMAGE
        timeout = COPY_MOVE_DETECTION_TIMEOUT
    
    # Build Docker command based on method
    if method == METHOD_KEYPOINT and docker_image is None:
        cmd = _build_keypoint_docker_command(paths, selected_image, timeout)
    else:
        cmd = _build_dense_docker_command(paths, selected_image, dense_method, timeout)
    
    # Execute detection
    return _run_docker_detection(cmd, timeout, paths)


# Legacy compatibility function
def run_dense_copy_move_detection(
    analysis_id: str,
    analysis_type: str,
    user_id: str,
    image_path: str,
    target_image_path: str = None,
    method: int = 2
) -> Tuple[bool, str, Dict]:
    """Legacy wrapper for dense-only detection (backward compatibility).
    
    Deprecated: Use run_copy_move_detection_with_docker with method='dense' instead.
    """
    return run_copy_move_detection_with_docker(
        analysis_id=analysis_id,
        analysis_type=analysis_type,
        user_id=user_id,
        image_path=image_path,
        target_image_path=target_image_path,
        method=METHOD_DENSE,
        dense_method=method
    )
