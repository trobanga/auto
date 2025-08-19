"""GitHub review integration for the review cycle system."""

import json
import subprocess
from datetime import datetime
from typing import Any

from auto.models import GitHubRepository
from auto.utils.logger import get_logger
from auto.utils.shell import ShellError, run_command

logger = get_logger(__name__)


def validate_github_auth() -> bool:
    """Validate GitHub authentication for review operations."""
    try:
        # Check if gh CLI is authenticated
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
    except Exception:
        return False


class GitHubReviewError(Exception):
    """GitHub review integration error."""

    pass


class ReviewComment(dict):
    """Review comment model extending dict for JSON compatibility."""

    def __init__(
        self,
        id: int,
        body: str,
        path: str | None = None,
        line: int | None = None,
        start_line: int | None = None,
        side: str = "RIGHT",
        author: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        resolved: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.id = id
        self.body = body
        self.path = path
        self.line = line
        self.start_line = start_line
        self.side = side
        self.author = author
        self.created_at = created_at
        self.updated_at = updated_at
        self.resolved = resolved

        # Store in dict for JSON serialization
        self.update(
            {
                "id": id,
                "body": body,
                "path": path,
                "line": line,
                "start_line": start_line,
                "side": side,
                "author": author,
                "created_at": created_at.isoformat() if created_at else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "resolved": resolved,
            }
        )


class PRReview(dict):
    """PR review model extending dict for JSON compatibility."""

    def __init__(
        self,
        id: int,
        state: str,
        body: str,
        author: str | None = None,
        submitted_at: datetime | None = None,
        comments: list[ReviewComment] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.id = id
        self.state = state
        self.body = body
        self.author = author
        self.submitted_at = submitted_at
        self.comments = comments or []

        # Store in dict for JSON serialization
        self.update(
            {
                "id": id,
                "state": state,
                "body": body,
                "author": author,
                "submitted_at": submitted_at.isoformat() if submitted_at else None,
                "comments": [dict(comment) for comment in self.comments],
            }
        )


class GitHubReviewIntegration:
    """GitHub review integration using gh CLI."""

    def __init__(self) -> None:
        """Initialize GitHub review integration with authentication validation."""
        from auto.integrations.github import GitHubAuthError, validate_github_auth

        if not validate_github_auth():
            raise GitHubAuthError(
                "GitHub CLI authentication required. Run 'gh auth login' to authenticate."
            )

    def get_pr_reviews(
        self, pr_number: int, repository: GitHubRepository | None = None
    ) -> list[PRReview]:
        """Fetch all reviews for a PR with pagination.

        Args:
            pr_number: Pull request number
            repository: Repository context (auto-detected if None)

        Returns:
            List of PR reviews

        Raises:
            GitHubReviewError: If reviews cannot be fetched
        """
        if repository is None:
            from auto.integrations.github import GitHubIntegration

            github = GitHubIntegration()
            repository = github.detect_repository()

        try:
            # Fetch reviews using gh CLI
            result = run_command(
                f"gh pr view {pr_number} --repo {repository.full_name} --json reviews",
                check=True,
                timeout=30,
            )

            pr_data = json.loads(result.stdout)
            reviews_data = pr_data.get("reviews", [])

            reviews = []
            for review_data in reviews_data:
                # Parse submitted_at timestamp
                submitted_at = None
                if review_data.get("submittedAt"):
                    submitted_at = datetime.fromisoformat(
                        review_data["submittedAt"].replace("Z", "+00:00")
                    )

                # Get author
                author = None
                if review_data.get("author"):
                    author = review_data["author"].get("login")

                review = PRReview(
                    id=review_data["id"],
                    state=review_data["state"],
                    body=review_data.get("body", ""),
                    author=author,
                    submitted_at=submitted_at,
                )
                reviews.append(review)

            return reviews

        except ShellError as e:
            raise GitHubReviewError(f"Failed to fetch PR reviews: {e.stderr}") from e
        except json.JSONDecodeError as e:
            raise GitHubReviewError(f"Failed to parse review data: {e}") from e

    def get_review_comments(
        self, pr_number: int, repository: GitHubRepository | None = None
    ) -> list[ReviewComment]:
        """Retrieve review comments with thread context.

        Args:
            pr_number: Pull request number
            repository: Repository context (auto-detected if None)

        Returns:
            List of review comments

        Raises:
            GitHubReviewError: If comments cannot be fetched
        """
        if repository is None:
            from auto.integrations.github import GitHubIntegration

            github = GitHubIntegration()
            repository = github.detect_repository()

        try:
            # Fetch review comments using gh API
            result = run_command(
                f"gh api repos/{repository.full_name}/pulls/{pr_number}/comments",
                check=True,
                timeout=30,
            )

            comments_data = json.loads(result.stdout)

            comments = []
            for comment_data in comments_data:
                # Parse timestamps
                created_at = None
                updated_at = None
                if comment_data.get("created_at"):
                    created_at = datetime.fromisoformat(
                        comment_data["created_at"].replace("Z", "+00:00")
                    )
                if comment_data.get("updated_at"):
                    updated_at = datetime.fromisoformat(
                        comment_data["updated_at"].replace("Z", "+00:00")
                    )

                # Get author
                author = None
                if comment_data.get("user"):
                    author = comment_data["user"].get("login")

                comment = ReviewComment(
                    id=comment_data["id"],
                    body=comment_data["body"],
                    path=comment_data.get("path"),
                    line=comment_data.get("line"),
                    start_line=comment_data.get("start_line"),
                    side=comment_data.get("side", "RIGHT"),
                    author=author,
                    created_at=created_at,
                    updated_at=updated_at,
                    resolved=comment_data.get("resolved", False),
                )
                comments.append(comment)

            return comments

        except ShellError as e:
            raise GitHubReviewError(f"Failed to fetch review comments: {e.stderr}") from e
        except json.JSONDecodeError as e:
            raise GitHubReviewError(f"Failed to parse comments data: {e}") from e

    def post_ai_review(
        self,
        pr_number: int,
        review_body: str,
        comments: list[dict[str, Any]] | None = None,
        repository: GitHubRepository | None = None,
        event: str = "COMMENT",
    ) -> PRReview:
        """Submit AI-generated review with organized comments.

        Args:
            pr_number: Pull request number
            review_body: Main review body text
            comments: List of line-specific comments
            repository: Repository context (auto-detected if None)
            event: Review event type (COMMENT, APPROVE, REQUEST_CHANGES)

        Returns:
            Created review object

        Raises:
            GitHubReviewError: If review cannot be posted
        """
        if repository is None:
            from auto.integrations.github import GitHubIntegration

            github = GitHubIntegration()
            repository = github.detect_repository()

        try:
            # Build review data
            review_data: dict[str, Any] = {"body": review_body, "event": event}

            # Add comments if provided
            if comments:
                review_data["comments"] = comments

            # Post review using gh API
            result = run_command(
                f"gh api repos/{repository.full_name}/pulls/{pr_number}/reviews "
                f"--method POST --input -",
                input_data=json.dumps(review_data),
                check=True,
                timeout=30,
            )

            review_response = json.loads(result.stdout)

            # Parse response
            submitted_at = None
            if review_response.get("submitted_at"):
                submitted_at = datetime.fromisoformat(
                    review_response["submitted_at"].replace("Z", "+00:00")
                )

            author = None
            if review_response.get("user"):
                author = review_response["user"].get("login")

            return PRReview(
                id=review_response["id"],
                state=review_response["state"],
                body=review_response.get("body", ""),
                author=author,
                submitted_at=submitted_at,
            )

        except ShellError as e:
            raise GitHubReviewError(f"Failed to post AI review: {e.stderr}") from e
        except json.JSONDecodeError as e:
            raise GitHubReviewError(f"Failed to parse review response: {e}") from e

    def check_approval_status(
        self, pr_number: int, repository: GitHubRepository | None = None
    ) -> tuple[bool, list[str], list[str]]:
        """Monitor PR approval status and merge eligibility.

        Args:
            pr_number: Pull request number
            repository: Repository context (auto-detected if None)

        Returns:
            Tuple of (is_approved, approving_reviewers, requesting_changes_reviewers)

        Raises:
            GitHubReviewError: If status cannot be checked
        """
        if repository is None:
            from auto.integrations.github import GitHubIntegration

            github = GitHubIntegration()
            repository = github.detect_repository()

        try:
            # Get PR reviews and check status
            reviews = self.get_pr_reviews(pr_number, repository)

            # Track latest review state per reviewer
            reviewer_states = {}
            for review in reviews:
                if review.author:
                    reviewer_states[review.author] = review.state

            # Categorize reviewers
            approving_reviewers = []
            requesting_changes_reviewers = []

            for reviewer, state in reviewer_states.items():
                if state == "APPROVED":
                    approving_reviewers.append(reviewer)
                elif state == "CHANGES_REQUESTED":
                    requesting_changes_reviewers.append(reviewer)

            # PR is approved if there are approvers and no one requesting changes
            is_approved = len(approving_reviewers) > 0 and len(requesting_changes_reviewers) == 0

            return is_approved, approving_reviewers, requesting_changes_reviewers

        except Exception as e:
            raise GitHubReviewError(f"Failed to check approval status: {e}") from e

    def get_unresolved_comments(
        self, pr_number: int, repository: GitHubRepository | None = None
    ) -> list[ReviewComment]:
        """Filter unresolved review comments.

        Args:
            pr_number: Pull request number
            repository: Repository context (auto-detected if None)

        Returns:
            List of unresolved review comments

        Raises:
            GitHubReviewError: If comments cannot be fetched
        """
        try:
            comments = self.get_review_comments(pr_number, repository)
            return [comment for comment in comments if not comment.resolved]

        except Exception as e:
            raise GitHubReviewError(f"Failed to get unresolved comments: {e}") from e

    def update_pr_description(
        self, pr_number: int, description: str, repository: GitHubRepository | None = None
    ) -> None:
        """Update PR description with review cycle metadata.

        Args:
            pr_number: Pull request number
            description: New PR description
            repository: Repository context (auto-detected if None)

        Raises:
            GitHubReviewError: If description cannot be updated
        """
        if repository is None:
            from auto.integrations.github import GitHubIntegration

            github = GitHubIntegration()
            repository = github.detect_repository()

        try:
            # Update PR description using gh CLI
            _result = run_command(
                f"gh pr edit {pr_number} --repo {repository.full_name} --body -",
                input_data=description,
                check=True,
                timeout=30,
            )

            logger.info(f"Updated PR #{pr_number} description")

        except ShellError as e:
            raise GitHubReviewError(f"Failed to update PR description: {e.stderr}") from e

    def get_pr_status(
        self, pr_number: int, repository: GitHubRepository | None = None
    ) -> dict[str, Any]:
        """Get comprehensive PR status including checks and reviews.

        Args:
            pr_number: Pull request number
            repository: Repository context (auto-detected if None)

        Returns:
            Dictionary with PR status information

        Raises:
            GitHubReviewError: If status cannot be fetched
        """
        if repository is None:
            from auto.integrations.github import GitHubIntegration

            github = GitHubIntegration()
            repository = github.detect_repository()

        try:
            # Get PR details
            result = run_command(
                f"gh pr view {pr_number} --repo {repository.full_name} "
                f"--json state,mergeable,mergeCommit,statusCheckRollup,reviewDecision",
                check=True,
                timeout=30,
            )

            pr_data = json.loads(result.stdout)

            # Get approval status
            is_approved, approving_reviewers, requesting_changes = self.check_approval_status(
                pr_number, repository
            )

            return {
                "state": pr_data.get("state"),
                "mergeable": pr_data.get("mergeable"),
                "merge_commit": pr_data.get("mergeCommit"),
                "review_decision": pr_data.get("reviewDecision"),
                "status_checks": pr_data.get("statusCheckRollup", []),
                "is_approved": is_approved,
                "approving_reviewers": approving_reviewers,
                "requesting_changes_reviewers": requesting_changes,
            }

        except ShellError as e:
            raise GitHubReviewError(f"Failed to get PR status: {e.stderr}") from e
        except json.JSONDecodeError as e:
            raise GitHubReviewError(f"Failed to parse PR status: {e}") from e
