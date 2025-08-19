"""Tests for GitHub review integration functionality."""

import json
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from auto.integrations.review import (
    GitHubReviewError,
    GitHubReviewIntegration,
    PRReview,
    ReviewComment,
)
from auto.models import GitHubRepository


class TestGitHubReviewIntegration:
    """Test GitHub review integration."""

    @pytest.fixture
    def mock_repository(self):
        """Mock repository fixture."""
        return GitHubRepository(owner="test-owner", name="test-repo", default_branch="main")

    @pytest.fixture
    def review_integration(self):
        """Review integration fixture with mocked auth."""
        with patch("auto.integrations.github.validate_github_auth", return_value=True):
            return GitHubReviewIntegration()

    def test_init_success(self):
        """Test successful initialization with valid auth."""
        with patch("auto.integrations.github.validate_github_auth", return_value=True):
            integration = GitHubReviewIntegration()
            assert integration is not None

    def test_init_auth_failure(self):
        """Test initialization failure with invalid auth."""
        from auto.integrations.github import GitHubAuthError

        with patch("auto.integrations.github.validate_github_auth", return_value=False):
            with pytest.raises(GitHubAuthError):
                GitHubReviewIntegration()

    @patch("auto.integrations.review.run_command")
    def test_get_pr_reviews_success(self, mock_run_command, review_integration, mock_repository):
        """Test successful PR review fetching."""
        # Mock gh CLI response
        mock_reviews_data = {
            "reviews": [
                {
                    "id": "123",
                    "state": "APPROVED",
                    "body": "Looks good!",
                    "author": {"login": "reviewer1"},
                    "submittedAt": "2024-01-15T10:00:00Z",
                },
                {
                    "id": "124",
                    "state": "CHANGES_REQUESTED",
                    "body": "Please fix the bugs",
                    "author": {"login": "reviewer2"},
                    "submittedAt": "2024-01-15T11:00:00Z",
                },
            ]
        }

        mock_run_command.return_value = Mock(
            success=True, stdout=json.dumps(mock_reviews_data), stderr=""
        )

        # Test the method
        reviews = review_integration.get_pr_reviews(123, mock_repository)

        # Verify results
        assert len(reviews) == 2
        assert reviews[0].id == "123"
        assert reviews[0].state == "APPROVED"
        assert reviews[0].author == "reviewer1"
        assert reviews[1].id == "124"
        assert reviews[1].state == "CHANGES_REQUESTED"
        assert reviews[1].author == "reviewer2"

        # Verify command called correctly
        mock_run_command.assert_called_once()
        call_args = mock_run_command.call_args[0][0]
        assert "gh pr view 123" in call_args
        assert "--repo test-owner/test-repo" in call_args
        assert "--json reviews" in call_args

    @patch("auto.integrations.review.run_command")
    def test_get_pr_reviews_command_failure(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test PR review fetching with command failure."""
        from auto.utils.shell import ShellError

        mock_run_command.side_effect = ShellError("Command failed", "", "API error")

        with pytest.raises(GitHubReviewError, match="Failed to fetch PR reviews"):
            review_integration.get_pr_reviews(123, mock_repository)

    @patch("auto.integrations.review.run_command")
    def test_get_review_comments_success(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test successful review comment fetching."""
        # Mock gh API response
        mock_comments_data = [
            {
                "id": 456,
                "body": "This line needs fixing",
                "path": "src/main.py",
                "line": 42,
                "side": "RIGHT",
                "user": {"login": "reviewer1"},
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-15T10:00:00Z",
                "resolved": False,
            }
        ]

        mock_run_command.return_value = Mock(
            success=True, stdout=json.dumps(mock_comments_data), stderr=""
        )

        # Test the method
        comments = review_integration.get_review_comments(123, mock_repository)

        # Verify results
        assert len(comments) == 1
        assert comments[0].id == 456
        assert comments[0].body == "This line needs fixing"
        assert comments[0].path == "src/main.py"
        assert comments[0].line == 42
        assert comments[0].author == "reviewer1"
        assert not comments[0].resolved

        # Verify command called correctly
        mock_run_command.assert_called_once()
        call_args = mock_run_command.call_args[0][0]
        assert "gh api repos/test-owner/test-repo/pulls/123/comments" in call_args

    @patch("auto.integrations.review.run_command")
    def test_post_ai_review_success(self, mock_run_command, review_integration, mock_repository):
        """Test successful AI review posting."""
        # Mock gh API response
        mock_review_response = {
            "id": 789,
            "state": "COMMENTED",
            "body": "AI Review: Found 3 issues",
            "user": {"login": "github-actions[bot]"},
            "submitted_at": "2024-01-15T12:00:00Z",
        }

        mock_run_command.return_value = Mock(
            success=True, stdout=json.dumps(mock_review_response), stderr=""
        )

        # Test the method
        review_body = "AI Review: Found 3 issues"
        comments = [{"body": "Fix this issue", "path": "src/main.py", "line": 10}]

        review = review_integration.post_ai_review(
            pr_number=123,
            review_body=review_body,
            comments=comments,
            repository=mock_repository,
            event="REQUEST_CHANGES",
        )

        # Verify results
        assert review.id == 789
        assert review.state == "COMMENTED"
        assert review.body == "AI Review: Found 3 issues"
        assert review.author == "github-actions[bot]"

        # Verify command called correctly
        mock_run_command.assert_called_once()
        call_args = mock_run_command.call_args
        assert "gh api repos/test-owner/test-repo/pulls/123/reviews" in call_args[0][0]
        assert "--method POST" in call_args[0][0]

    @patch("auto.integrations.review.GitHubReviewIntegration.get_pr_reviews")
    def test_check_approval_status_approved(
        self, mock_get_reviews, review_integration, mock_repository
    ):
        """Test approval status check with approved PR."""
        # Mock reviews with approval
        mock_reviews = [
            PRReview(
                id=1, state="APPROVED", body="LGTM", author="reviewer1", submitted_at=datetime.now()
            ),
            PRReview(
                id=2,
                state="COMMENTED",
                body="Minor comment",
                author="reviewer2",
                submitted_at=datetime.now(),
            ),
        ]

        mock_get_reviews.return_value = mock_reviews

        # Test the method
        is_approved, approvers, requesters = review_integration.check_approval_status(
            123, mock_repository
        )

        # Verify results
        assert is_approved is True
        assert "reviewer1" in approvers
        assert len(requesters) == 0

    @patch("auto.integrations.review.GitHubReviewIntegration.get_pr_reviews")
    def test_check_approval_status_changes_requested(
        self, mock_get_reviews, review_integration, mock_repository
    ):
        """Test approval status check with changes requested."""
        # Mock reviews with changes requested
        mock_reviews = [
            PRReview(
                id=1,
                state="CHANGES_REQUESTED",
                body="Please fix the issues",
                author="reviewer1",
                submitted_at=datetime.now(),
            )
        ]

        mock_get_reviews.return_value = mock_reviews

        # Test the method
        is_approved, approvers, requesters = review_integration.check_approval_status(
            123, mock_repository
        )

        # Verify results
        assert is_approved is False
        assert len(approvers) == 0
        assert "reviewer1" in requesters

    @patch("auto.integrations.review.GitHubReviewIntegration.get_review_comments")
    def test_get_unresolved_comments(self, mock_get_comments, review_integration, mock_repository):
        """Test filtering of unresolved comments."""
        # Mock comments with mix of resolved/unresolved
        mock_comments = [
            ReviewComment(id=1, body="Resolved issue", resolved=True, created_at=datetime.now()),
            ReviewComment(id=2, body="Unresolved issue", resolved=False, created_at=datetime.now()),
        ]

        mock_get_comments.return_value = mock_comments

        # Test the method
        unresolved = review_integration.get_unresolved_comments(123, mock_repository)

        # Verify results
        assert len(unresolved) == 1
        assert unresolved[0].id == 2
        assert unresolved[0].body == "Unresolved issue"

    @patch("auto.integrations.review.run_command")
    def test_update_pr_description_success(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test successful PR description update."""
        mock_run_command.return_value = Mock(success=True, stdout="", stderr="")

        # Test the method
        new_description = "Updated PR description with review cycle info"
        review_integration.update_pr_description(
            pr_number=123, description=new_description, repository=mock_repository
        )

        # Verify command called correctly
        mock_run_command.assert_called_once()
        call_args = mock_run_command.call_args
        assert "gh pr edit 123" in call_args[0][0]
        assert "--repo test-owner/test-repo" in call_args[0][0]
        assert "--body -" in call_args[0][0]
        assert call_args[1]["input_data"] == new_description

    @patch("auto.integrations.review.run_command")
    def test_get_pr_status_success(self, mock_run_command, review_integration, mock_repository):
        """Test successful PR status fetching."""
        # Mock gh CLI response
        mock_status_data = {
            "state": "OPEN",
            "mergeable": "MERGEABLE",
            "mergeCommit": None,
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [{"state": "SUCCESS", "context": "continuous-integration"}],
        }

        mock_run_command.return_value = Mock(
            success=True, stdout=json.dumps(mock_status_data), stderr=""
        )

        # Mock approval status check
        with patch.object(review_integration, "check_approval_status") as mock_check:
            mock_check.return_value = (True, ["reviewer1"], [])

            # Test the method
            status = review_integration.get_pr_status(123, mock_repository)

            # Verify results
            assert status["state"] == "OPEN"
            assert status["mergeable"] == "MERGEABLE"
            assert status["review_decision"] == "APPROVED"
            assert status["is_approved"] is True
            assert "reviewer1" in status["approving_reviewers"]
            assert len(status["requesting_changes_reviewers"]) == 0


class TestReviewComment:
    """Test ReviewComment model."""

    def test_review_comment_creation(self):
        """Test ReviewComment creation and dict behavior."""
        comment = ReviewComment(
            id=123, body="Test comment", path="src/main.py", line=42, author="testuser"
        )

        assert comment.id == 123
        assert comment.body == "Test comment"
        assert comment.path == "src/main.py"
        assert comment.line == 42
        assert comment.author == "testuser"
        assert comment.resolved is False

        # Test dict behavior
        assert comment["id"] == 123
        assert comment["body"] == "Test comment"
        assert comment["resolved"] is False


class TestPRReview:
    """Test PRReview model."""

    def test_pr_review_creation(self):
        """Test PRReview creation and dict behavior."""
        review = PRReview(id=456, state="APPROVED", body="Looks good!", author="reviewer1")

        assert review.id == 456
        assert review.state == "APPROVED"
        assert review.body == "Looks good!"
        assert review.author == "reviewer1"
        assert len(review.comments) == 0

        # Test dict behavior
        assert review["id"] == 456
        assert review["state"] == "APPROVED"
        assert review["comments"] == []

    def test_pr_review_with_comments(self):
        """Test PRReview with comments."""
        comment = ReviewComment(id=789, body="Fix this", path="src/main.py", line=10)

        review = PRReview(
            id=456,
            state="CHANGES_REQUESTED",
            body="Please address the issues",
            author="reviewer1",
            comments=[comment],
        )

        assert len(review.comments) == 1
        assert review.comments[0].id == 789
        assert len(review["comments"]) == 1
        assert review["comments"][0]["id"] == 789


class TestReviewIntegrationComprehensive:
    """Comprehensive tests for GitHub review integration with edge cases."""

    @pytest.fixture
    def review_integration(self):
        """Review integration fixture with mocked auth."""
        with patch("auto.integrations.github.validate_github_auth", return_value=True):
            return GitHubReviewIntegration()

    @pytest.fixture
    def mock_repository(self):
        """Mock repository fixture."""
        return GitHubRepository(owner="test-owner", name="test-repo", default_branch="main")

    @patch("auto.integrations.review.run_command")
    def test_get_pr_reviews_empty_response(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test PR review fetching with empty response."""
        mock_run_command.return_value = Mock(success=True, stdout='{"reviews": []}', stderr="")

        reviews = review_integration.get_pr_reviews(123, mock_repository)
        assert len(reviews) == 0

    @patch("auto.integrations.review.run_command")
    def test_get_pr_reviews_malformed_json(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test PR review fetching with malformed JSON."""
        mock_run_command.return_value = Mock(
            success=True, stdout='{"reviews": [invalid json', stderr=""
        )

        with pytest.raises(GitHubReviewError, match="Failed to parse review data"):
            review_integration.get_pr_reviews(123, mock_repository)

    @patch("auto.integrations.review.run_command")
    def test_get_pr_reviews_network_timeout(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test PR review fetching with network timeout."""
        from auto.utils.shell import ShellError

        mock_run_command.side_effect = ShellError(
            "Command timed out", "", "timeout: the monitored command dumped core"
        )

        with pytest.raises(GitHubReviewError, match="Failed to fetch PR reviews"):
            review_integration.get_pr_reviews(123, mock_repository)

    @patch("auto.integrations.review.run_command")
    def test_get_pr_reviews_api_rate_limit(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test PR review fetching with API rate limit."""
        from auto.utils.shell import ShellError

        mock_run_command.side_effect = ShellError(
            "Rate limit exceeded", "", "API rate limit exceeded"
        )

        with pytest.raises(GitHubReviewError, match="Failed to fetch PR reviews"):
            review_integration.get_pr_reviews(123, mock_repository)

    @patch("auto.integrations.review.run_command")
    def test_get_review_comments_pagination(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test review comment fetching with pagination."""
        # Mock large number of comments across pages
        mock_comments_data = [
            {
                "id": i,
                "body": f"Comment {i}",
                "path": "src/main.py",
                "line": 10 + i,
                "side": "RIGHT",
                "user": {"login": "reviewer1"},
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-15T10:00:00Z",
                "resolved": False,
            }
            for i in range(1, 101)  # 100 comments
        ]

        mock_run_command.return_value = Mock(
            success=True, stdout=json.dumps(mock_comments_data), stderr=""
        )

        comments = review_integration.get_review_comments(123, mock_repository)
        assert len(comments) == 100
        assert all(comment.author == "reviewer1" for comment in comments)

    @patch("auto.integrations.review.run_command")
    def test_post_ai_review_with_large_comments(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test AI review posting with large number of comments."""
        mock_review_response = {
            "id": 789,
            "state": "COMMENTED",
            "body": "AI Review: Found 50 issues",
            "user": {"login": "github-actions[bot]"},
            "submitted_at": "2024-01-15T12:00:00Z",
        }

        mock_run_command.return_value = Mock(
            success=True, stdout=json.dumps(mock_review_response), stderr=""
        )

        # Generate large number of comments
        comments = [
            {"body": f"Issue {i}: Fix this problem", "path": f"src/file{i}.py", "line": 10}
            for i in range(1, 51)
        ]

        review = review_integration.post_ai_review(
            pr_number=123,
            review_body="AI Review: Found 50 issues",
            comments=comments,
            repository=mock_repository,
        )

        assert review.id == 789
        assert "50 issues" in review.body

    @patch("auto.integrations.review.run_command")
    def test_post_ai_review_api_failure(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test AI review posting with API failure."""
        from auto.utils.shell import ShellError

        mock_run_command.side_effect = ShellError(
            "API request failed",
            "",
            "HTTP 422: Validation Failed (https://docs.github.com/rest/reference/pulls#create-a-review-for-a-pull-request)",
        )

        with pytest.raises(GitHubReviewError, match="Failed to post AI review"):
            review_integration.post_ai_review(
                pr_number=123, review_body="Test review", comments=[], repository=mock_repository
            )

    @patch("auto.integrations.review.GitHubReviewIntegration.get_pr_reviews")
    def test_check_approval_status_conflicting_reviews(
        self, mock_get_reviews, review_integration, mock_repository
    ):
        """Test approval status with conflicting reviews from same reviewer."""
        # Mock reviews where same reviewer has both approved and requested changes
        mock_reviews = [
            PRReview(
                id=1,
                state="CHANGES_REQUESTED",
                body="Please fix these issues",
                author="reviewer1",
                submitted_at=datetime.fromisoformat("2024-01-15T10:00:00+00:00"),
            ),
            PRReview(
                id=2,
                state="APPROVED",
                body="LGTM after fixes",
                author="reviewer1",
                submitted_at=datetime.fromisoformat("2024-01-15T11:00:00+00:00"),  # Later approval
            ),
        ]

        mock_get_reviews.return_value = mock_reviews

        is_approved, approvers, requesters = review_integration.check_approval_status(
            123, mock_repository
        )

        # Latest review should take precedence
        assert is_approved is True
        assert "reviewer1" in approvers
        assert "reviewer1" not in requesters

    @patch("auto.integrations.review.GitHubReviewIntegration.get_review_comments")
    def test_get_unresolved_comments_mixed_states(
        self, mock_get_comments, review_integration, mock_repository
    ):
        """Test filtering comments with various resolution states."""
        mock_comments = [
            ReviewComment(id=1, body="Resolved issue", resolved=True, created_at=datetime.now()),
            ReviewComment(id=2, body="Unresolved issue", resolved=False, created_at=datetime.now()),
            ReviewComment(
                id=3, body="Another unresolved issue", resolved=False, created_at=datetime.now()
            ),
            ReviewComment(
                id=4, body="Outdated resolved issue", resolved=True, created_at=datetime.now()
            ),
        ]

        mock_get_comments.return_value = mock_comments

        unresolved = review_integration.get_unresolved_comments(123, mock_repository)

        assert len(unresolved) == 2
        assert all(not comment.resolved for comment in unresolved)
        assert unresolved[0].id == 2
        assert unresolved[1].id == 3

    @patch("auto.integrations.review.run_command")
    def test_update_pr_description_special_characters(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test PR description update with special characters."""
        mock_run_command.return_value = Mock(success=True, stdout="", stderr="")

        # Test with special characters, markdown, and unicode
        special_description = """
        # Updated PR Description 🚀

        - Fixed issue with `special_function()`
        - Added support for émojis and ünîcødé
        - Updated "quoted strings" and 'single quotes'
        - Handle edge case: `value > 100 && value < 200`

        **Review Status**: ✅ Ready for review
        """

        review_integration.update_pr_description(
            pr_number=123, description=special_description, repository=mock_repository
        )

        mock_run_command.assert_called_once()
        call_args = mock_run_command.call_args
        assert call_args[1]["input_data"] == special_description

    @patch("auto.integrations.review.run_command")
    def test_get_pr_status_comprehensive(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test comprehensive PR status fetching with all fields."""
        mock_status_data = {
            "state": "OPEN",
            "mergeable": "MERGEABLE",
            "mergeCommit": None,
            "reviewDecision": "REVIEW_REQUIRED",
            "statusCheckRollup": [
                {"state": "SUCCESS", "context": "continuous-integration"},
                {"state": "PENDING", "context": "security-scan"},
                {"state": "FAILURE", "context": "lint-check"},
            ],
            "mergeable_state": "clean",
            "merged": False,
            "draft": False,
            "assignees": [{"login": "assignee1"}],
            "requested_reviewers": [{"login": "requested_reviewer"}],
        }

        mock_run_command.return_value = Mock(
            success=True, stdout=json.dumps(mock_status_data), stderr=""
        )

        with patch.object(review_integration, "check_approval_status") as mock_check:
            mock_check.return_value = (False, [], ["reviewer1"])

            status = review_integration.get_pr_status(123, mock_repository)

            assert status["state"] == "OPEN"
            assert status["mergeable"] == "MERGEABLE"
            assert status["review_decision"] == "REVIEW_REQUIRED"
            assert status["is_approved"] is False
            assert len(status["requesting_changes_reviewers"]) == 1
            assert "reviewer1" in status["requesting_changes_reviewers"]

    def test_review_comment_edge_cases(self):
        """Test ReviewComment model with edge cases."""
        # Test with minimal data
        comment = ReviewComment(
            id=123,
            body="",  # Empty body
            path=None,  # No file path
            line=None,  # No line number
            author="",  # Empty author
        )

        assert comment.id == 123
        assert comment.body == ""
        assert comment.path is None
        assert comment.line is None
        assert comment.author == ""
        assert comment.resolved is False

    def test_pr_review_with_unicode_content(self):
        """Test PRReview with unicode and special characters."""
        review = PRReview(
            id=456,
            state="APPROVED",
            body="Looks good! 👍 ñice work on the ünîcødé support",
            author="reviewer_ñame",
        )

        assert "👍" in review.body
        assert "ñice" in review.body
        assert "ünîcødé" in review.body
        assert "ñame" in review.author


class TestReviewIntegrationPerformance:
    """Performance tests for review integration."""

    @pytest.fixture
    def review_integration(self):
        """Review integration fixture with mocked auth."""
        with patch("auto.integrations.github.validate_github_auth", return_value=True):
            return GitHubReviewIntegration()

    @pytest.fixture
    def mock_repository(self):
        """Mock repository fixture."""
        return GitHubRepository(owner="test-owner", name="test-repo", default_branch="main")

    @patch("auto.integrations.review.run_command")
    def test_large_review_processing_performance(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test performance with large number of reviews."""
        import time

        # Generate large number of reviews
        large_reviews_data = {
            "reviews": [
                {
                    "id": str(i),
                    "state": "APPROVED" if i % 2 == 0 else "CHANGES_REQUESTED",
                    "body": f"Review {i}: {'Approved' if i % 2 == 0 else 'Changes needed'}",
                    "author": {"login": f"reviewer{i % 10}"},
                    "submittedAt": "2024-01-15T10:00:00Z",
                }
                for i in range(1, 1001)  # 1000 reviews
            ]
        }

        mock_run_command.return_value = Mock(
            success=True, stdout=json.dumps(large_reviews_data), stderr=""
        )

        start_time = time.time()
        reviews = review_integration.get_pr_reviews(123, mock_repository)
        end_time = time.time()

        # Should complete within reasonable time (< 1 second for 1000 reviews)
        processing_time = end_time - start_time
        assert processing_time < 1.0
        assert len(reviews) == 1000

    @patch("auto.integrations.review.run_command")
    def test_large_comment_processing_performance(
        self, mock_run_command, review_integration, mock_repository
    ):
        """Test performance with large number of comments."""
        import time

        # Generate large number of comments
        large_comments_data = [
            {
                "id": i,
                "body": f"Comment {i}: This needs to be fixed for performance reasons",
                "path": f"src/file{i % 50}.py",
                "line": 10 + (i % 100),
                "side": "RIGHT",
                "user": {"login": f"reviewer{i % 5}"},
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-15T10:00:00Z",
                "resolved": i % 3 != 0,  # 2/3 resolved, 1/3 unresolved
            }
            for i in range(1, 501)  # 500 comments
        ]

        mock_run_command.return_value = Mock(
            success=True, stdout=json.dumps(large_comments_data), stderr=""
        )

        start_time = time.time()
        comments = review_integration.get_review_comments(123, mock_repository)
        end_time = time.time()

        # Should complete within reasonable time (< 0.5 seconds for 500 comments)
        processing_time = end_time - start_time
        assert processing_time < 0.5
        assert len(comments) == 500

        # Test unresolved filtering performance
        start_time = time.time()
        unresolved = review_integration.get_unresolved_comments(123, mock_repository)
        end_time = time.time()

        filtering_time = end_time - start_time
        assert filtering_time < 0.5
        # Should have ~1/3 unresolved comments
        assert 150 <= len(unresolved) <= 170
