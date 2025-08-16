"""Tests for AI integration module."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from auto.integrations.ai import (
    AIError,
    ClaudeIntegration,
    execute_ai_command,
    format_implementation_prompt,
    parse_ai_response,
    validate_ai_prerequisites,
)
from auto.models import AIConfig, AIResponse, Issue, IssueProvider, IssueStatus


@pytest.fixture
def ai_config():
    """Create test AI configuration."""
    return AIConfig(
        command="claude",
        implementation_agent="coder",
        review_agent="pull-request-reviewer",
        update_agent="coder",
        timeout=60,
        max_retries=1,
        response_format="structured"
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
- All components support both themes
- Smooth transition between themes""",
        status=IssueStatus.OPEN,
        labels=["feature", "ui"],
        assignee="testuser"
    )


class TestClaudeIntegration:
    """Test ClaudeIntegration class."""
    
    def test_init(self, ai_config):
        """Test ClaudeIntegration initialization."""
        integration = ClaudeIntegration(ai_config)
        
        assert integration.config == ai_config
        assert integration.command == "claude"
        assert integration.implementation_agent == "coder"
        assert integration.timeout == 60
        assert integration.max_retries == 1
    
    @patch('auto.integrations.ai.run_command')
    def test_validate_ai_prerequisites_success(self, mock_run_command, ai_config):
        """Test successful AI prerequisites validation."""
        # Mock successful claude --version command
        mock_run_command.return_value = Mock(
            returncode=0,
            stdout="claude version 1.0.0",
            stderr=""
        )
        
        integration = ClaudeIntegration(ai_config)
        
        # Should not raise
        integration.validate_ai_prerequisites()
        
        mock_run_command.assert_called_once_with(
            ["claude", "--version"],
            capture_output=True,
            timeout=10
        )
    
    @patch('auto.integrations.ai.run_command')
    def test_validate_ai_prerequisites_claude_not_available(self, mock_run_command, ai_config):
        """Test AI prerequisites validation when Claude CLI is not available."""
        # Mock failed claude --version command
        mock_run_command.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="command not found"
        )
        
        integration = ClaudeIntegration(ai_config)
        
        with pytest.raises(AIError, match="Claude CLI not available"):
            integration.validate_ai_prerequisites()
    
    @patch('auto.integrations.ai.run_command')
    def test_validate_ai_prerequisites_timeout(self, mock_run_command, ai_config):
        """Test AI prerequisites validation timeout."""
        # Mock timeout exception
        mock_run_command.side_effect = subprocess.TimeoutExpired("claude", 10)
        
        integration = ClaudeIntegration(ai_config)
        
        with pytest.raises(AIError, match="Claude CLI command timed out"):
            integration.validate_ai_prerequisites()
    
    def test_validate_ai_prerequisites_invalid_agent(self):
        """Test AI prerequisites validation with invalid agent."""
        config = AIConfig(implementation_agent="")
        integration = ClaudeIntegration(config)
        
        with pytest.raises(AIError, match="Invalid agent configuration"):
            integration.validate_ai_prerequisites()
    
    @patch('auto.integrations.ai.run_command')
    def test_execute_ai_command_success(self, mock_run_command, ai_config):
        """Test successful AI command execution."""
        # Mock successful command execution
        mock_run_command.return_value = Mock(
            returncode=0,
            stdout="AI response here",
            stderr=""
        )
        
        integration = ClaudeIntegration(ai_config)
        result = integration.execute_ai_command("test prompt", "coder")
        
        assert result == "AI response here"
        mock_run_command.assert_called_once_with(
            ["claude", "--agent", "coder", "test prompt"],
            capture_output=True,
            timeout=60,
            cwd=None,
            input=None
        )
    
    @patch('auto.integrations.ai.run_command')
    def test_execute_ai_command_long_prompt_uses_stdin(self, mock_run_command, ai_config):
        """Test AI command execution with long prompt uses stdin."""
        # Mock successful command execution
        mock_run_command.return_value = Mock(
            returncode=0,
            stdout="AI response here",
            stderr=""
        )
        
        long_prompt = "x" * 1500  # Longer than 1000 chars
        
        integration = ClaudeIntegration(ai_config)
        result = integration.execute_ai_command(long_prompt, "coder")
        
        assert result == "AI response here"
        mock_run_command.assert_called_once_with(
            ["claude", "--agent", "coder"],
            capture_output=True,
            timeout=60,
            cwd=None,
            input=long_prompt
        )
    
    @patch('auto.integrations.ai.run_command')
    def test_execute_ai_command_with_working_directory(self, mock_run_command, ai_config):
        """Test AI command execution with working directory."""
        mock_run_command.return_value = Mock(
            returncode=0,
            stdout="AI response",
            stderr=""
        )
        
        integration = ClaudeIntegration(ai_config)
        result = integration.execute_ai_command(
            "test prompt",
            "coder",
            working_directory="/tmp/test"
        )
        
        assert result == "AI response"
        mock_run_command.assert_called_once_with(
            ["claude", "--agent", "coder", "test prompt"],
            capture_output=True,
            timeout=60,
            cwd="/tmp/test",
            input=None
        )
    
    @patch('auto.integrations.ai.run_command')
    def test_execute_ai_command_failure(self, mock_run_command, ai_config):
        """Test AI command execution failure."""
        # Mock failed command execution
        mock_run_command.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="Agent not found"
        )
        
        integration = ClaudeIntegration(ai_config)
        
        with pytest.raises(AIError, match="Claude CLI failed: Agent not found"):
            integration.execute_ai_command("test prompt", "invalid-agent")
    
    @patch('auto.integrations.ai.run_command')
    def test_execute_ai_command_timeout(self, mock_run_command, ai_config):
        """Test AI command execution timeout."""
        # Mock timeout exception
        mock_run_command.side_effect = subprocess.TimeoutExpired("claude", 60)
        
        integration = ClaudeIntegration(ai_config)
        
        with pytest.raises(AIError, match="Claude CLI command timed out"):
            integration.execute_ai_command("test prompt", "coder")
    
    @patch('auto.integrations.ai.run_command')
    def test_execute_ai_command_retries(self, mock_run_command, ai_config):
        """Test AI command execution with retries."""
        # First call fails, second succeeds
        mock_run_command.side_effect = [
            Mock(returncode=1, stdout="", stderr="Temporary error"),
            Mock(returncode=0, stdout="Success", stderr="")
        ]
        
        integration = ClaudeIntegration(ai_config)
        result = integration.execute_ai_command("test prompt", "coder")
        
        assert result == "Success"
        assert mock_run_command.call_count == 2
    
    def test_format_implementation_prompt_basic(self, ai_config, test_issue):
        """Test basic implementation prompt formatting."""
        integration = ClaudeIntegration(ai_config)
        
        prompt = integration.format_implementation_prompt(test_issue)
        
        assert "#123" in prompt
        assert "Add dark mode support" in prompt
        assert "Users can toggle between light and dark themes" in prompt
        assert "feature, ui" in prompt
        assert "testuser" in prompt
    
    def test_format_implementation_prompt_with_custom_prompt(self, ai_config, test_issue):
        """Test implementation prompt formatting with custom prompt."""
        integration = ClaudeIntegration(ai_config)
        custom_prompt = "Custom implementation prompt for {issue_title} ({issue_id})"
        
        prompt = integration.format_implementation_prompt(
            test_issue,
            custom_prompt=custom_prompt
        )
        
        assert "Custom implementation prompt for Add dark mode support (#123)" in prompt
    
    def test_format_implementation_prompt_with_repository_context(self, ai_config, test_issue):
        """Test implementation prompt formatting with repository context."""
        integration = ClaudeIntegration(ai_config)
        repo_context = {
            "name": "my-project",
            "branch": "feature-branch",
            "file_structure": "src/\n  components/\n  utils/",
            "coding_standards": "Use TypeScript and ESLint"
        }
        
        prompt = integration.format_implementation_prompt(
            test_issue,
            repository_context=repo_context
        )
        
        assert "my-project" in prompt
        assert "feature-branch" in prompt
        assert "File Structure" in prompt
        assert "src/" in prompt
        assert "Coding Standards" in prompt
        assert "TypeScript" in prompt
    
    def test_extract_acceptance_criteria(self, ai_config):
        """Test acceptance criteria extraction."""
        integration = ClaudeIntegration(ai_config)
        
        description = """Feature description here.

Acceptance Criteria:
- Criterion 1
- Criterion 2
- Criterion 3

Additional notes."""
        
        criteria = integration._extract_acceptance_criteria(description)
        assert "Criterion 1" in criteria
        assert "Criterion 2" in criteria
        assert "Criterion 3" in criteria
    
    def test_extract_acceptance_criteria_alternative_format(self, ai_config):
        """Test acceptance criteria extraction with alternative formats."""
        integration = ClaudeIntegration(ai_config)
        
        # Test with "AC:" format
        description = """Feature description.

AC:
- Must do this
- Must do that"""
        
        criteria = integration._extract_acceptance_criteria(description)
        assert "Must do this" in criteria
        assert "Must do that" in criteria
    
    def test_extract_acceptance_criteria_not_found(self, ai_config):
        """Test acceptance criteria extraction when not found."""
        integration = ClaudeIntegration(ai_config)
        
        description = "Simple feature description without criteria."
        
        criteria = integration._extract_acceptance_criteria(description)
        assert criteria == ""
    
    def test_parse_structured_response(self, ai_config):
        """Test parsing of structured AI response."""
        integration = ClaudeIntegration(ai_config)
        
        raw_response = """**IMPLEMENTATION SUMMARY:**
Added dark mode toggle with localStorage persistence

**FILES MODIFIED:**
- src/components/ThemeToggle.tsx - create - New theme toggle component
- src/hooks/useDarkMode.ts - create - Custom hook for theme management
- src/App.tsx - modify - Added theme provider

**COMMANDS TO RUN:**
`npm install @types/react`
`npm test`

**NOTES:**
Theme preference is stored in localStorage with fallback to system preference."""
        
        response = integration.parse_ai_response(raw_response)
        
        assert response.success is True
        assert "dark mode toggle" in response.summary.lower()
        assert len(response.file_changes) == 3
        assert len(response.commands) == 2
        
        # Check file changes
        file_paths = [fc.path for fc in response.file_changes]
        assert "src/components/ThemeToggle.tsx" in file_paths
        assert "src/hooks/useDarkMode.ts" in file_paths
        assert "src/App.tsx" in file_paths
        
        # Check commands
        commands = [cmd.command for cmd in response.commands]
        assert "npm install @types/react" in commands
        assert "npm test" in commands
    
    def test_parse_freeform_response(self, ai_config):
        """Test parsing of freeform AI response."""
        config = AIConfig(response_format="freeform")
        integration = ClaudeIntegration(config)
        
        raw_response = """I'll implement the dark mode feature by creating ThemeToggle.tsx 
and modifying App.tsx. You should run `npm install` after implementation."""
        
        response = integration.parse_ai_response(raw_response)
        
        assert response.success is True
        assert "implement the dark mode feature" in response.summary
        assert len(response.file_changes) >= 1
        assert len(response.commands) >= 1
    
    def test_parse_malformed_response(self, ai_config):
        """Test parsing of malformed AI response."""
        integration = ClaudeIntegration(ai_config)
        
        raw_response = "Invalid response format without structure"
        
        response = integration.parse_ai_response(raw_response)
        
        # Should still return a response, even if parsing failed
        assert response.raw_output == raw_response
    
    def test_parse_file_changes(self, ai_config):
        """Test parsing file changes from text."""
        integration = ClaudeIntegration(ai_config)
        
        files_text = """- src/component.tsx - create - New component
- utils/helper.ts - modify - Added utility function
- README.md - update - Updated documentation"""
        
        file_changes = integration._parse_file_changes(files_text)
        
        assert len(file_changes) == 3
        assert file_changes[0].path == "src/component.tsx"
        assert file_changes[0].action == "create"
        assert file_changes[1].path == "utils/helper.ts"
        assert file_changes[1].action == "modify"
        assert file_changes[2].path == "README.md"
        assert file_changes[2].action == "modify"  # update -> modify
    
    def test_parse_commands(self, ai_config):
        """Test parsing commands from text."""
        integration = ClaudeIntegration(ai_config)
        
        commands_text = """- `npm install` - Install dependencies
- `npm test` - Run tests
- `npm run build` - Build project"""
        
        commands = integration._parse_commands(commands_text)
        
        assert len(commands) == 3
        assert commands[0].command == "npm install"
        assert commands[0].description == "Install dependencies"
        assert commands[1].command == "npm test"
        assert commands[2].command == "npm run build"


class TestAIIntegrationFunctions:
    """Test AI integration module functions."""
    
    @patch('auto.integrations.ai.ClaudeIntegration')
    def test_execute_ai_command(self, mock_integration_class, ai_config):
        """Test execute_ai_command function."""
        mock_integration = Mock()
        mock_integration.validate_ai_prerequisites.return_value = None
        mock_integration.execute_ai_command.return_value = "AI response"
        mock_integration_class.return_value = mock_integration
        
        result = execute_ai_command("test prompt", "coder", ai_config)
        
        assert result == "AI response"
        mock_integration.validate_ai_prerequisites.assert_called_once()
        mock_integration.execute_ai_command.assert_called_once_with(
            "test prompt", "coder", None, None
        )
    
    @patch('auto.integrations.ai.ClaudeIntegration')
    def test_format_implementation_prompt(self, mock_integration_class, ai_config, test_issue):
        """Test format_implementation_prompt function."""
        mock_integration = Mock()
        mock_integration.format_implementation_prompt.return_value = "formatted prompt"
        mock_integration_class.return_value = mock_integration
        
        result = format_implementation_prompt(test_issue, ai_config)
        
        assert result == "formatted prompt"
        mock_integration.format_implementation_prompt.assert_called_once_with(
            test_issue, None, None
        )
    
    @patch('auto.integrations.ai.ClaudeIntegration')
    def test_parse_ai_response(self, mock_integration_class, ai_config):
        """Test parse_ai_response function."""
        mock_integration = Mock()
        mock_response = AIResponse(success=True, summary="test")
        mock_integration.parse_ai_response.return_value = mock_response
        mock_integration_class.return_value = mock_integration
        
        result = parse_ai_response("raw response", ai_config)
        
        assert result == mock_response
        mock_integration.parse_ai_response.assert_called_once_with("raw response")
    
    @patch('auto.integrations.ai.ClaudeIntegration')
    def test_validate_ai_prerequisites(self, mock_integration_class, ai_config):
        """Test validate_ai_prerequisites function."""
        mock_integration = Mock()
        mock_integration.validate_ai_prerequisites.return_value = None
        mock_integration_class.return_value = mock_integration
        
        validate_ai_prerequisites(ai_config)
        
        mock_integration.validate_ai_prerequisites.assert_called_once()


class TestAIIntegrationEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_claude_integration_with_empty_agent(self):
        """Test ClaudeIntegration with empty agent configuration."""
        config = AIConfig(implementation_agent="")
        integration = ClaudeIntegration(config)
        
        with pytest.raises(AIError):
            integration.validate_ai_prerequisites()
    
    @patch('auto.integrations.ai.run_command')
    def test_execute_ai_command_with_additional_args(self, mock_run_command, ai_config):
        """Test AI command execution with additional arguments."""
        mock_run_command.return_value = Mock(
            returncode=0,
            stdout="AI response",
            stderr=""
        )
        
        integration = ClaudeIntegration(ai_config)
        integration.execute_ai_command(
            "test prompt",
            "coder",
            additional_args=["--verbose", "--debug"]
        )
        
        mock_run_command.assert_called_once_with(
            ["claude", "--agent", "coder", "--verbose", "--debug", "test prompt"],
            capture_output=True,
            timeout=60,
            cwd=None,
            input=None
        )
    
    def test_format_prompt_with_missing_variables(self, ai_config, test_issue):
        """Test prompt formatting with missing variables."""
        integration = ClaudeIntegration(ai_config)
        
        # Use custom prompt with non-existent variable
        custom_prompt = "Issue {issue_id} by {nonexistent_variable}"
        
        # Should not raise, but log warning
        prompt = integration.format_implementation_prompt(
            test_issue,
            custom_prompt=custom_prompt
        )
        
        assert "#123" in prompt
        # The nonexistent variable should remain unreplaced
        assert "{nonexistent_variable}" in prompt
    
    def test_parse_response_with_exception(self, ai_config):
        """Test AI response parsing when exception occurs."""
        integration = ClaudeIntegration(ai_config)
        
        # Mock to raise exception during parsing
        with patch.object(integration, '_parse_structured_response', side_effect=Exception("Parse error")):
            response = integration.parse_ai_response("test response")
            
            assert response.success is False
            assert "Failed to parse AI response" in response.error_message
            assert response.raw_output == "test response"