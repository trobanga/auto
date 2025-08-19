"""Integration tests for CLI fetch command."""

from unittest.mock import Mock, patch

from click.testing import CliRunner

from auto.cli import cli
from auto.models import (
    Issue,
    IssueProvider,
    IssueStatus,
    IssueType,
    WorkflowState,
    WorkflowStatus,
)


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
            issue_type=IssueType.FEATURE,
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
            url="https://github.com/owner/repo/issues/123",
        )

        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = mock_issue
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_fetch_workflow.return_value = mock_state

        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "123", "--verbose"])

        assert result.exit_code == 0
        assert "Parsing github issue" in result.output
        assert "Status: IssueStatus.OPEN" in result.output
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
