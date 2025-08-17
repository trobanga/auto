"""Tests for GitHub integration."""

import json
import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from auto.integrations.github import (
    GitHubIntegration,
    GitHubAuthError,
    GitHubRepositoryError,
    GitHubIssueError,
    validate_github_auth,
    detect_repository,
)
from auto.models import GitHubRepository, Issue, IssueProvider, IssueStatus
from auto.utils.shell import ShellError, ShellResult


class TestGitHubAuth:
    """Test GitHub authentication."""
    
    @patch("auto.integrations.github.check_command_exists")
    def test_validate_github_auth_no_gh_cli(self, mock_check_command):
        """Test validation fails when gh CLI is not installed."""
        mock_check_command.return_value = False
        
        result = validate_github_auth()
        assert result is False
        mock_check_command.assert_called_once_with("gh")
    
    @patch("auto.integrations.github.run_command")
    @patch("auto.integrations.github.check_command_exists")
    def test_validate_github_auth_success(self, mock_check_command, mock_run_command):
        """Test successful GitHub authentication validation."""
        mock_check_command.return_value = True
        mock_run_command.return_value = ShellResult(0, "", "", "gh auth status")
        
        result = validate_github_auth()
        assert result is True
        mock_run_command.assert_called_once_with("gh auth status", check=False)
    
    @patch("auto.integrations.github.run_command")
    @patch("auto.integrations.github.check_command_exists")
    def test_validate_github_auth_failure(self, mock_check_command, mock_run_command):
        """Test GitHub authentication validation failure."""
        mock_check_command.return_value = True
        mock_run_command.return_value = ShellResult(1, "", "Not authenticated", "gh auth status")
        
        result = validate_github_auth()
        assert result is False
    
    @patch("auto.integrations.github.run_command")
    @patch("auto.integrations.github.check_command_exists")
    def test_validate_github_auth_exception(self, mock_check_command, mock_run_command):
        """Test GitHub authentication validation with exception."""
        mock_check_command.return_value = True
        mock_run_command.side_effect = ShellError("Command failed", 1)
        
        result = validate_github_auth()
        assert result is False


class TestRepositoryDetection:
    """Test GitHub repository detection."""
    
    @patch("auto.integrations.github.run_command")
    def test_detect_repository_https_url(self, mock_run_command):
        """Test repository detection from HTTPS URL."""
        mock_run_command.side_effect = [
            ShellResult(0, "https://github.com/owner/repo.git", "", "git remote get-url origin"),
            ShellResult(0, "refs/remotes/origin/main", "", "git symbolic-ref refs/remotes/origin/HEAD"),
        ]
        
        repo = detect_repository()
        assert repo is not None
        assert repo.owner == "owner"
        assert repo.name == "repo"
        assert repo.default_branch == "main"
        assert repo.remote_url == "https://github.com/owner/repo.git"
    
    @patch("auto.integrations.github.run_command")
    def test_detect_repository_ssh_url(self, mock_run_command):
        """Test repository detection from SSH URL."""
        mock_run_command.side_effect = [
            ShellResult(0, "git@github.com:owner/repo.git", "", "git remote get-url origin"),
            ShellResult(1, "", "error", "git symbolic-ref refs/remotes/origin/HEAD"),
            ShellResult(0, "main", "", "git ls-remote --heads origin main"),
            ShellResult(1, "", "error", "git ls-remote --heads origin master"),
        ]
        
        repo = detect_repository()
        assert repo is not None
        assert repo.owner == "owner"
        assert repo.name == "repo"
        assert repo.default_branch == "main"
        assert repo.remote_url == "git@github.com:owner/repo.git"
    
    @patch("auto.integrations.github.run_command")
    def test_detect_repository_master_branch(self, mock_run_command):
        """Test repository detection with master branch."""
        mock_run_command.side_effect = [
            ShellResult(0, "https://github.com/owner/repo", "", "git remote get-url origin"),
            ShellResult(1, "", "error", "git symbolic-ref refs/remotes/origin/HEAD"),
            ShellResult(1, "", "no main", "git ls-remote --heads origin main"),
            ShellResult(0, "master", "", "git ls-remote --heads origin master"),
        ]
        
        repo = detect_repository()
        assert repo is not None
        assert repo.default_branch == "master"
    
    @patch("auto.integrations.github.run_command")
    def test_detect_repository_no_remote(self, mock_run_command):
        """Test repository detection fails with no remote."""
        mock_run_command.side_effect = ShellError("fatal: not a git repository", 128)
        
        repo = detect_repository()
        assert repo is None
    
    @patch("auto.integrations.github.run_command")
    def test_detect_repository_non_github(self, mock_run_command):
        """Test repository detection fails with non-GitHub remote."""
        mock_run_command.return_value = ShellResult(0, "https://gitlab.com/owner/repo.git", "", "git remote get-url origin")
        
        repo = detect_repository()
        assert repo is None


class TestGitHubIntegration:
    """Test GitHub integration class."""
    
    @patch("auto.integrations.github.validate_github_auth")
    def test_github_integration_init_success(self, mock_validate_auth):
        """Test successful GitHub integration initialization."""
        mock_validate_auth.return_value = True
        
        integration = GitHubIntegration()
        assert integration is not None
        mock_validate_auth.assert_called_once()
    
    @patch("auto.integrations.github.validate_github_auth")
    def test_github_integration_init_auth_failure(self, mock_validate_auth):
        """Test GitHub integration initialization with auth failure."""
        mock_validate_auth.return_value = False
        
        with pytest.raises(GitHubAuthError, match="GitHub CLI authentication required"):
            GitHubIntegration()
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.detect_repository")
    def test_detect_repository_success(self, mock_detect_repo, mock_validate_auth):
        """Test successful repository detection."""
        mock_validate_auth.return_value = True
        mock_repo = GitHubRepository(owner="owner", name="repo")
        mock_detect_repo.return_value = mock_repo
        
        integration = GitHubIntegration()
        repo = integration.detect_repository()
        
        assert repo == mock_repo
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.detect_repository")
    def test_detect_repository_failure(self, mock_detect_repo, mock_validate_auth):
        """Test repository detection failure."""
        mock_validate_auth.return_value = True
        mock_detect_repo.return_value = None
        
        integration = GitHubIntegration()
        
        with pytest.raises(GitHubRepositoryError, match="Could not detect GitHub repository"):
            integration.detect_repository()


class TestIssureFetching:
    """Test GitHub issue fetching."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.sample_issue_data = {
            "number": 123,
            "title": "Test issue",
            "body": "Test description",
            "state": "OPEN",
            "labels": [{"name": "bug"}, {"name": "priority-high"}],
            "assignees": [{"login": "testuser"}],
            "createdAt": "2024-01-15T10:00:00Z",
            "updatedAt": "2024-01-15T11:00:00Z",
            "url": "https://github.com/owner/repo/issues/123"
        }
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.run_command")
    def test_fetch_issue_success(self, mock_run_command, mock_validate_auth):
        """Test successful issue fetching."""
        mock_validate_auth.return_value = True
        mock_run_command.return_value = ShellResult(
            0, 
            json.dumps(self.sample_issue_data), 
            "", 
            "gh issue view 123"
        )
        
        integration = GitHubIntegration()
        repo = GitHubRepository(owner="owner", name="repo")
        
        issue = integration.fetch_issue("123", repository=repo)
        
        assert issue.id == "#123"
        assert issue.provider == IssueProvider.GITHUB
        assert issue.title == "Test issue"
        assert issue.description == "Test description"
        assert issue.status == IssueStatus.OPEN
        assert issue.labels == ["bug", "priority-high"]
        assert issue.assignee == "testuser"
        assert issue.url == "https://github.com/owner/repo/issues/123"
        assert issue.issue_type is not None  # Should be inferred from labels
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.run_command")
    def test_fetch_issue_with_hash_prefix(self, mock_run_command, mock_validate_auth):
        """Test issue fetching with # prefix in issue ID."""
        mock_validate_auth.return_value = True
        mock_run_command.return_value = ShellResult(
            0, 
            json.dumps(self.sample_issue_data), 
            "", 
            "gh issue view 123"
        )
        
        integration = GitHubIntegration()
        repo = GitHubRepository(owner="owner", name="repo")
        
        issue = integration.fetch_issue("#123", repository=repo)
        assert issue.id == "#123"
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.detect_repository")
    @patch("auto.integrations.github.run_command")
    def test_fetch_issue_auto_detect_repo(self, mock_run_command, mock_detect_repo, mock_validate_auth):
        """Test issue fetching with auto-detected repository."""
        mock_validate_auth.return_value = True
        mock_repo = GitHubRepository(owner="owner", name="repo")
        mock_detect_repo.return_value = mock_repo
        mock_run_command.return_value = ShellResult(
            0, 
            json.dumps(self.sample_issue_data), 
            "", 
            "gh issue view 123"
        )
        
        integration = GitHubIntegration()
        issue = integration.fetch_issue("123")
        
        assert issue.id == "#123"
        mock_detect_repo.assert_called_once()
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.run_command")
    def test_fetch_issue_not_found(self, mock_run_command, mock_validate_auth):
        """Test issue fetching with non-existent issue."""
        mock_validate_auth.return_value = True
        mock_run_command.side_effect = ShellError(
            "Command failed", 
            1, 
            "", 
            "could not resolve to an Issue"
        )
        
        integration = GitHubIntegration()
        repo = GitHubRepository(owner="owner", name="repo")
        
        with pytest.raises(GitHubIssueError, match="Issue #123 not found"):
            integration.fetch_issue("123", repository=repo)
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.run_command")
    def test_fetch_issue_repo_not_found(self, mock_run_command, mock_validate_auth):
        """Test issue fetching with non-existent repository."""
        mock_validate_auth.return_value = True
        mock_run_command.side_effect = ShellError(
            "Command failed", 
            1, 
            "", 
            "HTTP 404: Not Found"
        )
        
        integration = GitHubIntegration()
        repo = GitHubRepository(owner="owner", name="repo")
        
        with pytest.raises(GitHubIssueError, match="Repository owner/repo not found"):
            integration.fetch_issue("123", repository=repo)
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.run_command")
    def test_fetch_issue_json_parse_error(self, mock_run_command, mock_validate_auth):
        """Test issue fetching with invalid JSON response."""
        mock_validate_auth.return_value = True
        mock_run_command.return_value = ShellResult(0, "invalid json", "", "gh issue view 123")
        
        integration = GitHubIntegration()
        repo = GitHubRepository(owner="owner", name="repo")
        
        with pytest.raises(GitHubIssueError, match="Failed to parse issue data"):
            integration.fetch_issue("123", repository=repo)
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.run_command")
    def test_fetch_issue_closed_status(self, mock_run_command, mock_validate_auth):
        """Test issue fetching with closed status."""
        mock_validate_auth.return_value = True
        closed_issue_data = self.sample_issue_data.copy()
        closed_issue_data["state"] = "CLOSED"
        mock_run_command.return_value = ShellResult(
            0, 
            json.dumps(closed_issue_data), 
            "", 
            "gh issue view 123"
        )
        
        integration = GitHubIntegration()
        repo = GitHubRepository(owner="owner", name="repo")
        
        issue = integration.fetch_issue("123", repository=repo)
        assert issue.status == IssueStatus.CLOSED
    
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.integrations.github.run_command")
    def test_fetch_issue_minimal_data(self, mock_run_command, mock_validate_auth):
        """Test issue fetching with minimal issue data."""
        mock_validate_auth.return_value = True
        minimal_issue_data = {
            "number": 123,
            "title": "Minimal issue",
            "state": "OPEN"
        }
        mock_run_command.return_value = ShellResult(
            0, 
            json.dumps(minimal_issue_data), 
            "", 
            "gh issue view 123"
        )
        
        integration = GitHubIntegration()
        repo = GitHubRepository(owner="owner", name="repo")
        
        issue = integration.fetch_issue("123", repository=repo)
        assert issue.id == "#123"
        assert issue.title == "Minimal issue"
        assert issue.description == ""
        assert issue.labels == []
        assert issue.assignee is None
        assert issue.url is None
        assert issue.created_at is None
        assert issue.updated_at is None