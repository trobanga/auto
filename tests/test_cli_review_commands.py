"""Tests for CLI review commands."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from click.testing import CliRunner

from auto.cli import cli


class TestCLIReviewCommands:
    """Test CLI review command implementations."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.mock_repo = MagicMock()
        self.mock_repo.owner = "test-owner"
        self.mock_repo.name = "test-repo"
    
    def test_review_command_success(self):
        """Test successful review command execution."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.trigger_ai_review') as mock_trigger, \
             patch('auto.cli.asyncio.run') as mock_asyncio:
            
            # Setup mock to return success
            mock_asyncio.return_value = True
            
            # Execute command
            result = self.runner.invoke(cli, ['review', '123'])
            
            # Assert
            assert result.exit_code == 0
            assert "Starting AI review for PR #123" in result.output
            assert "AI review completed for PR #123" in result.output
            mock_asyncio.assert_called_once()
    
    def test_review_command_with_options(self):
        """Test review command with force and agent options."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.trigger_ai_review') as mock_trigger, \
             patch('auto.cli.asyncio.run') as mock_asyncio:
            
            mock_asyncio.return_value = True
            
            # Execute command with options
            result = self.runner.invoke(cli, [
                'review', '123', 
                '--force', 
                '--agent', 'custom-reviewer'
            ])
            
            # Assert
            assert result.exit_code == 0
            mock_asyncio.assert_called_once()
            
            # Verify the trigger_ai_review was called with correct parameters
            call_args = mock_asyncio.call_args[0][0]
            # This would be the coroutine that was passed to asyncio.run
            # In a real implementation, we'd verify the parameters
    
    def test_review_command_invalid_pr_id(self):
        """Test review command with invalid PR ID."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo):
            
            # Execute command with invalid PR ID
            result = self.runner.invoke(cli, ['review', 'invalid'])
            
            # Assert
            assert result.exit_code == 1
            assert "Invalid PR ID format" in result.output
    
    def test_review_command_repository_detection_failure(self):
        """Test review command when repository detection fails."""
        with patch('auto.cli.detect_repository', side_effect=Exception("No git repo")):
            
            # Execute command
            result = self.runner.invoke(cli, ['review', '123'])
            
            # Assert
            assert result.exit_code == 1
            assert "Could not detect repository" in result.output
    
    def test_review_command_trigger_failure(self):
        """Test review command when AI review fails."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.asyncio.run', return_value=False):
            
            # Execute command
            result = self.runner.invoke(cli, ['review', '123'])
            
            # Assert
            assert result.exit_code == 1
            assert "AI review failed for PR #123" in result.output
    
    def test_update_command_success(self):
        """Test successful update command execution."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.execute_review_update') as mock_update, \
             patch('auto.cli.asyncio.run') as mock_asyncio:
            
            mock_asyncio.return_value = True
            
            # Execute command
            result = self.runner.invoke(cli, ['update', '123'])
            
            # Assert
            assert result.exit_code == 0
            assert "Updating PR #123 based on review comments" in result.output
            assert "PR #123 updated successfully" in result.output
    
    def test_update_command_with_options(self):
        """Test update command with force and agent options."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.execute_review_update') as mock_update, \
             patch('auto.cli.asyncio.run') as mock_asyncio:
            
            mock_asyncio.return_value = True
            
            # Execute command with options
            result = self.runner.invoke(cli, [
                'update', '123', 
                '--force', 
                '--agent', 'custom-updater'
            ])
            
            # Assert
            assert result.exit_code == 0
            mock_asyncio.assert_called_once()
    
    def test_update_command_failure(self):
        """Test update command when update fails."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.asyncio.run', return_value=False):
            
            # Execute command
            result = self.runner.invoke(cli, ['update', '123'])
            
            # Assert
            assert result.exit_code == 1
            assert "Failed to update PR #123" in result.output
    
    def test_merge_command_success(self):
        """Test successful merge command execution."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.execute_auto_merge') as mock_merge, \
             patch('auto.cli.get_core') as mock_core, \
             patch('auto.cli.asyncio.run') as mock_asyncio:
            
            mock_asyncio.return_value = True
            
            # Execute command
            result = self.runner.invoke(cli, ['merge', '123'])
            
            # Assert
            assert result.exit_code == 0
            assert "Starting merge process for PR #123" in result.output
            assert "PR #123 merged successfully" in result.output
    
    def test_merge_command_with_options(self):
        """Test merge command with all options."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.execute_auto_merge') as mock_merge, \
             patch('auto.cli.get_core') as mock_core, \
             patch('auto.cli.asyncio.run') as mock_asyncio:
            
            mock_asyncio.return_value = True
            
            # Execute command with options
            result = self.runner.invoke(cli, [
                'merge', '123', 
                '--force', 
                '--method', 'squash',
                '--no-cleanup'
            ])
            
            # Assert
            assert result.exit_code == 0
            mock_asyncio.assert_called_once()
    
    def test_merge_command_failure(self):
        """Test merge command when merge fails."""
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.get_core') as mock_core, \
             patch('auto.cli.asyncio.run', return_value=False):
            
            # Execute command
            result = self.runner.invoke(cli, ['merge', '123'])
            
            # Assert
            assert result.exit_code == 1
            assert "Failed to merge PR #123" in result.output
    
    def test_merge_command_invalid_method(self):
        """Test merge command with invalid merge method."""
        # Execute command with invalid method
        result = self.runner.invoke(cli, [
            'merge', '123', 
            '--method', 'invalid'
        ])
        
        # Assert
        assert result.exit_code != 0
        # Click should handle the invalid choice validation
    
    def test_pr_id_parsing(self):
        """Test various PR ID formats are handled correctly."""
        test_cases = [
            "123",      # Plain number
            "#123",     # With hash
            "pr-123",   # Invalid format
        ]
        
        with patch('auto.cli.detect_repository', return_value=self.mock_repo), \
             patch('auto.cli.asyncio.run', return_value=True):
            
            # Test valid formats
            for pr_id in ["123", "#123"]:
                result = self.runner.invoke(cli, ['review', pr_id])
                assert result.exit_code == 0
            
            # Test invalid format
            result = self.runner.invoke(cli, ['review', 'pr-123'])
            assert result.exit_code == 1
            assert "Invalid PR ID format" in result.output


class TestCLIStatusCommand:
    """Test CLI status command with review information."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.mock_core = MagicMock()
        self.mock_workflow_state = MagicMock()
        self.mock_workflow_state.issue_id = "TEST-123"
        self.mock_workflow_state.status = "in_review"
        self.mock_workflow_state.ai_status = "implemented"
        self.mock_workflow_state.pr_number = 456
        self.mock_workflow_state.branch = "feature/test"
        self.mock_workflow_state.updated_at.strftime.return_value = "2024-01-15 10:30"
        self.mock_workflow_state.worktree_info = None
        self.mock_workflow_state.repository = None
    
    def test_status_command_basic(self):
        """Test basic status command."""
        with patch('auto.cli.get_core', return_value=self.mock_core):
            
            self.mock_core.get_workflow_states.return_value = [self.mock_workflow_state]
            
            # Execute command
            result = self.runner.invoke(cli, ['status'])
            
            # Assert
            assert result.exit_code == 0
            assert "Active Workflows" in result.output
            assert "TEST-123" in result.output
            assert "#456" in result.output
    
    def test_status_command_with_reviews(self):
        """Test status command with review information."""
        with patch('auto.cli.get_core', return_value=self.mock_core), \
             patch('auto.cli.get_review_cycle_status') as mock_review_status, \
             patch('auto.cli.asyncio.run') as mock_asyncio:
            
            self.mock_core.get_workflow_states.return_value = [self.mock_workflow_state]
            
            # Setup mock review status
            mock_cycle_status = MagicMock()
            mock_cycle_status.status.value = "waiting_for_human"
            mock_cycle_status.iteration_count = 2
            mock_asyncio.return_value = mock_cycle_status
            
            # Execute command with reviews flag
            result = self.runner.invoke(cli, ['status', '--reviews'])
            
            # Assert
            assert result.exit_code == 0
            assert "Review Status" in result.output
            assert "Iterations" in result.output
    
    def test_status_command_verbose(self):
        """Test status command with verbose output."""
        with patch('auto.cli.get_core', return_value=self.mock_core):
            
            self.mock_core.get_workflow_states.return_value = [self.mock_workflow_state]
            
            # Execute command with verbose flag
            result = self.runner.invoke(cli, ['status', '--verbose'])
            
            # Assert
            assert result.exit_code == 0
            assert "Worktree" in result.output
            assert "Repository" in result.output
    
    def test_status_command_no_workflows(self):
        """Test status command when no workflows are active."""
        with patch('auto.cli.get_core', return_value=self.mock_core):
            
            self.mock_core.get_workflow_states.return_value = []
            
            # Execute command
            result = self.runner.invoke(cli, ['status'])
            
            # Assert
            assert result.exit_code == 0
            assert "No active workflows found" in result.output
    
    def test_status_command_error_handling(self):
        """Test status command error handling."""
        with patch('auto.cli.get_core', side_effect=Exception("Core error")):
            
            # Execute command
            result = self.runner.invoke(cli, ['status'])
            
            # Assert
            assert result.exit_code == 1
            assert "Error:" in result.output


class TestCLIIntegration:
    """Integration tests for CLI review commands."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    def test_review_update_merge_workflow(self):
        """Test complete review workflow through CLI."""
        mock_repo = MagicMock()
        mock_repo.owner = "owner"
        mock_repo.name = "repo"
        
        with patch('auto.cli.detect_repository', return_value=mock_repo), \
             patch('auto.cli.asyncio.run', return_value=True):
            
            # Step 1: Trigger review
            result = self.runner.invoke(cli, ['review', '123'])
            assert result.exit_code == 0
            assert "AI review completed" in result.output
            
            # Step 2: Update based on comments
            result = self.runner.invoke(cli, ['update', '123'])
            assert result.exit_code == 0
            assert "updated successfully" in result.output
            
            # Step 3: Merge after approval
            result = self.runner.invoke(cli, ['merge', '123'])
            assert result.exit_code == 0
            assert "merged successfully" in result.output
    
    def test_error_propagation(self):
        """Test that errors are properly propagated through CLI."""
        with patch('auto.cli.detect_repository', side_effect=Exception("Repository error")):
            
            # Test each command handles repository errors
            for command in ['review', 'update', 'merge']:
                result = self.runner.invoke(cli, [command, '123'])
                assert result.exit_code == 1
                assert "Could not detect repository" in result.output
    
    def test_help_messages(self):
        """Test that help messages are informative."""
        # Test help for review command
        result = self.runner.invoke(cli, ['review', '--help'])
        assert result.exit_code == 0
        assert "Trigger AI review on existing PR" in result.output
        assert "--force" in result.output
        assert "--agent" in result.output
        
        # Test help for update command
        result = self.runner.invoke(cli, ['update', '--help'])
        assert result.exit_code == 0
        assert "Update PR based on review comments" in result.output
        
        # Test help for merge command
        result = self.runner.invoke(cli, ['merge', '--help'])
        assert result.exit_code == 0
        assert "Merge PR after approval validation" in result.output
        assert "--method" in result.output
        assert "--cleanup" in result.output


class TestCLIArgumentValidation:
    """Test CLI argument validation."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    def test_missing_pr_id_argument(self):
        """Test commands fail when PR ID is missing."""
        for command in ['review', 'update', 'merge']:
            result = self.runner.invoke(cli, [command])
            assert result.exit_code != 0
            # Click should show usage error
    
    def test_invalid_merge_method(self):
        """Test merge command validates method choices."""
        result = self.runner.invoke(cli, ['merge', '123', '--method', 'invalid'])
        assert result.exit_code != 0
        # Click should validate the choice
    
    def test_boolean_flag_handling(self):
        """Test boolean flags work correctly."""
        with patch('auto.cli.detect_repository') as mock_detect, \
             patch('auto.cli.asyncio.run', return_value=True):
            
            mock_repo = MagicMock()
            mock_repo.owner = "owner"
            mock_repo.name = "repo"
            mock_detect.return_value = mock_repo
            
            # Test --force flag
            result = self.runner.invoke(cli, ['review', '123', '--force'])
            assert result.exit_code == 0
            
            # Test --no-cleanup flag for merge
            result = self.runner.invoke(cli, ['merge', '123', '--no-cleanup'])
            assert result.exit_code == 0