"""Shared test configuration and fixtures."""

from pathlib import Path
from unittest.mock import Mock
import pytest

from auto.config import ConfigManager


@pytest.fixture
def temp_home(tmp_path):
    """Create a temporary home directory for tests."""
    return tmp_path


@pytest.fixture
def isolated_config_manager(temp_home, monkeypatch):
    """Create an isolated ConfigManager that doesn't touch real config files."""
    # Mock Path.home() to return our temp directory
    monkeypatch.setattr(Path, "home", lambda: temp_home)
    
    # Mock git root to prevent finding real project config
    def mock_get_git_root():
        return None  # No git root found
    monkeypatch.setattr("auto.config.get_git_root", mock_get_git_root)
    
    # Create a fresh ConfigManager instance
    manager = ConfigManager()
    manager._user_config_path = temp_home / ".auto" / "config.yaml"
    manager._project_config_path = None
    manager._config = None  # Ensure fresh config state
    
    return manager


@pytest.fixture(autouse=True)
def mock_global_config_manager(isolated_config_manager, monkeypatch):
    """Automatically mock the global config_manager for all tests."""
    # Import here to avoid circular imports
    import auto.config
    
    # Replace the global config_manager with our isolated instance
    monkeypatch.setattr(auto.config, "config_manager", isolated_config_manager)
    
    # Also mock it in any modules that might have imported it
    import auto.cli
    if hasattr(auto.cli, 'config_manager'):
        monkeypatch.setattr(auto.cli, "config_manager", isolated_config_manager)
    
    import auto.core
    if hasattr(auto.core, 'config_manager'):
        monkeypatch.setattr(auto.core, "config_manager", isolated_config_manager)
    
    # Mock other modules that use config_manager
    try:
        import auto.workflows.process
        if hasattr(auto.workflows.process, 'config_manager'):
            monkeypatch.setattr(auto.workflows.process, "config_manager", isolated_config_manager)
    except ImportError:
        pass
    
    try:
        import auto.workflows.implement
        if hasattr(auto.workflows.implement, 'config_manager'):
            monkeypatch.setattr(auto.workflows.implement, "config_manager", isolated_config_manager)
    except ImportError:
        pass
    
    try:
        import auto.integrations.ai
        if hasattr(auto.integrations.ai, 'config_manager'):
            monkeypatch.setattr(auto.integrations.ai, "config_manager", isolated_config_manager)
    except ImportError:
        pass
    
    return isolated_config_manager


@pytest.fixture
def test_config(isolated_config_manager):
    """Create a test configuration with reasonable defaults."""
    # Create the .auto directory
    config_dir = isolated_config_manager._user_config_path.parent
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a default config for testing
    config_path = isolated_config_manager.create_default_config(user_level=True)
    
    # Load the config to ensure it's valid
    config = isolated_config_manager.get_config()
    
    return config


@pytest.fixture
def mock_git_root(tmp_path, monkeypatch):
    """Mock git root to return a temporary directory."""
    
    git_root = tmp_path / "git_repo"
    git_root.mkdir()
    
    def mock_get_git_root():
        return git_root
    
    monkeypatch.setattr("auto.utils.shell.get_git_root", mock_get_git_root)
    monkeypatch.setattr("auto.config.get_git_root", mock_get_git_root)
    monkeypatch.setattr("auto.core.get_git_root", mock_get_git_root)
    
    return git_root


@pytest.fixture
def mock_github_integration(monkeypatch):
    """Mock GitHub integration to avoid requiring real GitHub authentication."""
    mock = Mock()
    
    # Mock the GitHubIntegration class
    monkeypatch.setattr("auto.integrations.github.GitHubIntegration", lambda: mock)
    
    # Mock validation functions
    monkeypatch.setattr("auto.integrations.github.validate_github_auth", lambda: True)
    monkeypatch.setattr("auto.integrations.github.detect_repository", lambda: mock)
    
    return mock


@pytest.fixture
def mock_ai_integration(monkeypatch):
    """Mock AI integration to avoid requiring Claude CLI."""
    mock = Mock()
    
    # Mock the ClaudeIntegration class
    from auto.integrations.ai import AIResponse
    
    def mock_claude_init(config):
        return mock
    
    # Create a mock response
    mock_response = AIResponse(
        success=True,
        content="Mock AI implementation completed",
        file_changes=[],
        commands=[],
        metadata={}
    )
    
    mock.execute_implementation.return_value = mock_response
    mock.execute_review.return_value = mock_response
    mock.execute_update.return_value = mock_response
    
    monkeypatch.setattr("auto.integrations.ai.ClaudeIntegration", mock_claude_init)
    
    return mock


@pytest.fixture
def mock_auto_core(tmp_path, monkeypatch):
    """Mock AutoCore to use isolated state directory."""
    from auto.core import AutoCore
    
    # Create a mock state directory
    state_dir = tmp_path / ".auto" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    
    # Mock the AutoCore class
    mock_core = Mock(spec=AutoCore)
    mock_core.state_dir = state_dir
    mock_core.get_workflow_states.return_value = []  # Empty by default
    mock_core.get_workflow_state.return_value = None
    
    # Mock the global core instance
    monkeypatch.setattr("auto.core.core", mock_core)
    monkeypatch.setattr("auto.cli.get_core", lambda: mock_core)
    
    return mock_core


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    from click.testing import CliRunner
    return CliRunner()