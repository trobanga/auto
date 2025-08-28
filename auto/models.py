"""Data models for the auto tool."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

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


class AIStatus(str, Enum):
    """AI implementation status values."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    FAILED = "failed"


class Issue(BaseModel):
    """Issue model for GitHub and Linear issues."""

    id: str = Field(description="Issue ID (e.g., '#123', 'ENG-456')")
    provider: IssueProvider = Field(description="Issue provider")
    title: str = Field(description="Issue title")
    description: str = Field(description="Issue description/body")
    status: IssueStatus = Field(description="Issue status")
    issue_type: IssueType | None = Field(default=None, description="Issue type")
    assignee: str | None = Field(default=None, description="Assigned user")
    labels: list[str] = Field(default_factory=list, description="Issue labels")
    url: str | None = Field(default=None, description="Issue URL")
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")

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
    author: str | None = Field(default=None, description="PR author")
    assignee: str | None = Field(default=None, description="Assigned reviewer")
    url: str | None = Field(default=None, description="PR URL")
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")


class GitHubRepository(BaseModel):
    """GitHub repository context model."""

    owner: str = Field(description="Repository owner")
    name: str = Field(description="Repository name")
    default_branch: str = Field(default="main", description="Default branch")
    remote_url: str | None = Field(default=None, description="Remote URL")

    @property
    def full_name(self) -> str:
        """Get full repository name (owner/name)."""
        return f"{self.owner}/{self.name}"

    @property
    def github_url(self) -> str:
        """Get GitHub URL for the repository."""
        return f"https://github.com/{self.owner}/{self.name}"


class WorktreeInfo(BaseModel):
    """Worktree information model."""

    path: str = Field(description="Worktree path")
    branch: str = Field(description="Branch name")
    issue_id: str = Field(description="Associated issue ID")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @property
    def path_obj(self) -> Path:
        """Get Path object for worktree path."""
        return Path(self.path)

    def exists(self) -> bool:
        """Check if worktree path exists."""
        return self.path_obj.exists()


class ReviewComment(BaseModel):
    """Individual review comment model."""

    id: int = Field(description="Comment ID")
    body: str = Field(description="Comment body text")
    path: str | None = Field(default=None, description="File path for line comments")
    line: int | None = Field(default=None, description="Line number for line comments")
    start_line: int | None = Field(default=None, description="Start line for multi-line comments")
    side: str = Field(default="RIGHT", description="Side of diff (LEFT/RIGHT)")
    author: str | None = Field(default=None, description="Comment author")
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")
    resolved: bool = Field(default=False, description="Whether comment is resolved")


class GitHubPRReview(BaseModel):
    """GitHub PR review model."""

    id: int = Field(description="Review ID")
    state: str = Field(description="Review state (COMMENTED, APPROVED, CHANGES_REQUESTED)")
    body: str = Field(description="Review body text")
    author: str | None = Field(default=None, description="Review author")
    submitted_at: datetime | None = Field(default=None, description="Submission timestamp")
    comments: list[ReviewComment] = Field(default_factory=list, description="Review comments")


class Review(BaseModel):
    """Review model for tracking review cycles."""

    type: ReviewType = Field(description="Type of review")
    reviewer: str | None = Field(default=None, description="Reviewer (for human reviews)")
    status: ReviewStatus = Field(description="Review status")
    timestamp: datetime = Field(default_factory=datetime.now, description="Review timestamp")
    comments: list[str] = Field(default_factory=list, description="Review comments")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    github_review: GitHubPRReview | None = Field(
        default=None, description="Associated GitHub review"
    )


class AIFileChange(BaseModel):
    """AI suggested file change."""

    path: str = Field(description="File path")
    action: str = Field(description="Action: create, modify, delete")
    content: str | None = Field(default=None, description="File content for create/modify")
    description: str | None = Field(default=None, description="Change description")


class AICommand(BaseModel):
    """AI suggested command to run."""

    command: str = Field(description="Command to execute")
    description: str | None = Field(default=None, description="Command description")
    working_directory: str | None = Field(default=None, description="Working directory")


class AIResponse(BaseModel):
    """AI response model for structured parsing."""

    success: bool = Field(description="Whether AI implementation was successful")
    response_type: str = Field(description="Type of response: implementation, review, update")
    content: str = Field(description="Main response content")
    file_changes: list[dict[str, str]] = Field(
        default_factory=list, description="Suggested file changes"
    )
    commands: list[str] = Field(default_factory=list, description="Commands to run")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    # Optional fields for review responses
    comments: list[str] | None = Field(
        default=None, description="Review comments (for review responses)"
    )
    summary: str | None = Field(default=None, description="Review summary (for review responses)")


class PRMetadata(BaseModel):
    """Pull request metadata model."""

    title: str = Field(description="PR title")
    description: str = Field(description="PR description")
    labels: list[str] = Field(default_factory=list, description="PR labels")
    assignees: list[str] = Field(default_factory=list, description="PR assignees")
    reviewers: list[str] = Field(default_factory=list, description="PR reviewers")
    draft: bool = Field(default=False, description="Whether PR is a draft")
    base_branch: str = Field(default="main", description="Base branch for PR")


class WorkflowState(BaseModel):
    """State model for tracking workflow progress."""

    pr_number: int | None = Field(default=None, description="PR number")
    issue_id: str = Field(description="Issue ID")
    branch: str | None = Field(default=None, description="Branch name")
    worktree: str | None = Field(default=None, description="Worktree path")
    worktree_info: WorktreeInfo | None = Field(default=None, description="Worktree details")
    repository: GitHubRepository | None = Field(default=None, description="Repository context")
    issue: Issue | None = Field(default=None, description="Issue details")
    status: WorkflowStatus = Field(description="Current workflow status")
    ai_status: AIStatus = Field(
        default=AIStatus.NOT_STARTED, description="AI implementation status"
    )
    ai_response: AIResponse | None = Field(default=None, description="AI implementation response")
    pr_metadata: PRMetadata | None = Field(default=None, description="PR metadata")
    review_iteration: int = Field(default=0, description="Current review iteration")
    reviews: list[Review] = Field(default_factory=list, description="Review history")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    def update_status(self, status: WorkflowStatus) -> None:
        """Update workflow status and timestamp."""
        self.status = status
        self.updated_at = datetime.now()

    def update_ai_status(self, ai_status: AIStatus, ai_response: AIResponse | None = None) -> None:
        """Update AI implementation status and timestamp."""
        self.ai_status = ai_status
        if ai_response:
            self.ai_response = ai_response
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

    default_org: str | None = Field(default=None, description="Default GitHub organization")
    default_reviewer: str | None = Field(default=None, description="Default reviewer")
    pr_template: str = Field(
        default=".github/pull_request_template.md", description="PR template path"
    )
    token: str | None = Field(default=None, description="GitHub token (optional with gh CLI)")
    base_branch_detection: bool = Field(default=True, description="Auto-detect main/master branch")
    issue_fetch_timeout: int = Field(default=30, description="Timeout for issue fetching (seconds)")
    required_approvals: int = Field(default=1, description="Required number of approvals for merge")
    required_reviewers: list[str] = Field(
        default_factory=list, description="List of required reviewer usernames"
    )

    # Status check configuration
    status_check_retries: int = Field(default=3, description="Retries for status check failures")
    status_check_interval: int = Field(
        default=30, description="Interval between status check polls (seconds)"
    )

    @field_validator("status_check_retries")
    @classmethod
    def validate_status_check_retries(cls, v: int) -> int:
        """Validate status check retries is reasonable."""
        if v < 0:
            raise ValueError("Status check retries cannot be negative") from None
        if v > 10:
            raise ValueError("Status check retries cannot exceed 10")
        return v

    @field_validator("status_check_interval")
    @classmethod
    def validate_status_check_interval(cls, v: int) -> int:
        """Validate status check interval is reasonable."""
        if v < 5:
            raise ValueError("Status check interval must be at least 5 seconds") from None
        if v > 300:
            raise ValueError("Status check interval cannot exceed 5 minutes")
        return v


class LinearConfig(BaseModel):
    """Linear configuration settings."""

    api_key: str | None = Field(default=None, description="Linear API key")
    workspace: str | None = Field(default=None, description="Linear workspace")
    auto_assign: bool = Field(default=True, description="Auto-assign issues")


class AIConfig(BaseModel):
    """AI configuration settings."""

    command: str = Field(default="claude", description="AI command")
    command_format: str = Field(
        default="claude", description="AI command format (claude|openai|ollama|custom)"
    )
    implementation_agent: str = Field(default="coder", description="Implementation agent")
    review_agent: str = Field(default="pull-request-reviewer", description="Review agent")
    update_agent: str = Field(default="coder", description="Update agent")
    implementation_prompt: str = Field(
        default="Implement the following issue: {description}",
        description="Implementation prompt template",
    )
    review_prompt: str = Field(
        default="Review this PR critically for bugs, security issues, performance, and best practices. Be thorough and specific.",
        description="Review prompt template",
    )
    update_prompt: str = Field(
        default="Address the following review comments: {comments}",
        description="Update prompt template",
    )
    stale_timeout: int = Field(
        default=300,
        description="AI command stale timeout - kill if no output for X seconds (0 = disabled)",
    )
    enable_activity_monitoring: bool = Field(
        default=True, description="Enable real-time activity monitoring and progress display"
    )
    enable_streaming: bool = Field(
        default=True, description="Enable real-time streaming output from AI commands"
    )
    output_format: str = Field(
        default="stream-json", description="AI output format: stream-json, text"
    )
    show_ai_output: bool = Field(
        default=False, description="Show full AI output in console (vs just activity indicators)"
    )
    max_retries: int = Field(default=2, description="Maximum retries for failed commands")
    include_file_context: bool = Field(
        default=True, description="Include relevant file content in prompts"
    )
    response_format: str = Field(default="structured", description="structured|freeform")

    # Command format support
    command_template: str | None = Field(
        default=None, description="Custom command template for 'custom' format"
    )

    # Custom prompt support
    prompt_templates_dir: str = Field(
        default="~/.auto/prompts", description="User prompt templates directory"
    )
    allow_custom_prompts: bool = Field(default=True, description="Enable custom prompt CLI options")
    default_template: str = Field(default="implementation", description="Default template name")
    prompt_variables: list[str] = Field(
        default_factory=lambda: [
            "issue_id",
            "issue_title",
            "issue_description",
            "acceptance_criteria",
            "repository",
            "branch",
            "labels",
            "assignee",
        ],
        description="Available template variables",
    )

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Validate AI command is not empty."""
        if not v or not v.strip():
            raise ValueError("AI command cannot be empty") from None
        return v.strip()

    @field_validator("command_format")
    @classmethod
    def validate_command_format(cls, v: str) -> str:
        """Validate command format."""
        valid_formats = {"claude", "openai", "ollama", "custom"}
        if v not in valid_formats:
            raise ValueError(
                f"Invalid command format: {v}. Must be one of {valid_formats}"
            ) from None
        return v

    @field_validator("stale_timeout")
    @classmethod
    def validate_stale_timeout(cls, v: int) -> int:
        """Validate stale timeout is reasonable."""
        if v < 0:
            raise ValueError("Stale timeout cannot be negative (use 0 to disable)")
        if v > 3600:
            raise ValueError("Stale timeout cannot exceed 1 hour (3600 seconds)")
        return v

    @field_validator("max_retries")
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        """Validate max retries is reasonable."""
        if v < 0:
            raise ValueError("Max retries cannot be negative") from None
        if v > 10:
            raise ValueError("Max retries cannot exceed 10") from None
        return v

    @field_validator("output_format")
    @classmethod
    def validate_output_format(cls, v: str) -> str:
        """Validate output format."""
        valid_formats = {"stream-json", "text", "json"}
        if v not in valid_formats:
            raise ValueError(
                f"Invalid output format: {v}. Must be one of {valid_formats}"
            ) from None
        return v

    @field_validator("response_format")
    @classmethod
    def validate_response_format(cls, v: str) -> str:
        """Validate response format."""
        valid_formats = {"structured", "freeform"}
        if v not in valid_formats:
            raise ValueError(
                f"Invalid response format: {v}. Must be one of {valid_formats}"
            ) from None
        return v

    @field_validator("implementation_agent", "review_agent", "update_agent")
    @classmethod
    def validate_agent_names(cls, v: str) -> str:
        """Validate agent names are not empty."""
        if not v or not v.strip():
            raise ValueError("Agent name cannot be empty") from None
        return v.strip()

    @field_validator("implementation_prompt", "review_prompt", "update_prompt")
    @classmethod
    def validate_prompts(cls, v: str) -> str:
        """Validate prompts are not empty."""
        if not v or not v.strip():
            raise ValueError("Prompt template cannot be empty") from None
        return v.strip()

    @model_validator(mode="after")
    def validate_custom_command_template(self) -> "AIConfig":
        """Validate custom command template when format is custom."""
        if self.command_format == "custom" and not self.command_template:
            raise ValueError(
                "command_template is required when command_format is 'custom'"
            ) from None
        return self


class WorkflowsConfig(BaseModel):
    """Workflow configuration settings."""

    branch_naming: str = Field(default="auto/{type}/{id}", description="Branch naming pattern")
    commit_convention: str = Field(default="conventional", description="Commit convention")
    ai_review_first: bool = Field(default=True, description="AI reviews before human")
    require_human_approval: bool = Field(default=True, description="Require human approval")
    test_command: str | None = Field(default=None, description="Test command")
    review_check_interval: int = Field(default=60, description="Review check interval (seconds)")
    max_review_iterations: int = Field(default=10, description="Maximum review iterations")
    worktree_cleanup_on_merge: bool = Field(
        default=True, description="Auto-cleanup merged worktrees"
    )
    worktree_conflict_resolution: str = Field(default="prompt", description="prompt|force|skip")
    auto_create_pr: bool = Field(default=True, description="Auto-create PR after implementation")
    pr_draft_mode: bool = Field(default=False, description="Create draft PRs by default")
    implementation_commit_message: str = Field(
        default="feat: implement {id} - {title}",
        description="Commit message template for implementations",
    )

    # Status check validation configuration
    wait_for_checks: bool = Field(default=True, description="Wait for pending status checks")
    check_timeout: int = Field(default=600, description="Max wait time for status checks (seconds)")
    required_status_checks: list[str] = Field(
        default_factory=list, description="Override required status checks"
    )

    @field_validator("review_check_interval")
    @classmethod
    def validate_review_check_interval(cls, v: int) -> int:
        """Validate review check interval is reasonable."""
        if v < 1:
            raise ValueError("Review check interval must be at least 1 second") from None
        if v > 3600:
            raise ValueError("Review check interval must be at most 1 hour")
        return v

    @field_validator("max_review_iterations")
    @classmethod
    def validate_max_review_iterations(cls, v: int) -> int:
        """Validate max review iterations is reasonable."""
        if v < 1:
            raise ValueError("Max review iterations must be at least 1") from None
        if v > 50:
            raise ValueError("Max review iterations must be at most 50 (to prevent infinite loops)")
        return v

    @field_validator("worktree_conflict_resolution")
    @classmethod
    def validate_conflict_resolution(cls, v: str) -> str:
        """Validate conflict resolution strategy."""
        valid_strategies = {"prompt", "force", "skip"}
        if v not in valid_strategies:
            raise ValueError(
                f"Invalid conflict resolution strategy: {v}. Must be one of {valid_strategies}"
            )
        return v

    @field_validator("branch_naming")
    @classmethod
    def validate_branch_naming(cls, v: str) -> str:
        """Validate branch naming pattern."""
        if not v or not isinstance(v, str):
            raise ValueError("Branch naming pattern cannot be empty") from None

        # Check for required placeholders
        required_placeholders = ["{id}"]
        for placeholder in required_placeholders:
            if placeholder not in v:
                raise ValueError(f"Branch naming pattern must contain {placeholder}") from None

        # Check for invalid characters
        invalid_chars = [":", "~", "^", "?", "*", "[", "\\", " "]
        for char in invalid_chars:
            if char in v:
                raise ValueError(
                    f"Branch naming pattern contains invalid character: '{char}'"
                ) from None

        return v

    @field_validator("commit_convention")
    @classmethod
    def validate_commit_convention(cls, v: str) -> str:
        """Validate commit convention."""
        valid_conventions = {"conventional", "angular", "gitmoji", "custom"}
        if v not in valid_conventions:
            raise ValueError(
                f"Invalid commit convention: {v}. Must be one of {valid_conventions}"
            ) from None
        return v

    @field_validator("check_timeout")
    @classmethod
    def validate_check_timeout(cls, v: int) -> int:
        """Validate check timeout is reasonable."""
        if v < 0:
            raise ValueError("Check timeout cannot be negative") from None
        if v > 7200:  # 2 hours max
            raise ValueError("Check timeout cannot exceed 2 hours")
        return v


class Config(BaseModel):
    """Main configuration model."""

    version: str = Field(default="1.0", description="Config version")
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig, description="Default settings")
    github: GitHubConfig = Field(default_factory=GitHubConfig, description="GitHub settings")
    linear: LinearConfig = Field(default_factory=LinearConfig, description="Linear settings")
    ai: AIConfig = Field(default_factory=AIConfig, description="AI settings")
    workflows: WorkflowsConfig = Field(
        default_factory=WorkflowsConfig, description="Workflow settings"
    )

    model_config = {"extra": "allow"}  # Allow additional fields for extensibility


class ValidationResult(BaseModel):
    """Result of PR review validation for merge automation."""

    success: bool = Field(description="Whether validation passed")
    message: str = Field(description="Summary message of validation result")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Detailed validation information"
    )
    actionable_items: list[str] = Field(
        default_factory=list, description="List of items that need attention"
    )


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

        raise ValueError(f"Unable to parse issue identifier: {identifier}") from None


class ConflictType(str, Enum):
    """Types of merge conflicts."""
    
    CONTENT = "content"
    RENAME = "rename"  
    DELETE = "delete"
    MODIFY_DELETE = "modify_delete"
    ADD_ADD = "add_add"
    MODE = "mode"


class ConflictComplexity(str, Enum):
    """Complexity levels for merge conflicts."""
    
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    CRITICAL = "critical"


class ConflictDetail(BaseModel):
    """Individual merge conflict details."""
    
    file_path: str = Field(description="Path to conflicted file")
    conflict_type: ConflictType = Field(description="Type of conflict")
    complexity: ConflictComplexity = Field(description="Conflict complexity level")
    description: str = Field(description="Human-readable conflict description")
    ours_content: str | None = Field(default=None, description="Our version content")
    theirs_content: str | None = Field(default=None, description="Their version content")
    ancestor_content: str | None = Field(default=None, description="Common ancestor content")
    line_numbers: list[int] = Field(default_factory=list, description="Conflicted line numbers")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional conflict metadata")


class ResolutionSuggestion(BaseModel):
    """AI-generated suggestion for conflict resolution."""
    
    file_path: str = Field(description="Path to conflicted file")
    suggested_resolution: str = Field(description="Suggested resolution approach")
    confidence: float = Field(description="AI confidence score (0.0-1.0)")
    rationale: str = Field(description="Explanation for the suggestion")
    manual_steps: list[str] = Field(default_factory=list, description="Manual steps to resolve")
    validation_steps: list[str] = Field(default_factory=list, description="Steps to validate resolution")
    alternative_approaches: list[str] = Field(default_factory=list, description="Alternative resolution strategies")
    

class ConflictResolution(BaseModel):
    """Complete merge conflict resolution analysis."""
    
    conflicts_detected: list[ConflictDetail] = Field(description="List of detected conflicts")
    resolution_suggestions: list[ResolutionSuggestion] = Field(description="AI-generated resolution suggestions")
    manual_steps: list[str] = Field(description="Overall manual resolution steps")
    ai_assistance_available: bool = Field(description="Whether AI can assist with resolution")
    estimated_resolution_time: int = Field(description="Estimated time to resolve (minutes)")
    complexity_score: float = Field(description="Overall complexity score (0.0-10.0)")
    priority_order: list[str] = Field(description="Suggested order to resolve conflicts by file path")
    conflict_summary: str = Field(description="Human-readable summary of conflicts")
    resolution_report: str = Field(description="Detailed resolution guidance report")
