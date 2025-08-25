"""Unit tests for merge execution functionality."""

import json
from unittest.mock import patch

import pytest

from auto.models import (
    Config,
    DefaultsConfig,
    GitHubRepository,
)
from auto.utils.shell import ShellResult
from auto.workflows.merge import (
    _execute_merge_operation,
    _extract_merge_commit_sha,
    _is_recoverable_error,
)


@pytest.fixture
def sample_repository():
    """Sample repository for testing."""
    return GitHubRepository(owner="testorg", name="testrepo")


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return Config(
        defaults=DefaultsConfig(
            delete_branch_on_merge=True,
            merge_retry_attempts=3,
            merge_retry_delay=1,  # Shorter delay for tests
            merge_timeout=30,
        )
    )


@pytest.fixture
def successful_shell_result():
    """Shell result for successful merge."""
    return ShellResult(
        returncode=0,
        stdout="✓ Pull request #123 merged (commit abc123def456)",
        stderr="",
        command="gh pr merge 123 --merge --repo testorg/testrepo",
    )


@pytest.fixture
def failed_shell_result():
    """Shell result for failed merge."""
    return ShellResult(
        returncode=1,
        stdout="",
        stderr="Error: Pull request #123 cannot be merged due to conflicts",
        command="gh pr merge 123 --merge --repo testorg/testrepo",
    )


@pytest.fixture
def recoverable_error_result():
    """Shell result for recoverable error."""
    return ShellResult(
        returncode=1,
        stdout="",
        stderr="Error: API rate limit exceeded. Try again later.",
        command="gh pr merge 123 --merge --repo testorg/testrepo",
    )


class TestExecuteMergeOperation:
    """Test the main _execute_merge_operation function."""

    @pytest.mark.asyncio
    async def test_successful_merge(
        self, sample_repository, sample_config, successful_shell_result
    ):
        """Test successful merge operation."""
        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run,
            patch("auto.workflows.merge._extract_merge_commit_sha") as mock_extract,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_run.return_value = successful_shell_result
            mock_extract.return_value = "abc123def456789"

            # Execute merge
            result = await _execute_merge_operation(123, sample_repository, "merge", sample_config)

            # Verify result
            assert result.success is True
            assert result.method_used == "merge"
            assert result.merge_commit_sha == "abc123def456789"
            assert result.retry_count == 0
            assert result.error_message is None

            # Verify command was called correctly
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == [
                "gh",
                "pr",
                "merge",
                "123",
                "--merge",
                "--repo",
                "testorg/testrepo",
                "--delete-branch",
            ]

    @pytest.mark.asyncio
    async def test_validation_failure(self, sample_repository, sample_config):
        """Test merge with validation failures."""
        with patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate:
            # Setup validation failure
            validation_errors = [
                "PR is not approved",
                "Required status checks failed",
            ]
            mock_validate.return_value = (False, validation_errors)

            # Execute merge
            result = await _execute_merge_operation(123, sample_repository, "squash", sample_config)

            # Verify result
            assert result.success is False
            assert result.validation_errors == validation_errors
            assert "Pre-merge validation failed" in result.error_message
            assert result.merge_commit_sha is None

    @pytest.mark.asyncio
    async def test_merge_conflicts(self, sample_repository, sample_config):
        """Test merge with conflicts."""
        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])
            conflicted_files = ["src/main.py", "README.md"]
            mock_conflicts.return_value = conflicted_files

            # Execute merge
            result = await _execute_merge_operation(123, sample_repository, "rebase", sample_config)

            # Verify result
            assert result.success is False
            assert result.conflict_details is not None
            assert result.conflict_details.conflicted_files == conflicted_files
            assert "Merge conflicts detected" in result.error_message
            assert len(result.conflict_details.resolution_suggestions) > 0

    @pytest.mark.asyncio
    async def test_merge_command_failure(
        self, sample_repository, sample_config, failed_shell_result
    ):
        """Test merge command failure."""
        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_run.return_value = failed_shell_result

            # Execute merge
            result = await _execute_merge_operation(123, sample_repository, "merge", sample_config)

            # Verify result
            assert result.success is False
            assert "Merge failed" in result.error_message
            assert result.merge_commit_sha is None
            assert result.retry_count == 0  # No retries for non-recoverable errors

    @pytest.mark.asyncio
    async def test_retry_logic_recoverable_error(
        self, sample_repository, sample_config, recoverable_error_result, successful_shell_result
    ):
        """Test retry logic with recoverable errors."""
        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run,
            patch("auto.workflows.merge._extract_merge_commit_sha") as mock_extract,
            patch("asyncio.sleep") as mock_sleep,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_extract.return_value = "success_sha"
            mock_sleep.return_value = None

            # First call fails with recoverable error, second succeeds
            mock_run.side_effect = [recoverable_error_result, successful_shell_result]

            # Execute merge
            result = await _execute_merge_operation(123, sample_repository, "merge", sample_config)

            # Verify result
            assert result.success is True
            assert result.retry_count == 1  # One retry was performed
            assert result.merge_commit_sha == "success_sha"

            # Verify retry delay was called
            mock_sleep.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_timeout_handling(self, sample_repository, sample_config):
        """Test timeout handling."""
        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_run.side_effect = TimeoutError()

            # Execute merge
            result = await _execute_merge_operation(123, sample_repository, "merge", sample_config)

            # Verify result
            assert result.success is False
            assert "timed out" in result.error_message
            assert result.retry_count == 2  # All retries exhausted

    @pytest.mark.asyncio
    async def test_max_retries_reached(
        self, sample_repository, sample_config, recoverable_error_result
    ):
        """Test behavior when max retries are reached."""
        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run,
            patch("asyncio.sleep") as mock_sleep,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_sleep.return_value = None

            # All attempts fail with recoverable errors
            mock_run.return_value = recoverable_error_result

            # Execute merge
            result = await _execute_merge_operation(123, sample_repository, "merge", sample_config)

            # Verify result
            assert result.success is False
            assert "failed after 3 attempts" in result.error_message
            assert result.retry_count == 2  # Final attempt number

    @pytest.mark.asyncio
    async def test_different_merge_methods(self, sample_repository, sample_config):
        """Test different merge methods are handled correctly."""
        with (
            patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
            patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
            patch("auto.workflows.merge.run_command_async") as mock_run,
            patch("auto.workflows.merge._extract_merge_commit_sha") as mock_extract,
        ):
            # Setup mocks
            mock_validate.return_value = (True, [])
            mock_conflicts.return_value = None
            mock_extract.return_value = "test_sha"

            success_result = ShellResult(0, "Success", "", "test")
            mock_run.return_value = success_result

            # Test different merge methods
            for method in ["merge", "squash", "rebase"]:
                result = await _execute_merge_operation(
                    123, sample_repository, method, sample_config
                )

                assert result.success is True
                assert result.method_used == method

                # Check the command called
                call_args = mock_run.call_args[0][0]
                assert f"--{method}" in call_args


class TestExtractMergeCommitSha:
    """Test merge commit SHA extraction."""

    @pytest.mark.asyncio
    async def test_extract_from_gh_output(self):
        """Test extracting SHA from gh CLI output."""
        repository = GitHubRepository(owner="test", name="repo")

        # Test with full SHA
        output_with_full_sha = (
            "✓ Pull request #123 merged (commit abc123def456789012345678901234567890abcd)"
        )
        sha = await _extract_merge_commit_sha(output_with_full_sha, repository, 123)
        assert sha == "abc123def456789012345678901234567890abcd"

        # Test with short SHA
        output_with_short_sha = "✓ Pull request #123 merged (commit abc1234)"
        sha = await _extract_merge_commit_sha(output_with_short_sha, repository, 123)
        assert sha == "abc1234"

        # Test with multiple SHAs (should return longest)
        output_with_multiple = "Previous: abc123 New: def456789012345678901234567890abcdef"
        sha = await _extract_merge_commit_sha(output_with_multiple, repository, 123)
        assert sha == "def456789012345678901234567890abcdef"

    @pytest.mark.asyncio
    async def test_extract_from_api_fallback(self):
        """Test fallback to API when no SHA in output."""
        repository = GitHubRepository(owner="test", name="repo")

        api_response = {"mergeCommit": {"oid": "api123def456789012345678901234567890abcd"}}

        with patch("auto.workflows.merge.run_command_async") as mock_run:
            mock_result = ShellResult(0, json.dumps(api_response), "", "gh pr view")
            mock_run.return_value = mock_result

            sha = await _extract_merge_commit_sha("No SHA here", repository, 123)
            assert sha == "api123def456789012345678901234567890abcd"

            # Verify API was called correctly
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == [
                "gh",
                "pr",
                "view",
                "123",
                "--repo",
                "test/repo",
                "--json",
                "mergeCommit",
            ]

    @pytest.mark.asyncio
    async def test_extract_api_failure(self):
        """Test API fallback failure handling."""
        repository = GitHubRepository(owner="test", name="repo")

        with patch("auto.workflows.merge.run_command_async") as mock_run:
            mock_run.side_effect = Exception("API error")

            sha = await _extract_merge_commit_sha("No SHA", repository, 123)
            assert sha is None


class TestIsRecoverableError:
    """Test recoverable error detection."""

    def test_recoverable_error_patterns(self):
        """Test various recoverable error patterns."""
        recoverable_errors = [
            "API rate limit exceeded",
            "Service temporarily unavailable",
            "502 Bad Gateway",
            "503 Service Unavailable",
            "504 Gateway Timeout",
            "Connection reset by peer",
            "Network error occurred",
            "Temporary failure in name resolution",
        ]

        for error in recoverable_errors:
            assert _is_recoverable_error(error) is True, f"Should be recoverable: {error}"

    def test_non_recoverable_errors(self):
        """Test non-recoverable error patterns."""
        non_recoverable_errors = [
            "Pull request not found",
            "Insufficient permissions",
            "Merge conflicts detected",
            "Branch protection rules prevent merge",
            "Invalid merge method",
            "",  # Empty string
        ]

        for error in non_recoverable_errors:
            assert _is_recoverable_error(error) is False, f"Should not be recoverable: {error}"

    def test_case_insensitive_matching(self):
        """Test that error matching is case insensitive."""
        assert _is_recoverable_error("API RATE LIMIT") is True
        assert _is_recoverable_error("Service Temporarily Unavailable") is True
        assert _is_recoverable_error("502 bad gateway") is True

    def test_empty_and_none_errors(self):
        """Test handling of empty and None error messages."""
        assert _is_recoverable_error("") is False
        assert _is_recoverable_error(None) is False


@pytest.mark.asyncio
async def test_github_api_response_storage():
    """Test that GitHub API responses are properly stored."""
    repository = GitHubRepository(owner="test", name="repo")
    config = Config(defaults=DefaultsConfig())

    shell_result = ShellResult(
        returncode=1, stdout="some output", stderr="some error", command="gh pr merge 123"
    )

    with (
        patch("auto.workflows.merge.validate_merge_eligibility") as mock_validate,
        patch("auto.workflows.merge.handle_merge_conflicts") as mock_conflicts,
        patch("auto.workflows.merge.run_command_async") as mock_run,
    ):
        mock_validate.return_value = (True, [])
        mock_conflicts.return_value = None
        mock_run.return_value = shell_result

        result = await _execute_merge_operation(123, repository, "merge", config)

        # Verify API response is stored
        assert result.github_api_response["returncode"] == 1
        assert result.github_api_response["stdout"] == "some output"
        assert result.github_api_response["stderr"] == "some error"
        assert "gh pr merge 123" in result.github_api_response["command"]
