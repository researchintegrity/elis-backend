import pytest
import os
import time
from unittest.mock import patch, MagicMock
from PIL import Image
from app.utils.docker_trufor import run_trufor_detection_with_docker
from app.schemas import AnalysisType

# Create a large dummy image for testing
@pytest.fixture
def large_image(tmp_path):
    # Create a 4000x4000 image to ensure processing takes > 1 second
    width, height = 4000, 4000
    # Create a solid color image (or random-ish if needed, but solid is fine for size)
    img = Image.new('RGB', (width, height), color='red')
    
    file_path = tmp_path / "large_test_image.png"
    img.save(file_path)
    return str(file_path)

@pytest.mark.asyncio
async def test_trufor_timeout(large_image):
    """
    Test that the TruFor detection times out correctly when the timeout is set to a small value.
    """
    analysis_id = "test_timeout_analysis"
    user_id = "test_user"
    
    # Mock status callback to capture "TIMEOUT" status
    status_updates = []
    def status_callback(msg):
        status_updates.append(msg)
        print(f"Test Callback: {msg}")

    # Patch the timeout to be very short (1 second) and disable GPU
    # We patch it where it is used in app.utils.docker_trufor
    with patch('app.utils.docker_trufor.TRUFOR_TIMEOUT', 1), \
         patch('app.utils.docker_trufor.TRUFOR_USE_GPU', False):
        start_time = time.time()
        
        success, message, results = run_trufor_detection_with_docker(
            analysis_id=analysis_id,
            user_id=user_id,
            image_path=large_image,
            status_callback=status_callback
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"Execution took {duration:.2f} seconds")
        print(f"Result: success={success}, message={message}")
        print(f"Status updates: {status_updates}")

        # Assertions
        assert success is False, "Detection should have failed due to timeout"
        
        # Check if we received the TIMEOUT status update
        # The run_trufor.py script prints "[STATUS] TIMEOUT" which docker_trufor.py parses
        assert "TIMEOUT" in status_updates, "Should have received TIMEOUT status update"
        
        # The duration should be roughly the timeout (plus some overhead)
        # It shouldn't take significantly longer than the timeout
        # (e.g. if it took 10s for a 1s timeout, something is wrong)
        assert duration < 10, "Execution took too long for a 1s timeout"

if __name__ == "__main__":
    # Manual run helper
    import asyncio
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        img_path = os.path.join(tmpdir, "large.png")
        Image.new('RGB', (4000, 4000)).save(img_path)
        asyncio.run(test_trufor_timeout(img_path))
