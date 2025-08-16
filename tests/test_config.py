"""Tests for configuration management."""

import os
import tempfile
from pathlib import Path
import pytest
import yaml

from auto.config import ConfigManager, ConfigError
from auto.models import Config


class TestConfigManager:
    """Test ConfigManager functionality."""
    
    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary directory for config tests."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)
    
    @pytest.fixture
    def config_manager(self, temp_config_dir, monkeypatch):
        """Create ConfigManager with temporary directories."""
        # Mock home directory
        monkeypatch.setattr(Path, "home", lambda: temp_config_dir)
        
        # Create a fresh config manager
        manager = ConfigManager()
        manager._user_config_path = temp_config_dir / ".auto" / "config.yaml"
        manager._project_config_path = None
        manager._config = None  # Ensure fresh config state
        
        return manager
    
    def test_default_config_creation(self, config_manager):
        """Test default configuration creation."""
        config_path = config_manager.create_default_config(user_level=True)
        
        assert config_path.exists()
        assert config_path.name == "config.yaml"
        
        # Load and verify config
        with open(config_path) as f:
            data = yaml.safe_load(f)
        
        assert data["version"] == "1.0"
        assert "defaults" in data
        assert "ai" in data
    
    def test_env_var_expansion(self, config_manager, temp_config_dir):
        """Test environment variable expansion."""
        # Set environment variables
        os.environ["TEST_TOKEN"] = "secret-token"
        os.environ["TEST_AGENT"] = "test-agent"
        
        try:
            # Create config with env vars
            config_data = {
                "github": {
                    "token": "${TEST_TOKEN}",
                    "default_org": "${MISSING_VAR:-default-org}"
                },
                "ai": {
                    "implementation_agent": "$TEST_AGENT"
                }
            }
            
            config_path = temp_config_dir / ".auto" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_path, "w") as f:
                yaml.safe_dump(config_data, f)
            
            config_manager._user_config_path = config_path
            
            # Load config and verify expansion
            config = config_manager.load_config()
            
            assert config.github.token == "secret-token"
            assert config.github.default_org == "default-org"  # Default value
            assert config.ai.implementation_agent == "test-agent"
            
        finally:
            # Clean up environment
            os.environ.pop("TEST_TOKEN", None)
            os.environ.pop("TEST_AGENT", None)
    
    def test_env_override(self, config_manager, temp_config_dir):
        """Test environment variable overrides."""
        # Set environment overrides
        os.environ["AUTO_AI__COMMAND"] = "custom-claude"
        os.environ["AUTO_DEFAULTS__AUTO_MERGE"] = "true"
        os.environ["AUTO_DEFAULTS__MAX_REVIEW_ITERATIONS"] = "5"
        
        try:
            # Create basic config
            config_data = {
                "ai": {"command": "original-claude"},
                "defaults": {"auto_merge": False}
            }
            
            config_path = temp_config_dir / ".auto" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_path, "w") as f:
                yaml.safe_dump(config_data, f)
            
            config_manager._user_config_path = config_path
            
            # Load config and verify overrides
            config = config_manager.load_config()
            
            assert config.ai.command == "custom-claude"
            assert config.defaults.auto_merge is True
            assert config.defaults.max_review_iterations == 5
            
        finally:
            # Clean up environment
            os.environ.pop("AUTO_AI__COMMAND", None)
            os.environ.pop("AUTO_DEFAULTS__AUTO_MERGE", None)
            os.environ.pop("AUTO_DEFAULTS__MAX_REVIEW_ITERATIONS", None)
    
    def test_config_merge(self, config_manager, temp_config_dir):
        """Test configuration merging."""
        # Create user config
        user_config = {
            "ai": {"command": "user-claude"},
            "defaults": {"auto_merge": True}
        }
        
        user_path = temp_config_dir / ".auto" / "config.yaml"
        user_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(user_path, "w") as f:
            yaml.safe_dump(user_config, f)
        
        # Create project config
        project_config = {
            "ai": {"implementation_agent": "project-coder"},
            "defaults": {"auto_merge": False},  # Should override user
            "github": {"default_org": "project-org"}
        }
        
        project_path = temp_config_dir / "project" / ".auto" / "config.yaml"
        project_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(project_path, "w") as f:
            yaml.safe_dump(project_config, f)
        
        # Set up manager paths
        config_manager._user_config_path = user_path
        config_manager._project_config_path = project_path
        
        # Load merged config
        config = config_manager.load_config()
        
        # Verify merging
        assert config.ai.command == "user-claude"  # From user
        assert config.ai.implementation_agent == "project-coder"  # From project
        assert config.defaults.auto_merge is False  # Project overrides user
        assert config.github.default_org == "project-org"  # Only in project
    
    def test_get_set_config_value(self, config_manager):
        """Test getting and setting configuration values."""
        # Create initial config
        config_manager.create_default_config(user_level=True)
        
        # Reload config to ensure fresh state
        config_manager.reload_config()
        
        # Test getting value
        command = config_manager.get_config_value("ai.command")
        assert command == "claude"
        
        # Test setting value
        config_manager.set_config_value("ai.command", "new-claude", user_level=True)
        
        # Verify value was set
        new_command = config_manager.get_config_value("ai.command")
        assert new_command == "new-claude"
        
        # Test nested value
        config_manager.set_config_value("github.default_org", "test-org", user_level=True)
        org = config_manager.get_config_value("github.default_org")
        assert org == "test-org"
    
    def test_invalid_key(self, config_manager):
        """Test getting invalid configuration key."""
        config_manager.create_default_config(user_level=True)
        
        with pytest.raises(ConfigError):
            config_manager.get_config_value("invalid.key.path")
    
    def test_config_file_listing(self, config_manager):
        """Test configuration file listing."""
        # Initially no files
        files = config_manager.list_config_files()
        assert files["user"] is None
        # Don't assert about project - it might exist from environment
        
        # Create user config
        config_manager.create_default_config(user_level=True)
        
        files = config_manager.list_config_files()
        assert files["user"] is not None
        assert files["user"].exists()
        # Don't assert about project - it might exist from environment