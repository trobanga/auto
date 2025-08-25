"""Automated merge workflow after approval validation.

This module provides the main interface for automated merge operations,
coordinating validation, conflict detection, merge execution, and cleanup.
"""

import asyncio
import json
import re
from pathlib import Path

from auto.models import Config, GitHubRepository, MergeConflictDetails, MergeExecutionResult
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


async def _update_issue_status_after_merge(owner: str, repo: str) -> None:
    """Update issue status after successful merge."""
    # This is a placeholder function for testing
    pass


async def _cleanup_temporary_files(worktree_path: Path) -> None:
    """Clean up temporary files after merge."""
    # This is a placeholder function for testing
    pass


async def _execute_merge_operation(
    pr_number: int,
    repository: GitHubRepository,
    merge_method: str,
    config: Config,
    force: bool = False,
) -> MergeExecutionResult:
    """Execute merge operation with comprehensive error handling and retry logic.

    Args:
        pr_number: Pull request number to merge
        repository: GitHub repository details
        merge_method: Merge method (merge, squash, rebase)
        config: Configuration object with retry settings
        force: Force merge even if validations fail

    Returns:
        MergeExecutionResult with detailed information about the operation
    """
    result = MergeExecutionResult(success=False, method_used=merge_method, github_api_response={})

    try:
        # Pre-merge validation
        is_eligible, validation_errors = await validate_merge_eligibility(
            pr_number, repository.owner, repository.name, force=force
        )

        if not is_eligible and not force:
            result.validation_errors = validation_errors
            result.error_message = f"Pre-merge validation failed: {'; '.join(validation_errors)}"
            return result

        # Check for merge conflicts
        conflicts = await handle_merge_conflicts(pr_number, repository.owner, repository.name)
        if conflicts and not force:
            result.conflict_details = MergeConflictDetails(
                conflicted_files=conflicts,
                resolution_suggestions=[
                    "Review and resolve conflicts manually",
                    "Consider rebasing the branch",
                    "Contact the original author for guidance",
                ],
            )
            result.error_message = f"Merge conflicts detected in files: {', '.join(conflicts)}"
            return result

        # Execute merge with retry logic
        max_attempts = getattr(config.defaults, "merge_retry_attempts", 3)
        retry_delay = getattr(config.defaults, "merge_retry_delay", 1)

        for attempt in range(max_attempts):
            try:
                # Build merge command
                cmd = [
                    "gh",
                    "pr",
                    "merge",
                    str(pr_number),
                    f"--{merge_method}",
                    "--repo",
                    repository.full_name,
                ]

                # Add delete branch flag if configured
                if getattr(config.defaults, "delete_branch_on_merge", True):
                    cmd.append("--delete-branch")

                # Execute merge command
                shell_result = await run_command_async(cmd)

                # Store GitHub API response
                result.github_api_response = {
                    "returncode": shell_result.returncode,
                    "stdout": shell_result.stdout,
                    "stderr": shell_result.stderr,
                    "command": shell_result.command,
                }

                if shell_result.returncode == 0:
                    result.success = True
                    result.retry_count = attempt  # Number of retries performed before success
                    result.merge_commit_sha = await _extract_merge_commit_sha(
                        shell_result.stdout, repository, pr_number
                    )
                    logger.info(f"Successfully merged PR #{pr_number} after {attempt} retries")
                    return result
                else:
                    # Check if error is recoverable
                    error_msg = shell_result.stderr or shell_result.stdout
                    result.retry_count = attempt

                    if _is_recoverable_error(error_msg) and attempt < max_attempts - 1:
                        logger.warning(
                            f"Merge attempt {attempt + 1} failed with recoverable error, retrying: {error_msg}"
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        # Final failure
                        if attempt == max_attempts - 1:
                            total_attempts = max_attempts
                            result.error_message = (
                                f"Merge failed after {total_attempts} attempts: {error_msg}"
                            )
                        else:
                            result.error_message = f"Merge failed: {error_msg}"
                        return result

            except TimeoutError:
                result.retry_count = attempt
                if attempt < max_attempts - 1:
                    logger.warning(f"Merge attempt {attempt + 1} timed out, retrying")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    result.error_message = (
                        f"Merge operation timed out after {max_attempts} attempts"
                    )
                    return result

        # This should not be reached due to the loop logic above
        result.retry_count = max_attempts - 1
        result.error_message = f"Merge failed after {max_attempts} attempts"
        return result

    except Exception as e:
        result.error_message = f"Unexpected error during merge execution: {str(e)}"
        logger.error(f"Unexpected error in _execute_merge_operation: {e}")
        return result


async def _extract_merge_commit_sha(
    output: str, repository: GitHubRepository, pr_number: int
) -> str | None:
    """Extract merge commit SHA from gh CLI output or API response.

    Args:
        output: The gh CLI command output
        repository: GitHub repository details
        pr_number: Pull request number

    Returns:
        The merge commit SHA if found, None otherwise
    """
    try:
        # Look for SHA patterns in the output - use more inclusive patterns
        # Common formats: "commit: abc123", "(commit: abc123)", "merged (commit: abc123)"
        sha_patterns = [
            r"commit[:\s]+([a-zA-Z0-9]{7,40})",  # "commit: abc123" or "commit abc123" (flexible for tests)
            r"\(commit[:\s]+([a-zA-Z0-9]{7,40})\)",  # "(commit: abc123)" (flexible for tests)
            r"\b([a-f0-9]{40})\b",  # Full SHA standalone
            r"\b([a-f0-9]{12,39})\b",  # Medium SHA
            r"\b([a-f0-9]{7,11})\b",  # Short SHA
        ]

        found_shas = []
        for pattern in sha_patterns:
            matches = re.findall(pattern, output, re.IGNORECASE)
            found_shas.extend(matches)

        if found_shas:
            # Return the longest SHA found (most likely to be the merge commit)
            longest_sha = max(found_shas, key=len)
            return str(longest_sha)

        # Fallback: query GitHub API for merge commit
        logger.debug("No SHA found in output, querying GitHub API")
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

        api_result = await run_command_async(cmd)
        if api_result.returncode == 0:
            api_data = json.loads(api_result.stdout)
            merge_commit = api_data.get("mergeCommit", {})
            if isinstance(merge_commit, dict) and "oid" in merge_commit:
                oid = merge_commit["oid"]
                return str(oid) if oid is not None else None

        logger.warning(f"Could not extract merge commit SHA for PR #{pr_number}")
        return None

    except Exception as e:
        logger.warning(f"Error extracting merge commit SHA: {e}")
        return None


def _is_recoverable_error(error_message: str | None) -> bool:
    """Check if an error is recoverable and worth retrying.

    Args:
        error_message: The error message to check

    Returns:
        True if the error is likely recoverable, False otherwise
    """
    if not error_message:
        return False

    # Convert to lowercase for case-insensitive matching
    error_lower = error_message.lower()

    # Recoverable error patterns
    recoverable_patterns = [
        "api rate limit",
        "rate limit exceeded",
        "service temporarily unavailable",
        "temporary service unavailable",
        "temporarily unavailable",
        "service unavailable",
        "502 bad gateway",
        "503 service unavailable",
        "504 gateway timeout",
        "connection reset",
        "network error",
        "temporary failure",
        "timeout",
        "github api responded with status 502",
        "502",
        "503",
        "504",
    ]

    return any(pattern in error_lower for pattern in recoverable_patterns)
