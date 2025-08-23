"""Merge conflict detection and handling for pull requests.

This module handles detection of merge conflicts and provides guidance
for resolving them during the merge process.
"""

from typing import Any

from auto.utils.logger import get_logger
from auto.utils.shell import run_command_async as run_command

logger = get_logger(__name__)


class MergeConflictError(Exception):
    """Raised when merge conflicts are detected."""

    pass


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
            conflicts = await get_conflict_details(pr_number, owner, repo)
            logger.warning(f"Merge conflicts detected in PR #{pr_number}: {conflicts}")
            return conflicts

        logger.debug(f"No merge conflicts detected for PR #{pr_number}")
        return None

    except Exception as e:
        logger.error(f"Error checking for merge conflicts: {e}")
        return [f"Error checking conflicts: {str(e)}"]


async def get_conflict_details(pr_number: int, owner: str, repo: str) -> list[str]:
    """Get detailed information about merge conflicts.

    Args:
        pr_number: Pull request number
        owner: Repository owner
        repo: Repository name

    Returns:
        List of conflict descriptions
    """
    try:
        # This would require more sophisticated conflict detection
        # For now, return a generic message
        return ["Merge conflicts detected - manual resolution required"]

    except Exception as e:
        return [f"Error getting conflict details: {str(e)}"]


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

        result = await run_command(cmd)

        if result.returncode == 0:
            import json

            return dict(json.loads(result.stdout))
        else:
            logger.error(f"Failed to get PR info: {result.stderr}")
            return {}

    except Exception as e:
        logger.error(f"Error getting PR info: {e}")
        return {}
