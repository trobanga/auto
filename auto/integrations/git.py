"""Git worktree management."""

import os
import re
import shutil
from pathlib import Path
from typing import List, Optional

from auto.config import Config
from auto.models import Issue, WorktreeInfo, IssueType
from auto.utils.logger import get_logger
from auto.utils.shell import run_command, get_git_root, ShellError

logger = get_logger(__name__)


class GitWorktreeError(Exception):
    """Git worktree error."""
    pass


class GitWorktreeConflictError(GitWorktreeError):
    """Git worktree conflict error."""
    pass


class GitWorktreeManager:
    """Git worktree management."""
    
    def __init__(self, config: Config):
        """Initialize git worktree manager.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self._validate_git_repository()
    
    def _validate_git_repository(self) -> None:
        """Validate that we're in a git repository.
        
        Raises:
            GitWorktreeError: If not in a git repository
        """
        git_root = get_git_root()
        if git_root is None:
            raise GitWorktreeError("Not in a git repository. Git worktrees require a git repository.")
    
    def create_worktree(self, issue: Issue, base_branch: str = "main") -> WorktreeInfo:
        """Create worktree for issue.
        
        Args:
            issue: Issue to create worktree for
            base_branch: Base branch to create from
            
        Returns:
            Worktree information
            
        Raises:
            GitWorktreeError: If worktree creation fails
        """
        # Generate branch and worktree names
        branch_name = self.generate_branch_name(issue)
        worktree_path = self.generate_worktree_path(branch_name)
        
        logger.info(f"Creating worktree for issue {issue.id}: {worktree_path}")
        
        # Check if branch already exists
        self._handle_existing_branch(branch_name)
        
        # Check if worktree path already exists
        self._handle_existing_worktree_path(worktree_path)
        
        try:
            # Ensure base branch exists and is up to date
            self._prepare_base_branch(base_branch)
            
            # Create worktree with new branch
            self._create_git_worktree(worktree_path, branch_name, base_branch)
            
            # Create worktree info
            worktree_info = WorktreeInfo(
                path=str(worktree_path),
                branch=branch_name,
                issue_id=issue.id,
                metadata={
                    "base_branch": base_branch,
                    "issue_title": issue.title,
                    "issue_type": issue.issue_type.value if issue.issue_type else None,
                }
            )
            
            logger.info(f"Successfully created worktree: {worktree_path}")
            return worktree_info
            
        except Exception as e:
            # Clean up on failure
            self._cleanup_failed_worktree(worktree_path, branch_name)
            raise GitWorktreeError(f"Failed to create worktree for {issue.id}: {e}")
    
    def cleanup_worktree(self, worktree_info: WorktreeInfo) -> None:
        """Clean up worktree and branch.
        
        Args:
            worktree_info: Worktree to clean up
            
        Raises:
            GitWorktreeError: If cleanup fails
        """
        logger.info(f"Cleaning up worktree: {worktree_info.path}")
        
        errors = []
        
        # Remove worktree
        try:
            if worktree_info.exists():
                result = run_command(f"git worktree remove {worktree_info.path}", check=False)
                if not result.success:
                    # Try force remove if normal remove fails
                    result = run_command(f"git worktree remove --force {worktree_info.path}", check=False)
                    if not result.success:
                        # Last resort: manual directory removal
                        if worktree_info.path_obj.exists():
                            shutil.rmtree(worktree_info.path_obj)
                            logger.warning(f"Manually removed worktree directory: {worktree_info.path}")
        except Exception as e:
            errors.append(f"Failed to remove worktree directory: {e}")
        
        # Remove branch
        try:
            # Check if branch exists
            result = run_command(f"git branch --list {worktree_info.branch}", check=False)
            if result.success and result.stdout.strip():
                # Delete branch
                result = run_command(f"git branch -D {worktree_info.branch}", check=False)
                if not result.success:
                    errors.append(f"Failed to delete branch {worktree_info.branch}: {result.stderr}")
        except Exception as e:
            errors.append(f"Failed to delete branch: {e}")
        
        if errors:
            raise GitWorktreeError(f"Worktree cleanup completed with errors: {'; '.join(errors)}")
        
        logger.info(f"Successfully cleaned up worktree for {worktree_info.issue_id}")
    
    def list_worktrees(self) -> List[WorktreeInfo]:
        """List all worktrees.
        
        Returns:
            List of worktree information
        """
        try:
            result = run_command("git worktree list --porcelain", check=True)
            worktrees = []
            
            current_worktree = {}
            for line in result.stdout.strip().split('\n'):
                if not line:
                    if current_worktree:
                        worktree_info = self._parse_worktree_entry(current_worktree)
                        if worktree_info:
                            worktrees.append(worktree_info)
                    current_worktree = {}
                elif line.startswith('worktree '):
                    current_worktree['path'] = line[9:]  # Remove 'worktree ' prefix
                elif line.startswith('branch '):
                    current_worktree['branch'] = line[7:]  # Remove 'branch ' prefix
                elif line.startswith('HEAD '):
                    current_worktree['head'] = line[5:]  # Remove 'HEAD ' prefix
            
            # Handle last worktree
            if current_worktree:
                worktree_info = self._parse_worktree_entry(current_worktree)
                if worktree_info:
                    worktrees.append(worktree_info)
            
            return worktrees
            
        except ShellError as e:
            logger.warning(f"Failed to list worktrees: {e}")
            return []
    
    def _parse_worktree_entry(self, entry: dict) -> Optional[WorktreeInfo]:
        """Parse worktree entry from git worktree list output.
        
        Args:
            entry: Worktree entry dictionary
            
        Returns:
            WorktreeInfo or None if not an auto-managed worktree
        """
        path = entry.get('path')
        branch = entry.get('branch')
        
        if not path or not branch:
            return None
        
        # Only include auto-managed worktrees (branches starting with 'auto/')
        if not branch.startswith('auto/'):
            return None
        
        # Try to extract issue ID from branch name
        issue_id = self._extract_issue_id_from_branch(branch)
        if not issue_id:
            return None
        
        return WorktreeInfo(
            path=path,
            branch=branch,
            issue_id=issue_id,
        )
    
    def _extract_issue_id_from_branch(self, branch: str) -> Optional[str]:
        """Extract issue ID from branch name.
        
        Args:
            branch: Branch name
            
        Returns:
            Issue ID or None if not extractable
        """
        # Expected format: auto/{issue_type}/{issue_id}
        parts = branch.split('/')
        if len(parts) >= 3 and parts[0] == 'auto':
            # Return the issue ID part (could be #123 or ENG-456)
            return parts[2]
        return None
    
    def generate_branch_name(self, issue: Issue) -> str:
        """Generate branch name from issue.
        
        Args:
            issue: Issue to generate name for
            
        Returns:
            Branch name
        """
        # Use the branch naming pattern from config
        pattern = self.config.workflows.branch_naming
        
        # Extract issue type and clean issue ID
        issue_type = issue.issue_type.value if issue.issue_type else IssueType.TASK.value
        issue_id = issue.id.lstrip("#")  # Remove # prefix for GitHub issues
        
        # Replace placeholders
        branch_name = pattern.format(
            issue_type=issue_type,
            issue_id=issue_id,
        )
        
        # Sanitize branch name for git
        branch_name = self._sanitize_branch_name(branch_name)
        
        return branch_name
    
    def _sanitize_branch_name(self, name: str) -> str:
        """Sanitize branch name for git.
        
        Args:
            name: Raw branch name
            
        Returns:
            Sanitized branch name
        """
        # Replace invalid characters with hyphens
        sanitized = re.sub(r'[^a-zA-Z0-9/_.-]', '-', name)
        
        # Remove consecutive hyphens
        sanitized = re.sub(r'-+', '-', sanitized)
        
        # Remove leading/trailing hyphens and dots
        sanitized = sanitized.strip('-.')
        
        # Ensure it doesn't start with a slash
        sanitized = sanitized.lstrip('/')
        
        return sanitized
    
    def generate_worktree_path(self, branch_name: str) -> Path:
        """Generate worktree path from branch name.
        
        Args:
            branch_name: Branch name
            
        Returns:
            Worktree path
        """
        # Get project name for worktree base
        git_root = get_git_root()
        if git_root:
            project_name = git_root.name
        else:
            project_name = "project"
        
        # Use worktree base from config
        worktree_base_pattern = self.config.defaults.worktree_base
        worktree_base = Path(worktree_base_pattern.format(project=project_name))
        
        # Make worktree base absolute if it's relative
        if not worktree_base.is_absolute():
            if git_root:
                worktree_base = git_root.parent / worktree_base
            else:
                worktree_base = Path.cwd() / worktree_base
        
        # Generate unique directory name from branch
        dir_name = branch_name.replace('/', '-')
        worktree_path = worktree_base / dir_name
        
        return worktree_path
    
    def _handle_existing_branch(self, branch_name: str) -> None:
        """Handle existing branch conflicts.
        
        Args:
            branch_name: Branch name to check
            
        Raises:
            GitWorktreeConflictError: If branch exists and conflict resolution fails
        """
        try:
            result = run_command(f"git branch --list {branch_name}", check=False)
            if result.success and result.stdout.strip():
                # Branch exists - check conflict resolution strategy
                strategy = getattr(self.config.workflows, 'worktree_conflict_resolution', 'prompt')
                
                if strategy == 'force':
                    # Force delete existing branch
                    logger.warning(f"Force deleting existing branch: {branch_name}")
                    run_command(f"git branch -D {branch_name}", check=True)
                elif strategy == 'skip':
                    raise GitWorktreeConflictError(f"Branch {branch_name} already exists (skipped due to configuration)")
                else:
                    # Default: raise error (prompt would be handled by CLI)
                    raise GitWorktreeConflictError(f"Branch {branch_name} already exists")
        except ShellError as e:
            if "not found" not in str(e).lower():
                raise GitWorktreeError(f"Failed to check existing branch: {e}")
    
    def _handle_existing_worktree_path(self, worktree_path: Path) -> None:
        """Handle existing worktree path conflicts.
        
        Args:
            worktree_path: Worktree path to check
            
        Raises:
            GitWorktreeConflictError: If path exists and conflict resolution fails
        """
        if worktree_path.exists():
            strategy = getattr(self.config.workflows, 'worktree_conflict_resolution', 'prompt')
            
            if strategy == 'force':
                # Force remove existing directory
                logger.warning(f"Force removing existing worktree directory: {worktree_path}")
                shutil.rmtree(worktree_path)
            elif strategy == 'skip':
                raise GitWorktreeConflictError(f"Worktree path {worktree_path} already exists (skipped due to configuration)")
            else:
                # Default: raise error (prompt would be handled by CLI)
                raise GitWorktreeConflictError(f"Worktree path {worktree_path} already exists")
    
    def _prepare_base_branch(self, base_branch: str) -> None:
        """Prepare base branch for worktree creation.
        
        Args:
            base_branch: Base branch name
            
        Raises:
            GitWorktreeError: If base branch preparation fails
        """
        try:
            # Fetch latest changes
            run_command("git fetch", check=False)  # Non-critical if it fails
            
            # Check if base branch exists locally
            result = run_command(f"git branch --list {base_branch}", check=False)
            if not result.success or not result.stdout.strip():
                # Try to check if it exists on remote
                result = run_command(f"git ls-remote --heads origin {base_branch}", check=False)
                if result.success and result.stdout.strip():
                    # Create local tracking branch
                    run_command(f"git branch {base_branch} origin/{base_branch}", check=True)
                else:
                    raise GitWorktreeError(f"Base branch '{base_branch}' not found locally or on remote")
            
        except ShellError as e:
            raise GitWorktreeError(f"Failed to prepare base branch '{base_branch}': {e}")
    
    def _create_git_worktree(self, worktree_path: Path, branch_name: str, base_branch: str) -> None:
        """Create git worktree with new branch.
        
        Args:
            worktree_path: Path for new worktree
            branch_name: Name for new branch
            base_branch: Base branch to branch from
            
        Raises:
            GitWorktreeError: If worktree creation fails
        """
        try:
            # Ensure parent directory exists
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create worktree with new branch with timeout
            result = run_command(
                f"git worktree add -b {branch_name} {worktree_path} {base_branch}",
                check=True,
                timeout=60  # 60 second timeout for worktree operations
            )
            
            logger.debug(f"Git worktree created: {result.stdout}")
            
        except ShellError as e:
            raise GitWorktreeError(f"Failed to create git worktree: {e}")
        except OSError as e:
            raise GitWorktreeError(f"Filesystem error creating worktree: {e}")
    
    def _cleanup_failed_worktree(self, worktree_path: Path, branch_name: str) -> None:
        """Clean up after failed worktree creation.
        
        Args:
            worktree_path: Worktree path to clean up
            branch_name: Branch name to clean up
        """
        try:
            # Remove worktree directory if it exists
            if worktree_path.exists():
                try:
                    run_command(f"git worktree remove --force {worktree_path}", check=False)
                except:
                    shutil.rmtree(worktree_path, ignore_errors=True)
            
            # Remove branch if it was created
            run_command(f"git branch -D {branch_name}", check=False)
            
        except Exception as e:
            logger.warning(f"Failed to clean up after worktree creation failure: {e}")


def create_worktree(issue: Issue, config: Config, base_branch: str = "main") -> WorktreeInfo:
    """Create worktree for issue.
    
    Args:
        issue: Issue to create worktree for
        config: Configuration object
        base_branch: Base branch to create from
        
    Returns:
        Worktree information
    """
    manager = GitWorktreeManager(config)
    return manager.create_worktree(issue, base_branch)


def cleanup_worktree(worktree_info: WorktreeInfo, config: Config) -> None:
    """Clean up worktree and branch.
    
    Args:
        worktree_info: Worktree to clean up
        config: Configuration object
    """
    manager = GitWorktreeManager(config)
    manager.cleanup_worktree(worktree_info)