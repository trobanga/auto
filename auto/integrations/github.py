"""GitHub integration via gh CLI."""

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from typing import List, Optional

from auto.models import GitHubRepository, Issue, IssueProvider, IssueStatus
from auto.utils.logger import get_logger
from auto.utils.shell import run_command, check_command_exists, ShellError

logger = get_logger(__name__)


class GitHubIntegrationError(Exception):
    """GitHub integration error."""
    pass


class GitHubAuthError(GitHubIntegrationError):
    """GitHub authentication error."""
    pass


class GitHubRepositoryError(GitHubIntegrationError):
    """GitHub repository error."""
    pass


class GitHubIssueError(GitHubIntegrationError):
    """GitHub issue error."""
    pass


class GitHubIntegration:
    """GitHub integration using gh CLI."""
    
    def __init__(self):
        """Initialize GitHub integration."""
        self.validate_auth()
    
    def validate_auth(self) -> None:
        """Validate GitHub authentication.
        
        Raises:
            GitHubAuthError: If authentication is not valid
        """
        if not validate_github_auth():
            raise GitHubAuthError(
                "GitHub CLI authentication required. Run 'gh auth login' to authenticate."
            )
    
    def detect_repository(self) -> GitHubRepository:
        """Detect GitHub repository from current directory.
        
        Returns:
            GitHub repository information
            
        Raises:
            GitHubRepositoryError: If repository cannot be detected
        """
        repo = detect_repository()
        if repo is None:
            raise GitHubRepositoryError(
                "Could not detect GitHub repository. Ensure you're in a git repository with a GitHub remote."
            )
        return repo
    
    def fetch_issue(self, issue_id: str, repository: Optional[GitHubRepository] = None) -> Issue:
        """Fetch GitHub issue by ID.
        
        Args:
            issue_id: Issue ID (e.g., "#123")
            repository: Repository context (auto-detected if None)
            
        Returns:
            Issue object
            
        Raises:
            GitHubIssueError: If issue cannot be fetched
        """
        if repository is None:
            repository = self.detect_repository()
        
        # Clean issue ID (remove # prefix if present)
        clean_issue_id = issue_id.lstrip("#")
        
        try:
            # Use gh CLI to fetch issue details with timeout
            result = run_command(
                f"gh issue view {clean_issue_id} --repo {repository.full_name} --json number,title,body,state,labels,assignees,createdAt,updatedAt,url",
                check=True,
                timeout=30  # 30 second timeout for network operations
            )
            
            issue_data = json.loads(result.stdout)
            
            # Parse labels
            labels = [label["name"] for label in issue_data.get("labels", [])]
            
            # Parse assignee
            assignees = issue_data.get("assignees", [])
            assignee = assignees[0]["login"] if assignees else None
            
            # Parse timestamps
            created_at = None
            updated_at = None
            if issue_data.get("createdAt"):
                created_at = datetime.fromisoformat(issue_data["createdAt"].replace("Z", "+00:00"))
            if issue_data.get("updatedAt"):
                updated_at = datetime.fromisoformat(issue_data["updatedAt"].replace("Z", "+00:00"))
            
            # Map state
            state_map = {
                "OPEN": IssueStatus.OPEN,
                "CLOSED": IssueStatus.CLOSED,
            }
            status = state_map.get(issue_data.get("state", "OPEN"), IssueStatus.OPEN)
            
            return Issue(
                id=f"#{issue_data['number']}",
                provider=IssueProvider.GITHUB,
                title=issue_data["title"],
                description=issue_data.get("body", ""),
                status=status,
                assignee=assignee,
                labels=labels,
                url=issue_data.get("url"),
                created_at=created_at,
                updated_at=updated_at,
            )
            
        except ShellError as e:
            if "could not resolve to an Issue" in e.stderr:
                raise GitHubIssueError(f"Issue #{clean_issue_id} not found in {repository.full_name}")
            elif "HTTP 404" in e.stderr:
                raise GitHubIssueError(f"Repository {repository.full_name} not found or not accessible")
            else:
                raise GitHubIssueError(f"Failed to fetch issue #{clean_issue_id}: {e.stderr}")
        except json.JSONDecodeError as e:
            raise GitHubIssueError(f"Failed to parse issue data: {e}")
    
    def list_issues(
        self, 
        repository: Optional[GitHubRepository] = None,
        state: str = "open",
        assignee: Optional[str] = None,
        labels: Optional[List[str]] = None,
        limit: int = 30
    ) -> List[Issue]:
        """List GitHub issues for repository.
        
        Args:
            repository: Repository context (auto-detected if None)
            state: Filter by state: open, closed, or all (default: open)
            assignee: Filter by assignee username
            labels: Filter by label names
            limit: Maximum number of issues to fetch (default: 30)
            
        Returns:
            List of Issue objects
            
        Raises:
            GitHubIssueError: If issues cannot be fetched
        """
        if repository is None:
            repository = self.detect_repository()
        
        # Build gh issue list command
        cmd_parts = [
            "gh", "issue", "list",
            "--repo", repository.full_name,
            "--state", state,
            "--limit", str(limit),
            "--json", "number,title,body,state,labels,assignees,createdAt,updatedAt,url"
        ]
        
        # Add optional filters
        if assignee:
            cmd_parts.extend(["--assignee", assignee])
        
        if labels:
            for label in labels:
                cmd_parts.extend(["--label", label])
        
        try:
            # Execute command with timeout
            result = run_command(
                " ".join(cmd_parts),
                check=True,
                timeout=30
            )
            
            issues_data = json.loads(result.stdout)
            issues = []
            
            # Parse each issue
            for issue_data in issues_data:
                # Parse labels
                labels_list = [label["name"] for label in issue_data.get("labels", [])]
                
                # Parse assignee
                assignees = issue_data.get("assignees", [])
                assignee_username = assignees[0]["login"] if assignees else None
                
                # Parse timestamps
                created_at = None
                updated_at = None
                if issue_data.get("createdAt"):
                    created_at = datetime.fromisoformat(issue_data["createdAt"].replace("Z", "+00:00"))
                if issue_data.get("updatedAt"):
                    updated_at = datetime.fromisoformat(issue_data["updatedAt"].replace("Z", "+00:00"))
                
                # Map state
                state_map = {
                    "OPEN": IssueStatus.OPEN,
                    "CLOSED": IssueStatus.CLOSED,
                }
                status = state_map.get(issue_data.get("state", "OPEN"), IssueStatus.OPEN)
                
                issue = Issue(
                    id=f"#{issue_data['number']}",
                    provider=IssueProvider.GITHUB,
                    title=issue_data["title"],
                    description=issue_data.get("body", ""),
                    status=status,
                    assignee=assignee_username,
                    labels=labels_list,
                    url=issue_data.get("url"),
                    created_at=created_at,
                    updated_at=updated_at,
                )
                issues.append(issue)
            
            return issues
            
        except ShellError as e:
            if "HTTP 404" in e.stderr:
                raise GitHubIssueError(f"Repository {repository.full_name} not found or not accessible")
            else:
                raise GitHubIssueError(f"Failed to list issues: {e.stderr}")
        except json.JSONDecodeError as e:
            raise GitHubIssueError(f"Failed to parse issues data: {e}")
    
    async def create_pull_request(
        self,
        title: str,
        description: str,
        head_branch: str,
        base_branch: str = "main",
        draft: bool = False
    ) -> "PullRequest":
        """Create a pull request using gh CLI.
        
        Args:
            title: PR title
            description: PR description/body
            head_branch: Source branch
            base_branch: Target branch
            draft: Create as draft PR
            
        Returns:
            Created PullRequest object
            
        Raises:
            GitHubIntegrationError: If PR creation fails
        """
        from auto.models import PullRequest, PRStatus
        
        try:
            logger.info(f"Creating PR: {title}")
            
            # Write description to temporary file to avoid argument length limits
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as temp_file:
                temp_file.write(description)
                temp_file_path = temp_file.name
            
            try:
                # Build gh pr create command using temp file for body
                cmd_args = [
                    "gh", "pr", "create",
                    "--title", title,
                    "--body-file", temp_file_path,
                    "--base", base_branch,
                    "--head", head_branch
                ]
                
                if draft:
                    cmd_args.append("--draft")
                
                # Create the PR using subprocess with proper argument separation
                result = subprocess.run(
                    cmd_args,
                    capture_output=True,
                    text=True,
                    check=True
                )
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except OSError:
                    pass  # Ignore cleanup errors
            
            # Extract PR URL from output
            pr_url = result.stdout.strip()
            
            # Extract PR number from URL
            pr_match = re.search(r'/pull/(\d+)', pr_url)
            if not pr_match:
                raise GitHubIntegrationError(f"Could not extract PR number from URL: {pr_url}")
            
            pr_number = int(pr_match.group(1))
            
            logger.info(f"Successfully created PR #{pr_number}: {pr_url}")
            
            return PullRequest(
                number=pr_number,
                title=title,
                description=description,
                status=PRStatus.DRAFT if draft else PRStatus.OPEN,
                branch=head_branch,
                base_branch=base_branch,
                url=pr_url
            )
            
        except subprocess.CalledProcessError as e:
            raise GitHubIntegrationError(f"Failed to create PR: {e.stderr}")
        except Exception as e:
            raise GitHubIntegrationError(f"Failed to create PR: {e}")
    
    async def add_pr_labels(self, pr_number: int, labels: List[str]) -> None:
        """Add labels to a pull request.
        
        Args:
            pr_number: PR number
            labels: List of label names
            
        Raises:
            GitHubIntegrationError: If adding labels fails
        """
        if not labels:
            return
            
        try:
            logger.debug(f"Adding labels to PR #{pr_number}: {labels}")
            
            # Build command
            labels_str = ",".join(labels)
            cmd = f'gh pr edit {pr_number} --add-label "{labels_str}"'
            
            run_command(cmd, check=True)
            logger.debug(f"Successfully added labels to PR #{pr_number}")
            
        except ShellError as e:
            logger.warning(f"Failed to add labels to PR #{pr_number}: {e.stderr}")
            # Don't raise - labels are not critical for PR creation
    
    async def add_pr_assignees(self, pr_number: int, assignees: List[str]) -> None:
        """Add assignees to a pull request.
        
        Args:
            pr_number: PR number
            assignees: List of assignee usernames
            
        Raises:
            GitHubIntegrationError: If adding assignees fails
        """
        if not assignees:
            return
            
        try:
            logger.debug(f"Adding assignees to PR #{pr_number}: {assignees}")
            
            # Build command
            assignees_str = ",".join(assignees)
            cmd = f'gh pr edit {pr_number} --add-assignee "{assignees_str}"'
            
            run_command(cmd, check=True)
            logger.debug(f"Successfully added assignees to PR #{pr_number}")
            
        except ShellError as e:
            logger.warning(f"Failed to add assignees to PR #{pr_number}: {e.stderr}")
            # Don't raise - assignees are not critical for PR creation
    
    async def request_pr_reviewers(self, pr_number: int, reviewers: List[str]) -> None:
        """Request reviewers for a pull request.
        
        Args:
            pr_number: PR number
            reviewers: List of reviewer usernames
            
        Raises:
            GitHubIntegrationError: If requesting reviewers fails
        """
        if not reviewers:
            return
            
        try:
            logger.debug(f"Requesting reviewers for PR #{pr_number}: {reviewers}")
            
            # Build command
            reviewers_str = ",".join(reviewers)
            cmd = f'gh pr edit {pr_number} --add-reviewer "{reviewers_str}"'
            
            run_command(cmd, check=True)
            logger.debug(f"Successfully requested reviewers for PR #{pr_number}")
            
        except ShellError as e:
            logger.warning(f"Failed to request reviewers for PR #{pr_number}: {e.stderr}")
            # Don't raise - reviewers are not critical for PR creation


def validate_github_auth() -> bool:
    """Validate GitHub authentication via gh CLI.
    
    Returns:
        True if authenticated, False otherwise
    """
    # Check if gh CLI is installed
    if not check_command_exists("gh"):
        logger.warning("GitHub CLI (gh) not found. Please install it first.")
        return False
    
    try:
        # Check authentication status
        result = run_command("gh auth status", check=False)
        
        # gh auth status returns 0 when authenticated, non-zero when not
        if result.success:
            logger.debug("GitHub CLI authentication verified")
            return True
        else:
            logger.debug("GitHub CLI not authenticated")
            return False
            
    except ShellError:
        logger.debug("Failed to check GitHub CLI authentication")
        return False


def detect_repository() -> Optional[GitHubRepository]:
    """Detect GitHub repository from git remote.
    
    Returns:
        Repository information or None if not detected
    """
    try:
        # Get remote URL
        result = run_command("git remote get-url origin", check=True)
        remote_url = result.stdout.strip()
        
        # Parse GitHub URL patterns
        github_patterns = [
            r"https://github\.com/([^/]+)/([^/]+)(?:\.git)?/?$",
            r"git@github\.com:([^/]+)/([^/]+)(?:\.git)?$",
        ]
        
        for pattern in github_patterns:
            match = re.match(pattern, remote_url)
            if match:
                owner, name = match.groups()
                # Remove .git suffix if present
                name = name.rstrip(".git")
                
                # Try to get default branch
                default_branch = "main"  # Default fallback
                try:
                    # Try to get default branch from remote
                    branch_result = run_command("git symbolic-ref refs/remotes/origin/HEAD", check=False)
                    if branch_result.success:
                        # Extract branch name from refs/remotes/origin/branch_name
                        default_branch = branch_result.stdout.strip().split("/")[-1]
                    else:
                        # Fallback: try to detect main/master
                        main_result = run_command("git ls-remote --heads origin main", check=False)
                        master_result = run_command("git ls-remote --heads origin master", check=False)
                        if main_result.success and main_result.stdout.strip():
                            default_branch = "main"
                        elif master_result.success and master_result.stdout.strip():
                            default_branch = "master"
                except ShellError:
                    pass  # Keep default_branch as "main"
                
                return GitHubRepository(
                    owner=owner,
                    name=name,
                    default_branch=default_branch,
                    remote_url=remote_url,
                )
        
        logger.debug(f"Remote URL does not match GitHub patterns: {remote_url}")
        return None
        
    except ShellError:
        logger.debug("Could not detect GitHub repository from git remote")
        return None
