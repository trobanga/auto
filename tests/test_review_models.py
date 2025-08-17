"""Tests for enhanced review data models."""

import pytest
from datetime import datetime
from pydantic import ValidationError

from auto.models import (
    ReviewComment,
    GitHubPRReview,
    Review,
    ReviewType,
    ReviewStatus,
    WorkflowsConfig
)


class TestReviewComment:
    """Test ReviewComment model."""
    
    def test_review_comment_basic(self):
        """Test basic ReviewComment creation."""
        comment = ReviewComment(
            id=123,
            body="This needs to be fixed"
        )
        
        assert comment.id == 123
        assert comment.body == "This needs to be fixed"
        assert comment.path is None
        assert comment.line is None
        assert comment.side == "RIGHT"
        assert comment.resolved is False
    
    def test_review_comment_with_location(self):
        """Test ReviewComment with file location."""
        comment = ReviewComment(
            id=456,
            body="Fix this line",
            path="src/main.py",
            line=42,
            start_line=40,
            side="LEFT"
        )
        
        assert comment.path == "src/main.py"
        assert comment.line == 42
        assert comment.start_line == 40
        assert comment.side == "LEFT"
    
    def test_review_comment_with_metadata(self):
        """Test ReviewComment with timestamps and author."""
        now = datetime.now()
        comment = ReviewComment(
            id=789,
            body="Good catch!",
            author="reviewer1",
            created_at=now,
            updated_at=now,
            resolved=True
        )
        
        assert comment.author == "reviewer1"
        assert comment.created_at == now
        assert comment.updated_at == now
        assert comment.resolved is True
    
    def test_review_comment_validation(self):
        """Test ReviewComment validation."""
        # Test required fields
        with pytest.raises(ValidationError):
            ReviewComment()  # Missing required id and body
        
        with pytest.raises(ValidationError):
            ReviewComment(id=123)  # Missing required body
        
        # Test valid creation
        comment = ReviewComment(id=1, body="test")
        assert comment.id == 1
        assert comment.body == "test"


class TestGitHubPRReview:
    """Test GitHubPRReview model."""
    
    def test_github_pr_review_basic(self):
        """Test basic GitHubPRReview creation."""
        review = GitHubPRReview(
            id=123,
            state="APPROVED",
            body="Looks good to me!"
        )
        
        assert review.id == 123
        assert review.state == "APPROVED"
        assert review.body == "Looks good to me!"
        assert review.author is None
        assert review.submitted_at is None
        assert len(review.comments) == 0
    
    def test_github_pr_review_with_metadata(self):
        """Test GitHubPRReview with full metadata."""
        submitted_time = datetime.now()
        review = GitHubPRReview(
            id=456,
            state="CHANGES_REQUESTED",
            body="Please address these issues",
            author="senior-dev",
            submitted_at=submitted_time
        )
        
        assert review.author == "senior-dev"
        assert review.submitted_at == submitted_time
        assert review.state == "CHANGES_REQUESTED"
    
    def test_github_pr_review_with_comments(self):
        """Test GitHubPRReview with comments."""
        comment1 = ReviewComment(id=1, body="Fix this")
        comment2 = ReviewComment(id=2, body="And this too")
        
        review = GitHubPRReview(
            id=789,
            state="COMMENTED",
            body="General review",
            comments=[comment1, comment2]
        )
        
        assert len(review.comments) == 2
        assert review.comments[0].id == 1
        assert review.comments[1].id == 2
        assert review.comments[0].body == "Fix this"
    
    def test_github_pr_review_validation(self):
        """Test GitHubPRReview validation."""
        # Test required fields
        with pytest.raises(ValidationError):
            GitHubPRReview()  # Missing required fields
        
        with pytest.raises(ValidationError):
            GitHubPRReview(id=123)  # Missing state and body
        
        # Test valid creation
        review = GitHubPRReview(id=1, state="APPROVED", body="LGTM")
        assert review.id == 1
        assert review.state == "APPROVED"


class TestReviewModel:
    """Test enhanced Review model."""
    
    def test_review_basic(self):
        """Test basic Review creation."""
        review = Review(
            type=ReviewType.AI,
            status=ReviewStatus.COMPLETED
        )
        
        assert review.type == ReviewType.AI
        assert review.status == ReviewStatus.COMPLETED
        assert review.reviewer is None
        assert len(review.comments) == 0
        assert review.github_review is None
        assert isinstance(review.timestamp, datetime)
    
    def test_review_human_with_reviewer(self):
        """Test human Review with reviewer."""
        review = Review(
            type=ReviewType.HUMAN,
            reviewer="senior-dev",
            status=ReviewStatus.APPROVED,
            comments=["Looks great!", "Minor suggestions"]
        )
        
        assert review.type == ReviewType.HUMAN
        assert review.reviewer == "senior-dev"
        assert review.status == ReviewStatus.APPROVED
        assert len(review.comments) == 2
        assert "Looks great!" in review.comments
    
    def test_review_with_github_review(self):
        """Test Review with associated GitHubPRReview."""
        github_review = GitHubPRReview(
            id=123,
            state="APPROVED",
            body="LGTM",
            author="reviewer1"
        )
        
        review = Review(
            type=ReviewType.HUMAN,
            reviewer="reviewer1",
            status=ReviewStatus.APPROVED,
            github_review=github_review
        )
        
        assert review.github_review is not None
        assert review.github_review.id == 123
        assert review.github_review.state == "APPROVED"
        assert review.reviewer == "reviewer1"
    
    def test_review_metadata(self):
        """Test Review with metadata."""
        metadata = {
            "pr_number": 42,
            "iteration": 2,
            "ai_agent": "pull-request-reviewer"
        }
        
        review = Review(
            type=ReviewType.AI,
            status=ReviewStatus.COMMENTS_POSTED,
            metadata=metadata
        )
        
        assert review.metadata["pr_number"] == 42
        assert review.metadata["iteration"] == 2
        assert review.metadata["ai_agent"] == "pull-request-reviewer"
    
    def test_review_validation(self):
        """Test Review validation."""
        # Test required fields
        with pytest.raises(ValidationError):
            Review()  # Missing required fields
        
        with pytest.raises(ValidationError):
            Review(type=ReviewType.AI)  # Missing status
        
        # Test valid enum values
        with pytest.raises(ValidationError):
            Review(type="invalid_type", status=ReviewStatus.PENDING)
        
        # Test valid creation
        review = Review(type=ReviewType.AI, status=ReviewStatus.PENDING)
        assert review.type == ReviewType.AI
        assert review.status == ReviewStatus.PENDING


class TestWorkflowsConfigValidation:
    """Test WorkflowsConfig validation for review settings."""
    
    def test_workflows_config_defaults(self):
        """Test WorkflowsConfig with default values."""
        config = WorkflowsConfig()
        
        assert config.ai_review_first is True
        assert config.require_human_approval is True
        assert config.review_check_interval == 60
        assert config.worktree_conflict_resolution == "prompt"
    
    def test_review_check_interval_validation(self):
        """Test review_check_interval validation."""
        # Test valid values
        config = WorkflowsConfig(review_check_interval=30)
        assert config.review_check_interval == 30
        
        config = WorkflowsConfig(review_check_interval=300)
        assert config.review_check_interval == 300
        
        # Test invalid values - too low
        with pytest.raises(ValidationError, match="Review check interval must be at least 10 seconds"):
            WorkflowsConfig(review_check_interval=5)
        
        # Test invalid values - too high
        with pytest.raises(ValidationError, match="Review check interval must be at most 1 hour"):
            WorkflowsConfig(review_check_interval=4000)
    
    def test_conflict_resolution_validation(self):
        """Test worktree_conflict_resolution validation."""
        # Test valid values
        for strategy in ["prompt", "force", "skip"]:
            config = WorkflowsConfig(worktree_conflict_resolution=strategy)
            assert config.worktree_conflict_resolution == strategy
        
        # Test invalid values
        with pytest.raises(ValidationError, match="Invalid conflict resolution strategy"):
            WorkflowsConfig(worktree_conflict_resolution="invalid")
        
        with pytest.raises(ValidationError, match="Invalid conflict resolution strategy"):
            WorkflowsConfig(worktree_conflict_resolution="auto")
    
    def test_workflows_config_review_settings(self):
        """Test review-specific settings in WorkflowsConfig."""
        config = WorkflowsConfig(
            ai_review_first=False,
            require_human_approval=False,
            review_check_interval=120,
            worktree_conflict_resolution="force"
        )
        
        assert config.ai_review_first is False
        assert config.require_human_approval is False
        assert config.review_check_interval == 120
        assert config.worktree_conflict_resolution == "force"
    
    def test_workflows_config_template_validation(self):
        """Test template fields validation."""
        config = WorkflowsConfig(
            branch_naming="feature/{id}",
            implementation_commit_message="feat({id}): {title}"
        )
        
        assert config.branch_naming == "feature/{id}"
        assert config.implementation_commit_message == "feat({id}): {title}"


class TestReviewModelsIntegration:
    """Test integration between different review models."""
    
    def test_review_with_full_github_data(self):
        """Test complete Review with full GitHub review data."""
        # Create review comments
        comment1 = ReviewComment(
            id=1,
            body="Please fix the formatting",
            path="src/main.py",
            line=25,
            author="reviewer1"
        )
        
        comment2 = ReviewComment(
            id=2,
            body="Add error handling here",
            path="src/utils.py",
            line=10,
            author="reviewer1"
        )
        
        # Create GitHub PR review
        github_review = GitHubPRReview(
            id=123,
            state="CHANGES_REQUESTED",
            body="Please address the following issues before merging",
            author="reviewer1",
            submitted_at=datetime.now(),
            comments=[comment1, comment2]
        )
        
        # Create Review model
        review = Review(
            type=ReviewType.HUMAN,
            reviewer="reviewer1",
            status=ReviewStatus.CHANGES_REQUESTED,
            comments=["General feedback about code quality"],
            github_review=github_review,
            metadata={
                "pr_number": 42,
                "review_iteration": 1
            }
        )
        
        # Verify the complete structure
        assert review.type == ReviewType.HUMAN
        assert review.reviewer == "reviewer1"
        assert review.github_review.id == 123
        assert len(review.github_review.comments) == 2
        assert review.github_review.comments[0].body == "Please fix the formatting"
        assert review.github_review.comments[1].path == "src/utils.py"
        assert review.metadata["pr_number"] == 42
    
    def test_multiple_reviews_workflow(self):
        """Test multiple reviews in a workflow scenario."""
        # AI Review
        ai_review = Review(
            type=ReviewType.AI,
            status=ReviewStatus.COMMENTS_POSTED,
            comments=["Found 3 potential issues"],
            metadata={"ai_agent": "pull-request-reviewer"}
        )
        
        # Human Review
        human_review = Review(
            type=ReviewType.HUMAN,
            reviewer="senior-dev",
            status=ReviewStatus.APPROVED,
            comments=["Code looks good after AI suggestions"]
        )
        
        # AI Update Review
        update_review = Review(
            type=ReviewType.AI_UPDATE,
            status=ReviewStatus.COMPLETED,
            comments=["Addressed all review comments"],
            metadata={"ai_agent": "coder"}
        )
        
        reviews = [ai_review, human_review, update_review]
        
        # Verify the workflow
        assert len(reviews) == 3
        assert reviews[0].type == ReviewType.AI
        assert reviews[1].type == ReviewType.HUMAN
        assert reviews[2].type == ReviewType.AI_UPDATE
        assert reviews[1].status == ReviewStatus.APPROVED
        assert reviews[2].status == ReviewStatus.COMPLETED