"""Tests for PR creation workflow."""

import pytest
import anyio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from auto.workflows.pr_create import (
    create_pull_request_workflow,
    generate_pr_metadata,
    generate_pr_title,
    generate_pr_description,
    load_pr_template,
    determine_pr_labels,
    determine_pr_assignees,
    determine_pr_reviewers,
    commit_implementation_changes,
    generate_commit_message,
    push_branch_to_remote,
    create_github_pr,
    validate_pr_prerequisites,
    has_uncommitted_changes,
    has_implementation_commits,
    get_pr_creation_summary,
    PRCreationError
)
from auto.models import (
    Issue, IssueProvider, IssueStatus, IssueType, WorkflowState, WorkflowStatus,
    AIStatus, AIResponse, PRMetadata, PullRequest, PRStatus
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
        issue_type=IssueType.FEATURE,
        labels=["feature", "ui"],
        assignee="developer"
    )


@pytest.fixture
def workflow_state(tmp_path):
    """Sample workflow state with worktree."""
    worktree_path = str(tmp_path / "worktree")
    Path(worktree_path).mkdir()
    (Path(worktree_path) / ".git").mkdir()
    
    return WorkflowState(
        issue_id="#123",
        branch="auto/feature/123",
        worktree=worktree_path,
        status=WorkflowStatus.IMPLEMENTING,
        ai_status=AIStatus.IMPLEMENTED,
        ai_response=AIResponse(
            success=True,
            response_type="implementation",
            content="Implementation completed successfully",
            file_changes=[
                {"action": "created", "path": "src/DarkMode.tsx"},
                {"action": "modified", "path": "src/App.tsx"}
            ],
            commands=["npm test"],
            metadata={}
        )
    )


@pytest.fixture
def mock_config():
    """Mock configuration."""
    config = MagicMock()
    config.github.pr_template = ".github/pull_request_template.md"
    config.github.default_reviewer = "reviewer1"
    config.github.default_branch = "main"
    config.workflows.test_command = "npm test"
    config.workflows.implementation_commit_message = "feat: implement {id} - {title}"
    return config


class TestCreatePullRequestWorkflow:
    """Test create_pull_request_workflow function."""

    @pytest.mark.anyio
    async def test_successful_pr_creation(self, sample_issue, workflow_state, mock_config):
        """Test successful PR creation workflow."""
        mock_pr = PullRequest(
            number=456,
            title="feat: Add dark mode support",
            description="PR description",
            status=PRStatus.OPEN,
            branch="auto/feature/123",
            url="https://github.com/owner/repo/pull/456"
        )
        
        with patch('auto.workflows.pr_create.validate_pr_prerequisites'), \
             patch('auto.workflows.pr_create.Config', return_value=mock_config), \
             patch('auto.workflows.pr_create.has_uncommitted_changes', return_value=True), \
             patch('auto.workflows.pr_create.commit_implementation_changes', new_callable=AsyncMock), \
             patch('auto.workflows.pr_create.push_branch_to_remote', new_callable=AsyncMock), \
             patch('auto.workflows.pr_create.GitHubIntegration') as mock_github_class, \
             patch('auto.workflows.pr_create.create_github_pr', new_callable=AsyncMock, return_value=mock_pr):
            
            mock_github = MagicMock()
            mock_github_class.return_value = mock_github
            
            result = await create_pull_request_workflow(sample_issue, workflow_state)
            
            # Verify state updates
            assert result.pr_number == 456
            assert result.status == WorkflowStatus.IN_REVIEW
            assert result.pr_metadata is not None
            assert result.pr_metadata.title == "feat: Add dark mode support"

    @pytest.mark.anyio
    async def test_no_changes_error(self, sample_issue, workflow_state, mock_config):
        """Test error when no changes to commit."""
        with patch('auto.workflows.pr_create.validate_pr_prerequisites'), \
             patch('auto.workflows.pr_create.Config', return_value=mock_config), \
             patch('auto.workflows.pr_create.has_uncommitted_changes', return_value=False), \
             patch('auto.workflows.pr_create.has_implementation_commits', return_value=False):
            
            with pytest.raises(PRCreationError) as excinfo:
                await create_pull_request_workflow(sample_issue, workflow_state)
            
            assert "No implementation changes found" in str(excinfo.value)

    @pytest.mark.anyio
    async def test_draft_pr_creation(self, sample_issue, workflow_state, mock_config):
        """Test creating draft PR."""
        mock_pr = PullRequest(
            number=456,
            title="feat: Add dark mode support",
            description="PR description",
            status=PRStatus.DRAFT,
            branch="auto/feature/123",
            url="https://github.com/owner/repo/pull/456"
        )
        
        with patch('auto.workflows.pr_create.validate_pr_prerequisites'), \
             patch('auto.workflows.pr_create.Config', return_value=mock_config), \
             patch('auto.workflows.pr_create.has_uncommitted_changes', return_value=True), \
             patch('auto.workflows.pr_create.commit_implementation_changes', new_callable=AsyncMock), \
             patch('auto.workflows.pr_create.push_branch_to_remote', new_callable=AsyncMock), \
             patch('auto.workflows.pr_create.GitHubIntegration'), \
             patch('auto.workflows.pr_create.create_github_pr', new_callable=AsyncMock, return_value=mock_pr):
            
            result = await create_pull_request_workflow(
                sample_issue, 
                workflow_state, 
                draft=True
            )
            
            assert result.pr_metadata.draft is True

    @pytest.mark.anyio
    async def test_pr_creation_failure(self, sample_issue, workflow_state, mock_config):
        """Test handling of PR creation failure."""
        from auto.integrations.github import GitHubError
        
        with patch('auto.workflows.pr_create.validate_pr_prerequisites'), \
             patch('auto.workflows.pr_create.Config', return_value=mock_config), \
             patch('auto.workflows.pr_create.has_uncommitted_changes', return_value=True), \
             patch('auto.workflows.pr_create.commit_implementation_changes', new_callable=AsyncMock), \
             patch('auto.workflows.pr_create.push_branch_to_remote', new_callable=AsyncMock), \
             patch('auto.workflows.pr_create.create_github_pr', new_callable=AsyncMock, 
                   side_effect=GitHubError("API error")):
            
            with pytest.raises(PRCreationError) as excinfo:
                await create_pull_request_workflow(sample_issue, workflow_state)
            
            assert "GitHub PR creation failed" in str(excinfo.value)
            assert workflow_state.status == WorkflowStatus.FAILED


class TestGeneratePRMetadata:
    """Test generate_pr_metadata function."""

    @pytest.mark.asyncio
    async def test_generate_pr_metadata(self, sample_issue, workflow_state, mock_config):
        """Test PR metadata generation."""
        metadata = await generate_pr_metadata(sample_issue, workflow_state, mock_config)
        
        assert metadata.title == "feat: Add dark mode support"
        assert "Closes #123" in metadata.description
        assert "Implementation completed successfully" in metadata.description
        assert "feature" in metadata.labels
        assert "ui" in metadata.labels
        assert "ai-implemented" in metadata.labels
        assert "developer" in metadata.assignees
        assert "reviewer1" in metadata.reviewers

    @pytest.mark.asyncio
    async def test_generate_pr_metadata_draft(self, sample_issue, workflow_state, mock_config):
        """Test PR metadata generation for draft."""
        metadata = await generate_pr_metadata(sample_issue, workflow_state, mock_config, draft=True)
        
        assert metadata.draft is True


class TestGeneratePRTitle:
    """Test generate_pr_title function."""

    def test_generate_title_with_feature_type(self, mock_config):
        """Test PR title generation with feature type."""
        issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Add dark mode support",
            description="Description",
            status=IssueStatus.OPEN,
            issue_type=IssueType.FEATURE
        )
        
        title = generate_pr_title(issue, mock_config)
        
        assert title == "feat: Add dark mode support"

    def test_generate_title_with_bug_type(self, mock_config):
        """Test PR title generation with bug type."""
        issue = Issue(
            id="#456",
            provider=IssueProvider.GITHUB,
            title="Fix login error",
            description="Description",
            status=IssueStatus.OPEN,
            issue_type=IssueType.BUG
        )
        
        title = generate_pr_title(issue, mock_config)
        
        assert title == "fix: Fix login error"

    def test_generate_title_no_type(self, mock_config):
        """Test PR title generation without issue type."""
        issue = Issue(
            id="#789",
            provider=IssueProvider.GITHUB,
            title="Update documentation",
            description="Description",
            status=IssueStatus.OPEN
        )
        
        title = generate_pr_title(issue, mock_config)
        
        assert title == "Update documentation"


class TestGeneratePRDescription:
    """Test generate_pr_description function."""

    @pytest.mark.asyncio
    async def test_generate_description_with_template(self, sample_issue, workflow_state, mock_config):
        """Test PR description generation with template."""
        with patch('auto.workflows.pr_create.load_pr_template', return_value="## Template\nTemplate content"):
            
            description = await generate_pr_description(sample_issue, workflow_state, mock_config)
            
            assert "## Template" in description
            assert "Template content" in description
            assert "Closes #123" in description
            assert "Implementation completed successfully" in description
            assert "Created: `src/DarkMode.tsx`" in description
            assert "Modified: `src/App.tsx`" in description
            assert "`npm test`" in description

    @pytest.mark.asyncio
    async def test_generate_description_without_template(self, sample_issue, workflow_state, mock_config):
        """Test PR description generation without template."""
        with patch('auto.workflows.pr_create.load_pr_template', return_value=None):
            
            description = await generate_pr_description(sample_issue, workflow_state, mock_config)
            
            assert "## Related Issue" in description
            assert "Closes #123" in description
            assert "## Implementation Summary" in description
            assert "## Testing" in description
            assert "## Review Checklist" in description

    @pytest.mark.asyncio
    async def test_generate_description_no_ai_response(self, sample_issue, mock_config):
        """Test PR description generation without AI response."""
        workflow_state = WorkflowState(
            issue_id="#123",
            branch="auto/feature/123",
            status=WorkflowStatus.IMPLEMENTING
        )
        
        with patch('auto.workflows.pr_create.load_pr_template', return_value=None):
            
            description = await generate_pr_description(sample_issue, workflow_state, mock_config)
            
            assert "Closes #123" in description
            assert "## Testing" in description
            # Should not contain implementation summary
            assert "## Implementation Summary" not in description


class TestLoadPRTemplate:
    """Test load_pr_template function."""

    def test_load_existing_template(self, mock_config, tmp_path):
        """Test loading existing PR template."""
        template_path = tmp_path / "template.md"
        template_content = "## Description\nPlease describe your changes"
        template_path.write_text(template_content)
        
        mock_config.github.pr_template = str(template_path)
        
        result = load_pr_template(mock_config)
        
        assert result == template_content

    def test_load_nonexistent_template(self, mock_config):
        """Test loading non-existent PR template."""
        mock_config.github.pr_template = "/nonexistent/template.md"
        
        result = load_pr_template(mock_config)
        
        assert result is None


class TestDeterminePRLabels:
    """Test determine_pr_labels function."""

    def test_determine_labels_with_ai_response(self, sample_issue, workflow_state):
        """Test label determination with AI response."""
        workflow_state.ai_response.file_changes = [
            {"action": "created", "path": "src/component.tsx"},
            {"action": "modified", "path": "tests/component.test.ts"},
            {"action": "created", "path": "docs/README.md"}
        ]
        
        labels = determine_pr_labels(sample_issue, workflow_state)
        
        assert "feature" in labels
        assert "ui" in labels
        assert "ai-implemented" in labels
        assert "tests" in labels
        assert "documentation" in labels

    def test_determine_labels_without_ai_response(self, sample_issue):
        """Test label determination without AI response."""
        workflow_state = WorkflowState(
            issue_id="#123",
            branch="auto/feature/123",
            status=WorkflowStatus.IMPLEMENTING
        )
        
        labels = determine_pr_labels(sample_issue, workflow_state)
        
        assert "feature" in labels
        assert "ui" in labels
        assert "ai-implemented" not in labels


class TestDeterminePRAssigneesAndReviewers:
    """Test determine_pr_assignees and determine_pr_reviewers functions."""

    def test_determine_assignees(self, sample_issue, mock_config):
        """Test assignee determination."""
        assignees = determine_pr_assignees(sample_issue, mock_config)
        
        assert "developer" in assignees

    def test_determine_reviewers(self, sample_issue, mock_config):
        """Test reviewer determination."""
        reviewers = determine_pr_reviewers(sample_issue, mock_config)
        
        assert "reviewer1" in reviewers

    def test_determine_assignees_no_assignee(self, mock_config):
        """Test assignee determination without issue assignee."""
        issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Test issue",
            description="Description",
            status=IssueStatus.OPEN
        )
        
        assignees = determine_pr_assignees(issue, mock_config)
        
        assert len(assignees) == 0


class TestCommitImplementationChanges:
    """Test commit_implementation_changes function."""

    @pytest.mark.anyio
    async def test_successful_commit(self, sample_issue, workflow_state, mock_config):
        """Test successful commit of implementation changes."""
        with patch('subprocess.run') as mock_run:
            # Mock successful git add
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # git add
                MagicMock(returncode=0, stdout="[main abc123] commit message", stderr="")  # git commit
            ]
            
            await commit_implementation_changes(sample_issue, workflow_state, mock_config)
            
            # Verify git commands were called
            assert mock_run.call_count == 2
            mock_run.assert_any_call(
                ["git", "add", "."],
                cwd=workflow_state.worktree,
                capture_output=True,
                text=True,
                timeout=30
            )

    @pytest.mark.anyio
    async def test_commit_nothing_to_commit(self, sample_issue, workflow_state, mock_config):
        """Test commit when nothing to commit."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # git add
                MagicMock(returncode=1, stdout="nothing to commit", stderr="")  # git commit
            ]
            
            # Should not raise
            await commit_implementation_changes(sample_issue, workflow_state, mock_config)

    @pytest.mark.anyio
    async def test_commit_failure(self, sample_issue, workflow_state, mock_config):
        """Test commit failure handling."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # git add
                MagicMock(returncode=1, stdout="", stderr="commit failed")  # git commit
            ]
            
            with pytest.raises(PRCreationError) as excinfo:
                await commit_implementation_changes(sample_issue, workflow_state, mock_config)
            
            assert "Failed to commit changes" in str(excinfo.value)


class TestGenerateCommitMessage:
    """Test generate_commit_message function."""

    def test_generate_commit_message_with_template(self, sample_issue, workflow_state, mock_config):
        """Test commit message generation with template."""
        message = generate_commit_message(sample_issue, workflow_state, mock_config)
        
        assert message == "feat: implement #123 - Add dark mode support"

    def test_generate_commit_message_template_error(self, sample_issue, workflow_state):
        """Test commit message generation with template error."""
        config = MagicMock()
        config.workflows.implementation_commit_message = "Invalid {unknown_var}"
        
        message = generate_commit_message(sample_issue, workflow_state, config)
        
        # Should fallback to simple message
        assert message == "Implement #123: Add dark mode support"


class TestPushBranchToRemote:
    """Test push_branch_to_remote function."""

    @pytest.mark.anyio
    async def test_successful_push(self, workflow_state):
        """Test successful branch push."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            
            await push_branch_to_remote(workflow_state)
            
            mock_run.assert_called_once_with(
                ["git", "push", "-u", "origin", workflow_state.branch],
                cwd=workflow_state.worktree,
                capture_output=True,
                text=True,
                timeout=60
            )

    @pytest.mark.anyio
    async def test_push_failure(self, workflow_state):
        """Test push failure handling."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="push failed")
            
            with pytest.raises(PRCreationError) as excinfo:
                await push_branch_to_remote(workflow_state)
            
            assert "Failed to push branch" in str(excinfo.value)


class TestCreateGitHubPR:
    """Test create_github_pr function."""

    @pytest.mark.anyio
    async def test_create_github_pr_success(self, workflow_state):
        """Test successful GitHub PR creation."""
        mock_github = MagicMock()
        mock_pr = PullRequest(
            number=456,
            title="Test PR",
            description="Description",
            status=PRStatus.OPEN,
            branch="auto/feature/123",
            url="https://github.com/owner/repo/pull/456"
        )
        mock_github.create_pull_request = AsyncMock(return_value=mock_pr)
        mock_github.add_pr_labels = AsyncMock()
        mock_github.add_pr_assignees = AsyncMock()
        mock_github.request_pr_reviewers = AsyncMock()
        
        pr_metadata = PRMetadata(
            title="Test PR",
            description="Description",
            labels=["feature"],
            assignees=["dev"],
            reviewers=["reviewer"],
            draft=False
        )
        
        result = await create_github_pr(mock_github, pr_metadata, workflow_state)
        
        assert result == mock_pr
        mock_github.create_pull_request.assert_called_once()
        mock_github.add_pr_labels.assert_called_once_with(456, ["feature"])
        mock_github.add_pr_assignees.assert_called_once_with(456, ["dev"])
        mock_github.request_pr_reviewers.assert_called_once_with(456, ["reviewer"])


class TestValidatePRPrerequisites:
    """Test validate_pr_prerequisites function."""

    def test_valid_prerequisites(self, workflow_state):
        """Test validation with valid prerequisites."""
        # Should not raise
        validate_pr_prerequisites(workflow_state)

    def test_no_worktree(self):
        """Test validation with no worktree."""
        workflow_state = WorkflowState(
            issue_id="#123",
            branch="auto/feature/123",
            worktree=None,
            status=WorkflowStatus.IMPLEMENTING
        )
        
        with pytest.raises(PRCreationError) as excinfo:
            validate_pr_prerequisites(workflow_state)
        
        assert "No worktree available" in str(excinfo.value)

    def test_no_branch(self, tmp_path):
        """Test validation with no branch."""
        worktree_path = str(tmp_path / "worktree")
        Path(worktree_path).mkdir()
        (Path(worktree_path) / ".git").mkdir()
        
        workflow_state = WorkflowState(
            issue_id="#123",
            branch=None,
            worktree=worktree_path,
            status=WorkflowStatus.IMPLEMENTING
        )
        
        with pytest.raises(PRCreationError) as excinfo:
            validate_pr_prerequisites(workflow_state)
        
        assert "No branch specified" in str(excinfo.value)


class TestUtilityFunctions:
    """Test utility functions."""

    def test_has_uncommitted_changes_true(self, tmp_path):
        """Test has_uncommitted_changes when changes exist."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="M  file1.txt\n")
            
            result = has_uncommitted_changes(str(tmp_path))
            
            assert result is True

    def test_has_uncommitted_changes_false(self, tmp_path):
        """Test has_uncommitted_changes when no changes."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            
            result = has_uncommitted_changes(str(tmp_path))
            
            assert result is False

    def test_has_implementation_commits_true(self, tmp_path):
        """Test has_implementation_commits when commits exist."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="3\n")
            
            result = has_implementation_commits(str(tmp_path), "feature-branch")
            
            assert result is True

    def test_has_implementation_commits_false(self, tmp_path):
        """Test has_implementation_commits when no commits."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
            
            result = has_implementation_commits(str(tmp_path), "feature-branch")
            
            assert result is False

    def test_get_pr_creation_summary(self, workflow_state):
        """Test PR creation summary generation."""
        workflow_state.pr_number = 456
        workflow_state.pr_metadata = PRMetadata(
            title="Test PR",
            description="Description",
            labels=["feature", "ui"],
            assignees=["dev"],
            reviewers=["reviewer1", "reviewer2"],
            draft=False
        )
        
        summary = get_pr_creation_summary(workflow_state)
        
        assert "PR #456 created" in summary
        assert "with 2 labels" in summary
        assert "and 2 reviewers" in summary

    def test_get_pr_creation_summary_no_pr(self):
        """Test PR creation summary when no PR created."""
        workflow_state = WorkflowState(
            issue_id="#123",
            status=WorkflowStatus.IMPLEMENTING
        )
        
        summary = get_pr_creation_summary(workflow_state)
        
        assert summary == "PR not created yet"