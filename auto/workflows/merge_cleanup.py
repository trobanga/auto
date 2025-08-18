"""Post-merge cleanup functionality.

This module handles cleanup operations after a successful merge,
including worktree removal, issue status updates, and temporary file cleanup.
"""

import shutil
from pathlib import Path

from auto.utils.logger import get_logger
from auto.utils.shell import run_command_async

logger = get_logger(__name__)


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
            try:
                result = await run_command_async(f"git worktree remove {worktree_path}")
                if result.returncode == 0:
                    logger.info(f"Removed worktree: {worktree_path}")
                else:
                    logger.warning(f"Failed to remove worktree {worktree_path}: {result.stderr}")
                    # Fallback to manual directory removal
                    shutil.rmtree(worktree_path, ignore_errors=True)
                    logger.info(f"Manually removed worktree directory: {worktree_path}")
            except Exception as e:
                logger.warning(f"Error removing worktree {worktree_path}: {e}")
                # Fallback to manual directory removal
                shutil.rmtree(worktree_path, ignore_errors=True)
                logger.info(f"Manually removed worktree directory: {worktree_path}")

        # Update issue status if configured
        if update_issue_status:
            await update_issue_status_after_merge(owner, repo)

        # Clean up any temporary files or state
        await cleanup_temporary_files(worktree_path)

        logger.info("Post-merge cleanup completed successfully")

    except Exception as e:
        logger.error(f"Error during post-merge cleanup: {e}")
        # Don't re-raise as cleanup failure shouldn't fail the merge


async def cleanup_temporary_files(worktree_path: Path) -> None:
    """Clean up any temporary files created during the workflow.

    Args:
        worktree_path: Path to the worktree directory
    """
    try:
        # Clean up any .auto state files if they exist
        auto_dir = worktree_path / ".auto"
        if auto_dir.exists():
            shutil.rmtree(auto_dir)
            logger.debug(f"Cleaned up temporary .auto directory: {auto_dir}")

    except Exception as e:
        logger.warning(f"Error cleaning up temporary files: {e}")


async def update_issue_status_after_merge(owner: str, repo: str) -> None:
    """Update associated issue status after successful merge.

    Args:
        owner: Repository owner
        repo: Repository name
    """
    # This would integrate with Linear/GitHub issue status updates
    # Implementation depends on issue tracking system
    logger.debug("Issue status update after merge - implementation pending")


async def cleanup_stale_worktrees(base_path: Path, max_age_days: int = 7) -> None:
    """Clean up stale worktrees that are older than the specified age.

    Args:
        base_path: Base path where worktrees are stored
        max_age_days: Maximum age in days before a worktree is considered stale
    """
    from datetime import datetime, timedelta

    try:
        if not base_path.exists():
            return

        cutoff_time = datetime.now() - timedelta(days=max_age_days)

        for worktree_dir in base_path.iterdir():
            if worktree_dir.is_dir():
                # Check if worktree is older than cutoff
                modification_time = datetime.fromtimestamp(worktree_dir.stat().st_mtime)

                if modification_time < cutoff_time:
                    try:
                        result = await run_command_async(f"git worktree remove {worktree_dir}")
                        if result.returncode == 0:
                            logger.info(f"Cleaned up stale worktree: {worktree_dir}")
                        else:
                            logger.warning(
                                f"Failed to clean up stale worktree {worktree_dir}: {result.stderr}"
                            )
                            # Fallback to manual directory removal
                            shutil.rmtree(worktree_dir, ignore_errors=True)
                            logger.info(
                                f"Manually cleaned up stale worktree directory: {worktree_dir}"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to clean up stale worktree {worktree_dir}: {e}")
                        # Fallback to manual directory removal
                        shutil.rmtree(worktree_dir, ignore_errors=True)
                        logger.info(f"Manually cleaned up stale worktree directory: {worktree_dir}")

    except Exception as e:
        logger.error(f"Error during stale worktree cleanup: {e}")


async def cleanup_merge_state(pr_number: int) -> None:
    """Clean up any persistent state files for the merged PR.

    Args:
        pr_number: Pull request number that was merged
    """
    try:
        from pathlib import Path

        # Clean up state files
        state_dir = Path(".auto/state")
        if state_dir.exists():
            state_file = state_dir / f"{pr_number}.yaml"
            if state_file.exists():
                state_file.unlink()
                logger.debug(f"Cleaned up state file: {state_file}")

    except Exception as e:
        logger.warning(f"Error cleaning up merge state: {e}")
