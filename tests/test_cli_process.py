"""Integration tests for CLI process command."""

from click.testing import CliRunner
from unittest.mock import Mock, patch

from auto.cli import cli
from auto.models import (
    Issue,
    IssueProvider,
    IssueStatus,
    IssueType,
    WorkflowState,
    WorkflowStatus,
    WorktreeInfo,
)


class TestProcessCommand:
    """Test process command integration."""

    def test_process_command_help(self):
        """Test process command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "--help"])

        print(result)

        assert result.exit_code == 0
        assert "Process issue: fetch details" in result.output

    @patch("auto.workflows.validate_process_prerequisites")
    @patch("auto.workflows.process_issue_workflow")
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
            issue_type=IssueType.FEATURE,
        )

        mock_worktree_info = WorktreeInfo(
            path="/tmp/test-worktrees/auto-feature-123", branch="auto/feature/123", issue_id="#123"
        )

        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = mock_issue
        mock_state.worktree_info = mock_worktree_info
        mock_state.metadata = {"base_branch": "main"}
        mock_state.repository = None
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_state.ai_response = None  # No AI implementation in this test
        mock_state.pr_number = None  # No PR created in this test
        mock_process_workflow.return_value = mock_state

        runner = CliRunner()
        result = runner.invoke(cli, ["process", "123"])

        assert result.exit_code == 0
        assert "Validating prerequisites" in result.output
        assert "Processing issue #123" in result.output
        assert "Processed issue #123: Test issue" in result.output
        assert "Created worktree: /tmp/test-worktrees/auto-feature-123" in result.output
        assert "Created branch: auto/feature/123" in result.output
        assert "Process workflow completed" in result.output
        assert "Next steps:" in result.output

        mock_validate_prereqs.assert_called_once_with("#123")
        mock_process_workflow.assert_called_once_with(
            issue_id="#123", 
            base_branch=None,
            enable_ai=True,
            enable_pr=True,
            prompt_override=None,
            prompt_file=None,
            prompt_template=None,
            prompt_append=None,
            show_prompt=False,
            resume=False
        )

    @patch("auto.workflows.validate_process_prerequisites")
    @patch("auto.workflows.process_issue_workflow")
    def test_process_command_with_base_branch(self, mock_process_workflow, mock_validate_prereqs):
        """Test process command with custom base branch."""
        mock_validate_prereqs.return_value = []

        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = None
        mock_state.worktree_info = None
        mock_state.metadata = {}
        mock_state.repository = None
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_state.ai_response = None
        mock_state.pr_number = None
        mock_process_workflow.return_value = mock_state

        runner = CliRunner()
        result = runner.invoke(cli, ["process", "123", "--base-branch", "develop"])

        assert result.exit_code == 0
        mock_process_workflow.assert_called_once_with(
            issue_id="#123", 
            base_branch="develop",
            enable_ai=True,
            enable_pr=True,
            prompt_override=None,
            prompt_file=None,
            prompt_template=None,
            prompt_append=None,
            show_prompt=False,
            resume=False
        )

    @patch("auto.workflows.validate_process_prerequisites")
    def test_process_command_prerequisites_failure(self, mock_validate_prereqs):
        """Test process command with prerequisites failure."""
        mock_validate_prereqs.return_value = [
            "Not in a git repository",
            "GitHub CLI not authenticated",
        ]

        runner = CliRunner()
        result = runner.invoke(cli, ["process", "123"])

        assert result.exit_code == 1
        assert "Prerequisites not met" in result.output
        assert "Not in a git repository" in result.output
        assert "GitHub CLI not authenticated" in result.output

    @patch("auto.workflows.validate_process_prerequisites")
    @patch("auto.workflows.process_issue_workflow")
    def test_process_command_workflow_error(self, mock_process_workflow, mock_validate_prereqs):
        """Test process command with workflow error."""
        from auto.workflows.process import ProcessWorkflowError

        mock_validate_prereqs.return_value = []
        mock_process_workflow.side_effect = ProcessWorkflowError("Worktree creation failed")

        runner = CliRunner()
        result = runner.invoke(cli, ["process", "123"])

        assert result.exit_code == 1
        assert "Worktree creation failed" in result.output

    @patch("auto.workflows.validate_process_prerequisites")
    @patch("auto.workflows.process_issue_workflow")
    def test_process_command_verbose(self, mock_process_workflow, mock_validate_prereqs):
        """Test process command with verbose output."""
        mock_validate_prereqs.return_value = []

        mock_issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Test issue",
            description="Test description",
            status=IssueStatus.OPEN,
            issue_type=IssueType.FEATURE,
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
        mock_state.ai_response = None
        mock_state.pr_number = None
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
