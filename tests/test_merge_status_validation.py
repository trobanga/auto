"""Tests for merge status validation functionality."""

import json
from unittest.mock import patch

import pytest

from auto.models import Config, GitHubConfig, GitHubRepository, WorkflowsConfig
from auto.utils.shell import ShellError, ShellResult
from auto.workflows.merge_validation import (
    _fetch_status_checks,
    _get_required_status_checks_from_protection,
    _validate_status_checks,
)


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    return Config(
        workflows=WorkflowsConfig(
            wait_for_checks=True,
            check_timeout=600,
            required_status_checks=["ci/test", "security/scan"],
        ),
        github=GitHubConfig(status_check_retries=3, status_check_interval=30),
    )


@pytest.fixture
def mock_repository():
    """Create a mock repository for testing."""
    return GitHubRepository(owner="test-owner", name="test-repo", default_branch="main")


class TestValidateStatusChecks:
    """Test the _validate_status_checks function."""

    @pytest.mark.asyncio
    async def test_all_checks_passing(self, mock_config, mock_repository):
        """Test when all required status checks are passing."""
        with (
            patch("auto.workflows.merge_validation._get_pr_info") as mock_get_pr_info,
            patch("auto.workflows.merge_validation._fetch_status_checks") as mock_fetch_status,
            patch(
                "auto.workflows.merge_validation._get_required_status_checks_from_protection"
            ) as mock_get_required,
        ):
            # Mock PR info
            mock_get_pr_info.return_value = {"headRefOid": "abc123", "baseRefName": "main"}

            # Mock required checks from branch protection
            mock_get_required.return_value = ["ci/build"]

            # Mock status checks - all passing
            mock_fetch_status.return_value = {
                "statuses": [
                    {
                        "context": "ci/test",
                        "state": "success",
                        "description": "All tests passed",
                        "target_url": "https://example.com/test",
                    },
                    {
                        "context": "security/scan",
                        "state": "success",
                        "description": "Security scan passed",
                        "target_url": "https://example.com/security",
                    },
                    {
                        "context": "ci/build",
                        "state": "success",
                        "description": "Build successful",
                        "target_url": "https://example.com/build",
                    },
                ]
            }

            result = await _validate_status_checks(123, mock_repository, mock_config)

            assert result.success is True
            assert "All status checks passing" in result.message
            assert len(result.actionable_items) == 0
            assert result.details["head_sha"] == "abc123"

    @pytest.mark.asyncio
    async def test_failing_required_checks(self, mock_config, mock_repository):
        """Test when required status checks are failing."""
        with (
            patch("auto.workflows.merge_validation._get_pr_info") as mock_get_pr_info,
            patch("auto.workflows.merge_validation._fetch_status_checks") as mock_fetch_status,
            patch(
                "auto.workflows.merge_validation._get_required_status_checks_from_protection"
            ) as mock_get_required,
        ):
            mock_get_pr_info.return_value = {"headRefOid": "abc123", "baseRefName": "main"}

            mock_get_required.return_value = []

            # Mock failing status checks
            mock_fetch_status.return_value = {
                "statuses": [
                    {
                        "context": "ci/test",
                        "state": "failure",
                        "description": "Tests failed",
                        "target_url": "https://example.com/test",
                    },
                    {
                        "context": "security/scan",
                        "state": "success",
                        "description": "Security scan passed",
                        "target_url": "https://example.com/security",
                    },
                ]
            }

            result = await _validate_status_checks(123, mock_repository, mock_config)

            assert result.success is False
            assert "failing" in result.message.lower()
            assert "ci/test" in result.message
            assert len(result.actionable_items) > 0
            assert any("Fix failing status checks" in item for item in result.actionable_items)

    @pytest.mark.asyncio
    async def test_pending_checks_within_timeout(self, mock_config, mock_repository):
        """Test pending checks that resolve within timeout."""
        with (
            patch("auto.workflows.merge_validation._get_pr_info") as mock_get_pr_info,
            patch("auto.workflows.merge_validation._fetch_status_checks") as mock_fetch_status,
            patch(
                "auto.workflows.merge_validation._get_required_status_checks_from_protection"
            ) as mock_get_required,
            patch("time.time") as mock_time,
            patch("asyncio.sleep") as mock_sleep,
        ):
            mock_get_pr_info.return_value = {"headRefOid": "abc123", "baseRefName": "main"}

            mock_get_required.return_value = []

            # Mock time progression - start time, then 60s later
            mock_time.side_effect = [0, 60, 120]  # Start, first check, second check

            # First call returns pending, second call returns success
            mock_fetch_status.side_effect = [
                {
                    "statuses": [
                        {
                            "context": "ci/test",
                            "state": "pending",
                            "description": "Tests running",
                            "target_url": "https://example.com/test",
                        },
                        {
                            "context": "security/scan",
                            "state": "success",
                            "description": "Security scan passed",
                            "target_url": "https://example.com/security",
                        },
                    ]
                },
                {
                    "statuses": [
                        {
                            "context": "ci/test",
                            "state": "success",
                            "description": "Tests passed",
                            "target_url": "https://example.com/test",
                        },
                        {
                            "context": "security/scan",
                            "state": "success",
                            "description": "Security scan passed",
                            "target_url": "https://example.com/security",
                        },
                    ]
                },
            ]

            result = await _validate_status_checks(123, mock_repository, mock_config)

            assert result.success is True
            mock_sleep.assert_called_with(30)  # Should wait the configured interval

    @pytest.mark.asyncio
    async def test_pending_checks_timeout(self, mock_config, mock_repository):
        """Test pending checks that exceed timeout."""
        with (
            patch("auto.workflows.merge_validation._get_pr_info") as mock_get_pr_info,
            patch("auto.workflows.merge_validation._fetch_status_checks") as mock_fetch_status,
            patch(
                "auto.workflows.merge_validation._get_required_status_checks_from_protection"
            ) as mock_get_required,
            patch("time.time") as mock_time,
        ):
            mock_get_pr_info.return_value = {"headRefOid": "abc123", "baseRefName": "main"}

            mock_get_required.return_value = []

            # Mock time exceeding timeout
            mock_time.side_effect = [0, 700]  # Start time, then past timeout

            mock_fetch_status.return_value = {
                "statuses": [
                    {
                        "context": "ci/test",
                        "state": "pending",
                        "description": "Tests running",
                        "target_url": "https://example.com/test",
                    }
                ]
            }

            result = await _validate_status_checks(123, mock_repository, mock_config)

            assert result.success is False
            assert "timed out" in result.message.lower()
            assert "ci/test" in result.message
            assert len(result.actionable_items) > 0

    @pytest.mark.asyncio
    async def test_missing_required_checks(self, mock_config, mock_repository):
        """Test when required checks are missing entirely."""
        with (
            patch("auto.workflows.merge_validation._get_pr_info") as mock_get_pr_info,
            patch("auto.workflows.merge_validation._fetch_status_checks") as mock_fetch_status,
            patch(
                "auto.workflows.merge_validation._get_required_status_checks_from_protection"
            ) as mock_get_required,
        ):
            mock_get_pr_info.return_value = {"headRefOid": "abc123", "baseRefName": "main"}

            mock_get_required.return_value = []

            # Only one check present, but config requires two
            mock_fetch_status.return_value = {
                "statuses": [
                    {
                        "context": "ci/test",
                        "state": "success",
                        "description": "Tests passed",
                        "target_url": "https://example.com/test",
                    }
                ]
            }

            result = await _validate_status_checks(123, mock_repository, mock_config)

            assert result.success is False
            assert "not found" in result.message.lower()
            assert "security/scan" in result.message  # Missing required check

    @pytest.mark.asyncio
    async def test_check_runs_support(self, mock_config, mock_repository):
        """Test support for GitHub Check Runs API."""
        with (
            patch("auto.workflows.merge_validation._get_pr_info") as mock_get_pr_info,
            patch("auto.workflows.merge_validation._fetch_status_checks") as mock_fetch_status,
            patch(
                "auto.workflows.merge_validation._get_required_status_checks_from_protection"
            ) as mock_get_required,
        ):
            mock_get_pr_info.return_value = {"headRefOid": "abc123", "baseRefName": "main"}

            mock_get_required.return_value = []

            # Mock check runs instead of statuses
            mock_fetch_status.return_value = {
                "check_runs": [
                    {
                        "name": "ci/test",
                        "conclusion": "success",
                        "output": {"summary": "All tests passed"},
                        "html_url": "https://example.com/test",
                    },
                    {
                        "name": "security/scan",
                        "conclusion": "failure",
                        "output": {"summary": "Security issues found"},
                        "html_url": "https://example.com/security",
                    },
                ]
            }

            result = await _validate_status_checks(123, mock_repository, mock_config)

            assert result.success is False  # Should fail due to security/scan failure
            assert "security/scan" in result.message

    @pytest.mark.asyncio
    async def test_network_error_retry(self, mock_config, mock_repository):
        """Test retry logic on network errors."""
        with (
            patch("auto.workflows.merge_validation._get_pr_info") as mock_get_pr_info,
            patch("auto.workflows.merge_validation._fetch_status_checks") as mock_fetch_status,
            patch(
                "auto.workflows.merge_validation._get_required_status_checks_from_protection"
            ) as mock_get_required,
            patch("asyncio.sleep") as mock_sleep,
        ):
            mock_get_pr_info.return_value = {"headRefOid": "abc123", "baseRefName": "main"}

            mock_get_required.return_value = []

            # First two calls fail, third succeeds
            mock_fetch_status.side_effect = [
                None,  # Network error
                None,  # Network error
                {
                    "statuses": [
                        {
                            "context": "ci/test",
                            "state": "success",
                            "description": "Tests passed",
                            "target_url": "https://example.com/test",
                        },
                        {
                            "context": "security/scan",
                            "state": "success",
                            "description": "Security scan passed",
                            "target_url": "https://example.com/security",
                        },
                    ]
                },
            ]

            result = await _validate_status_checks(123, mock_repository, mock_config)

            assert result.success is True
            assert mock_sleep.call_count == 2  # Should have retried twice

    @pytest.mark.asyncio
    async def test_no_wait_for_pending_checks(self, mock_repository):
        """Test when wait_for_checks is disabled."""
        config = Config(
            workflows=WorkflowsConfig(
                wait_for_checks=False,  # Disabled
                required_status_checks=["ci/test"],
            ),
            github=GitHubConfig(),
        )

        with (
            patch("auto.workflows.merge_validation._get_pr_info") as mock_get_pr_info,
            patch("auto.workflows.merge_validation._fetch_status_checks") as mock_fetch_status,
            patch(
                "auto.workflows.merge_validation._get_required_status_checks_from_protection"
            ) as mock_get_required,
        ):
            mock_get_pr_info.return_value = {"headRefOid": "abc123", "baseRefName": "main"}

            mock_get_required.return_value = []

            mock_fetch_status.return_value = {
                "statuses": [
                    {
                        "context": "ci/test",
                        "state": "pending",
                        "description": "Tests running",
                        "target_url": "https://example.com/test",
                    }
                ]
            }

            result = await _validate_status_checks(123, mock_repository, config)

            assert result.success is False
            assert "pending" in result.message.lower()

    @pytest.mark.asyncio
    async def test_pr_info_fetch_failure(self, mock_config, mock_repository):
        """Test when PR info cannot be fetched."""
        with patch("auto.workflows.merge_validation._get_pr_info") as mock_get_pr_info:
            mock_get_pr_info.return_value = None  # Fetch failed

            result = await _validate_status_checks(123, mock_repository, mock_config)

            assert result.success is False
            assert "Failed to retrieve PR information" in result.message
            assert "Check if the PR exists" in result.actionable_items[0]


class TestFetchStatusChecks:
    """Test the _fetch_status_checks helper function."""

    @pytest.mark.asyncio
    async def test_successful_status_fetch(self):
        """Test successful status check fetching."""
        mock_status_result = ShellResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "state": "success",
                    "statuses": [
                        {"context": "ci/test", "state": "success", "description": "Tests passed"}
                    ],
                }
            ),
            stderr="",
            command="gh api ...",
            cwd=None,
        )

        mock_check_result = ShellResult(
            returncode=0,
            stdout=json.dumps({"check_runs": [{"name": "security/scan", "conclusion": "success"}]}),
            stderr="",
            command="gh api ...",
            cwd=None,
        )

        with patch("auto.workflows.merge_validation.run_command_async") as mock_run_command:
            mock_run_command.side_effect = [mock_status_result, mock_check_result]

            result = await _fetch_status_checks("owner", "repo", "abc123")

            assert result is not None
            assert "statuses" in result
            assert "check_runs" in result
            assert len(result["statuses"]) == 1
            assert len(result["check_runs"]) == 1

    @pytest.mark.asyncio
    async def test_status_fetch_failure(self):
        """Test status check fetch failure."""
        with patch("auto.workflows.merge_validation.run_command_async") as mock_run_command:
            mock_run_command.side_effect = ShellError("API error", 1, "", "Rate limited")

            result = await _fetch_status_checks("owner", "repo", "abc123")

            assert result is None


class TestGetRequiredStatusChecks:
    """Test the _get_required_status_checks_from_protection helper function."""

    @pytest.mark.asyncio
    async def test_branch_protection_with_required_checks(self):
        """Test getting required checks from branch protection."""
        mock_result = ShellResult(
            returncode=0,
            stdout=json.dumps(["ci/build", "security/scan"]),
            stderr="",
            command="gh api ...",
            cwd=None,
        )

        with patch("auto.workflows.merge_validation.run_command_async") as mock_run_command:
            mock_run_command.return_value = mock_result

            result = await _get_required_status_checks_from_protection("owner", "repo", "main")

            assert result == ["ci/build", "security/scan"]

    @pytest.mark.asyncio
    async def test_no_branch_protection(self):
        """Test when branch has no protection rules."""
        mock_result = ShellResult(
            returncode=1,  # Not found
            stdout="",
            stderr="Not Found",
            command="gh api ...",
            cwd=None,
        )

        with patch("auto.workflows.merge_validation.run_command_async") as mock_run_command:
            mock_run_command.return_value = mock_result

            result = await _get_required_status_checks_from_protection("owner", "repo", "main")

            assert result == []

    @pytest.mark.asyncio
    async def test_api_error(self):
        """Test API error handling."""
        with patch("auto.workflows.merge_validation.run_command_async") as mock_run_command:
            mock_run_command.side_effect = Exception("Network error")

            result = await _get_required_status_checks_from_protection("owner", "repo", "main")

            assert result == []


class TestConfigValidation:
    """Test configuration validation for status check settings."""

    def test_workflows_config_validation(self):
        """Test WorkflowsConfig validation for status check settings."""
        # Valid config
        config = WorkflowsConfig(
            wait_for_checks=True,
            check_timeout=300,
            required_status_checks=["ci/test", "security/scan"],
        )
        assert config.wait_for_checks is True
        assert config.check_timeout == 300
        assert config.required_status_checks == ["ci/test", "security/scan"]

        # Test timeout validation
        with pytest.raises(ValueError, match="Check timeout cannot be negative"):
            WorkflowsConfig(check_timeout=-1)

        with pytest.raises(ValueError, match="Check timeout cannot exceed 2 hours"):
            WorkflowsConfig(check_timeout=8000)

    def test_github_config_validation(self):
        """Test GitHubConfig validation for status check settings."""
        # Valid config
        config = GitHubConfig(status_check_retries=3, status_check_interval=30)
        assert config.status_check_retries == 3
        assert config.status_check_interval == 30

        # Test retries validation
        with pytest.raises(ValueError, match="Status check retries cannot be negative"):
            GitHubConfig(status_check_retries=-1)

        with pytest.raises(ValueError, match="Status check retries cannot exceed 10"):
            GitHubConfig(status_check_retries=15)

        # Test interval validation
        with pytest.raises(ValueError, match="Status check interval must be at least 5 seconds"):
            GitHubConfig(status_check_interval=2)

        with pytest.raises(ValueError, match="Status check interval cannot exceed 5 minutes"):
            GitHubConfig(status_check_interval=400)
