"""Merge execution functionality for pull requests.

This module handles the actual execution of merge operations,
including different merge methods and configuration options.
"""

from auto.config import get_config
from auto.utils.logger import get_logger
from auto.utils.shell import ShellError
from auto.utils.shell import run_command_async as run_command

logger = get_logger(__name__)


class MergeExecutionError(Exception):
    """Raised when merge execution fails."""

    pass


async def execute_merge(
    pr_number: int, owner: str, repo: str, merge_method: str | None = None
) -> bool:
    """Execute the actual merge operation.

    Args:
        pr_number: Pull request number to merge
        owner: Repository owner
        repo: Repository name
        merge_method: Merge method to use (merge, squash, rebase)

    Returns:
        True if merge was successful, False otherwise

    Raises:
        MergeExecutionError: If merge execution fails
    """
    if merge_method is None:
        config = get_config()
        if hasattr(config.defaults, "merge_method"):
            merge_method = config.defaults.merge_method
        else:
            merge_method = "merge"

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

        result = await run_command(cmd)

        if result.returncode == 0:
            logger.info(f"Successfully merged PR #{pr_number}")
            return True
        else:
            logger.error(f"Merge command failed: {result.stderr}")
            return False

    except ShellError as e:
        logger.error(f"Error executing merge command: {e}")
        raise MergeExecutionError(f"Error executing merge command: {e}") from e


async def validate_merge_method(merge_method: str) -> bool:
    """Validate that the specified merge method is supported.

    Args:
        merge_method: The merge method to validate

    Returns:
        True if the merge method is valid, False otherwise
    """
    valid_methods = ["merge", "squash", "rebase"]
    return merge_method in valid_methods


def get_default_merge_method() -> str:
    """Get the default merge method from configuration.

    Returns:
        The default merge method
    """
    try:
        config = get_config()
        if hasattr(config.defaults, "merge_method"):
            return str(config.defaults.merge_method)
        else:
            return "merge"
    except Exception:
        return "merge"
