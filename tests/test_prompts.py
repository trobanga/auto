"""Tests for prompt management module."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

from auto.integrations.prompts import (
    PromptManager,
    PromptTemplate,
    PromptError,
    resolve_prompt,
    load_prompt_template,
    expand_prompt_variables,
    list_available_templates
)
from auto.models import Issue, IssueProvider, IssueStatus


@pytest.fixture
def sample_issue():
    """Sample issue for testing."""
    return Issue(
        id="#123",
        provider=IssueProvider.GITHUB,
        title="Add dark mode support",
        description="Implement a dark mode toggle for the application",
        status=IssueStatus.OPEN,
        labels=["feature", "ui"],
        assignee="developer"
    )


@pytest.fixture
def prompt_manager():
    """PromptManager instance for testing."""
    return PromptManager()


@pytest.fixture
def sample_template():
    """Sample prompt template for testing."""
    return PromptTemplate(
        name="test-template",
        content="Implement {title} with focus on {custom_focus}",
        description="Test template",
        variables=["title", "custom_focus"],
        metadata={"category": "implementation"}
    )


class TestPromptTemplate:
    """Test PromptTemplate dataclass."""

    def test_init_with_defaults(self):
        """Test PromptTemplate initialization with defaults."""
        template = PromptTemplate(
            name="test",
            content="Test content"
        )
        
        assert template.name == "test"
        assert template.content == "Test content"
        assert template.description == ""
        assert template.variables == []
        assert template.metadata == {}

    def test_init_with_all_fields(self):
        """Test PromptTemplate initialization with all fields."""
        template = PromptTemplate(
            name="test",
            content="Test content",
            description="Test description",
            variables=["var1", "var2"],
            metadata={"key": "value"}
        )
        
        assert template.name == "test"
        assert template.content == "Test content"
        assert template.description == "Test description"
        assert template.variables == ["var1", "var2"]
        assert template.metadata == {"key": "value"}


class TestPromptManager:
    """Test PromptManager class."""

    def test_init(self):
        """Test PromptManager initialization."""
        manager = PromptManager()
        assert manager.config_dir is None
        assert manager._template_cache == {}
        
        manager_with_config = PromptManager("/custom/config")
        assert manager_with_config.config_dir == "/custom/config"

    def test_resolve_prompt_with_override(self, prompt_manager, sample_issue):
        """Test prompt resolution with direct override."""
        override_prompt = "Custom implementation prompt"
        
        result = prompt_manager.resolve_prompt(
            issue=sample_issue,
            prompt_override=override_prompt
        )
        
        assert result == override_prompt

    def test_resolve_prompt_with_file(self, prompt_manager, sample_issue, tmp_path):
        """Test prompt resolution from file."""
        prompt_file = tmp_path / "custom_prompt.txt"
        prompt_content = "Implement the feature with testing focus"
        prompt_file.write_text(prompt_content)
        
        result = prompt_manager.resolve_prompt(
            issue=sample_issue,
            prompt_file=str(prompt_file)
        )
        
        assert prompt_content in result

    def test_resolve_prompt_with_template(self, prompt_manager, sample_issue):
        """Test prompt resolution with template."""
        with patch.object(prompt_manager, 'load_prompt_template') as mock_load:
            mock_template = PromptTemplate(
                name="security-focused",
                content="Implement {title} with security focus",
                description="Security template"
            )
            mock_load.return_value = mock_template
            
            result = prompt_manager.resolve_prompt(
                issue=sample_issue,
                prompt_template="security-focused"
            )
            
            assert "Add dark mode support" in result
            assert "security focus" in result
            mock_load.assert_called_once_with("security-focused")

    def test_resolve_prompt_with_append(self, prompt_manager, sample_issue):
        """Test prompt resolution with append text."""
        default_prompt = "Basic implementation"
        append_text = "Make sure to add comprehensive tests"
        
        result = prompt_manager.resolve_prompt(
            issue=sample_issue,
            default_prompt=default_prompt,
            prompt_append=append_text
        )
        
        assert "Basic implementation" in result
        assert "comprehensive tests" in result

    def test_resolve_prompt_no_source(self, prompt_manager, sample_issue):
        """Test prompt resolution with no source raises error."""
        with pytest.raises(PromptError) as excinfo:
            prompt_manager.resolve_prompt(issue=sample_issue)
        
        assert "No prompt source provided" in str(excinfo.value)

    def test_resolve_prompt_with_variables(self, prompt_manager, sample_issue):
        """Test prompt resolution with custom variables."""
        template_content = "Implement {title} for {target_platform}"
        variables = {"target_platform": "mobile"}
        
        result = prompt_manager.resolve_prompt(
            issue=sample_issue,
            prompt_override=template_content,
            variables=variables
        )
        
        assert "Add dark mode support" in result
        assert "mobile" in result

    def test_load_prompt_template_from_cache(self, prompt_manager):
        """Test template loading from cache."""
        cached_template = PromptTemplate(
            name="cached",
            content="Cached content"
        )
        prompt_manager._template_cache["cached"] = cached_template
        
        result = prompt_manager.load_prompt_template("cached")
        
        assert result == cached_template

    def test_load_prompt_template_from_file(self, prompt_manager, tmp_path):
        """Test template loading from file."""
        template_dir = tmp_path / "templates" / "prompts"
        template_dir.mkdir(parents=True)
        
        template_file = template_dir / "test-template.yaml"
        template_data = {
            "description": "Test template",
            "content": "Implement {title} with focus",
            "variables": ["title"],
            "metadata": {"category": "test"}
        }
        template_file.write_text(yaml.dump(template_data))
        
        with patch.object(prompt_manager, '_get_template_search_paths', return_value=[template_dir]):
            result = prompt_manager.load_prompt_template("test-template")
        
        assert result.name == "test-template"
        assert result.content == "Implement {title} with focus"
        assert result.description == "Test template"
        assert result.variables == ["title"]
        assert result.metadata == {"category": "test"}

    def test_load_prompt_template_not_found(self, prompt_manager):
        """Test template loading when template not found."""
        with patch.object(prompt_manager, '_get_template_search_paths', return_value=[]):
            with pytest.raises(PromptError) as excinfo:
                prompt_manager.load_prompt_template("nonexistent")
        
        assert "Template 'nonexistent' not found" in str(excinfo.value)

    def test_expand_prompt_variables(self, prompt_manager, sample_issue):
        """Test prompt variable expansion."""
        prompt = "Issue: {id} - {title} ({labels})"
        
        result = prompt_manager.expand_prompt_variables(prompt, sample_issue)
        
        assert "#123" in result
        assert "Add dark mode support" in result
        assert "feature, ui" in result

    def test_expand_prompt_variables_with_additional(self, prompt_manager, sample_issue):
        """Test prompt variable expansion with additional variables."""
        prompt = "Issue: {title} for {platform}"
        additional_vars = {"platform": "web"}
        
        result = prompt_manager.expand_prompt_variables(
            prompt, 
            sample_issue, 
            additional_vars
        )
        
        assert "Add dark mode support" in result
        assert "web" in result

    def test_expand_prompt_variables_missing_variable(self, prompt_manager, sample_issue):
        """Test prompt variable expansion with missing variable."""
        prompt = "Issue: {title} - {missing_var}"
        
        # Should not raise, should handle gracefully
        result = prompt_manager.expand_prompt_variables(prompt, sample_issue)
        
        assert "Add dark mode support" in result
        assert "[missing_var]" in result or "missing_var" in result

    def test_list_available_templates(self, prompt_manager, tmp_path):
        """Test listing available templates."""
        template_dir = tmp_path / "templates" / "prompts"
        template_dir.mkdir(parents=True)
        
        (template_dir / "template1.yaml").write_text("content: test1")
        (template_dir / "template2.yaml").write_text("content: test2")
        (template_dir / "not-yaml.txt").write_text("not a template")
        
        with patch.object(prompt_manager, '_get_template_search_paths', return_value=[template_dir]):
            templates = prompt_manager.list_available_templates()
        
        assert "template1" in templates
        assert "template2" in templates
        assert "not-yaml" not in templates
        assert len(templates) == 2

    def test_validate_template_exists(self, prompt_manager):
        """Test template validation for existing template."""
        with patch.object(prompt_manager, 'load_prompt_template') as mock_load:
            mock_load.return_value = PromptTemplate(name="test", content="test")
            
            assert prompt_manager.validate_template("test") is True
            mock_load.assert_called_once_with("test")

    def test_validate_template_not_exists(self, prompt_manager):
        """Test template validation for non-existing template."""
        with patch.object(prompt_manager, 'load_prompt_template', side_effect=PromptError("Not found")):
            
            assert prompt_manager.validate_template("nonexistent") is False

    def test_create_template(self, prompt_manager, tmp_path):
        """Test template creation."""
        with patch.object(prompt_manager, '_get_user_templates_dir', return_value=tmp_path):
            template_file = prompt_manager.create_template(
                "new-template",
                "Implement {title} carefully",
                "Careful implementation template"
            )
            
            assert template_file.exists()
            assert template_file.name == "new-template.yaml"
            
            # Verify content
            with open(template_file) as f:
                data = yaml.safe_load(f)
            
            assert data["description"] == "Careful implementation template"
            assert data["content"] == "Implement {title} carefully"
            assert "title" in data["variables"]

    def test_load_prompt_from_file(self, prompt_manager, tmp_path):
        """Test loading prompt from file."""
        prompt_file = tmp_path / "prompt.txt"
        prompt_content = "Custom prompt content"
        prompt_file.write_text(prompt_content)
        
        result = prompt_manager._load_prompt_from_file(str(prompt_file))
        
        assert result == prompt_content

    def test_load_prompt_from_file_not_found(self, prompt_manager):
        """Test loading prompt from non-existent file."""
        with pytest.raises(PromptError) as excinfo:
            prompt_manager._load_prompt_from_file("/nonexistent/file.txt")
        
        assert "Prompt file not found" in str(excinfo.value)

    def test_load_prompt_from_file_empty(self, prompt_manager, tmp_path):
        """Test loading prompt from empty file."""
        prompt_file = tmp_path / "empty.txt"
        prompt_file.write_text("")
        
        with pytest.raises(PromptError) as excinfo:
            prompt_manager._load_prompt_from_file(str(prompt_file))
        
        assert "Prompt file is empty" in str(excinfo.value)

    def test_load_template_file_invalid_yaml(self, prompt_manager, tmp_path):
        """Test loading template with invalid YAML."""
        template_file = tmp_path / "invalid.yaml"
        template_file.write_text("invalid: yaml: content:")
        
        with pytest.raises(PromptError) as excinfo:
            prompt_manager._load_template_file(template_file)
        
        assert "Invalid YAML" in str(excinfo.value)

    def test_load_template_file_missing_content(self, prompt_manager, tmp_path):
        """Test loading template without content field."""
        template_file = tmp_path / "no-content.yaml"
        template_data = {"description": "No content"}
        template_file.write_text(yaml.dump(template_data))
        
        with pytest.raises(PromptError) as excinfo:
            prompt_manager._load_template_file(template_file)
        
        assert "missing 'content' field" in str(excinfo.value)

    def test_get_template_search_paths(self, prompt_manager):
        """Test template search paths generation."""
        with patch.object(prompt_manager, '_get_project_templates_dir', return_value=Path("/project")), \
             patch.object(prompt_manager, '_get_user_templates_dir', return_value=Path("/user")), \
             patch.object(prompt_manager, '_get_builtin_templates_dir', return_value=Path("/builtin")):
            
            paths = prompt_manager._get_template_search_paths()
            
            assert len(paths) == 3
            assert paths[0] == Path("/project")  # Highest precedence
            assert paths[1] == Path("/user")
            assert paths[2] == Path("/builtin")   # Lowest precedence

    def test_get_project_templates_dir_with_config(self, prompt_manager):
        """Test project templates directory with config."""
        prompt_manager.config_dir = "/custom/config"
        
        result = prompt_manager._get_project_templates_dir()
        
        assert result == Path("/custom/config/templates/prompts")

    def test_get_project_templates_dir_auto_detect(self, prompt_manager, tmp_path):
        """Test project templates directory auto-detection."""
        # Create .auto directory
        auto_dir = tmp_path / ".auto"
        auto_dir.mkdir()
        
        with patch('pathlib.Path.cwd', return_value=tmp_path):
            result = prompt_manager._get_project_templates_dir()
        
        assert result == auto_dir / "templates" / "prompts"

    def test_get_user_templates_dir(self, prompt_manager):
        """Test user templates directory."""
        with patch('pathlib.Path.home', return_value=Path("/home/user")):
            result = prompt_manager._get_user_templates_dir()
        
        assert result == Path("/home/user/.auto/templates/prompts")

    def test_get_builtin_templates_dir(self, prompt_manager):
        """Test builtin templates directory."""
        result = prompt_manager._get_builtin_templates_dir()
        
        # Should be relative to the prompts.py file
        assert "auto/templates/prompts" in str(result)

    def test_build_variable_context(self, prompt_manager, sample_issue):
        """Test variable context building."""
        additional_vars = {"custom_var": "custom_value"}
        
        context = prompt_manager._build_variable_context(sample_issue, additional_vars)
        
        assert context["id"] == "#123"
        assert context["title"] == "Add dark mode support"
        assert context["description"] == sample_issue.description
        assert context["labels"] == "feature, ui"
        assert context["assignee"] == "developer"
        assert context["custom_var"] == "custom_value"

    def test_safe_format_success(self, prompt_manager):
        """Test safe formatting with all variables available."""
        template = "Issue {id}: {title}"
        variables = {"id": "#123", "title": "Test"}
        
        result = prompt_manager._safe_format(template, variables)
        
        assert result == "Issue #123: Test"

    def test_safe_format_missing_variable(self, prompt_manager):
        """Test safe formatting with missing variable."""
        template = "Issue {id}: {missing_var}"
        variables = {"id": "#123"}
        
        result = prompt_manager._safe_format(template, variables)
        
        assert "#123" in result
        assert "[missing_var]" in result or "missing_var" in result

    def test_regex_format(self, prompt_manager):
        """Test regex-based formatting."""
        template = "Issue {id}: {title} - {missing}"
        variables = {"id": "#123", "title": "Test"}
        
        result = prompt_manager._regex_format(template, variables)
        
        assert result == "Issue #123: Test - [missing]"

    def test_extract_template_variables(self, prompt_manager):
        """Test template variable extraction."""
        content = "Implement {title} for {platform} with {focus}"
        
        variables = prompt_manager._extract_template_variables(content)
        
        assert variables == ["focus", "platform", "title"]  # Sorted


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_resolve_prompt(self, sample_issue):
        """Test resolve_prompt convenience function."""
        with patch('auto.integrations.prompts.PromptManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.resolve_prompt.return_value = "resolved prompt"
            mock_manager_class.return_value = mock_manager
            
            result = resolve_prompt(
                issue=sample_issue,
                prompt_override="test prompt"
            )
            
            assert result == "resolved prompt"
            mock_manager.resolve_prompt.assert_called_once()

    def test_load_prompt_template(self):
        """Test load_prompt_template convenience function."""
        with patch('auto.integrations.prompts.PromptManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_template = PromptTemplate(name="test", content="test")
            mock_manager.load_prompt_template.return_value = mock_template
            mock_manager_class.return_value = mock_manager
            
            result = load_prompt_template("test-template")
            
            assert result == mock_template
            mock_manager.load_prompt_template.assert_called_once_with("test-template")

    def test_expand_prompt_variables(self, sample_issue):
        """Test expand_prompt_variables convenience function."""
        with patch('auto.integrations.prompts.PromptManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.expand_prompt_variables.return_value = "expanded prompt"
            mock_manager_class.return_value = mock_manager
            
            result = expand_prompt_variables(
                "Test {title}",
                sample_issue
            )
            
            assert result == "expanded prompt"
            mock_manager.expand_prompt_variables.assert_called_once()

    def test_list_available_templates(self):
        """Test list_available_templates convenience function."""
        with patch('auto.integrations.prompts.PromptManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_available_templates.return_value = ["template1", "template2"]
            mock_manager_class.return_value = mock_manager
            
            result = list_available_templates()
            
            assert result == ["template1", "template2"]
            mock_manager.list_available_templates.assert_called_once()


class TestPromptError:
    """Test PromptError exception."""

    def test_prompt_error(self):
        """Test PromptError exception."""
        error = PromptError("Test error message")
        assert str(error) == "Test error message"