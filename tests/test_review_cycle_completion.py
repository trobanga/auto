"""
Tests for review cycle completion logic and end-to-end workflow validation.

These tests verify that review cycles complete correctly under various scenarios:
- Simple approval flows
- Multi-iteration cycles with review comments
- Edge cases and failure scenarios
- State transitions and persistence
"""

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from auto.integrations.ai import AIResponse
from auto.integrations.review import PRReview, ReviewComment
from auto.models import AIConfig
from auto.workflows.review import (
    ReviewCycleState,
    ReviewCycleStatus,
    ReviewWorkflowError,
    check_cycle_completion,
    execute_review_cycle,
)


class TestReviewCycleCompletion:
    """Test complete review cycle execution scenarios."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration for testing."""
        config = Mock()
        config.workflows.max_review_iterations = 5
        config.workflows.ai_review_first = True
        config.workflows.review_check_interval = 1  # Fast polling for tests
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
    async def test_single_iteration_approval_cycle(self, mock_config):
        """Test review cycle that completes in single iteration."""
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
                    content="Code looks good overall",
                    comments=["Minor: Consider adding more comments"],
                    summary="AI review completed",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration mock
            mock_review = Mock()
            mock_review.post_ai_review.return_value = Mock()

            # Mock human reviews - immediate approval
            mock_human_reviews = [
                PRReview(
                    id=1,
                    author="human_reviewer",
                    state="APPROVED",
                    body="LGTM!",
                    submitted_at=datetime.now(),
                )
            ]
            mock_review.get_pr_reviews.return_value = mock_human_reviews
            mock_review.get_unresolved_comments.return_value = []
            mock_review.check_approval_status.return_value = (True, ["human_reviewer"], [])
            mock_review_class.return_value = mock_review

            # Execute review cycle
            result = await execute_review_cycle(pr_number=123, repository="owner/repo")

            # Verify single iteration approval
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration == 1
            assert len(result.ai_reviews) == 1
            assert len(result.human_reviews) == 1
            assert result.ai_reviews[0]["status"] == "completed"

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)  # 30 second timeout
    async def test_multi_iteration_cycle_with_changes(self, mock_config):
        """Test review cycle with multiple iterations requiring changes."""
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
                    content="Found several issues",
                    comments=["Fix error handling", "Add input validation"],
                    summary="AI review found issues",
                )
            )
            mock_ai.execute_update_from_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="update",
                    content="Fixed issues",
                    summary="Updated code based on review",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration mock
            mock_review = Mock()
            mock_review.post_ai_review.return_value = Mock()

            # Mock human reviews - changes requested, then approved
            iteration_counter = [0]

            def get_reviews_side_effect(*args, **kwargs):
                iteration_counter[0] += 1
                if iteration_counter[0] <= 2:  # First two calls - changes requested
                    return [
                        PRReview(
                            id=1,
                            author="human_reviewer",
                            state="CHANGES_REQUESTED",
                            body="Please fix the error handling",
                            submitted_at=datetime.now(),
                        )
                    ]
                else:  # Third call - approved
                    return [
                        PRReview(
                            id=1,
                            author="human_reviewer",
                            state="CHANGES_REQUESTED",
                            body="Please fix the error handling",
                            submitted_at=datetime.now() - timedelta(minutes=5),
                        ),
                        PRReview(
                            id=2,
                            author="human_reviewer",
                            state="APPROVED",
                            body="Looks good now!",
                            submitted_at=datetime.now(),
                        ),
                    ]

            mock_review.get_pr_reviews.side_effect = get_reviews_side_effect

            # Mock unresolved comments - present first, then resolved
            def get_unresolved_side_effect(*args, **kwargs):
                if iteration_counter[0] <= 2:
                    return [
                        ReviewComment(
                            id=1,
                            body="Fix error handling",
                            path="src/main.py",
                            line=45,
                            author="human_reviewer",
                        )
                    ]
                else:
                    return []  # Comments resolved

            mock_review.get_unresolved_comments.side_effect = get_unresolved_side_effect

            # Mock approval status
            def check_approval_side_effect(*args, **kwargs):
                if iteration_counter[0] <= 2:
                    return (False, [], ["human_reviewer"])
                else:
                    return (True, ["human_reviewer"], [])

            mock_review.check_approval_status.side_effect = check_approval_side_effect
            mock_review_class.return_value = mock_review

            # Execute review cycle with timeout protection
            try:
                result = await asyncio.wait_for(
                    execute_review_cycle(pr_number=123, repository="owner/repo"),
                    timeout=20.0,  # 20 second timeout
                )
            except TimeoutError:
                pytest.fail("Review cycle test timed out after 20 seconds")

            # Verify multi-iteration completion
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration == 2  # Two iterations needed
            assert len(result.ai_reviews) >= 2  # AI review + AI update
            assert len(result.human_reviews) >= 1

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)  # 30 second timeout
    async def test_cycle_reaches_max_iterations(self, mock_config):
        """Test review cycle reaching maximum iterations."""
        mock_config.workflows.max_review_iterations = 2  # Low limit for testing

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
                    content="Found issues",
                    comments=["Fix this"],
                    summary="AI review",
                )
            )
            mock_ai.execute_update_from_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="update",
                    content="Attempted fix",
                    summary="Updated code",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration mock - always requesting changes
            mock_review = Mock()
            mock_review.post_ai_review.return_value = Mock()
            mock_review.get_pr_reviews.return_value = [
                PRReview(
                    id=1,
                    author="human_reviewer",
                    state="CHANGES_REQUESTED",
                    body="Still needs work",
                    submitted_at=datetime.now(),
                )
            ]
            mock_review.get_unresolved_comments.return_value = [
                ReviewComment(
                    id=1,
                    body="Still not fixed",
                    path="src/main.py",
                    line=45,
                    author="human_reviewer",
                )
            ]
            mock_review.check_approval_status.return_value = (False, [], ["human_reviewer"])
            mock_review_class.return_value = mock_review

            # Execute review cycle with timeout protection
            try:
                result = await asyncio.wait_for(
                    execute_review_cycle(pr_number=123, repository="owner/repo"),
                    timeout=20.0,  # 20 second timeout
                )
            except TimeoutError:
                pytest.fail("Review cycle test timed out after 20 seconds")

            # Verify max iterations reached
            assert result.status == ReviewCycleStatus.MAX_ITERATIONS_REACHED
            assert result.iteration == 2  # Reached max

    @pytest.mark.asyncio
    async def test_cycle_completion_with_no_human_review(self, mock_config):
        """Test review cycle behavior when no human review is received."""
        # Configure very short timeout for this test
        mock_config.workflows.human_review_timeout = 0.01  # 0.01 minutes = 0.6 seconds

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
                    comments=[],
                    summary="No issues found",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration mock - no human reviews
            mock_review = Mock()
            mock_review.post_ai_review.return_value = Mock()
            mock_review.get_pr_reviews.return_value = []  # No human reviews
            mock_review.get_unresolved_comments.return_value = []
            mock_review.check_approval_status.return_value = (False, [], [])
            mock_review_class.return_value = mock_review

            # Execute review cycle - should timeout quickly and reach max iterations
            result = await execute_review_cycle(pr_number=123, repository="owner/repo")

            # Should reach max iterations without human approval
            assert result.status == ReviewCycleStatus.MAX_ITERATIONS_REACHED
            assert len(result.human_reviews) == 0

    @pytest.mark.asyncio
    async def test_cycle_with_ai_review_failure(self, mock_config):
        """Test review cycle handling AI review failures."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
        ):
            # Setup AI integration mock to fail
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(side_effect=Exception("AI service unavailable"))
            mock_ai_class.return_value = mock_ai

            # Execute review cycle - should fail
            with pytest.raises(ReviewWorkflowError, match="Review cycle execution failed"):
                await execute_review_cycle(pr_number=123, repository="owner/repo")

    @pytest.mark.asyncio
    async def test_check_cycle_completion_various_states(self, mock_config):
        """Test cycle completion checker with various PR states."""
        with (
            patch("auto.workflows.review.get_config", return_value=mock_config),
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
        ):
            mock_review = Mock()
            mock_review_class.return_value = mock_review

            # Test state 1: Approved with no unresolved comments
            state = ReviewCycleState(
                pr_number=123,
                repository="owner/repo",
                iteration=1,
                status=ReviewCycleStatus.HUMAN_REVIEW_RECEIVED,
                ai_reviews=[],
                human_reviews=[],
                unresolved_comments=[],
                last_activity=time.time(),
                max_iterations=5,
            )

            mock_review.check_approval_status.return_value = (True, ["reviewer1"], [])

            result = await check_cycle_completion(state)
            assert result == ReviewCycleStatus.APPROVED

            # Test state 2: Changes requested with unresolved comments
            state.unresolved_comments = [
                ReviewComment(id=1, body="Fix this", path="src/main.py", line=10)
            ]
            mock_review.check_approval_status.return_value = (False, [], ["reviewer1"])

            result = await check_cycle_completion(state)
            assert result == ReviewCycleStatus.CHANGES_REQUESTED

            # Test state 3: No clear direction
            state.unresolved_comments = []
            mock_review.check_approval_status.return_value = (False, [], [])

            result = await check_cycle_completion(state)
            assert result == ReviewCycleStatus.WAITING_FOR_HUMAN

    @pytest.mark.asyncio
    async def test_cycle_with_concurrent_reviews(self, mock_config):
        """Test review cycle with multiple concurrent reviewers."""
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
                    content="AI review",
                    comments=[],
                    summary="AI review completed",
                )
            )
            mock_ai.execute_update_from_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="update",
                    content="AI update based on reviews",
                    summary="Updated based on feedback",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration mock - multiple reviewers
            mock_review = Mock()
            mock_review.post_ai_review.return_value = Mock()
            mock_review.get_pr_reviews.return_value = [
                PRReview(
                    id=1,
                    author="reviewer1",
                    state="APPROVED",
                    body="LGTM",
                    submitted_at=datetime.now(),
                ),
                PRReview(
                    id=2,
                    author="reviewer2",
                    state="CHANGES_REQUESTED",
                    body="Needs work",
                    submitted_at=datetime.now(),
                ),
                PRReview(
                    id=3,
                    author="reviewer3",
                    state="COMMENTED",
                    body="Some suggestions",
                    submitted_at=datetime.now(),
                ),
            ]
            mock_review.get_unresolved_comments.return_value = [
                ReviewComment(
                    id=1, body="Change this", path="src/main.py", line=10, author="reviewer2"
                )
            ]
            # One approval, one change request - should continue cycle
            mock_review.check_approval_status.return_value = (False, ["reviewer1"], ["reviewer2"])
            mock_review_class.return_value = mock_review

            # Execute review cycle
            result = await execute_review_cycle(pr_number=123, repository="owner/repo")

            # Should reach max iterations due to conflicting reviews
            assert result.status == ReviewCycleStatus.MAX_ITERATIONS_REACHED
            assert len(result.human_reviews) >= 3  # All reviewers captured


class TestReviewCyclePerformance:
    """Performance tests for review cycle completion."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration for performance testing."""
        config = Mock()
        config.workflows.max_review_iterations = 10
        config.workflows.ai_review_first = True
        config.workflows.review_check_interval = 1  # Very fast polling
        config.workflows.require_human_approval = True
        config.ai = AIConfig(
            command="claude",
            implementation_agent="coder",
            review_agent="pull-request-reviewer",
            update_agent="coder",
        )
        return config

    @pytest.mark.asyncio
    async def test_large_scale_review_cycle_performance(self, mock_config):
        """Test review cycle performance with large amounts of data."""
        import time

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
                    content="Large AI review",
                    comments=[f"Issue {i}: Fix this" for i in range(100)],  # 100 comments
                    summary="AI found 100 issues",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup review integration mock with large dataset
            mock_review = Mock()
            mock_review.post_ai_review.return_value = Mock()

            # Generate large number of human reviews
            large_reviews = [
                PRReview(
                    id=i,
                    author=f"reviewer{i % 10}",
                    state="APPROVED" if i % 2 == 0 else "CHANGES_REQUESTED",
                    body=f"Review {i}",
                    submitted_at=datetime.now(),
                )
                for i in range(1, 51)  # 50 reviews
            ]

            mock_review.get_pr_reviews.return_value = large_reviews
            mock_review.get_unresolved_comments.return_value = []  # Resolved for quick completion
            mock_review.check_approval_status.return_value = (
                True,
                [f"reviewer{i}" for i in range(10)],
                [],
            )
            mock_review_class.return_value = mock_review

            # Measure execution time
            start_time = time.time()
            result = await execute_review_cycle(pr_number=123, repository="owner/repo")
            end_time = time.time()

            execution_time = end_time - start_time

            # Should complete within reasonable time despite large dataset
            assert execution_time < 5.0  # 5 seconds max
            assert result.status == ReviewCycleStatus.APPROVED
            assert len(result.human_reviews) == 50

    @pytest.mark.asyncio
    async def test_concurrent_review_cycles(self, mock_config):
        """Test multiple concurrent review cycles."""

        async def run_review_cycle(pr_number):
            """Run a single review cycle."""
            with (
                patch("auto.workflows.review.get_config", return_value=mock_config),
                patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
                patch("auto.workflows.review.GitHubReviewIntegration") as mock_review_class,
            ):
                # Setup mocks for quick completion
                mock_ai = AsyncMock()
                mock_ai.execute_review = AsyncMock(
                    return_value=AIResponse(
                        success=True,
                        response_type="review",
                        content="Quick review",
                        comments=[],
                        summary="No issues",
                    )
                )
                mock_ai_class.return_value = mock_ai

                mock_review = Mock()
                mock_review.post_ai_review.return_value = Mock()
                mock_review.get_pr_reviews.return_value = [
                    PRReview(
                        id=1,
                        author="auto_reviewer",
                        state="APPROVED",
                        body="Auto-approved",
                        submitted_at=datetime.now(),
                    )
                ]
                mock_review.get_unresolved_comments.return_value = []
                mock_review.check_approval_status.return_value = (True, ["auto_reviewer"], [])
                mock_review_class.return_value = mock_review

                return await execute_review_cycle(pr_number, "owner/repo")

        # Run multiple concurrent cycles
        tasks = [run_review_cycle(i) for i in range(100, 110)]  # 10 concurrent cycles

        start_time = time.time()
        results = await asyncio.gather(*tasks)
        end_time = time.time()

        execution_time = end_time - start_time

        # All cycles should complete successfully
        assert len(results) == 10
        assert all(result.status == ReviewCycleStatus.APPROVED for result in results)

        # Concurrent execution should be faster than sequential
        assert execution_time < 10.0  # Much faster than 10 sequential cycles


class TestReviewCycleStateTransitions:
    """Test review cycle state transitions and persistence."""

    def test_review_cycle_state_creation_and_updates(self):
        """Test review cycle state object creation and updates."""
        initial_time = time.time()

        state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=0,
            status=ReviewCycleStatus.PENDING,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=initial_time,
            max_iterations=5,
        )

        # Test initial state
        assert state.pr_number == 123
        assert state.repository == "owner/repo"
        assert state.iteration == 0
        assert state.status == ReviewCycleStatus.PENDING
        assert len(state.ai_reviews) == 0
        assert len(state.human_reviews) == 0
        assert len(state.unresolved_comments) == 0
        assert state.last_activity == initial_time
        assert state.max_iterations == 5

        # Test state updates
        state.iteration += 1
        state.status = ReviewCycleStatus.AI_REVIEW_IN_PROGRESS
        state.ai_reviews.append({"iteration": 1, "timestamp": time.time(), "status": "completed"})
        state.last_activity = time.time()

        assert state.iteration == 1
        assert state.status == ReviewCycleStatus.AI_REVIEW_IN_PROGRESS
        assert len(state.ai_reviews) == 1
        assert state.last_activity > initial_time

    def test_review_cycle_status_transitions(self):
        """Test valid review cycle status transitions."""
        # Valid transition sequence
        valid_transitions = [
            ReviewCycleStatus.PENDING,
            ReviewCycleStatus.AI_REVIEW_IN_PROGRESS,
            ReviewCycleStatus.WAITING_FOR_HUMAN,
            ReviewCycleStatus.HUMAN_REVIEW_RECEIVED,
            ReviewCycleStatus.AI_UPDATE_IN_PROGRESS,
            ReviewCycleStatus.CHANGES_REQUESTED,
            ReviewCycleStatus.WAITING_FOR_HUMAN,
            ReviewCycleStatus.HUMAN_REVIEW_RECEIVED,
            ReviewCycleStatus.APPROVED,
        ]

        # All statuses should be valid enum values
        for status in valid_transitions:
            assert isinstance(status, ReviewCycleStatus)
            assert status.value in [
                "pending",
                "ai_review_in_progress",
                "waiting_for_human",
                "human_review_received",
                "ai_update_in_progress",
                "changes_requested",
                "approved",
                "max_iterations_reached",
                "failed",
            ]

    def test_review_cycle_state_serialization(self):
        """Test review cycle state can be serialized/deserialized."""
        original_state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=2,
            status=ReviewCycleStatus.APPROVED,
            ai_reviews=[
                {
                    "iteration": 1,
                    "timestamp": time.time(),
                    "status": "completed",
                    "comments_count": 5,
                }
            ],
            human_reviews=[
                {
                    "iteration": 2,
                    "timestamp": time.time(),
                    "author": "reviewer1",
                    "state": "APPROVED",
                }
            ],
            unresolved_comments=[],
            last_activity=time.time(),
            max_iterations=5,
        )

        # Convert to dict (simulating serialization)
        state_dict = {
            "pr_number": original_state.pr_number,
            "repository": original_state.repository,
            "iteration": original_state.iteration,
            "status": original_state.status.value,
            "ai_reviews": original_state.ai_reviews,
            "human_reviews": original_state.human_reviews,
            "unresolved_comments": [
                {
                    "id": comment.id,
                    "body": comment.body,
                    "path": comment.path,
                    "line": comment.line,
                    "author": comment.author,
                    "resolved": comment.resolved,
                }
                for comment in original_state.unresolved_comments
            ],
            "last_activity": original_state.last_activity,
            "max_iterations": original_state.max_iterations,
        }

        # Reconstruct state (simulating deserialization)
        reconstructed_state = ReviewCycleState(
            pr_number=state_dict["pr_number"],
            repository=state_dict["repository"],
            iteration=state_dict["iteration"],
            status=ReviewCycleStatus(state_dict["status"]),
            ai_reviews=state_dict["ai_reviews"],
            human_reviews=state_dict["human_reviews"],
            unresolved_comments=[
                ReviewComment(
                    id=comment["id"],
                    body=comment["body"],
                    path=comment["path"],
                    line=comment["line"],
                    author=comment["author"],
                    resolved=comment["resolved"],
                )
                for comment in state_dict["unresolved_comments"]
            ],
            last_activity=state_dict["last_activity"],
            max_iterations=state_dict["max_iterations"],
        )

        # Verify reconstruction
        assert reconstructed_state.pr_number == original_state.pr_number
        assert reconstructed_state.repository == original_state.repository
        assert reconstructed_state.iteration == original_state.iteration
        assert reconstructed_state.status == original_state.status
        assert len(reconstructed_state.ai_reviews) == len(original_state.ai_reviews)
        assert len(reconstructed_state.human_reviews) == len(original_state.human_reviews)
        assert reconstructed_state.last_activity == original_state.last_activity
        assert reconstructed_state.max_iterations == original_state.max_iterations
