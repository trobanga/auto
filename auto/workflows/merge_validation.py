"""Merge validation functionality for pull requests.

This module handles all validation logic for determining if a PR is eligible
for merging, including review validation, status checks, and branch protection.
"""

import json
from datetime import datetime
from typing import Any

from auto.config import get_config
from auto.integrations.review import GitHubReviewIntegration
from auto.models import Config, GitHubRepository, ValidationResult
from auto.utils.logger import get_logger
from auto.utils.shell import run_command_async

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
            repository = GitHubRepository(owner=owner, name=repo)
            config = get_config()
            validation_result = await _validate_status_checks(pr_number, repository, config)
            if not validation_result.success:
                errors.append(validation_result.message)
                errors.extend(validation_result.actionable_items)

        # Check branch protection rules
        if not force:
            repository = GitHubRepository(owner=owner, name=repo)
            config = get_config()
            protection_result = await _validate_branch_protection(pr_number, repository, config)
            if not protection_result.success:
                errors.append(protection_result.message)
                errors.extend(protection_result.actionable_items)

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


async def _validate_status_checks(
    pr_number: int, repository: GitHubRepository, config: Config
) -> ValidationResult:
    """Validate that all required status checks are passing.

    This function implements CI/CD status check validation to ensure all required
    checks pass before merge operations, with configurable timeout behavior for
    pending checks.

    Args:
        pr_number: Pull request number
        repository: Repository context
        config: Configuration object

    Returns:
        ValidationResult with success status and detailed information
    """
    import asyncio
    import time

    from auto.models import ValidationResult
    from auto.utils.shell import ShellError

    logger.debug(f"Validating status checks for PR #{pr_number}")

    actionable_items = []
    details = {}

    try:
        # Get configuration values
        wait_for_checks = getattr(config.workflows, "wait_for_checks", True)
        check_timeout = getattr(config.workflows, "check_timeout", 600)  # 10 minutes default
        required_status_checks = getattr(config.workflows, "required_status_checks", [])
        status_check_retries = getattr(config.github, "status_check_retries", 3)
        status_check_interval = getattr(config.github, "status_check_interval", 30)

        # Get PR information to extract the latest commit SHA
        pr_info = await _get_pr_info(pr_number, repository.owner, repository.name)
        if not pr_info:
            return ValidationResult(
                success=False,
                message="Failed to retrieve PR information",
                details={"error": "Could not fetch PR details"},
                actionable_items=["Check if the PR exists and is accessible"],
            )

        # Get the head commit SHA
        head_sha = pr_info.get("headRefOid")
        if not head_sha:
            # Fallback to getting commit info from PR
            head_sha = await _get_pr_head_sha(pr_number, repository.owner, repository.name)

        if not head_sha:
            return ValidationResult(
                success=False,
                message="Failed to retrieve PR head commit SHA",
                details={"error": "Could not determine latest commit"},
                actionable_items=["Ensure the PR has commits and try again"],
            )

        details["head_sha"] = head_sha

        # Fetch branch protection rules to identify required checks
        protected_branch = pr_info.get("baseRefName", "main")
        required_checks_from_protection = await _get_required_status_checks_from_protection(
            repository.owner, repository.name, protected_branch
        )

        # Combine required checks from config and branch protection
        all_required_checks = set(required_status_checks + required_checks_from_protection)
        details["required_checks"] = list(all_required_checks)

        # Start monitoring status checks with timeout
        start_time = time.time()
        retry_count = 0

        while retry_count <= status_check_retries:
            try:
                # Fetch current status checks
                status_data = await _fetch_status_checks(
                    repository.owner, repository.name, head_sha
                )

                if not status_data:
                    if retry_count < status_check_retries:
                        logger.debug(
                            f"No status data available, retrying in {status_check_interval}s..."
                        )
                        retry_count += 1
                        await asyncio.sleep(status_check_interval)
                        continue
                    else:
                        # No status checks found - this might be OK if none are required
                        if not all_required_checks:
                            return ValidationResult(
                                success=True,
                                message="No status checks required or found",
                                details=details,
                                actionable_items=[],
                            )
                        else:
                            return ValidationResult(
                                success=False,
                                message="Required status checks not found",
                                details=details,
                                actionable_items=[
                                    f"Configure required status checks: {', '.join(all_required_checks)}"
                                ],
                            )

                # Parse status check results
                failing_checks = []
                pending_checks = []
                passing_checks = []

                # Handle both statuses and check runs from the combined status
                all_checks = []

                # Add traditional status API results
                if "statuses" in status_data:
                    for status in status_data.get("statuses", []):
                        all_checks.append(
                            {
                                "name": status.get("context", "unknown"),
                                "state": status.get("state", "unknown").upper(),
                                "description": status.get("description", ""),
                                "target_url": status.get("target_url"),
                            }
                        )

                # Add check runs (newer GitHub Checks API)
                if "check_runs" in status_data:
                    for check in status_data.get("check_runs", []):
                        # Map check run conclusions to status states
                        conclusion = check.get("conclusion", "").upper()
                        if conclusion == "SUCCESS":
                            state = "SUCCESS"
                        elif conclusion in ["FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"]:
                            state = "FAILURE"
                        elif conclusion == "NEUTRAL":
                            state = "SUCCESS"  # Neutral is typically considered passing
                        else:
                            state = "PENDING"  # In progress or queued

                        all_checks.append(
                            {
                                "name": check.get("name", "unknown"),
                                "state": state,
                                "description": check.get("output", {}).get("summary", ""),
                                "target_url": check.get("html_url"),
                            }
                        )

                # Categorize checks
                for check in all_checks:
                    check_state = check["state"]

                    if check_state in ["FAILURE", "ERROR"]:
                        failing_checks.append(check)
                    elif check_state == "PENDING":
                        pending_checks.append(check)
                    elif check_state == "SUCCESS":
                        passing_checks.append(check)

                details["all_checks"] = all_checks
                details["failing_checks"] = failing_checks
                details["pending_checks"] = pending_checks
                details["passing_checks"] = passing_checks

                # Check for failing required checks
                failing_required = []
                for check in failing_checks:
                    if not all_required_checks or check["name"] in all_required_checks:
                        failing_required.append(check)

                if failing_required:
                    failing_names = [check["name"] for check in failing_required]
                    actionable_items.append(
                        f"Fix failing status checks: {', '.join(failing_names)}"
                    )
                    for check in failing_required:
                        if check.get("target_url"):
                            actionable_items.append(f"Check details: {check['target_url']}")

                    return ValidationResult(
                        success=False,
                        message=f"Required status checks are failing: {', '.join(failing_names)}",
                        details=details,
                        actionable_items=actionable_items,
                    )

                # Check for pending required checks
                pending_required = []
                for check in pending_checks:
                    if not all_required_checks or check["name"] in all_required_checks:
                        pending_required.append(check)

                if pending_required and wait_for_checks:
                    elapsed_time = time.time() - start_time

                    if elapsed_time < check_timeout:
                        pending_names = [check["name"] for check in pending_required]
                        logger.info(
                            f"Waiting for pending status checks: {', '.join(pending_names)} (elapsed: {elapsed_time:.0f}s)"
                        )

                        # Wait before checking again
                        await asyncio.sleep(status_check_interval)
                        retry_count = 0  # Reset retry count since we're making progress
                        continue
                    else:
                        # Timeout reached
                        pending_names = [check["name"] for check in pending_required]
                        actionable_items.append(
                            f"Status checks timed out after {check_timeout}s: {', '.join(pending_names)}"
                        )
                        for check in pending_required:
                            if check.get("target_url"):
                                actionable_items.append(f"Check details: {check['target_url']}")

                        return ValidationResult(
                            success=False,
                            message=f"Required status checks timed out: {', '.join(pending_names)}",
                            details=details,
                            actionable_items=actionable_items,
                        )
                elif pending_required and not wait_for_checks:
                    # Not waiting for checks, but they're still pending
                    pending_names = [check["name"] for check in pending_required]
                    actionable_items.append(
                        f"Status checks are pending: {', '.join(pending_names)}"
                    )

                    return ValidationResult(
                        success=False,
                        message=f"Required status checks are pending: {', '.join(pending_names)}",
                        details=details,
                        actionable_items=actionable_items,
                    )

                # Check if all required checks are present and passing
                if all_required_checks:
                    passing_required_names = {
                        check["name"]
                        for check in passing_checks
                        if check["name"] in all_required_checks
                    }
                    missing_checks = all_required_checks - passing_required_names

                    if missing_checks:
                        actionable_items.append(
                            f"Missing required status checks: {', '.join(missing_checks)}"
                        )
                        return ValidationResult(
                            success=False,
                            message=f"Required status checks not found: {', '.join(missing_checks)}",
                            details=details,
                            actionable_items=actionable_items,
                        )

                # All checks are passing
                passing_names = [check["name"] for check in passing_checks]
                logger.info(
                    f"All required status checks are passing: {', '.join(passing_names) if passing_names else 'none required'}"
                )

                return ValidationResult(
                    success=True,
                    message=f"All status checks passing ({len(passing_checks)} checks)",
                    details=details,
                    actionable_items=[],
                )

            except ShellError as e:
                logger.warning(
                    f"Error fetching status checks (attempt {retry_count + 1}): {e.stderr}"
                )
                if retry_count < status_check_retries:
                    retry_count += 1
                    await asyncio.sleep(status_check_interval)
                    continue
                else:
                    return ValidationResult(
                        success=False,
                        message=f"Failed to retrieve status checks after {status_check_retries + 1} attempts",
                        details={"error": str(e), "stderr": e.stderr},
                        actionable_items=["Check GitHub API access and repository permissions"],
                    )

        # This shouldn't be reached, but handle it gracefully
        return ValidationResult(
            success=False,
            message="Status check validation failed unexpectedly",
            details=details,
            actionable_items=["Please try again or check logs for details"],
        )

    except Exception as e:
        logger.error(f"Unexpected error during status check validation: {e}")
        return ValidationResult(
            success=False,
            message=f"Status check validation error: {str(e)}",
            details={"error": str(e), "error_type": type(e).__name__},
            actionable_items=["Check logs for detailed error information"],
        )


async def _get_pr_head_sha(pr_number: int, owner: str, repo: str) -> str | None:
    """Get the head commit SHA for a PR."""
    try:
        cmd = ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}", "--jq", ".head.sha"]

        result = await run_command_async(cmd)
        if result.returncode == 0:
            return str(result.stdout).strip()
        else:
            logger.warning(f"Failed to get PR head SHA: {result.stderr}")
            return None

    except Exception as e:
        logger.warning(f"Error getting PR head SHA: {e}")
        return None


async def _fetch_status_checks(owner: str, repo: str, sha: str) -> dict[str, Any] | None:
    """Fetch status checks for a specific commit."""
    try:
        # Get combined status (includes both status API and checks API results)
        cmd = ["gh", "api", f"repos/{owner}/{repo}/commits/{sha}/status", "--paginate"]

        result = await run_command_async(cmd)
        if result.returncode == 0:
            status_data = json.loads(result.stdout) if result.stdout.strip() else {}

            # Also get check runs for more comprehensive coverage
            check_cmd = [
                "gh",
                "api",
                f"repos/{owner}/{repo}/commits/{sha}/check-runs",
                "--paginate",
            ]

            check_result = await run_command_async(check_cmd)
            if check_result.returncode == 0:
                check_data = json.loads(check_result.stdout) if check_result.stdout.strip() else {}
                if "check_runs" in check_data:
                    status_data["check_runs"] = check_data["check_runs"]

            return status_data
        else:
            logger.warning(f"Failed to fetch status checks: {result.stderr}")
            return None

    except Exception as e:
        logger.warning(f"Error fetching status checks: {e}")
        return None


async def _get_required_status_checks_from_protection(
    owner: str, repo: str, branch: str
) -> list[str]:
    """Get required status checks from branch protection rules."""
    try:
        cmd = [
            "gh",
            "api",
            f"repos/{owner}/{repo}/branches/{branch}/protection",
            "--jq",
            ".required_status_checks.contexts // []",
        ]

        result = await run_command_async(cmd)
        if result.returncode == 0 and result.stdout.strip():
            required_checks = json.loads(result.stdout)
            return required_checks if isinstance(required_checks, list) else []
        else:
            # Branch might not have protection rules, which is fine
            logger.debug(f"No branch protection or required checks found for {branch}")
            return []

    except Exception as e:
        logger.debug(f"Error getting required status checks from protection: {e}")
        return []


async def _validate_branch_protection(
    pr_number: int, repository: GitHubRepository, config: Config
) -> ValidationResult:
    """Validate that PR complies with GitHub branch protection rules.

    This function ensures merge operations comply with GitHub branch protection rules
    and repository policies, including review requirements, status checks, and restrictions.

    Args:
        pr_number: Pull request number to validate
        repository: Repository context for the PR
        config: Configuration object with merge requirements

    Returns:
        ValidationResult with branch protection compliance status, message, and actionable items
    """
    logger.debug(f"Validating branch protection for PR #{pr_number}")

    actionable_items = []
    details = {}

    try:
        # Get PR information to determine the base branch
        pr_info = await _get_pr_info(pr_number, repository.owner, repository.name)
        if not pr_info:
            return ValidationResult(
                success=False,
                message="Failed to retrieve PR information for branch protection validation",
                details={"error": "Could not fetch PR details"},
                actionable_items=["Check if the PR exists and is accessible"],
            )

        base_branch = pr_info.get("baseRefName", repository.default_branch)
        details["base_branch"] = base_branch

        # Fetch branch protection rules
        protection_data = await _fetch_branch_protection_rules(
            repository.owner, repository.name, base_branch
        )

        # Handle repositories without branch protection gracefully
        if not protection_data:
            logger.info(f"No branch protection rules found for {base_branch}")
            return ValidationResult(
                success=True,
                message=f"No branch protection rules configured for {base_branch}",
                details={"base_branch": base_branch, "protection_enabled": False},
                actionable_items=[],
            )

        details.update(protection_data)
        details["protection_enabled"] = True

        # Get current user permissions to handle administrator overrides
        user_permissions = await _get_user_permissions(repository.owner, repository.name)
        is_admin = (user_permissions or {}).get("admin", False)
        details["user_is_admin"] = is_admin

        # Validate review requirements
        review_validation_errors = []
        if ((protection_data or {}).get("required_status_checks") or {}).get(
            "enforce_admins", False
        ) or not is_admin:
            review_errors = await _validate_protection_review_requirements(
                pr_number, repository, config, protection_data
            )
            review_validation_errors.extend(review_errors)

        # Validate status check requirements
        status_check_errors = []
        if (protection_data or {}).get("required_status_checks"):
            status_errors = await _validate_protection_status_checks(
                pr_number, repository, config, protection_data
            )
            status_check_errors.extend(status_errors)

        # Validate push restrictions
        restriction_errors = []
        if (protection_data or {}).get("restrictions"):
            restriction_errors = await _validate_push_restrictions(
                repository, protection_data, user_permissions or {}
            )

        # Combine all validation errors
        all_errors = review_validation_errors + status_check_errors + restriction_errors

        if all_errors:
            actionable_items.extend(all_errors)

            # Provide administrator override guidance if applicable
            if is_admin and not (
                ((protection_data or {}).get("required_status_checks") or {}).get(
                    "enforce_admins", False
                )
            ):
                actionable_items.append(
                    "As an administrator, you can override some protection rules"
                )

        # Determine overall success
        success = len(all_errors) == 0

        # Create appropriate message
        if success:
            message = f"Branch protection rules for '{base_branch}' are satisfied"
            if is_admin:
                message += " (administrator access confirmed)"
        else:
            message = f"Branch protection validation failed for '{base_branch}': {len(all_errors)} issue(s)"
            if all_errors:
                message += f" - {all_errors[0]}"
                if len(all_errors) > 1:
                    message += f" and {len(all_errors) - 1} more"

        logger.info(
            f"Branch protection validation for PR #{pr_number}: {'PASSED' if success else 'FAILED'}"
        )
        if not success:
            logger.warning(f"Branch protection issues: {'; '.join(all_errors[:3])}")

        return ValidationResult(
            success=success,
            message=message,
            details=details,
            actionable_items=actionable_items,
        )

    except Exception as e:
        import traceback

        logger.error(f"Error validating branch protection for PR #{pr_number}: {e}")
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return ValidationResult(
            success=False,
            message=f"Branch protection validation failed due to error: {str(e)}",
            details={"error": str(e)},
            actionable_items=[
                "Check GitHub API connectivity and repository permissions",
                "Verify repository exists and is accessible",
                "Retry the validation",
            ],
        )


async def _fetch_branch_protection_rules(
    owner: str, repo: str, branch: str
) -> dict[str, Any] | None:
    """Fetch branch protection rules for a specific branch."""
    cmd = [
        "gh",
        "api",
        f"repos/{owner}/{repo}/branches/{branch}/protection",
    ]

    result = await run_command_async(cmd)
    if result.returncode == 0 and result.stdout.strip():
        protection_data: dict[str, Any] = json.loads(result.stdout)
        return protection_data
    else:
        # Branch protection might not be enabled, which is fine
        logger.debug(f"No branch protection rules found for {branch}: {result.stderr}")
        return None


async def _get_user_permissions(owner: str, repo: str) -> dict[str, Any]:
    """Get current user permissions for the repository."""
    try:
        cmd = ["gh", "api", f"repos/{owner}/{repo}", "--jq", ".permissions"]

        result = await run_command_async(cmd)
        if result.returncode == 0 and result.stdout.strip():
            permissions = json.loads(result.stdout)
            return permissions or {}
        else:
            logger.debug(f"Could not fetch user permissions: {result.stderr}")
            return {}

    except Exception as e:
        logger.debug(f"Error fetching user permissions: {e}")
        return {}


async def _validate_protection_review_requirements(
    pr_number: int, repository: GitHubRepository, config: Config, protection_data: dict[str, Any]
) -> list[str]:
    """Validate review requirements from branch protection rules."""
    errors: list[str] = []

    # Get protection review requirements
    required_reviews = (protection_data or {}).get("required_pull_request_reviews", {})
    if not required_reviews:
        return errors

    required_review_count = required_reviews.get("required_approving_review_count", 0)
    dismiss_stale_reviews = required_reviews.get("dismiss_stale_reviews", False)
    require_code_owner_reviews = required_reviews.get("require_code_owner_reviews", False)

    # Use existing review validation function to get current review status
    review_result = await validate_reviews(pr_number, repository, config)
    if not review_result:
        errors.append("Could not retrieve review information for branch protection validation")
        return errors
    current_approvals = (review_result.details or {}).get("approval_count", 0)

    # Check if we have enough approvals
    if current_approvals < required_review_count:
        needed = required_review_count - current_approvals
        errors.append(
            f"Branch protection requires {required_review_count} approving reviews, but only {current_approvals} found (need {needed} more)"
        )

    # Check for stale review dismissal requirement
    if dismiss_stale_reviews:
        stale_reviewers = (review_result.details or {}).get("stale_reviewers", [])
        if stale_reviewers:
            errors.append(
                f"Branch protection dismisses stale reviews: {len(stale_reviewers)} stale review(s) found from {', '.join(stale_reviewers)}"
            )

    # Check for code owner review requirement
    if require_code_owner_reviews:
        # This would require additional API call to check CODEOWNERS file
        # For now, we'll add a general notice
        errors.append(
            "Branch protection requires code owner review - verify code owners have approved"
        )

    return errors


async def _validate_protection_status_checks(
    pr_number: int, repository: GitHubRepository, config: Config, protection_data: dict[str, Any]
) -> list[str]:
    """Validate status check requirements from branch protection rules."""
    errors: list[str] = []

    required_status_checks = (protection_data or {}).get("required_status_checks")
    if not required_status_checks:
        return errors

    # Use existing status check validation function
    status_result = await _validate_status_checks(pr_number, repository, config)

    if not status_result.success:
        errors.append("Branch protection requires all status checks to pass")
        # Add specific failing checks from the status validation
        errors.extend(status_result.actionable_items[:2])  # Limit to first 2 for brevity

    # Check for strict status checks (requiring branch to be up to date)
    if required_status_checks.get("strict", False):
        # We would need to check if the PR branch is up to date with base
        # This is a simplified check - in practice would need more detailed validation
        errors.append("Branch protection requires branch to be up to date before merging")

    return errors


async def _validate_push_restrictions(
    repository: GitHubRepository, protection_data: dict[str, Any], user_permissions: dict[str, Any]
) -> list[str]:
    """Validate push restrictions from branch protection rules."""
    errors: list[str] = []

    restrictions = (protection_data or {}).get("restrictions")
    if not restrictions:
        return errors

    # Get current user info
    current_user = await _get_current_user()
    if not current_user:
        errors.append("Could not verify user permissions against push restrictions")
        return errors

    # Check user restrictions
    allowed_users = restrictions.get("users", [])
    allowed_teams = restrictions.get("teams", [])

    # Simplified check - in practice would need team membership verification
    user_login = (current_user or {}).get("login", "")

    if allowed_users and user_login not in [user.get("login", "") for user in allowed_users]:
        errors.append(
            f"User '{user_login}' is not in the list of users allowed to push to this branch"
        )

    if allowed_teams:
        # Team membership check would require additional API calls
        errors.append("Branch has team-based push restrictions - verify team membership")

    return errors


async def _get_current_user() -> dict[str, Any] | None:
    """Get current GitHub user information."""
    try:
        cmd = ["gh", "api", "user"]

        result = await run_command_async(cmd)
        if result.returncode == 0 and result.stdout.strip():
            user_data: dict[str, Any] = json.loads(result.stdout)
            return user_data
        else:
            logger.debug(f"Could not fetch current user info: {result.stderr}")
            return None

    except Exception as e:
        logger.debug(f"Error fetching current user info: {e}")
        return None


async def validate_branch_protection(
    branch_name: str, owner: str, repo: str
) -> tuple[bool, list[str]]:
    """Legacy validate branch protection function for backward compatibility."""
    # Create repository object for the new function
    repository = GitHubRepository(owner=owner, name=repo, default_branch=branch_name)

    # Use a default config for this legacy function
    config = get_config()

    # Create a mock PR number - this is a limitation of the legacy interface
    # In practice, this function should be replaced with direct calls to _validate_branch_protection
    try:
        result = await _validate_branch_protection(
            0, repository, config
        )  # Use 0 as placeholder PR number
        return result.success, result.actionable_items
    except Exception:
        # Fallback to simple validation for now
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

        result = await run_command_async(cmd)

        if result.returncode == 0:
            return dict(json.loads(result.stdout))
        else:
            logger.error(f"Failed to get PR info: {result.stderr}")
            return {}

    except Exception as e:
        logger.error(f"Error getting PR info: {e}")
        return {}
