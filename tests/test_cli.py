"""Tests for CLI interface."""

from unittest.mock import patch, Mock

from auto.cli import cli


class TestCLI:
    """Test CLI functionality."""
    
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
    
    def test_init_command(self, runner, temp_home, mock_git_root, monkeypatch, isolated_config_manager):
        """Test init command creates project config by default."""
        # Mock current directory to be in a git repository
        monkeypatch.chdir(mock_git_root)
        
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert "Project configuration initialized" in result.output
        
        # Verify both user and project config files were created
        user_config_path = temp_home / ".auto" / "config.yaml"
        project_config_path = mock_git_root / ".auto" / "config.yaml"
        
        assert user_config_path.exists()
        assert project_config_path.exists()
    
    def test_init_command_user_config_exists(self, runner, temp_home, mock_git_root, monkeypatch, isolated_config_manager):
        """Test init command when user config already exists."""
        # Create user config first
        user_config_path = temp_home / ".auto" / "config.yaml"
        user_config_path.parent.mkdir(parents=True, exist_ok=True)
        user_config_path.write_text("version: 1.0\n")
        
        # Mock current directory to be in a git repository
        monkeypatch.chdir(mock_git_root)
        
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert "Project configuration initialized" in result.output
        # Should not mention creating user config since it already exists
        assert "User configuration created" not in result.output
        
        # Verify project config was created
        project_config_path = mock_git_root / ".auto" / "config.yaml"
        assert project_config_path.exists()
    
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
    
    def test_status_empty(self, runner, temp_home, mock_auto_core):
        """Test status command with no workflows."""
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "No active workflows found" in result.output
    
    def test_cleanup_empty(self, runner, temp_home, mock_auto_core):
        """Test cleanup command with no workflows."""
        result = runner.invoke(cli, ["cleanup"])
        assert result.exit_code == 0
        assert "No workflows to clean up" in result.output
    
    @patch("auto.cli.validate_issue_access")
    @patch("auto.cli.fetch_issue_workflow_sync")
    def test_issue_id_parsing(self, mock_fetch_workflow, mock_validate_access, runner, temp_home):
        """Test issue ID parsing in stub commands."""
        # Setup mocks
        mock_validate_access.return_value = True
        mock_state = Mock()
        mock_state.issue = Mock()
        mock_state.issue.title = "Test Issue"
        mock_state.issue.url = "https://github.com/owner/repo/issues/123"
        mock_fetch_workflow.return_value = mock_state
        
        # Test GitHub format
        result = runner.invoke(cli, ["fetch", "#123"])
        assert result.exit_code == 0
        assert "github" in result.output and "#123" in result.output
        
        # Test Linear format
        result = runner.invoke(cli, ["fetch", "ENG-456"])
        assert result.exit_code == 0
        assert "linear" in result.output and "ENG-456" in result.output
        
        # Test invalid format
        mock_validate_access.return_value = False
        result = runner.invoke(cli, ["fetch", "invalid"])
        assert result.exit_code == 1
        assert "Error:" in result.output
    
    def test_run_command_with_state_creation(self, runner, mock_git_root, monkeypatch):
        """Test run command creates workflow state."""
        # Mock current directory with git root
        monkeypatch.chdir(mock_git_root)
        
        # Ensure fresh core instance for test
        from auto.core import core
        core.state_dir = mock_git_root / ".auto" / "state"
        core.state_dir.mkdir(parents=True, exist_ok=True)
        
        result = runner.invoke(cli, ["run", "ENG-123"])
        assert result.exit_code == 0
        assert "Created workflow state for ENG-123" in result.output
        
        # Verify state file was created
        state_file = mock_git_root / ".auto" / "state" / "ENG-123.yaml"
        assert state_file.exists()
    
    def test_verbose_flag(self, runner, temp_home):
        """Test verbose flag enables debug logging."""
        result = runner.invoke(cli, ["--verbose", "status"])
        assert result.exit_code == 0
        # Note: Debug output goes to logging, not stdout, so we just verify no errors