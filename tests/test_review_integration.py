"""Tests for GitHub review integration functionality."""

import json
import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from auto.integrations.review import (
    GitHubReviewIntegration,
    GitHubReviewError,
    ReviewComment,
    PRReview
)
from auto.models import GitHubRepository


class TestGitHubReviewIntegration:
    """Test GitHub review integration."""
    
    @pytest.fixture
    def mock_repository(self):
        """Mock repository fixture."""
        return GitHubRepository(
            owner="test-owner",
            name="test-repo",
            default_branch="main"
        )
    
    @pytest.fixture
    def review_integration(self):
        """Review integration fixture with mocked auth."""
        with patch('auto.integrations.review.validate_github_auth', return_value=True):
            return GitHubReviewIntegration()
    
    def test_init_success(self):
        """Test successful initialization with valid auth."""
        with patch('auto.integrations.review.validate_github_auth', return_value=True):
            integration = GitHubReviewIntegration()
            assert integration is not None
    
    def test_init_auth_failure(self):
        """Test initialization failure with invalid auth."""
        with patch('auto.integrations.review.validate_github_auth', return_value=False):
            with pytest.raises(Exception):  # Should raise GitHubAuthError
                GitHubReviewIntegration()
    
    @patch('auto.integrations.review.run_command')
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
                    "submittedAt": "2024-01-15T10:00:00Z"
                },
                {
                    "id": "124",
                    "state": "CHANGES_REQUESTED",
                    "body": "Please fix the bugs",
                    "author": {"login": "reviewer2"},
                    "submittedAt": "2024-01-15T11:00:00Z"
                }
            ]
        }
        
        mock_run_command.return_value = Mock(
            success=True,
            stdout=json.dumps(mock_reviews_data),
            stderr=""
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
    
    @patch('auto.integrations.review.run_command')
    def test_get_pr_reviews_command_failure(self, mock_run_command, review_integration, mock_repository):
        """Test PR review fetching with command failure."""
        from auto.utils.shell import ShellError
        
        mock_run_command.side_effect = ShellError("Command failed", "", "API error")
        
        with pytest.raises(GitHubReviewError, match="Failed to fetch PR reviews"):
            review_integration.get_pr_reviews(123, mock_repository)
    
    @patch('auto.integrations.review.run_command')
    def test_get_review_comments_success(self, mock_run_command, review_integration, mock_repository):
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
                "resolved": False
            }
        ]
        
        mock_run_command.return_value = Mock(
            success=True,
            stdout=json.dumps(mock_comments_data),
            stderr=""
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
    
    @patch('auto.integrations.review.run_command')
    def test_post_ai_review_success(self, mock_run_command, review_integration, mock_repository):
        """Test successful AI review posting."""
        # Mock gh API response
        mock_review_response = {
            "id": 789,
            "state": "COMMENTED",
            "body": "AI Review: Found 3 issues",
            "user": {"login": "github-actions[bot]"},
            "submitted_at": "2024-01-15T12:00:00Z"
        }
        
        mock_run_command.return_value = Mock(
            success=True,
            stdout=json.dumps(mock_review_response),
            stderr=""
        )
        
        # Test the method
        review_body = "AI Review: Found 3 issues"
        comments = [
            {"body": "Fix this issue", "path": "src/main.py", "line": 10}
        ]
        
        review = review_integration.post_ai_review(
            pr_number=123,
            review_body=review_body,
            comments=comments,
            repository=mock_repository,
            event="REQUEST_CHANGES"
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
    
    @patch('auto.integrations.review.GitHubReviewIntegration.get_pr_reviews')
    def test_check_approval_status_approved(self, mock_get_reviews, review_integration, mock_repository):
        """Test approval status check with approved PR."""
        # Mock reviews with approval
        mock_reviews = [
            PRReview(
                id=1,
                state="APPROVED",
                body="LGTM",
                author="reviewer1",
                submitted_at=datetime.now()
            ),
            PRReview(
                id=2,
                state="COMMENTED",
                body="Minor comment",
                author="reviewer2",
                submitted_at=datetime.now()
            )
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
    
    @patch('auto.integrations.review.GitHubReviewIntegration.get_pr_reviews')
    def test_check_approval_status_changes_requested(self, mock_get_reviews, review_integration, mock_repository):
        """Test approval status check with changes requested."""
        # Mock reviews with changes requested
        mock_reviews = [
            PRReview(
                id=1,
                state="CHANGES_REQUESTED",
                body="Please fix the issues",
                author="reviewer1",
                submitted_at=datetime.now()
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
    
    @patch('auto.integrations.review.GitHubReviewIntegration.get_review_comments')
    def test_get_unresolved_comments(self, mock_get_comments, review_integration, mock_repository):
        """Test filtering of unresolved comments."""
        # Mock comments with mix of resolved/unresolved
        mock_comments = [
            ReviewComment(
                id=1,
                body="Resolved issue",
                resolved=True,
                created_at=datetime.now()
            ),
            ReviewComment(
                id=2,
                body="Unresolved issue",
                resolved=False,
                created_at=datetime.now()
            )
        ]
        
        mock_get_comments.return_value = mock_comments
        
        # Test the method
        unresolved = review_integration.get_unresolved_comments(123, mock_repository)
        
        # Verify results
        assert len(unresolved) == 1
        assert unresolved[0].id == 2
        assert unresolved[0].body == "Unresolved issue"
    
    @patch('auto.integrations.review.run_command')
    def test_update_pr_description_success(self, mock_run_command, review_integration, mock_repository):
        """Test successful PR description update."""
        mock_run_command.return_value = Mock(
            success=True,
            stdout="",
            stderr=""
        )
        
        # Test the method
        new_description = "Updated PR description with review cycle info"
        review_integration.update_pr_description(
            pr_number=123,
            description=new_description,
            repository=mock_repository
        )
        
        # Verify command called correctly
        mock_run_command.assert_called_once()
        call_args = mock_run_command.call_args
        assert "gh pr edit 123" in call_args[0][0]
        assert "--repo test-owner/test-repo" in call_args[0][0]
        assert "--body -" in call_args[0][0]
        assert call_args[1]["input_data"] == new_description
    
    @patch('auto.integrations.review.run_command')
    def test_get_pr_status_success(self, mock_run_command, review_integration, mock_repository):
        """Test successful PR status fetching."""
        # Mock gh CLI response
        mock_status_data = {
            "state": "OPEN",
            "mergeable": "MERGEABLE",
            "mergeCommit": None,
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [
                {"state": "SUCCESS", "context": "continuous-integration"}
            ]
        }
        
        mock_run_command.return_value = Mock(
            success=True,
            stdout=json.dumps(mock_status_data),
            stderr=""
        )
        
        # Mock approval status check
        with patch.object(review_integration, 'check_approval_status') as mock_check:
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
            id=123,
            body="Test comment",
            path="src/main.py",
            line=42,
            author="testuser"
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
        review = PRReview(
            id=456,
            state="APPROVED",
            body="Looks good!",
            author="reviewer1"
        )
        
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
        comment = ReviewComment(
            id=789,
            body="Fix this",
            path="src/main.py",
            line=10
        )
        
        review = PRReview(
            id=456,
            state="CHANGES_REQUESTED",
            body="Please address the issues",
            author="reviewer1",
            comments=[comment]
        )
        
        assert len(review.comments) == 1
        assert review.comments[0].id == 789
        assert len(review["comments"]) == 1
        assert review["comments"][0]["id"] == 789