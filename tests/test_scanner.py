"""Tests for scanner module."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from devclean.scanner import (
    CruftItem,
    ScanResult,
    get_dir_size,
    check_command_exists,
    scan_known_cruft,
)
from devclean.exceptions import TimeoutError, ScanError


class TestCruftItem:
    """Tests for CruftItem dataclass."""
    
    def test_cruft_item_creation(self):
        """Test creating a CruftItem."""
        item = CruftItem(
            path=Path("/tmp/test"),
            size_bytes=1048576,  # 1MB
            category="test",
            description="Test item",
            safe=True,
        )
        
        assert item.path == Path("/tmp/test")
        assert item.size_bytes == 1048576
        assert item.size_mb == 1.0
        assert item.size_gb == pytest.approx(0.001, abs=0.001)
        assert item.size_human == "1 MB"
        assert item.category == "test"
        assert item.safe is True
        assert item.tool_installed is None
    
    def test_size_human_gb(self):
        """Test human-readable size formatting for GB."""
        item = CruftItem(
            path=Path("/tmp/test"),
            size_bytes=2 * 1024**3,  # 2GB
            category="test",
            description="Test item",
        )
        
        assert item.size_human == "2.0 GB"
    
    def test_size_human_mb(self):
        """Test human-readable size formatting for MB."""
        item = CruftItem(
            path=Path("/tmp/test"),
            size_bytes=500 * 1024**2,  # 500MB
            category="test", 
            description="Test item",
        )
        
        assert item.size_human == "500 MB"


class TestScanResult:
    """Tests for ScanResult dataclass."""
    
    def test_scan_result_creation(self):
        """Test creating a ScanResult."""
        result = ScanResult()
        
        assert result.items == []
        assert result.venvs == []
        assert result.node_modules == []
        assert result.errors == []
        assert result.all_items == []
        assert result.total_bytes == 0
        assert result.total_gb == 0.0
    
    def test_scan_result_with_items(self):
        """Test ScanResult with items."""
        item1 = CruftItem(
            path=Path("/tmp/test1"),
            size_bytes=1024**3,  # 1GB
            category="test",
            description="Test item 1",
        )
        item2 = CruftItem(
            path=Path("/tmp/test2"),
            size_bytes=512 * 1024**2,  # 512MB
            category="test",
            description="Test item 2",
        )
        
        result = ScanResult(items=[item1], venvs=[item2])
        
        assert len(result.all_items) == 2
        assert result.total_bytes == 1024**3 + 512 * 1024**2
        assert result.total_gb == pytest.approx(1.5, abs=0.01)


class TestGetDirSize:
    """Tests for get_dir_size function."""
    
    @patch('devclean.scanner.subprocess.run')
    def test_get_dir_size_success(self, mock_run):
        """Test successful directory size calculation."""
        # Mock successful du command
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="1024\t/tmp/test\n"
        )
        
        result = get_dir_size(Path("/tmp/test"))
        assert result == 1024 * 1024  # Should convert from KB to bytes
    
    @patch('devclean.scanner.subprocess.run')
    def test_get_dir_size_timeout(self, mock_run):
        """Test directory size calculation timeout."""
        from subprocess import TimeoutExpired
        mock_run.side_effect = TimeoutExpired("du", 30)
        
        with pytest.raises(TimeoutError):
            get_dir_size(Path("/tmp/test"), timeout=30)
    
    @patch('devclean.scanner.subprocess.run')
    def test_get_dir_size_parse_error(self, mock_run):
        """Test directory size calculation parse error."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="invalid output"
        )
        
        with pytest.raises(ScanError):
            get_dir_size(Path("/tmp/test"))


class TestCheckCommandExists:
    """Tests for check_command_exists function."""
    
    @patch('devclean.scanner.subprocess.run')
    def test_command_exists(self, mock_run):
        """Test checking for existing command."""
        mock_run.return_value = MagicMock(returncode=0)
        
        result = check_command_exists("python")
        assert result is True
    
    @patch('devclean.scanner.subprocess.run')
    def test_command_not_exists(self, mock_run):
        """Test checking for non-existing command."""
        mock_run.return_value = MagicMock(returncode=1)
        
        result = check_command_exists("nonexistent-command")
        assert result is False
    
    @patch('devclean.scanner.subprocess.run')
    def test_command_check_error(self, mock_run):
        """Test command check with exception."""
        mock_run.side_effect = Exception("Test error")
        
        result = check_command_exists("python")
        assert result is False
    
    def test_command_with_args(self):
        """Test command with version argument."""
        # This should extract just 'python' from 'python --version'
        result = check_command_exists("python --version")
        # Result depends on whether python is actually installed
        assert isinstance(result, bool)


class TestScanKnownCruft:
    """Tests for scan_known_cruft function."""
    
    @patch('devclean.scanner.get_dir_size')
    @patch('devclean.scanner.check_command_exists')
    def test_scan_known_cruft_empty(self, mock_check_cmd, mock_get_size):
        """Test scanning with no cruft found.""" 
        # Mock that paths don't exist
        with patch('pathlib.Path.exists', return_value=False):
            result = scan_known_cruft(Path.home(), min_size_mb=100)
            assert result == []
    
    @patch('devclean.scanner.get_dir_size')
    @patch('devclean.scanner.check_command_exists')
    def test_scan_known_cruft_found(self, mock_check_cmd, mock_get_size):
        """Test scanning with cruft found."""
        mock_get_size.return_value = 200 * 1024 * 1024  # 200MB
        mock_check_cmd.return_value = True
        
        # Mock that only one path exists (pre-commit cache)
        def mock_exists(self):
            return ".cache/pre-commit" in str(self)
        
        with patch('pathlib.Path.exists', mock_exists):
            result = scan_known_cruft(Path.home(), min_size_mb=100)
            assert len(result) == 1
            assert result[0].category == "python"
            assert result[0].description == "Pre-commit hook environments"
            assert result[0].size_bytes == 200 * 1024 * 1024
            assert result[0].tool_installed is True
    
    @patch('devclean.scanner.get_dir_size')
    @patch('devclean.scanner.check_command_exists')
    def test_scan_known_cruft_too_small(self, mock_check_cmd, mock_get_size):
        """Test scanning with cruft that's too small."""
        mock_get_size.return_value = 50 * 1024 * 1024  # 50MB (below 100MB threshold)
        mock_check_cmd.return_value = True
        
        def mock_exists(self):
            return ".cache/pre-commit" in str(self)
        
        with patch('pathlib.Path.exists', mock_exists):
            result = scan_known_cruft(Path.home(), min_size_mb=100)
            assert result == []