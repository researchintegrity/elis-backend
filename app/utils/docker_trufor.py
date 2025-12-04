"""
Docker-based TruFor Detection using trufor container
"""
import subprocess
import os
import logging
from typing import Tuple, Dict, Optional, Callable
from app.config.settings import (
    is_container_path,
    get_container_path_length,
    convert_container_path_to_host,
    TRUFOR_DOCKER_IMAGE,
    TRUFOR_TIMEOUT,
    TRUFOR_USE_GPU,
    resolve_workspace_path,
    CONTAINER_WORKSPACE_PATH,
)
from app.utils.file_storage import get_analysis_output_path
from app.schemas import AnalysisType

logger = logging.getLogger(__name__)

def run_trufor_detection_with_docker(
    analysis_id: str,
    user_id: str,
    image_path: str,
    docker_image: str = None,
    status_callback: Optional[Callable[[str], None]] = None
) -> Tuple[bool, str, Dict]:
    """Run TruFor detection on an image using Docker.

    Args:
        analysis_id: ID of the analysis
        user_id: ID of the user
        image_path: Absolute path to the source image file
        docker_image: Optional custom docker image name
        status_callback: Optional function to call with status updates (str)

    Returns:
        Tuple (success, message, results)
        results is a dict containing paths to the generated images
    """
    results = {}
    
    if docker_image is None:
        docker_image = TRUFOR_DOCKER_IMAGE

    if not os.path.exists(image_path):
        # Try to resolve path using centralized utility
        resolved_path = resolve_workspace_path(image_path)
        if os.path.exists(resolved_path):
            image_path = resolved_path
        else:
            return False, f"Source image file not found: {image_path}", results
    
    # Ensure absolute path
    image_path = os.path.abspath(image_path)

    # Setup paths
    image_dir = os.path.dirname(image_path)
    image_filename = os.path.basename(image_path)
    
    # Get dedicated output directory
    try:
        output_dir_relative = get_analysis_output_path(user_id, analysis_id, AnalysisType.TRUFOR)
        output_dir_path = os.path.abspath(output_dir_relative)
    except Exception as e:
        return False, f"Failed to create output directory: {str(e)}", results

    # Handle Docker path conversion (Host vs Container)
    host_image_dir = image_dir
    host_output_dir = output_dir_path
    
    host_workspace_path = os.getenv("HOST_WORKSPACE_PATH")
    container_path_len = get_container_path_length()
    
    if is_container_path(image_dir):
        logger.info(f"Detected container environment. Converting paths for host Docker daemon")
        
        if not host_workspace_path:
            return False, "HOST_WORKSPACE_PATH environment variable not set", results
        
        rel_path = image_dir[container_path_len:]
        host_image_dir = host_workspace_path.rstrip('/') + '/' + rel_path.lstrip('/')
        
        if is_container_path(output_dir_path):
            rel_out_path = output_dir_path[container_path_len:]
            host_output_dir = host_workspace_path.rstrip('/') + '/' + rel_out_path.lstrip('/')

    # Construct Docker command
    container_input_path = f"/data/{image_filename}"
    container_output_path = "/data_out"
    
    cmd = ["docker", "run", "--rm"]
    
    if TRUFOR_USE_GPU:
        cmd.extend(["--runtime=nvidia", "--gpus", "all"])
        
    cmd.extend([
        "-v", f"{host_image_dir}:/data",
        "-v", f"{host_output_dir}:/data_out",
        docker_image
    ])
    
    if TRUFOR_USE_GPU:
        cmd.extend(["-gpu", "0"])
    else:
        cmd.extend(["-gpu", "-1"])
        
    cmd.extend([
        "-in", container_input_path,
        "-out", container_output_path,
        "--timeout", str(TRUFOR_TIMEOUT)
    ])

    logger.info(f"Running TruFor detection: {' '.join(cmd)}")

    try:
        # Use Popen to capture output in real-time
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Read stdout for status updates
        stdout_lines = []
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                stdout_lines.append(line)
                line = line.strip()
                if line.startswith("[STATUS]"):
                    status_msg = line.replace("[STATUS]", "").strip()
                    logger.info(f"TruFor Status: {status_msg}")
                    if status_callback:
                        status_callback(status_msg)
        
        # Get remaining output and stderr
        stdout_rest, stderr = process.communicate()
        if stdout_rest:
            stdout_lines.append(stdout_rest)
            
        if process.returncode != 0:
            logger.error(f"Docker command failed: {stderr}")
            if "Unknown runtime specified nvidia" in stderr:
                 return False, "GPU runtime not available. TruFor requires NVIDIA GPU.", results
            return False, f"Detection failed: {stderr}", results

        # Check output
        # We expect {basename}_trufor_result.png
        basename = os.path.splitext(image_filename)[0]
        expected_output = f"{basename}_trufor_result.png"
        output_path = os.path.join(output_dir_path, expected_output)
        
        if os.path.exists(output_path):
            results['visualization'] = convert_container_path_to_host(output_path)
            return True, "Analysis completed successfully", results
        else:
            # Check if any file was created
            files = os.listdir(output_dir_path)
            if files:
                # Maybe filename mismatch?
                logger.warning(f"Expected {expected_output} but found {files}")
                results['files'] = [convert_container_path_to_host(os.path.join(output_dir_path, f)) for f in files]
                return True, "Analysis completed (filename mismatch?)", results
            
            return False, "Analysis completed but no output file found.", results

    except Exception as e:
        logger.exception("Unexpected error during TruFor detection")
        return False, f"System error: {str(e)}", results
