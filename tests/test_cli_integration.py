"""Integration tests for CLI commands."""

import pytest
from click.testing import CliRunner
from unittest.mock import Mock, patch

from auto.cli import cli
from auto.models import Issue, IssueProvider, IssueStatus, IssueType, WorkflowState, WorkflowStatus, WorktreeInfo


class TestFetchCommand:
    """Test fetch command integration."""
    
    def test_fetch_command_help(self):
        """Test fetch command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--help"])
        
        assert result.exit_code == 0
        assert "Fetch issue details" in result.output
    
    @patch("auto.cli.validate_issue_access")
    @patch("auto.cli.fetch_issue_workflow_sync")
    def test_fetch_command_success(self, mock_fetch_workflow, mock_validate_access):
        """Test successful fetch command."""
        # Mock validation
        mock_validate_access.return_value = True
        
        # Mock workflow result
        mock_issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Test issue",
            description="Test description",
            status=IssueStatus.OPEN,
            issue_type=IssueType.FEATURE
        )
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = mock_issue
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_fetch_workflow.return_value = mock_state
        
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "123"])
        
        assert result.exit_code == 0
        assert "Fetched GitHub issue #123" in result.output
        assert "Test issue" in result.output
        assert "Workflow state created" in result.output
        
        mock_validate_access.assert_called_once_with("#123")
        mock_fetch_workflow.assert_called_once_with("#123")
    
    @patch("auto.cli.validate_issue_access")
    @patch("auto.cli.fetch_issue_workflow_sync")
    def test_fetch_command_verbose(self, mock_fetch_workflow, mock_validate_access):
        """Test fetch command with verbose output."""
        # Mock validation
        mock_validate_access.return_value = True
        
        # Mock workflow result
        mock_issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Test issue",
            description="Test description",
            status=IssueStatus.OPEN,
            issue_type=IssueType.FEATURE,
            assignee="testuser",
            labels=["bug", "priority-high"],
            url="https://github.com/owner/repo/issues/123"
        )
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = mock_issue
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_fetch_workflow.return_value = mock_state
        
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "123", "--verbose"])
        
        assert result.exit_code == 0
        assert "Parsing github issue" in result.output
        assert "Status: open" in result.output
        assert "Type: feature" in result.output
        assert "Assignee: testuser" in result.output
        assert "Labels: bug, priority-high" in result.output
        assert "URL: https://github.com/owner/repo/issues/123" in result.output
        assert "State file: .auto/state/#123.yaml" in result.output
    
    @patch("auto.cli.validate_issue_access")
    def test_fetch_command_validation_failure(self, mock_validate_access):
        """Test fetch command with validation failure."""
        mock_validate_access.return_value = False
        
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "123"])
        
        assert result.exit_code == 1
        assert "Cannot access issue #123" in result.output
        assert "Check authentication and repository access" in result.output
    
    @patch("auto.cli.validate_issue_access")
    @patch("auto.cli.fetch_issue_workflow_sync")
    def test_fetch_command_workflow_error(self, mock_fetch_workflow, mock_validate_access):
        """Test fetch command with workflow error."""
        from auto.workflows.fetch import FetchWorkflowError
        
        mock_validate_access.return_value = True
        mock_fetch_workflow.side_effect = FetchWorkflowError("GitHub authentication required")
        
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "123"])
        
        assert result.exit_code == 1
        assert "GitHub authentication required" in result.output
        assert "gh auth login" in result.output
    
    def test_fetch_command_invalid_issue_id(self):
        """Test fetch command with invalid issue ID."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "invalid-id"])
        
        assert result.exit_code == 1
        assert "Unable to parse issue identifier" in result.output


class TestProcessCommand:
    """Test process command integration."""
    
    def test_process_command_help(self):
        """Test process command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "--help"])
        
        assert result.exit_code == 0
        assert "Process issue by fetching details" in result.output
    
    @patch("auto.cli.validate_process_prerequisites")
    @patch("auto.cli.process_issue_workflow")
    def test_process_command_success(self, mock_process_workflow, mock_validate_prereqs):
        """Test successful process command."""
        # Mock validation
        mock_validate_prereqs.return_value = []
        
        # Mock workflow result
        mock_issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Test issue",
            description="Test description",
            status=IssueStatus.OPEN,
            issue_type=IssueType.FEATURE
        )
        
        mock_worktree_info = WorktreeInfo(
            path="/tmp/test-worktrees/auto-feature-123",
            branch="auto/feature/123",
            issue_id="#123"
        )
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = mock_issue
        mock_state.worktree_info = mock_worktree_info
        mock_state.metadata = {"base_branch": "main"}
        mock_state.repository = None
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_process_workflow.return_value = mock_state
        
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "123"])
        
        assert result.exit_code == 0
        assert "Validating prerequisites" in result.output
        assert "Processing issue #123" in result.output
        assert "Processed issue #123: Test issue" in result.output
        assert "Created worktree: /tmp/test-worktrees/auto-feature-123" in result.output
        assert "Created branch: auto/feature/123" in result.output
        assert "Ready for development" in result.output
        assert "Next steps:" in result.output
        
        mock_validate_prereqs.assert_called_once_with("#123")
        mock_process_workflow.assert_called_once_with("#123", None)
    
    @patch("auto.cli.validate_process_prerequisites")
    @patch("auto.cli.process_issue_workflow")
    def test_process_command_with_base_branch(self, mock_process_workflow, mock_validate_prereqs):
        """Test process command with custom base branch."""
        mock_validate_prereqs.return_value = []
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = None
        mock_state.worktree_info = None
        mock_state.metadata = {}
        mock_state.repository = None
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_process_workflow.return_value = mock_state
        
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "123", "--base-branch", "develop"])
        
        assert result.exit_code == 0
        mock_process_workflow.assert_called_once_with("#123", "develop")
    
    @patch("auto.cli.validate_process_prerequisites")
    def test_process_command_prerequisites_failure(self, mock_validate_prereqs):
        """Test process command with prerequisites failure."""
        mock_validate_prereqs.return_value = [
            "Not in a git repository",
            "GitHub CLI not authenticated"
        ]
        
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "123"])
        
        assert result.exit_code == 1
        assert "Prerequisites not met" in result.output
        assert "Not in a git repository" in result.output
        assert "GitHub CLI not authenticated" in result.output
    
    @patch("auto.cli.validate_process_prerequisites")
    @patch("auto.cli.process_issue_workflow")
    def test_process_command_workflow_error(self, mock_process_workflow, mock_validate_prereqs):
        """Test process command with workflow error."""
        from auto.workflows.process import ProcessWorkflowError
        
        mock_validate_prereqs.return_value = []
        mock_process_workflow.side_effect = ProcessWorkflowError("Worktree creation failed")
        
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "123"])
        
        assert result.exit_code == 1
        assert "Worktree creation failed" in result.output
    
    @patch("auto.cli.validate_process_prerequisites")
    @patch("auto.cli.process_issue_workflow")
    def test_process_command_verbose(self, mock_process_workflow, mock_validate_prereqs):
        """Test process command with verbose output."""
        mock_validate_prereqs.return_value = []
        
        mock_issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Test issue",
            description="Test description",
            status=IssueStatus.OPEN,
            issue_type=IssueType.FEATURE
        )
        
        mock_worktree_info = Mock(spec=WorktreeInfo)
        mock_worktree_info.path = "/tmp/test-worktrees/auto-feature-123"
        mock_worktree_info.branch = "auto/feature/123"
        mock_worktree_info.exists.return_value = True
        
        mock_repository = Mock()
        mock_repository.full_name = "owner/repo"
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = mock_issue
        mock_state.worktree_info = mock_worktree_info
        mock_state.metadata = {"base_branch": "main"}
        mock_state.repository = mock_repository
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_process_workflow.return_value = mock_state
        
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "123", "--verbose"])
        
        assert result.exit_code == 0
        assert "Processing github issue: #123" in result.output
        assert "Prerequisites validated" in result.output
        assert "Base branch: main" in result.output
        assert "Worktree exists: True" in result.output
        assert "Repository: owner/repo" in result.output
        assert "State file: .auto/state/#123.yaml" in result.output


class TestStatusCommand:
    """Test status command integration."""
    
    @patch("auto.cli.get_core")
    def test_status_command_no_workflows(self, mock_get_core):
        """Test status command with no workflows."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_states.return_value = []
        
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        
        assert result.exit_code == 0
        assert "No active workflows found" in result.output
    
    @patch("auto.cli.get_core")
    def test_status_command_with_workflows(self, mock_get_core):
        """Test status command with active workflows."""
        from datetime import datetime
        
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        # Mock workflow state
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue_id = "#123"
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_state.pr_number = None
        mock_state.branch = "auto/feature/123"
        mock_state.updated_at = datetime(2024, 1, 15, 10, 0, 0)
        mock_state.worktree_info = None
        mock_state.repository = None
        
        mock_core.get_workflow_states.return_value = [mock_state]
        
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        
        assert result.exit_code == 0
        assert "Active Workflows" in result.output
        assert "#123" in result.output
        assert "implementing" in result.output
        assert "auto/feature/123" in result.output
        assert "2024-01-15 10:00" in result.output
        assert "Summary: 1 active workflows" in result.output
        assert "implementing: 1" in result.output
    
    @patch("auto.cli.get_core")
    def test_status_command_verbose(self, mock_get_core):
        """Test status command with verbose output."""
        from datetime import datetime
        
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        # Mock worktree info
        mock_worktree_info = Mock(spec=WorktreeInfo)
        mock_worktree_info.path = "/tmp/test-worktrees/auto-feature-123"
        mock_worktree_info.exists.return_value = True
        
        # Mock repository
        mock_repository = Mock()
        mock_repository.full_name = "owner/repo"
        
        # Mock workflow state
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue_id = "#123"
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_state.pr_number = None
        mock_state.branch = "auto/feature/123"
        mock_state.updated_at = datetime(2024, 1, 15, 10, 0, 0)
        mock_state.worktree_info = mock_worktree_info
        mock_state.repository = mock_repository
        
        mock_core.get_workflow_states.return_value = [mock_state]
        
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--verbose"])
        
        assert result.exit_code == 0
        assert "✓ /tmp/test-worktrees/auto-feature-123" in result.output
        assert "owner/repo" in result.output
        assert "Active worktrees: 1" in result.output


class TestCleanupCommand:
    """Test cleanup command integration."""
    
    @patch("auto.cli.get_core")
    def test_cleanup_command_no_workflows(self, mock_get_core):
        """Test cleanup command with no workflows."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_states.return_value = []
        
        runner = CliRunner()
        result = runner.invoke(cli, ["cleanup"])
        
        assert result.exit_code == 0
        assert "No workflows to clean up" in result.output
    
    @patch("auto.cli.get_core")
    @patch("auto.cli.cleanup_process_workflow")
    def test_cleanup_command_completed_workflows(self, mock_cleanup_workflow, mock_get_core):
        """Test cleanup command with completed workflows."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        # Mock completed workflow state
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue_id = "#123"
        mock_state.status = Mock()
        mock_state.status.value = "completed"
        mock_state.worktree_info = Mock()
        
        mock_core.get_workflow_states.return_value = [mock_state]
        mock_core.cleanup_completed_states.return_value = 1
        mock_cleanup_workflow.return_value = True
        
        runner = CliRunner()
        result = runner.invoke(cli, ["cleanup"])
        
        assert result.exit_code == 0
        assert "Cleaned up 1 workflow(s)" in result.output
        assert "Cleaned up 1 worktree(s)" in result.output
        
        mock_cleanup_workflow.assert_called_once_with("#123")
    
    @patch("auto.cli.get_core")
    @patch("auto.cli.cleanup_process_workflow")
    def test_cleanup_command_force(self, mock_cleanup_workflow, mock_get_core):
        """Test cleanup command with force flag."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        # Mock active workflow state
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue_id = "#123"
        mock_state.status = Mock()
        mock_state.status.value = "implementing"
        mock_state.worktree_info = Mock()
        
        mock_core.get_workflow_states.return_value = [mock_state]
        mock_core.cleanup_completed_states.return_value = 0
        mock_cleanup_workflow.return_value = True
        
        runner = CliRunner()
        result = runner.invoke(cli, ["cleanup", "--force"])
        
        assert result.exit_code == 0
        assert "Cleaned up 1 workflow(s)" in result.output
        
        mock_cleanup_workflow.assert_called_once_with("#123")
    
    @patch("auto.cli.get_core")
    @patch("auto.cli.cleanup_process_workflow")
    def test_cleanup_command_errors(self, mock_cleanup_workflow, mock_get_core):
        """Test cleanup command with errors."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        # Mock workflow state
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue_id = "#123"
        mock_state.status = Mock()
        mock_state.status.value = "completed"
        mock_state.worktree_info = Mock()
        
        mock_core.get_workflow_states.return_value = [mock_state]
        mock_core.cleanup_completed_states.return_value = 0
        mock_cleanup_workflow.return_value = False  # Cleanup failed
        
        runner = CliRunner()
        result = runner.invoke(cli, ["cleanup"])
        
        assert result.exit_code == 0  # Should not fail, just report errors
        assert "Errors encountered" in result.output
        assert "Failed to clean up worktree for #123" in result.output