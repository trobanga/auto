"""Process workflow combining issue fetching, worktree creation, AI implementation, and PR creation."""

import asyncio
from typing import Optional

from auto.config import get_config
from auto.core import get_core
from auto.integrations.git import GitWorktreeManager, GitWorktreeError
from auto.integrations.github import GitHubIntegration, detect_repository
from auto.models import Issue, IssueIdentifier, WorkflowState, WorkflowStatus, AIStatus
from auto.utils.logger import get_logger
from auto.workflows.fetch import fetch_issue_workflow_sync, get_issue_from_state
from auto.workflows.implement import implement_issue_workflow, ImplementationError
from auto.workflows.pr_create import create_pull_request_workflow, PRCreationError

logger = get_logger(__name__)


class ProcessWorkflowError(Exception):
    """Process workflow error."""
    pass


def process_issue_workflow(
    issue_id: str, 
    base_branch: Optional[str] = None,
    enable_ai: bool = True,
    enable_pr: bool = True,
    prompt_override: Optional[str] = None,
    prompt_file: Optional[str] = None,
    prompt_template: Optional[str] = None,
    prompt_append: Optional[str] = None,
    show_prompt: bool = False,
    draft_pr: bool = False
) -> WorkflowState:
    """Enhanced process issue workflow: fetch → worktree → AI implementation → PR creation.
    
    Args:
        issue_id: Issue identifier
        base_branch: Base branch for worktree (auto-detected if None)
        enable_ai: Enable AI implementation step
        enable_pr: Enable PR creation step
        prompt_override: Direct prompt override for AI
        prompt_file: Path to prompt file for AI
        prompt_template: Named prompt template for AI
        prompt_append: Text to append to AI prompt
        show_prompt: Show resolved prompt instead of executing AI
        draft_pr: Create PR as draft
        
    Returns:
        Updated workflow state with complete process information
        
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
        
        # Save updated state after worktree creation
        core.save_workflow_state(state)
        
        logger.info(f"Worktree created: {worktree_info.path}")
        logger.info(f"Branch: {worktree_info.branch}")
        
        # AI Implementation step
        if enable_ai:
            logger.info("Starting AI implementation step")
            try:
                state = asyncio.run(implement_issue_workflow(
                    issue=issue,
                    workflow_state=state,
                    prompt_override=prompt_override,
                    prompt_file=prompt_file,
                    prompt_template=prompt_template,
                    prompt_append=prompt_append,
                    show_prompt=show_prompt
                ))
                
                # Save state after AI implementation
                core.save_workflow_state(state)
                
                if show_prompt:
                    logger.info("Prompt shown, stopping workflow")
                    return state
                
                if state.ai_status == AIStatus.IMPLEMENTED:
                    logger.info("AI implementation completed successfully")
                else:
                    logger.warning(f"AI implementation status: {state.ai_status}")
                    
            except ImplementationError as e:
                logger.error(f"AI implementation failed: {e}")
                state.update_status(WorkflowStatus.FAILED)
                state.metadata['ai_error'] = str(e)
                core.save_workflow_state(state)
                
                if not enable_pr:  # If PR creation is disabled, fail here
                    raise ProcessWorkflowError(f"AI implementation failed: {e}")
                else:
                    logger.warning("AI implementation failed, but continuing to PR creation")
        else:
            logger.info("AI implementation step skipped")
        
        # PR Creation step
        if enable_pr:
            logger.info("Starting PR creation step")
            try:
                state = asyncio.run(create_pull_request_workflow(
                    issue=issue,
                    workflow_state=state,
                    draft=draft_pr
                ))
                
                # Save state after PR creation
                core.save_workflow_state(state)
                
                if state.pr_number:
                    logger.info(f"PR #{state.pr_number} created successfully")
                else:
                    logger.warning("PR creation completed but no PR number available")
                    
            except PRCreationError as e:
                logger.error(f"PR creation failed: {e}")
                state.update_status(WorkflowStatus.FAILED)
                state.metadata['pr_error'] = str(e)
                core.save_workflow_state(state)
                raise ProcessWorkflowError(f"PR creation failed: {e}")
        else:
            logger.info("PR creation step skipped")
        
        logger.info(f"Successfully processed issue {issue.id}")
        if state.pr_number:
            logger.info(f"PR created: #{state.pr_number}")
        
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
            'ai_status': state.ai_status.value,
            'has_ai_response': state.ai_response is not None,
            'pr_number': state.pr_number,
            'has_pr_metadata': state.pr_metadata is not None,
        }
        
        # Add worktree details if available
        if state.worktree_info:
            status.update({
                'worktree_exists': state.worktree_info.exists(),
                'worktree_branch': state.worktree_info.branch,
                'worktree_created_at': state.worktree_info.created_at.isoformat(),
            })
        
        # Add AI details if available
        if state.ai_response:
            status.update({
                'ai_implementation_successful': state.ai_response.success,
                'ai_file_changes_count': len(state.ai_response.file_changes),
                'ai_commands_count': len(state.ai_response.commands),
                'ai_response_type': state.ai_response.response_type,
            })
        
        # Add PR details if available
        if state.pr_metadata:
            status.update({
                'pr_title': state.pr_metadata.title,
                'pr_draft': state.pr_metadata.draft,
                'pr_labels_count': len(state.pr_metadata.labels),
                'pr_reviewers_count': len(state.pr_metadata.reviewers),
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


async def enhanced_process_issue_workflow(
    issue_id: str, 
    base_branch: Optional[str] = None,
    enable_ai: bool = True,
    enable_pr: bool = True,
    prompt_override: Optional[str] = None,
    prompt_file: Optional[str] = None,
    prompt_template: Optional[str] = None,
    prompt_append: Optional[str] = None,
    show_prompt: bool = False,
    draft_pr: bool = False
) -> WorkflowState:
    """
    Async version of enhanced process workflow: fetch → worktree → AI implementation → PR creation.
    
    This is the same as process_issue_workflow but handles async operations directly
    without using asyncio.run(), making it suitable for use within async contexts.
    
    Args:
        issue_id: Issue identifier
        base_branch: Base branch for worktree (auto-detected if None)
        enable_ai: Enable AI implementation step
        enable_pr: Enable PR creation step
        prompt_override: Direct prompt override for AI
        prompt_file: Path to prompt file for AI
        prompt_template: Named prompt template for AI
        prompt_append: Text to append to AI prompt
        show_prompt: Show resolved prompt instead of executing AI
        draft_pr: Create PR as draft
        
    Returns:
        Updated workflow state with complete process information
        
    Raises:
        ProcessWorkflowError: If process workflow fails
    """
    logger.info(f"Starting enhanced async process workflow for issue: {issue_id}")
    
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
        
        # Save updated state after worktree creation
        core.save_workflow_state(state)
        
        logger.info(f"Worktree created: {worktree_info.path}")
        logger.info(f"Branch: {worktree_info.branch}")
        
        # AI Implementation step
        if enable_ai:
            logger.info("Starting AI implementation step")
            try:
                state = await implement_issue_workflow(
                    issue=issue,
                    workflow_state=state,
                    prompt_override=prompt_override,
                    prompt_file=prompt_file,
                    prompt_template=prompt_template,
                    prompt_append=prompt_append,
                    show_prompt=show_prompt
                )
                
                # Save state after AI implementation
                core.save_workflow_state(state)
                
                if show_prompt:
                    logger.info("Prompt shown, stopping workflow")
                    return state
                
                if state.ai_status == AIStatus.IMPLEMENTED:
                    logger.info("AI implementation completed successfully")
                else:
                    logger.warning(f"AI implementation status: {state.ai_status}")
                    
            except ImplementationError as e:
                logger.error(f"AI implementation failed: {e}")
                state.update_status(WorkflowStatus.FAILED)
                state.metadata['ai_error'] = str(e)
                core.save_workflow_state(state)
                
                if not enable_pr:  # If PR creation is disabled, fail here
                    raise ProcessWorkflowError(f"AI implementation failed: {e}")
                else:
                    logger.warning("AI implementation failed, but continuing to PR creation")
        else:
            logger.info("AI implementation step skipped")
        
        # PR Creation step
        if enable_pr:
            logger.info("Starting PR creation step")
            try:
                state = await create_pull_request_workflow(
                    issue=issue,
                    workflow_state=state,
                    draft=draft_pr
                )
                
                # Save state after PR creation
                core.save_workflow_state(state)
                
                if state.pr_number:
                    logger.info(f"PR #{state.pr_number} created successfully")
                else:
                    logger.warning("PR creation completed but no PR number available")
                    
            except PRCreationError as e:
                logger.error(f"PR creation failed: {e}")
                state.update_status(WorkflowStatus.FAILED)
                state.metadata['pr_error'] = str(e)
                core.save_workflow_state(state)
                raise ProcessWorkflowError(f"PR creation failed: {e}")
        else:
            logger.info("PR creation step skipped")
        
        logger.info(f"Successfully processed issue {issue.id}")
        if state.pr_number:
            logger.info(f"PR created: #{state.pr_number}")
        
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