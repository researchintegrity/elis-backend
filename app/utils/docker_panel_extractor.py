"""
Docker-based panel extraction using panel-extractor container

Extracts individual panels from images using YOLO-based panel detection.
Outputs extracted panel images and a PANELS.csv file mapping panels to source images
with bounding box coordinates and classifications.
"""
import subprocess
import os
import csv
import logging
from typing import Tuple, Dict, List, Any
from app.config.settings import (
    DOCKER_EXTRACTION_TIMEOUT,
    is_container_path,
    get_container_path_length,
    PANEL_EXTRACTOR_DOCKER_IMAGE,
    PANEL_EXTRACTION_DOCKER_WORKDIR,
    resolve_workspace_path,
)

logger = logging.getLogger(__name__)


def extract_panels_with_docker(
    image_ids: List[str],
    user_id: str,
    image_paths: List[str],
    docker_image: str = None
) -> Tuple[bool, str, Dict]:
    """Extract panels from images using Docker container.

    Runs the ``panel-extractor`` Docker container to detect and extract individual
    panels from images. The container outputs extracted panel images and a PANELS.csv
    file with metadata.

    Docker command example::

        docker run \\
            -v /host/path/workspace/user_id/images:/workspace/images \\
            -v /host/path/workspace/user_id/images/panels:/workspace/output \\
            panel-extractor:latest \\
            --input /workspace/images \\
            --output /workspace/output

    Args:
        image_ids: List of MongoDB image document IDs being processed
        user_id: User ID for workspace organization
        image_paths: List of full paths to image files to process
        docker_image: Docker image to use (if not provided, uses configured default)

    Returns:
        Tuple of (success, status_message, output_info)
        - success: Boolean indicating if extraction was successful
        - status_message: Human-readable status or error message
        - output_info: Dict with extraction info {
            panels_count, panels_csv_path, output_dir, panels_data
          }

    Notes:
        The PANELS.csv file contains columns:
        - FIGNAME: Basename of source image
        - PANEL_ID: Unique panel identifier
        - LABEL: Panel type/classification (Blots, Graphs, etc.)
        - X0, Y0, X1, Y1: Bounding box coordinates

        Errors are returned in the tuple instead of being raised so callers can
        handle failures consistently.
    """
    output_info = {}

    # Use default Docker image if not specified
    if docker_image is None:
        docker_image = PANEL_EXTRACTOR_DOCKER_IMAGE

    try:
        # Validate inputs
        if not image_paths:
            error_msg = "No image paths provided"
            logger.error(error_msg)
            return False, error_msg, output_info

        if len(image_paths) != len(image_ids):
            error_msg = f"Mismatch between image_ids ({len(image_ids)}) and image_paths ({len(image_paths)})"
            logger.error(error_msg)
            return False, error_msg, output_info

        # Validate all image files exist
        for i, path in enumerate(image_paths):
            if not os.path.exists(path):
                # Try to resolve path using centralized utility
                resolved_path = resolve_workspace_path(path)
                if os.path.exists(resolved_path):
                    image_paths[i] = resolved_path
                else:
                    error_msg = f"Image file not found: {path}"
                    logger.error(error_msg)
                    return False, error_msg, output_info

        # Convert to absolute paths
        image_paths = [os.path.abspath(p) for p in image_paths]

        # Get the input directory (all images should be in same directory)
        input_dir = os.path.dirname(image_paths[0])

        # Verify all images are in the same directory
        for path in image_paths:
            if os.path.dirname(path) != input_dir:
                error_msg = f"All images must be in the same directory. Got: {input_dir} and {os.path.dirname(path)}"
                logger.error(error_msg)
                return False, error_msg, output_info

        # Create output directory for panels, organized by source image
        # Structure: /workspace/{user_id}/images/panels/{source_image_id}/{figname}/
        # All panels should be in user-specific directory, not global location
        
        # Determine workspace root - construct correct path
        # input_dir format: /workspace/{user_id}/images/extracted/{doc_id}
        #             or: /workspace/{user_id}/images/uploaded
        # We need: /workspace/{user_id}/images/panels
        
        # Extract user_id from path: /workspace/{user_id}/images/...
        # Split path and find the user_id (third component after /workspace)
        path_parts = input_dir.split(os.sep)
        
        # Find 'workspace' in path and get the next component (user_id)
        try:
            workspace_idx = path_parts.index('workspace')
            user_id_from_path = path_parts[workspace_idx + 1]
            workspace_root = os.sep.join(path_parts[:workspace_idx + 1])
            workspace_user_dir = os.path.join(workspace_root, user_id_from_path)
        except (ValueError, IndexError) as e:
            error_msg = f"Failed to extract user_id from path {input_dir}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, output_info
        
        output_dir = os.path.join(workspace_user_dir, "images", "panels")
        os.makedirs(output_dir, exist_ok=True)

        logger.info(
            f"Panel extraction starting for user_id={user_id}\n"
            f"  Input directory: {input_dir}\n"
            f"  Output directory: {output_dir}\n"
            f"  Number of images: {len(image_paths)}\n"
            f"  Docker image: {docker_image}\n"
            f"  is_container_path: {is_container_path(input_dir)}\n"
            f"  WORKSPACE_PATH env: {os.getenv('WORKSPACE_PATH')}"
        )

        # Handle Docker running inside a container vs on the host
        host_input_dir = input_dir
        host_output_dir = output_dir

        workspace_path = os.getenv("HOST_WORKSPACE_PATH")
        container_path_len = get_container_path_length()

        if is_container_path(input_dir):
            # We're running in the worker container, need to convert paths for Docker daemon on host
            logger.info(f"Detected container environment. Converting paths for host Docker daemon")

            if not workspace_path:
                error_msg = "HOST_WORKSPACE_PATH environment variable not set"
                logger.error(error_msg)
                return False, error_msg, output_info

            # Convert: /workspace/user_id/... → /host/path/workspace/user_id/...
            rel_input_path = input_dir[container_path_len:]
            rel_output_path = output_dir[container_path_len:]
            host_input_dir = workspace_path + rel_input_path
            host_output_dir = workspace_path + rel_output_path

            logger.debug(
                f"Container path conversion:\n"
                f"  Original input dir: {input_dir}\n"
                f"  Original output dir: {output_dir}\n"
                f"  WORKSPACE_PATH: {workspace_path}\n"
                f"  Host input dir: {host_input_dir}\n"
                f"  Host output dir: {host_output_dir}"
            )

        # Construct Docker command
        # The panel extractor expects: --input-path IMAGE_PATH [IMAGE_PATH ...]
        # and --output-path for the output directory
        image_filenames = [os.path.basename(path) for path in image_paths]
        
        docker_command = [
            "docker",
            "run",
            "--rm",
            "-v", f"{host_input_dir}:{PANEL_EXTRACTION_DOCKER_WORKDIR}/input",
            "-v", f"{host_output_dir}:{PANEL_EXTRACTION_DOCKER_WORKDIR}/output",
            docker_image,
            "--input-path"
        ]
        
        # Add individual image file paths
        for filename in image_filenames:
            docker_command.append(f"{PANEL_EXTRACTION_DOCKER_WORKDIR}/input/{filename}")
        
        # Add output path
        docker_command.extend([
            "--output-path", f"{PANEL_EXTRACTION_DOCKER_WORKDIR}/output"
        ])

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

            # Check for PANELS.csv output
            panels_csv_path = os.path.join(output_dir, "PANELS.csv")

            if not os.path.exists(panels_csv_path):
                error_msg = f"Docker did not produce PANELS.csv: {panels_csv_path}"
                logger.error(error_msg)
                logger.error(f"Docker exit code: {result.returncode}")
                return False, error_msg, output_info

            # Parse PANELS.csv to extract panel metadata
            try:
                panels_data = _parse_panels_csv(
                    panels_csv_path,
                    image_paths,
                    image_ids
                )
            except Exception as e:
                error_msg = f"Error parsing PANELS.csv: {str(e)}"
                logger.error(error_msg, exc_info=True)
                return False, error_msg, output_info

            output_info = {
                "panels_count": len(panels_data),
                "panels_csv_path": panels_csv_path,
                "output_dir": output_dir,
                "panels_data": panels_data,
                "status": "completed"
            }

            success_msg = (
                f"Panel extraction successful for user_id={user_id}. "
                f"Extracted {len(panels_data)} panels"
            )
            logger.info(success_msg)
            return True, success_msg, output_info

        except subprocess.TimeoutExpired:
            error_msg = (
                f"Panel extraction timed out after {DOCKER_EXTRACTION_TIMEOUT} seconds "
                f"for user_id={user_id}"
            )
            logger.error(error_msg)
            return False, error_msg, output_info

        except Exception as e:
            error_msg = f"Docker execution error for user_id={user_id}: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, output_info

    except Exception as e:
        error_msg = f"Unexpected error during panel extraction for user_id={user_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg, output_info


def _parse_panels_csv(
    csv_path: str,
    image_paths: List[str],
    image_ids: List[str]
) -> List[Dict[str, Any]]:
    """Parse PANELS.csv and map FIGNAME to image IDs.

    Maps the FIGNAME column (source image basename) to the corresponding
    MongoDB image ID from the provided lists.

    Args:
        csv_path: Path to PANELS.csv file
        image_paths: List of image file paths
        image_ids: List of corresponding MongoDB image IDs

    Returns:
        List of panel dictionaries with parsed data:
        {
            "figname": str,
            "image_id": str,
            "panel_id": str,
            "panel_type": str,
            "bbox": {"x0": float, "y0": float, "x1": float, "y1": float}
        }

    Raises:
        ValueError: If FIGNAME cannot be matched to any image_id
        KeyError: If required columns are missing from CSV
    """
    # Build mapping from filename stem (without extension) to image_id
    # The CSV FIGNAME column contains stems like "1763554812_fig1"
    # but image filenames include extensions like "1763554812_fig1.jpg"
    filename_to_id = {}
    filename_stem_to_id = {}
    for path, img_id in zip(image_paths, image_ids):
        filename = os.path.basename(path)
        filename_to_id[filename] = img_id
        # Also add the stem (filename without extension) for matching FIGNAME
        filename_stem = os.path.splitext(filename)[0]
        filename_stem_to_id[filename_stem] = img_id

    logger.debug(f"Filename to image_id mapping: {filename_to_id}")
    logger.debug(f"Filename stem to image_id mapping: {filename_stem_to_id}")

    panels_data = []

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError("PANELS.csv is empty or has no header")

        # Validate required columns
        # Note: The actual CSV uses 'ID' not 'PANEL_ID', and 'LABEL' for panel type classification
        required_columns = {'FIGNAME', 'ID', 'LABEL', 'X0', 'Y0', 'X1', 'Y1'}
        if not required_columns.issubset(set(reader.fieldnames)):
            raise KeyError(f"PANELS.csv missing required columns. Expected: {required_columns}, Got: {set(reader.fieldnames)}")

        for row_num, row in enumerate(reader, start=2):  # Start at 2 (after header)
            try:
                figname = row['FIGNAME'].strip()
                logger.debug(f"Row {row_num}: Processing FIGNAME='{figname}'")
                logger.debug(f"  Checking exact match in: {list(filename_to_id.keys())}")
                logger.debug(f"  Checking stem match in: {list(filename_stem_to_id.keys())}")

                # Map FIGNAME to image_id
                # First try exact match (with extension)
                image_id = filename_to_id.get(figname)
                logger.debug(f"  Exact match result: {image_id}")
                
                # If no exact match, try matching by stem (FIGNAME is usually just the stem)
                if not image_id:
                    image_id = filename_stem_to_id.get(figname)
                    logger.debug(f"  Stem match result: {image_id}")
                
                if not image_id:
                    raise ValueError(
                        f"Row {row_num}: FIGNAME '{figname}' not found in source images. "
                        f"Available: {list(filename_to_id.keys())}"
                    )

                # Parse bbox coordinates
                try:
                    bbox = {
                        "x0": float(row['X0'].strip()),
                        "y0": float(row['Y0'].strip()),
                        "x1": float(row['X1'].strip()),
                        "y1": float(row['Y1'].strip())
                    }
                except ValueError as e:
                    raise ValueError(f"Row {row_num}: Invalid bbox coordinates: {str(e)}")

                panel_data = {
                    "figname": figname,
                    "image_id": image_id,
                    "panel_id": row['ID'].strip(),
                    "panel_type": row['LABEL'].strip(),
                    "bbox": bbox
                }

                panels_data.append(panel_data)
                logger.debug(f"Row {row_num}: Parsed panel {panel_data['panel_id']} from {figname}")

            except (ValueError, KeyError) as e:
                logger.error(f"Error parsing row {row_num}: {str(e)}")
                raise

    logger.info(f"Successfully parsed {len(panels_data)} panels from PANELS.csv")
    return panels_data
