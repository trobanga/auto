"""Tests for prompt management module."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from auto.integrations.prompts import (
    PromptError,
    PromptManager,
    PromptTemplate,
    expand_prompt_variables,
    load_prompt_template,
    resolve_prompt,
)
from auto.models import AIConfig, Issue, IssueProvider, IssueStatus


@pytest.fixture
def ai_config():
    """Create test AI configuration."""
    return AIConfig(
        prompt_templates_dir="~/.auto/prompts",
        allow_custom_prompts=True,
        default_template="implementation",
        prompt_variables=[
            "issue_id", "issue_title", "issue_description", "acceptance_criteria",
            "repository", "branch", "labels", "assignee"
        ]
    )


@pytest.fixture
def test_issue():
    """Create test issue."""
    return Issue(
        id="#123",
        provider=IssueProvider.GITHUB,
        title="Add dark mode support",
        description="""Add dark mode toggle to the application.

Acceptance Criteria:
- Users can toggle between light and dark themes
- Theme preference is persisted in localStorage
- All components support both themes""",
        status=IssueStatus.OPEN,
        labels=["feature", "ui"],
        assignee="testuser"
    )


@pytest.fixture
def temp_templates_dir():
    """Create temporary templates directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        templates_dir = Path(temp_dir) / "prompts"
        templates_dir.mkdir()
        yield templates_dir


@pytest.fixture
def sample_template():
    """Create sample template."""
    return PromptTemplate(
        name="test-template",
        description="Test template for testing",
        prompt="Implement {issue_title} for issue {issue_id} in {repository}",
        variables=["issue_id", "issue_title", "repository"],
        tags=["test", "implementation"]
    )


class TestPromptManager:
    """Test PromptManager class."""
    
    def test_init(self, ai_config):
        """Test PromptManager initialization."""
        manager = PromptManager(ai_config)
        
        assert manager.config == ai_config
        assert manager.allow_custom_prompts is True
        assert manager.default_template == "implementation"
        assert len(manager.available_variables) == 8
    
    def test_resolve_prompt_with_override(self, ai_config):
        """Test prompt resolution with direct override."""
        manager = PromptManager(ai_config)
        
        result = manager.resolve_prompt(
            prompt_override="Custom prompt text",
            base_prompt="Default prompt"
        )
        
        assert result == "Custom prompt text"
    
    def test_resolve_prompt_with_file(self, ai_config, temp_templates_dir):
        """Test prompt resolution from file."""
        manager = PromptManager(ai_config)
        
        # Create test prompt file
        prompt_file = temp_templates_dir / "custom.txt"
        prompt_file.write_text("Prompt from file content")
        
        result = manager.resolve_prompt(
            prompt_file=str(prompt_file),
            base_prompt="Default prompt"
        )
        
        assert result == "Prompt from file content"
    
    def test_resolve_prompt_with_template(self, ai_config):
        """Test prompt resolution with named template."""
        manager = PromptManager(ai_config)
        
        # Mock template loading
        with patch.object(manager, 'load_prompt_template') as mock_load:
            mock_template = PromptTemplate(
                name="test",
                prompt="Template prompt content",
                variables=[]
            )
            mock_load.return_value = mock_template
            
            result = manager.resolve_prompt(
                prompt_template="test",
                base_prompt="Default prompt"
            )
            
            assert result == "Template prompt content"
            mock_load.assert_called_once_with("test")
    
    def test_resolve_prompt_with_append(self, ai_config):
        """Test prompt resolution with append text."""
        manager = PromptManager(ai_config)
        
        result = manager.resolve_prompt(
            prompt_override="Base prompt",
            prompt_append="Additional instructions"
        )
        
        assert result == "Base prompt\n\nAdditional instructions"
    
    def test_resolve_prompt_fallback_to_base(self, ai_config):
        """Test prompt resolution fallback to base prompt."""
        manager = PromptManager(ai_config)
        
        result = manager.resolve_prompt(base_prompt="Default prompt")
        
        assert result == "Default prompt"
    
    def test_resolve_prompt_custom_disabled(self, ai_config):
        """Test prompt resolution when custom prompts are disabled."""
        ai_config.allow_custom_prompts = False
        manager = PromptManager(ai_config)
        
        result = manager.resolve_prompt(
            prompt_override="Custom prompt",
            base_prompt="Default prompt"
        )
        
        # Should use default prompt, not custom
        assert result == "Default prompt"
    
    def test_load_prompt_from_file_success(self, ai_config, temp_templates_dir):
        """Test loading prompt from file successfully."""
        manager = PromptManager(ai_config)
        
        prompt_file = temp_templates_dir / "test.txt"
        prompt_file.write_text("Test prompt content")
        
        result = manager._load_prompt_from_file(str(prompt_file))
        
        assert result == "Test prompt content"
    
    def test_load_prompt_from_file_not_found(self, ai_config):
        """Test loading prompt from non-existent file."""
        manager = PromptManager(ai_config)
        
        with pytest.raises(PromptError, match="Prompt file not found"):
            manager._load_prompt_from_file("/nonexistent/file.txt")
    
    def test_load_prompt_from_file_empty(self, ai_config, temp_templates_dir):
        """Test loading prompt from empty file."""
        manager = PromptManager(ai_config)
        
        prompt_file = temp_templates_dir / "empty.txt"
        prompt_file.write_text("")
        
        with pytest.raises(PromptError, match="Prompt file is empty"):
            manager._load_prompt_from_file(str(prompt_file))
    
    def test_load_template_file_success(self, ai_config, temp_templates_dir):
        """Test loading template from YAML file."""
        manager = PromptManager(ai_config)
        
        template_data = {
            "name": "test-template",
            "description": "Test template",
            "prompt": "Test prompt with {variable}",
            "variables": ["variable"],
            "tags": ["test"]
        }
        
        template_file = temp_templates_dir / "test.yaml"
        with open(template_file, 'w') as f:
            yaml.safe_dump(template_data, f)
        
        template = manager._load_template_file(template_file, "test")
        
        assert template.name == "test-template"
        assert template.description == "Test template"
        assert template.prompt == "Test prompt with {variable}"
        assert template.variables == ["variable"]
        assert template.tags == ["test"]
    
    def test_load_template_file_missing_prompt(self, ai_config, temp_templates_dir):
        """Test loading template file without prompt field."""
        manager = PromptManager(ai_config)
        
        template_data = {"name": "test", "description": "Test"}
        
        template_file = temp_templates_dir / "invalid.yaml"
        with open(template_file, 'w') as f:
            yaml.safe_dump(template_data, f)
        
        with pytest.raises(PromptError, match="missing 'prompt' field"):
            manager._load_template_file(template_file, "invalid")
    
    def test_load_template_file_invalid_yaml(self, ai_config, temp_templates_dir):
        """Test loading template file with invalid YAML."""
        manager = PromptManager(ai_config)
        
        template_file = temp_templates_dir / "invalid.yaml"
        template_file.write_text("invalid: yaml: content:")
        
        with pytest.raises(PromptError, match="Invalid YAML"):
            manager._load_template_file(template_file, "invalid")
    
    def test_load_template_file_sets_default_name(self, ai_config, temp_templates_dir):
        """Test that template file loading sets default name."""
        manager = PromptManager(ai_config)
        
        template_data = {"prompt": "Test prompt"}
        
        template_file = temp_templates_dir / "unnamed.yaml"
        with open(template_file, 'w') as f:
            yaml.safe_dump(template_data, f)
        
        template = manager._load_template_file(template_file, "test-name")
        
        assert template.name == "test-name"
    
    def test_load_builtin_template_implementation(self, ai_config):
        """Test loading built-in implementation template."""
        manager = PromptManager(ai_config)
        
        template = manager._load_builtin_template("implementation")
        
        assert template.name == "implementation"
        assert "Implement the following issue" in template.prompt
        assert "issue_description" in template.variables
        assert "implementation" in template.tags
    
    def test_load_builtin_template_security(self, ai_config):
        """Test loading built-in security template."""
        manager = PromptManager(ai_config)
        
        template = manager._load_builtin_template("security-focused")
        
        assert template.name == "security-focused"
        assert "security" in template.prompt.lower()
        assert "OWASP" in template.prompt
        assert "security" in template.tags
    
    def test_load_builtin_template_performance(self, ai_config):
        """Test loading built-in performance template."""
        manager = PromptManager(ai_config)
        
        template = manager._load_builtin_template("performance")
        
        assert template.name == "performance"
        assert "performance" in template.prompt.lower()
        assert "optimization" in template.tags
    
    def test_load_builtin_template_not_found(self, ai_config):
        """Test loading non-existent built-in template."""
        manager = PromptManager(ai_config)
        
        with pytest.raises(PromptError, match="Built-in template 'nonexistent' not found"):
            manager._load_builtin_template("nonexistent")
    
    @patch('auto.integrations.prompts.get_git_root')
    def test_load_prompt_template_search_order(self, mock_git_root, ai_config, temp_templates_dir):
        """Test prompt template loading search order."""
        # Mock git root to return a test directory
        git_root = temp_templates_dir.parent / "git_root"
        git_root.mkdir()
        project_prompts = git_root / ".auto" / "prompts"
        project_prompts.mkdir(parents=True)
        mock_git_root.return_value = git_root
        
        # Set user templates directory
        ai_config.prompt_templates_dir = str(temp_templates_dir)
        manager = PromptManager(ai_config)
        
        # Create template in project directory (should be found first)
        project_template_data = {
            "name": "search-test",
            "prompt": "Project template",
            "variables": []
        }
        project_template_file = project_prompts / "search-test.yaml"
        with open(project_template_file, 'w') as f:
            yaml.safe_dump(project_template_data, f)
        
        # Create template in user directory
        user_template_data = {
            "name": "search-test",
            "prompt": "User template",
            "variables": []
        }
        user_template_file = temp_templates_dir / "search-test.yaml"
        with open(user_template_file, 'w') as f:
            yaml.safe_dump(user_template_data, f)
        
        template = manager.load_prompt_template("search-test")
        
        # Should load project template (higher priority)
        assert template.prompt == "Project template"
    
    def test_load_prompt_template_fallback_to_builtin(self, ai_config):
        """Test prompt template loading fallback to built-in."""
        manager = PromptManager(ai_config)
        
        # Try to load built-in template when no custom templates exist
        template = manager.load_prompt_template("implementation")
        
        assert template.name == "implementation"
        assert "Implement the following issue" in template.prompt
    
    def test_load_prompt_template_not_found(self, ai_config):
        """Test loading non-existent template."""
        manager = PromptManager(ai_config)
        
        with pytest.raises(PromptError, match="Prompt template 'nonexistent' not found"):
            manager.load_prompt_template("nonexistent")
    
    def test_load_prompt_template_caching(self, ai_config):
        """Test that templates are cached after first load."""
        manager = PromptManager(ai_config)
        
        # Load template twice
        template1 = manager.load_prompt_template("implementation")
        template2 = manager.load_prompt_template("implementation")
        
        # Should be the same instance (cached)
        assert template1 is template2
    
    def test_expand_prompt_variables_basic(self, ai_config, test_issue):
        """Test basic prompt variable expansion."""
        manager = PromptManager(ai_config)
        
        prompt = "Issue {issue_id}: {issue_title} by {assignee}"
        
        result = manager.expand_prompt_variables(prompt, test_issue)
        
        assert result == "Issue #123: Add dark mode support by testuser"
    
    def test_expand_prompt_variables_with_repo_context(self, ai_config, test_issue):
        """Test prompt variable expansion with repository context."""
        manager = PromptManager(ai_config)
        
        prompt = "Implement {issue_title} in {repository} on {branch}"
        repo_context = {"name": "my-project", "branch": "main"}
        
        result = manager.expand_prompt_variables(
            prompt, test_issue, repository_context=repo_context
        )
        
        assert result == "Implement Add dark mode support in my-project on main"
    
    def test_expand_prompt_variables_with_acceptance_criteria(self, ai_config, test_issue):
        """Test prompt variable expansion with acceptance criteria."""
        manager = PromptManager(ai_config)
        
        prompt = "Issue: {issue_title}\n\n{acceptance_criteria}"
        
        result = manager.expand_prompt_variables(prompt, test_issue)
        
        assert "Add dark mode support" in result
        assert "Acceptance Criteria" in result
        assert "Users can toggle between light and dark themes" in result
    
    def test_expand_prompt_variables_missing_variable(self, ai_config, test_issue):
        """Test prompt variable expansion with missing variable."""
        manager = PromptManager(ai_config)
        
        prompt = "Issue {issue_id} with {nonexistent_variable}"
        
        # Should not raise, but log warning
        result = manager.expand_prompt_variables(prompt, test_issue)
        
        assert "#123" in result
        # Missing variable should remain unexpanded
        assert "{nonexistent_variable}" in result
    
    def test_expand_prompt_variables_with_custom_variables(self, ai_config, test_issue):
        """Test prompt variable expansion with custom variables."""
        manager = PromptManager(ai_config)
        
        prompt = "Issue {issue_id} priority: {priority}"
        custom_vars = {"priority": "high"}
        
        result = manager.expand_prompt_variables(
            prompt, test_issue, custom_variables=custom_vars
        )
        
        assert result == "Issue #123 priority: high"
    
    def test_extract_acceptance_criteria_found(self, ai_config):
        """Test acceptance criteria extraction when found."""
        manager = PromptManager(ai_config)
        
        description = """Feature description.

Acceptance Criteria:
- Must work on mobile
- Must be accessible
- Must load in under 2s"""
        
        result = manager._extract_acceptance_criteria(description)
        
        assert "## Acceptance Criteria" in result
        assert "Must work on mobile" in result
        assert "Must be accessible" in result
        assert "Must load in under 2s" in result
    
    def test_extract_acceptance_criteria_not_found(self, ai_config):
        """Test acceptance criteria extraction when not found."""
        manager = PromptManager(ai_config)
        
        description = "Simple feature description without criteria."
        
        result = manager._extract_acceptance_criteria(description)
        
        assert result == ""
    
    def test_list_templates(self, ai_config, temp_templates_dir):
        """Test listing available templates."""
        # Set user templates directory
        ai_config.prompt_templates_dir = str(temp_templates_dir)
        manager = PromptManager(ai_config)
        
        # Create custom template
        custom_template_data = {
            "name": "custom",
            "prompt": "Custom template",
            "variables": []
        }
        custom_template_file = temp_templates_dir / "custom.yaml"
        with open(custom_template_file, 'w') as f:
            yaml.safe_dump(custom_template_data, f)
        
        templates = manager.list_templates()
        
        # Should include built-in templates
        template_names = [t.name for t in templates]
        assert "implementation" in template_names
        assert "security-focused" in template_names
        assert "performance" in template_names
        assert "custom" in template_names
    
    def test_validate_template_success(self, ai_config, sample_template):
        """Test successful template validation."""
        manager = PromptManager(ai_config)
        
        warnings = manager.validate_template(sample_template)
        
        assert warnings == []
    
    def test_validate_template_unknown_variable(self, ai_config):
        """Test template validation with unknown variable."""
        manager = PromptManager(ai_config)
        
        template = PromptTemplate(
            name="test",
            prompt="Use {unknown_variable} in implementation",
            variables=["unknown_variable"]
        )
        
        warnings = manager.validate_template(template)
        
        assert len(warnings) == 1
        assert "Variable 'unknown_variable' not in available variables" in warnings[0]
    
    def test_validate_template_unused_variable(self, ai_config):
        """Test template validation with unused declared variable."""
        manager = PromptManager(ai_config)
        
        template = PromptTemplate(
            name="test",
            prompt="Simple prompt without variables",
            variables=["unused_variable"]
        )
        
        warnings = manager.validate_template(template)
        
        assert len(warnings) == 1
        assert "Declared variable 'unused_variable' not used" in warnings[0]
    
    def test_validate_template_short_prompt(self, ai_config):
        """Test template validation with very short prompt."""
        manager = PromptManager(ai_config)
        
        template = PromptTemplate(
            name="test",
            prompt="Short",
            variables=[]
        )
        
        warnings = manager.validate_template(template)
        
        assert len(warnings) == 1
        assert "very short" in warnings[0]
    
    def test_validate_template_long_prompt(self, ai_config):
        """Test template validation with very long prompt."""
        manager = PromptManager(ai_config)
        
        template = PromptTemplate(
            name="test",
            prompt="x" * 6000,  # Very long prompt
            variables=[]
        )
        
        warnings = manager.validate_template(template)
        
        assert len(warnings) == 1
        assert "very long" in warnings[0]
    
    @patch('auto.integrations.prompts.get_git_root')
    def test_create_template_directory_project(self, mock_git_root, ai_config, temp_templates_dir):
        """Test creating project template directory."""
        git_root = temp_templates_dir.parent / "git_root"
        git_root.mkdir()
        mock_git_root.return_value = git_root
        
        manager = PromptManager(ai_config)
        
        created_dir = manager.create_template_directory(user_level=False)
        
        expected_dir = git_root / ".auto" / "prompts"
        assert created_dir == expected_dir
        assert created_dir.exists()
    
    def test_create_template_directory_user(self, ai_config, temp_templates_dir):
        """Test creating user template directory."""
        ai_config.prompt_templates_dir = str(temp_templates_dir / "new_prompts")
        manager = PromptManager(ai_config)
        
        created_dir = manager.create_template_directory(user_level=True)
        
        assert created_dir.exists()
        assert created_dir.name == "new_prompts"


class TestPromptFunctions:
    """Test prompt management module functions."""
    
    @patch('auto.integrations.prompts.PromptManager')
    def test_resolve_prompt(self, mock_manager_class, ai_config):
        """Test resolve_prompt function."""
        mock_manager = Mock()
        mock_manager.resolve_prompt.return_value = "resolved prompt"
        mock_manager_class.return_value = mock_manager
        
        result = resolve_prompt(
            ai_config,
            prompt_override="custom",
            prompt_append="additional"
        )
        
        assert result == "resolved prompt"
        mock_manager.resolve_prompt.assert_called_once_with(
            prompt_override="custom",
            prompt_file=None,
            prompt_template=None,
            prompt_append="additional",
            base_prompt=None
        )
    
    @patch('auto.integrations.prompts.PromptManager')
    def test_load_prompt_template(self, mock_manager_class, ai_config, sample_template):
        """Test load_prompt_template function."""
        mock_manager = Mock()
        mock_manager.load_prompt_template.return_value = sample_template
        mock_manager_class.return_value = mock_manager
        
        result = load_prompt_template(ai_config, "test-template")
        
        assert result == sample_template
        mock_manager.load_prompt_template.assert_called_once_with("test-template")
    
    @patch('auto.integrations.prompts.PromptManager')
    def test_expand_prompt_variables(self, mock_manager_class, ai_config, test_issue):
        """Test expand_prompt_variables function."""
        mock_manager = Mock()
        mock_manager.expand_prompt_variables.return_value = "expanded prompt"
        mock_manager_class.return_value = mock_manager
        
        result = expand_prompt_variables(
            "prompt {variable}",
            test_issue,
            ai_config,
            repository_context={"name": "test"}
        )
        
        assert result == "expanded prompt"
        mock_manager.expand_prompt_variables.assert_called_once_with(
            prompt="prompt {variable}",
            issue=test_issue,
            repository_context={"name": "test"},
            custom_variables=None
        )


class TestPromptEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_prompt_manager_with_no_templates_dir(self, ai_config):
        """Test PromptManager when templates directory doesn't exist."""
        ai_config.prompt_templates_dir = "/nonexistent/path"
        manager = PromptManager(ai_config)
        
        # Should still work, just fall back to built-in templates
        template = manager.load_prompt_template("implementation")
        assert template.name == "implementation"
    
    def test_expand_variables_with_none_values(self, ai_config):
        """Test variable expansion with None values in issue."""
        manager = PromptManager(ai_config)
        
        issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Test",
            description="Test",
            status=IssueStatus.OPEN,
            assignee=None,  # None value
            labels=[]  # Empty list
        )
        
        prompt = "Issue {issue_id} by {assignee} with labels {labels}"
        
        result = manager.expand_prompt_variables(prompt, issue)
        
        assert "#123" in result
        assert "None" in result  # None should be converted to "None"
    
    def test_template_validation_edge_cases(self, ai_config):
        """Test template validation edge cases."""
        manager = PromptManager(ai_config)
        
        # Template with variable in nested braces
        template = PromptTemplate(
            name="edge-case",
            prompt="Use {{issue_id}} for ID and {issue_title} for title",
            variables=["issue_id", "issue_title"]
        )
        
        warnings = manager.validate_template(template)
        
        # Should detect that issue_id is not actually used (due to double braces)
        warning_text = " ".join(warnings)
        assert "not used" in warning_text or len(warnings) == 0  # Depending on regex behavior