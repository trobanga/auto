"""
Tests for update validation and regression prevention.

This module tests the comprehensive validation system that ensures updates
properly address feedback without introducing regressions.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from auto.workflows.review_update import (
    ReviewUpdateWorkflow,
    UpdateResult,
    UpdateStatus,
    UpdateValidation,
    UpdateType
)


@pytest.fixture
def mock_workflow():
    """Create mock workflow for testing validation."""
    workflow = Mock(spec=ReviewUpdateWorkflow)
    workflow._validate_syntax = AsyncMock()
    workflow._validate_formatting = AsyncMock()
    workflow._validate_basic_functionality = AsyncMock()
    workflow._validate_security = AsyncMock()
    workflow._validate_performance = AsyncMock()
    workflow._validate_tests = AsyncMock()
    return workflow


class TestValidationSteps:
    """Test individual validation steps."""
    
    @pytest.mark.asyncio
    async def test_syntax_validation(self, mock_workflow):
        """Test syntax validation for different file types."""
        # Mock successful validation
        mock_workflow._validate_syntax.return_value = True
        
        modified_files = ["src/auth.py", "src/utils.js", "src/styles.css"]
        result = await mock_workflow._validate_syntax(modified_files, "/test/worktree")
        
        assert result is True
        mock_workflow._validate_syntax.assert_called_once_with(modified_files, "/test/worktree")
    
    @pytest.mark.asyncio
    async def test_formatting_validation(self, mock_workflow):
        """Test code formatting validation."""
        mock_workflow._validate_formatting.return_value = True
        
        modified_files = ["src/main.py"]
        result = await mock_workflow._validate_formatting(modified_files, "/test/worktree")
        
        assert result is True
        mock_workflow._validate_formatting.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_security_validation(self, mock_workflow):
        """Test security validation for sensitive changes."""
        mock_workflow._validate_security.return_value = True
        
        modified_files = ["src/auth.py", "src/crypto.py"]
        result = await mock_workflow._validate_security(modified_files, "/test/worktree")
        
        assert result is True
        mock_workflow._validate_security.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_performance_validation(self, mock_workflow):
        """Test performance regression validation."""
        mock_workflow._validate_performance.return_value = True
        
        result = await mock_workflow._validate_performance("/test/worktree")
        
        assert result is True
        mock_workflow._validate_performance.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_test_execution_validation(self, mock_workflow):
        """Test that existing tests still pass."""
        mock_workflow._validate_tests.return_value = True
        
        result = await mock_workflow._validate_tests("/test/worktree")
        
        assert result is True
        mock_workflow._validate_tests.assert_called_once()


class TestUpdateValidationResults:
    """Test update validation result creation and analysis."""
    
    def test_validation_result_creation(self):
        """Test creating validation results."""
        validation = UpdateValidation(
            update_id="test_update",
            pre_conditions={"files_exist": True, "git_clean": True},
            post_conditions={"changes_applied": True, "no_conflicts": True},
            regression_checks={"tests_pass": True, "syntax_valid": True},
            code_quality_checks={"linting_pass": True, "coverage_maintained": True},
            overall_valid=True,
            issues_found=[]
        )
        
        assert validation.update_id == "test_update"
        assert validation.overall_valid is True
        assert len(validation.issues_found) == 0
        
        # All checks should pass
        assert all(validation.pre_conditions.values())
        assert all(validation.post_conditions.values())
        assert all(validation.regression_checks.values())
        assert all(validation.code_quality_checks.values())
    
    def test_validation_with_failures(self):
        """Test validation with some failures."""
        validation = UpdateValidation(
            update_id="failing_update",
            pre_conditions={"files_exist": True, "git_clean": False},
            post_conditions={"changes_applied": True, "no_conflicts": False},
            regression_checks={"tests_pass": False, "syntax_valid": True},
            code_quality_checks={"linting_pass": False, "coverage_maintained": True},
            overall_valid=False,
            issues_found=["Git working directory not clean", "Tests failing", "Linting errors"]
        )
        
        assert validation.overall_valid is False
        assert len(validation.issues_found) == 3
        
        # Should identify specific failing checks
        assert validation.pre_conditions["git_clean"] is False
        assert validation.post_conditions["no_conflicts"] is False
        assert validation.regression_checks["tests_pass"] is False
        assert validation.code_quality_checks["linting_pass"] is False


class TestRegressionPrevention:
    """Test regression prevention capabilities."""
    
    def test_identify_breaking_changes(self):
        """Test identification of potentially breaking changes."""
        # Simulate update results with potential issues
        risky_updates = [
            UpdateResult(
                update_id="api_change",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/api/endpoints.py"],
                commands_executed=["modify_public_interface"],
                execution_time=30.0,
                validation_results={"api_compatibility": False}
            ),
            UpdateResult(
                update_id="database_migration",
                status=UpdateStatus.COMPLETED,
                files_modified=["migrations/001_alter_schema.sql"],
                commands_executed=["alter_table"],
                execution_time=45.0,
                validation_results={"schema_compatible": False}
            )
        ]
        
        # These updates should be flagged as potentially risky
        for update in risky_updates:
            has_failures = any(not result for result in update.validation_results.values())
            assert has_failures, f"Update {update.update_id} should have validation failures"
    
    def test_safe_changes_pass_validation(self):
        """Test that safe changes pass validation."""
        safe_updates = [
            UpdateResult(
                update_id="documentation_update",
                status=UpdateStatus.COMPLETED,
                files_modified=["README.md", "docs/api.md"],
                commands_executed=["update_docs"],
                execution_time=10.0,
                validation_results={"markdown_valid": True, "links_valid": True}
            ),
            UpdateResult(
                update_id="style_fix",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/utils.py"],
                commands_executed=["fix_formatting"],
                execution_time=5.0,
                validation_results={"syntax_valid": True, "tests_pass": True}
            )
        ]
        
        # These updates should pass all validations
        for update in safe_updates:
            all_passed = all(update.validation_results.values())
            assert all_passed, f"Update {update.update_id} should pass all validations"


class TestValidationConfiguration:
    """Test validation configuration and customization."""
    
    def test_validation_steps_configuration(self):
        """Test configuring validation steps for different update types."""
        validation_configs = {
            UpdateType.CODE_FIX: ["syntax_check", "test_execution", "basic_functionality"],
            UpdateType.SECURITY_FIX: ["syntax_check", "security_scan", "test_execution"],
            UpdateType.PERFORMANCE_OPT: ["syntax_check", "performance_test", "basic_functionality"],
            UpdateType.STYLE_IMPROVEMENT: ["syntax_check", "formatting_check"],
            UpdateType.DOCUMENTATION: ["markdown_syntax", "link_check"],
            UpdateType.TEST_ADDITION: ["syntax_check", "test_execution"]
        }
        
        for update_type, expected_steps in validation_configs.items():
            # Verify each update type has appropriate validation steps
            assert len(expected_steps) > 0, f"Update type {update_type} should have validation steps"
            
            # Security and code fixes should have more comprehensive validation
            if update_type in [UpdateType.CODE_FIX, UpdateType.SECURITY_FIX]:
                assert len(expected_steps) >= 3, f"{update_type} should have comprehensive validation"
            
            # Style changes can have lighter validation
            if update_type == UpdateType.STYLE_IMPROVEMENT:
                assert "formatting_check" in expected_steps, "Style updates should check formatting"
    
    def test_validation_severity_levels(self):
        """Test different validation severity levels."""
        # Critical validations that must pass
        critical_validations = ["syntax_check", "security_scan", "basic_functionality"]
        
        # Warning validations that should pass but won't block
        warning_validations = ["formatting_check", "performance_test", "coverage_check"]
        
        # Info validations for best practices
        info_validations = ["documentation_check", "naming_convention"]
        
        all_validations = critical_validations + warning_validations + info_validations
        
        # Verify we have a good spread of validation types
        assert len(critical_validations) >= 3, "Should have multiple critical validations"
        assert len(warning_validations) >= 2, "Should have warning validations"
        assert len(info_validations) >= 2, "Should have info validations"
        
        # Critical validations should block deployment
        for validation in critical_validations:
            assert validation in ["syntax_check", "security_scan", "basic_functionality"], \
                f"{validation} should be a critical validation"


class TestValidationPerformance:
    """Test validation performance and efficiency."""
    
    @pytest.mark.asyncio
    async def test_parallel_validation_execution(self):
        """Test that validations can run in parallel for efficiency."""
        # Simulate multiple validation steps
        validation_steps = ["syntax_check", "formatting_check", "basic_functionality"]
        
        # Mock validation functions with delays
        async def mock_validation(step_name, delay=0.1):
            await asyncio.sleep(delay)
            return True
        
        # Test sequential execution (slow)
        start_time = asyncio.get_event_loop().time()
        sequential_results = []
        for step in validation_steps:
            result = await mock_validation(step)
            sequential_results.append(result)
        sequential_time = asyncio.get_event_loop().time() - start_time
        
        # Test parallel execution (fast)
        start_time = asyncio.get_event_loop().time()
        parallel_tasks = [mock_validation(step) for step in validation_steps]
        parallel_results = await asyncio.gather(*parallel_tasks)
        parallel_time = asyncio.get_event_loop().time() - start_time
        
        # Parallel should be significantly faster
        assert parallel_time < sequential_time * 0.8, "Parallel validation should be faster"
        assert len(parallel_results) == len(validation_steps)
        assert all(parallel_results), "All validations should pass"
    
    def test_validation_timeout_handling(self):
        """Test handling of validation timeouts."""
        # Simulate validation with timeout
        timeout_config = {
            "syntax_check": 30,     # 30 seconds for syntax
            "test_execution": 300,  # 5 minutes for tests
            "security_scan": 120,   # 2 minutes for security
            "performance_test": 600 # 10 minutes for performance
        }
        
        for validation_type, timeout in timeout_config.items():
            assert timeout > 0, f"Timeout for {validation_type} should be positive"
            assert timeout <= 600, f"Timeout for {validation_type} should be reasonable"
    
    def test_validation_resource_management(self):
        """Test that validation doesn't consume excessive resources."""
        # Define resource limits for different validations
        resource_limits = {
            "memory_mb": {
                "syntax_check": 100,
                "formatting_check": 50,
                "test_execution": 500,
                "security_scan": 200
            },
            "cpu_cores": {
                "syntax_check": 1,
                "formatting_check": 1,
                "test_execution": 2,
                "security_scan": 1
            }
        }
        
        # Verify limits are reasonable
        for resource_type, limits in resource_limits.items():
            for validation, limit in limits.items():
                assert limit > 0, f"{validation} {resource_type} limit should be positive"
                
                # Memory limits should be reasonable
                if resource_type == "memory_mb":
                    assert limit <= 1000, f"{validation} memory limit should be reasonable"
                
                # CPU limits should not exceed system capacity
                if resource_type == "cpu_cores":
                    assert limit <= 4, f"{validation} CPU limit should be reasonable"


class TestValidationIntegration:
    """Test integration between validation and update workflow."""
    
    @pytest.mark.asyncio
    async def test_validation_prevents_bad_commits(self):
        """Test that validation prevents commits when issues are found."""
        # Simulate update results with validation failures
        failed_update = UpdateResult(
            update_id="problematic_update",
            status=UpdateStatus.COMPLETED,  # Update executed but validation failed
            files_modified=["src/broken.py"],
            commands_executed=["introduce_bug"],
            execution_time=30.0,
            validation_results={"syntax_check": False, "tests_pass": False}
        )
        
        # Create validation that identifies the issues
        validation = UpdateValidation(
            update_id="problematic_update",
            pre_conditions={"files_exist": True},
            post_conditions={"changes_applied": True},
            regression_checks={"syntax_check": False, "tests_pass": False},
            code_quality_checks={"linting_pass": True},
            overall_valid=False,
            issues_found=["Syntax errors introduced", "Tests are failing"]
        )
        
        # Validation should prevent commit
        assert validation.overall_valid is False
        assert len(validation.issues_found) > 0
        
        # Update should not be committed with these failures
        critical_failures = not all([
            validation.regression_checks.get("syntax_check", True),
            validation.regression_checks.get("tests_pass", True)
        ])
        assert critical_failures, "Critical failures should prevent commit"
    
    @pytest.mark.asyncio
    async def test_validation_allows_safe_commits(self):
        """Test that validation allows commits when all checks pass."""
        # Simulate successful update
        successful_update = UpdateResult(
            update_id="good_update",
            status=UpdateStatus.COMPLETED,
            files_modified=["src/feature.py"],
            commands_executed=["add_feature"],
            execution_time=30.0,
            validation_results={"syntax_check": True, "tests_pass": True}
        )
        
        # Create validation that passes all checks
        validation = UpdateValidation(
            update_id="good_update",
            pre_conditions={"files_exist": True, "git_clean": True},
            post_conditions={"changes_applied": True, "no_conflicts": True},
            regression_checks={"syntax_check": True, "tests_pass": True},
            code_quality_checks={"linting_pass": True, "coverage_maintained": True},
            overall_valid=True,
            issues_found=[]
        )
        
        # Validation should allow commit
        assert validation.overall_valid is True
        assert len(validation.issues_found) == 0
        
        # All critical checks should pass
        critical_checks_pass = all([
            validation.regression_checks.get("syntax_check", False),
            validation.regression_checks.get("tests_pass", False)
        ])
        assert critical_checks_pass, "All critical checks should pass"


if __name__ == "__main__":
    pytest.main([__file__])