"""Process workflow combining issue fetching with worktree creation."""

from typing import Optional

from auto.config import get_config
from auto.core import get_core
from auto.integrations.git import GitWorktreeManager, GitWorktreeError
from auto.integrations.github import GitHubIntegration, detect_repository
from auto.models import Issue, IssueIdentifier, WorkflowState, WorkflowStatus
from auto.utils.logger import get_logger
from auto.workflows.fetch import fetch_issue_workflow_sync, get_issue_from_state

logger = get_logger(__name__)


class ProcessWorkflowError(Exception):
    """Process workflow error."""
    pass


def process_issue_workflow(issue_id: str, base_branch: Optional[str] = None) -> WorkflowState:
    """Process issue by fetching details and creating worktree.
    
    Args:
        issue_id: Issue identifier
        base_branch: Base branch for worktree (auto-detected if None)
        
    Returns:
        Updated workflow state with worktree information
        
    Raises:
        ProcessWorkflowError: If process workflow fails
    """
    logger.info(f"Starting process workflow for issue: {issue_id}")
    
    try:
        # Parse issue identifier for validation
        identifier = IssueIdentifier.parse(issue_id)
        
        # Get configuration
        config = get_config()
        core = get_core()
        
        # First, ensure we have issue details
        issue = get_issue_from_state(identifier.issue_id)
        
        if issue is None:
            # Need to fetch issue first
            logger.info(f"Issue not found in state, fetching: {identifier.issue_id}")
            state = fetch_issue_workflow_sync(identifier.issue_id)
            issue = state.issue
        else:
            # Get existing state
            state = core.get_workflow_state(identifier.issue_id)
            if state is None:
                raise ProcessWorkflowError(f"Workflow state not found for {identifier.issue_id}")
        
        if issue is None:
            raise ProcessWorkflowError(f"Failed to get issue details for {identifier.issue_id}")
        
        # Update status to implementing
        state.update_status(WorkflowStatus.IMPLEMENTING)
        core.save_workflow_state(state)
        
        # Determine base branch
        if base_branch is None:
            base_branch = _determine_base_branch(state)
        
        logger.info(f"Creating worktree for issue {issue.id} from base branch: {base_branch}")
        
        # Create worktree
        worktree_manager = GitWorktreeManager(config)
        worktree_info = worktree_manager.create_worktree(issue, base_branch)
        
        # Update workflow state with worktree information
        state.worktree = worktree_info.path
        state.worktree_info = worktree_info
        state.branch = worktree_info.branch
        
        # Add repository context if we have it
        if state.repository is None:
            try:
                repository = detect_repository()
                if repository:
                    state.repository = repository
            except Exception as e:
                logger.debug(f"Could not detect repository: {e}")
        
        # Update metadata
        state.metadata.update({
            'base_branch': base_branch,
            'worktree_created': True,
            'worktree_path': worktree_info.path,
            'branch_name': worktree_info.branch,
        })
        
        # Save updated state
        core.save_workflow_state(state)
        
        logger.info(f"Successfully processed issue {issue.id}")
        logger.info(f"Worktree created: {worktree_info.path}")
        logger.info(f"Branch: {worktree_info.branch}")
        
        return state
        
    except GitWorktreeError as e:
        # Update state to failed
        if 'state' in locals():
            state.update_status(WorkflowStatus.FAILED)
            state.metadata['error'] = f"Worktree creation failed: {e}"
            core.save_workflow_state(state)
        
        raise ProcessWorkflowError(f"Worktree creation failed for {issue_id}: {e}")
    
    except Exception as e:
        # Update state to failed
        if 'state' in locals():
            state.update_status(WorkflowStatus.FAILED)
            state.metadata['error'] = str(e)
            core.save_workflow_state(state)
        
        raise ProcessWorkflowError(f"Failed to process issue {issue_id}: {e}")


def _determine_base_branch(state: WorkflowState) -> str:
    """Determine base branch for worktree creation.
    
    Args:
        state: Workflow state
        
    Returns:
        Base branch name
    """
    # Try to get from repository context
    if state.repository and state.repository.default_branch:
        return state.repository.default_branch
    
    # Try to detect from GitHub repository
    try:
        repository = detect_repository()
        if repository:
            return repository.default_branch
    except Exception as e:
        logger.debug(f"Could not detect repository for base branch: {e}")
    
    # Fallback to main
    return "main"


def cleanup_process_workflow(issue_id: str) -> bool:
    """Clean up process workflow artifacts.
    
    Args:
        issue_id: Issue identifier
        
    Returns:
        True if cleanup successful, False otherwise
    """
    logger.info(f"Cleaning up process workflow for issue: {issue_id}")
    
    try:
        # Parse issue identifier
        identifier = IssueIdentifier.parse(issue_id)
        
        # Get workflow state
        core = get_core()
        state = core.get_workflow_state(identifier.issue_id)
        
        if state is None:
            logger.warning(f"No workflow state found for {identifier.issue_id}")
            return True
        
        # Clean up worktree if it exists
        if state.worktree_info:
            try:
                config = get_config()
                worktree_manager = GitWorktreeManager(config)
                worktree_manager.cleanup_worktree(state.worktree_info)
                logger.info(f"Cleaned up worktree: {state.worktree_info.path}")
            except Exception as e:
                logger.error(f"Failed to clean up worktree: {e}")
                return False
        
        # Remove workflow state
        try:
            core.cleanup_completed_states()
            logger.info(f"Cleaned up workflow state for {identifier.issue_id}")
        except Exception as e:
            logger.error(f"Failed to clean up workflow state: {e}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to cleanup process workflow for {issue_id}: {e}")
        return False


def get_process_status(issue_id: str) -> Optional[dict]:
    """Get process workflow status.
    
    Args:
        issue_id: Issue identifier
        
    Returns:
        Status dictionary or None if not found
    """
    try:
        # Parse issue identifier
        identifier = IssueIdentifier.parse(issue_id)
        
        # Get workflow state
        core = get_core()
        state = core.get_workflow_state(identifier.issue_id)
        
        if state is None:
            return None
        
        status = {
            'issue_id': state.issue_id,
            'status': state.status.value,
            'branch': state.branch,
            'worktree_path': state.worktree,
            'has_worktree': state.worktree_info is not None,
            'repository': state.repository.full_name if state.repository else None,
            'issue_title': state.issue.title if state.issue else None,
            'created_at': state.created_at.isoformat() if state.created_at else None,
            'updated_at': state.updated_at.isoformat() if state.updated_at else None,
        }
        
        # Add worktree details if available
        if state.worktree_info:
            status.update({
                'worktree_exists': state.worktree_info.exists(),
                'worktree_branch': state.worktree_info.branch,
                'worktree_created_at': state.worktree_info.created_at.isoformat(),
            })
        
        return status
        
    except Exception as e:
        logger.error(f"Failed to get process status for {issue_id}: {e}")
        return None


def validate_process_prerequisites(issue_id: str) -> list:
    """Validate prerequisites for process workflow.
    
    Args:
        issue_id: Issue identifier
        
    Returns:
        List of validation errors (empty if all good)
    """
    errors = []
    
    try:
        # Parse issue identifier
        identifier = IssueIdentifier.parse(issue_id)
    except ValueError as e:
        errors.append(f"Invalid issue identifier: {e}")
        return errors
    
    # Check if in git repository
    try:
        from auto.utils.shell import get_git_root
        git_root = get_git_root()
        if git_root is None:
            errors.append("Not in a git repository")
    except Exception:
        errors.append("Could not validate git repository")
    
    # Check GitHub authentication (for GitHub issues)
    if identifier.provider.value == "github":
        try:
            from auto.integrations.github import validate_github_auth
            if not validate_github_auth():
                errors.append("GitHub CLI not authenticated. Run 'gh auth login'")
        except Exception:
            errors.append("Could not validate GitHub authentication")
    
    # Check repository access
    try:
        repository = detect_repository()
        if repository is None:
            errors.append("Could not detect GitHub repository from git remote")
    except Exception as e:
        errors.append(f"Repository detection failed: {e}")
    
    # Check configuration
    try:
        config = get_config()
        if not config:
            errors.append("Could not load configuration")
    except Exception as e:
        errors.append(f"Configuration error: {e}")
    
    return errors