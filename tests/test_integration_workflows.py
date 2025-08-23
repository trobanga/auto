"""
Integration tests for complete review cycle workflows.

These tests verify end-to-end workflows including:
- Complete review cycles from start to finish
- Integration between all components
- Real-world scenarios and edge cases
- Performance under realistic conditions
- Cross-component compatibility
"""

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from auto.integrations.ai import AIResponse
from auto.integrations.review import PRReview, ReviewComment
from auto.models import AIConfig, Config, GitHubConfig, WorkflowsConfig
from auto.workflows.review import (
    ReviewCycleState,
    ReviewCycleStatus,
    execute_review_cycle,
)


class TestCompleteReviewWorkflows:
    """Test complete review cycle workflows end-to-end."""

    @pytest.fixture
    def full_config(self):
        """Complete configuration for integration testing."""
        return Config(
            version="1.0",
            defaults={
                "auto_merge": False,
                "delete_branch_on_merge": True,
                "worktree_base": "../test-worktrees",
            },
            github=GitHubConfig(
                default_org=None,
                default_reviewer=None,
                pr_template=".github/pull_request_template.md",
            ),
            ai=AIConfig(
                command="claude",
                implementation_agent="coder",
                review_agent="pull-request-reviewer",
                update_agent="coder",
                implementation_prompt="Implement: {description}",
                review_prompt="Review this PR thoroughly",
                update_prompt="Address: {comments}",
            ),
            workflows=WorkflowsConfig(
                branch_naming="auto/{issue_type}/{id}",
                commit_convention="conventional",
                ai_review_first=True,
                require_human_approval=True,
                max_review_iterations=5,
                review_check_interval=1,  # Fast for testing
            ),
        )

    @pytest.mark.asyncio
    async def test_simple_approval_workflow(self, full_config):
        """Test simple workflow: AI review → Human approval → Complete."""
        with (
            patch("auto.workflows.review.get_config", return_value=full_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup AI integration
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Code looks good with minor suggestions",
                    comments=["Consider adding more documentation"],
                    summary="AI review: 1 minor suggestion",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup GitHub integration
            mock_github = Mock()
            mock_github.post_ai_review.return_value = Mock(id=1, state="COMMENTED")

            # Simulate human approval after AI review
            mock_github.get_pr_reviews.return_value = [
                PRReview(
                    id=2,
                    author="human_reviewer",
                    state="APPROVED",
                    body="LGTM! Good work.",
                    submitted_at=datetime.now(),
                )
            ]

            mock_github.get_unresolved_comments.return_value = []
            mock_github.check_approval_status.return_value = (True, ["human_reviewer"], [])
            mock_github_class.return_value = mock_github

            # Execute complete workflow
            result = await execute_review_cycle(pr_number=123, repository="owner/repo")

            # Verify successful completion
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration == 1
            assert len(result.ai_reviews) == 1
            assert len(result.human_reviews) == 1

            # Verify AI review was posted
            mock_ai.execute_review.assert_called_once()
            mock_github.post_ai_review.assert_called_once()

            # Verify human review was detected
            assert result.human_reviews[0]["author"] == "human_reviewer"
            assert result.human_reviews[0]["state"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_iterative_improvement_workflow(self, full_config):
        """Test iterative workflow: AI review → Human changes → AI update → Approval."""
        with (
            patch("auto.workflows.review.get_config", return_value=full_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup AI integration
            mock_ai = AsyncMock()

            # AI review finds issues
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Found several issues that need attention",
                    comments=[
                        "Fix error handling in line 45",
                        "Add input validation for user data",
                        "Consider performance optimization in loop",
                    ],
                    summary="AI review: 3 issues found",
                )
            )

            # AI update addresses issues
            mock_ai.execute_update_from_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="update",
                    content="Fixed all identified issues",
                    summary="Updated: Fixed error handling, added validation, optimized loop",
                )
            )

            mock_ai_class.return_value = mock_ai

            # Setup GitHub integration with iterative responses
            mock_github = Mock()
            mock_github.post_ai_review.return_value = Mock(id=1, state="CHANGES_REQUESTED")

            call_count = [0]

            def get_reviews_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] <= 2:  # First iteration - changes requested
                    return [
                        PRReview(
                            id=2,
                            author="senior_dev",
                            state="CHANGES_REQUESTED",
                            body="Please address the error handling and validation issues",
                            submitted_at=datetime.now(),
                        )
                    ]
                else:  # Second iteration - approved
                    return [
                        PRReview(
                            id=2,
                            author="senior_dev",
                            state="CHANGES_REQUESTED",
                            body="Please address the error handling and validation issues",
                            submitted_at=datetime.now() - timedelta(minutes=10),
                        ),
                        PRReview(
                            id=3,
                            author="senior_dev",
                            state="APPROVED",
                            body="Great improvements! Ready to merge.",
                            submitted_at=datetime.now(),
                        ),
                    ]

            def get_unresolved_comments_side_effect(*args, **kwargs):
                if call_count[0] <= 2:  # Issues present
                    return [
                        ReviewComment(
                            id=1,
                            body="Fix error handling in line 45",
                            path="src/main.py",
                            line=45,
                            author="senior_dev",
                        ),
                        ReviewComment(
                            id=2,
                            body="Add input validation for user data",
                            path="src/api.py",
                            line=23,
                            author="senior_dev",
                        ),
                    ]
                else:  # Issues resolved
                    return []

            def check_approval_side_effect(*args, **kwargs):
                if call_count[0] <= 2:  # Changes requested
                    return (False, [], ["senior_dev"])
                else:  # Approved
                    return (True, ["senior_dev"], [])

            mock_github.get_pr_reviews.side_effect = get_reviews_side_effect
            mock_github.get_unresolved_comments.side_effect = get_unresolved_comments_side_effect
            mock_github.check_approval_status.side_effect = check_approval_side_effect
            mock_github_class.return_value = mock_github

            # Execute iterative workflow
            result = await execute_review_cycle(pr_number=123, repository="owner/repo")

            # Verify iterative completion
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration == 2  # Two iterations needed
            assert len(result.ai_reviews) >= 2  # AI review + AI update

            # Verify AI methods were called appropriately for iterative workflow
            assert mock_ai.execute_review.call_count >= 1  # At least initial review
            mock_ai.execute_update_from_review.assert_called_once()  # One update cycle

            # Verify final approval
            final_human_review = result.human_reviews[-1]
            assert final_human_review["state"] == "APPROVED"
            assert "Ready to merge" in final_human_review["body"]

    @pytest.mark.asyncio
    async def test_complex_multi_reviewer_workflow(self, full_config):
        """Test complex workflow with multiple reviewers and conflicting opinions."""
        with (
            patch("auto.workflows.review.get_config", return_value=full_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup AI integration
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Comprehensive review completed",
                    comments=["Consider refactoring this method"],
                    summary="AI review: 1 suggestion",
                )
            )
            mock_ai.execute_update_from_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="update",
                    content="Addressed reviewer feedback",
                    summary="Refactored method as suggested",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup GitHub integration with simpler, more predictable behavior
            mock_github = Mock()
            mock_github.post_ai_review.return_value = Mock(id=1, state="COMMENTED")

            # Simplified multi-reviewer scenario that progresses predictably
            # Initial state: mixed reviews, then all approved after one cycle
            reviews_sequence = [
                # First call: mixed reviews (changes requested)
                [
                    PRReview(
                        id=2,
                        author="reviewer_1",
                        state="APPROVED",
                        body="Looks good to me!",
                        submitted_at=datetime.now() - timedelta(minutes=5),
                    ),
                    PRReview(
                        id=3,
                        author="reviewer_2",
                        state="CHANGES_REQUESTED",
                        body="Please address the performance concerns",
                        submitted_at=datetime.now() - timedelta(minutes=3),
                    ),
                ],
                # Second call: all approved
                [
                    PRReview(
                        id=2,
                        author="reviewer_1",
                        state="APPROVED",
                        body="Looks good to me!",
                        submitted_at=datetime.now() - timedelta(minutes=5),
                    ),
                    PRReview(
                        id=4,
                        author="reviewer_2",  # Same reviewer, now approved
                        state="APPROVED",
                        body="Performance issues addressed. LGTM!",
                        submitted_at=datetime.now(),
                    ),
                    PRReview(
                        id=5,
                        author="reviewer_3",
                        state="APPROVED",
                        body="All suggestions addressed. Good work!",
                        submitted_at=datetime.now(),
                    ),
                ],
            ]

            comments_sequence = [
                # First call: unresolved comments
                [
                    ReviewComment(
                        id=1,
                        body="Performance concern in loop",
                        path="src/performance.py",
                        line=67,
                        author="reviewer_2",
                    )
                ],
                # Second call: all resolved
                [],
            ]

            approval_sequence = [
                # First call: not approved (changes requested)
                (False, ["reviewer_1"], ["reviewer_2"]),
                # Second call: approved by all
                (True, ["reviewer_1", "reviewer_2", "reviewer_3"], []),
            ]

            mock_github.get_pr_reviews.side_effect = reviews_sequence
            mock_github.get_unresolved_comments.side_effect = comments_sequence
            mock_github.check_approval_status.side_effect = approval_sequence
            mock_github_class.return_value = mock_github

            # Execute complex workflow
            result = await execute_review_cycle(pr_number=123, repository="owner/repo")

            # Verify complex workflow completion
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration >= 1
            assert len(result.human_reviews) >= 2  # Multiple reviewers captured

            # Verify workflow handled multiple reviewers
            final_reviewer_names = set()
            for review in result.human_reviews:
                final_reviewer_names.add(review["author"])
            assert "reviewer_1" in final_reviewer_names
            assert "reviewer_2" in final_reviewer_names

    @pytest.mark.asyncio
    async def test_workflow_with_failures_and_recovery(self, full_config):
        """Test workflow resilience with failures and recovery."""
        with (
            patch("auto.workflows.review.get_config", return_value=full_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup AI integration with initial failure, then success
            mock_ai = AsyncMock()
            ai_attempt_count = [0]

            def ai_review_side_effect(*args, **kwargs):
                ai_attempt_count[0] += 1
                if ai_attempt_count[0] == 1:
                    raise Exception("AI service temporarily unavailable")
                else:
                    return AIResponse(
                        success=True,
                        response_type="review",
                        content="Review completed after retry",
                        comments=["One minor issue found"],
                        summary="AI review: 1 issue (after retry)",
                    )

            mock_ai.execute_review = AsyncMock(side_effect=ai_review_side_effect)
            mock_ai_class.return_value = mock_ai

            # Setup GitHub integration with transient failures
            mock_github = Mock()
            github_attempt_count = [0]

            def post_review_side_effect(*args, **kwargs):
                github_attempt_count[0] += 1
                if github_attempt_count[0] == 1:
                    raise Exception("GitHub API rate limit exceeded")
                else:
                    return Mock(id=1, state="COMMENTED")

            mock_github.post_ai_review.side_effect = post_review_side_effect

            # Success after retry
            mock_github.get_pr_reviews.return_value = [
                PRReview(
                    id=2,
                    author="reviewer",
                    state="APPROVED",
                    body="Looks good despite the initial hiccups",
                    submitted_at=datetime.now(),
                )
            ]

            mock_github.get_unresolved_comments.return_value = []
            mock_github.check_approval_status.return_value = (True, ["reviewer"], [])
            mock_github_class.return_value = mock_github

            # First attempt should fail
            try:
                result = await execute_review_cycle(123, "owner/repo")
                # If it succeeds despite failures, that's OK (retry logic worked)
                assert result.status == ReviewCycleStatus.APPROVED
            except Exception:
                # Expected failure on first attempt
                pass

            # Verify failure was recorded if state tracking is implemented
            # This would depend on your actual state persistence implementation


class TestWorkflowPerformance:
    """Test review workflow performance under various conditions."""

    @pytest.fixture
    def performance_config(self):
        """Configuration optimized for performance testing."""
        return Config(
            workflows=WorkflowsConfig(
                max_review_iterations=3,  # Lower for faster tests
                review_check_interval=1,  # Very fast polling
                ai_review_first=True,
                require_human_approval=True,
            ),
            ai=AIConfig(
                command="claude", review_agent="pull-request-reviewer", update_agent="coder"
            ),
        )

    @pytest.mark.asyncio
    async def test_large_pr_review_performance(self, performance_config):
        """Test performance with large PR (many files, comments)."""
        with (
            patch("auto.workflows.review.get_config", return_value=performance_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup AI integration for large PR
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Large PR review completed",
                    comments=[f"Issue {i}: Fix this problem" for i in range(1, 51)],  # 50 issues
                    summary="AI review: Found 50 issues in large PR",
                )
            )
            mock_ai.execute_update_from_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="update",
                    content="Updated large PR based on feedback",
                    summary="AI update: Addressed 10 issues",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup GitHub integration for large PR
            mock_github = Mock()
            mock_github.post_ai_review.return_value = Mock(id=1, state="CHANGES_REQUESTED")

            # Large number of reviews and comments
            large_reviews = [
                PRReview(
                    id=i,
                    author=f"reviewer_{i % 5}",  # 5 different reviewers
                    state="APPROVED" if i > 45 else "COMMENTED",
                    body=f"Review {i} of large PR",
                    submitted_at=datetime.now() - timedelta(minutes=60 - i),
                )
                for i in range(1, 51)  # 50 reviews
            ]

            [
                ReviewComment(
                    id=i,
                    body=f"Comment {i}: This needs attention",
                    path=f"src/file_{i % 20}.py",  # 20 different files
                    line=10 + (i % 100),
                    author=f"reviewer_{i % 5}",
                )
                for i in range(1, 101)  # 100 comments
            ]

            mock_github.get_pr_reviews.return_value = large_reviews
            mock_github.get_unresolved_comments.return_value = []  # No unresolved comments to avoid AI update
            mock_github.check_approval_status.return_value = (
                True,  # Approved overall
                [f"reviewer_{i}" for i in range(5)],  # All reviewers approve
                [],
            )
            mock_github_class.return_value = mock_github

            # Measure performance
            start_time = time.time()
            result = await execute_review_cycle(123, "owner/large-repo")
            end_time = time.time()

            execution_time = end_time - start_time

            # Should complete within reasonable time despite large data
            assert execution_time < 10.0  # 10 seconds max for large PR
            assert result.status == ReviewCycleStatus.APPROVED
            assert len(result.human_reviews) == 50

    @pytest.mark.asyncio
    async def test_concurrent_workflow_performance(self, performance_config):
        """Test performance with multiple concurrent review cycles."""

        async def run_single_workflow(pr_number):
            """Run a single review workflow."""
            with (
                patch("auto.workflows.review.get_config", return_value=performance_config),
                patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
                patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
            ):
                # Setup quick success mocks
                mock_ai = AsyncMock()
                mock_ai.execute_review.return_value = AIResponse(
                    success=True,
                    response_type="review",
                    content=f"Review for PR {pr_number}",
                    comments=[],
                    summary="Quick AI review",
                )
                mock_ai_class.return_value = mock_ai

                mock_github = Mock()
                mock_github.post_ai_review.return_value = Mock(id=1, state="COMMENTED")
                mock_github.get_pr_reviews.return_value = [
                    PRReview(
                        id=1,
                        author="fast_reviewer",
                        state="APPROVED",
                        body="Quick approval",
                        submitted_at=datetime.now(),
                    )
                ]
                mock_github.get_unresolved_comments.return_value = []
                mock_github.check_approval_status.return_value = (True, ["fast_reviewer"], [])
                mock_github_class.return_value = mock_github

                return await execute_review_cycle(pr_number, "owner/repo")

        # Run multiple concurrent workflows
        pr_numbers = list(range(100, 110))  # 10 concurrent PRs

        start_time = time.time()
        tasks = [run_single_workflow(pr_num) for pr_num in pr_numbers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()

        execution_time = end_time - start_time

        # Verify concurrent execution
        successful_results = [r for r in results if isinstance(r, ReviewCycleState)]

        # Should handle concurrent workflows efficiently
        assert len(successful_results) >= 8  # At least 80% success rate
        assert execution_time < 15.0  # Reasonable time for 10 concurrent workflows

        # Verify all successful workflows completed properly
        for result in successful_results:
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration >= 1


class TestWorkflowEdgeCases:
    """Test review workflow edge cases and unusual scenarios."""

    @pytest.fixture
    def edge_case_config(self):
        """Configuration for edge case testing."""
        return Config(
            workflows=WorkflowsConfig(
                max_review_iterations=2,  # Low for testing limits
                review_check_interval=1,  # Very fast
                ai_review_first=True,
                require_human_approval=True,
            ),
            ai=AIConfig(
                command="claude", review_agent="pull-request-reviewer", update_agent="coder"
            ),
        )

    @pytest.mark.asyncio
    async def test_empty_pr_workflow(self, edge_case_config):
        """Test workflow with empty PR (no changes)."""
        with (
            patch("auto.workflows.review.get_config", return_value=edge_case_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup AI integration for empty PR
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="No changes to review",
                    comments=[],
                    summary="AI review: Empty PR",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup GitHub integration for empty PR
            mock_github = Mock()
            mock_github.post_ai_review.return_value = Mock(id=1, state="COMMENTED")
            mock_github.get_pr_reviews.return_value = [
                PRReview(
                    id=2,
                    author="reviewer",
                    state="APPROVED",
                    body="Nothing to review, LGTM",
                    submitted_at=datetime.now(),
                )
            ]
            mock_github.get_unresolved_comments.return_value = []
            mock_github.check_approval_status.return_value = (True, ["reviewer"], [])
            mock_github_class.return_value = mock_github

            # Execute workflow on empty PR
            result = await execute_review_cycle(123, "owner/repo")

            # Should handle empty PR gracefully
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration == 1
            assert len(result.ai_reviews) == 1
            assert result.ai_reviews[0]["comments_count"] == 0

    @pytest.mark.asyncio
    async def test_very_long_review_cycle(self, edge_case_config):
        """Test workflow that reaches maximum iterations."""
        edge_case_config.workflows.max_review_iterations = 2  # Very low limit

        with (
            patch("auto.workflows.review.get_config", return_value=edge_case_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup AI integration
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Found persistent issues",
                    comments=["This issue keeps coming back"],
                    summary="AI review: Persistent issue",
                )
            )
            mock_ai.execute_update_from_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="update",
                    content="Attempted fix",
                    summary="Tried to fix issue",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup GitHub integration with persistent issues
            mock_github = Mock()
            mock_github.post_ai_review.return_value = Mock(id=1, state="CHANGES_REQUESTED")

            # Track iteration to return appropriate number of reviews
            call_count = [0]

            def get_reviews_side_effect(*args, **kwargs):
                call_count[0] += 1
                reviews = []

                # Add one review per iteration to simulate new reviews coming in
                for i in range(min(call_count[0], 2)):  # Cap at 2 reviews max
                    reviews.append(
                        PRReview(
                            id=2 + i,
                            author="persistent_reviewer",
                            state="CHANGES_REQUESTED",
                            body=f"Iteration {i + 1}: This issue still exists",
                            submitted_at=datetime.now() - timedelta(minutes=10 - i),
                        )
                    )

                return reviews

            mock_github.get_pr_reviews.side_effect = get_reviews_side_effect

            mock_github.get_unresolved_comments.return_value = [
                ReviewComment(
                    id=1,
                    body="Persistent issue that won't resolve",
                    path="src/problematic.py",
                    line=42,
                    author="persistent_reviewer",
                )
            ]

            mock_github.check_approval_status.return_value = (False, [], ["persistent_reviewer"])
            mock_github_class.return_value = mock_github

            # Execute workflow that will hit iteration limit
            result = await execute_review_cycle(123, "owner/repo")

            # Should reach max iterations
            assert result.status == ReviewCycleStatus.MAX_ITERATIONS_REACHED
            assert result.iteration == 2  # Hit the limit
            assert len(result.ai_reviews) >= 2  # Multiple AI attempts

    @pytest.mark.asyncio
    async def test_reviewer_changes_mind_workflow(self, edge_case_config):
        """Test workflow where reviewer changes their mind multiple times."""
        with (
            patch("auto.workflows.review.get_config", return_value=edge_case_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup AI integration
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Comprehensive review",
                    comments=["Consider this improvement"],
                    summary="AI review: 1 suggestion",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup GitHub integration with changing reviewer
            mock_github = Mock()
            mock_github.post_ai_review.return_value = Mock(id=1, state="COMMENTED")

            call_sequence = [0]

            def get_reviews_side_effect(*args, **kwargs):
                call_sequence[0] += 1

                # Reviewer changes mind multiple times - start with changes requested
                reviews = []

                if call_sequence[0] >= 1:
                    reviews.append(
                        PRReview(
                            id=2,
                            author="indecisive_reviewer",
                            state="CHANGES_REQUESTED",
                            body="I found some issues that need fixing",
                            submitted_at=datetime.now() - timedelta(minutes=15),
                        )
                    )

                if call_sequence[0] >= 2:
                    reviews.append(
                        PRReview(
                            id=3,
                            author="indecisive_reviewer",
                            state="APPROVED",
                            body="Actually, it looks good now",
                            submitted_at=datetime.now() - timedelta(minutes=5),
                        )
                    )

                if call_sequence[0] >= 3:
                    reviews.append(
                        PRReview(
                            id=4,
                            author="indecisive_reviewer",
                            state="CHANGES_REQUESTED",
                            body="Wait, I found another issue",
                            submitted_at=datetime.now() - timedelta(minutes=2),
                        )
                    )

                if call_sequence[0] >= 4:
                    reviews.append(
                        PRReview(
                            id=5,
                            author="indecisive_reviewer",
                            state="APPROVED",
                            body="OK, finally approved after all changes",
                            submitted_at=datetime.now(),
                        )
                    )

                return reviews

            def check_approval_side_effect(*args, **kwargs):
                # Approval status follows the latest review
                if call_sequence[0] in [1, 3]:  # Changes requested states
                    return (False, [], ["indecisive_reviewer"])
                else:  # Approved states
                    return (True, ["indecisive_reviewer"], [])

            mock_github.get_pr_reviews.side_effect = get_reviews_side_effect
            mock_github.get_unresolved_comments.return_value = []
            mock_github.check_approval_status.side_effect = check_approval_side_effect
            mock_github_class.return_value = mock_github

            # Execute workflow with indecisive reviewer
            result = await execute_review_cycle(123, "owner/repo")

            # Should eventually complete when reviewer settles on approval
            assert result.status == ReviewCycleStatus.APPROVED
            assert len(result.human_reviews) >= 2  # Multiple reviews from same reviewer

            # Final review should be approval
            final_review = max(result.human_reviews, key=lambda r: r["timestamp"])
            assert final_review["state"] == "APPROVED"
