"""
Tests for branch protection rule validation in merge workflow.

This module tests the comprehensive branch protection validation system that ensures
PRs comply with GitHub branch protection rules before merge operations.
"""

import json
from unittest.mock import patch

import pytest

from auto.models import Config, GitHubConfig, GitHubRepository, ValidationResult, WorkflowsConfig
from auto.utils.shell import ShellResult
from auto.workflows.merge_validation import _validate_branch_protection


@pytest.fixture
def mock_repository():
    """Create mock repository for testing."""
    return GitHubRepository(owner="test-owner", name="test-repo", default_branch="main")


@pytest.fixture
def base_config():
    """Create base configuration for testing."""
    return Config(
        github=GitHubConfig(required_approvals=1, required_reviewers=[]),
        workflows=WorkflowsConfig(require_human_approval=True),
    )


@pytest.fixture
def mock_get_pr_info():
    """Create mock _get_pr_info function."""
    with patch("auto.workflows.merge_validation._get_pr_info") as mock_func:
        yield mock_func


@pytest.fixture
def mock_run_command_async():
    """Create mock run_command_async function."""
    with patch("auto.workflows.merge_validation.run_command_async") as mock_func:
        yield mock_func


@pytest.fixture
def mock_validate_reviews():
    """Create mock validate_reviews function."""
    with patch("auto.workflows.merge_validation.validate_reviews") as mock_func:
        yield mock_func


@pytest.fixture
def mock_validate_status_checks():
    """Create mock _validate_status_checks function."""
    with patch("auto.workflows.merge_validation._validate_status_checks") as mock_func:
        yield mock_func


class TestValidateBranchProtection:
    """Test the _validate_branch_protection function."""

    @pytest.mark.asyncio
    async def test_successful_validation_no_protection(
        self, mock_repository, base_config, mock_get_pr_info, mock_run_command_async
    ):
        """Test successful validation when no branch protection is configured."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }
        mock_run_command_async.return_value = ShellResult(
            returncode=1, stdout="", stderr="Branch protection not enabled", command="gh api"
        )

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is True
        assert "No branch protection rules configured" in result.message
        assert result.details["protection_enabled"] is False
        assert result.details["base_branch"] == "main"
        assert len(result.actionable_items) == 0

    @pytest.mark.asyncio
    async def test_successful_validation_with_satisfied_protection(
        self,
        mock_repository,
        base_config,
        mock_get_pr_info,
        mock_run_command_async,
        mock_validate_reviews,
        mock_validate_status_checks,
    ):
        """Test successful validation with satisfied branch protection rules."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }

        # Mock protection rules
        protection_data = {
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": False,
                "require_code_owner_reviews": False,
            },
            "required_status_checks": {
                "strict": False,
                "contexts": ["ci/test"],
                "enforce_admins": False,
            },
            "restrictions": None,
        }

        # Mock multiple API calls
        def mock_command_side_effect(cmd, *args, **kwargs):
            if "protection" in cmd[2]:
                return ShellResult(
                    returncode=0, stdout=json.dumps(protection_data), stderr="", command="gh api"
                )
            elif len(cmd) > 4 and cmd[4] == ".permissions":
                return ShellResult(
                    returncode=0,
                    stdout='{"admin": false, "push": true}',
                    stderr="",
                    command="gh api",
                )
            elif cmd[2] == "user":
                return ShellResult(
                    returncode=0, stdout='{"login": "test-user"}', stderr="", command="gh api"
                )
            return ShellResult(returncode=1, stdout="", stderr="Not found", command="gh api")

        mock_run_command_async.side_effect = mock_command_side_effect

        # Mock validation functions returning success
        mock_validate_reviews.return_value = ValidationResult(
            success=True, message="Reviews OK", details={"approval_count": 1}, actionable_items=[]
        )
        mock_validate_status_checks.return_value = ValidationResult(
            success=True, message="Status checks OK", details={}, actionable_items=[]
        )

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is True
        assert "Branch protection rules for 'main' are satisfied" in result.message
        assert result.details["protection_enabled"] is True
        assert result.details["user_is_admin"] is False
        assert len(result.actionable_items) == 0

    @pytest.mark.asyncio
    async def test_validation_fails_insufficient_reviews(
        self,
        mock_repository,
        base_config,
        mock_get_pr_info,
        mock_run_command_async,
        mock_validate_reviews,
        mock_validate_status_checks,
    ):
        """Test validation fails when insufficient reviews for branch protection."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }

        protection_data = {
            "required_pull_request_reviews": {
                "required_approving_review_count": 2,
                "dismiss_stale_reviews": False,
                "require_code_owner_reviews": False,
            },
            "required_status_checks": None,
            "restrictions": None,
        }

        def mock_command_side_effect(cmd, *args, **kwargs):
            if "protection" in cmd[2]:
                return ShellResult(
                    returncode=0, stdout=json.dumps(protection_data), stderr="", command="gh api"
                )
            elif (
                len(cmd) > 4
                and cmd[2].startswith("repos/")
                and cmd[3] == "--jq"
                and cmd[4] == ".permissions"
            ):
                return ShellResult(
                    returncode=0,
                    stdout='{"admin": false, "push": true}',
                    stderr="",
                    command="gh api",
                )
            elif cmd[2] == "user":
                return ShellResult(
                    returncode=0, stdout='{"login": "test-user"}', stderr="", command="gh api"
                )
            return ShellResult(returncode=1, stdout="", stderr="Not found", command="gh api")

        mock_run_command_async.side_effect = mock_command_side_effect

        # Mock validation functions - reviews insufficient
        mock_validate_reviews.return_value = ValidationResult(
            success=False,
            message="Need more reviews",
            details={"approval_count": 1},
            actionable_items=[],
        )
        mock_validate_status_checks.return_value = ValidationResult(
            success=True, message="Status checks OK", details={}, actionable_items=[]
        )

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is False
        assert "Branch protection validation failed" in result.message
        assert "requires 2 approving reviews, but only 1 found" in result.actionable_items[0]

    @pytest.mark.asyncio
    async def test_validation_fails_status_checks(
        self,
        mock_repository,
        base_config,
        mock_get_pr_info,
        mock_run_command_async,
        mock_validate_reviews,
        mock_validate_status_checks,
    ):
        """Test validation fails when status checks don't pass."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }

        protection_data = {
            "required_pull_request_reviews": None,
            "required_status_checks": {
                "strict": False,
                "contexts": ["ci/test", "ci/lint"],
                "enforce_admins": False,
            },
            "restrictions": None,
        }

        def mock_command_side_effect(cmd, *args, **kwargs):
            if "protection" in cmd[2]:
                return ShellResult(
                    returncode=0, stdout=json.dumps(protection_data), stderr="", command="gh api"
                )
            elif (
                len(cmd) > 4
                and cmd[2].startswith("repos/")
                and cmd[3] == "--jq"
                and cmd[4] == ".permissions"
            ):
                return ShellResult(
                    returncode=0,
                    stdout='{"admin": false, "push": true}',
                    stderr="",
                    command="gh api",
                )
            elif cmd[2] == "user":
                return ShellResult(
                    returncode=0, stdout='{"login": "test-user"}', stderr="", command="gh api"
                )
            return ShellResult(returncode=1, stdout="", stderr="Not found", command="gh api")

        mock_run_command_async.side_effect = mock_command_side_effect

        # Mock validation functions - status checks failing
        mock_validate_reviews.return_value = ValidationResult(
            success=True, message="Reviews OK", details={"approval_count": 1}, actionable_items=[]
        )
        mock_validate_status_checks.return_value = ValidationResult(
            success=False,
            message="Status checks failing",
            details={},
            actionable_items=["Fix failing check: ci/test", "Fix failing check: ci/lint"],
        )

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is False
        assert "Branch protection requires all status checks to pass" in result.actionable_items[0]
        assert "Fix failing check: ci/test" in result.actionable_items[1]

    @pytest.mark.asyncio
    async def test_validation_with_admin_override(
        self,
        mock_repository,
        base_config,
        mock_get_pr_info,
        mock_run_command_async,
        mock_validate_reviews,
        mock_validate_status_checks,
    ):
        """Test validation with administrator override capabilities."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }

        protection_data = {
            "required_pull_request_reviews": {
                "required_approving_review_count": 2,
                "dismiss_stale_reviews": False,
                "require_code_owner_reviews": False,
            },
            "required_status_checks": {
                "strict": False,
                "contexts": ["ci/test"],
                "enforce_admins": False,  # Admins can override
            },
            "restrictions": None,
        }

        def mock_command_side_effect(cmd, *args, **kwargs):
            if "protection" in cmd[2]:
                return ShellResult(
                    returncode=0, stdout=json.dumps(protection_data), stderr="", command="gh api"
                )
            elif len(cmd) > 4 and cmd[4] == ".permissions":
                return ShellResult(
                    returncode=0,
                    stdout='{"admin": true, "push": true}',
                    stderr="",  # Admin user
                    command="gh api",
                )
            return ShellResult(returncode=1, stdout="", stderr="Not found", command="gh api")

        mock_run_command_async.side_effect = mock_command_side_effect

        # Mock validation functions - would normally fail but admin can override
        mock_validate_reviews.return_value = ValidationResult(
            success=False,
            message="Need more reviews",
            details={"approval_count": 1},
            actionable_items=[],
        )
        mock_validate_status_checks.return_value = ValidationResult(
            success=True, message="Status checks OK", details={}, actionable_items=[]
        )

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions - admin should bypass requirements when enforce_admins=False
        assert result.success is True
        assert "administrator access confirmed" in result.message
        assert result.details["user_is_admin"] is True

    @pytest.mark.asyncio
    async def test_validation_with_push_restrictions(
        self,
        mock_repository,
        base_config,
        mock_get_pr_info,
        mock_run_command_async,
        mock_validate_reviews,
        mock_validate_status_checks,
    ):
        """Test validation with push restrictions."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }

        protection_data = {
            "required_pull_request_reviews": None,
            "required_status_checks": None,
            "restrictions": {
                "users": [{"login": "approved-user"}],
                "teams": [{"name": "core-team"}],
            },
        }

        def mock_command_side_effect(cmd, *args, **kwargs):
            if "protection" in cmd[2]:
                return ShellResult(
                    returncode=0, stdout=json.dumps(protection_data), stderr="", command="gh api"
                )
            elif len(cmd) > 4 and cmd[4] == ".permissions":
                return ShellResult(
                    returncode=0,
                    stdout='{"admin": false, "push": true}',
                    stderr="",
                    command="gh api",
                )
            elif cmd[2] == "user":
                return ShellResult(
                    returncode=0,
                    stdout='{"login": "other-user"}',
                    stderr="",  # Not in approved list
                    command="gh api",
                )
            return ShellResult(returncode=1, stdout="", stderr="Not found", command="gh api")

        mock_run_command_async.side_effect = mock_command_side_effect

        mock_validate_reviews.return_value = ValidationResult(
            success=True, message="Reviews OK", details={}, actionable_items=[]
        )
        mock_validate_status_checks.return_value = ValidationResult(
            success=True, message="Status checks OK", details={}, actionable_items=[]
        )

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is False
        assert any(
            "not in the list of users allowed to push" in item for item in result.actionable_items
        )
        assert any("team-based push restrictions" in item for item in result.actionable_items)

    @pytest.mark.asyncio
    async def test_validation_with_stale_reviews(
        self,
        mock_repository,
        base_config,
        mock_get_pr_info,
        mock_run_command_async,
        mock_validate_reviews,
        mock_validate_status_checks,
    ):
        """Test validation with stale review dismissal enabled."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }

        protection_data = {
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": True,  # Stale reviews are dismissed
                "require_code_owner_reviews": False,
            },
            "required_status_checks": None,
            "restrictions": None,
        }

        def mock_command_side_effect(cmd, *args, **kwargs):
            if "protection" in cmd[2]:
                return ShellResult(
                    returncode=0, stdout=json.dumps(protection_data), stderr="", command="gh api"
                )
            elif (
                len(cmd) > 4
                and cmd[2].startswith("repos/")
                and cmd[3] == "--jq"
                and cmd[4] == ".permissions"
            ):
                return ShellResult(
                    returncode=0,
                    stdout='{"admin": false, "push": true}',
                    stderr="",
                    command="gh api",
                )
            elif cmd[2] == "user":
                return ShellResult(
                    returncode=0, stdout='{"login": "test-user"}', stderr="", command="gh api"
                )
            return ShellResult(returncode=1, stdout="", stderr="Not found", command="gh api")

        mock_run_command_async.side_effect = mock_command_side_effect

        # Mock validation functions - has stale reviews
        mock_validate_reviews.return_value = ValidationResult(
            success=True,
            message="Reviews OK",
            details={"approval_count": 1, "stale_reviewers": ["reviewer1"]},
            actionable_items=[],
        )
        mock_validate_status_checks.return_value = ValidationResult(
            success=True, message="Status checks OK", details={}, actionable_items=[]
        )

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is False
        assert "dismisses stale reviews" in result.actionable_items[0]
        assert "1 stale review(s) found from reviewer1" in result.actionable_items[0]

    @pytest.mark.asyncio
    async def test_validation_with_code_owner_reviews(
        self,
        mock_repository,
        base_config,
        mock_get_pr_info,
        mock_run_command_async,
        mock_validate_reviews,
        mock_validate_status_checks,
    ):
        """Test validation with code owner review requirements."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }

        protection_data = {
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": False,
                "require_code_owner_reviews": True,  # Code owner review required
            },
            "required_status_checks": None,
            "restrictions": None,
        }

        def mock_command_side_effect(cmd, *args, **kwargs):
            if "protection" in cmd[2]:
                return ShellResult(
                    returncode=0, stdout=json.dumps(protection_data), stderr="", command="gh api"
                )
            elif (
                len(cmd) > 4
                and cmd[2].startswith("repos/")
                and cmd[3] == "--jq"
                and cmd[4] == ".permissions"
            ):
                return ShellResult(
                    returncode=0,
                    stdout='{"admin": false, "push": true}',
                    stderr="",
                    command="gh api",
                )
            elif cmd[2] == "user":
                return ShellResult(
                    returncode=0, stdout='{"login": "test-user"}', stderr="", command="gh api"
                )
            return ShellResult(returncode=1, stdout="", stderr="Not found", command="gh api")

        mock_run_command_async.side_effect = mock_command_side_effect

        mock_validate_reviews.return_value = ValidationResult(
            success=True, message="Reviews OK", details={"approval_count": 1}, actionable_items=[]
        )
        mock_validate_status_checks.return_value = ValidationResult(
            success=True, message="Status checks OK", details={}, actionable_items=[]
        )

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is False
        assert any("code owner review" in item for item in result.actionable_items)

    @pytest.mark.asyncio
    async def test_validation_handles_pr_fetch_error(
        self, mock_repository, base_config, mock_get_pr_info
    ):
        """Test validation handles PR information fetch errors."""
        # Setup mock to return None (PR not found)
        mock_get_pr_info.return_value = None

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is False
        assert "Failed to retrieve PR information" in result.message
        assert "Check if the PR exists and is accessible" in result.actionable_items

    @pytest.mark.asyncio
    async def test_validation_handles_api_errors(
        self, mock_repository, base_config, mock_get_pr_info, mock_run_command_async
    ):
        """Test validation handles GitHub API errors gracefully."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }
        mock_run_command_async.side_effect = Exception("API connection failed")

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is False
        assert "API connection failed" in result.message
        assert "Check GitHub API connectivity" in result.actionable_items[0]
        assert result.details["error"] == "API connection failed"

    @pytest.mark.asyncio
    async def test_validation_with_strict_status_checks(
        self,
        mock_repository,
        base_config,
        mock_get_pr_info,
        mock_run_command_async,
        mock_validate_reviews,
        mock_validate_status_checks,
    ):
        """Test validation with strict status checks (branch must be up to date)."""
        # Setup mock data
        mock_get_pr_info.return_value = {
            "baseRefName": "main",
            "state": "open",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviews": {"totalCount": 1},
            "statusCheckRollup": {"state": "SUCCESS"},
        }

        protection_data = {
            "required_pull_request_reviews": None,
            "required_status_checks": {
                "strict": True,  # Branch must be up to date
                "contexts": ["ci/test"],
                "enforce_admins": False,
            },
            "restrictions": None,
        }

        def mock_command_side_effect(cmd, *args, **kwargs):
            if "protection" in cmd[2]:
                return ShellResult(
                    returncode=0, stdout=json.dumps(protection_data), stderr="", command="gh api"
                )
            elif (
                len(cmd) > 4
                and cmd[2].startswith("repos/")
                and cmd[3] == "--jq"
                and cmd[4] == ".permissions"
            ):
                return ShellResult(
                    returncode=0,
                    stdout='{"admin": false, "push": true}',
                    stderr="",
                    command="gh api",
                )
            elif cmd[2] == "user":
                return ShellResult(
                    returncode=0, stdout='{"login": "test-user"}', stderr="", command="gh api"
                )
            return ShellResult(returncode=1, stdout="", stderr="Not found", command="gh api")

        mock_run_command_async.side_effect = mock_command_side_effect

        mock_validate_reviews.return_value = ValidationResult(
            success=True, message="Reviews OK", details={}, actionable_items=[]
        )
        mock_validate_status_checks.return_value = ValidationResult(
            success=True, message="Status checks OK", details={}, actionable_items=[]
        )

        # Execute validation
        result = await _validate_branch_protection(123, mock_repository, base_config)

        # Assertions
        assert result.success is False
        assert any(
            "requires branch to be up to date before merging" in item
            for item in result.actionable_items
        )


class TestHelperFunctions:
    """Test helper functions used by branch protection validation."""

    @pytest.mark.asyncio
    async def test_fetch_branch_protection_rules_success(self, mock_run_command_async):
        """Test successful fetching of branch protection rules."""
        from auto.workflows.merge_validation import _fetch_branch_protection_rules

        protection_data = {"required_pull_request_reviews": {"required_approving_review_count": 1}}
        mock_run_command_async.return_value = ShellResult(
            returncode=0, stdout=json.dumps(protection_data), stderr="", command="gh api"
        )

        result = await _fetch_branch_protection_rules("owner", "repo", "main")

        assert result == protection_data
        mock_run_command_async.assert_called_once()
        assert (
            "repos/owner/repo/branches/main/protection" in mock_run_command_async.call_args[0][0][2]
        )

    @pytest.mark.asyncio
    async def test_fetch_branch_protection_rules_not_found(self, mock_run_command_async):
        """Test fetching branch protection rules when none exist."""
        from auto.workflows.merge_validation import _fetch_branch_protection_rules

        mock_run_command_async.return_value = ShellResult(
            returncode=1, stdout="", stderr="Branch protection not enabled", command="gh api"
        )

        result = await _fetch_branch_protection_rules("owner", "repo", "main")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_permissions_success(self, mock_run_command_async):
        """Test successful fetching of user permissions."""
        from auto.workflows.merge_validation import _get_user_permissions

        permissions = {"admin": True, "push": True, "pull": True}
        mock_run_command_async.return_value = ShellResult(
            returncode=0, stdout=json.dumps(permissions), stderr="", command="gh api"
        )

        result = await _get_user_permissions("owner", "repo")

        assert result == permissions
        mock_run_command_async.assert_called_once()
        assert "repos/owner/repo" in mock_run_command_async.call_args[0][0][2]

    @pytest.mark.asyncio
    async def test_get_current_user_success(self, mock_run_command_async):
        """Test successful fetching of current user information."""
        from auto.workflows.merge_validation import _get_current_user

        user_data = {"login": "test-user", "id": 12345}
        mock_run_command_async.return_value = ShellResult(
            returncode=0, stdout=json.dumps(user_data), stderr="", command="gh api"
        )

        result = await _get_current_user()

        assert result == user_data
        mock_run_command_async.assert_called_once()
        assert mock_run_command_async.call_args[0][0][2] == "user"


if __name__ == "__main__":
    pytest.main([__file__])
