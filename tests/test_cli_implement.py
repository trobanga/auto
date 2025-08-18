"""
Tests for Phase 3 CLI enhancements: implement command and enhanced process command.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from click.testing import CliRunner

from auto.cli import implement, process
from auto.models import WorkflowState, WorkflowStatus, AIStatus, Issue, IssueProvider, IssueStatus


class TestImplementCommand:
    """Test the auto implement command."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.mock_state = WorkflowState(
            issue_id="123",
            status=WorkflowStatus.IMPLEMENTING,
            ai_status=AIStatus.NOT_STARTED,
            worktree="/tmp/test-worktree"
        )
        self.mock_issue = Issue(
            id="123",
            provider=IssueProvider.GITHUB,
            title="Test Issue",
            description="Test description",
            status=IssueStatus.OPEN
        )
    
    @patch('auto.cli.get_core')
    @patch('auto.workflows.get_issue_from_state')
    @patch('auto.workflows.validate_implementation_prerequisites')
    @patch('auto.workflows.implement_issue_workflow')
    def test_implement_basic_success(self, mock_implement, mock_validate, mock_get_issue, mock_get_core):
        """Test basic implement command success."""
        # Setup mocks
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = self.mock_state
        mock_get_issue.return_value = self.mock_issue
        mock_validate.return_value = None
        
        # Mock successful AI implementation
        success_state = self.mock_state.model_copy()
        success_state.ai_status = AIStatus.IMPLEMENTED
        success_state.ai_response = Mock(success=True, file_changes=[], commands=[])
        # Configure mock to be an async function that returns success_state
        async def async_implement(*args, **kwargs):
            return success_state
        mock_implement.side_effect = async_implement
        
        result = self.runner.invoke(implement, ['123', '--no-pr'])
        
        assert result.exit_code == 0
        assert "AI implementation completed" in result.output
        mock_implement.assert_called_once()
        mock_core.save_workflow_state.assert_called()
    
    @patch('auto.cli.get_core')
    def test_implement_no_workflow_state(self, mock_get_core):
        """Test implement command with no existing workflow state."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = None
        
        result = self.runner.invoke(implement, ['123'])
        
        assert result.exit_code == 1
        assert "No workflow state found" in result.output
    
    @patch('auto.cli.get_core')
    @patch('auto.workflows.get_issue_from_state')
    def test_implement_no_issue_details(self, mock_get_issue, mock_get_core):
        """Test implement command with no issue details."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = self.mock_state
        mock_get_issue.return_value = None
        
        result = self.runner.invoke(implement, ['123'])
        
        assert result.exit_code == 1
        assert "Issue details not found" in result.output
    
    @patch('auto.cli.get_core')
    @patch('auto.workflows.get_issue_from_state')
    @patch('auto.workflows.validate_implementation_prerequisites')
    def test_implement_prerequisites_not_met(self, mock_get_core, mock_get_issue, mock_validate):
        """Test implement command with prerequisites not met."""
        from auto.workflows.implement import ImplementationError
        
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = self.mock_state
        mock_get_issue.return_value = self.mock_issue  # Return valid issue so it gets to prerequisites check
        mock_validate.side_effect = ImplementationError("Prerequisites not met")
        
        result = self.runner.invoke(implement, ['123'])
        
        assert result.exit_code == 1
        assert "Prerequisites not met" in result.output
    
    @patch('auto.cli.get_core')
    @patch('auto.workflows.get_issue_from_state')
    @patch('auto.workflows.validate_implementation_prerequisites')
    @patch('auto.workflows.implement_issue_workflow')
    def test_implement_with_custom_prompt(self, mock_implement, mock_validate, mock_get_issue, mock_get_core):
        """Test implement command with custom prompt options."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = self.mock_state
        mock_get_issue.return_value = self.mock_issue
        mock_validate.return_value = None
        
        success_state = self.mock_state.model_copy()
        success_state.ai_status = AIStatus.IMPLEMENTED
        success_state.ai_response = Mock(success=True, file_changes=[], commands=[])
        # Configure mock to be an async function that returns success_state
        async def async_implement(*args, **kwargs):
            return success_state
        mock_implement.side_effect = async_implement
        
        result = self.runner.invoke(implement, [
            '123', 
            '--prompt', 'Custom prompt text',
            '--prompt-template', 'security-focused',
            '--prompt-append', 'Additional instructions',
            '--no-pr',
            '--verbose'
        ])
        
        assert result.exit_code == 0
        assert "AI implementation completed" in result.output
        assert "Using prompt template: security-focused" in result.output
        
        # Verify the prompt options were passed correctly
        mock_implement.assert_called_once()
        call_args = mock_implement.call_args
        assert call_args[1]['prompt_override'] == 'Custom prompt text'
        assert call_args[1]['prompt_template'] == 'security-focused'
        assert call_args[1]['prompt_append'] == 'Additional instructions'
    
    @patch('auto.cli.get_core')
    @patch('auto.workflows.get_issue_from_state')
    @patch('auto.workflows.validate_implementation_prerequisites')
    @patch('auto.workflows.implement_issue_workflow')
    def test_implement_show_prompt(self, mock_implement, mock_validate, mock_get_issue, mock_get_core):
        """Test implement command with --show-prompt flag."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = self.mock_state
        mock_get_issue.return_value = self.mock_issue
        mock_validate.return_value = None
        
        # Mock show prompt behavior - needs to be async
        async def async_implement(*args, **kwargs):
            return self.mock_state
        mock_implement.side_effect = async_implement
        
        result = self.runner.invoke(implement, ['123', '--show-prompt'])
        
        assert result.exit_code == 0
        assert "Prompt displayed" in result.output
        
        # Verify show_prompt was passed as True
        mock_implement.assert_called_once()
        call_args = mock_implement.call_args
        assert call_args[1]['show_prompt'] is True
    
    @patch('auto.cli.get_core')
    @patch('auto.workflows.get_issue_from_state')
    @patch('auto.workflows.validate_implementation_prerequisites')
    @patch('auto.cli.get_config')
    @patch('auto.workflows.implement_issue_workflow')
    def test_implement_with_custom_agent(self, mock_implement, mock_get_config, mock_validate, mock_get_issue, mock_get_core):
        """Test implement command with custom agent."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = self.mock_state
        mock_get_issue.return_value = self.mock_issue
        mock_validate.return_value = None
        
        
        mock_config = Mock()
        mock_config.ai.implementation_agent = "default-agent"
        mock_get_config.return_value = mock_config
        
        success_state = self.mock_state.model_copy()
        success_state.ai_status = AIStatus.IMPLEMENTED
        success_state.ai_response = Mock(success=True, file_changes=[], commands=[])
        # Configure mock to be an async function that returns success_state
        async def async_implement(*args, **kwargs):
            return success_state
        mock_implement.side_effect = async_implement
        
        result = self.runner.invoke(implement, ['123', '--agent', 'custom-agent', '--no-pr', '--verbose'])
        
        assert result.exit_code == 0
        assert "AI implementation completed" in result.output
        assert "Agent override: default-agent → custom-agent" in result.output
        
        # Verify agent was overridden
        assert mock_config.ai.implementation_agent == "custom-agent"


class TestEnhancedProcessCommand:
    """Test the enhanced auto process command."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.mock_state = WorkflowState(
            issue_id="123",
            status=WorkflowStatus.IMPLEMENTING,
            ai_status=AIStatus.NOT_STARTED
        )
    
    @patch('auto.workflows.validate_process_prerequisites')
    @patch('auto.workflows.process_issue_workflow')
    def test_process_with_ai_enabled(self, mock_process, mock_validate):
        """Test process command with AI implementation enabled."""
        mock_validate.return_value = []
        
        # Mock successful process with AI
        success_state = self.mock_state.model_copy()
        success_state.ai_status = AIStatus.IMPLEMENTED
        success_state.ai_response = Mock(success=True, file_changes=[{'path': 'test.py', 'action': 'create'}], commands=[])
        success_state.pr_number = 456
        mock_process.return_value = success_state
        
        result = self.runner.invoke(process, ['123', '--verbose'])
        
        assert result.exit_code == 0
        assert "AI implementation completed" in result.output
        assert "Pull request created: #456" in result.output
        
        # Verify AI was enabled
        mock_process.assert_called_once()
        call_args = mock_process.call_args
        assert call_args[1]['enable_ai'] is True
        assert call_args[1]['enable_pr'] is True
    
    @patch('auto.workflows.validate_process_prerequisites')
    @patch('auto.workflows.process_issue_workflow')
    def test_process_with_no_ai_flag(self, mock_process, mock_validate):
        """Test process command with --no-ai flag."""
        mock_validate.return_value = []
        
        success_state = self.mock_state.model_copy()
        success_state.status = WorkflowStatus.IMPLEMENTING
        mock_process.return_value = success_state
        
        result = self.runner.invoke(process, ['123', '--no-ai', '--verbose'])
        
        assert result.exit_code == 0
        assert "AI implementation step will be skipped" in result.output
        assert "AI implementation skipped" in result.output
        
        # Verify AI was disabled
        mock_process.assert_called_once()
        call_args = mock_process.call_args
        assert call_args[1]['enable_ai'] is False
    
    @patch('auto.workflows.validate_process_prerequisites')
    @patch('auto.workflows.process_issue_workflow')
    def test_process_with_no_pr_flag(self, mock_process, mock_validate):
        """Test process command with --no-pr flag."""
        mock_validate.return_value = []
        
        success_state = self.mock_state.model_copy()
        success_state.ai_status = AIStatus.IMPLEMENTED
        success_state.ai_response = Mock(success=True, file_changes=[], commands=[])
        mock_process.return_value = success_state
        
        result = self.runner.invoke(process, ['123', '--no-pr', '--verbose'])
        
        assert result.exit_code == 0
        assert "PR creation step will be skipped" in result.output
        assert "PR creation skipped" in result.output
        
        # Verify PR was disabled
        mock_process.assert_called_once()
        call_args = mock_process.call_args
        assert call_args[1]['enable_pr'] is False
    
    @patch('auto.workflows.validate_process_prerequisites')
    @patch('auto.workflows.process_issue_workflow')
    def test_process_with_custom_prompt_options(self, mock_process, mock_validate):
        """Test process command with custom prompt options."""
        mock_validate.return_value = []
        
        success_state = self.mock_state.model_copy()
        success_state.ai_status = AIStatus.IMPLEMENTED
        success_state.ai_response = Mock(success=True, file_changes=[], commands=[])
        mock_process.return_value = success_state
        
        result = self.runner.invoke(process, [
            '123',
            '--prompt-template', 'performance',
            '--prompt-append', 'Focus on speed',
            '--verbose'
        ])
        
        assert result.exit_code == 0
        assert "Using prompt template: performance" in result.output
        
        # Verify prompt options were passed
        mock_process.assert_called_once()
        call_args = mock_process.call_args
        assert call_args[1]['prompt_template'] == 'performance'
        assert call_args[1]['prompt_append'] == 'Focus on speed'
    
    @patch('auto.workflows.validate_process_prerequisites')
    @patch('auto.workflows.process_issue_workflow')
    def test_process_show_prompt(self, mock_process, mock_validate):
        """Test process command with --show-prompt flag."""
        mock_validate.return_value = []
        
        mock_process.return_value = self.mock_state
        
        result = self.runner.invoke(process, ['123', '--show-prompt'])
        
        assert result.exit_code == 0
        assert "Prompt displayed" in result.output
        
        # Verify show_prompt was passed
        mock_process.assert_called_once()
        call_args = mock_process.call_args
        assert call_args[1]['show_prompt'] is True
    
    @patch('auto.workflows.validate_process_prerequisites')
    def test_process_prerequisites_failed(self, mock_validate):
        """Test process command with failed prerequisites."""
        mock_validate.return_value = ["GitHub not authenticated", "Not in git repository"]
        
        result = self.runner.invoke(process, ['123'])
        
        assert result.exit_code == 1
        assert "Prerequisites not met" in result.output
        assert "GitHub not authenticated" in result.output
        assert "Not in git repository" in result.output


class TestStatusCommandEnhancements:
    """Test the enhanced status command."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('auto.cli.get_core')
    def test_status_shows_ai_status_column(self, mock_get_core):
        """Test that status command shows AI status column."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        # Create mock workflow states with different AI statuses
        states = [
            WorkflowState(
                issue_id="123",
                status=WorkflowStatus.IMPLEMENTING,
                ai_status=AIStatus.IN_PROGRESS,
                branch="feature/123"
            ),
            WorkflowState(
                issue_id="456",
                status=WorkflowStatus.IN_REVIEW,
                ai_status=AIStatus.IMPLEMENTED,
                pr_number=789,
                branch="feature/456"
            )
        ]
        mock_core.get_workflow_states.return_value = states
        
        from auto.cli import status
        result = self.runner.invoke(status)
        
        assert result.exit_code == 0
        assert "AI Status" in result.output
        assert "in_progress" in result.output
        assert "implemented" in result.output
    
    @patch('auto.cli.get_core')
    def test_status_shows_ai_summary(self, mock_get_core):
        """Test that status command shows AI implementation summary."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        states = [
            WorkflowState(
                issue_id="123",
                status=WorkflowStatus.IMPLEMENTING,
                ai_status=AIStatus.IMPLEMENTED,
            ),
            WorkflowState(
                issue_id="456",
                status=WorkflowStatus.FAILED,
                ai_status=AIStatus.FAILED,
            ),
            WorkflowState(
                issue_id="789",
                status=WorkflowStatus.FETCHING,
                ai_status=AIStatus.NOT_STARTED,
            )
        ]
        mock_core.get_workflow_states.return_value = states
        
        from auto.cli import status
        result = self.runner.invoke(status)
        
        assert result.exit_code == 0
        assert "AI Implementation:" in result.output
        assert "implemented: 1" in result.output
        assert "failed: 1" in result.output
        assert "not_started: 1" in result.output


if __name__ == "__main__":
    pytest.main([__file__])
