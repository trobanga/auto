"""Issue fetching workflow."""

from typing import Optional

from auto.config import get_config
from auto.core import get_core
from auto.integrations.github import GitHubIntegration, GitHubIntegrationError
from auto.models import Issue, IssueIdentifier, IssueProvider, WorkflowState, WorkflowStatus
from auto.utils.logger import get_logger

logger = get_logger(__name__)


class FetchWorkflowError(Exception):
    """Fetch workflow error."""
    pass


async def fetch_issue_workflow(issue_id: str) -> WorkflowState:
    """Fetch issue and create/update workflow state.
    
    Args:
        issue_id: Issue identifier (e.g., "#123", "ENG-456")
        
    Returns:
        Updated workflow state
        
    Raises:
        FetchWorkflowError: If issue fetching fails
    """
    logger.info(f"Starting fetch workflow for issue: {issue_id}")
    
    try:
        # Parse issue identifier
        identifier = IssueIdentifier.parse(issue_id)
        logger.debug(f"Parsed issue identifier: {identifier.provider.value} {identifier.issue_id}")
        
        # Get or create workflow state
        core = get_core()
        state = core.get_workflow_state(identifier.issue_id)
        
        if state is None:
            # Create new workflow state
            state = core.create_workflow_state(identifier.issue_id)
            logger.debug(f"Created new workflow state for {identifier.issue_id}")
        else:
            logger.debug(f"Found existing workflow state for {identifier.issue_id}")
        
        # Update status to fetching
        state.update_status(WorkflowStatus.FETCHING)
        core.save_workflow_state(state)
        
        # Fetch issue based on provider
        if identifier.provider == IssueProvider.GITHUB:
            issue = await _fetch_github_issue(identifier.issue_id)
        elif identifier.provider == IssueProvider.LINEAR:
            raise FetchWorkflowError("Linear integration not yet implemented")
        else:
            raise FetchWorkflowError(f"Unsupported issue provider: {identifier.provider}")
        
        # Update workflow state with issue details
        state.issue = issue
        state.update_status(WorkflowStatus.IMPLEMENTING)  # Ready for next phase
        core.save_workflow_state(state)
        
        logger.info(f"Successfully fetched issue {issue.id}: {issue.title}")
        return state
        
    except Exception as e:
        # Update state to failed if we have one
        if 'state' in locals():
            state.update_status(WorkflowStatus.FAILED)
            state.metadata['error'] = str(e)
            core.save_workflow_state(state)
        
        raise FetchWorkflowError(f"Failed to fetch issue {issue_id}: {e}")


def fetch_issue_workflow_sync(issue_id: str) -> WorkflowState:
    """Synchronous wrapper for fetch_issue_workflow.
    
    Args:
        issue_id: Issue identifier
        
    Returns:
        Updated workflow state
    """
    import asyncio
    
    try:
        return asyncio.run(fetch_issue_workflow(issue_id))
    except Exception as e:
        raise FetchWorkflowError(f"Failed to fetch issue {issue_id}: {e}")


async def _fetch_github_issue(issue_id: str) -> Issue:
    """Fetch GitHub issue.
    
    Args:
        issue_id: GitHub issue ID
        
    Returns:
        Issue object
        
    Raises:
        FetchWorkflowError: If GitHub issue fetching fails
    """
    try:
        github = GitHubIntegration()
        repository = github.detect_repository()
        
        logger.debug(f"Detected repository: {repository.full_name}")
        
        issue = github.fetch_issue(issue_id, repository)
        
        logger.debug(f"Fetched issue details: {issue.title} ({issue.status})")
        return issue
        
    except GitHubIntegrationError as e:
        raise FetchWorkflowError(f"GitHub integration error: {e}")
    except Exception as e:
        raise FetchWorkflowError(f"Unexpected error fetching GitHub issue: {e}")


def validate_issue_access(issue_id: str) -> bool:
    """Validate that we can access the issue.
    
    Args:
        issue_id: Issue identifier
        
    Returns:
        True if issue is accessible, False otherwise
    """
    try:
        # Parse identifier
        identifier = IssueIdentifier.parse(issue_id)
        
        if identifier.provider == IssueProvider.GITHUB:
            # Try to fetch issue (will raise exception if not accessible)
            github = GitHubIntegration()
            repository = github.detect_repository()
            github.fetch_issue(identifier.issue_id, repository)
            return True
        elif identifier.provider == IssueProvider.LINEAR:
            # Linear validation not implemented yet
            return False
        else:
            return False
            
    except Exception as e:
        logger.debug(f"Issue access validation failed for {issue_id}: {e}")
        return False


def get_issue_from_state(issue_id: str) -> Optional[Issue]:
    """Get issue from existing workflow state.
    
    Args:
        issue_id: Issue identifier
        
    Returns:
        Issue object if found in state, None otherwise
    """
    try:
        core = get_core()
        state = core.get_workflow_state(issue_id)
        
        if state and state.issue:
            return state.issue
        
        return None
        
    except Exception as e:
        logger.debug(f"Failed to get issue from state for {issue_id}: {e}")
        return None