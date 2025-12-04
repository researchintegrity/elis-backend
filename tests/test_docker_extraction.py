"""
Docker extraction integration tests

This module contains tests for the Docker-based PDF image extraction.
Run with: pytest tests/test_docker_extraction.py -v
"""
import pytest
import os
import tempfile
from unittest.mock import patch, MagicMock
from app.utils.docker_extraction import (
    extract_images_with_docker,
    extract_images_with_docker_compose,
    verify_docker_image_exists,
    get_docker_info
)


class TestDockerExtraction:
    """Test Docker image extraction functionality"""
    
    def test_get_docker_info_available(self):
        """Test getting Docker info when Docker is available"""
        info = get_docker_info()
        
        assert isinstance(info, dict)
        assert "docker_available" in info
        assert "docker_version" in info
        assert "error" in info
        
        # Note: This test will only pass if Docker is actually installed
        # In CI/CD environments without Docker, this will be skipped
    
    def test_verify_docker_image_exists(self):
        """Test checking if Docker image exists"""
        result = verify_docker_image_exists("python:3.12")  # Use python image as it's likely available
        
        assert isinstance(result, bool)
    
    def test_extract_with_missing_pdf(self):
        """Test extraction with non-existent PDF file"""
        doc_id = "test_doc_123"
        user_id = "test_user_456"
        pdf_path = "/path/that/does/not/exist/sample.pdf"
        
        count, errors, files = extract_images_with_docker(
            doc_id=doc_id,
            user_id=user_id,
            pdf_file_path=pdf_path
        )
        
        assert count == 0
        assert len(errors) > 0
        assert "not found" in errors[0].lower()
    
    @patch('subprocess.run')
    def test_extract_docker_command_structure(self, mock_run):
        """Test that Docker command is structured correctly"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake PDF file
            pdf_path = os.path.join(tmpdir, "test.pdf")
            with open(pdf_path, 'w') as f:
                f.write("fake pdf content")
            
            count, errors, files = extract_images_with_docker(
                doc_id="test_doc",
                user_id="test_user",
                pdf_file_path=pdf_path
            )
            
            # Verify Docker command was called
            mock_run.assert_called_once()
            
            # Get the actual command
            call_args = mock_run.call_args
            docker_command = call_args[0][0]
            
            # Verify command structure
            assert docker_command[0] == "docker"
            assert docker_command[1] == "run"
            assert "--rm" in docker_command
            assert "-v" in docker_command
            assert "-e" in docker_command
            assert "pdf-extractor:latest" in docker_command
    
    @patch('subprocess.run')
    def test_extract_handles_timeout(self, mock_run):
        """Test handling of extraction timeout"""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("docker", 300)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            with open(pdf_path, 'w') as f:
                f.write("fake pdf content")
            
            count, errors, files = extract_images_with_docker(
                doc_id="test_doc",
                user_id="test_user",
                pdf_file_path=pdf_path
            )
            
            assert count == 0
            assert len(errors) > 0
            assert "timeout" in errors[0].lower()
    
    @patch('subprocess.run')
    def test_extract_handles_docker_failure(self, mock_run):
        """Test handling of Docker command failure"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Docker error: Image not found"
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            with open(pdf_path, 'w') as f:
                f.write("fake pdf content")
            
            count, errors, files = extract_images_with_docker(
                doc_id="test_doc",
                user_id="test_user",
                pdf_file_path=pdf_path
            )
            
            assert count == 0
            assert len(errors) > 0
            assert "failed" in errors[0].lower()
    
    @patch('subprocess.run')
    @patch('os.listdir')
    @patch('os.path.getsize')
    def test_extract_counts_images(self, mock_getsize, mock_listdir, mock_run):
        """Test that extracted images are counted correctly"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_listdir.return_value = [
            "image_0.png",
            "image_1.jpg",
            "image_2.jpeg",
            "metadata.json",  # Should not be counted
            "README.txt"      # Should not be counted
        ]
        mock_getsize.return_value = 1024  # Mock file size
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            with open(pdf_path, 'w') as f:
                f.write("fake pdf content")
            
            count, errors, files = extract_images_with_docker(
                doc_id="test_doc",
                user_id="test_user",
                pdf_file_path=pdf_path
            )
            
            assert count == 3  # Should only count image files
            assert len(errors) == 0
    
    @patch('os.path.exists')
    def test_extract_handles_missing_output_dir(self, mock_exists):
        """Test handling when output directory is not created"""
        # Mock os.path.exists: True for PDF check, False for output dir check
        mock_exists.side_effect = [True, False]
        
        with patch('subprocess.run') as mock_run:
            with patch('os.makedirs') as mock_makedirs:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                mock_makedirs.return_value = None  # Simulate makedirs working
                
                count, errors, files = extract_images_with_docker(
                    doc_id="test_doc",
                    user_id="test_user",
                    pdf_file_path="/tmp/test.pdf"
                )
                
                assert count == 0
                assert len(errors) > 0
                # Error could be about output directory or Docker
                assert isinstance(errors, list)
    
    def test_extract_returns_tuple(self):
        """Test that extraction always returns a tuple"""
        # With non-existent file
        result = extract_images_with_docker(
            doc_id="test",
            user_id="test",
            pdf_file_path="/nonexistent/file.pdf"
        )
        
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], int)
        assert isinstance(result[1], list)
        assert isinstance(result[2], list)
    
    @patch('subprocess.run')
    def test_extract_with_custom_docker_image(self, mock_run):
        """Test extraction with custom Docker image"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            with open(pdf_path, 'w') as f:
                f.write("fake pdf content")
            
            count, errors, files = extract_images_with_docker(
                doc_id="test_doc",
                user_id="test_user",
                pdf_file_path=pdf_path,
                docker_image="custom-image:latest"
            )
            
            # Verify custom image was used
            call_args = mock_run.call_args
            docker_command = call_args[0][0]
            assert "custom-image:latest" in docker_command


class TestDockerCompose:
    """Test Docker Compose extraction functionality"""
    
    @patch('subprocess.run')
    def test_docker_compose_command_structure(self, mock_run):
        """Test that Docker Compose command is structured correctly"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            with open(pdf_path, 'w') as f:
                f.write("fake pdf content")
            
            count, errors = extract_images_with_docker_compose(
                doc_id="test_doc",
                user_id="test_user",
                pdf_file_path=pdf_path
            )
            
            # Verify Docker Compose command was called
            mock_run.assert_called_once()
            
            # Get the actual command
            call_args = mock_run.call_args
            compose_command = call_args[0][0]
            
            # Verify command structure
            assert compose_command[0] == "docker-compose"
            assert compose_command[1] == "run"
            assert "--rm" in compose_command
    
    def test_docker_compose_with_missing_pdf(self):
        """Test Docker Compose with non-existent PDF"""
        count, errors = extract_images_with_docker_compose(
            doc_id="test_doc",
            user_id="test_user",
            pdf_file_path="/path/that/does/not/exist.pdf"
        )
        
        assert count == 0
        assert len(errors) > 0


class TestDockerIntegration:
    """Integration tests for Docker extraction with the system"""
    
    @pytest.mark.skipif(
        os.environ.get("DOCKER_AVAILABLE") != "true",
        reason="Requires Docker to be installed and running"
    )
    def test_real_docker_extraction(self):
        """Real test with actual Docker (only runs if Docker is available)"""
        info = get_docker_info()
        if not info['docker_available']:
            pytest.skip("Docker not available")
        
        # This would require a real PDF file
        # For now, just verify Docker is available
        assert info['docker_available']
    
    def test_extraction_error_handling(self):
        """Test error handling in extraction"""
        # Test with invalid parameters
        count, errors, files = extract_images_with_docker(
            doc_id="",
            user_id="",
            pdf_file_path=""
        )
        
        assert isinstance(count, int)
        assert isinstance(errors, list)
        assert count == 0


class TestDockerEnvironmentVariables:
    """Test Docker environment variable handling"""
    
    @patch('subprocess.run')
    def test_input_path_env_variable(self, mock_run):
        """Test that INPUT_PATH environment variable is set correctly"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "myfile.pdf")
            with open(pdf_path, 'w') as f:
                f.write("fake pdf content")
            
            extract_images_with_docker(
                doc_id="test_doc",
                user_id="test_user",
                pdf_file_path=pdf_path
            )
            
            call_args = mock_run.call_args
            docker_command = call_args[0][0]
            
            # Find INPUT_PATH environment variable
            for i, arg in enumerate(docker_command):
                if arg == "-e" and i + 1 < len(docker_command):
                    env_var = docker_command[i + 1]
                    if env_var.startswith("INPUT_PATH="):
                        assert "/INPUT/myfile.pdf" in env_var
                        break
            else:
                pytest.fail("INPUT_PATH environment variable not found")
    
    @patch('subprocess.run')
    def test_output_path_env_variable(self, mock_run):
        """Test that OUTPUT_PATH environment variable is set correctly"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            with open(pdf_path, 'w') as f:
                f.write("fake pdf content")
            
            extract_images_with_docker(
                doc_id="test_doc",
                user_id="test_user",
                pdf_file_path=pdf_path
            )
            
            call_args = mock_run.call_args
            docker_command = call_args[0][0]
            
            # Find OUTPUT_PATH environment variable
            for i, arg in enumerate(docker_command):
                if arg == "-e" and i + 1 < len(docker_command):
                    env_var = docker_command[i + 1]
                    if env_var.startswith("OUTPUT_PATH="):
                        assert env_var == "OUTPUT_PATH=/OUTPUT"
                        break
            else:
                pytest.fail("OUTPUT_PATH environment variable not found")


# Integration with Celery task
def test_extraction_hook_returns_tuple():
    """Test that figure_extraction_hook returns correct type"""
    from app.utils.file_storage import figure_extraction_hook
    
    # Mock docker extraction
    with patch('app.utils.docker_extraction.extract_images_with_docker') as mock:
        mock.return_value = (5, [], [])
        
        result = figure_extraction_hook(
            doc_id="test_doc",
            user_id="test_user",
            pdf_file_path="/tmp/test.pdf"
        )
        
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], int)
        assert isinstance(result[1], list)
        assert isinstance(result[2], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
