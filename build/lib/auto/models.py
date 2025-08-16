"""Data models for the auto tool."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class IssueProvider(str, Enum):
    """Supported issue providers."""
    
    GITHUB = "github"
    LINEAR = "linear"


class IssueType(str, Enum):
    """Issue types for branch naming."""
    
    FEATURE = "feature"
    BUG = "bug"
    ENHANCEMENT = "enhancement"
    TASK = "task"
    HOTFIX = "hotfix"


class IssueStatus(str, Enum):
    """Issue status values."""
    
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class PRStatus(str, Enum):
    """Pull request status values."""
    
    DRAFT = "draft"
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class ReviewType(str, Enum):
    """Review types in the review cycle."""
    
    AI = "ai"
    HUMAN = "human"
    AI_UPDATE = "ai_update"


class ReviewStatus(str, Enum):
    """Review status values."""
    
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMMENTS_POSTED = "comments_posted"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    COMPLETED = "completed"


class WorkflowStatus(str, Enum):
    """Overall workflow status."""
    
    INITIALIZED = "initialized"
    FETCHING = "fetching"
    IMPLEMENTING = "implementing"
    CREATING_PR = "creating_pr"
    IN_REVIEW = "in_review"
    UPDATING = "updating"
    READY_TO_MERGE = "ready_to_merge"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"


class Issue(BaseModel):
    """Issue model for GitHub and Linear issues."""
    
    id: str = Field(description="Issue ID (e.g., '#123', 'ENG-456')")
    provider: IssueProvider = Field(description="Issue provider")
    title: str = Field(description="Issue title")
    description: str = Field(description="Issue description/body")
    status: IssueStatus = Field(description="Issue status")
    issue_type: Optional[IssueType] = Field(default=None, description="Issue type")
    assignee: Optional[str] = Field(default=None, description="Assigned user")
    labels: List[str] = Field(default_factory=list, description="Issue labels")
    url: Optional[str] = Field(default=None, description="Issue URL")
    created_at: Optional[datetime] = Field(default=None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(default=None, description="Last update timestamp")
    
    @model_validator(mode="before")
    @classmethod
    def infer_issue_type(cls, data: Any) -> Any:
        """Infer issue type from labels or title if not provided."""
        if not isinstance(data, dict):
            return data
            
        if data.get("issue_type") is not None:
            return data
        
        labels = data.get("labels", [])
        title = data.get("title", "").lower()
        
        # Check labels first
        for label in labels:
            label_lower = label.lower()
            if label_lower in ["bug", "bugfix"]:
                data["issue_type"] = IssueType.BUG
                return data
            elif label_lower in ["enhancement", "improvement"]:
                data["issue_type"] = IssueType.ENHANCEMENT
                return data
            elif label_lower in ["feature", "new-feature"]:
                data["issue_type"] = IssueType.FEATURE
                return data
            elif label_lower in ["hotfix", "urgent"]:
                data["issue_type"] = IssueType.HOTFIX
                return data
        
        # Check title keywords
        if any(word in title for word in ["bug", "fix", "broken"]):
            data["issue_type"] = IssueType.BUG
        elif any(word in title for word in ["feature", "add", "new"]):
            data["issue_type"] = IssueType.FEATURE
        elif any(word in title for word in ["enhance", "improve", "optimize"]):
            data["issue_type"] = IssueType.ENHANCEMENT
        elif any(word in title for word in ["hotfix", "urgent", "critical"]):
            data["issue_type"] = IssueType.HOTFIX
        else:
            data["issue_type"] = IssueType.TASK
        
        return data


class PullRequest(BaseModel):
    """Pull request model."""
    
    number: int = Field(description="PR number")
    title: str = Field(description="PR title")
    description: str = Field(description="PR description/body")
    status: PRStatus = Field(description="PR status")
    branch: str = Field(description="Branch name")
    base_branch: str = Field(default="main", description="Base branch")
    author: Optional[str] = Field(default=None, description="PR author")
    assignee: Optional[str] = Field(default=None, description="Assigned reviewer")
    url: Optional[str] = Field(default=None, description="PR URL")
    created_at: Optional[datetime] = Field(default=None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(default=None, description="Last update timestamp")


class Review(BaseModel):
    """Review model for tracking review cycles."""
    
    type: ReviewType = Field(description="Type of review")
    reviewer: Optional[str] = Field(default=None, description="Reviewer (for human reviews)")
    status: ReviewStatus = Field(description="Review status")
    timestamp: datetime = Field(default_factory=datetime.now, description="Review timestamp")
    comments: List[str] = Field(default_factory=list, description="Review comments")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class WorkflowState(BaseModel):
    """State model for tracking workflow progress."""
    
    pr_number: Optional[int] = Field(default=None, description="PR number")
    issue_id: str = Field(description="Issue ID")
    branch: Optional[str] = Field(default=None, description="Branch name")
    worktree: Optional[str] = Field(default=None, description="Worktree path")
    status: WorkflowStatus = Field(description="Current workflow status")
    review_iteration: int = Field(default=0, description="Current review iteration")
    reviews: List[Review] = Field(default_factory=list, description="Review history")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update timestamp")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    def update_status(self, status: WorkflowStatus) -> None:
        """Update workflow status and timestamp."""
        self.status = status
        self.updated_at = datetime.now()
    
    def add_review(self, review: Review) -> None:
        """Add a review to the workflow."""
        self.reviews.append(review)
        self.updated_at = datetime.now()


class DefaultsConfig(BaseModel):
    """Default configuration settings."""
    
    auto_merge: bool = Field(default=False, description="Auto-merge PRs after approval")
    delete_branch_on_merge: bool = Field(default=True, description="Delete branch after merge")
    worktree_base: str = Field(default="../{project}-worktrees", description="Worktree base path")
    max_review_iterations: int = Field(default=10, description="Max review iterations")


class GitHubConfig(BaseModel):
    """GitHub configuration settings."""
    
    default_org: Optional[str] = Field(default=None, description="Default GitHub organization")
    default_reviewer: Optional[str] = Field(default=None, description="Default reviewer")
    pr_template: str = Field(default=".github/pull_request_template.md", description="PR template path")
    token: Optional[str] = Field(default=None, description="GitHub token")


class LinearConfig(BaseModel):
    """Linear configuration settings."""
    
    api_key: Optional[str] = Field(default=None, description="Linear API key")
    workspace: Optional[str] = Field(default=None, description="Linear workspace")
    auto_assign: bool = Field(default=True, description="Auto-assign issues")


class AIConfig(BaseModel):
    """AI configuration settings."""
    
    command: str = Field(default="claude", description="AI command")
    implementation_agent: str = Field(default="coder", description="Implementation agent")
    review_agent: str = Field(default="pull-request-reviewer", description="Review agent")
    update_agent: str = Field(default="coder", description="Update agent")
    implementation_prompt: str = Field(
        default="Implement the following issue: {description}",
        description="Implementation prompt template"
    )
    review_prompt: str = Field(
        default="Review this PR critically for bugs, security issues, performance, and best practices. Be thorough and specific.",
        description="Review prompt template"
    )
    update_prompt: str = Field(
        default="Address the following review comments: {comments}",
        description="Update prompt template"
    )


class WorkflowsConfig(BaseModel):
    """Workflow configuration settings."""
    
    branch_naming: str = Field(default="auto/{issue_type}/{issue_id}", description="Branch naming pattern")
    commit_convention: str = Field(default="conventional", description="Commit convention")
    ai_review_first: bool = Field(default=True, description="AI reviews before human")
    require_human_approval: bool = Field(default=True, description="Require human approval")
    test_command: Optional[str] = Field(default=None, description="Test command")
    review_check_interval: int = Field(default=60, description="Review check interval (seconds)")


class Config(BaseModel):
    """Main configuration model."""
    
    version: str = Field(default="1.0", description="Config version")
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig, description="Default settings")
    github: GitHubConfig = Field(default_factory=GitHubConfig, description="GitHub settings")
    linear: LinearConfig = Field(default_factory=LinearConfig, description="Linear settings")
    ai: AIConfig = Field(default_factory=AIConfig, description="AI settings")
    workflows: WorkflowsConfig = Field(default_factory=WorkflowsConfig, description="Workflow settings")
    
    model_config = {"extra": "allow"}  # Allow additional fields for extensibility


class IssueIdentifier(BaseModel):
    """Issue identifier parser."""
    
    raw: str = Field(description="Raw issue identifier")
    provider: IssueProvider = Field(description="Detected provider")
    issue_id: str = Field(description="Extracted issue ID")
    
    @classmethod
    def parse(cls, identifier: str) -> "IssueIdentifier":
        """Parse issue identifier and detect provider.
        
        Supported formats:
        - GitHub: #123, gh-123, https://github.com/owner/repo/issues/123
        - Linear: ENG-123, https://linear.app/workspace/issue/ENG-123
        """
        identifier = identifier.strip()
        
        # GitHub URL
        if "github.com" in identifier and "/issues/" in identifier:
            issue_id = identifier.split("/issues/")[-1].split("/")[0].split("?")[0]
            return cls(raw=identifier, provider=IssueProvider.GITHUB, issue_id=f"#{issue_id}")
        
        # GitHub formats
        if identifier.startswith("#") or identifier.startswith("gh-"):
            issue_id = identifier.replace("gh-", "#").replace("#", "")
            if issue_id.isdigit():
                return cls(raw=identifier, provider=IssueProvider.GITHUB, issue_id=f"#{issue_id}")
        
        # Linear URL
        if "linear.app" in identifier and "/issue/" in identifier:
            issue_id = identifier.split("/issue/")[-1].split("/")[0].split("?")[0]
            return cls(raw=identifier, provider=IssueProvider.LINEAR, issue_id=issue_id)
        
        # Linear format (assumes format like ENG-123, PROJ-456, etc.)
        if "-" in identifier and len(identifier.split("-")) == 2:
            prefix, number = identifier.split("-", 1)
            if prefix.isalpha() and number.isdigit():
                return cls(raw=identifier, provider=IssueProvider.LINEAR, issue_id=identifier)
        
        # Default to GitHub if numeric
        if identifier.isdigit():
            return cls(raw=identifier, provider=IssueProvider.GITHUB, issue_id=f"#{identifier}")
        
        raise ValueError(f"Unable to parse issue identifier: {identifier}")