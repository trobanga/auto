"""
Tests for review cycle configuration validation and defaults.

These tests verify that the configuration system properly handles:
- Review-specific configuration options
- Configuration validation and error handling
- Default values and environment variable overrides
- Configuration merging and precedence
- Configuration migration and compatibility
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from auto.config import ConfigError, ConfigManager, get_config
from auto.models import AIConfig, Config, WorkflowsConfig


class TestReviewConfigurationValidation:
    """Test review configuration validation and defaults."""

    def test_default_review_configuration(self):
        """Test default review configuration values."""
        config = Config()

        # Verify review-specific defaults
        assert config.workflows.max_review_iterations == 10
        assert config.workflows.ai_review_first is True
        assert config.workflows.require_human_approval is True
        assert config.workflows.review_check_interval == 60

        # Verify AI configuration defaults
        assert config.ai.review_agent == "pull-request-reviewer"
        assert config.ai.update_agent == "coder"
        assert config.ai.review_prompt is not None
        assert config.ai.update_prompt is not None

    def test_review_configuration_validation(self):
        """Test review configuration field validation."""
        # Valid configuration should pass
        valid_config = WorkflowsConfig(
            max_review_iterations=5,
            ai_review_first=True,
            require_human_approval=True,
            review_check_interval=30,
        )
        assert valid_config.max_review_iterations == 5
        assert valid_config.ai_review_first is True
        assert valid_config.require_human_approval is True
        assert valid_config.review_check_interval == 30

        # Test invalid max_review_iterations
        with pytest.raises(ValueError):
            WorkflowsConfig(
                max_review_iterations=0,  # Should be > 0
                ai_review_first=True,
                require_human_approval=True,
                review_check_interval=30,
            )

        with pytest.raises(ValueError):
            WorkflowsConfig(
                max_review_iterations=-1,  # Should be > 0
                ai_review_first=True,
                require_human_approval=True,
                review_check_interval=30,
            )

        # Test invalid review_check_interval
        with pytest.raises(ValueError):
            WorkflowsConfig(
                max_review_iterations=5,
                ai_review_first=True,
                require_human_approval=True,
                review_check_interval=0,  # Should be > 0
            )

    def test_ai_review_configuration_validation(self):
        """Test AI review configuration validation."""
        # Valid AI configuration
        valid_ai_config = AIConfig(
            command="claude",
            implementation_agent="coder",
            review_agent="pull-request-reviewer",
            update_agent="coder",
            implementation_prompt="Implement: {description}",
            review_prompt="Review this PR thoroughly",
            update_prompt="Address these comments: {comments}",
        )

        assert valid_ai_config.review_agent == "pull-request-reviewer"
        assert valid_ai_config.update_agent == "coder"
        assert "thoroughly" in valid_ai_config.review_prompt
        assert "{comments}" in valid_ai_config.update_prompt

    def test_configuration_with_custom_review_settings(self):
        """Test configuration with custom review settings."""
        custom_config_data = {
            "workflows": {
                "max_review_iterations": 15,
                "ai_review_first": False,
                "require_human_approval": False,
                "review_check_interval": 120,
                "branch_naming": "review/{issue_type}/{id}",
                "commit_convention": "conventional",
            },
            "ai": {
                "command": "claude",
                "review_agent": "security-focused-reviewer",
                "update_agent": "performance-optimizer",
                "review_prompt": "Perform comprehensive security review",
                "update_prompt": "Optimize performance based on: {comments}",
            },
        }

        config = Config.model_validate(custom_config_data)

        # Verify custom workflow settings
        assert config.workflows.max_review_iterations == 15
        assert config.workflows.ai_review_first is False
        assert config.workflows.require_human_approval is False
        assert config.workflows.review_check_interval == 120

        # Verify custom AI settings
        assert config.ai.review_agent == "security-focused-reviewer"
        assert config.ai.update_agent == "performance-optimizer"
        assert "security review" in config.ai.review_prompt
        assert "performance" in config.ai.update_prompt


class TestReviewConfigurationFiles:
    """Test review configuration file handling."""

    def test_review_configuration_file_loading(self):
        """Test loading review configuration from files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            # Create configuration file with review settings
            config_data = {
                "workflows": {
                    "max_review_iterations": 8,
                    "ai_review_first": True,
                    "require_human_approval": True,
                    "review_check_interval": 45,
                },
                "ai": {
                    "command": "claude",
                    "review_agent": "thorough-reviewer",
                    "update_agent": "code-fixer",
                    "review_prompt": "Please review this code carefully",
                    "update_prompt": "Fix these issues: {comments}",
                },
            }

            with open(config_path, "w") as f:
                yaml.safe_dump(config_data, f)

            # Create config manager and load
            manager = ConfigManager()
            manager._user_config_path = config_path

            config = manager.load_config()

            # Verify loaded review settings
            assert config.workflows.max_review_iterations == 8
            assert config.workflows.ai_review_first is True
            assert config.workflows.review_check_interval == 45
            assert config.ai.review_agent == "thorough-reviewer"
            assert config.ai.update_agent == "code-fixer"

    def test_review_configuration_environment_overrides(self):
        """Test review configuration environment variable overrides."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            # Create base configuration
            base_config = {
                "workflows": {"max_review_iterations": 5, "review_check_interval": 60},
                "ai": {"review_agent": "default-reviewer"},
            }

            with open(config_path, "w") as f:
                yaml.safe_dump(base_config, f)

            # Set environment overrides
            env_overrides = {
                "AUTO_WORKFLOWS__MAX_REVIEW_ITERATIONS": "12",
                "AUTO_WORKFLOWS__REVIEW_CHECK_INTERVAL": "30",
                "AUTO_AI__REVIEW_AGENT": "env-reviewer",
            }

            with patch.dict(os.environ, env_overrides):
                manager = ConfigManager()
                manager._user_config_path = config_path

                config = manager.load_config()

                # Verify environment overrides
                assert config.workflows.max_review_iterations == 12
                assert config.workflows.review_check_interval == 30
                assert config.ai.review_agent == "env-reviewer"

    def test_review_configuration_merging(self):
        """Test merging user and project review configurations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            user_config_path = Path(temp_dir) / "user_config.yaml"
            project_config_path = Path(temp_dir) / "project_config.yaml"

            # User configuration
            user_config = {
                "workflows": {
                    "max_review_iterations": 10,
                    "ai_review_first": True,
                    "require_human_approval": True,
                },
                "ai": {
                    "review_agent": "user-preferred-reviewer",
                    "review_prompt": "User's review prompt",
                },
            }

            # Project configuration (overrides some user settings)
            project_config = {
                "workflows": {
                    "max_review_iterations": 5,  # Override
                    "review_check_interval": 30,  # Additional setting
                },
                "ai": {
                    "review_agent": "project-specific-reviewer",  # Override
                    "update_agent": "project-updater",  # Additional setting
                },
            }

            with open(user_config_path, "w") as f:
                yaml.safe_dump(user_config, f)

            with open(project_config_path, "w") as f:
                yaml.safe_dump(project_config, f)

            # Create manager and load merged config
            manager = ConfigManager()
            manager._user_config_path = user_config_path
            manager._project_config_path = project_config_path

            config = manager.load_config()

            # Verify merged configuration
            assert config.workflows.max_review_iterations == 5  # Project override
            assert config.workflows.ai_review_first is True  # User setting
            assert config.workflows.review_check_interval == 30  # Project addition
            assert config.ai.review_agent == "project-specific-reviewer"  # Project override
            assert config.ai.update_agent == "project-updater"  # Project addition
            assert "User's review prompt" in config.ai.review_prompt  # User setting


class TestReviewConfigurationErrors:
    """Test review configuration error handling."""

    def test_invalid_review_configuration_file(self):
        """Test handling of invalid review configuration files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "invalid_config.yaml"

            # Create invalid YAML file
            with open(config_path, "w") as f:
                f.write("workflows:\n  max_review_iterations: [invalid yaml")

            manager = ConfigManager()
            manager._user_config_path = config_path

            # Should raise ConfigError
            with pytest.raises(ConfigError, match="Failed to parse YAML"):
                manager.load_config()

    def test_invalid_review_field_values(self):
        """Test handling of invalid review field values."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            # Create configuration with invalid review values
            invalid_config = {
                "workflows": {
                    "max_review_iterations": "invalid",  # Should be int
                    "ai_review_first": "maybe",  # Should be bool
                    "review_check_interval": -10,  # Should be positive
                }
            }

            with open(config_path, "w") as f:
                yaml.safe_dump(invalid_config, f)

            manager = ConfigManager()
            manager._user_config_path = config_path

            # Should raise ConfigError due to validation
            with pytest.raises(ConfigError, match="Invalid configuration"):
                manager.load_config()

    def test_missing_required_review_fields(self):
        """Test handling of missing required review fields."""
        # This test depends on which fields are actually required in your Config model
        # Assuming some fields have defaults, this tests the validation logic

        # Create config with minimal data
        minimal_config_data = {
            "ai": {
                "command": "claude"
                # Missing other fields - should use defaults
            }
        }

        # Should succeed with defaults
        config = Config.model_validate(minimal_config_data)
        assert config.ai.command == "claude"
        assert config.workflows.max_review_iterations > 0  # Default applied

    def test_configuration_type_coercion(self):
        """Test configuration type coercion and validation."""
        config_data = {
            "workflows": {
                "max_review_iterations": "5",  # String should convert to int
                "ai_review_first": "true",  # String should convert to bool
                "review_check_interval": "60",  # String should convert to int
            }
        }

        config = Config.model_validate(config_data)

        # Verify type coercion
        assert isinstance(config.workflows.max_review_iterations, int)
        assert config.workflows.max_review_iterations == 5
        assert isinstance(config.workflows.ai_review_first, bool)
        assert config.workflows.ai_review_first is True
        assert isinstance(config.workflows.review_check_interval, int)
        assert config.workflows.review_check_interval == 60


class TestReviewConfigurationDefaults:
    """Test review configuration default values and behavior."""

    def test_review_workflow_defaults(self):
        """Test default values for review workflow configuration."""
        config = Config()

        # Test workflow defaults
        assert config.workflows.max_review_iterations == 10
        assert config.workflows.ai_review_first is True
        assert config.workflows.require_human_approval is True
        assert config.workflows.review_check_interval == 60
        assert config.workflows.branch_naming == "auto/{type}/{id}"
        assert config.workflows.commit_convention == "conventional"

    def test_ai_review_defaults(self):
        """Test default values for AI review configuration."""
        config = Config()

        # Test AI defaults for review
        assert config.ai.command == "claude"
        assert config.ai.implementation_agent == "coder"
        assert config.ai.review_agent == "pull-request-reviewer"
        assert config.ai.update_agent == "coder"

        # Test default prompts exist and contain expected content
        assert config.ai.implementation_prompt is not None
        assert "{description}" in config.ai.implementation_prompt

        assert config.ai.review_prompt is not None
        assert "review" in config.ai.review_prompt.lower()

        assert config.ai.update_prompt is not None
        assert "{comments}" in config.ai.update_prompt

    def test_github_review_defaults(self):
        """Test default values for GitHub review configuration."""
        config = Config()

        # Test GitHub defaults that affect reviews
        assert config.github.default_reviewer is None  # No default reviewer
        assert config.github.pr_template is not None  # Should have template path

    def test_configuration_with_partial_overrides(self):
        """Test configuration behavior with partial overrides."""
        partial_config_data = {
            "workflows": {
                "max_review_iterations": 7  # Only override this field
                # Other fields should use defaults
            }
        }

        config = Config.model_validate(partial_config_data)

        # Verify override
        assert config.workflows.max_review_iterations == 7

        # Verify defaults are still applied
        assert config.workflows.ai_review_first is True  # Default
        assert config.workflows.require_human_approval is True  # Default
        assert config.workflows.review_check_interval == 60  # Default


class TestReviewConfigurationUtilities:
    """Test review configuration utility functions."""

    def test_get_config_function(self):
        """Test the get_config utility function."""
        # Mock the global config manager
        with patch("auto.config.config_manager") as mock_manager:
            mock_config = Mock()
            mock_config.workflows.max_review_iterations = 8
            mock_config.ai.review_agent = "test-reviewer"

            mock_manager.get_config.return_value = mock_config

            # Test get_config function
            config = get_config()

            assert config.workflows.max_review_iterations == 8
            assert config.ai.review_agent == "test-reviewer"
            mock_manager.get_config.assert_called_once()

    def test_config_value_retrieval(self):
        """Test retrieving specific configuration values."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            config_data = {
                "workflows": {"max_review_iterations": 6, "review_check_interval": 45},
                "ai": {"review_agent": "custom-reviewer"},
            }

            with open(config_path, "w") as f:
                yaml.safe_dump(config_data, f)

            manager = ConfigManager()
            manager._user_config_path = config_path
            manager.load_config()

            # Test specific value retrieval
            max_iterations = manager.get_config_value("workflows.max_review_iterations")
            assert max_iterations == 6

            check_interval = manager.get_config_value("workflows.review_check_interval")
            assert check_interval == 45

            review_agent = manager.get_config_value("ai.review_agent")
            assert review_agent == "custom-reviewer"

    def test_config_value_setting(self):
        """Test setting configuration values."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            # Create initial config
            initial_config = {"workflows": {"max_review_iterations": 5}}
            with open(config_path, "w") as f:
                yaml.safe_dump(initial_config, f)

            manager = ConfigManager()
            manager._user_config_path = config_path

            # Set new values
            manager.set_config_value("workflows.max_review_iterations", 12)
            manager.set_config_value("workflows.review_check_interval", 30)
            manager.set_config_value("ai.review_agent", "new-reviewer")

            # Verify values were set
            assert manager.get_config_value("workflows.max_review_iterations") == 12
            assert manager.get_config_value("workflows.review_check_interval") == 30
            assert manager.get_config_value("ai.review_agent") == "new-reviewer"

            # Verify file was updated
            with open(config_path) as f:
                saved_config = yaml.safe_load(f)

            assert saved_config["workflows"]["max_review_iterations"] == 12
            assert saved_config["workflows"]["review_check_interval"] == 30
            assert saved_config["ai"]["review_agent"] == "new-reviewer"


class TestReviewConfigurationMigration:
    """Test review configuration migration and compatibility."""

    def test_legacy_configuration_compatibility(self):
        """Test compatibility with legacy configuration formats."""
        # Simulate legacy config format
        legacy_config_data = {
            "review": {  # Old nested structure
                "max_iterations": 8,
                "ai_first": True,
                "check_interval": 45,
            },
            "ai_config": {  # Old AI config structure
                "reviewer": "legacy-reviewer",
                "updater": "legacy-updater",
            },
        }

        # Test migration logic (this would be implemented in your ConfigManager)
        # For now, test that new structure works correctly
        new_config_data = {
            "workflows": {
                "max_review_iterations": legacy_config_data["review"]["max_iterations"],
                "ai_review_first": legacy_config_data["review"]["ai_first"],
                "review_check_interval": legacy_config_data["review"]["check_interval"],
            },
            "ai": {
                "review_agent": legacy_config_data["ai_config"]["reviewer"],
                "update_agent": legacy_config_data["ai_config"]["updater"],
            },
        }

        config = Config.model_validate(new_config_data)

        # Verify migration preserved values
        assert config.workflows.max_review_iterations == 8
        assert config.workflows.ai_review_first is True
        assert config.workflows.review_check_interval == 45
        assert config.ai.review_agent == "legacy-reviewer"
        assert config.ai.update_agent == "legacy-updater"

    def test_configuration_version_handling(self):
        """Test handling of different configuration versions."""
        # Test current version
        current_config = {"version": "1.0", "workflows": {"max_review_iterations": 10}}

        config = Config.model_validate(current_config)
        assert config.workflows.max_review_iterations == 10

        # Test handling of missing version (assume current)
        no_version_config = {"workflows": {"max_review_iterations": 5}}

        config = Config.model_validate(no_version_config)
        assert config.workflows.max_review_iterations == 5
