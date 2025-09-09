"""Automated merge workflow after approval validation.

This module provides the main interface for automated merge operations,
coordinating validation, conflict detection, merge execution, and cleanup.
"""

import asyncio
from pathlib import Path

from auto.models import Config, ConflictDetails, GitHubRepository, MergeResult
from auto.utils.logger import get_logger
from auto.utils.shell import run_command_async
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


async def _execute_merge_operation(
    pr_number: int, repository: GitHubRepository, method: str, config: Config
) -> MergeResult:
    """Execute GitHub PR merge operation with comprehensive error handling and retry logic.

    Args:
        pr_number: Pull request number to merge
        repository: GitHub repository context
        method: Merge method (merge, squash, rebase)
        config: Configuration object

    Returns:
        MergeResult with detailed operation results

    Raises:
        MergeValidationError: If pre-merge validation fails
        MergeExecutionError: If merge execution fails after retries
    """
    logger.info(f"Executing merge operation for PR #{pr_number} using method: {method}")

    # Initialize result with defaults
    result = MergeResult(success=False, method_used=method, retry_count=0)

    try:
        # Step 1: Execute pre-merge validation
        logger.debug("Running pre-merge validation")
        is_eligible, validation_errors = await validate_merge_eligibility(
            pr_number, repository.owner, repository.name, force=False
        )

        if not is_eligible:
            result.validation_errors = validation_errors
            result.error_message = f"Pre-merge validation failed: {'; '.join(validation_errors)}"
            logger.error(f"PR #{pr_number} failed validation: {validation_errors}")
            return result

        # Step 2: Check for merge conflicts
        logger.debug("Checking for merge conflicts")
        conflict_files = await handle_merge_conflicts(pr_number, repository.owner, repository.name)
        if conflict_files:
            conflict_details = ConflictDetails(
                conflicted_files=conflict_files,
                conflict_summary=f"Found {len(conflict_files)} files with conflicts",
                resolution_suggestions=[
                    "Resolve conflicts locally and push to the PR branch",
                    "Use GitHub's web interface to resolve simple conflicts",
                    "Consider rebasing the PR branch on the target branch",
                ],
            )
            result.conflict_details = conflict_details
            result.error_message = f"Merge conflicts detected in {len(conflict_files)} files"
            logger.error(f"PR #{pr_number} has merge conflicts: {conflict_files}")
            return result

        # Step 3: Execute merge with retry logic
        max_retries = getattr(config.defaults, "merge_retry_attempts", 3)
        retry_delay = getattr(config.defaults, "merge_retry_delay", 5)  # seconds

        for attempt in range(max_retries):
            result.retry_count = attempt

            try:
                logger.info(f"Merge attempt {attempt + 1}/{max_retries}")

                # Build gh CLI command
                cmd = [
                    "gh",
                    "pr",
                    "merge",
                    str(pr_number),
                    f"--{method}",
                    "--repo",
                    repository.full_name,
                ]

                # Add delete branch flag if configured
                if config.defaults.delete_branch_on_merge:
                    cmd.append("--delete-branch")

                # Execute merge with timeout
                timeout = getattr(config.defaults, "merge_timeout", 120)  # 2 minutes default
                shell_result = await run_command_async(
                    cmd,
                    timeout=timeout,
                    check=False,  # We'll handle errors manually
                )

                # Store raw GitHub response info
                result.github_api_response = {
                    "returncode": shell_result.returncode,
                    "stdout": shell_result.stdout,
                    "stderr": shell_result.stderr,
                    "command": " ".join(cmd),
                }

                if shell_result.success:
                    # Extract merge commit SHA from output
                    merge_sha = await _extract_merge_commit_sha(
                        shell_result.stdout, repository, pr_number
                    )
                    result.merge_commit_sha = merge_sha
                    result.success = True

                    logger.info(
                        f"Successfully merged PR #{pr_number} using {method} method "
                        f"(commit: {merge_sha or 'unknown'})"
                    )
                    return result

                else:
                    # Check if this is a recoverable error
                    if _is_recoverable_error(shell_result.stderr):
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"Merge attempt {attempt + 1} failed with recoverable error, "
                                f"retrying in {retry_delay}s: {shell_result.stderr}"
                            )
                            await asyncio.sleep(retry_delay)
                            continue

                    # Non-recoverable error or final attempt
                    result.error_message = f"Merge failed: {shell_result.stderr}"
                    logger.error(f"PR #{pr_number} merge failed: {shell_result.stderr}")
                    return result

            except TimeoutError:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Merge attempt {attempt + 1} timed out, retrying in {retry_delay}s"
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    result.error_message = f"Merge operation timed out after {timeout}s"
                    logger.error(f"PR #{pr_number} merge timed out")
                    return result

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Merge attempt {attempt + 1} failed with exception, retrying: {e}"
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    result.error_message = f"Unexpected error during merge: {str(e)}"
                    logger.error(f"PR #{pr_number} merge failed with exception: {e}")
                    return result

        # If we get here, all retries failed
        result.error_message = f"Merge failed after {max_retries} attempts"
        return result

    except Exception as e:
        result.error_message = f"Pre-merge setup failed: {str(e)}"
        logger.error(f"Error in merge operation setup: {e}")
        return result


async def _extract_merge_commit_sha(
    gh_output: str, repository: GitHubRepository, pr_number: int
) -> str | None:
    """Extract merge commit SHA from gh CLI output or fetch from API.

    Args:
        gh_output: Output from gh pr merge command
        repository: GitHub repository context
        pr_number: Pull request number

    Returns:
        Merge commit SHA if found, None otherwise
    """
    import re

    # Try to extract from gh output first
    sha_pattern = r"[a-f0-9]{40}|[a-f0-9]{7,}"
    matches = re.findall(sha_pattern, gh_output)
    if matches:
        # Return the longest match (likely the full SHA)
        return max(matches, key=len)

    # Fallback: Query the PR to get merge commit SHA
    try:
        cmd = [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repository.full_name,
            "--json",
            "mergeCommit",
        ]

        result = await run_command_async(cmd, timeout=30)
        if result.success:
            import json

            pr_data = json.loads(result.stdout)
            merge_commit = pr_data.get("mergeCommit")
            if merge_commit and isinstance(merge_commit, dict):
                return merge_commit.get("oid")

    except Exception as e:
        logger.warning(f"Could not fetch merge commit SHA: {e}")

    return None


def _is_recoverable_error(error_message: str) -> bool:
    """Check if a merge error is potentially recoverable with retry.

    Args:
        error_message: Error message from gh CLI

    Returns:
        True if error might be recoverable with retry
    """
    if not error_message:
        return False

    error_lower = error_message.lower()

    # GitHub API rate limiting or temporary issues
    recoverable_patterns = [
        "rate limit",
        "api rate limit",
        "temporarily unavailable",
        "service unavailable",
        "timeout",
        "connection reset",
        "502 bad gateway",
        "503 service unavailable",
        "504 gateway timeout",
        "network error",
        "temporary failure",
    ]

    return any(pattern in error_lower for pattern in recoverable_patterns)


async def _update_issue_status_after_merge(owner: str, repo: str) -> None:
    """Update issue status after successful merge."""
    # This is a placeholder function for testing
    pass


async def _cleanup_temporary_files(worktree_path: Path) -> None:
    """Clean up temporary files after merge."""
    # This is a placeholder function for testing
    pass
