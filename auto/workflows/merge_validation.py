"""Merge validation functionality for pull requests.

This module handles all validation logic for determining if a PR is eligible
for merging, including review validation, status checks, and branch protection.
"""

from datetime import datetime
from typing import Any

from auto.config import get_config
from auto.integrations.review import GitHubReviewIntegration
from auto.models import Config, GitHubRepository, ValidationResult
from auto.utils.logger import get_logger
from auto.utils.shell import run_command_async as run_command

logger = get_logger(__name__)


class MergeValidationError(Exception):
    """Raised when merge validation fails."""

    pass


async def validate_merge_eligibility(
    pr_number: int, owner: str, repo: str, force: bool = False
) -> tuple[bool, list[str]]:
    """Check merge requirements and branch protection compliance.

    Args:
        pr_number: Pull request number
        owner: Repository owner
        repo: Repository name
        force: Skip some validation checks

    Returns:
        Tuple of (is_eligible, list_of_validation_errors)
    """
    logger.debug(f"Validating merge eligibility for PR #{pr_number}")

    errors = []

    try:
        # Get PR status and reviews
        pr_info = await _get_pr_info(pr_number, owner, repo)

        # Check if PR is in mergeable state
        if pr_info.get("state") != "open":
            errors.append(f"PR is not open (current state: {pr_info.get('state')})")

        if pr_info.get("isDraft"):
            errors.append("PR is in draft state")

        # Check if PR is mergeable
        mergeable = pr_info.get("mergeable")
        if mergeable is False:
            errors.append("PR has conflicts that must be resolved")
        elif mergeable is None and not force:
            errors.append("PR mergeable status is unknown (try again in a moment)")

        # Check for required reviews
        if not force:
            config = get_config()
            validation_result = await validate_reviews(
                pr_number, GitHubRepository(owner=owner, name=repo), config
            )
            if not validation_result.success:
                errors.append(validation_result.message)
                errors.extend(validation_result.actionable_items)

        # Check for required status checks
        if not force:
            checks_valid, check_errors = await validate_status_checks(pr_number, owner, repo)
            if not checks_valid:
                errors.extend(check_errors)

        # Check branch protection rules
        protection_valid, protection_errors = await validate_branch_protection(
            pr_info.get("base", {}).get("ref", "main"), owner, repo
        )
        if not protection_valid and not force:
            errors.extend(protection_errors)

        is_eligible = len(errors) == 0

        if is_eligible:
            logger.info(f"PR #{pr_number} is eligible for merge")
        else:
            logger.warning(f"PR #{pr_number} failed validation: {errors}")

        return is_eligible, errors

    except Exception as e:
        logger.error(f"Error validating merge eligibility: {e}")
        return False, [f"Validation error: {str(e)}"]


async def validate_reviews(
    pr_number: int, repository: GitHubRepository, config: Config
) -> ValidationResult:
    """Validate that PR has sufficient approvals and no blocking change requests.

    Args:
        pr_number: Pull request number to validate
        repository: Repository context for the PR
        config: Configuration object with review requirements

    Returns:
        ValidationResult with success status, message, and actionable items
    """
    logger.debug(f"Validating reviews for PR #{pr_number}")

    try:
        # Initialize GitHub review integration
        github_review = GitHubReviewIntegration()

        # Fetch all PR reviews
        reviews = github_review.get_pr_reviews(pr_number, repository)

        # Get PR information for commit SHA to check for stale reviews
        pr_info = await _get_pr_info(pr_number, repository.owner, repository.name)
        head_sha = pr_info.get("headRefOid") if pr_info else None

        # Track latest review state per reviewer (excluding stale reviews)
        reviewer_states = {}
        reviewer_review_dates: dict[str, datetime | None] = {}
        stale_reviewers = []

        for review in reviews:
            if review.author:
                reviewer = review.author

                # Check if review is stale (submitted before latest commit)
                is_stale = False
                if head_sha and hasattr(review, "commit_id") and review.commit_id != head_sha:
                    is_stale = True
                    if reviewer not in stale_reviewers:
                        stale_reviewers.append(reviewer)

                # Only consider non-stale reviews for approval status
                if not is_stale:
                    # Use the most recent review from each reviewer
                    existing_date = reviewer_review_dates.get(reviewer)
                    is_more_recent = reviewer not in reviewer_review_dates or (
                        review.submitted_at
                        and (existing_date is None or review.submitted_at > existing_date)
                    )
                    if is_more_recent:
                        reviewer_states[reviewer] = review.state
                        reviewer_review_dates[reviewer] = review.submitted_at

        # Categorize reviewers by their latest review state
        approving_reviewers = []
        requesting_changes_reviewers = []
        commented_only_reviewers = []

        for reviewer, state in reviewer_states.items():
            if state == "APPROVED":
                approving_reviewers.append(reviewer)
            elif state == "CHANGES_REQUESTED":
                requesting_changes_reviewers.append(reviewer)
            elif state == "COMMENTED":
                commented_only_reviewers.append(reviewer)

        # Check configuration requirements
        require_human_approval = config.workflows.require_human_approval
        required_approvals = config.github.required_approvals
        required_reviewers = config.github.required_reviewers

        # Validation checks
        actionable_items = []
        issues = []

        # Check for outstanding change requests
        if requesting_changes_reviewers:
            issue = f"{len(requesting_changes_reviewers)} reviewer(s) requested changes: {', '.join(requesting_changes_reviewers)}"
            issues.append(issue)
            actionable_items.append(
                f"Address change requests from: {', '.join(requesting_changes_reviewers)}"
            )

        # Check for required approval count
        approval_count = len(approving_reviewers)
        if require_human_approval and approval_count < required_approvals:
            issue = f"Need {required_approvals - approval_count} more approval(s) (currently have {approval_count})"
            issues.append(issue)
            if approval_count == 0:
                actionable_items.append("Get at least one reviewer to approve the PR")
            else:
                actionable_items.append(
                    f"Need {required_approvals - approval_count} more approval(s)"
                )

        # Check for required specific reviewers
        if required_reviewers:
            missing_required_reviewers = []
            for required_reviewer in required_reviewers:
                if required_reviewer not in approving_reviewers:
                    missing_required_reviewers.append(required_reviewer)

            if missing_required_reviewers:
                issue = f"Missing required approvals from: {', '.join(missing_required_reviewers)}"
                issues.append(issue)
                actionable_items.append(
                    f"Get approval from required reviewers: {', '.join(missing_required_reviewers)}"
                )

        # Warn about stale reviews
        if stale_reviewers:
            stale_issue = f"{len(stale_reviewers)} review(s) are stale (before latest commit): {', '.join(stale_reviewers)}"
            issues.append(stale_issue)
            actionable_items.append(
                f"Ask {', '.join(stale_reviewers)} to re-review after latest changes"
            )

        # Determine overall validation result
        critical_issues = len(requesting_changes_reviewers) > 0
        insufficient_approvals = require_human_approval and approval_count < required_approvals
        missing_required_reviewers_check = required_reviewers and any(
            r not in approving_reviewers for r in required_reviewers
        )

        success = not (
            critical_issues or insufficient_approvals or missing_required_reviewers_check
        )

        # Create summary message
        if success:
            message = f"PR reviews validated successfully: {approval_count} approval(s)"
            if stale_reviewers:
                message += f", {len(stale_reviewers)} stale review(s) noted"
        else:
            message = "PR review validation failed"
            if issues:
                # Limit to first 2 issues for brevity
                message += f": {'; '.join(issues[:2])}"
                if len(issues) > 2:
                    message += f" and {len(issues) - 2} more issue(s)"

        # Build detailed validation information
        details = {
            "total_reviews": len(reviews),
            "approval_count": approval_count,
            "approving_reviewers": approving_reviewers,
            "requesting_changes_count": len(requesting_changes_reviewers),
            "requesting_changes_reviewers": requesting_changes_reviewers,
            "commented_only_reviewers": commented_only_reviewers,
            "stale_reviewers": stale_reviewers,
            "required_approvals": required_approvals,
            "required_reviewers": required_reviewers,
            "require_human_approval": require_human_approval,
            "all_issues": issues,
        }

        logger.info(f"Review validation for PR #{pr_number}: {'PASSED' if success else 'FAILED'}")
        if not success:
            logger.warning(f"Review validation issues: {'; '.join(issues)}")

        return ValidationResult(
            success=success, message=message, details=details, actionable_items=actionable_items
        )

    except Exception as e:
        logger.error(f"Error validating reviews for PR #{pr_number}: {e}")
        return ValidationResult(
            success=False,
            message=f"Review validation failed due to error: {str(e)}",
            details={"error": str(e)},
            actionable_items=[
                "Check GitHub API connectivity and permissions",
                "Retry the validation",
            ],
        )


async def validate_status_checks(pr_number: int, owner: str, repo: str) -> tuple[bool, list[str]]:
    """Validate that all required status checks are passing."""
    errors = []

    try:
        pr_info = await _get_pr_info(pr_number, owner, repo)
        status_rollup = pr_info.get("statusCheckRollup", [])

        # Check for any failing status checks
        failing_checks = [
            check for check in status_rollup if check.get("state") in ["FAILURE", "ERROR"]
        ]

        if failing_checks:
            check_names = [check.get("name", "unknown") for check in failing_checks]
            errors.append(f"Failing status checks: {', '.join(check_names)}")

        # Check for any pending checks
        pending_checks = [check for check in status_rollup if check.get("state") == "PENDING"]

        if pending_checks:
            check_names = [check.get("name", "unknown") for check in pending_checks]
            errors.append(f"Pending status checks: {', '.join(check_names)}")

        return len(errors) == 0, errors

    except Exception as e:
        return False, [f"Error validating status checks: {str(e)}"]


async def validate_branch_protection(
    branch_name: str, owner: str, repo: str
) -> tuple[bool, list[str]]:
    """Validate branch protection rules."""
    # For now, just return True as branch protection validation
    # would require more complex GitHub API calls
    return True, []


async def _get_pr_info(pr_number: int, owner: str, repo: str) -> dict[str, Any]:
    """Get PR information from GitHub."""
    try:
        cmd = [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "state,isDraft,mergeable,reviews,statusCheckRollup,baseRefName",
        ]

        result = await run_command(cmd)

        if result.returncode == 0:
            import json

            return dict(json.loads(result.stdout))
        else:
            logger.error(f"Failed to get PR info: {result.stderr}")
            return {}

    except Exception as e:
        logger.error(f"Error getting PR info: {e}")
        return {}
