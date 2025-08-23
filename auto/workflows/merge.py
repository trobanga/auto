"""Automated merge workflow after approval validation.

This module implements the automated merge process for pull requests after they
have been approved through the review cycle. It includes validation, conflict
detection, merge execution, and post-merge cleanup.
"""

from pathlib import Path
from typing import Any

from auto.config import get_config
from auto.integrations.git import GitIntegration
from auto.integrations.github import GitHubIntegration
from auto.utils.logger import get_logger
from auto.utils.shell import ShellError, run_command

logger = get_logger(__name__)


class MergeValidationError(Exception):
    """Raised when merge validation fails."""

    pass


class MergeConflictError(Exception):
    """Raised when merge conflicts are detected."""

    pass


class MergeExecutionError(Exception):
    """Raised when merge execution fails."""

    pass


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
        # Initialize integrations
        GitHubIntegration()
        config = get_config()

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
        merge_method = (
            config.defaults.merge_method if hasattr(config.defaults, "merge_method") else "merge"
        )
        success = await _execute_merge(pr_number, owner, repo, merge_method)

        if not success:
            raise MergeExecutionError(f"Failed to merge PR #{pr_number}") from None

        logger.info(f"Successfully merged PR #{pr_number}")

        # Post-merge cleanup
        if worktree_path:
            await cleanup_after_merge(worktree_path, owner, repo)

        return True

    except Exception as e:
        logger.error(f"Error during automated merge: {e}")
        raise


async def validate_merge_eligibility(
    pr_number: int, owner: str, repo: str, force: bool = False
) -> tuple[bool, list[str]]:
    """Check merge requirements and branch protection compliance.

    Args:
        pr_number: Pull request number
        owner: Repository owner
        repo: Repository name
        force: Skip some validation checks

    Returns:
        Tuple of (is_eligible, list_of_validation_errors)
    """
    logger.debug(f"Validating merge eligibility for PR #{pr_number}")

    errors = []

    try:
        # Get PR status and reviews
        pr_info = await _get_pr_info(pr_number, owner, repo)

        # Check if PR is in mergeable state
        if pr_info.get("state") != "open":
            errors.append(f"PR is not open (current state: {pr_info.get('state')})")

        if pr_info.get("draft"):
            errors.append("PR is in draft state")

        # Check if PR is mergeable
        mergeable = pr_info.get("mergeable")
        if mergeable is False:
            errors.append("PR has conflicts that must be resolved")
        elif mergeable is None and not force:
            errors.append("PR mergeable status is unknown (try again in a moment)")

        # Check for required reviews
        if not force:
            reviews_valid, review_errors = await _validate_reviews(pr_number, owner, repo)
            if not reviews_valid:
                errors.extend(review_errors)

        # Check for required status checks
        if not force:
            checks_valid, check_errors = await _validate_status_checks(pr_number, owner, repo)
            if not checks_valid:
                errors.extend(check_errors)

        # Check branch protection rules
        protection_valid, protection_errors = await _validate_branch_protection(
            pr_info.get("base", {}).get("ref", "main"), owner, repo
        )
        if not protection_valid and not force:
            errors.extend(protection_errors)

        is_eligible = len(errors) == 0

        if is_eligible:
            logger.info(f"PR #{pr_number} is eligible for merge")
        else:
            logger.warning(f"PR #{pr_number} failed validation: {errors}")

        return is_eligible, errors

    except Exception as e:
        logger.error(f"Error validating merge eligibility: {e}")
        return False, [f"Validation error: {str(e)}"]


async def cleanup_after_merge(
    worktree_path: Path, owner: str, repo: str, update_issue_status: bool = True
) -> None:
    """Clean up worktrees and update issue status after successful merge.

    Args:
        worktree_path: Path to worktree to clean up
        owner: Repository owner
        repo: Repository name
        update_issue_status: Whether to update associated issue status
    """
    logger.info(f"Starting post-merge cleanup for worktree: {worktree_path}")

    try:
        # Remove worktree
        if worktree_path.exists():
            git = GitIntegration()
            # Create WorktreeInfo from path
            from auto.models import WorktreeInfo

            # Extract branch from worktree path (last component is usually the branch)
            branch_from_path = worktree_path.name
            worktree_info = WorktreeInfo(
                path=str(worktree_path),
                branch=branch_from_path,
                issue_id="",  # Not needed for removal
            )
            git.remove_worktree(worktree_info)
            logger.info(f"Removed worktree: {worktree_path}")

        # Update issue status if configured
        if update_issue_status:
            await _update_issue_status_after_merge(owner, repo)

        # Clean up any temporary files or state
        await _cleanup_temporary_files(worktree_path)

        logger.info("Post-merge cleanup completed successfully")

    except Exception as e:
        logger.error(f"Error during post-merge cleanup: {e}")
        # Don't re-raise as cleanup failure shouldn't fail the merge


async def handle_merge_conflicts(pr_number: int, owner: str, repo: str) -> list[str] | None:
    """Detect and provide guidance for merge conflicts.

    Args:
        pr_number: Pull request number
        owner: Repository owner
        repo: Repository name

    Returns:
        List of conflict descriptions if conflicts exist, None otherwise
    """
    logger.debug(f"Checking for merge conflicts in PR #{pr_number}")

    try:
        # Get PR mergeable status
        pr_info = await _get_pr_info(pr_number, owner, repo)
        mergeable = pr_info.get("mergeable")

        if mergeable is False:
            # Get detailed conflict information
            conflicts = await _get_conflict_details(pr_number, owner, repo)
            logger.warning(f"Merge conflicts detected in PR #{pr_number}: {conflicts}")
            return conflicts

        logger.debug(f"No merge conflicts detected for PR #{pr_number}")
        return None

    except Exception as e:
        logger.error(f"Error checking for merge conflicts: {e}")
        return [f"Error checking conflicts: {str(e)}"]


# Private helper functions


async def _execute_merge(
    pr_number: int, owner: str, repo: str, merge_method: str = "merge"
) -> bool:
    """Execute the actual merge operation."""
    logger.info(f"Executing merge for PR #{pr_number} using method: {merge_method}")

    try:
        # Use gh CLI to merge the PR
        cmd = [
            "gh",
            "pr",
            "merge",
            str(pr_number),
            f"--{merge_method}",
            "--repo",
            f"{owner}/{repo}",
        ]

        # Add delete branch flag if configured
        config = get_config()
        if config.defaults.delete_branch_on_merge:
            cmd.append("--delete-branch")

        result = run_command(cmd, capture_output=True)

        if result.returncode == 0:
            logger.info(f"Successfully merged PR #{pr_number}")
            return True
        else:
            logger.error(f"Merge command failed: {result.stderr}")
            return False

    except ShellError as e:
        logger.error(f"Error executing merge command: {e}")
        return False


async def _get_pr_info(pr_number: int, owner: str, repo: str) -> dict[str, Any]:
    """Get PR information from GitHub."""
    try:
        cmd = [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "state,draft,mergeable,reviews,statusCheckRollup,baseRefName",
        ]

        result = run_command(cmd, capture_output=True)

        if result.returncode == 0:
            import json

            return dict(json.loads(result.stdout))
        else:
            logger.error(f"Failed to get PR info: {result.stderr}")
            return {}

    except Exception as e:
        logger.error(f"Error getting PR info: {e}")
        return {}


async def _validate_reviews(pr_number: int, owner: str, repo: str) -> tuple[bool, list[str]]:
    """Validate that PR has required approvals."""
    errors = []

    try:
        pr_info = await _get_pr_info(pr_number, owner, repo)
        reviews = pr_info.get("reviews", [])

        # Check for at least one approval
        approvals = [r for r in reviews if r.get("state") == "APPROVED"]
        if not approvals:
            errors.append("No approving reviews found")

        # Check for any pending change requests
        change_requests = [r for r in reviews if r.get("state") == "CHANGES_REQUESTED"]
        if change_requests:
            errors.append(f"{len(change_requests)} unresolved change requests")

        return len(errors) == 0, errors

    except Exception as e:
        return False, [f"Error validating reviews: {str(e)}"]


async def _validate_status_checks(pr_number: int, owner: str, repo: str) -> tuple[bool, list[str]]:
    """Validate that all required status checks are passing."""
    errors = []

    try:
        pr_info = await _get_pr_info(pr_number, owner, repo)
        status_rollup = pr_info.get("statusCheckRollup", [])

        # Check for any failing status checks
        failing_checks = [
            check for check in status_rollup if check.get("state") in ["FAILURE", "ERROR"]
        ]

        if failing_checks:
            check_names = [check.get("name", "unknown") for check in failing_checks]
            errors.append(f"Failing status checks: {', '.join(check_names)}")

        # Check for any pending checks
        pending_checks = [check for check in status_rollup if check.get("state") == "PENDING"]

        if pending_checks:
            check_names = [check.get("name", "unknown") for check in pending_checks]
            errors.append(f"Pending status checks: {', '.join(check_names)}")

        return len(errors) == 0, errors

    except Exception as e:
        return False, [f"Error validating status checks: {str(e)}"]


async def _validate_branch_protection(
    branch_name: str, owner: str, repo: str
) -> tuple[bool, list[str]]:
    """Validate branch protection rules."""
    # For now, just return True as branch protection validation
    # would require more complex GitHub API calls
    return True, []


async def _get_conflict_details(pr_number: int, owner: str, repo: str) -> list[str]:
    """Get detailed information about merge conflicts."""
    try:
        # This would require more sophisticated conflict detection
        # For now, return a generic message
        return ["Merge conflicts detected - manual resolution required"]

    except Exception as e:
        return [f"Error getting conflict details: {str(e)}"]


async def _update_issue_status_after_merge(owner: str, repo: str) -> None:
    """Update associated issue status after successful merge."""
    # This would integrate with Linear/GitHub issue status updates
    # Implementation depends on issue tracking system
    logger.debug("Issue status update after merge - implementation pending")


async def _cleanup_temporary_files(worktree_path: Path) -> None:
    """Clean up any temporary files created during the workflow."""
    try:
        # Clean up any .auto state files if they exist
        auto_dir = worktree_path / ".auto"
        if auto_dir.exists():
            import shutil

            shutil.rmtree(auto_dir)
            logger.debug(f"Cleaned up temporary .auto directory: {auto_dir}")

    except Exception as e:
        logger.warning(f"Error cleaning up temporary files: {e}")
