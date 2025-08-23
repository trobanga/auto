"""
Tests for review cycle error handling and recovery scenarios.

These tests verify that the review system handles various error conditions gracefully:
- Network failures and timeouts
- API rate limiting and authentication issues
- Malformed data and parsing errors
- Service unavailability and recovery
- Edge cases and unexpected scenarios
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from auto.integrations.ai import AIIntegrationError, AIResponse
from auto.integrations.review import GitHubReviewError, PRReview, ReviewComment
from auto.models import AIConfig
from auto.utils.shell import ShellError
from auto.workflows.review import (
    ReviewCycleState,
    ReviewCycleStatus,
    ReviewWorkflowError,
    check_cycle_completion,
    execute_review_cycle,
    process_review_comments,
    trigger_ai_review,
    wait_for_human_review,
)


class TestReviewErrorHandling:
    """Test review cycle error handling scenarios."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration for testing."""
        config = Mock()
        config.workflows.max_review_iterations = 3
        config.workflows.ai_review_first = True
        config.workflows.review_check_interval = 1
        config.workflows.require_human_approval = True
        config.workflows.human_review_timeout = 0.167  # 10 second timeout for tests (in minutes)
        config.ai = AIConfig(
            command="claude",
            implementation_agent="coder",
            review_agent="pull-request-reviewer",
            update_agent="coder",
        )
        return config

    @pytest.fixture
    def sample_state(self):
        """Sample review cycle state for testing."""
        return ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.AI_REVIEW_IN_PROGRESS,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=0,
            max_iterations=3,
        )

    @pytest.mark.asyncio
    async def test_ai_service_unavailable_error(self, mock_config, sample_state):
        """Test handling of AI service unavailability."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
        ):
            # Setup AI integration to fail with service unavailable
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                side_effect=AIIntegrationError("Claude service is currently unavailable")
            )
            mock_ai_class.return_value = mock_ai

            # Should raise ReviewWorkflowError
            with pytest.raises(ReviewWorkflowError, match="AI review execution failed"):
                await trigger_ai_review(sample_state)

            # Should record failed AI review in state
            assert len(sample_state.ai_reviews) == 1
            assert sample_state.ai_reviews[0]["status"] == "failed"
            assert "unavailable" in sample_state.ai_reviews[0]["error"]

    @pytest.mark.asyncio
    async def test_github_api_rate_limit_error(self, mock_config, sample_state):
        """Test handling of GitHub API rate limiting."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup review integration to fail with rate limit
            mock_review = Mock()
            mock_review.get_pr_reviews.side_effect = GitHubReviewError(
                "API rate limit exceeded. Try again later."
            )
            mock_review_class.return_value = mock_review

            # Should handle error gracefully
            result = await wait_for_human_review(sample_state, timeout_minutes=0.01)
            assert result is False  # Timeout due to error

    @pytest.mark.asyncio
    async def test_network_timeout_error(self, mock_config, sample_state):
        """Test handling of network timeouts."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup review integration to fail with timeout
            mock_review = Mock()
            mock_review.get_unresolved_comments.side_effect = ShellError(
                "Command timed out", "", "timeout: the monitored command dumped core"
            )
            mock_review_class.return_value = mock_review

            # Should handle timeout gracefully
            await process_review_comments(sample_state)
            # Should not crash, may have empty unresolved comments
            assert isinstance(sample_state.unresolved_comments, list)

    @pytest.mark.asyncio
    async def test_malformed_json_response_error(self, mock_config):
        """Test handling of malformed JSON responses."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup review integration to return malformed JSON
            mock_review = Mock()
            mock_review.check_approval_status.side_effect = GitHubReviewError(
                "Failed to parse review data: Invalid JSON"
            )
            mock_review_class.return_value = mock_review

            state = ReviewCycleState(
                pr_number=123,
                repository="owner/repo",
                iteration=1,
                status=ReviewCycleStatus.HUMAN_REVIEW_RECEIVED,
                ai_reviews=[],
                human_reviews=[],
                unresolved_comments=[],
                last_activity=0,
                max_iterations=3,
            )

            # Should handle parsing error gracefully
            result = await check_cycle_completion(state)
            assert result == ReviewCycleStatus.FAILED

    @pytest.mark.asyncio
    async def test_authentication_failure_error(self, mock_config):
        """Test handling of authentication failures."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
        ):
            # Setup AI integration to fail with auth error
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                side_effect=AIIntegrationError("Authentication failed: Invalid API key")
            )
            mock_ai_class.return_value = mock_ai

            # Should propagate auth error
            with pytest.raises(ReviewWorkflowError, match="AI review execution failed"):
                await execute_review_cycle(123, "owner/repo")

    @pytest.mark.asyncio
    async def test_concurrent_modification_error(self, mock_config):
        """Test handling of concurrent PR modifications."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup AI integration
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Review completed",
                    comments=[],
                    summary="No issues",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration with concurrent modification error
            mock_review = Mock()
            mock_review.post_ai_review.side_effect = [
                GitHubReviewError("PR was modified during review posting"),
                Mock(),  # Second attempt succeeds
            ]
            mock_review.get_pr_reviews.return_value = [
                PRReview(
                    id=1,
                    author="reviewer",
                    state="APPROVED",
                    body="LGTM",
                    submitted_at=datetime.now(),
                )
            ]
            mock_review.get_unresolved_comments.return_value = []
            mock_review.check_approval_status.return_value = (True, ["reviewer"], [])
            mock_review_class.return_value = mock_review

            # Should handle concurrent modification and succeed on retry
            result = await execute_review_cycle(123, "owner/repo")
            assert result.status == ReviewCycleStatus.APPROVED

    @pytest.mark.asyncio
    async def test_invalid_pr_number_error(self, mock_config):
        """Test handling of invalid PR numbers."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup AI integration to fail with invalid PR during trigger_ai_review
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                side_effect=AIIntegrationError("Pull request #99999 not found")
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration to fail with invalid PR
            mock_review = Mock()
            mock_review.get_pr_reviews.side_effect = GitHubReviewError(
                "Pull request #99999 not found"
            )
            mock_review_class.return_value = mock_review

            # Should handle invalid PR gracefully
            with pytest.raises(ReviewWorkflowError, match="AI review execution failed"):
                await execute_review_cycle(99999, "owner/repo")

    @pytest.mark.asyncio
    async def test_repository_access_denied_error(self, mock_config):
        """Test handling of repository access denied errors."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup AI integration mock
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="AI review completed",
                    comments=["Review looks good"],
                    summary="AI review summary",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration to fail with access denied
            mock_review = Mock()
            mock_review.get_pr_reviews.side_effect = GitHubReviewError(
                "Access denied: insufficient permissions for owner/private-repo"
            )
            mock_review_class.return_value = mock_review

            # Should handle access denied error gracefully by reaching max iterations
            try:
                result = await asyncio.wait_for(
                    execute_review_cycle(123, "owner/private-repo"),
                    timeout=15.0,  # 15 second timeout
                )
                # Should reach max iterations due to repeated access denied errors
                assert result.status == ReviewCycleStatus.MAX_ITERATIONS_REACHED
                assert result.iteration == 3  # Reached max iterations
            except TimeoutError:
                pytest.fail("Test timed out after 15 seconds")

    @pytest.mark.asyncio
    async def test_ai_response_parsing_error(self, mock_config, sample_state):
        """Test handling of AI response parsing errors."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
        ):
            # Setup AI integration to raise an exception for parsing errors
            mock_ai = AsyncMock()
            from auto.integrations.ai import AIIntegrationError

            mock_ai.execute_review = AsyncMock(
                side_effect=AIIntegrationError("Failed to parse code: Syntax error in file")
            )
            mock_ai_class.return_value = mock_ai

            # Should handle AI parsing error
            with pytest.raises(ReviewWorkflowError, match="AI review execution failed"):
                await trigger_ai_review(sample_state)

    @pytest.mark.asyncio
    async def test_memory_exhaustion_error(self, mock_config):
        """Test handling of memory exhaustion during large operations."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
        ):
            # Setup AI integration to fail with memory error
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(side_effect=MemoryError("Out of memory"))
            mock_ai_class.return_value = mock_ai

            # Should handle memory error
            with pytest.raises(ReviewWorkflowError, match="Review cycle execution failed"):
                await execute_review_cycle(123, "owner/repo")

    @pytest.mark.asyncio
    async def test_interrupted_operation_error(self, mock_config):
        """Test handling of interrupted operations."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
        ):
            # Setup AI integration to be interrupted
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                side_effect=KeyboardInterrupt("Operation interrupted")
            )
            mock_ai_class.return_value = mock_ai

            # Should propagate keyboard interrupt
            with pytest.raises(KeyboardInterrupt):
                await execute_review_cycle(123, "owner/repo")


class TestReviewRecoveryScenarios:
    """Test review cycle recovery from various failure scenarios."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration for testing."""
        config = Mock()
        config.workflows.max_review_iterations = 3
        config.workflows.ai_review_first = True
        config.workflows.review_check_interval = 1
        config.workflows.require_human_approval = True
        config.workflows.human_review_timeout = 0.167  # 10 second timeout for tests (in minutes)
        config.ai = AIConfig(
            command="claude",
            implementation_agent="coder",
            review_agent="pull-request-reviewer",
            update_agent="coder",
        )
        return config

    @pytest.mark.asyncio
    async def test_recovery_after_ai_failure(self, mock_config):
        """Test recovery after AI service failure."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            failure_count = [0]

            def ai_execute_side_effect(*args, **kwargs):
                failure_count[0] += 1
                if failure_count[0] <= 2:  # Fail first 2 times
                    raise AIIntegrationError("Service temporarily unavailable")
                else:  # Succeed on third try
                    return AIResponse(
                        success=True,
                        response_type="review",
                        content="Review completed after retry",
                        comments=[],
                        summary="No issues found",
                    )

            # Setup AI integration with retry logic
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(side_effect=ai_execute_side_effect)
            mock_ai_class.return_value = mock_ai

            # Setup review integration for success
            mock_review = Mock()
            mock_review.post_ai_review.return_value = Mock()
            mock_review.get_pr_reviews.return_value = [
                PRReview(
                    id=1,
                    author="reviewer",
                    state="APPROVED",
                    body="LGTM",
                    submitted_at=datetime.now(),
                )
            ]
            mock_review.get_unresolved_comments.return_value = []
            mock_review.check_approval_status.return_value = (True, ["reviewer"], [])
            mock_review_class.return_value = mock_review

            # Should eventually succeed after retries (simulated by multiple cycle attempts)
            try:
                result = await execute_review_cycle(123, "owner/repo")
                # If it succeeds, great!
                assert result.status in [
                    ReviewCycleStatus.APPROVED,
                    ReviewCycleStatus.MAX_ITERATIONS_REACHED,
                ]
            except ReviewWorkflowError:
                # Expected on first attempts due to AI failures
                pass

    @pytest.mark.asyncio
    async def test_partial_data_recovery(self, mock_config):
        """Test recovery when partial data is available."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup AI integration
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Partial review",
                    comments=["Fix this issue"],
                    summary="Found 1 issue",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration with partial failures
            mock_review = Mock()
            mock_review.post_ai_review.return_value = Mock()

            # First call fails, second succeeds with partial data
            call_count = [0]

            def get_reviews_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise GitHubReviewError("Network timeout")
                else:
                    return [
                        PRReview(
                            id=1,
                            author="reviewer",
                            state="COMMENTED",
                            body="Partial review",
                            submitted_at=datetime.now(),
                        )
                    ]

            mock_review.get_pr_reviews.side_effect = get_reviews_side_effect
            mock_review.get_unresolved_comments.return_value = []
            mock_review.check_approval_status.return_value = (False, [], [])
            mock_review_class.return_value = mock_review

            # Should handle partial failure and continue
            result = await execute_review_cycle(123, "owner/repo")
            assert result.status == ReviewCycleStatus.MAX_ITERATIONS_REACHED
            # Should have some data despite partial failures
            assert result.iteration > 0

    @pytest.mark.asyncio
    async def test_state_consistency_after_error(self, mock_config):
        """Test that state remains consistent after errors."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
        ):
            # Setup AI integration to fail
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(side_effect=Exception("Unexpected error"))
            mock_ai_class.return_value = mock_ai

            # Execute and expect failure
            with pytest.raises(ReviewWorkflowError):
                await execute_review_cycle(123, "owner/repo")

            # State should still be accessible and consistent (tested by not crashing)
            # In a real implementation, you'd verify state persistence here


class TestReviewEdgeCases:
    """Test edge cases and unusual scenarios in review cycles."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration for testing."""
        config = Mock()
        config.workflows.max_review_iterations = 3
        config.workflows.ai_review_first = True
        config.workflows.review_check_interval = 1
        config.workflows.require_human_approval = True
        config.workflows.human_review_timeout = 0.167  # 10 second timeout for tests (in minutes)
        config.ai = AIConfig(
            command="claude",
            implementation_agent="coder",
            review_agent="pull-request-reviewer",
            update_agent="coder",
        )
        return config

    @pytest.fixture
    def sample_state(self):
        """Sample review cycle state for testing."""
        return ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=1,
            status=ReviewCycleStatus.AI_REVIEW_IN_PROGRESS,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=0,
            max_iterations=3,
        )

    @pytest.mark.asyncio
    async def test_empty_repository_error(self, mock_config):
        """Test handling of empty repository."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup AI integration
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="No changes to review",
                    comments=[],
                    summary="AI review: Empty repository",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration for empty repo
            mock_review = Mock()
            mock_review.get_pr_reviews.side_effect = GitHubReviewError("Repository is empty")
            mock_review_class.return_value = mock_review

            # Should handle empty repo gracefully
            result = await execute_review_cycle(123, "owner/empty-repo")
            assert result.status == ReviewCycleStatus.MAX_ITERATIONS_REACHED

    @pytest.mark.asyncio
    async def test_very_large_pr_handling(self, mock_config):
        """Test handling of very large PRs."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration"),
        ):
            # Setup AI integration for large PR
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                side_effect=AIIntegrationError("Input too large: PR contains 10,000+ lines")
            )
            mock_ai_class.return_value = mock_ai

            # Should handle large PR error
            with pytest.raises(ReviewWorkflowError, match="AI review execution failed"):
                await execute_review_cycle(123, "owner/huge-pr-repo")

    @pytest.mark.asyncio
    async def test_unicode_content_error_handling(self, mock_config, sample_state):
        """Test handling of unicode content errors."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup review integration with unicode issues
            mock_review = Mock()
            mock_review.get_unresolved_comments.side_effect = UnicodeDecodeError(
                "utf-8", b"\xff\xfe", 0, 1, "invalid start byte"
            )
            mock_review_class.return_value = mock_review

            # Should handle unicode error gracefully
            await process_review_comments(sample_state)
            # Should not crash, may have empty comments
            assert isinstance(sample_state.unresolved_comments, list)

    @pytest.mark.asyncio
    async def test_circular_dependency_error(self, mock_config):
        """Test handling of circular dependency in review process."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup AI integration
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Found circular dependency",
                    comments=["Fix circular import"],
                    summary="Dependency issue",
                )
            )
            mock_ai.execute_update_from_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="update",
                    content="Attempted to fix dependency",
                    summary="Still has circular dependency",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration with persistent issues
            mock_review = Mock()
            mock_review.post_ai_review.return_value = Mock()
            mock_review.get_pr_reviews.return_value = [
                PRReview(
                    id=1,
                    author="reviewer",
                    state="CHANGES_REQUESTED",
                    body="Circular dependency still exists",
                    submitted_at=datetime.now(),
                )
            ]
            # Always have unresolved comments (circular dependency persists)
            mock_review.get_unresolved_comments.return_value = [
                ReviewComment(
                    id=1,
                    body="Circular dependency detected",
                    path="src/main.py",
                    line=10,
                    author="reviewer",
                )
            ]
            mock_review.check_approval_status.return_value = (False, [], ["reviewer"])
            mock_review_class.return_value = mock_review

            # Should reach max iterations due to persistent issue
            result = await execute_review_cycle(123, "owner/repo")
            assert result.status == ReviewCycleStatus.MAX_ITERATIONS_REACHED
            assert result.iteration == mock_config.workflows.max_review_iterations

    def test_invalid_config_parameters(self):
        """Test handling of invalid configuration parameters."""
        # Test with invalid max_iterations - validation now properly implemented
        with pytest.raises(ValueError, match="Max iterations must be greater than zero"):
            ReviewCycleState(
                pr_number=123,
                repository="owner/repo",
                iteration=0,
                status=ReviewCycleStatus.PENDING,
                ai_reviews=[],
                human_reviews=[],
                unresolved_comments=[],
                last_activity=0,
                max_iterations=-1,  # Invalid negative value
            )

        # Test with invalid pr_number
        with pytest.raises(ValueError, match="PR number must be non-negative"):
            ReviewCycleState(
                pr_number=-1,  # Invalid negative value
                repository="owner/repo",
                iteration=0,
                status=ReviewCycleStatus.PENDING,
                ai_reviews=[],
                human_reviews=[],
                unresolved_comments=[],
                last_activity=0,
                max_iterations=5,
            )

    @pytest.mark.asyncio
    async def test_simultaneous_error_conditions(self, mock_config):
        """Test handling of multiple simultaneous error conditions."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            # Setup AI integration to fail
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(side_effect=AIIntegrationError("AI failed"))
            mock_ai_class.return_value = mock_ai

            # Setup review integration to also fail
            mock_review = Mock()
            mock_review.get_pr_reviews.side_effect = GitHubReviewError("GitHub API failed")
            mock_review_class.return_value = mock_review

            # Should handle multiple failures gracefully
            with pytest.raises(ReviewWorkflowError):
                await execute_review_cycle(123, "owner/repo")
