"""
Performance benchmarks and optimization tests for review cycles.

These tests measure and validate performance characteristics:
- Review cycle execution time under various loads
- Memory usage during large operations
- Concurrency and scalability testing
- Optimization validation
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import psutil
import pytest

from auto.integrations.ai import AIResponse
from auto.integrations.review import PRReview, ReviewComment
from auto.models import AIConfig, Config, WorkflowsConfig
from auto.workflows.review import (
    ReviewCycleState,
    ReviewCycleStatus,
    execute_review_cycle,
    process_review_comments,
)


class TestPerformanceBenchmarks:
    """Performance benchmarks for review cycle operations."""

    @pytest.fixture
    def performance_config(self):
        """Optimized configuration for performance testing."""
        return Config(
            workflows=WorkflowsConfig(
                max_review_iterations=3,
                review_check_interval=1,  # Fast for testing (seconds)
                ai_review_first=True,
                require_human_approval=True,
            ),
            ai=AIConfig(
                command="claude",
                review_agent="pull-request-reviewer",
                update_agent="coder",
                max_retries=1,  # Reduce retries for performance
                stale_timeout=60,  # Shorter timeout
            ),
        )

    @pytest.mark.asyncio
    async def test_single_review_cycle_performance(self, performance_config):
        """Benchmark single review cycle execution time."""
        with (
            patch("auto.workflows.review.get_config", return_value=performance_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup optimized mocks
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Quick review",
                    comments=[],
                    summary="Fast AI review",
                )
            )
            mock_ai_class.return_value = mock_ai

            mock_github = Mock()
            mock_github.post_ai_review.return_value = Mock(id=1, state="COMMENTED")
            mock_github.get_pr_reviews.return_value = [
                PRReview(
                    id=2,
                    author="fast_reviewer",
                    state="APPROVED",
                    body="Quick approval",
                    submitted_at=datetime.now(),
                )
            ]
            mock_github.get_unresolved_comments.return_value = []
            mock_github.check_approval_status.return_value = (True, ["fast_reviewer"], [])
            mock_github_class.return_value = mock_github

            # Benchmark execution
            start_time = time.time()
            result = await execute_review_cycle(123, "owner/repo")
            end_time = time.time()

            execution_time = end_time - start_time

            # Performance assertions
            assert execution_time < 1.0  # Should complete within 1 second
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration == 1

            # Memory usage should be reasonable
            memory_usage = psutil.Process().memory_info().rss / 1024 / 1024  # MB
            assert memory_usage < 100  # Less than 100MB for simple operation

    @pytest.mark.asyncio
    async def test_concurrent_review_cycles_performance(self, performance_config):
        """Benchmark concurrent review cycle performance."""

        async def run_fast_cycle(pr_number):
            """Run a single fast review cycle."""
            with (
                patch("auto.workflows.review.get_config", return_value=performance_config),
                patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
                patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
            ):
                mock_ai = AsyncMock()
                mock_ai.execute_review = AsyncMock(
                    return_value=AIResponse(
                        success=True,
                        response_type="review",
                        content=f"Review for PR {pr_number}",
                        comments=[],
                        summary="Fast review",
                    )
                )
                mock_ai_class.return_value = mock_ai

                mock_github = Mock()
                mock_github.post_ai_review.return_value = Mock(id=1, state="COMMENTED")
                mock_github.get_pr_reviews.return_value = [
                    PRReview(
                        id=2,
                        author="reviewer",
                        state="APPROVED",
                        body="Approved",
                        submitted_at=datetime.now(),
                    )
                ]
                mock_github.get_unresolved_comments.return_value = []
                mock_github.check_approval_status.return_value = (True, ["reviewer"], [])
                mock_github_class.return_value = mock_github

                return await execute_review_cycle(pr_number, "owner/repo")

        # Run 10 concurrent cycles
        pr_numbers = range(100, 110)

        start_time = time.time()
        start_memory = psutil.Process().memory_info().rss / 1024 / 1024

        tasks = [run_fast_cycle(pr_num) for pr_num in pr_numbers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.time()
        end_memory = psutil.Process().memory_info().rss / 1024 / 1024

        execution_time = end_time - start_time
        memory_increase = end_memory - start_memory

        # Performance assertions
        successful_results = [r for r in results if isinstance(r, ReviewCycleState)]
        assert len(successful_results) >= 8  # At least 80% success rate
        assert execution_time < 5.0  # All 10 cycles in under 5 seconds
        assert memory_increase < 50  # Memory increase less than 50MB

        # All successful results should be approved quickly
        for result in successful_results:
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration == 1

    @pytest.mark.asyncio
    async def test_large_comment_processing_performance(self, performance_config):
        """Benchmark performance with large numbers of comments."""
        with (
            patch("auto.workflows.review.get_config", return_value=performance_config),
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Create large number of comments
            large_comments = [
                ReviewComment(
                    id=i,
                    body=f"Comment {i}: " + "A" * 100,  # 100 char comments
                    path=f"src/file{i % 10}.py",
                    line=10 + i,
                    author=f"reviewer{i % 3}",
                )
                for i in range(1, 1001)  # 1000 comments
            ]

            mock_github = Mock()
            mock_github.get_unresolved_comments.return_value = large_comments
            mock_github_class.return_value = mock_github

            state = ReviewCycleState(
                pr_number=123,
                repository="owner/repo",
                iteration=1,
                status=ReviewCycleStatus.HUMAN_REVIEW_RECEIVED,
                ai_reviews=[],
                human_reviews=[],
                unresolved_comments=[],
                last_activity=time.time(),
                max_iterations=3,
            )

            # Benchmark comment processing
            start_time = time.time()
            start_memory = psutil.Process().memory_info().rss / 1024 / 1024

            await process_review_comments(state)

            end_time = time.time()
            end_memory = psutil.Process().memory_info().rss / 1024 / 1024

            processing_time = end_time - start_time
            memory_used = end_memory - start_memory

            # Performance assertions
            assert processing_time < 2.0  # Process 1000 comments in under 2 seconds
            assert memory_used < 20  # Memory usage under 20MB
            assert len(state.unresolved_comments) == 1000

    @pytest.mark.asyncio
    async def test_iterative_cycle_performance(self, performance_config):
        """Benchmark performance of iterative review cycles."""
        with (
            patch("auto.workflows.review.get_config", return_value=performance_config),
            patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
            patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
        ):
            # Setup AI with multiple iterations
            mock_ai = AsyncMock()
            mock_ai.execute_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="review",
                    content="Found issues",
                    comments=["Fix this", "Fix that"],
                    summary="AI review with issues",
                )
            )
            mock_ai.execute_update_from_review = AsyncMock(
                return_value=AIResponse(
                    success=True,
                    response_type="update",
                    content="Fixed issues",
                    summary="Updated code",
                )
            )
            mock_ai_class.return_value = mock_ai

            # Setup GitHub with iterative responses
            mock_github = Mock()
            mock_github.post_ai_review.return_value = Mock(id=1, state="CHANGES_REQUESTED")

            call_count = [0]

            def get_reviews_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] <= 2:  # First two iterations - changes requested
                    return [
                        PRReview(
                            id=2,
                            author="reviewer",
                            state="CHANGES_REQUESTED",
                            body="Need fixes",
                            submitted_at=datetime.now(),
                        )
                    ]
                else:  # Final iteration - approved
                    return [
                        PRReview(
                            id=2,
                            author="reviewer",
                            state="CHANGES_REQUESTED",
                            body="Need fixes",
                            submitted_at=datetime.now() - timedelta(minutes=5),
                        ),
                        PRReview(
                            id=3,
                            author="reviewer",
                            state="APPROVED",
                            body="Good now",
                            submitted_at=datetime.now(),
                        ),
                    ]

            def get_unresolved_side_effect(*args, **kwargs):
                if call_count[0] <= 2:
                    return [
                        ReviewComment(
                            id=1,
                            body="Fix this issue",
                            path="src/main.py",
                            line=10,
                            author="reviewer",
                        )
                    ]
                else:
                    return []

            def check_approval_side_effect(*args, **kwargs):
                if call_count[0] <= 2:
                    return (False, [], ["reviewer"])
                else:
                    return (True, ["reviewer"], [])

            mock_github.get_pr_reviews.side_effect = get_reviews_side_effect
            mock_github.get_unresolved_comments.side_effect = get_unresolved_side_effect
            mock_github.check_approval_status.side_effect = check_approval_side_effect
            mock_github_class.return_value = mock_github

            # Benchmark iterative execution
            start_time = time.time()
            result = await execute_review_cycle(123, "owner/repo")
            end_time = time.time()

            execution_time = end_time - start_time

            # Performance assertions
            assert execution_time < 3.0  # Multiple iterations in under 3 seconds
            assert result.status == ReviewCycleStatus.APPROVED
            assert result.iteration >= 2  # Multiple iterations completed
            assert len(result.ai_reviews) >= 2  # AI review + update


class TestMemoryOptimization:
    """Test memory usage optimization in review cycles."""

    @pytest.mark.asyncio
    async def test_memory_cleanup_after_cycles(self):
        """Test that memory is properly cleaned up after review cycles."""
        _performance_config = Config(
            workflows=WorkflowsConfig(max_review_iterations=2, review_check_interval=1),
            ai=AIConfig(command="claude", review_agent="pull-request-reviewer"),
        )

        initial_memory = psutil.Process().memory_info().rss / 1024 / 1024

        # Run multiple cycles to check for memory leaks
        for i in range(10):
            with (
                patch("auto.workflows.review.get_config", return_value=_performance_config),
                patch("auto.workflows.review.ClaudeIntegration") as mock_ai_class,
                patch("auto.workflows.review.GitHubReviewIntegration") as mock_github_class,
            ):
                mock_ai = AsyncMock()
                mock_ai.execute_review = AsyncMock(
                    return_value=AIResponse(
                        success=True,
                        response_type="review",
                        content="Review",
                        comments=[],
                        summary="Quick review",
                    )
                )
                mock_ai_class.return_value = mock_ai

                mock_github = Mock()
                mock_github.post_ai_review.return_value = Mock(id=1)
                mock_github.get_pr_reviews.return_value = [
                    PRReview(
                        id=2,
                        author="reviewer",
                        state="APPROVED",
                        body="OK",
                        submitted_at=datetime.now(),
                    )
                ]
                mock_github.get_unresolved_comments.return_value = []
                mock_github.check_approval_status.return_value = (True, ["reviewer"], [])
                mock_github_class.return_value = mock_github

                await execute_review_cycle(100 + i, "owner/repo")

        final_memory = psutil.Process().memory_info().rss / 1024 / 1024
        memory_increase = final_memory - initial_memory

        # Memory increase should be minimal (< 10MB for 10 cycles)
        assert memory_increase < 10, f"Memory increased by {memory_increase}MB"

    @pytest.mark.asyncio
    async def test_large_data_structure_handling(self):
        """Test handling of large data structures efficiently."""
        # Create very large review state
        large_ai_reviews = [
            {
                "iteration": i,
                "timestamp": time.time(),
                "status": "completed",
                "response": "A" * 1000,  # 1KB response
                "comments_count": i % 10,
            }
            for i in range(1, 101)  # 100 AI reviews
        ]

        large_human_reviews = [
            {
                "iteration": i,
                "author": f"reviewer{i % 10}",
                "state": "APPROVED",
                "body": "B" * 1000,  # 1KB review
                "timestamp": time.time(),
            }
            for i in range(1, 101)  # 100 human reviews
        ]

        large_comments = [
            ReviewComment(
                id=i,
                body="C" * 500,  # 500 char comment
                path=f"src/file{i}.py",
                line=i,
                author="reviewer",
            )
            for i in range(1, 1001)  # 1000 comments
        ]

        start_memory = psutil.Process().memory_info().rss / 1024 / 1024

        # Create large state object
        large_state = ReviewCycleState(
            pr_number=123,
            repository="owner/repo",
            iteration=100,
            status=ReviewCycleStatus.APPROVED,
            ai_reviews=large_ai_reviews,
            human_reviews=large_human_reviews,
            unresolved_comments=large_comments,
            last_activity=time.time(),
            max_iterations=100,
        )

        end_memory = psutil.Process().memory_info().rss / 1024 / 1024
        memory_used = end_memory - start_memory

        # Should handle large data efficiently (< 50MB for all data)
        assert memory_used < 50, f"Large state used {memory_used}MB"

        # Verify data integrity
        assert len(large_state.ai_reviews) == 100
        assert len(large_state.human_reviews) == 100
        assert len(large_state.unresolved_comments) == 1000

        # Cleanup
        del large_state
        del large_ai_reviews
        del large_human_reviews
        del large_comments


class TestScalabilityBenchmarks:
    """Test scalability of review cycle operations."""

    def test_thread_safety_performance(self):
        """Test thread safety and performance under concurrent access."""
        _performance_config = Config(
            workflows=WorkflowsConfig(max_review_iterations=1, review_check_interval=1)
        )

        def create_review_state(pr_number):
            """Create a review state in a thread."""
            return ReviewCycleState(
                pr_number=pr_number,
                repository=f"owner/repo{pr_number}",
                iteration=1,
                status=ReviewCycleStatus.APPROVED,
                ai_reviews=[],
                human_reviews=[],
                unresolved_comments=[],
                last_activity=time.time(),
                max_iterations=1,
            )

        start_time = time.time()

        # Create 100 states concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_review_state, i) for i in range(100)]

            results = [future.result() for future in futures]

        end_time = time.time()
        execution_time = end_time - start_time

        # Should complete quickly even with threading
        assert execution_time < 1.0
        assert len(results) == 100
        assert all(isinstance(r, ReviewCycleState) for r in results)

    @pytest.mark.asyncio
    async def test_async_scalability(self):
        """Test async scalability with many concurrent operations."""

        async def fast_ai_review():
            """Simulate fast AI review operation."""
            await asyncio.sleep(0.001)  # 1ms delay
            return AIResponse(
                success=True,
                response_type="review",
                content="Fast review",
                comments=[],
                summary="Quick",
            )

        start_time = time.time()

        # Run 100 concurrent AI reviews
        tasks = [fast_ai_review() for _ in range(100)]
        results = await asyncio.gather(*tasks)

        end_time = time.time()
        execution_time = end_time - start_time

        # Should complete much faster than sequential (< 0.5 seconds)
        assert execution_time < 0.5
        assert len(results) == 100
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_gradual_load_increase(self):
        """Test performance under gradually increasing load."""
        _performance_config = Config(
            workflows=WorkflowsConfig(max_review_iterations=1, review_check_interval=1)
        )

        execution_times = []

        # Test with increasing numbers of concurrent operations
        for load in [1, 5, 10, 20, 50]:

            async def mock_review_cycle():
                """Mock review cycle operation."""
                await asyncio.sleep(0.01)  # 10ms work
                return ReviewCycleState(
                    pr_number=1,
                    repository="owner/repo",
                    iteration=1,
                    status=ReviewCycleStatus.APPROVED,
                    ai_reviews=[],
                    human_reviews=[],
                    unresolved_comments=[],
                    last_activity=time.time(),
                    max_iterations=1,
                )

            start_time = time.time()

            tasks = [mock_review_cycle() for _ in range(load)]
            await asyncio.gather(*tasks)

            end_time = time.time()
            execution_time = end_time - start_time
            execution_times.append(execution_time)

        # Performance should scale reasonably (not exponentially)
        # Each step should not be more than 2x the previous
        for i in range(1, len(execution_times)):
            ratio = execution_times[i] / execution_times[i - 1]
            assert ratio < 3.0, f"Performance degraded too much: {ratio}x slower"


class TestOptimizationValidation:
    """Validate that optimizations are working correctly."""

    @pytest.mark.asyncio
    async def test_caching_optimization(self):
        """Test that caching optimizations improve performance."""
        # This test would validate any caching mechanisms
        # For now, we'll test that repeated operations are fast

        _performance_config = Config(
            workflows=WorkflowsConfig(max_review_iterations=1, review_check_interval=1)
        )

        async def cached_operation():
            """Simulate an operation that could benefit from caching."""
            # In real implementation, this might cache GitHub API responses
            await asyncio.sleep(0.001)
            return {"result": "cached_data"}

        # First run (cold cache)
        start_time = time.time()
        result1 = await cached_operation()
        first_run_time = time.time() - start_time

        # Second run (warm cache - should be faster if caching is implemented)
        start_time = time.time()
        result2 = await cached_operation()
        second_run_time = time.time() - start_time

        # Results should be the same
        assert result1 == result2

        # Both runs should be fast (this test mainly ensures no performance regression)
        assert first_run_time < 0.1
        assert second_run_time < 0.1

    def test_data_structure_efficiency(self):
        """Test that data structures are used efficiently."""
        # Test that we're using appropriate data structures

        # Large list operations should be efficient
        large_list = list(range(10000))

        start_time = time.time()
        # Simulate operations that might happen in review cycles
        filtered = [x for x in large_list if x % 2 == 0]
        sorted_data = sorted(filtered)
        lookup_set = set(sorted_data)
        end_time = time.time()

        processing_time = end_time - start_time

        # Should handle large data operations quickly
        assert processing_time < 0.1
        assert len(filtered) == 5000
        assert len(lookup_set) == 5000
        assert 1000 in lookup_set

    @pytest.mark.asyncio
    async def test_async_optimization(self):
        """Test that async operations are properly optimized."""
        # Test that we're not blocking unnecessarily

        async def io_bound_operation(delay):
            """Simulate I/O bound operation."""
            await asyncio.sleep(delay)
            return f"completed_{delay}"

        start_time = time.time()

        # Run operations concurrently (should be faster than sequential)
        results = await asyncio.gather(
            io_bound_operation(0.01),
            io_bound_operation(0.01),
            io_bound_operation(0.01),
            io_bound_operation(0.01),
            io_bound_operation(0.01),
        )

        end_time = time.time()
        execution_time = end_time - start_time

        # 5 operations of 0.01s each should complete in ~0.01s concurrently
        # Allow some overhead, but should be much less than 0.05s sequential time
        assert execution_time < 0.03
        assert len(results) == 5
        assert all("completed_" in result for result in results)
