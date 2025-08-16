"""Tests for CLI interface."""

import tempfile
from pathlib import Path
import pytest
from click.testing import CliRunner

from auto.cli import cli


class TestCLI:
    """Test CLI functionality."""
    
    @pytest.fixture
    def runner(self):
        """Create CLI test runner."""
        return CliRunner()
    
    @pytest.fixture
    def temp_home(self, monkeypatch):
        """Mock home directory for tests."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            monkeypatch.setattr(Path, "home", lambda: temp_path)
            yield temp_path
    
    def test_version_flag(self, runner):
        """Test --version flag."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "auto version" in result.output
    
    def test_help_output(self, runner):
        """Test help output."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Automatic User Task Orchestrator" in result.output
        assert "Commands:" in result.output
    
    def test_init_command(self, runner, temp_home, monkeypatch):
        """Test init command."""
        # Ensure no existing config affects test
        from auto.config import config_manager
        config_manager._config = None
        
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert "configuration initialized" in result.output
        
        # Verify config file was created
        config_path = temp_home / ".auto" / "config.yaml"
        assert config_path.exists()
    
    def test_init_project_flag(self, runner, temp_home, monkeypatch):
        """Test init command with --project flag."""
        # Mock current directory
        cwd = temp_home / "project"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        
        result = runner.invoke(cli, ["init", "--project"])
        assert result.exit_code == 0
        assert "Project configuration initialized" in result.output
        
        # Verify project config file was created
        config_path = cwd / ".auto" / "config.yaml"
        assert config_path.exists()
    
    def test_config_get_set(self, runner, temp_home):
        """Test config get and set commands."""
        # Initialize config first
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        
        # Test getting a value
        result = runner.invoke(cli, ["config", "get", "ai.command"])
        assert result.exit_code == 0
        assert "ai.command: claude" in result.output
        
        # Test setting a value
        result = runner.invoke(cli, ["config", "set", "ai.command", "new-claude"])
        assert result.exit_code == 0
        assert "config updated" in result.output
        
        # Verify the value was set
        result = runner.invoke(cli, ["config", "get", "ai.command"])
        assert result.exit_code == 0
        assert "ai.command: new-claude" in result.output
    
    def test_config_list(self, runner, temp_home):
        """Test config list command."""
        # Initialize config first
        runner.invoke(cli, ["init"])
        
        result = runner.invoke(cli, ["config", "list"])
        assert result.exit_code == 0
        assert "Configuration Files" in result.output
        assert "User" in result.output
        assert "✓ Exists" in result.output
    
    def test_status_empty(self, runner, temp_home):
        """Test status command with no workflows."""
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "No active workflows found" in result.output
    
    def test_cleanup_empty(self, runner, temp_home):
        """Test cleanup command with no workflows."""
        result = runner.invoke(cli, ["cleanup"])
        assert result.exit_code == 0
        assert "No completed workflows to clean up" in result.output
    
    def test_issue_id_parsing(self, runner, temp_home):
        """Test issue ID parsing in stub commands."""
        # Test GitHub format
        result = runner.invoke(cli, ["fetch", "#123"])
        assert result.exit_code == 0
        assert "github" in result.output and "#123" in result.output
        
        # Test Linear format
        result = runner.invoke(cli, ["fetch", "ENG-456"])
        assert result.exit_code == 0
        assert "linear" in result.output and "ENG-456" in result.output
        
        # Test invalid format
        result = runner.invoke(cli, ["fetch", "invalid"])
        assert result.exit_code == 1
        assert "Error:" in result.output
    
    def test_run_command_with_state_creation(self, runner, temp_home, monkeypatch):
        """Test run command creates workflow state."""
        # Mock current directory with git root
        cwd = temp_home / "project"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        
        # Mock git root detection
        from auto.utils import shell
        monkeypatch.setattr(shell, "get_git_root", lambda: cwd)
        
        # Ensure fresh core instance for test
        from auto.core import core
        core.state_dir = cwd / ".auto" / "state"
        core.state_dir.mkdir(parents=True, exist_ok=True)
        
        result = runner.invoke(cli, ["run", "ENG-123"])
        assert result.exit_code == 0
        assert "Created workflow state for ENG-123" in result.output
        
        # Verify state file was created
        state_file = cwd / ".auto" / "state" / "ENG-123.yaml"
        assert state_file.exists()
    
    def test_verbose_flag(self, runner, temp_home):
        """Test verbose flag enables debug logging."""
        result = runner.invoke(cli, ["--verbose", "status"])
        assert result.exit_code == 0
        # Note: Debug output goes to logging, not stdout, so we just verify no errors