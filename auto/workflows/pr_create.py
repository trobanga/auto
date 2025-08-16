"""
Pull Request Creation Workflow

Handles GitHub PR creation automation including description generation, commit preparation,
template support, and metadata management.
"""

import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from ..integrations.github import GitHubIntegration, GitHubError
from ..models import Issue, WorkflowState, WorkflowStatus, PRMetadata, PullRequest, PRStatus
from ..utils.logger import get_logger
from ..config import Config

logger = get_logger(__name__)


class PRCreationError(Exception):
    """Exception raised for PR creation workflow errors."""
    pass


async def create_pull_request_workflow(
    issue: Issue,
    workflow_state: WorkflowState,
    draft: bool = False,
    auto_merge: bool = False
) -> WorkflowState:
    """
    Complete PR creation workflow for an implemented issue.
    
    Validates implementation, commits changes, pushes branch, creates GitHub PR
    with templates, and updates workflow state.
    
    Args:
        issue: Issue that was implemented
        workflow_state: Current workflow state
        draft: Create PR as draft
        auto_merge: Enable auto-merge after approval
        
    Returns:
        Updated workflow state with PR information
        
    Raises:
        PRCreationError: If PR creation fails
    """
    logger.info(f"Starting PR creation for issue {issue.id}")
    
    try:
        # Validate prerequisites
        validate_pr_prerequisites(workflow_state)
        
        # Update state to creating PR
        workflow_state.update_status(WorkflowStatus.CREATING_PR)
        
        config = Config()
        
        # Validate implementation exists
        if not has_uncommitted_changes(workflow_state.worktree):
            logger.warning("No uncommitted changes found, checking if implementation was committed")
            if not has_implementation_commits(workflow_state.worktree, workflow_state.branch):
                raise PRCreationError("No implementation changes found to create PR")
        
        # Generate PR metadata
        pr_metadata = generate_pr_metadata(issue, workflow_state, config, draft)
        workflow_state.pr_metadata = pr_metadata
        
        # Commit implementation changes
        await commit_implementation_changes(
            issue=issue,
            workflow_state=workflow_state,
            config=config
        )
        
        # Push branch to remote
        await push_branch_to_remote(workflow_state)
        
        # Create GitHub PR
        github_integration = GitHubIntegration(config.github)
        pr = await create_github_pr(
            github_integration=github_integration,
            pr_metadata=pr_metadata,
            workflow_state=workflow_state
        )
        
        # Update workflow state with PR info
        workflow_state.pr_number = pr.number
        workflow_state.update_status(WorkflowStatus.IN_REVIEW)
        
        logger.info(f"Successfully created PR #{pr.number} for issue {issue.id}")
        logger.info(f"PR URL: {pr.url}")
        
        return workflow_state
        
    except GitHubError as e:
        logger.error(f"GitHub error during PR creation: {e}")
        workflow_state.update_status(WorkflowStatus.FAILED)
        raise PRCreationError(f"GitHub PR creation failed: {e}")
    
    except Exception as e:
        logger.error(f"Unexpected error during PR creation: {e}")
        workflow_state.update_status(WorkflowStatus.FAILED)
        raise PRCreationError(f"PR creation failed: {e}")


def generate_pr_metadata(
    issue: Issue,
    workflow_state: WorkflowState,
    config: Config,
    draft: bool = False
) -> PRMetadata:
    """
    Generate PR metadata including title, description, labels, and assignees.
    
    Args:
        issue: Issue being implemented
        workflow_state: Current workflow state
        config: Configuration
        draft: Whether PR is a draft
        
    Returns:
        PRMetadata object
    """
    # Generate PR title
    pr_title = generate_pr_title(issue, config)
    
    # Generate PR description
    pr_description = generate_pr_description(issue, workflow_state, config)
    
    # Determine labels
    labels = determine_pr_labels(issue, workflow_state)
    
    # Determine assignees and reviewers
    assignees = determine_pr_assignees(issue, config)
    reviewers = determine_pr_reviewers(issue, config)
    
    return PRMetadata(
        title=pr_title,
        description=pr_description,
        labels=labels,
        assignees=assignees,
        reviewers=reviewers,
        draft=draft,
        base_branch=config.github.default_branch if hasattr(config.github, 'default_branch') else "main"
    )


def generate_pr_title(issue: Issue, config: Config) -> str:
    """
    Generate PR title from issue.
    
    Args:
        issue: Issue being implemented
        config: Configuration
        
    Returns:
        Generated PR title
    """
    # Use issue title directly, optionally with prefix
    title = issue.title
    
    # Add issue type prefix if available
    if issue.issue_type:
        type_prefix = {
            "feature": "feat:",
            "bug": "fix:",
            "enhancement": "enhance:",
            "hotfix": "hotfix:",
            "task": "task:"
        }.get(issue.issue_type.value.lower(), "")
        
        if type_prefix:
            title = f"{type_prefix} {title}"
    
    return title


def generate_pr_description(
    issue: Issue,
    workflow_state: WorkflowState,
    config: Config
) -> str:
    """
    Generate PR description combining issue context, implementation summary,
    and template formatting.
    
    Args:
        issue: Issue being implemented
        workflow_state: Current workflow state
        config: Configuration
        
    Returns:
        Generated PR description
    """
    description_parts = []
    
    # Load and apply PR template if available
    template_content = load_pr_template(config)
    if template_content:
        description_parts.append(template_content)
    
    # Add issue information
    description_parts.append(f"## Related Issue")
    description_parts.append(f"Closes {issue.id}")
    description_parts.append("")
    
    # Add issue description if significant
    if issue.description and len(issue.description.strip()) > 20:
        description_parts.append(f"## Issue Description")
        description_parts.append(issue.description.strip())
        description_parts.append("")
    
    # Add implementation summary
    if workflow_state.ai_response:
        description_parts.append(f"## Implementation Summary")
        
        # Add AI implementation details
        if workflow_state.ai_response.content:
            description_parts.append(workflow_state.ai_response.content)
            description_parts.append("")
        
        # Add file changes summary
        if workflow_state.ai_response.file_changes:
            description_parts.append(f"### Files Changed")
            for change in workflow_state.ai_response.file_changes:
                action = change.get('action', 'modified')
                path = change.get('path', 'unknown')
                description_parts.append(f"- {action.title()}: `{path}`")
            description_parts.append("")
        
        # Add commands run
        if workflow_state.ai_response.commands:
            description_parts.append(f"### Commands Executed")
            for command in workflow_state.ai_response.commands:
                description_parts.append(f"- `{command}`")
            description_parts.append("")
    
    # Add testing information
    description_parts.append(f"## Testing")
    description_parts.append(f"- [ ] All tests pass")
    description_parts.append(f"- [ ] Manual testing completed")
    
    if config.workflows.test_command:
        description_parts.append(f"- [ ] Automated tests: `{config.workflows.test_command}`")
    
    description_parts.append("")
    
    # Add checklist
    description_parts.append(f"## Review Checklist")
    description_parts.append(f"- [ ] Code follows project conventions")
    description_parts.append(f"- [ ] Tests are comprehensive")
    description_parts.append(f"- [ ] Documentation is updated")
    description_parts.append(f"- [ ] No breaking changes (or properly documented)")
    
    return "\n".join(description_parts)


def load_pr_template(config: Config) -> Optional[str]:
    """
    Load PR template from configured path.
    
    Args:
        config: Configuration
        
    Returns:
        Template content or None if not found
    """
    template_path = Path(config.github.pr_template)
    
    if template_path.exists():
        try:
            content = template_path.read_text(encoding='utf-8')
            logger.debug(f"Loaded PR template from {template_path}")
            return content
        except Exception as e:
            logger.warning(f"Failed to load PR template from {template_path}: {e}")
    
    return None


def determine_pr_labels(issue: Issue, workflow_state: WorkflowState) -> List[str]:
    """
    Determine appropriate labels for the PR.
    
    Args:
        issue: Issue being implemented
        workflow_state: Current workflow state
        
    Returns:
        List of label names
    """
    labels = []
    
    # Add issue labels
    if issue.labels:
        labels.extend(issue.labels)
    
    # Add implementation-specific labels
    if workflow_state.ai_response:
        # Add AI-implemented label
        labels.append("ai-implemented")
        
        # Add labels based on file changes
        file_changes = workflow_state.ai_response.file_changes
        if file_changes:
            # Check for test files
            test_files = [f for f in file_changes if any(test_pattern in f.get('path', '') 
                         for test_pattern in ['test', 'spec', '__test__'])]
            if test_files:
                labels.append("tests")
            
            # Check for documentation files
            doc_files = [f for f in file_changes if any(doc_pattern in f.get('path', '') 
                        for doc_pattern in ['README', 'docs/', '.md'])]
            if doc_files:
                labels.append("documentation")
    
    # Remove duplicates while preserving order
    return list(dict.fromkeys(labels))


def determine_pr_assignees(issue: Issue, config: Config) -> List[str]:
    """
    Determine PR assignees.
    
    Args:
        issue: Issue being implemented
        config: Configuration
        
    Returns:
        List of assignee usernames
    """
    assignees = []
    
    # Add issue assignee
    if issue.assignee:
        assignees.append(issue.assignee)
    
    return assignees


def determine_pr_reviewers(issue: Issue, config: Config) -> List[str]:
    """
    Determine PR reviewers.
    
    Args:
        issue: Issue being implemented
        config: Configuration
        
    Returns:
        List of reviewer usernames
    """
    reviewers = []
    
    # Add default reviewer from config
    if config.github.default_reviewer:
        reviewers.append(config.github.default_reviewer)
    
    return reviewers


async def commit_implementation_changes(
    issue: Issue,
    workflow_state: WorkflowState,
    config: Config
) -> None:
    """
    Commit implementation changes with appropriate commit message.
    
    Args:
        issue: Issue being implemented
        workflow_state: Current workflow state
        config: Configuration
        
    Raises:
        PRCreationError: If commit fails
    """
    logger.info("Committing implementation changes")
    
    try:
        # Generate commit message
        commit_message = generate_commit_message(issue, workflow_state, config)
        
        # Stage all changes
        result = subprocess.run(
            ["git", "add", "."],
            cwd=workflow_state.worktree,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            raise PRCreationError(f"Failed to stage changes: {result.stderr}")
        
        # Commit changes
        result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=workflow_state.worktree,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            if "nothing to commit" in result.stdout:
                logger.info("No uncommitted changes to commit")
            else:
                raise PRCreationError(f"Failed to commit changes: {result.stderr}")
        else:
            logger.info(f"Successfully committed changes: {commit_message}")
    
    except subprocess.TimeoutExpired:
        raise PRCreationError("Git commit command timed out")
    except subprocess.SubprocessError as e:
        raise PRCreationError(f"Git commit command failed: {e}")


def generate_commit_message(
    issue: Issue,
    workflow_state: WorkflowState,
    config: Config
) -> str:
    """
    Generate commit message for implementation.
    
    Args:
        issue: Issue being implemented
        workflow_state: Current workflow state
        config: Configuration
        
    Returns:
        Generated commit message
    """
    template = config.workflows.implementation_commit_message
    
    try:
        return template.format(
            issue_id=issue.id,
            issue_title=issue.title,
            issue_type=issue.issue_type.value if issue.issue_type else "task"
        )
    except (KeyError, AttributeError):
        # Fallback to simple message
        return f"Implement {issue.id}: {issue.title}"


async def push_branch_to_remote(workflow_state: WorkflowState) -> None:
    """
    Push branch to remote repository.
    
    Args:
        workflow_state: Current workflow state
        
    Raises:
        PRCreationError: If push fails
    """
    logger.info(f"Pushing branch {workflow_state.branch} to remote")
    
    try:
        # Push branch with upstream tracking
        result = subprocess.run(
            ["git", "push", "-u", "origin", workflow_state.branch],
            cwd=workflow_state.worktree,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            raise PRCreationError(f"Failed to push branch: {result.stderr}")
        
        logger.info(f"Successfully pushed branch {workflow_state.branch}")
    
    except subprocess.TimeoutExpired:
        raise PRCreationError("Git push command timed out")
    except subprocess.SubprocessError as e:
        raise PRCreationError(f"Git push command failed: {e}")


async def create_github_pr(
    github_integration: GitHubIntegration,
    pr_metadata: PRMetadata,
    workflow_state: WorkflowState
) -> PullRequest:
    """
    Create GitHub PR using the GitHub integration.
    
    Args:
        github_integration: GitHub integration instance
        pr_metadata: PR metadata
        workflow_state: Current workflow state
        
    Returns:
        Created PullRequest object
        
    Raises:
        PRCreationError: If PR creation fails
    """
    logger.info(f"Creating GitHub PR: {pr_metadata.title}")
    
    try:
        # Create PR via GitHub integration
        pr = await github_integration.create_pull_request(
            title=pr_metadata.title,
            description=pr_metadata.description,
            head_branch=workflow_state.branch,
            base_branch=pr_metadata.base_branch,
            draft=pr_metadata.draft
        )
        
        # Add labels if specified
        if pr_metadata.labels:
            await github_integration.add_pr_labels(pr.number, pr_metadata.labels)
        
        # Add assignees if specified
        if pr_metadata.assignees:
            await github_integration.add_pr_assignees(pr.number, pr_metadata.assignees)
        
        # Request reviewers if specified
        if pr_metadata.reviewers:
            await github_integration.request_pr_reviewers(pr.number, pr_metadata.reviewers)
        
        logger.info(f"Successfully created PR #{pr.number}")
        return pr
    
    except Exception as e:
        raise PRCreationError(f"Failed to create GitHub PR: {e}")


def validate_pr_prerequisites(workflow_state: WorkflowState) -> None:
    """
    Validate prerequisites for PR creation.
    
    Args:
        workflow_state: Current workflow state
        
    Raises:
        PRCreationError: If prerequisites are not met
    """
    if not workflow_state.worktree:
        raise PRCreationError("No worktree available for PR creation")
    
    worktree_path = Path(workflow_state.worktree)
    if not worktree_path.exists():
        raise PRCreationError(f"Worktree does not exist: {workflow_state.worktree}")
    
    if not workflow_state.branch:
        raise PRCreationError("No branch specified for PR creation")
    
    # Check if worktree is a git repository
    git_dir = worktree_path / ".git"
    if not git_dir.exists():
        raise PRCreationError(f"Worktree is not a git repository: {workflow_state.worktree}")


def has_uncommitted_changes(worktree_path: str) -> bool:
    """
    Check if worktree has uncommitted changes.
    
    Args:
        worktree_path: Path to worktree
        
    Returns:
        True if there are uncommitted changes
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        return bool(result.stdout.strip())
    
    except (subprocess.SubprocessError, subprocess.TimeoutExpired):
        logger.warning(f"Failed to check git status in {worktree_path}")
        return False


def has_implementation_commits(worktree_path: str, branch: str) -> bool:
    """
    Check if there are implementation commits on the branch.
    
    Args:
        worktree_path: Path to worktree
        branch: Branch name
        
    Returns:
        True if there are commits on the branch
    """
    try:
        # Check if branch has commits ahead of main
        result = subprocess.run(
            ["git", "rev-list", "--count", f"main..{branch}"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            commit_count = int(result.stdout.strip())
            return commit_count > 0
        
        return False
    
    except (subprocess.SubprocessError, subprocess.TimeoutExpired, ValueError):
        logger.warning(f"Failed to check commit count in {worktree_path}")
        return False


def get_pr_creation_summary(workflow_state: WorkflowState) -> str:
    """
    Get human-readable summary of PR creation status.
    
    Args:
        workflow_state: Current workflow state
        
    Returns:
        Summary string
    """
    if not workflow_state.pr_number:
        return "PR not created yet"
    
    summary_parts = [f"PR #{workflow_state.pr_number} created"]
    
    if workflow_state.pr_metadata:
        if workflow_state.pr_metadata.draft:
            summary_parts.append("(draft)")
        
        if workflow_state.pr_metadata.labels:
            label_count = len(workflow_state.pr_metadata.labels)
            summary_parts.append(f"with {label_count} labels")
        
        if workflow_state.pr_metadata.reviewers:
            reviewer_count = len(workflow_state.pr_metadata.reviewers)
            summary_parts.append(f"and {reviewer_count} reviewers")
    
    return " ".join(summary_parts)