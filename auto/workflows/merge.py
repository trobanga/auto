"""Automated merge workflow after approval validation.

This module provides the main interface for automated merge operations,
coordinating validation, conflict detection, merge execution, and cleanup.
"""

from pathlib import Path

from auto.utils.logger import get_logger
from auto.workflows.merge_cleanup import cleanup_after_merge
from auto.workflows.merge_conflicts import MergeConflictError, handle_merge_conflicts
from auto.workflows.merge_execution import execute_merge
from auto.workflows.merge_validation import (
    MergeValidationError,
    validate_merge_eligibility,
)

logger = get_logger(__name__)


async def execute_auto_merge(
    pr_number: int, owner: str, repo: str, worktree_path: Path | None = None, force: bool = False
) -> bool:
    """Execute automated PR merge after approval with validation.

    Args:
        pr_number: Pull request number to merge
        owner: Repository owner
        repo: Repository name
        worktree_path: Optional path to worktree for cleanup
        force: Force merge even if some checks fail

    Returns:
        True if merge was successful, False otherwise

    Raises:
        MergeValidationError: If merge validation fails
        MergeExecutionError: If merge execution fails
    """
    logger.info(f"Starting automated merge for PR #{pr_number}")

    try:
        # Validate merge eligibility
        is_eligible, validation_errors = await validate_merge_eligibility(
            pr_number, owner, repo, force
        )

        if not is_eligible:
            logger.error(f"PR #{pr_number} is not eligible for merge: {validation_errors}")
            raise MergeValidationError(f"Merge validation failed: {', '.join(validation_errors)}")

        logger.info(f"PR #{pr_number} passed merge validation")

        # Check for merge conflicts
        conflicts = await handle_merge_conflicts(pr_number, owner, repo)
        if conflicts and not force:
            logger.error(f"Merge conflicts detected for PR #{pr_number}")
            raise MergeConflictError(f"Merge conflicts detected: {conflicts}") from None

        # Execute the merge
        success = await execute_merge(pr_number, owner, repo)
        if not success:
            logger.error(f"Failed to merge PR #{pr_number}")
            return False

        logger.info(f"Successfully merged PR #{pr_number}")

        # Post-merge cleanup
        if worktree_path:
            await cleanup_after_merge(worktree_path, owner, repo)

        return True

    except Exception as e:
        logger.error(f"Error during automated merge: {e}")
        raise


async def _update_issue_status_after_merge(owner: str, repo: str) -> None:
    """Update issue status after successful merge."""
    # This is a placeholder function for testing
    pass


async def _cleanup_temporary_files(worktree_path: Path) -> None:
    """Clean up temporary files after merge."""
    # This is a placeholder function for testing
    pass
