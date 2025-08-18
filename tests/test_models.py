"""Tests for data models."""

import pytest

from auto.models import (
    Issue,
    IssueIdentifier,
    IssueProvider,
    IssueStatus,
    IssueType,
    Config,
    WorkflowState,
    WorkflowStatus,
)


class TestIssueIdentifier:
    """Test issue identifier parsing."""
    
    def test_github_hash_format(self):
        """Test GitHub #123 format."""
        identifier = IssueIdentifier.parse("#123")
        assert identifier.provider == IssueProvider.GITHUB
        assert identifier.issue_id == "#123"
        assert identifier.raw == "#123"
    
    def test_github_gh_format(self):
        """Test GitHub gh-123 format."""
        identifier = IssueIdentifier.parse("gh-123")
        assert identifier.provider == IssueProvider.GITHUB
        assert identifier.issue_id == "#123"
        assert identifier.raw == "gh-123"
    
    def test_github_numeric(self):
        """Test GitHub numeric format."""
        identifier = IssueIdentifier.parse("123")
        assert identifier.provider == IssueProvider.GITHUB
        assert identifier.issue_id == "#123"
        assert identifier.raw == "123"
    
    def test_github_url(self):
        """Test GitHub URL format."""
        url = "https://github.com/owner/repo/issues/123"
        identifier = IssueIdentifier.parse(url)
        assert identifier.provider == IssueProvider.GITHUB
        assert identifier.issue_id == "#123"
        assert identifier.raw == url
    
    def test_linear_format(self):
        """Test Linear ENG-123 format."""
        identifier = IssueIdentifier.parse("ENG-123")
        assert identifier.provider == IssueProvider.LINEAR
        assert identifier.issue_id == "ENG-123"
        assert identifier.raw == "ENG-123"
    
    def test_linear_url(self):
        """Test Linear URL format."""
        url = "https://linear.app/workspace/issue/ENG-123"
        identifier = IssueIdentifier.parse(url)
        assert identifier.provider == IssueProvider.LINEAR
        assert identifier.issue_id == "ENG-123"
        assert identifier.raw == url
    
    def test_invalid_format(self):
        """Test invalid format raises error."""
        with pytest.raises(ValueError):
            IssueIdentifier.parse("invalid-format")


class TestIssue:
    """Test Issue model."""
    
    def test_issue_type_inference_from_labels(self):
        """Test issue type inference from labels."""
        issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Test Issue",
            description="Test description",
            status=IssueStatus.OPEN,
            labels=["bug", "high-priority"]
        )
        assert issue.issue_type == IssueType.BUG
    
    def test_issue_type_inference_from_title(self):
        """Test issue type inference from title."""
        issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Add new feature for users",
            description="Test description",
            status=IssueStatus.OPEN,
        )
        assert issue.issue_type == IssueType.FEATURE
    
    def test_issue_type_explicit(self):
        """Test explicit issue type is preserved."""
        issue = Issue(
            id="#123",
            provider=IssueProvider.GITHUB,
            title="Add new feature for users",
            description="Test description",
            status=IssueStatus.OPEN,
            issue_type=IssueType.ENHANCEMENT,
            labels=["bug"]  # Should not override explicit type
        )
        assert issue.issue_type == IssueType.ENHANCEMENT


class TestWorkflowState:
    """Test WorkflowState model."""
    
    def test_update_status(self):
        """Test status update functionality."""
        state = WorkflowState(
            issue_id="ENG-123",
            status=WorkflowStatus.INITIALIZED,
        )
        
        original_updated = state.updated_at
        
        # Small delay to ensure timestamp changes
        import time
        time.sleep(0.01)
        
        state.update_status(WorkflowStatus.IN_REVIEW)
        
        assert state.status == WorkflowStatus.IN_REVIEW
        assert state.updated_at > original_updated


class TestConfig:
    """Test Config model."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = Config()
        
        assert config.version == "1.0"
        assert config.defaults.auto_merge is False
        assert config.defaults.max_review_iterations == 10
        assert config.ai.command == "claude"
        assert config.ai.implementation_agent == "coder"
        assert config.workflows.branch_naming == "auto/{type}/{id}"
    
    def test_config_with_overrides(self):
        """Test configuration with overrides."""
        config = Config(
            defaults={"auto_merge": True, "max_review_iterations": 5},
            ai={"command": "custom-ai", "implementation_agent": "custom-coder"}
        )
        
        assert config.defaults.auto_merge is True
        assert config.defaults.max_review_iterations == 5
        assert config.ai.command == "custom-ai"
        assert config.ai.implementation_agent == "custom-coder"
        # Defaults should still be preserved
        assert config.workflows.branch_naming == "auto/{type}/{id}"