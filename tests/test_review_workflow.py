"""
Tests for the review workflow functionality.

Tests cover:
- AI review execution and comment posting
- Human review monitoring and detection
- Review cycle orchestration and state management
- Review prompt templates and formatting
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import dataclass
from typing import List, Dict, Any

from auto.workflows.review import (
    execute_review_cycle,
    trigger_ai_review,
    wait_for_human_review,
    process_review_comments,
    check_cycle_completion,
    trigger_ai_update,
    initiate_review_cycle,
    ReviewCycleStatus,
    ReviewCycleState,
    ReviewWorkflowError,
)
from auto.integrations.ai import ClaudeIntegration, AIResponse
from auto.integrations.review import GitHubReviewIntegration, ReviewComment, PRReview
from auto.models import AIConfig


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    config = Mock()
    config.workflows.max_review_iterations = 3
    config.workflows.ai_review_first = True
    config.workflows.review_check_interval = 1  # Fast polling for tests
    config.workflows.require_human_approval = True
    return config


@pytest.fixture
def mock_ai_config():
    """Mock AI configuration."""
    return AIConfig(
        command="claude",
        implementation_agent="coder",
        review_agent="pull-request-reviewer",
        update_agent="coder",
        implementation_prompt="Implement: {description}",
        review_prompt="Review this PR thoroughly",
        update_prompt="Address these comments: {comments}"
    )


@pytest.fixture
def sample_review_comments():
    """Sample review comments for testing."""
    return [
        ReviewComment(
            id="1",
            body="This function is too complex, consider breaking it down",
            file_path="src/main.py",
            line_number=45,
            author="reviewer1"
        ),
        ReviewComment(
            id="2",
            body="Add error handling for this API call",
            file_path="src/api.py",
            line_number=23,
            author="reviewer2"
        )
    ]


@pytest.fixture
def sample_pr_reviews():
    """Sample PR reviews for testing."""
    return [
        PRReview(
            id="review1",
            author="reviewer1",
            state="COMMENTED",
            body="Found a few issues that need addressing",
            submitted_at="2024-01-15T10:00:00Z"
        ),
        PRReview(
            id="review2", 
            author="reviewer2",
            state="APPROVED",
            body="Looks good to merge!",
            submitted_at="2024-01-15T11:00:00Z"
        )
    ]


class TestReviewCycleOrchestration:
    """Test review cycle orchestration functionality."""
    
    @pytest.mark.asyncio
    async def test_execute_review_cycle_success(self, mock_config):
        """Test successful review cycle execution."""
        with patch('auto.workflows.review.get_config', return_value=mock_config), \
             patch('auto.workflows.review.trigger_ai_review') as mock_ai_review, \
             patch('auto.workflows.review.wait_for_human_review') as mock_wait_human, \
             patch('auto.workflows.review.process_review_comments') as mock_process, \
             patch('auto.workflows.review.check_cycle_completion') as mock_check:
            
            # Setup mocks
            mock_wait_human.return_value = True  # Human review received
            mock_check.return_value = ReviewCycleStatus.APPROVED
            
            # Execute review cycle
            result = await execute_review_cycle(
                pr_number=123,
                repository="owner/repo"
            )
            
            # Verify result
            assert result.pr_number == 123
            assert result.repository == "owner/repo"
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration == 1
            
            # Verify calls
            mock_ai_review.assert_called_once()
            mock_wait_human.assert_called_once()
            mock_process.assert_called_once()
            mock_check.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_review_cycle_max_iterations(self, mock_config):
        """Test review cycle reaching max iterations."""
        with patch('auto.workflows.review.get_config', return_value=mock_config), \
             patch('auto.workflows.review.trigger_ai_review'), \
             patch('auto.workflows.review.wait_for_human_review', return_value=True), \
             patch('auto.workflows.review.process_review_comments'), \
             patch('auto.workflows.review.check_cycle_completion', return_value=ReviewCycleStatus.CHANGES_REQUESTED):
            
            # Execute review cycle
            result = await execute_review_cycle(
                pr_number=123,
                repository="owner/repo"
            )
            
            # Should reach max iterations
            assert result.status == ReviewCycleStatus.MAX_ITERATIONS_REACHED
            assert result.iteration == 3
    
    @pytest.mark.asyncio
    async def test_execute_review_cycle_error_handling(self, mock_config):
        """Test review cycle error handling."""
        with patch('auto.workflows.review.get_config', return_value=mock_config), \
             patch('auto.workflows.review.trigger_ai_review', side_effect=Exception("AI review failed")):
            
            # Should raise ReviewWorkflowError
            with pytest.raises(ReviewWorkflowError, match="Review cycle execution failed"):
                await execute_review_cycle(123, "owner/repo")


class TestAIReviewExecution:
    """Test AI review execution functionality."""
    
    @pytest.mark.asyncio
    async def test_trigger_ai_review_success(self, mock_ai_config, sample_review_comments):
        """Test successful AI review execution."""
        # Create test state
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.AI_REVIEW_IN_PROGRESS,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=time.time(),
            max_iterations=3
        )
        
        # Mock AI response
        ai_response = AIResponse(
            success=True,
            response_type="review",
            content="Found several issues that need attention",
            comments=["Issue 1: Fix logic error", "Issue 2: Add validation"],
            summary="Review completed with 2 issues found"
        )
        
        with patch('auto.integrations.ai.ClaudeIntegration') as mock_ai_class, \
             patch('auto.integrations.review.GitHubReviewIntegration') as mock_review_class:
            
            # Setup mocks
            mock_ai = Mock()
            mock_ai.execute_review.return_value = ai_response
            mock_ai_class.return_value = mock_ai
            
            mock_review = Mock()
            mock_review.post_ai_review = AsyncMock()
            mock_review_class.return_value = mock_review
            
            # Execute AI review
            await trigger_ai_review(state)
            
            # Verify AI review was called
            mock_ai.execute_review.assert_called_once_with(
                pr_number=123,
                repository="owner/repo"
            )
            
            # Verify comments were posted
            mock_review.post_ai_review.assert_called_once()
            
            # Verify state was updated
            assert len(state.ai_reviews) == 1
            assert state.ai_reviews[0]["status"] == "completed"
            assert state.ai_reviews[0]["comments_count"] == 2
    
    @pytest.mark.asyncio
    async def test_trigger_ai_review_failure(self):
        """Test AI review failure handling."""
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.AI_REVIEW_IN_PROGRESS,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=time.time(),
            max_iterations=3
        )
        
        with patch('auto.integrations.ai.ClaudeIntegration') as mock_ai_class:
            # Setup mock to fail
            mock_ai = Mock()
            mock_ai.execute_review.side_effect = Exception("AI service unavailable")
            mock_ai_class.return_value = mock_ai
            
            # Should raise ReviewWorkflowError
            with pytest.raises(ReviewWorkflowError, match="AI review execution failed"):
                await trigger_ai_review(state)
            
            # Verify failed review was recorded
            assert len(state.ai_reviews) == 1
            assert state.ai_reviews[0]["status"] == "failed"


class TestHumanReviewMonitoring:
    """Test human review monitoring functionality."""
    
    @pytest.mark.asyncio
    async def test_wait_for_human_review_success(self, sample_pr_reviews):
        """Test successful human review detection."""
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.WAITING_FOR_HUMAN,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=time.time(),
            max_iterations=3
        )
        
        with patch('auto.workflows.review.get_config') as mock_get_config, \
             patch('auto.integrations.review.GitHubReviewIntegration') as mock_review_class:
            
            # Setup config
            mock_config = Mock()
            mock_config.workflows.review_check_interval = 0.1
            mock_get_config.return_value = mock_config
            
            # Setup review integration mock
            mock_review = Mock()
            mock_review.get_pr_reviews.return_value = sample_pr_reviews
            mock_review_class.return_value = mock_review
            
            # Execute human review wait
            result = await wait_for_human_review(state, timeout_minutes=0.01)  # Very short timeout
            
            # Should detect human reviews
            assert result is True
            assert len(state.human_reviews) == 2
    
    @pytest.mark.asyncio
    async def test_wait_for_human_review_timeout(self):
        """Test human review timeout."""
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.WAITING_FOR_HUMAN,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=time.time(),
            max_iterations=3
        )
        
        with patch('auto.workflows.review.get_config') as mock_get_config, \
             patch('auto.integrations.review.GitHubReviewIntegration') as mock_review_class:
            
            # Setup config
            mock_config = Mock()
            mock_config.workflows.review_check_interval = 0.1
            mock_get_config.return_value = mock_config
            
            # Setup review integration mock - no new reviews
            mock_review = Mock()
            mock_review.get_pr_reviews.return_value = []
            mock_review_class.return_value = mock_review
            
            # Execute human review wait with very short timeout
            result = await wait_for_human_review(state, timeout_minutes=0.01)
            
            # Should timeout
            assert result is False


class TestReviewCommentProcessing:
    """Test review comment processing functionality."""
    
    @pytest.mark.asyncio
    async def test_process_review_comments(self, sample_review_comments):
        """Test review comment processing."""
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.HUMAN_REVIEW_RECEIVED,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=time.time(),
            max_iterations=3
        )
        
        with patch('auto.integrations.review.GitHubReviewIntegration') as mock_review_class:
            # Setup review integration mock
            mock_review = Mock()
            mock_review.get_unresolved_comments.return_value = sample_review_comments
            mock_review_class.return_value = mock_review
            
            # Process review comments
            await process_review_comments(state)
            
            # Verify comments were processed
            assert len(state.unresolved_comments) == 2
            assert state.unresolved_comments[0].body == "This function is too complex, consider breaking it down"


class TestCycleCompletion:
    """Test review cycle completion evaluation."""
    
    @pytest.mark.asyncio
    async def test_check_cycle_completion_approved(self):
        """Test cycle completion when PR is approved."""
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.HUMAN_REVIEW_RECEIVED,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=time.time(),
            max_iterations=3
        )
        
        with patch('auto.integrations.review.GitHubReviewIntegration') as mock_review_class:
            # Setup review integration mock - approved with no unresolved comments
            mock_review = Mock()
            mock_review.check_approval_status.return_value = {
                "approved": True,
                "changes_requested": False,
                "approving_reviewers": ["reviewer1"],
                "requesting_changes_reviewers": []
            }
            mock_review_class.return_value = mock_review
            
            # Check cycle completion
            result = await check_cycle_completion(state)
            
            # Should be approved
            assert result == ReviewCycleStatus.APPROVED
    
    @pytest.mark.asyncio
    async def test_check_cycle_completion_changes_requested(self, sample_review_comments):
        """Test cycle completion when changes are requested."""
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.HUMAN_REVIEW_RECEIVED,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=sample_review_comments,
            last_activity=time.time(),
            max_iterations=3
        )
        
        with patch('auto.integrations.review.GitHubReviewIntegration') as mock_review_class:
            # Setup review integration mock - changes requested
            mock_review = Mock()
            mock_review.check_approval_status.return_value = {
                "approved": False,
                "changes_requested": True,
                "approving_reviewers": [],
                "requesting_changes_reviewers": ["reviewer1"]
            }
            mock_review_class.return_value = mock_review
            
            # Check cycle completion
            result = await check_cycle_completion(state)
            
            # Should request changes
            assert result == ReviewCycleStatus.CHANGES_REQUESTED


class TestAIUpdate:
    """Test AI update functionality."""
    
    @pytest.mark.asyncio
    async def test_trigger_ai_update_success(self, sample_review_comments):
        """Test successful AI update execution."""
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.AI_UPDATE_IN_PROGRESS,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=sample_review_comments,
            last_activity=time.time(),
            max_iterations=3
        )
        
        # Mock AI response
        ai_response = AIResponse(
            success=True,
            response_type="review_update",
            content="Successfully addressed all review comments",
            summary="Updated code to fix issues"
        )
        
        with patch('auto.integrations.ai.ClaudeIntegration') as mock_ai_class:
            # Setup AI integration mock
            mock_ai = Mock()
            mock_ai.execute_update_from_review.return_value = ai_response
            mock_ai_class.return_value = mock_ai
            
            # Execute AI update
            await trigger_ai_update(state)
            
            # Verify AI update was called
            mock_ai.execute_update_from_review.assert_called_once()
            
            # Verify state was updated
            assert len(state.ai_reviews) == 1
            assert state.ai_reviews[0]["type"] == "update"
            assert state.ai_reviews[0]["status"] == "completed"
            assert state.ai_reviews[0]["comments_addressed"] == 2
    
    @pytest.mark.asyncio
    async def test_trigger_ai_update_no_comments(self):
        """Test AI update when no unresolved comments."""
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.AI_UPDATE_IN_PROGRESS,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],  # No comments to address
            last_activity=time.time(),
            max_iterations=3
        )
        
        # Execute AI update
        await trigger_ai_update(state)
        
        # Should return early without calling AI
        assert len(state.ai_reviews) == 0


class TestInitiateReviewCycle:
    """Test review cycle initiation."""
    
    @pytest.mark.asyncio
    async def test_initiate_review_cycle(self, mock_config):
        """Test review cycle initiation for existing PR."""
        with patch('auto.workflows.review.execute_review_cycle') as mock_execute:
            mock_state = ReviewCycleState(
                pr_number=123,
                repository="owner/repo",
                iteration=1,
                status=ReviewCycleStatus.APPROVED,
                ai_reviews=[],
                human_reviews=[],
                unresolved_comments=[],
                last_activity=time.time(),
                max_iterations=3
            )
            mock_execute.return_value = mock_state
            
            # Initiate review cycle
            result = await initiate_review_cycle(123, "owner/repo")
            
            # Verify execution was called
            mock_execute.assert_called_once_with(123, "owner/repo")
            assert result == mock_state


class TestReviewCycleState:
    """Test review cycle state management."""
    
    def test_review_cycle_state_creation(self):
        """Test review cycle state creation."""
        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=0,
            status=ReviewCycleStatus.PENDING,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=time.time(),
            max_iterations=5
        )
        
        assert state.pr_number == 123
        assert state.repository == "owner/repo"
        assert state.status == ReviewCycleStatus.PENDING
        assert state.iteration == 0
        assert state.max_iterations == 5
    
    def test_review_cycle_status_enum(self):
        """Test review cycle status enumeration."""
        # Verify all expected statuses exist
        assert ReviewCycleStatus.PENDING.value == "pending"
        assert ReviewCycleStatus.AI_REVIEW_IN_PROGRESS.value == "ai_review_in_progress"
        assert ReviewCycleStatus.WAITING_FOR_HUMAN.value == "waiting_for_human"
        assert ReviewCycleStatus.APPROVED.value == "approved"
        assert ReviewCycleStatus.CHANGES_REQUESTED.value == "changes_requested"
        assert ReviewCycleStatus.MAX_ITERATIONS_REACHED.value == "max_iterations_reached"
        assert ReviewCycleStatus.FAILED.value == "failed"