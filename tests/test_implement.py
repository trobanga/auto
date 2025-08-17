"""Tests for AI implementation workflow."""

import pytest
import anyio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from auto.workflows.implement import (
    implement_issue_workflow,
    apply_ai_changes,
    validate_implementation_prerequisites,
    get_implementation_status,
    has_uncommitted_changes,
    get_implementation_summary,
    ImplementationError
)
from auto.models import (
    Issue, IssueProvider, IssueStatus, WorkflowState, WorkflowStatus,
    AIStatus, AIResponse, WorktreeInfo
)


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
def workflow_state(tmp_path):
    """Sample workflow state with worktree."""
    worktree_path = str(tmp_path / "worktree")
    Path(worktree_path).mkdir()
    
    # Create a git repository
    (Path(worktree_path) / ".git").mkdir()
    
    return WorkflowState(
        issue_id="#123",
        worktree=worktree_path,
        status=WorkflowStatus.FETCHING,
        ai_status=AIStatus.NOT_STARTED
    )


@pytest.fixture
def ai_response():
    """Sample AI response."""
    return AIResponse(
        success=True,
        response_type="implementation",
        content="Implementation completed successfully",
        file_changes=[
            {"action": "created", "path": "src/DarkMode.tsx", "content": "// Dark mode component"},
            {"action": "modified", "path": "src/App.tsx", "content": "// Updated app"}
        ],
        commands=["npm test", "npm run build"],
        metadata={"duration": "30s"}
    )


class TestImplementIssueWorkflow:
    """Test implement_issue_workflow function."""

    @pytest.mark.anyio
    async def test_successful_implementation(self, sample_issue, workflow_state, ai_response):
        """Test successful AI implementation workflow."""
        with patch('auto.workflows.implement.Config') as mock_config_class, \
             patch('auto.workflows.implement.PromptManager') as mock_prompt_manager_class, \
             patch('auto.workflows.implement.ClaudeIntegration') as mock_ai_class, \
             patch('auto.workflows.implement.apply_ai_changes', new_callable=AsyncMock) as mock_apply:
            
            # Mock configuration
            mock_config = MagicMock()
            mock_config.ai.implementation_prompt = "Default prompt"
            mock_config_class.return_value = mock_config
            
            # Mock prompt manager
            mock_prompt_manager = MagicMock()
            mock_prompt_manager.resolve_prompt.return_value = "Resolved prompt"
            mock_prompt_manager_class.return_value = mock_prompt_manager
            
            # Mock AI integration
            mock_ai_integration = MagicMock()
            mock_ai_integration.execute_implementation = AsyncMock(return_value=ai_response)
            mock_ai_class.return_value = mock_ai_integration
            
            # Execute workflow
            result = await implement_issue_workflow(sample_issue, workflow_state)
            
            # Verify state updates
            assert result.ai_status == AIStatus.IMPLEMENTED
            assert result.ai_response == ai_response
            
            # Verify AI integration was called correctly
            mock_ai_integration.execute_implementation.assert_called_once_with(
                issue=sample_issue,
                worktree_path=workflow_state.worktree,
                custom_prompt="Resolved prompt"
            )
            
            # Verify changes were applied
            mock_apply.assert_called_once_with(
                ai_response=ai_response,
                worktree_path=workflow_state.worktree,
                config=mock_config
            )

    @pytest.mark.anyio
    async def test_implementation_with_custom_prompt(self, sample_issue, workflow_state):
        """Test implementation with custom prompt options."""
        with patch('auto.workflows.implement.Config') as mock_config_class, \
             patch('auto.workflows.implement.PromptManager') as mock_prompt_manager_class, \
             patch('auto.workflows.implement.ClaudeIntegration') as mock_ai_class, \
             patch('auto.workflows.implement.apply_ai_changes', new_callable=AsyncMock):
            
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config
            
            mock_prompt_manager = MagicMock()
            mock_prompt_manager.resolve_prompt.return_value = "Custom resolved prompt"
            mock_prompt_manager_class.return_value = mock_prompt_manager
            
            mock_ai_integration = MagicMock()
            mock_ai_integration.execute_implementation = AsyncMock(return_value=AIResponse(
                success=True, response_type="implementation", content="Done",
                file_changes=[], commands=[], metadata={}
            ))
            mock_ai_class.return_value = mock_ai_integration
            
            # Execute with custom prompt options
            await implement_issue_workflow(
                sample_issue, 
                workflow_state,
                prompt_template="security-focused",
                prompt_append="Focus on testing"
            )
            
            # Verify prompt manager was called with custom options
            mock_prompt_manager.resolve_prompt.assert_called_once_with(
                issue=sample_issue,
                prompt_override=None,
                prompt_file=None,
                prompt_template="security-focused",
                prompt_append="Focus on testing",
                default_prompt=mock_config.ai.implementation_prompt
            )

    @pytest.mark.anyio
    async def test_show_prompt_mode(self, sample_issue, workflow_state):
        """Test show prompt mode without execution."""
        with patch('auto.workflows.implement.Config') as mock_config_class, \
             patch('auto.workflows.implement.PromptManager') as mock_prompt_manager_class:
            
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config
            
            mock_prompt_manager = MagicMock()
            mock_prompt_manager.resolve_prompt.return_value = "Test prompt"
            mock_prompt_manager_class.return_value = mock_prompt_manager
            
            # Execute in show prompt mode
            result = await implement_issue_workflow(
                sample_issue, 
                workflow_state,
                show_prompt=True
            )
            
            # Should return without executing AI
            assert result == workflow_state
            assert result.ai_status == AIStatus.IN_PROGRESS  # Status was updated to in progress
            
            # Verify prompt was resolved but AI wasn't called
            mock_prompt_manager.resolve_prompt.assert_called_once()

    @pytest.mark.anyio
    async def test_no_worktree_error(self, sample_issue):
        """Test error when no worktree is available."""
        workflow_state = WorkflowState(
            issue_id="#123",
            worktree=None,  # No worktree
            status=WorkflowStatus.FETCHING
        )
        
        with pytest.raises(ImplementationError) as excinfo:
            await implement_issue_workflow(sample_issue, workflow_state)
        
        assert "No worktree available" in str(excinfo.value)

    @pytest.mark.anyio
    async def test_nonexistent_worktree_error(self, sample_issue):
        """Test error when worktree path doesn't exist."""
        workflow_state = WorkflowState(
            issue_id="#123",
            worktree="/nonexistent/path",
            status=WorkflowStatus.FETCHING
        )
        
        with pytest.raises(ImplementationError) as excinfo:
            await implement_issue_workflow(sample_issue, workflow_state)
        
        assert "does not exist" in str(excinfo.value)

    @pytest.mark.anyio
    async def test_ai_implementation_failure(self, sample_issue, workflow_state):
        """Test handling of AI implementation failure."""
        failed_response = AIResponse(
            success=False,
            response_type="implementation",
            content="AI implementation failed due to error",
            file_changes=[],
            commands=[],
            metadata={}
        )
        
        with patch('auto.workflows.implement.Config') as mock_config_class, \
             patch('auto.workflows.implement.PromptManager') as mock_prompt_manager_class, \
             patch('auto.workflows.implement.ClaudeIntegration') as mock_ai_class:
            
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config
            
            mock_prompt_manager = MagicMock()
            mock_prompt_manager.resolve_prompt.return_value = "Test prompt"
            mock_prompt_manager_class.return_value = mock_prompt_manager
            
            mock_ai_integration = MagicMock()
            mock_ai_integration.execute_implementation = AsyncMock(return_value=failed_response)
            mock_ai_class.return_value = mock_ai_integration
            
            with pytest.raises(ImplementationError) as excinfo:
                await implement_issue_workflow(sample_issue, workflow_state)
            
            assert "AI implementation failed" in str(excinfo.value)
            assert workflow_state.ai_status == AIStatus.FAILED
            assert workflow_state.status == WorkflowStatus.FAILED

    @pytest.mark.anyio
    async def test_prompt_resolution_error(self, sample_issue, workflow_state):
        """Test handling of prompt resolution errors."""
        from auto.integrations.prompts import PromptError
        
        with patch('auto.workflows.implement.Config') as mock_config_class, \
             patch('auto.workflows.implement.PromptManager') as mock_prompt_manager_class:
            
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config
            
            mock_prompt_manager = MagicMock()
            mock_prompt_manager.resolve_prompt.side_effect = PromptError("Template not found")
            mock_prompt_manager_class.return_value = mock_prompt_manager
            
            with pytest.raises(ImplementationError) as excinfo:
                await implement_issue_workflow(sample_issue, workflow_state)
            
            assert "Failed to resolve prompt" in str(excinfo.value)


class TestApplyAIChanges:
    """Test apply_ai_changes function."""

    @pytest.mark.anyio
    async def test_apply_file_changes(self, ai_response, tmp_path):
        """Test applying file changes from AI response."""
        worktree_path = str(tmp_path)
        
        with patch('auto.workflows.implement.os.chdir') as mock_chdir, \
             patch('auto.workflows.implement.os.getcwd', return_value="/original"):
            
            await apply_ai_changes(ai_response, worktree_path, MagicMock())
            
            # Verify directory changes
            mock_chdir.assert_any_call(worktree_path)
            mock_chdir.assert_any_call("/original")  # Restored
            
            # Verify files were created
            created_file = tmp_path / "src" / "DarkMode.tsx"
            modified_file = tmp_path / "src" / "App.tsx"
            
            assert created_file.exists()
            assert created_file.read_text() == "// Dark mode component"
            
            assert modified_file.exists()
            assert modified_file.read_text() == "// Updated app"

    @pytest.mark.anyio
    async def test_execute_commands(self, tmp_path):
        """Test executing AI-suggested commands."""
        ai_response = AIResponse(
            success=True,
            response_type="implementation",
            content="Commands executed",
            file_changes=[],
            commands=["echo 'test'", "echo 'another test'"],
            metadata={}
        )
        
        worktree_path = str(tmp_path)
        
        with patch('auto.workflows.implement.os.chdir'), \
             patch('auto.workflows.implement.os.getcwd', return_value="/original"), \
             patch('asyncio.create_subprocess_shell') as mock_subprocess:
            
            # Mock successful command execution
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"output", b"")
            mock_subprocess.return_value = mock_process
            
            await apply_ai_changes(ai_response, worktree_path, MagicMock())
            
            # Verify commands were executed
            assert mock_subprocess.call_count == 2
            mock_subprocess.assert_any_call(
                "echo 'test'",
                cwd=worktree_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

    @pytest.mark.anyio
    async def test_command_failure_handling(self, tmp_path):
        """Test handling of command execution failures."""
        ai_response = AIResponse(
            success=True,
            response_type="implementation",
            content="Command failed",
            file_changes=[],
            commands=["failing_command"],
            metadata={}
        )
        
        worktree_path = str(tmp_path)
        
        with patch('auto.workflows.implement.os.chdir'), \
             patch('auto.workflows.implement.os.getcwd', return_value="/original"), \
             patch('asyncio.create_subprocess_shell') as mock_subprocess:
            
            # Mock failed command execution
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate.return_value = (b"", b"error output")
            mock_subprocess.return_value = mock_process
            
            # Should not raise, should continue
            await apply_ai_changes(ai_response, worktree_path, MagicMock())

    @pytest.mark.anyio
    async def test_directory_restoration_on_exception(self, ai_response, tmp_path):
        """Test that original directory is restored even on exception."""
        worktree_path = str(tmp_path)
        
        with patch('auto.workflows.implement.os.chdir') as mock_chdir, \
             patch('auto.workflows.implement.os.getcwd', return_value="/original"), \
             patch('auto.workflows.implement._apply_file_changes', side_effect=Exception("Test error")):
            
            with pytest.raises(ImplementationError):
                await apply_ai_changes(ai_response, worktree_path, MagicMock())
            
            # Verify directory was restored
            mock_chdir.assert_any_call("/original")


class TestValidateImplementationPrerequisites:
    """Test validate_implementation_prerequisites function."""

    def test_valid_prerequisites(self, workflow_state):
        """Test validation with valid prerequisites."""
        with patch('auto.workflows.implement.Config') as mock_config_class:
            mock_config = MagicMock()
            mock_config.ai.implementation_agent = "coder"
            mock_config_class.return_value = mock_config
            
            # Should not raise
            validate_implementation_prerequisites(workflow_state)

    def test_no_worktree(self):
        """Test validation with no worktree."""
        workflow_state = WorkflowState(
            issue_id="#123",
            worktree=None,
            status=WorkflowStatus.FETCHING
        )
        
        with pytest.raises(ImplementationError) as excinfo:
            validate_implementation_prerequisites(workflow_state)
        
        assert "No worktree configured" in str(excinfo.value)

    def test_nonexistent_worktree(self):
        """Test validation with non-existent worktree."""
        workflow_state = WorkflowState(
            issue_id="#123",
            worktree="/nonexistent/path",
            status=WorkflowStatus.FETCHING
        )
        
        with pytest.raises(ImplementationError) as excinfo:
            validate_implementation_prerequisites(workflow_state)
        
        assert "does not exist" in str(excinfo.value)

    def test_worktree_not_directory(self, tmp_path):
        """Test validation when worktree is not a directory."""
        # Create a file instead of directory
        worktree_file = tmp_path / "not_a_dir"
        worktree_file.write_text("content")
        
        workflow_state = WorkflowState(
            issue_id="#123",
            worktree=str(worktree_file),
            status=WorkflowStatus.FETCHING
        )
        
        with pytest.raises(ImplementationError) as excinfo:
            validate_implementation_prerequisites(workflow_state)
        
        assert "not a directory" in str(excinfo.value)

    def test_worktree_not_git_repo(self, tmp_path):
        """Test validation when worktree is not a git repository."""
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()
        
        workflow_state = WorkflowState(
            issue_id="#123",
            worktree=str(worktree_path),
            status=WorkflowStatus.FETCHING
        )
        
        with pytest.raises(ImplementationError) as excinfo:
            validate_implementation_prerequisites(workflow_state)
        
        assert "not a git repository" in str(excinfo.value)

    def test_no_ai_agent_configured(self, workflow_state):
        """Test validation with no AI agent configured."""
        with patch('auto.workflows.implement.Config') as mock_config_class:
            mock_config = MagicMock()
            mock_config.ai.implementation_agent = ""  # Empty agent
            mock_config_class.return_value = mock_config
            
            with pytest.raises(ImplementationError) as excinfo:
                validate_implementation_prerequisites(workflow_state)
            
            assert "No AI implementation agent configured" in str(excinfo.value)


class TestGetImplementationStatus:
    """Test get_implementation_status function."""

    @pytest.mark.anyio
    async def test_status_with_ai_response(self, workflow_state, ai_response):
        """Test status retrieval with AI response."""
        workflow_state.ai_status = AIStatus.IMPLEMENTED
        workflow_state.ai_response = ai_response
        
        status = await get_implementation_status(workflow_state)
        
        assert status["ai_status"] == "implemented"
        assert status["has_ai_response"] is True
        assert status["file_changes_count"] == 2
        assert status["commands_count"] == 2
        assert status["implementation_successful"] is True
        assert status["response_type"] == "implementation"

    @pytest.mark.anyio
    async def test_status_without_ai_response(self, workflow_state):
        """Test status retrieval without AI response."""
        workflow_state.ai_status = AIStatus.NOT_STARTED
        
        status = await get_implementation_status(workflow_state)
        
        assert status["ai_status"] == "not_started"
        assert status["has_ai_response"] is False
        assert status["file_changes_count"] == 0
        assert status["commands_count"] == 0
        assert status["implementation_successful"] is False


class TestHasUncommittedChanges:
    """Test has_uncommitted_changes function."""

    def test_has_changes(self, tmp_path):
        """Test detection of uncommitted changes."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "M  file1.txt\nA  file2.txt\n"
            
            result = has_uncommitted_changes(str(tmp_path))
            
            assert result is True
            mock_run.assert_called_once_with(
                ["git", "status", "--porcelain"],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=10
            )

    def test_no_changes(self, tmp_path):
        """Test when there are no uncommitted changes."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = ""
            
            result = has_uncommitted_changes(str(tmp_path))
            
            assert result is False

    def test_git_command_failure(self, tmp_path):
        """Test handling of git command failure."""
        with patch('subprocess.run', side_effect=subprocess.SubprocessError):
            
            result = has_uncommitted_changes(str(tmp_path))
            
            assert result is False  # Default to False on error


class TestGetImplementationSummary:
    """Test get_implementation_summary function."""

    def test_not_started_summary(self):
        """Test summary for not started implementation."""
        workflow_state = WorkflowState(
            issue_id="#123",
            status=WorkflowStatus.FETCHING,
            ai_status=AIStatus.NOT_STARTED
        )
        
        summary = get_implementation_summary(workflow_state)
        
        assert summary == "AI implementation not started"

    def test_in_progress_summary(self):
        """Test summary for in progress implementation."""
        workflow_state = WorkflowState(
            issue_id="#123",
            status=WorkflowStatus.IMPLEMENTING,
            ai_status=AIStatus.IN_PROGRESS
        )
        
        summary = get_implementation_summary(workflow_state)
        
        assert summary == "AI implementation in progress"

    def test_failed_summary_with_response(self):
        """Test summary for failed implementation with response."""
        workflow_state = WorkflowState(
            issue_id="#123",
            status=WorkflowStatus.FAILED,
            ai_status=AIStatus.FAILED,
            ai_response=AIResponse(
                success=False,
                response_type="implementation",
                content="This is a very long error message that should be truncated",
                file_changes=[],
                commands=[],
                metadata={}
            )
        )
        
        summary = get_implementation_summary(workflow_state)
        
        assert "AI implementation failed:" in summary
        assert "should be truncated" not in summary  # Should be truncated

    def test_completed_summary_with_response(self, ai_response):
        """Test summary for completed implementation with response."""
        workflow_state = WorkflowState(
            issue_id="#123",
            status=WorkflowStatus.COMPLETED,
            ai_status=AIStatus.IMPLEMENTED,
            ai_response=ai_response
        )
        
        summary = get_implementation_summary(workflow_state)
        
        assert "AI implementation completed:" in summary
        assert "2 files modified" in summary
        assert "2 commands executed" in summary