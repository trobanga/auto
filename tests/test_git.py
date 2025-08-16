"""Tests for git worktree management."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from auto.integrations.git import (
    GitWorktreeManager,
    GitWorktreeError,
    GitWorktreeConflictError,
    create_worktree,
    cleanup_worktree,
)
from auto.models import Config, Issue, IssueProvider, IssueType, WorktreeInfo
from auto.utils.shell import ShellError, ShellResult


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    config = Mock(spec=Config)
    
    # Mock defaults
    defaults = Mock()
    defaults.worktree_base = "../{project}-worktrees"
    config.defaults = defaults
    
    # Mock workflows
    workflows = Mock()
    workflows.branch_naming = "auto/{issue_type}/{issue_id}"
    workflows.worktree_conflict_resolution = "prompt"
    config.workflows = workflows
    
    return config


@pytest.fixture
def sample_issue():
    """Create sample issue."""
    return Issue(
        id="#123",
        provider=IssueProvider.GITHUB,
        title="Test issue",
        description="Test description",
        status="open",
        issue_type=IssueType.FEATURE,
        labels=["feature"]
    )


@pytest.fixture
def sample_worktree_info():
    """Create sample worktree info."""
    return WorktreeInfo(
        path="/tmp/test-worktree",
        branch="auto/feature/123",
        issue_id="#123"
    )


class TestGitWorktreeManager:
    """Test git worktree manager."""
    
    @patch("auto.integrations.git.get_git_root")
    def test_init_success(self, mock_get_git_root, mock_config):
        """Test successful initialization."""
        mock_get_git_root.return_value = Path("/repo")
        
        manager = GitWorktreeManager(mock_config)
        assert manager.config == mock_config
    
    @patch("auto.integrations.git.get_git_root")
    def test_init_not_git_repo(self, mock_get_git_root, mock_config):
        """Test initialization fails when not in git repo."""
        mock_get_git_root.return_value = None
        
        with pytest.raises(GitWorktreeError, match="Not in a git repository"):
            GitWorktreeManager(mock_config)


class TestBranchNaming:
    """Test branch naming logic."""
    
    @patch("auto.integrations.git.get_git_root")
    def test_generate_branch_name_feature(self, mock_get_git_root, mock_config, sample_issue):
        """Test branch name generation for feature."""
        mock_get_git_root.return_value = Path("/repo")
        
        manager = GitWorktreeManager(mock_config)
        branch_name = manager.generate_branch_name(sample_issue)
        
        assert branch_name == "auto/feature/123"
    
    @patch("auto.integrations.git.get_git_root")
    def test_generate_branch_name_bug(self, mock_get_git_root, mock_config):
        """Test branch name generation for bug."""
        mock_get_git_root.return_value = Path("/repo")
        
        bug_issue = Issue(
            id="#456",
            provider=IssueProvider.GITHUB,
            title="Bug issue",
            description="Bug description",
            status="open",
            issue_type=IssueType.BUG,
        )
        
        manager = GitWorktreeManager(mock_config)
        branch_name = manager.generate_branch_name(bug_issue)
        
        assert branch_name == "auto/bug/456"
    
    @patch("auto.integrations.git.get_git_root")
    def test_generate_branch_name_sanitization(self, mock_get_git_root, mock_config):
        """Test branch name sanitization."""
        mock_get_git_root.return_value = Path("/repo")
        
        issue = Issue(
            id="ENG-456",
            provider=IssueProvider.LINEAR,
            title="Issue with special chars!",
            description="Description",
            status="open",
            issue_type=IssueType.FEATURE,
        )
        
        manager = GitWorktreeManager(mock_config)
        branch_name = manager.generate_branch_name(issue)
        
        assert branch_name == "auto/feature/ENG-456"
        assert "/" in branch_name  # Forward slashes should be preserved
        assert "!" not in branch_name  # Special chars should be removed
    
    @patch("auto.integrations.git.get_git_root")
    def test_sanitize_branch_name(self, mock_get_git_root, mock_config):
        """Test branch name sanitization edge cases."""
        mock_get_git_root.return_value = Path("/repo")
        
        manager = GitWorktreeManager(mock_config)
        
        # Test various problematic characters
        assert manager._sanitize_branch_name("test/branch") == "test/branch"
        assert manager._sanitize_branch_name("test@branch") == "test-branch"
        assert manager._sanitize_branch_name("test branch") == "test-branch"
        assert manager._sanitize_branch_name("test--branch") == "test-branch"
        assert manager._sanitize_branch_name("-test-") == "test"
        assert manager._sanitize_branch_name("./test") == "test"


class TestWorktreePath:
    """Test worktree path generation."""
    
    @patch("auto.integrations.git.get_git_root")
    def test_generate_worktree_path(self, mock_get_git_root, mock_config):
        """Test worktree path generation."""
        mock_get_git_root.return_value = Path("/repo")
        
        manager = GitWorktreeManager(mock_config)
        worktree_path = manager.generate_worktree_path("auto/feature/123")
        
        expected_path = Path("/repo-worktrees/auto-feature-123")
        assert worktree_path == expected_path
    
    @patch("auto.integrations.git.get_git_root")
    def test_generate_worktree_path_absolute_base(self, mock_get_git_root, mock_config):
        """Test worktree path generation with absolute base."""
        mock_get_git_root.return_value = Path("/repo")
        mock_config.defaults.worktree_base = "/custom/worktrees"
        
        manager = GitWorktreeManager(mock_config)
        worktree_path = manager.generate_worktree_path("auto/bug/456")
        
        expected_path = Path("/custom/worktrees/auto-bug-456")
        assert worktree_path == expected_path
    
    @patch("auto.integrations.git.get_git_root")
    def test_generate_worktree_path_no_git_root(self, mock_get_git_root, mock_config):
        """Test worktree path generation when git root is None."""
        mock_get_git_root.return_value = None
        
        # This should not happen as __init__ validates git repo, but test defensive code
        with pytest.raises(GitWorktreeError):
            GitWorktreeManager(mock_config)


class TestWorktreeCreation:
    """Test worktree creation."""
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_create_worktree_success(self, mock_run_command, mock_get_git_root, mock_config, sample_issue):
        """Test successful worktree creation."""
        mock_get_git_root.return_value = Path("/repo")
        
        # Mock successful command executions
        mock_run_command.side_effect = [
            ShellResult(0, "", "", "git fetch"),  # fetch
            ShellResult(0, "main", "", "git branch --list main"),  # base branch check
            ShellResult(0, "", "", "git branch --list auto/feature/123"),  # branch conflict check
            ShellResult(0, "", "", "git worktree add"),  # worktree creation
        ]
        
        with patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'mkdir'):
            
            manager = GitWorktreeManager(mock_config)
            worktree_info = manager.create_worktree(sample_issue)
            
            assert worktree_info.branch == "auto/feature/123"
            assert worktree_info.issue_id == "#123"
            assert "auto-feature-123" in worktree_info.path
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_create_worktree_branch_conflict(self, mock_run_command, mock_get_git_root, mock_config, sample_issue):
        """Test worktree creation with branch conflict."""
        mock_get_git_root.return_value = Path("/repo")
        
        # Mock branch already exists
        mock_run_command.side_effect = [
            ShellResult(0, "", "", "git fetch"),  # fetch
            ShellResult(0, "main", "", "git branch --list main"),  # base branch check
            ShellResult(0, "auto/feature/123", "", "git branch --list auto/feature/123"),  # branch exists
        ]
        
        with patch.object(Path, 'exists', return_value=False):
            manager = GitWorktreeManager(mock_config)
            
            with pytest.raises(GitWorktreeConflictError, match="Branch auto/feature/123 already exists"):
                manager.create_worktree(sample_issue)
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_create_worktree_force_branch_conflict(self, mock_run_command, mock_get_git_root, mock_config, sample_issue):
        """Test worktree creation with force resolution of branch conflict."""
        mock_get_git_root.return_value = Path("/repo")
        mock_config.workflows.worktree_conflict_resolution = "force"
        
        # Mock branch already exists, then successful deletion and creation
        mock_run_command.side_effect = [
            ShellResult(0, "", "", "git fetch"),  # fetch
            ShellResult(0, "main", "", "git branch --list main"),  # base branch check
            ShellResult(0, "auto/feature/123", "", "git branch --list auto/feature/123"),  # branch exists
            ShellResult(0, "", "", "git branch -D auto/feature/123"),  # force delete
            ShellResult(0, "", "", "git worktree add"),  # worktree creation
        ]
        
        with patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'mkdir'):
            
            manager = GitWorktreeManager(mock_config)
            worktree_info = manager.create_worktree(sample_issue)
            
            assert worktree_info.branch == "auto/feature/123"
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_create_worktree_path_conflict(self, mock_run_command, mock_get_git_root, mock_config, sample_issue):
        """Test worktree creation with path conflict."""
        mock_get_git_root.return_value = Path("/repo")
        
        mock_run_command.side_effect = [
            ShellResult(0, "", "", "git fetch"),  # fetch
            ShellResult(0, "main", "", "git branch --list main"),  # base branch check
            ShellResult(0, "", "", "git branch --list auto/feature/123"),  # no branch conflict
        ]
        
        with patch.object(Path, 'exists', return_value=True):  # Path exists
            manager = GitWorktreeManager(mock_config)
            
            with pytest.raises(GitWorktreeConflictError, match="already exists"):
                manager.create_worktree(sample_issue)
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_create_worktree_base_branch_not_found(self, mock_run_command, mock_get_git_root, mock_config, sample_issue):
        """Test worktree creation with missing base branch."""
        mock_get_git_root.return_value = Path("/repo")
        
        mock_run_command.side_effect = [
            ShellResult(0, "", "", "git fetch"),  # fetch
            ShellResult(0, "", "", "git branch --list main"),  # base branch doesn't exist locally
            ShellResult(0, "", "", "git ls-remote --heads origin main"),  # base branch doesn't exist on remote
        ]
        
        with patch.object(Path, 'exists', return_value=False):
            manager = GitWorktreeManager(mock_config)
            
            with pytest.raises(GitWorktreeError, match="Base branch 'main' not found"):
                manager.create_worktree(sample_issue)
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_create_worktree_git_failure(self, mock_run_command, mock_get_git_root, mock_config, sample_issue):
        """Test worktree creation with git command failure."""
        mock_get_git_root.return_value = Path("/repo")
        
        mock_run_command.side_effect = [
            ShellResult(0, "", "", "git fetch"),  # fetch
            ShellResult(0, "main", "", "git branch --list main"),  # base branch check
            ShellResult(0, "", "", "git branch --list auto/feature/123"),  # branch conflict check
            ShellError("Git worktree add failed", 1, "", "fatal: could not create worktree"),  # git worktree add fails
        ]
        
        with patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'mkdir'):
            
            manager = GitWorktreeManager(mock_config)
            
            with pytest.raises(GitWorktreeError, match="Failed to create worktree"):
                manager.create_worktree(sample_issue)


class TestWorktreeCleanup:
    """Test worktree cleanup."""
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_cleanup_worktree_success(self, mock_run_command, mock_get_git_root, mock_config, sample_worktree_info):
        """Test successful worktree cleanup."""
        mock_get_git_root.return_value = Path("/repo")
        
        mock_run_command.side_effect = [
            ShellResult(0, "", "", "git worktree remove"),  # worktree removal
            ShellResult(0, "auto/feature/123", "", "git branch --list auto/feature/123"),  # branch exists
            ShellResult(0, "", "", "git branch -D auto/feature/123"),  # branch deletion
        ]
        
        with patch.object(sample_worktree_info, 'exists', return_value=True):
            manager = GitWorktreeManager(mock_config)
            manager.cleanup_worktree(sample_worktree_info)
            
            # Should complete without raising exceptions
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    @patch("auto.integrations.git.shutil")
    def test_cleanup_worktree_force_removal(self, mock_shutil, mock_run_command, mock_get_git_root, mock_config, sample_worktree_info):
        """Test worktree cleanup with force removal."""
        mock_get_git_root.return_value = Path("/repo")
        
        # First removal fails, force removal succeeds
        mock_run_command.side_effect = [
            ShellResult(1, "", "failed", "git worktree remove"),  # worktree removal fails
            ShellResult(0, "", "", "git worktree remove --force"),  # force removal succeeds
            ShellResult(0, "auto/feature/123", "", "git branch --list auto/feature/123"),  # branch exists
            ShellResult(0, "", "", "git branch -D auto/feature/123"),  # branch deletion
        ]
        
        with patch.object(sample_worktree_info, 'exists', return_value=True):
            manager = GitWorktreeManager(mock_config)
            manager.cleanup_worktree(sample_worktree_info)
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    @patch("auto.integrations.git.shutil.rmtree")
    def test_cleanup_worktree_manual_removal(self, mock_rmtree, mock_run_command, mock_get_git_root, mock_config, sample_worktree_info):
        """Test worktree cleanup with manual directory removal."""
        mock_get_git_root.return_value = Path("/repo")
        
        # Both git removals fail
        mock_run_command.side_effect = [
            ShellResult(1, "", "failed", "git worktree remove"),  # worktree removal fails
            ShellResult(1, "", "failed", "git worktree remove --force"),  # force removal fails
            ShellResult(0, "auto/feature/123", "", "git branch --list auto/feature/123"),  # branch exists
            ShellResult(0, "", "", "git branch -D auto/feature/123"),  # branch deletion
        ]
        
        with patch.object(sample_worktree_info, 'exists', return_value=True), \
             patch.object(sample_worktree_info.path_obj, 'exists', return_value=True):
            
            manager = GitWorktreeManager(mock_config)
            manager.cleanup_worktree(sample_worktree_info)
            
            # Should call manual removal
            mock_rmtree.assert_called_once()
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_cleanup_worktree_errors(self, mock_run_command, mock_get_git_root, mock_config, sample_worktree_info):
        """Test worktree cleanup with persistent errors."""
        mock_get_git_root.return_value = Path("/repo")
        
        # All operations fail
        mock_run_command.side_effect = [
            ShellResult(1, "", "failed", "git worktree remove"),  # worktree removal fails
            ShellResult(1, "", "failed", "git worktree remove --force"),  # force removal fails
            ShellResult(0, "auto/feature/123", "", "git branch --list auto/feature/123"),  # branch exists
            ShellResult(1, "", "failed", "git branch -D auto/feature/123"),  # branch deletion fails
        ]
        
        with patch.object(sample_worktree_info, 'exists', return_value=True), \
             patch.object(sample_worktree_info.path_obj, 'exists', return_value=False):
            
            manager = GitWorktreeManager(mock_config)
            
            with pytest.raises(GitWorktreeError, match="Worktree cleanup completed with errors"):
                manager.cleanup_worktree(sample_worktree_info)


class TestWorktreeListing:
    """Test worktree listing."""
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_list_worktrees_success(self, mock_run_command, mock_get_git_root, mock_config):
        """Test successful worktree listing."""
        mock_get_git_root.return_value = Path("/repo")
        
        # Mock git worktree list output
        worktree_output = """worktree /repo
HEAD abcd1234

worktree /repo-worktrees/auto-feature-123
branch auto/feature/123
HEAD efgh5678

worktree /repo-worktrees/auto-bug-456
branch auto/bug/456
HEAD ijkl9012
"""
        
        mock_run_command.return_value = ShellResult(0, worktree_output.strip(), "", "git worktree list --porcelain")
        
        manager = GitWorktreeManager(mock_config)
        worktrees = manager.list_worktrees()
        
        assert len(worktrees) == 2  # Should exclude main worktree
        assert worktrees[0].branch == "auto/feature/123"
        assert worktrees[0].issue_id == "123"
        assert worktrees[1].branch == "auto/bug/456"
        assert worktrees[1].issue_id == "456"
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_list_worktrees_empty(self, mock_run_command, mock_get_git_root, mock_config):
        """Test worktree listing with no auto worktrees."""
        mock_get_git_root.return_value = Path("/repo")
        
        # Only main worktree
        worktree_output = """worktree /repo
HEAD abcd1234
"""
        
        mock_run_command.return_value = ShellResult(0, worktree_output.strip(), "", "git worktree list --porcelain")
        
        manager = GitWorktreeManager(mock_config)
        worktrees = manager.list_worktrees()
        
        assert len(worktrees) == 0
    
    @patch("auto.integrations.git.get_git_root")
    @patch("auto.integrations.git.run_command")
    def test_list_worktrees_git_failure(self, mock_run_command, mock_get_git_root, mock_config):
        """Test worktree listing with git command failure."""
        mock_get_git_root.return_value = Path("/repo")
        
        mock_run_command.side_effect = ShellError("Git failed", 1, "", "fatal: not a git repository")
        
        manager = GitWorktreeManager(mock_config)
        worktrees = manager.list_worktrees()
        
        assert len(worktrees) == 0  # Should return empty list on failure


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    @patch("auto.integrations.git.GitWorktreeManager")
    def test_create_worktree_function(self, mock_manager_class, mock_config, sample_issue):
        """Test create_worktree convenience function."""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        mock_worktree_info = Mock()
        mock_manager.create_worktree.return_value = mock_worktree_info
        
        result = create_worktree(sample_issue, mock_config)
        
        mock_manager_class.assert_called_once_with(mock_config)
        mock_manager.create_worktree.assert_called_once_with(sample_issue, "main")
        assert result == mock_worktree_info
    
    @patch("auto.integrations.git.GitWorktreeManager")
    def test_cleanup_worktree_function(self, mock_manager_class, mock_config, sample_worktree_info):
        """Test cleanup_worktree convenience function."""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        
        cleanup_worktree(sample_worktree_info, mock_config)
        
        mock_manager_class.assert_called_once_with(mock_config)
        mock_manager.cleanup_worktree.assert_called_once_with(sample_worktree_info)