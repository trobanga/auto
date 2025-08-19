"""Tests for merge automation workflow."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from auto.workflows.merge import (
    MergeConflictError,
    MergeValidationError,
    _execute_merge,
    _get_pr_info,
    _validate_reviews,
    _validate_status_checks,
    cleanup_after_merge,
    execute_auto_merge,
    handle_merge_conflicts,
    validate_merge_eligibility,
)


class TestMergeAutomation:
    """Test merge automation functions."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration."""
        config = MagicMock()
        config.defaults.merge_method = "merge"
        config.defaults.delete_branch_on_merge = True
        return config

    @pytest.fixture
    def mock_pr_info(self):
        """Mock PR information."""
        return {
            "state": "open",
            "draft": False,
            "mergeable": True,
            "reviews": [
                {"state": "APPROVED", "user": {"login": "reviewer1"}},
            ],
            "statusCheckRollup": [
                {"state": "SUCCESS", "name": "ci/build"},
            ],
            "base": {"ref": "main"},
        }

    @pytest.mark.asyncio
    async def test_execute_auto_merge_success(self, mock_config, mock_pr_info):
        """Test successful automated merge."""
        with (
            patch("auto.workflows.merge.GitHubIntegration"),
            patch("auto.workflows.merge.get_config", return_value=mock_config),
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge._execute_merge") as mock_execute,
            patch("auto.workflows.merge.cleanup_after_merge") as mock_cleanup,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_execute.return_value = True
            mock_cleanup.return_value = None

            # Execute
            result = await execute_auto_merge(123, "owner", "repo")

            # Assert
            assert result is True
            mock_validate.assert_called_once_with(123, "owner", "repo", False)
            mock_conflicts.assert_called_once_with(123, "owner", "repo")
            mock_execute.assert_called_once_with(123, "owner", "repo", "merge")

    @pytest.mark.asyncio
    async def test_execute_auto_merge_validation_failure(self, mock_config):
        """Test merge with validation failure."""
        with (
            patch("auto.workflows.merge.GitHubIntegration"),
            patch("auto.workflows.merge.get_config", return_value=mock_config),
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
        ):
            # Setup validation failure
            mock_validate.return_value = (False, ["PR is in draft state"])

            # Execute and assert exception
            with pytest.raises(MergeValidationError) as exc_info:
                await execute_auto_merge(123, "owner", "repo")

            assert "PR is in draft state" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_auto_merge_conflicts(self, mock_config):
        """Test merge with conflicts."""
        with (
            patch("auto.workflows.merge.GitHubIntegration"),
            patch("auto.workflows.merge.get_config", return_value=mock_config),
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = ["Conflict in file.py"]

            # Execute and assert exception
            with pytest.raises(MergeConflictError) as exc_info:
                await execute_auto_merge(123, "owner", "repo")

            assert "Conflict in file.py" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_auto_merge_force_override(self, mock_config):
        """Test merge with force override."""
        with (
            patch("auto.workflows.merge.GitHubIntegration"),
            patch("auto.workflows.merge.get_config", return_value=mock_config),
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge._execute_merge") as mock_execute,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])  # Force should make validation pass
            mock_conflicts.return_value = ["Conflict in file.py"]
            mock_execute.return_value = True

            # Execute with force
            result = await execute_auto_merge(123, "owner", "repo", force=True)

            # Assert - should succeed despite conflicts
            assert result is True
            mock_validate.assert_called_once_with(123, "owner", "repo", True)

    @pytest.mark.asyncio
    async def test_validate_merge_eligibility_success(self, mock_pr_info):
        """Test successful merge eligibility validation."""
        with (
            patch("auto.workflows.merge._get_pr_info", return_value=mock_pr_info),
            patch("auto.workflows.merge._validate_reviews") as mock_reviews,
            patch("auto.workflows.merge._validate_status_checks") as mock_checks,
            patch("auto.workflows.merge._validate_branch_protection") as mock_protection,
        ):
            # Setup mocks
            mock_reviews.return_value = (True, [])
            mock_checks.return_value = (True, [])
            mock_protection.return_value = (True, [])

            # Execute
            is_eligible, errors = await validate_merge_eligibility(123, "owner", "repo")

            # Assert
            assert is_eligible is True
            assert errors == []

    @pytest.mark.asyncio
    async def test_validate_merge_eligibility_draft_pr(self, mock_pr_info):
        """Test validation failure for draft PR."""
        mock_pr_info["draft"] = True

        with (
            patch("auto.workflows.merge._get_pr_info", return_value=mock_pr_info),
            patch("auto.workflows.merge._validate_reviews") as mock_reviews,
            patch("auto.workflows.merge._validate_status_checks") as mock_checks,
            patch("auto.workflows.merge._validate_branch_protection") as mock_protection,
        ):
            # Setup mocks
            mock_reviews.return_value = (True, [])
            mock_checks.return_value = (True, [])
            mock_protection.return_value = (True, [])

            # Execute
            is_eligible, errors = await validate_merge_eligibility(123, "owner", "repo")

            # Assert
            assert is_eligible is False
            assert "PR is in draft state" in errors

    @pytest.mark.asyncio
    async def test_validate_merge_eligibility_not_mergeable(self, mock_pr_info):
        """Test validation failure for non-mergeable PR."""
        mock_pr_info["mergeable"] = False

        with (
            patch("auto.workflows.merge._get_pr_info", return_value=mock_pr_info),
            patch("auto.workflows.merge._validate_reviews") as mock_reviews,
            patch("auto.workflows.merge._validate_status_checks") as mock_checks,
            patch("auto.workflows.merge._validate_branch_protection") as mock_protection,
        ):
            # Setup mocks
            mock_reviews.return_value = (True, [])
            mock_checks.return_value = (True, [])
            mock_protection.return_value = (True, [])

            # Execute
            is_eligible, errors = await validate_merge_eligibility(123, "owner", "repo")

            # Assert
            assert is_eligible is False
            assert "PR has conflicts that must be resolved" in errors

    @pytest.mark.asyncio
    async def test_cleanup_after_merge_success(self):
        """Test successful post-merge cleanup."""
        worktree_path = Path("/test/worktree")

        with (
            patch("auto.workflows.merge.GitIntegration") as mock_git_class,
            patch("auto.workflows.merge._update_issue_status_after_merge") as mock_update,
            patch("auto.workflows.merge._cleanup_temporary_files") as mock_cleanup,
            patch("pathlib.Path.exists", return_value=True),  # Mock path exists
        ):
            mock_git = MagicMock()
            mock_git.remove_worktree = MagicMock()  # Not async
            mock_git_class.return_value = mock_git

            # Execute
            await cleanup_after_merge(worktree_path, "owner", "repo")

            # Assert - function calls remove_worktree with WorktreeInfo, not path directly
            mock_git.remove_worktree.assert_called_once()
            call_args = mock_git.remove_worktree.call_args[0][0]  # Get first argument
            assert call_args.path == str(worktree_path)
            assert call_args.branch == "worktree"  # Last component of path

            mock_update.assert_called_once_with("owner", "repo")
            mock_cleanup.assert_called_once_with(worktree_path)

    @pytest.mark.asyncio
    async def test_handle_merge_conflicts_no_conflicts(self, mock_pr_info):
        """Test conflict detection with no conflicts."""
        with patch("auto.workflows.merge._get_pr_info", return_value=mock_pr_info):
            # Execute
            conflicts = await handle_merge_conflicts(123, "owner", "repo")

            # Assert
            assert conflicts is None

    @pytest.mark.asyncio
    async def test_handle_merge_conflicts_with_conflicts(self, mock_pr_info):
        """Test conflict detection with conflicts."""
        mock_pr_info["mergeable"] = False

        with (
            patch("auto.workflows.merge._get_pr_info", return_value=mock_pr_info),
            patch("auto.workflows.merge._get_conflict_details") as mock_details,
        ):
            mock_details.return_value = ["Conflict in file.py", "Conflict in other.py"]

            # Execute
            conflicts = await handle_merge_conflicts(123, "owner", "repo")

            # Assert
            assert conflicts == ["Conflict in file.py", "Conflict in other.py"]


class TestMergeHelperFunctions:
    """Test merge helper functions."""

    @pytest.mark.asyncio
    async def test_execute_merge_success(self):
        """Test successful merge execution."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Merged successfully"

        with (
            patch("auto.workflows.merge.run_command", return_value=mock_result) as mock_run,
            patch("auto.workflows.merge.get_config") as mock_config,
        ):
            config = MagicMock()
            config.defaults.delete_branch_on_merge = True
            mock_config.return_value = config

            # Execute
            result = await _execute_merge(123, "owner", "repo", "squash")

            # Assert
            assert result is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "gh" in call_args
            assert "pr" in call_args
            assert "merge" in call_args
            assert "123" in call_args
            assert "--squash" in call_args
            assert "--delete-branch" in call_args

    @pytest.mark.asyncio
    async def test_execute_merge_failure(self):
        """Test merge execution failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Merge failed"

        with (
            patch("auto.workflows.merge.run_command", return_value=mock_result),
            patch("auto.workflows.merge.get_config") as mock_config,
        ):
            config = MagicMock()
            config.defaults.delete_branch_on_merge = False
            mock_config.return_value = config

            # Execute
            result = await _execute_merge(123, "owner", "repo")

            # Assert
            assert result is False

    @pytest.mark.asyncio
    async def test_get_pr_info_success(self):
        """Test getting PR info successfully."""
        _expected_data = {"state": "open", "mergeable": True}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"state": "open", "mergeable": true}'

        with patch("auto.workflows.merge.run_command", return_value=mock_result):
            # Execute
            pr_info = await _get_pr_info(123, "owner", "repo")

            # Assert
            assert pr_info["state"] == "open"
            assert pr_info["mergeable"] is True

    @pytest.mark.asyncio
    async def test_get_pr_info_failure(self):
        """Test getting PR info failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "PR not found"

        with patch("auto.workflows.merge.run_command", return_value=mock_result):
            # Execute
            pr_info = await _get_pr_info(123, "owner", "repo")

            # Assert
            assert pr_info == {}

    @pytest.mark.asyncio
    async def test_validate_reviews_success(self):
        """Test review validation success."""
        pr_info = {
            "reviews": [
                {"state": "APPROVED", "user": {"login": "reviewer1"}},
                {"state": "COMMENTED", "user": {"login": "reviewer2"}},
            ]
        }

        with patch("auto.workflows.merge._get_pr_info", return_value=pr_info):
            # Execute
            is_valid, errors = await _validate_reviews(123, "owner", "repo")

            # Assert
            assert is_valid is True
            assert errors == []

    @pytest.mark.asyncio
    async def test_validate_reviews_no_approvals(self):
        """Test review validation with no approvals."""
        pr_info = {
            "reviews": [
                {"state": "COMMENTED", "user": {"login": "reviewer1"}},
            ]
        }

        with patch("auto.workflows.merge._get_pr_info", return_value=pr_info):
            # Execute
            is_valid, errors = await _validate_reviews(123, "owner", "repo")

            # Assert
            assert is_valid is False
            assert "No approving reviews found" in errors

    @pytest.mark.asyncio
    async def test_validate_reviews_change_requests(self):
        """Test review validation with change requests."""
        pr_info = {
            "reviews": [
                {"state": "APPROVED", "user": {"login": "reviewer1"}},
                {"state": "CHANGES_REQUESTED", "user": {"login": "reviewer2"}},
            ]
        }

        with patch("auto.workflows.merge._get_pr_info", return_value=pr_info):
            # Execute
            is_valid, errors = await _validate_reviews(123, "owner", "repo")

            # Assert
            assert is_valid is False
            assert "1 unresolved change requests" in errors

    @pytest.mark.asyncio
    async def test_validate_status_checks_success(self):
        """Test status check validation success."""
        pr_info = {
            "statusCheckRollup": [
                {"state": "SUCCESS", "name": "ci/build"},
                {"state": "SUCCESS", "name": "ci/test"},
            ]
        }

        with patch("auto.workflows.merge._get_pr_info", return_value=pr_info):
            # Execute
            is_valid, errors = await _validate_status_checks(123, "owner", "repo")

            # Assert
            assert is_valid is True
            assert errors == []

    @pytest.mark.asyncio
    async def test_validate_status_checks_failures(self):
        """Test status check validation with failures."""
        pr_info = {
            "statusCheckRollup": [
                {"state": "SUCCESS", "name": "ci/build"},
                {"state": "FAILURE", "name": "ci/test"},
                {"state": "ERROR", "name": "ci/lint"},
            ]
        }

        with patch("auto.workflows.merge._get_pr_info", return_value=pr_info):
            # Execute
            is_valid, errors = await _validate_status_checks(123, "owner", "repo")

            # Assert
            assert is_valid is False
            assert "Failing status checks: ci/test, ci/lint" in errors

    @pytest.mark.asyncio
    async def test_validate_status_checks_pending(self):
        """Test status check validation with pending checks."""
        pr_info = {
            "statusCheckRollup": [
                {"state": "SUCCESS", "name": "ci/build"},
                {"state": "PENDING", "name": "ci/test"},
            ]
        }

        with patch("auto.workflows.merge._get_pr_info", return_value=pr_info):
            # Execute
            is_valid, errors = await _validate_status_checks(123, "owner", "repo")

            # Assert
            assert is_valid is False
            assert "Pending status checks: ci/test" in errors


class TestMergeIntegration:
    """Integration tests for merge automation."""

    @pytest.mark.asyncio
    async def test_full_merge_workflow_success(self):
        """Test complete merge workflow."""
        worktree_path = Path("/test/worktree")

        # Mock all external dependencies
        mock_config = MagicMock()
        mock_config.defaults.merge_method = "squash"
        mock_config.defaults.delete_branch_on_merge = True

        mock_pr_info = {
            "state": "open",
            "draft": False,
            "mergeable": True,
            "reviews": [{"state": "APPROVED"}],
            "statusCheckRollup": [{"state": "SUCCESS", "name": "ci"}],
            "base": {"ref": "main"},
        }

        mock_merge_result = MagicMock()
        mock_merge_result.returncode = 0

        with (
            patch("auto.workflows.merge.GitHubIntegration"),
            patch("auto.workflows.merge.get_config", return_value=mock_config),
            patch("auto.workflows.merge._get_pr_info", return_value=mock_pr_info),
            patch("auto.workflows.merge._validate_reviews", return_value=(True, [])),
            patch("auto.workflows.merge._validate_status_checks", return_value=(True, [])),
            patch("auto.workflows.merge._validate_branch_protection", return_value=(True, [])),
            patch("auto.workflows.merge.run_command", return_value=mock_merge_result),
            patch("auto.workflows.merge.cleanup_after_merge") as mock_cleanup,
        ):
            # Execute full workflow
            result = await execute_auto_merge(
                pr_number=123, owner="test-owner", repo="test-repo", worktree_path=worktree_path
            )

            # Assert
            assert result is True
            mock_cleanup.assert_called_once_with(worktree_path, "test-owner", "test-repo")

    @pytest.mark.asyncio
    async def test_merge_workflow_with_validation_errors(self):
        """Test merge workflow with multiple validation errors."""
        mock_config = MagicMock()
        mock_config.defaults.merge_method = "merge"

        mock_pr_info = {
            "state": "open",
            "draft": True,  # Draft PR
            "mergeable": False,  # Has conflicts
            "reviews": [],  # No reviews
            "statusCheckRollup": [{"state": "FAILURE", "name": "ci"}],  # Failing checks
            "base": {"ref": "main"},
        }

        with (
            patch("auto.workflows.merge.GitHubIntegration"),
            patch("auto.workflows.merge.get_config", return_value=mock_config),
            patch("auto.workflows.merge._get_pr_info", return_value=mock_pr_info),
            patch("auto.workflows.merge._validate_reviews", return_value=(False, ["No approvals"])),
            patch(
                "auto.workflows.merge._validate_status_checks",
                return_value=(False, ["Failing checks"]),
            ),
            patch("auto.workflows.merge._validate_branch_protection", return_value=(True, [])),
        ):
            # Execute and expect validation failure
            with pytest.raises(MergeValidationError) as exc_info:
                await execute_auto_merge(123, "owner", "repo")

            # Assert multiple validation errors are reported
            error_message = str(exc_info.value)
            assert "draft state" in error_message
            assert "conflicts" in error_message
