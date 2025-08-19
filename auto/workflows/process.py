"""Process workflow combining issue fetching, worktree creation, AI implementation, and PR creation."""

import asyncio

from auto.config import get_config
from auto.core import get_core
from auto.integrations.git import GitWorktreeError, GitWorktreeManager
from auto.integrations.github import detect_repository
from auto.models import AIStatus, IssueIdentifier, WorkflowState, WorkflowStatus
from auto.utils.logger import get_logger
from auto.workflows.fetch import fetch_issue_workflow_sync, get_issue_from_state
from auto.workflows.implement import ImplementationError, implement_issue_workflow
from auto.workflows.pr_create import PRCreationError, create_pull_request_workflow

logger = get_logger(__name__)


class ProcessWorkflowError(Exception):
    """Process workflow error."""

    pass


def determine_resume_point(state: WorkflowState) -> tuple[str, str]:
    """Determine where to resume workflow based on current state.

    Args:
        state: Current workflow state

    Returns:
        Tuple of (resume_point, reason) where resume_point is one of:
        - "fetch": Start from issue fetching
        - "worktree": Start from worktree creation
        - "ai": Start from AI implementation
        - "pr": Start from PR creation
        - "completed": Workflow already completed
        - "failed": Workflow failed, needs manual intervention
    """
    # Check if workflow is already completed
    if state.status == WorkflowStatus.COMPLETED:
        return "completed", "Workflow already completed successfully"

    # Check if workflow failed
    if state.status == WorkflowStatus.FAILED:
        # Check metadata to see what failed
        if "ai_error" in state.metadata:
            return "ai", "AI implementation failed, resuming from AI step"
        elif "pr_error" in state.metadata:
            return "pr", "PR creation failed, resuming from PR step"
        else:
            return "worktree", "Workflow failed, resuming from worktree creation"

    # Check if PR was created
    if state.pr_number is not None:
        return "completed", "PR already created, workflow complete"

    # Check if AI implementation was completed
    if state.ai_status == AIStatus.IMPLEMENTED and state.ai_response:
        return "pr", "AI implementation completed, resuming from PR creation"

    # Check if worktree exists
    if state.worktree_info and state.worktree_info.exists():
        return "ai", "Worktree exists, resuming from AI implementation"

    # Check if issue was fetched
    if state.issue is not None:
        return "worktree", "Issue fetched, resuming from worktree creation"

    # Default to start from beginning
    return "fetch", "No progress detected, starting from issue fetch"


def process_issue_workflow(
    issue_id: str,
    base_branch: str | None = None,
    enable_ai: bool = True,
    enable_pr: bool = True,
    prompt_override: str | None = None,
    prompt_file: str | None = None,
    prompt_template: str | None = None,
    prompt_append: str | None = None,
    show_prompt: bool = False,
    draft_pr: bool = False,
    resume: bool = False,
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
        resume: Resume interrupted workflow from saved state

    Returns:
        Updated workflow state with complete process information

    Raises:
        ProcessWorkflowError: If process workflow fails
    """
    logger.info(f"Starting process workflow for issue: {issue_id} (resume={resume})")

    try:
        # Parse issue identifier for validation
        identifier = IssueIdentifier.parse(issue_id)

        # Get configuration
        config = get_config()
        core = get_core()

        # Initialize resume point
        resume_point = "fetch"

        # Handle resume logic
        if resume:
            # Get existing state for resume
            state = core.get_workflow_state(identifier.issue_id)
            if state is None:
                raise ProcessWorkflowError(
                    f"No existing workflow state found for resume: {identifier.issue_id}"
                )

            # Determine where to resume from
            resume_point, resume_reason = determine_resume_point(state)
            logger.info(f"Resume analysis: {resume_reason}")

            # Handle special resume cases
            if resume_point == "completed":
                logger.info("Workflow already completed, nothing to resume")
                return state
            elif resume_point == "failed":
                logger.warning(
                    "Workflow failed previously, attempting to continue from last known point"
                )

            # Get issue from state (should exist for resume)
            issue = state.issue
            if issue is None:
                logger.warning("Issue not found in state during resume, fetching...")
                state = fetch_issue_workflow_sync(identifier.issue_id)
                issue = state.issue
        else:
            # Normal workflow start - ensure we have issue details
            issue = get_issue_from_state(identifier.issue_id)

            if issue is None:
                # Need to fetch issue first
                logger.info(f"Issue not found in state, fetching: {identifier.issue_id}")
                state = fetch_issue_workflow_sync(identifier.issue_id)
                issue = state.issue
                resume_point = "worktree"  # Continue from worktree creation
            else:
                # Get existing state
                state = core.get_workflow_state(identifier.issue_id)
                if state is None:
                    raise ProcessWorkflowError(
                        f"Workflow state not found for {identifier.issue_id}"
                    )
                resume_point = "worktree"  # Continue from worktree creation

        if issue is None:
            raise ProcessWorkflowError(
                f"Failed to get issue details for {identifier.issue_id}"
            ) from None

        # Only update status if not resuming from completed/failed states
        if not resume or (resume and resume_point not in ["completed"]):
            state.update_status(WorkflowStatus.IMPLEMENTING)
            core.save_workflow_state(state)

        # Worktree creation step (skip if resuming from AI or PR)
        if not resume or resume_point in ["fetch", "worktree"]:
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

            # Update metadata
            state.metadata.update(
                {
                    "base_branch": base_branch,
                    "worktree_created": True,
                    "worktree_path": worktree_info.path,
                    "branch_name": worktree_info.branch,
                }
            )

            logger.info(f"Worktree created: {worktree_info.path}")
            logger.info(f"Branch: {worktree_info.branch}")
        else:
            logger.info(f"Skipping worktree creation (resuming from {resume_point})")
            # Validate existing worktree still exists
            if state.worktree_info and not state.worktree_info.exists():
                logger.warning("Existing worktree no longer exists, recreating...")
                # Fall back to creating worktree
                if base_branch is None:
                    base_branch = _determine_base_branch(state)

                worktree_manager = GitWorktreeManager(config)
                worktree_info = worktree_manager.create_worktree(issue, base_branch)

                # Update workflow state with new worktree information
                state.worktree = worktree_info.path
                state.worktree_info = worktree_info
                state.branch = worktree_info.branch

                logger.info(f"Worktree recreated: {worktree_info.path}")

        # Add repository context if we have it
        if state.repository is None:
            try:
                repository = detect_repository()
                if repository:
                    state.repository = repository
            except Exception as e:
                logger.debug(f"Could not detect repository: {e}")

        # Save updated state after worktree handling
        core.save_workflow_state(state)

        # AI Implementation step (skip if resuming from PR or already implemented)
        if enable_ai and (not resume or resume_point in ["fetch", "worktree", "ai"]):
            # Check if AI is already implemented
            if resume and state.ai_status == AIStatus.IMPLEMENTED and state.ai_response:
                logger.info("AI implementation already completed, skipping")
            else:
                logger.info("Starting AI implementation step")
                try:
                    state = asyncio.run(
                        implement_issue_workflow(
                            issue=issue,
                            workflow_state=state,
                            prompt_override=prompt_override,
                            prompt_file=prompt_file,
                            prompt_template=prompt_template,
                            prompt_append=prompt_append,
                            show_prompt=show_prompt,
                        )
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
                    # Don't log here - error already logged at lower levels
                    state.update_status(WorkflowStatus.FAILED)
                    state.metadata["ai_error"] = str(e)
                    core.save_workflow_state(state)

                    # Always fail when AI implementation fails - don't continue to PR creation
                    raise ProcessWorkflowError(f"AI implementation failed: {e}") from e
        else:
            logger.info("AI implementation step skipped")

        # PR Creation step (skip if already created)
        if enable_pr and (not resume or resume_point in ["fetch", "worktree", "ai", "pr"]):
            # Check if PR is already created
            if resume and state.pr_number is not None:
                logger.info(f"PR #{state.pr_number} already created, skipping")
            else:
                logger.info("Starting PR creation step")
                try:
                    state = asyncio.run(
                        create_pull_request_workflow(
                            issue=issue, workflow_state=state, draft=draft_pr
                        )
                    )

                    # Save state after PR creation
                    core.save_workflow_state(state)

                    if state.pr_number:
                        logger.info(f"PR #{state.pr_number} created successfully")
                    else:
                        logger.warning("PR creation completed but no PR number available")

                except PRCreationError as e:
                    state.update_status(WorkflowStatus.FAILED)
                    state.metadata["pr_error"] = str(e)
                    core.save_workflow_state(state)
                    raise ProcessWorkflowError(f"PR creation failed: {e}") from e
        else:
            logger.info("PR creation step skipped")

        # Review Cycle Initiation (after successful PR creation)
        if state.pr_number and config.workflows.ai_review_first:
            logger.info("Initiating review cycle for created PR")
            try:
                from auto.workflows.review import initiate_review_cycle

                # Update workflow status to in_review
                state.update_status(WorkflowStatus.IN_REVIEW)
                core.save_workflow_state(state)

                # Start the review cycle asynchronously
                repository_name = (
                    f"{state.repository.owner}/{state.repository.name}" if state.repository else ""
                )
                asyncio.run(
                    initiate_review_cycle(
                        pr_number=state.pr_number,
                        repository=repository_name,
                    )
                )

                logger.info(f"Review cycle initiated for PR #{state.pr_number}")

            except Exception as e:
                logger.warning(f"Failed to initiate review cycle: {e}")
                # Don't fail the whole workflow if review cycle initiation fails
                # Just log the warning and continue

        logger.info(f"Successfully processed issue {issue.id}")
        if state.pr_number:
            logger.info(f"PR created: #{state.pr_number}")
            if config.workflows.ai_review_first:
                logger.info("Review cycle has been initiated")

        return state

    except GitWorktreeError as e:
        # Update state to failed
        if "state" in locals() and state is not None:
            state.update_status(WorkflowStatus.FAILED)
            state.metadata["error"] = f"Worktree creation failed: {e}"
            core.save_workflow_state(state)

        raise ProcessWorkflowError(f"Worktree creation failed for {issue_id}: {e}") from e

    except Exception as e:
        # Update state to failed
        if "state" in locals() and state is not None:
            state.update_status(WorkflowStatus.FAILED)
            state.metadata["error"] = str(e)
            core.save_workflow_state(state)

        raise ProcessWorkflowError(f"Failed to process issue {issue_id}: {e}") from e


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


def get_process_status(issue_id: str) -> dict | None:
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
            "issue_id": state.issue_id,
            "status": state.status.value,
            "branch": state.branch,
            "worktree_path": state.worktree,
            "has_worktree": state.worktree_info is not None,
            "repository": state.repository.full_name if state.repository else None,
            "issue_title": state.issue.title if state.issue else None,
            "created_at": state.created_at.isoformat() if state.created_at else None,
            "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            "ai_status": state.ai_status.value,
            "has_ai_response": state.ai_response is not None,
            "pr_number": state.pr_number,
            "has_pr_metadata": state.pr_metadata is not None,
        }

        # Add worktree details if available
        if state.worktree_info:
            status.update(
                {
                    "worktree_exists": state.worktree_info.exists(),
                    "worktree_branch": state.worktree_info.branch,
                    "worktree_created_at": state.worktree_info.created_at.isoformat(),
                }
            )

        # Add AI details if available
        if state.ai_response:
            status.update(
                {
                    "ai_implementation_successful": state.ai_response.success,
                    "ai_file_changes_count": len(state.ai_response.file_changes),
                    "ai_commands_count": len(state.ai_response.commands),
                    "ai_response_type": state.ai_response.response_type,
                }
            )

        # Add PR details if available
        if state.pr_metadata:
            status.update(
                {
                    "pr_title": state.pr_metadata.title,
                    "pr_draft": state.pr_metadata.draft,
                    "pr_labels_count": len(state.pr_metadata.labels),
                    "pr_reviewers_count": len(state.pr_metadata.reviewers),
                }
            )

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
    from auto.utils.shell import get_git_root

    if get_git_root() is None:
        errors.append("Not in a git repository")
        return errors

    # Check GitHub authentication for GitHub issues
    if identifier.provider.value == "github":
        try:
            from auto.integrations.github import validate_github_auth

            if not validate_github_auth():
                errors.append("GitHub CLI not authenticated or not authorized")
        except Exception:
            errors.append("GitHub CLI not available")

    # Check repository access
    if identifier.provider.value == "github":
        try:
            repository = detect_repository()
            if repository is None:
                errors.append("Could not detect GitHub repository")
        except Exception as e:
            errors.append(f"Repository access error: {e}")

    return errors


async def enhanced_process_issue_workflow(
    issue_id: str,
    base_branch: str | None = None,
    enable_ai: bool = True,
    enable_pr: bool = True,
    prompt_override: str | None = None,
    prompt_file: str | None = None,
    prompt_template: str | None = None,
    prompt_append: str | None = None,
    show_prompt: bool = False,
    draft_pr: bool = False,
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

        state: WorkflowState
        if issue is None:
            # Need to fetch issue first
            logger.info(f"Issue not found in state, fetching: {identifier.issue_id}")
            state = fetch_issue_workflow_sync(identifier.issue_id)
            issue = state.issue
        else:
            # Get existing state
            existing_state = core.get_workflow_state(identifier.issue_id)
            if existing_state is None:
                raise ProcessWorkflowError(
                    f"Workflow state not found for {identifier.issue_id}"
                ) from None
            state = existing_state

        if issue is None:
            raise ProcessWorkflowError(
                f"Failed to get issue details for {identifier.issue_id}"
            ) from None

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
        state.metadata.update(
            {
                "base_branch": base_branch,
                "worktree_created": True,
                "worktree_path": worktree_info.path,
                "branch_name": worktree_info.branch,
            }
        )

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
                    show_prompt=show_prompt,
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
                # Don't log here - error already logged at lower levels
                state.update_status(WorkflowStatus.FAILED)
                state.metadata["ai_error"] = str(e)
                core.save_workflow_state(state)

                # Always fail when AI implementation fails - don't continue to PR creation
                raise ProcessWorkflowError(f"AI implementation failed: {e}") from e
        else:
            logger.info("AI implementation step skipped")

        # PR Creation step
        if enable_pr:
            logger.info("Starting PR creation step")
            try:
                state = await create_pull_request_workflow(
                    issue=issue, workflow_state=state, draft=draft_pr
                )

                # Save state after PR creation
                core.save_workflow_state(state)

                if state.pr_number:
                    logger.info(f"PR #{state.pr_number} created successfully")
                else:
                    logger.warning("PR creation completed but no PR number available")

            except PRCreationError as e:
                state.update_status(WorkflowStatus.FAILED)
                state.metadata["pr_error"] = str(e)
                core.save_workflow_state(state)
                raise ProcessWorkflowError(f"PR creation failed: {e}") from e
        else:
            logger.info("PR creation step skipped")

        logger.info(f"Successfully processed issue {issue.id}")
        if state.pr_number:
            logger.info(f"PR created: #{state.pr_number}")

        return state

    except GitWorktreeError as e:
        # Update state to failed
        if "state" in locals() and state is not None:
            state.update_status(WorkflowStatus.FAILED)
            state.metadata["error"] = f"Worktree creation failed: {e}"
            core.save_workflow_state(state)

        raise ProcessWorkflowError(f"Worktree creation failed for {issue_id}: {e}") from e

    except Exception as e:
        # Update state to failed
        if "state" in locals() and state is not None:
            state.update_status(WorkflowStatus.FAILED)
            state.metadata["error"] = str(e)
            core.save_workflow_state(state)

        raise ProcessWorkflowError(f"Failed to process issue {issue_id}: {e}") from e
