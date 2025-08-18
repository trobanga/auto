"""Integration tests for CLI status command."""

from click.testing import CliRunner
from unittest.mock import Mock, patch

from auto.cli import cli
from auto.models import (
    WorkflowState,
    WorkflowStatus,
    WorktreeInfo,
)


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
        mock_state.ai_status = Mock()
        mock_state.ai_status.value = "not_started"
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
        assert "not_started" in result.output
        assert "auto/feature" in result.output  # Truncated in table
        assert "2024-01-15" in result.output
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
        mock_state.ai_status = Mock()
        mock_state.ai_status.value = "not_started"
        mock_state.pr_number = None
        mock_state.branch = "auto/feature/123"
        mock_state.updated_at = datetime(2024, 1, 15, 10, 0, 0)
        mock_state.worktree_info = mock_worktree_info
        mock_state.repository = mock_repository

        mock_core.get_workflow_states.return_value = [mock_state]

        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--verbose"])

        assert result.exit_code == 0
        assert "/tmp/t" in result.output  # Truncated path in table
        assert "owner/r" in result.output  # Truncated repository name
        assert "Active worktrees: 1" in result.output