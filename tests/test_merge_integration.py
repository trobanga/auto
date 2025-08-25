"""Integration tests for merge execution functionality."""

from unittest.mock import patch

import pytest

from auto.models import (
    Config,
    DefaultsConfig,
    GitHubRepository,
)
from auto.utils.shell import ShellResult
from auto.workflows.merge import _execute_merge_operation


@pytest.fixture
def integration_repository():
    """Repository for integration testing."""
    return GitHubRepository(owner="testorg", name="integration-test-repo", default_branch="main")


@pytest.fixture
def integration_config():
    """Configuration for integration testing."""
    return Config(
        defaults=DefaultsConfig(
            delete_branch_on_merge=True,
            merge_retry_attempts=2,
            merge_retry_delay=0.1,  # Very short delay for tests
            merge_timeout=60,
        )
    )


class TestMergeIntegrationWorkflow:
    """Test complete merge workflow integration."""

    @pytest.mark.asyncio
    async def test_complete_successful_workflow(self, integration_repository, integration_config):
        """Test complete successful merge workflow from start to finish."""

        # Mock all external dependencies
        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run_cmd,
        ):
            # Setup successful validation
            mock_validate.return_value = (True, [])

            # No conflicts
            mock_conflicts.return_value = None

            # Successful merge command
            successful_result = ShellResult(
                returncode=0,
                stdout="✓ Pull request #456 merged successfully (commit: a1b2c3d4e5f6)",
                stderr="",
                command="gh pr merge 456 --squash --repo testorg/integration-test-repo --delete-branch",
            )
            mock_run_cmd.return_value = successful_result

            # Execute the merge operation
            result = await _execute_merge_operation(
                456, integration_repository, "squash", integration_config
            )

            # Verify complete success
            assert result.success is True
            assert result.method_used == "squash"
            assert result.merge_commit_sha is not None
            assert "a1b2c3d4e5f6" in result.merge_commit_sha
            assert result.retry_count == 0
            assert result.error_message is None
            assert len(result.validation_errors) == 0

            # Verify all steps were called
            mock_validate.assert_called_once_with(
                456, "testorg", "integration-test-repo", force=False
            )
            mock_conflicts.assert_called_once_with(456, "testorg", "integration-test-repo")
            mock_run_cmd.assert_called_once()

    @pytest.mark.asyncio
    async def test_validation_failure_workflow(self, integration_repository, integration_config):
        """Test workflow when validation fails."""

        validation_errors = [
            "PR requires approval from code owners",
            "Status check 'ci/tests' has not passed",
            "Branch protection rules not satisfied",
        ]

        with patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate:
            mock_validate.return_value = (False, validation_errors)

            result = await _execute_merge_operation(
                789, integration_repository, "merge", integration_config
            )

            # Verify validation failure is handled properly
            assert result.success is False
            assert result.validation_errors == validation_errors
            assert "Pre-merge validation failed" in result.error_message
            assert result.merge_commit_sha is None

            # Should not proceed to merge attempts
            assert result.retry_count == 0

    @pytest.mark.asyncio
    async def test_conflict_detection_workflow(self, integration_repository, integration_config):
        """Test workflow when merge conflicts are detected."""

        conflicted_files = ["src/main.py", "package.json", "README.md"]

        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
        ):
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = conflicted_files

            result = await _execute_merge_operation(
                321, integration_repository, "rebase", integration_config
            )

            # Verify conflict handling
            assert result.success is False
            assert result.conflict_details is not None
            assert result.conflict_details.conflicted_files == conflicted_files
            assert len(result.conflict_details.resolution_suggestions) > 0
            assert "conflicts detected" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_retry_mechanism_integration(self, integration_repository, integration_config):
        """Test retry mechanism with realistic failure scenarios."""

        # First attempt: API rate limit (recoverable)
        rate_limit_result = ShellResult(
            returncode=1,
            stdout="",
            stderr="API rate limit exceeded. Please wait and try again.",
            command="gh pr merge",
        )

        # Second attempt: Network timeout (recoverable)
        ShellResult(
            returncode=1, stdout="", stderr="Network timeout occurred", command="gh pr merge"
        )

        # Third attempt: Success
        success_result = ShellResult(
            returncode=0,
            stdout="✓ Pull request #999 merged (commit: success123)",
            stderr="",
            command="gh pr merge",
        )

        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run_cmd,
            patch("asyncio.sleep") as mock_sleep,
        ):
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_sleep.return_value = None

            # Simulate the retry sequence
            mock_run_cmd.side_effect = [
                rate_limit_result,
                success_result,  # Success on second attempt (retry_count=1)
            ]

            result = await _execute_merge_operation(
                999, integration_repository, "merge", integration_config
            )

            # Verify retry worked
            assert result.success is True
            assert result.retry_count == 1  # One retry was performed
            assert result.merge_commit_sha == "success123"

            # Verify sleep was called during retry
            mock_sleep.assert_called_once_with(0.1)

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_workflow(self, integration_repository, integration_config):
        """Test workflow when all retries are exhausted."""

        persistent_error = ShellResult(
            returncode=1, stdout="", stderr="Temporary service unavailable", command="gh pr merge"
        )

        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run_cmd,
            patch("asyncio.sleep") as mock_sleep,
        ):
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_sleep.return_value = None

            # All attempts fail with recoverable error
            mock_run_cmd.return_value = persistent_error

            result = await _execute_merge_operation(
                111, integration_repository, "merge", integration_config
            )

            # Verify all retries were exhausted
            assert result.success is False
            assert result.retry_count == 1  # Final attempt number (0-indexed)
            assert "failed after 2 attempts" in result.error_message

            # Verify sleep was called for each retry
            assert mock_sleep.call_count == 1  # One sleep between attempts 0 and 1

    @pytest.mark.asyncio
    async def test_timeout_integration_workflow(self, integration_repository, integration_config):
        """Test integration workflow with command timeouts."""

        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run_cmd,
        ):
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None

            # Simulate timeout on all attempts
            mock_run_cmd.side_effect = TimeoutError()

            result = await _execute_merge_operation(
                222, integration_repository, "squash", integration_config
            )

            # Verify timeout handling
            assert result.success is False
            assert "timed out" in result.error_message
            assert result.retry_count == 1  # All retries exhausted

    @pytest.mark.asyncio
    async def test_mixed_error_scenarios(self, integration_repository, integration_config):
        """Test workflow with mixed error scenarios."""

        # First attempt: Timeout
        # Second attempt: Rate limit (recoverable)
        # Final result: Still fails with non-recoverable error

        non_recoverable_error = ShellResult(
            returncode=1,
            stdout="",
            stderr="Pull request has already been merged",
            command="gh pr merge",
        )

        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run_cmd,
            patch("asyncio.sleep") as mock_sleep,
        ):
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_sleep.return_value = None

            # Mix of timeout and non-recoverable error
            mock_run_cmd.side_effect = [
                TimeoutError(),  # First attempt
                non_recoverable_error,  # Second attempt (should not retry)
            ]

            result = await _execute_merge_operation(
                333, integration_repository, "merge", integration_config
            )

            # Should fail after second attempt due to non-recoverable error
            assert result.success is False
            assert result.retry_count == 1
            assert "already been merged" in result.error_message

    @pytest.mark.asyncio
    async def test_configuration_integration(self, integration_repository):
        """Test integration with different configuration options."""

        # Custom configuration
        custom_config = Config(
            defaults=DefaultsConfig(
                delete_branch_on_merge=False,  # Don't delete branch
                merge_retry_attempts=1,  # Only one retry
                merge_retry_delay=0.05,
                merge_timeout=30,
            )
        )

        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run_cmd,
        ):
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None

            success_result = ShellResult(0, "Success", "", "gh pr merge")
            mock_run_cmd.return_value = success_result

            result = await _execute_merge_operation(
                444, integration_repository, "rebase", custom_config
            )

            # Verify custom configuration was used
            assert result.success is True

            # Check that --delete-branch was NOT added to command and --rebase was used
            # Get the first call (merge command), not the last call (SHA extraction)
            first_call_args = mock_run_cmd.call_args_list[0][0][0]
            assert "--delete-branch" not in first_call_args
            assert "--rebase" in first_call_args


class TestErrorRecoveryIntegration:
    """Test error recovery in integration scenarios."""

    @pytest.mark.asyncio
    async def test_github_api_integration_errors(self, integration_repository, integration_config):
        """Test integration with real GitHub API error scenarios."""

        github_api_errors = [
            "GitHub API responded with status 502",
            "502 Bad Gateway from GitHub",
            "503 Service temporarily unavailable",
            "504 Gateway timeout from api.github.com",
            "Connection reset by GitHub servers",
        ]

        success_result = ShellResult(0, "✓ Merged successfully", "", "gh pr merge")

        for error_msg in github_api_errors:
            error_result = ShellResult(1, "", error_msg, "gh pr merge")

            with (
                patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
                patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
                patch("auto.workflows.merge.run_command_async") as mock_run_cmd,
                patch("asyncio.sleep") as mock_sleep,
            ):
                mock_validate.return_value = (True, [])
                mock_conflicts.return_value = None
                mock_sleep.return_value = None

                # First attempt fails with API error, second succeeds
                mock_run_cmd.side_effect = [error_result, success_result]

                result = await _execute_merge_operation(
                    555, integration_repository, "merge", integration_config
                )

                # Should recover from API errors
                assert result.success is True, f"Failed to recover from: {error_msg}"
                assert result.retry_count == 1

    @pytest.mark.asyncio
    async def test_comprehensive_workflow_validation(
        self, integration_repository, integration_config
    ):
        """Test comprehensive workflow with all components working together."""

        # This test verifies the entire workflow pipeline works correctly
        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run_cmd,
        ):
            # Successful validation
            mock_validate.return_value = (True, [])

            # No conflicts
            mock_conflicts.return_value = None

            # Successful merge with detailed output
            success_output = """
✓ Pull request #777 merged successfully into main
Commit: 1a2b3c4d5e6f7g8h9i0j
Method: squash
Branch: feature/test-branch (deleted)
"""

            # Mock that returns different commands based on the method used
            def mock_command_response(*args, **kwargs):
                cmd = args[0] if args else []
                command_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                return ShellResult(0, success_output, "", command_str)

            mock_run_cmd.side_effect = mock_command_response

            # Execute with all merge methods
            for method in ["merge", "squash", "rebase"]:
                result = await _execute_merge_operation(
                    777, integration_repository, method, integration_config
                )

                # Comprehensive verification
                assert result.success is True
                assert result.method_used == method
                assert result.merge_commit_sha is not None
                assert result.retry_count == 0
                assert result.error_message is None
                assert len(result.validation_errors) == 0
                assert result.conflict_details is None

                # Verify GitHub API response is captured
                assert result.github_api_response["returncode"] == 0
                assert "merged successfully" in result.github_api_response["stdout"]
                assert result.github_api_response["stderr"] == ""
                assert method in result.github_api_response["command"]
