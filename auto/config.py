"""Configuration management for the auto tool."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import ValidationError

from auto.models import Config
from auto.utils.logger import get_logger
from auto.utils.shell import get_git_root

logger = get_logger(__name__)


class ConfigError(Exception):
    """Configuration error."""
    pass


class ConfigManager:
    """Configuration manager with hierarchical loading and environment variable support."""
    
    def __init__(self):
        """Initialize configuration manager."""
        self._config: Optional[Config] = None
        self._user_config_path = Path.home() / ".auto" / "config.yaml"
        self._project_config_path: Optional[Path] = None
        self._find_project_config()
    
    def _find_project_config(self) -> None:
        """Find project configuration file."""
        git_root = get_git_root()
        if git_root:
            project_config = git_root / ".auto" / "config.yaml"
            if project_config.exists():
                # Ensure project config is different from user config
                if project_config != self._user_config_path:
                    self._project_config_path = project_config
                    logger.debug(f"Found project config: {project_config}")
                else:
                    logger.debug(f"Skipping user config found as project config: {project_config}")
            else:
                # Check in current directory and parent directories, but only within git repo
                current = Path.cwd()
                # Only search within the git repository to avoid finding user config
                search_paths = []
                for parent in [current] + list(current.parents):
                    # Stop searching if we've gone outside the git repository
                    if git_root in parent.parents or parent == git_root:
                        search_paths.append(parent)
                    else:
                        break
                
                for parent in search_paths:
                    config_path = parent / ".auto" / "config.yaml"
                    if config_path.exists() and config_path != self._user_config_path:
                        self._project_config_path = config_path
                        logger.debug(f"Found project config: {config_path}")
                        break
    
    def _expand_env_vars(self, data: Any) -> Any:
        """Recursively expand environment variables in configuration data.
        
        Supports formats:
        - ${VAR}
        - ${VAR:-default}
        - $VAR (simple format)
        """
        if isinstance(data, str):
            # Pattern for ${VAR} and ${VAR:-default}
            def replace_env_var(match):
                var_expr = match.group(1)
                if ":-" in var_expr:
                    var_name, default_value = var_expr.split(":-", 1)
                    return os.getenv(var_name, default_value)
                else:
                    var_value = os.getenv(var_expr)
                    if var_value is None:
                        logger.warning(f"Environment variable '{var_expr}' not found")
                        return match.group(0)  # Return original if not found
                    return var_value
            
            # Replace ${VAR} and ${VAR:-default}
            data = re.sub(r'\$\{([^}]+)\}', replace_env_var, data)
            
            # Replace simple $VAR format
            def replace_simple_var(match):
                var_name = match.group(1)
                var_value = os.getenv(var_name)
                if var_value is None:
                    logger.warning(f"Environment variable '{var_name}' not found")
                    return match.group(0)  # Return original if not found
                return var_value
            
            data = re.sub(r'\$([A-Z_][A-Z0-9_]*)', replace_simple_var, data)
            
        elif isinstance(data, dict):
            return {key: self._expand_env_vars(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._expand_env_vars(item) for item in data]
        
        return data
    
    def _load_yaml_file(self, path: Path) -> Dict[str, Any]:
        """Load and parse YAML configuration file.
        
        Args:
            path: Path to YAML file
            
        Returns:
            Parsed configuration data
            
        Raises:
            ConfigError: If file cannot be loaded or parsed
        """
        try:
            if not path.exists():
                return {}
            
            logger.debug(f"Loading config file: {path}")
            
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            
            # Expand environment variables
            data = self._expand_env_vars(data)
            
            logger.debug(f"Loaded config with keys: {list(data.keys())}")
            return data
            
        except yaml.YAMLError as e:
            raise ConfigError(f"Failed to parse YAML file {path}: {e}")
        except Exception as e:
            raise ConfigError(f"Failed to load config file {path}: {e}")
    
    def _merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Merge configuration dictionaries recursively.
        
        Args:
            base: Base configuration
            override: Override configuration
            
        Returns:
            Merged configuration
        """
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def load_config(self) -> Config:
        """Load configuration from all sources.
        
        Loading order (later sources override earlier):
        1. Default configuration (from Config model)
        2. User configuration (~/.auto/config.yaml)
        3. Project configuration (<project>/.auto/config.yaml)
        4. Environment variables
        
        Returns:
            Loaded configuration
            
        Raises:
            ConfigError: If configuration is invalid
        """
        try:
            # Start with default config
            config_data = {}
            
            # Load user config
            user_config = self._load_yaml_file(self._user_config_path)
            config_data = self._merge_configs(config_data, user_config)
            
            # Load project config
            if self._project_config_path:
                project_config = self._load_yaml_file(self._project_config_path)
                config_data = self._merge_configs(config_data, project_config)
            
            # Apply environment variable overrides
            config_data = self._apply_env_overrides(config_data)
            
            # Create and validate config
            self._config = Config.model_validate(config_data)
            logger.debug("Configuration loaded successfully")
            
            return self._config
            
        except ValidationError as e:
            raise ConfigError(f"Invalid configuration: {e}")
        except Exception as e:
            raise ConfigError(f"Failed to load configuration: {e}")
    
    def _apply_env_overrides(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply environment variable overrides to configuration.
        
        Environment variables should be prefixed with AUTO_ and use double underscores
        to separate nested keys. For example:
        - AUTO_GITHUB__TOKEN -> github.token
        - AUTO_AI__COMMAND -> ai.command
        
        Args:
            config_data: Configuration data to override
            
        Returns:
            Configuration data with environment overrides applied
        """
        for key, value in os.environ.items():
            if not key.startswith("AUTO_"):
                continue
            
            # Remove prefix and split on double underscores
            config_key = key[5:]  # Remove "AUTO_"
            key_parts = config_key.lower().split("__")
            
            # Navigate to the nested dictionary
            current = config_data
            for part in key_parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            
            # Set the value
            final_key = key_parts[-1]
            
            # Try to parse as appropriate type
            if value.lower() in ("true", "false"):
                current[final_key] = value.lower() == "true"
            elif value.isdigit():
                current[final_key] = int(value)
            else:
                try:
                    current[final_key] = float(value)
                except ValueError:
                    current[final_key] = value
            
            logger.debug(f"Applied env override: {'.'.join(key_parts)} = {current[final_key]}")
        
        return config_data
    
    def get_config(self) -> Config:
        """Get current configuration, loading if necessary.
        
        Returns:
            Configuration object
        """
        if self._config is None:
            self._config = self.load_config()
        return self._config
    
    def reload_config(self) -> Config:
        """Reload configuration from all sources.
        
        Returns:
            Reloaded configuration
        """
        self._config = None
        self._find_project_config()
        return self.load_config()
    
    def get_config_value(self, key: str) -> Any:
        """Get configuration value by dot-separated key.
        
        Args:
            key: Dot-separated key (e.g., 'github.token', 'ai.command')
            
        Returns:
            Configuration value
            
        Raises:
            ConfigError: If key is not found
        """
        config = self.get_config()
        
        # Navigate nested structure
        current = config.model_dump()
        key_parts = key.split(".")
        
        try:
            for part in key_parts:
                current = current[part]
            return current
        except (KeyError, TypeError):
            raise ConfigError(f"Configuration key not found: {key}")
    
    def set_config_value(self, key: str, value: Any, user_level: bool = True) -> None:
        """Set configuration value and save to file.
        
        Args:
            key: Dot-separated key (e.g., 'github.token', 'ai.command')
            value: Value to set
            user_level: If True, save to user config; if False, save to project config
            
        Raises:
            ConfigError: If configuration cannot be saved
        """
        config_path = self._user_config_path if user_level else self._project_config_path
        
        if config_path is None and not user_level:
            # Create project config if it doesn't exist
            git_root = get_git_root()
            if git_root:
                config_path = git_root / ".auto" / "config.yaml"
            else:
                config_path = Path.cwd() / ".auto" / "config.yaml"
            
            config_path.parent.mkdir(parents=True, exist_ok=True)
            self._project_config_path = config_path
        
        # Load existing config data
        config_data = self._load_yaml_file(config_path)
        
        # Set the value
        key_parts = key.split(".")
        current = config_data
        
        for part in key_parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        
        current[key_parts[-1]] = value
        
        # Save to file
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_path, "w") as f:
                yaml.safe_dump(config_data, f, default_flow_style=False, sort_keys=False)
            
            logger.info(f"Configuration saved to {config_path}: {key} = {value}")
            
            # Reload config to reflect changes
            self.reload_config()
            
        except Exception as e:
            raise ConfigError(f"Failed to save configuration to {config_path}: {e}")
    
    def create_default_config(self, user_level: bool = True) -> Path:
        """Create default configuration file.
        
        Args:
            user_level: If True, create user config; if False, create project config
            
        Returns:
            Path to created configuration file
            
        Raises:
            ConfigError: If configuration cannot be created
        """
        config_path = self._user_config_path if user_level else None
        
        if not user_level:
            git_root = get_git_root()
            if git_root:
                config_path = git_root / ".auto" / "config.yaml"
            else:
                config_path = Path.cwd() / ".auto" / "config.yaml"
        
        if config_path.exists():
            logger.warning(f"Configuration file already exists: {config_path}")
            return config_path
        
        # Create default config
        default_config = Config()
        config_data = default_config.model_dump(mode="json")  # Use JSON mode to serialize enums as strings
        
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_path, "w") as f:
                f.write("# Auto tool configuration\n")
                f.write("# See https://github.com/trobanga/auto for documentation\n\n")
                yaml.safe_dump(config_data, f, default_flow_style=False, sort_keys=False)
            
            logger.info(f"Default configuration created: {config_path}")
            
            # Update internal state
            if user_level:
                pass  # Already set
            else:
                self._project_config_path = config_path
            
            # Reload config
            self.reload_config()
            
            return config_path
            
        except Exception as e:
            raise ConfigError(f"Failed to create configuration file {config_path}: {e}")
    
    def list_config_files(self) -> Dict[str, Optional[Path]]:
        """List all configuration file paths.
        
        Returns:
            Dictionary with config file types and their paths
        """
        return {
            "user": self._user_config_path if self._user_config_path.exists() else None,
            "project": self._project_config_path,
        }


# Global config manager instance
config_manager = ConfigManager()


def get_config() -> Config:
    """Get current configuration.
    
    Returns:
        Configuration object
    """
    return config_manager.get_config()


def reload_config() -> Config:
    """Reload configuration from all sources.
    
    Returns:
        Reloaded configuration
    """
    return config_manager.reload_config()


def get_config_value(key: str) -> Any:
    """Get configuration value by key.
    
    Args:
        key: Dot-separated configuration key
        
    Returns:
        Configuration value
    """
    return config_manager.get_config_value(key)


def set_config_value(key: str, value: Any, user_level: bool = True) -> None:
    """Set configuration value.
    
    Args:
        key: Dot-separated configuration key
        value: Value to set
        user_level: Whether to save at user or project level
    """
    config_manager.set_config_value(key, value, user_level)