"""Tests for workflow implementations."""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from auto.models import (
    Issue, IssueProvider, IssueStatus, IssueType,
    WorkflowState, WorkflowStatus, AIStatus,
    GitHubRepository, WorktreeInfo
)
from auto.workflows.fetch import (
    fetch_issue_workflow_sync,
    validate_issue_access,
    get_issue_from_state,
    FetchWorkflowError,
)
from auto.workflows.process import (
    process_issue_workflow,
    cleanup_process_workflow,
    get_process_status,
    validate_process_prerequisites,
    ProcessWorkflowError,
)


@pytest.fixture
def sample_issue():
    """Create sample issue."""
    return Issue(
        id="#123",
        provider=IssueProvider.GITHUB,
        title="Test issue",
        description="Test description",
        status=IssueStatus.OPEN,
        issue_type=IssueType.FEATURE,
        labels=["feature"],
        assignee="testuser",
        url="https://github.com/owner/repo/issues/123"
    )


@pytest.fixture
def sample_repository():
    """Create sample repository."""
    return GitHubRepository(
        owner="owner",
        name="repo",
        default_branch="main",
        remote_url="https://github.com/owner/repo.git"
    )


@pytest.fixture
def sample_worktree_info():
    """Create sample worktree info."""
    return WorktreeInfo(
        path="/tmp/test-worktrees/auto-feature-123",
        branch="auto/feature/123",
        issue_id="#123",
        metadata={"base_branch": "main"}
    )


class TestFetchWorkflow:
    """Test fetch workflow."""
    
    @patch("auto.workflows.fetch.get_core")
    @patch("auto.workflows.fetch.GitHubIntegration")
    def test_fetch_issue_workflow_success(self, mock_github_class, mock_get_core, sample_issue, sample_repository):
        """Test successful issue fetching workflow."""
        # Mock core
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = None  # No existing state
        
        mock_state = Mock(spec=WorkflowState)
        mock_core.create_workflow_state.return_value = mock_state
        
        # Mock GitHub integration
        mock_github = Mock()
        mock_github_class.return_value = mock_github
        mock_github.detect_repository.return_value = sample_repository
        mock_github.fetch_issue.return_value = sample_issue
        
        # Run workflow
        result = fetch_issue_workflow_sync("#123")
        
        # Verify workflow steps
        mock_core.create_workflow_state.assert_called_once_with("#123")
        mock_state.update_status.assert_called()
        mock_core.save_workflow_state.assert_called()
        mock_github.fetch_issue.assert_called_once_with("#123", sample_repository)
        
        assert result == mock_state
    
    @patch("auto.workflows.fetch.get_core")
    @patch("auto.workflows.fetch.GitHubIntegration")
    def test_fetch_issue_workflow_existing_state(self, mock_github_class, mock_get_core, sample_issue, sample_repository):
        """Test fetch workflow with existing state."""
        # Mock core with existing state
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        mock_state = Mock(spec=WorkflowState)
        mock_core.get_workflow_state.return_value = mock_state
        
        # Mock GitHub integration
        mock_github = Mock()
        mock_github_class.return_value = mock_github
        mock_github.detect_repository.return_value = sample_repository
        mock_github.fetch_issue.return_value = sample_issue
        
        # Run workflow
        result = fetch_issue_workflow_sync("#123")
        
        # Should not create new state
        mock_core.create_workflow_state.assert_not_called()
        assert result == mock_state
    
    @patch("auto.workflows.fetch.GitHubIntegration")
    def test_fetch_issue_workflow_github_error(self, mock_github_class):
        """Test fetch workflow with GitHub error."""
        # Mock GitHub integration that fails
        mock_github = Mock()
        mock_github_class.return_value = mock_github
        mock_github.detect_repository.side_effect = Exception("GitHub error")
        
        with pytest.raises(FetchWorkflowError, match="GitHub error"):
            fetch_issue_workflow_sync("#123")
    
    def test_fetch_issue_workflow_linear_not_implemented(self):
        """Test fetch workflow with Linear issue (not implemented)."""
        with pytest.raises(FetchWorkflowError, match="Linear integration not yet implemented"):
            fetch_issue_workflow_sync("ENG-123")
    
    def test_fetch_issue_workflow_invalid_identifier(self):
        """Test fetch workflow with invalid identifier."""
        with pytest.raises(FetchWorkflowError):
            fetch_issue_workflow_sync("invalid-id")
    
    @patch("auto.workflows.fetch.GitHubIntegration")
    def test_validate_issue_access_success(self, mock_github_class, sample_issue, sample_repository):
        """Test successful issue access validation."""
        mock_github = Mock()
        mock_github_class.return_value = mock_github
        mock_github.detect_repository.return_value = sample_repository
        mock_github.fetch_issue.return_value = sample_issue
        
        result = validate_issue_access("#123")
        assert result is True
    
    @patch("auto.workflows.fetch.GitHubIntegration")
    def test_validate_issue_access_failure(self, mock_github_class):
        """Test issue access validation failure."""
        mock_github = Mock()
        mock_github_class.return_value = mock_github
        mock_github.detect_repository.side_effect = Exception("Access denied")
        
        result = validate_issue_access("#123")
        assert result is False
    
    def test_validate_issue_access_linear(self):
        """Test issue access validation for Linear (not implemented)."""
        result = validate_issue_access("ENG-123")
        assert result is False
    
    @patch("auto.workflows.fetch.get_core")
    def test_get_issue_from_state_success(self, mock_get_core, sample_issue):
        """Test getting issue from existing state."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = sample_issue
        mock_core.get_workflow_state.return_value = mock_state
        
        result = get_issue_from_state("#123")
        assert result == sample_issue
    
    @patch("auto.workflows.fetch.get_core")
    def test_get_issue_from_state_no_state(self, mock_get_core):
        """Test getting issue when no state exists."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = None
        
        result = get_issue_from_state("#123")
        assert result is None
    
    @patch("auto.workflows.fetch.get_core")
    def test_get_issue_from_state_no_issue(self, mock_get_core):
        """Test getting issue when state has no issue."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = None
        mock_core.get_workflow_state.return_value = mock_state
        
        result = get_issue_from_state("#123")
        assert result is None


class TestProcessWorkflow:
    """Test process workflow."""
    
    @patch("auto.workflows.process.get_config")
    @patch("auto.workflows.process.get_core")
    @patch("auto.workflows.process.GitWorktreeManager")
    @patch("auto.workflows.process.get_issue_from_state")
    @patch("auto.workflows.process.detect_repository")
    @patch("auto.workflows.implement.Path")  # Mock Path to avoid filesystem checks
    def test_process_issue_workflow_success(
        self, 
        mock_path,
        mock_detect_repo,
        mock_get_issue, 
        mock_worktree_class, 
        mock_get_core, 
        mock_get_config,
        sample_issue, 
        sample_repository, 
        sample_worktree_info
    ):
        """Test successful process workflow."""
        # Mock Path.exists() to return True for worktree path
        mock_path_instance = Mock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance
        
        # Mock dependencies
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = sample_issue
        mock_state.repository = None
        mock_state.metadata = {}
        mock_state.pr_number = None
        mock_state.worktree = None
        mock_state.worktree_info = None
        mock_state.branch = None
        mock_core.get_workflow_state.return_value = mock_state
        
        # Mock issue already in state
        mock_get_issue.return_value = sample_issue
        
        # Mock repository detection
        mock_detect_repo.return_value = sample_repository
        
        # Mock worktree manager
        mock_worktree_manager = Mock()
        mock_worktree_class.return_value = mock_worktree_manager
        mock_worktree_manager.create_worktree.return_value = sample_worktree_info
        
        # Mock the AI implementation to avoid filesystem operations
        with patch("auto.workflows.process.implement_issue_workflow") as mock_implement:
            # Return the same state after successful implementation
            mock_state_after_ai = Mock(spec=WorkflowState)
            mock_state_after_ai.ai_status = "implemented"
            mock_state_after_ai.issue = sample_issue
            mock_state_after_ai.repository = sample_repository
            mock_state_after_ai.metadata = {}
            mock_implement.return_value = mock_state_after_ai
            
            # Run workflow with AI disabled to test just the worktree part
            result = process_issue_workflow("#123", enable_ai=False, enable_pr=False)
            
            # Verify workflow steps
            mock_worktree_manager.create_worktree.assert_called_once_with(sample_issue, "main")
            mock_state.update_status.assert_called()
            mock_core.save_workflow_state.assert_called()
            
            assert result == mock_state
            assert mock_state.worktree == sample_worktree_info.path
            assert mock_state.worktree_info == sample_worktree_info
            assert mock_state.branch == sample_worktree_info.branch
    
    @patch("auto.workflows.process.get_config")
    @patch("auto.workflows.process.get_core")
    @patch("auto.workflows.process.fetch_issue_workflow_sync")
    @patch("auto.workflows.process.get_issue_from_state")
    @patch("auto.workflows.implement.Path")  # Mock Path to avoid filesystem checks
    def test_process_issue_workflow_fetch_required(
        self, 
        mock_path,
        mock_get_issue, 
        mock_fetch_workflow, 
        mock_get_core, 
        mock_get_config,
        sample_issue
    ):
        """Test process workflow when issue fetch is required."""
        # Mock Path.exists() to return True for worktree path
        mock_path_instance = Mock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance
        
        # Mock dependencies
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        # No issue in state initially
        mock_get_issue.return_value = None
        
        # Mock fetch workflow
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = sample_issue
        mock_state.repository = None
        mock_state.metadata = {}
        mock_state.pr_number = None
        mock_state.worktree = None
        mock_state.worktree_info = None
        mock_state.branch = None
        mock_fetch_workflow.return_value = mock_state
        
        # Mock worktree creation (simplified)
        with patch("auto.workflows.process.GitWorktreeManager") as mock_worktree_class:
            mock_worktree_manager = Mock()
            mock_worktree_class.return_value = mock_worktree_manager
            mock_worktree_info = Mock()
            mock_worktree_info.path = "/tmp/test-worktrees/auto-feature-123"
            mock_worktree_info.branch = "auto/feature/123"
            mock_worktree_manager.create_worktree.return_value = mock_worktree_info
            
            # Mock the AI implementation to avoid filesystem operations
            with patch("auto.workflows.process.implement_issue_workflow") as mock_implement:
                mock_implement.return_value = mock_state
                
                # Run workflow with AI disabled to test just the fetch and worktree parts
                result = process_issue_workflow("#123", enable_ai=False, enable_pr=False)
                
                # Verify fetch was called
                mock_fetch_workflow.assert_called_once_with("#123")
                assert result == mock_state
    
    @patch("auto.workflows.process.get_config")
    @patch("auto.workflows.process.get_core")
    @patch("auto.workflows.process.GitWorktreeManager")
    @patch("auto.workflows.process.get_issue_from_state")
    def test_process_issue_workflow_worktree_error(
        self, 
        mock_get_issue, 
        mock_worktree_class, 
        mock_get_core, 
        mock_get_config,
        sample_issue
    ):
        """Test process workflow with worktree creation error."""
        # Mock dependencies
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue = sample_issue
        mock_state.metadata = {}
        mock_core.get_workflow_state.return_value = mock_state
        
        mock_get_issue.return_value = sample_issue
        
        # Mock worktree manager that fails
        mock_worktree_manager = Mock()
        mock_worktree_class.return_value = mock_worktree_manager
        mock_worktree_manager.create_worktree.side_effect = Exception("Worktree creation failed")
        
        with pytest.raises(ProcessWorkflowError, match="Failed to process issue"):
            process_issue_workflow("#123")
        
        # Should update state to failed
        mock_state.update_status.assert_called_with(WorkflowStatus.FAILED)
    
    @patch("auto.workflows.process.get_config")
    @patch("auto.workflows.process.get_core")
    @patch("auto.workflows.process.GitWorktreeManager")
    def test_cleanup_process_workflow_success(
        self, 
        mock_worktree_class, 
        mock_get_core, 
        mock_get_config,
        sample_worktree_info
    ):
        """Test successful process workflow cleanup."""
        # Mock dependencies
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.worktree_info = sample_worktree_info
        mock_core.get_workflow_state.return_value = mock_state
        
        # Mock worktree manager
        mock_worktree_manager = Mock()
        mock_worktree_class.return_value = mock_worktree_manager
        
        # Run cleanup
        result = cleanup_process_workflow("#123")
        
        # Verify cleanup steps
        mock_worktree_manager.cleanup_worktree.assert_called_once_with(sample_worktree_info)
        mock_core.cleanup_completed_states.assert_called_once()
        
        assert result is True
    
    @patch("auto.workflows.process.get_core")
    def test_cleanup_process_workflow_no_state(self, mock_get_core):
        """Test cleanup when no workflow state exists."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = None
        
        result = cleanup_process_workflow("#123")
        assert result is True
    
    @patch("auto.workflows.process.get_config")
    @patch("auto.workflows.process.get_core")
    @patch("auto.workflows.process.GitWorktreeManager")
    def test_cleanup_process_workflow_worktree_error(
        self, 
        mock_worktree_class, 
        mock_get_core, 
        mock_get_config,
        sample_worktree_info
    ):
        """Test cleanup with worktree cleanup error."""
        # Mock dependencies
        mock_config = Mock()
        mock_get_config.return_value = mock_config
        
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.worktree_info = sample_worktree_info
        mock_core.get_workflow_state.return_value = mock_state
        
        # Mock worktree manager that fails
        mock_worktree_manager = Mock()
        mock_worktree_class.return_value = mock_worktree_manager
        mock_worktree_manager.cleanup_worktree.side_effect = Exception("Cleanup failed")
        
        result = cleanup_process_workflow("#123")
        assert result is False
    
    @patch("auto.workflows.process.get_core")
    def test_get_process_status_success(self, mock_get_core, sample_issue, sample_repository, sample_worktree_info):
        """Test getting process status."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        
        mock_state = Mock(spec=WorkflowState)
        mock_state.issue_id = "#123"
        mock_state.status = WorkflowStatus.IMPLEMENTING
        mock_state.branch = "auto/feature/123"
        mock_state.worktree = "/tmp/test-worktrees/auto-feature-123"
        mock_state.worktree_info = sample_worktree_info
        mock_state.repository = sample_repository
        mock_state.issue = sample_issue
        mock_state.created_at = datetime.now()
        mock_state.updated_at = datetime.now()
        # Add missing attributes for WorkflowState
        mock_state.ai_status = AIStatus.IMPLEMENTED
        mock_state.ai_response = None
        mock_state.pr_number = None
        mock_state.pr_metadata = None
        mock_core.get_workflow_state.return_value = mock_state
        
        # Mock the WorktreeInfo.exists() method using the Path class
        with patch("auto.models.Path") as mock_path_class:
            mock_path_instance = Mock()
            mock_path_instance.exists.return_value = True
            mock_path_class.return_value = mock_path_instance
            
            result = get_process_status("#123")
            
            assert result is not None
            assert result['issue_id'] == "#123"
            assert result['status'] == "implementing"
            assert result['branch'] == "auto/feature/123"
            assert result['has_worktree'] is True
            assert result['worktree_exists'] is True
            assert result['repository'] == "owner/repo"
            assert result['issue_title'] == "Test issue"
    
    @patch("auto.workflows.process.get_core")
    def test_get_process_status_no_state(self, mock_get_core):
        """Test getting process status when no state exists."""
        mock_core = Mock()
        mock_get_core.return_value = mock_core
        mock_core.get_workflow_state.return_value = None
        
        result = get_process_status("#123")
        assert result is None
    
    @patch("auto.utils.shell.get_git_root")
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.workflows.process.detect_repository")
    @patch("auto.workflows.process.get_config")
    def test_validate_process_prerequisites_success(
        self, 
        mock_get_config, 
        mock_detect_repo, 
        mock_validate_auth, 
        mock_get_git_root,
        sample_repository
    ):
        """Test successful prerequisite validation."""
        mock_get_git_root.return_value = Path("/repo")
        mock_validate_auth.return_value = True
        mock_detect_repo.return_value = sample_repository
        mock_get_config.return_value = Mock()
        
        errors = validate_process_prerequisites("#123")
        assert len(errors) == 0
    
    @patch("auto.utils.shell.get_git_root")
    def test_validate_process_prerequisites_no_git_repo(self, mock_get_git_root):
        """Test prerequisite validation without git repository."""
        mock_get_git_root.return_value = None
        
        errors = validate_process_prerequisites("#123")
        assert "Not in a git repository" in errors
    
    @patch("auto.utils.shell.get_git_root")
    @patch("auto.integrations.github.validate_github_auth")
    def test_validate_process_prerequisites_no_github_auth(self, mock_validate_auth, mock_get_git_root):
        """Test prerequisite validation without GitHub authentication."""
        mock_get_git_root.return_value = Path("/repo")
        mock_validate_auth.return_value = False
        
        errors = validate_process_prerequisites("#123")
        assert any("GitHub CLI not authenticated" in error for error in errors)
    
    @patch("auto.utils.shell.get_git_root")
    @patch("auto.integrations.github.validate_github_auth")
    @patch("auto.workflows.process.detect_repository")
    def test_validate_process_prerequisites_no_repo_access(
        self, 
        mock_detect_repo, 
        mock_validate_auth, 
        mock_get_git_root
    ):
        """Test prerequisite validation without repository access."""
        mock_get_git_root.return_value = Path("/repo")
        mock_validate_auth.return_value = True
        mock_detect_repo.return_value = None
        
        errors = validate_process_prerequisites("#123")
        assert any("Could not detect GitHub repository" in error for error in errors)
    
    def test_validate_process_prerequisites_invalid_issue_id(self):
        """Test prerequisite validation with invalid issue ID."""
        errors = validate_process_prerequisites("invalid-id")
        assert any("Invalid issue identifier" in error for error in errors)