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
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from ..config import get_config
from ..integrations.ai import ClaudeIntegration
from ..integrations.review import GitHubReviewIntegration, PRReview, ReviewComment
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
    ai_reviews: List[Dict[str, Any]]
    human_reviews: List[Dict[str, Any]]
    unresolved_comments: List[ReviewComment]
    last_activity: float
    max_iterations: int


class ReviewWorkflowError(Exception):
    """Exception raised for review workflow errors."""
    pass


async def execute_review_cycle(
    pr_number: int,
    repository: str,
    max_iterations: Optional[int] = None
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
            max_iterations=max_iterations
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
            ReviewCycleStatus.APPROVED, ReviewCycleStatus.FAILED
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
        
        ai_integration = ClaudeIntegration()
        review_integration = GitHubReviewIntegration()
        
        # Execute AI review
        ai_response = await ai_integration.execute_review(
            pr_number=state.pr_number,
            repository=state.repository
        )
        
        # Post AI review comments
        if ai_response.comments:
            await review_integration.post_ai_review(
                pr_number=state.pr_number,
                repository=state.repository,
                comments=ai_response.comments,
                overall_feedback=ai_response.summary
            )
            
            logger.info(f"Posted {len(ai_response.comments)} AI review comments")
        
        # Record AI review in state
        state.ai_reviews.append({
            "iteration": state.iteration,
            "timestamp": time.time(),
            "response": ai_response.summary,
            "comments_count": len(ai_response.comments),
            "status": "completed"
        })
        
    except Exception as e:
        logger.error(f"AI review failed: {e}")
        # Record failed AI review
        state.ai_reviews.append({
            "iteration": state.iteration,
            "timestamp": time.time(),
            "error": str(e),
            "status": "failed"
        })
        raise ReviewWorkflowError(f"AI review execution failed: {e}") from e


async def wait_for_human_review(
    state: ReviewCycleState,
    timeout_minutes: Optional[int] = None
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
        timeout_minutes = timeout_minutes or 60  # Default 1 hour timeout
        timeout_seconds = timeout_minutes * 60
        
        logger.info(f"Waiting for human review on PR #{state.pr_number}")
        logger.info(f"Checking every {check_interval} seconds (timeout: {timeout_minutes} minutes)")
        
        review_integration = GitHubReviewIntegration()
        start_time = time.time()
        initial_review_count = len(state.human_reviews)
        
        while (time.time() - start_time) < timeout_seconds:
            # Check for new reviews
            reviews = await review_integration.get_pr_reviews(
                pr_number=state.pr_number,
                repository=state.repository
            )
            
            # Filter for human reviews (non-bot reviews)
            human_reviews = [
                review for review in reviews 
                if not review.author.endswith('[bot]') and review.author != 'github-actions[bot]'
            ]
            
            # Check if we have new human reviews
            if len(human_reviews) > initial_review_count:
                new_reviews = human_reviews[initial_review_count:]
                logger.info(f"Received {len(new_reviews)} new human review(s)")
                
                # Add new reviews to state
                for review in new_reviews:
                    state.human_reviews.append({
                        "iteration": state.iteration,
                        "timestamp": time.time(),
                        "author": review.author,
                        "state": review.state,
                        "body": review.body,
                        "review_id": review.id
                    })
                
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
        unresolved = await review_integration.get_unresolved_comments(
            pr_number=state.pr_number,
            repository=state.repository
        )
        
        state.unresolved_comments = unresolved
        logger.info(f"Found {len(unresolved)} unresolved review comments")
        
        # Log comment categories for debugging
        if unresolved:
            categories = {}
            for comment in unresolved:
                category = comment.file_path or "general"
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
        config = get_config()
        review_integration = GitHubReviewIntegration()
        
        # Check approval status
        approval_status = await review_integration.check_approval_status(
            pr_number=state.pr_number,
            repository=state.repository
        )
        
        logger.info(f"PR approval status: {approval_status}")
        
        # If approved and no unresolved comments, we're done
        if approval_status["approved"] and not state.unresolved_comments:
            logger.info("PR approved with no unresolved comments - cycle complete")
            return ReviewCycleStatus.APPROVED
        
        # If changes requested or unresolved comments, continue cycle
        if approval_status["changes_requested"] or state.unresolved_comments:
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
        
        ai_integration = ClaudeIntegration()
        
        # Format comments for AI
        comments_text = "\n".join([
            f"File: {comment.file_path}\nLine: {comment.line_number}\nComment: {comment.body}"
            for comment in state.unresolved_comments
        ])
        
        # Execute AI update using the review workflow method
        ai_response = await ai_integration.execute_update_from_review(
            repository=state.repository,
            comments=comments_text
        )
        
        logger.info(f"AI update completed: {ai_response.summary}")
        
        # Record AI update in state
        state.ai_reviews.append({
            "iteration": state.iteration,
            "timestamp": time.time(),
            "type": "update",
            "response": ai_response.summary,
            "comments_addressed": len(state.unresolved_comments),
            "status": "completed"
        })
        
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