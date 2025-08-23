"""
Review cycle workflow orchestration for the auto tool.

This module implements the complete review cycle workflow including:
- AI review execution and comment posting
- Human review monitoring with polling
- Review comment aggregation and categorization
- Review cycle completion evaluation
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..config import get_config
from ..integrations.ai import ClaudeIntegration
from ..integrations.review import GitHubReviewIntegration, ReviewComment
from ..utils.logger import logger


class ReviewCycleStatus(Enum):
    """Status of the review cycle."""

    PENDING = "pending"
    AI_REVIEW_IN_PROGRESS = "ai_review_in_progress"
    WAITING_FOR_HUMAN = "waiting_for_human"
    HUMAN_REVIEW_RECEIVED = "human_review_received"
    AI_UPDATE_IN_PROGRESS = "ai_update_in_progress"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    FAILED = "failed"


@dataclass
class ReviewCycleState:
    """State tracking for review cycle."""

    pr_number: int
    repository: str
    iteration: int
    status: ReviewCycleStatus
    ai_reviews: list[dict[str, Any]]
    human_reviews: list[dict[str, Any]]
    unresolved_comments: list[ReviewComment]
    last_activity: float
    max_iterations: int
    iteration_count: int = 0  # Backward compatibility field

    def __post_init__(self) -> None:
        """Validate state parameters after initialization."""
        if self.pr_number < 0:
            raise ValueError("PR number must be non-negative")
        if self.max_iterations <= 0:
            raise ValueError("Max iterations must be greater than zero")

        # Set iteration_count for backward compatibility
        self.iteration_count = self.iteration


class ReviewWorkflowError(Exception):
    """Exception raised for review workflow errors."""

    pass


async def execute_review_cycle(
    pr_number: int, repository: str, max_iterations: int | None = None
) -> ReviewCycleState:
    """
    Execute the complete review cycle orchestration.

    This is the main orchestrator that manages the entire review cycle:
    1. Trigger AI review
    2. Wait for human review
    3. Process review comments
    4. Check for completion
    5. Repeat until approved or max iterations reached

    Args:
        pr_number: Pull request number
        repository: Repository name (owner/repo format)
        max_iterations: Maximum number of review iterations (default from config)

    Returns:
        ReviewCycleState with final status

    Raises:
        ReviewWorkflowError: If review cycle fails
    """
    try:
        config = get_config()
        max_iterations = max_iterations or config.workflows.max_review_iterations

        state = ReviewCycleState(
            pr_number=pr_number,
            repository=repository,
            iteration=0,
            status=ReviewCycleStatus.PENDING,
            ai_reviews=[],
            human_reviews=[],
            unresolved_comments=[],
            last_activity=time.time(),
            max_iterations=max_iterations,
        )

        logger.info(f"Starting review cycle for PR #{pr_number} (max {max_iterations} iterations)")

        while state.iteration < max_iterations:
            state.iteration += 1
            logger.info(f"Review cycle iteration {state.iteration}/{max_iterations}")

            # Step 1: AI Review (if configured to go first)
            if config.workflows.ai_review_first or state.iteration == 1:
                state.status = ReviewCycleStatus.AI_REVIEW_IN_PROGRESS
                await trigger_ai_review(state)

            # Step 2: Wait for human review
            state.status = ReviewCycleStatus.WAITING_FOR_HUMAN
            human_review_received = await wait_for_human_review(state)

            if human_review_received:
                state.status = ReviewCycleStatus.HUMAN_REVIEW_RECEIVED

                # Step 3: Process review comments
                await process_review_comments(state)

                # Step 4: Check if cycle is complete
                completion_status = await check_cycle_completion(state)
                state.status = completion_status

                if completion_status in [ReviewCycleStatus.APPROVED, ReviewCycleStatus.FAILED]:
                    break

                # Step 5: If changes requested, trigger AI update
                if completion_status == ReviewCycleStatus.CHANGES_REQUESTED:
                    state.status = ReviewCycleStatus.AI_UPDATE_IN_PROGRESS
                    await trigger_ai_update(state)

            # Update activity timestamp
            state.last_activity = time.time()

        # Check if max iterations reached
        if state.iteration >= max_iterations and state.status not in [
            ReviewCycleStatus.APPROVED,
            ReviewCycleStatus.FAILED,
        ]:
            state.status = ReviewCycleStatus.MAX_ITERATIONS_REACHED
            logger.warning(f"Review cycle reached max iterations ({max_iterations})")

        logger.info(f"Review cycle completed with status: {state.status.value}")
        return state

    except Exception as e:
        logger.error(f"Review cycle failed: {e}")
        raise ReviewWorkflowError(f"Review cycle execution failed: {e}") from e


async def trigger_ai_review(state: ReviewCycleState) -> None:
    """
    Execute AI review using configured review agent.

    Args:
        state: Current review cycle state

    Raises:
        ReviewWorkflowError: If AI review fails
    """
    try:
        logger.info(f"Triggering AI review for PR #{state.pr_number}")

        config = get_config()
        ai_integration = ClaudeIntegration(config.ai)
        review_integration = GitHubReviewIntegration()

        # Execute AI review
        ai_response = await ai_integration.execute_review(
            pr_number=state.pr_number, repository=state.repository
        )

        # Post AI review comments
        if ai_response.comments:
            # Transform string comments to dict format
            comment_dicts = [{"body": comment} for comment in ai_response.comments]
            review_integration.post_ai_review(
                pr_number=state.pr_number,
                review_body=ai_response.summary or "AI Review",
                comments=comment_dicts,
                repository=None,  # Let integration auto-detect repository
            )

            logger.info(f"Posted {len(ai_response.comments)} AI review comments")

        # Record AI review in state
        state.ai_reviews.append(
            {
                "iteration": state.iteration,
                "timestamp": time.time(),
                "response": ai_response.summary or ai_response.content,
                "comments_count": len(ai_response.comments) if ai_response.comments else 0,
                "status": "completed",
            }
        )

    except Exception as e:
        logger.error(f"AI review failed: {e}")
        # Record failed AI review
        state.ai_reviews.append(
            {
                "iteration": state.iteration,
                "timestamp": time.time(),
                "error": str(e),
                "status": "failed",
            }
        )
        raise ReviewWorkflowError(f"AI review execution failed: {e}") from e


async def wait_for_human_review(
    state: ReviewCycleState, timeout_minutes: int | None = None
) -> bool:
    """
    Monitor PR for human review activity with polling.

    Args:
        state: Current review cycle state
        timeout_minutes: Maximum time to wait (default from config)

    Returns:
        True if human review was received, False if timeout
    """
    try:
        config = get_config()
        check_interval = config.workflows.review_check_interval  # seconds
        # Use config timeout if available, otherwise default to 60 minutes
        default_timeout = getattr(config.workflows, "human_review_timeout", 60)
        # Ensure default_timeout is a number (not a Mock)
        if callable(default_timeout):  # It's a Mock or callable
            default_timeout = 60
        timeout_minutes = timeout_minutes or default_timeout
        timeout_seconds = timeout_minutes * 60

        logger.info(f"Waiting for human review on PR #{state.pr_number}")
        logger.info(f"Checking every {check_interval} seconds (timeout: {timeout_minutes} minutes)")

        review_integration = GitHubReviewIntegration()
        start_time = time.time()
        initial_review_count = len(state.human_reviews)

        while (time.time() - start_time) < timeout_seconds:
            # Check for new reviews
            reviews = review_integration.get_pr_reviews(
                pr_number=state.pr_number,
                repository=None,  # Let integration auto-detect repository
            )

            # Filter for human reviews (non-bot reviews)
            human_reviews = [
                review
                for review in reviews
                if review.author
                and not review.author.endswith("[bot]")
                and review.author != "github-actions[bot]"
            ]

            # Check if we have new human reviews
            if len(human_reviews) > initial_review_count:
                new_reviews = human_reviews[initial_review_count:]
                logger.info(f"Received {len(new_reviews)} new human review(s)")

                # Add new reviews to state
                for review in new_reviews:
                    state.human_reviews.append(
                        {
                            "iteration": state.iteration,
                            "timestamp": time.time(),
                            "author": review.author,
                            "state": review.state,
                            "body": review.body,
                            "review_id": review.id,
                        }
                    )

                return True

            # Wait before next check
            await asyncio.sleep(check_interval)

        logger.info("Human review timeout reached")
        return False

    except Exception as e:
        logger.error(f"Error waiting for human review: {e}")
        return False


async def process_review_comments(state: ReviewCycleState) -> None:
    """
    Aggregate and categorize review comments.

    Args:
        state: Current review cycle state
    """
    try:
        logger.info(f"Processing review comments for PR #{state.pr_number}")

        review_integration = GitHubReviewIntegration()

        # Get all unresolved comments
        unresolved = review_integration.get_unresolved_comments(
            pr_number=state.pr_number,
            repository=None,  # Let integration auto-detect repository
        )

        state.unresolved_comments = unresolved
        logger.info(f"Found {len(unresolved)} unresolved review comments")

        # Log comment categories for debugging
        if unresolved:
            categories: dict[str, int] = {}
            for comment in unresolved:
                category = comment.path or "general"
                categories[category] = categories.get(category, 0) + 1

            logger.debug(f"Comment categories: {categories}")

    except Exception as e:
        logger.error(f"Error processing review comments: {e}")


async def check_cycle_completion(state: ReviewCycleState) -> ReviewCycleStatus:
    """
    Evaluate review cycle completion criteria.

    Args:
        state: Current review cycle state

    Returns:
        ReviewCycleStatus indicating next action
    """
    try:
        get_config()
        review_integration = GitHubReviewIntegration()

        # Check approval status
        is_approved, approving_reviewers, requesting_changes_reviewers = (
            review_integration.check_approval_status(
                pr_number=state.pr_number,
                repository=None,  # Let integration auto-detect repository
            )
        )

        logger.info(
            f"PR approval status: approved={is_approved}, approvers={approving_reviewers}, requesting_changes={requesting_changes_reviewers}"
        )

        # If approved and no unresolved comments, we're done
        if is_approved and not state.unresolved_comments:
            logger.info("PR approved with no unresolved comments - cycle complete")
            return ReviewCycleStatus.APPROVED

        # If changes requested or unresolved comments, continue cycle
        if requesting_changes_reviewers or state.unresolved_comments:
            logger.info("Changes requested or unresolved comments - continuing cycle")
            return ReviewCycleStatus.CHANGES_REQUESTED

        # If no clear direction, continue waiting
        logger.info("No clear approval or rejection - continuing cycle")
        return ReviewCycleStatus.WAITING_FOR_HUMAN

    except Exception as e:
        logger.error(f"Error checking cycle completion: {e}")
        return ReviewCycleStatus.FAILED


async def trigger_ai_update(state: ReviewCycleState) -> None:
    """
    Trigger AI to address review comments.

    Args:
        state: Current review cycle state

    Raises:
        ReviewWorkflowError: If AI update fails
    """
    try:
        logger.info(f"Triggering AI update for PR #{state.pr_number}")

        if not state.unresolved_comments:
            logger.info("No unresolved comments to address")
            return

        config = get_config()
        ai_integration = ClaudeIntegration(config.ai)

        # Format comments for AI
        comments_text = "\n".join(
            [
                f"File: {comment.path}\nLine: {comment.line}\nComment: {comment.body}"
                for comment in state.unresolved_comments
            ]
        )

        # Execute AI update using the review workflow method
        ai_response = await ai_integration.execute_update_from_review(
            repository=state.repository, comments=comments_text
        )

        logger.info(f"AI update completed: {ai_response.summary}")

        # Record AI update in state
        state.ai_reviews.append(
            {
                "iteration": state.iteration,
                "timestamp": time.time(),
                "type": "update",
                "response": ai_response.summary,
                "comments_addressed": len(state.unresolved_comments),
                "status": "completed",
            }
        )

    except Exception as e:
        logger.error(f"AI update failed: {e}")
        raise ReviewWorkflowError(f"AI update execution failed: {e}") from e


async def initiate_review_cycle(pr_number: int, repository: str) -> ReviewCycleState:
    """
    Start review cycle for existing PR.

    This is a convenience function to start a review cycle for a PR that
    has already been created but needs to enter the review process.

    Args:
        pr_number: Pull request number
        repository: Repository name

    Returns:
        ReviewCycleState with final status
    """
    logger.info(f"Initiating review cycle for existing PR #{pr_number}")
    return await execute_review_cycle(pr_number, repository)


async def get_review_cycle_status(pr_number: int, owner: str, repo: str) -> ReviewCycleState | None:
    """Get current review cycle status for a PR.

    Args:
        pr_number: Pull request number
        owner: Repository owner
        repo: Repository name

    Returns:
        Review cycle state or None if not found
    """
    try:
        from auto.core import get_core

        core = get_core()
        review_state = core.get_review_cycle_state(pr_number)

        if not review_state:
            return None

        # Convert dict to ReviewCycleState object
        iteration_value = review_state.get("iteration_count", 0)
        state = ReviewCycleState(
            pr_number=pr_number,
            repository=f"{owner}/{repo}",
            iteration=iteration_value,
            status=ReviewCycleStatus(review_state.get("status", "not_started")),
            ai_reviews=review_state.get("ai_reviews", []),
            human_reviews=review_state.get("human_reviews", []),
            unresolved_comments=[],
            last_activity=review_state.get("last_updated", time.time()),
            max_iterations=review_state.get("max_iterations", 10),
            iteration_count=iteration_value,  # Initialize the field properly
        )

        # iteration_count is now properly initialized in the constructor
        return state

    except Exception as e:
        logger.error(f"Error getting review cycle status for PR #{pr_number}: {e}")
        return None
