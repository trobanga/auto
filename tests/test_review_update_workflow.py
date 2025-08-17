"""
Tests for review update workflow functionality.

This module tests the sophisticated PR update workflows that apply review feedback
through AI-powered code changes and validation.
"""

import pytest
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from auto.models import ReviewComment, Issue, AIResponse, WorktreeInfo
from auto.integrations.github import GitHubIntegration
from auto.integrations.git import GitWorktreeManager
from auto.integrations.ai import ClaudeIntegration
from auto.workflows.review_comment import (
    ReviewCommentProcessor,
    ProcessedComment,
    CommentProcessingResult,
    CommentCategory,
    CommentPriority,
    CommentType
)
from auto.workflows.review_update import (
    ReviewUpdateWorkflow,
    UpdateType,
    UpdateStatus,
    UpdatePlan,
    UpdateResult,
    UpdateBatch,
    UpdateValidation,
    CommitStrategy
)


@pytest.fixture
def mock_github_integration():
    """Create mock GitHub integration."""
    mock_github = Mock(spec=GitHubIntegration)
    mock_github.add_pr_comment = AsyncMock()
    return mock_github


@pytest.fixture
def mock_git_integration():
    """Create mock Git integration."""
    mock_git = Mock(spec=GitWorktreeManager)
    mock_git.add_file = AsyncMock()
    mock_git.commit_changes = AsyncMock(return_value="abc123")
    mock_git.push_changes = AsyncMock(return_value=True)
    mock_git.get_current_branch = AsyncMock(return_value="feature/test")
    return mock_git


@pytest.fixture
def mock_ai_integration():
    """Create mock AI integration."""
    mock_ai = Mock(spec=ClaudeIntegration)
    mock_ai.execute_update_from_review = AsyncMock()
    return mock_ai


@pytest.fixture
def mock_comment_processor():
    """Create mock comment processor."""
    return Mock(spec=ReviewCommentProcessor)


@pytest.fixture
def update_workflow(mock_github_integration, mock_git_integration, mock_ai_integration, mock_comment_processor):
    """Create ReviewUpdateWorkflow instance with mocked dependencies."""
    return ReviewUpdateWorkflow(
        mock_github_integration,
        mock_git_integration,
        mock_ai_integration,
        mock_comment_processor
    )


@pytest.fixture
def sample_issue():
    """Create sample issue for testing."""
    return Issue(
        id="123",
        title="Add user authentication",
        description="Implement user login and registration functionality",
        type="feature",
        status="in_progress",
        provider="github"
    )


@pytest.fixture
def sample_review_comments():
    """Create sample review comments for testing."""
    return [
        ReviewComment(
            id=1,
            body="This function has a null pointer exception",
            path="src/auth.py",
            line=15,
            author="reviewer1",
            created_at=datetime.now(),
            resolved=False
        ),
        ReviewComment(
            id=2,
            body="Consider using async/await for better performance",
            path="src/auth.py",
            line=25,
            author="reviewer1",
            created_at=datetime.now(),
            resolved=False
        ),
        ReviewComment(
            id=3,
            body="Missing docstring for this function",
            path="src/utils.py",
            line=10,
            author="reviewer2",
            created_at=datetime.now(),
            resolved=False
        )
    ]


@pytest.fixture
def sample_processed_comments():
    """Create sample processed comments for testing."""
    return [
        ProcessedComment(
            original_comment=ReviewComment(
                id=1,
                body="Bug in authentication",
                path="src/auth.py",
                line=15,
                author="reviewer"
            ),
            category=CommentCategory.BUG,
            priority=CommentPriority.CRITICAL,
            comment_type=CommentType.LINE_COMMENT,
            actionable=True,
            requires_code_change=True,
            complexity_score=7,
            estimated_effort="medium",
            related_files=["src/auth.py"]
        ),
        ProcessedComment(
            original_comment=ReviewComment(
                id=2,
                body="Performance issue",
                path="src/auth.py",
                line=25,
                author="reviewer"
            ),
            category=CommentCategory.PERFORMANCE,
            priority=CommentPriority.HIGH,
            comment_type=CommentType.LINE_COMMENT,
            actionable=True,
            requires_code_change=True,
            complexity_score=6,
            estimated_effort="medium",
            related_files=["src/auth.py"]
        ),
        ProcessedComment(
            original_comment=ReviewComment(
                id=3,
                body="Missing documentation",
                path="src/utils.py",
                line=10,
                author="reviewer"
            ),
            category=CommentCategory.DOCUMENTATION,
            priority=CommentPriority.MEDIUM,
            comment_type=CommentType.LINE_COMMENT,
            actionable=True,
            requires_code_change=False,
            complexity_score=3,
            estimated_effort="quick",
            related_files=["src/utils.py"]
        )
    ]


@pytest.fixture
def sample_processing_result(sample_processed_comments):
    """Create sample comment processing result."""
    return CommentProcessingResult(
        total_comments=3,
        processed_comments=sample_processed_comments,
        comment_threads=[],
        priority_summary={
            CommentPriority.CRITICAL: 1,
            CommentPriority.HIGH: 1,
            CommentPriority.MEDIUM: 1,
            CommentPriority.LOW: 0
        },
        category_summary={
            CommentCategory.BUG: 1,
            CommentCategory.PERFORMANCE: 1,
            CommentCategory.DOCUMENTATION: 1
        },
        actionable_count=3,
        estimated_total_effort="medium",
        recommended_order=[1, 2, 3]
    )


class TestUpdatePlanCreation:
    """Test update plan creation functionality."""
    
    @pytest.mark.asyncio
    async def test_create_update_plans(self, update_workflow, sample_processing_result, sample_issue):
        """Test creating update plans from processed comments."""
        plans = await update_workflow._create_update_plans(
            sample_processing_result, sample_issue, "test/repo"
        )
        
        assert len(plans) > 0
        
        # Should have plans for different update types
        update_types = [plan.update_type for plan in plans]
        assert UpdateType.CODE_FIX in update_types
        assert UpdateType.PERFORMANCE_OPT in update_types
        
        # Check plan structure
        for plan in plans:
            assert isinstance(plan, UpdatePlan)
            assert plan.update_id
            assert len(plan.target_files) > 0
            assert len(plan.related_comments) > 0
            assert plan.estimated_effort in ["quick", "medium", "significant"]
            assert isinstance(plan.automated, bool)
    
    @pytest.mark.asyncio
    async def test_create_file_update_plans(self, update_workflow, sample_issue):
        """Test creating update plans for specific files."""
        # Create comments for a single file
        bug_comment = ProcessedComment(
            original_comment=ReviewComment(id=1, body="Bug", path="src/auth.py", author="reviewer"),
            category=CommentCategory.BUG,
            priority=CommentPriority.CRITICAL,
            comment_type=CommentType.LINE_COMMENT,
            actionable=True,
            requires_code_change=True,
            complexity_score=7,
            estimated_effort="medium"
        )
        
        style_comment = ProcessedComment(
            original_comment=ReviewComment(id=2, body="Style issue", path="src/auth.py", author="reviewer"),
            category=CommentCategory.STYLE,
            priority=CommentPriority.LOW,
            comment_type=CommentType.LINE_COMMENT,
            actionable=True,
            requires_code_change=True,
            complexity_score=2,
            estimated_effort="quick"
        )
        
        comments = [bug_comment, style_comment]
        
        plans = await update_workflow._create_file_update_plans(
            "src/auth.py", comments, sample_issue, "test/repo"
        )
        
        assert len(plans) == 2  # One for bug, one for style
        
        # Check bug fix plan
        bug_plan = next((p for p in plans if p.update_type == UpdateType.CODE_FIX), None)
        assert bug_plan is not None
        assert "src/auth.py" in bug_plan.target_files
        assert 1 in bug_plan.related_comments
        
        # Check style plan
        style_plan = next((p for p in plans if p.update_type == UpdateType.STYLE_IMPROVEMENT), None)
        assert style_plan is not None
        assert "src/auth.py" in style_plan.target_files
        assert 2 in style_plan.related_comments
    
    def test_group_comments_by_file(self, update_workflow, sample_processed_comments):
        """Test grouping comments by file path."""
        file_groups = update_workflow._group_comments_by_file(sample_processed_comments)
        
        assert "src/auth.py" in file_groups
        assert "src/utils.py" in file_groups
        
        # Check auth.py group
        auth_comments = file_groups["src/auth.py"]
        assert len(auth_comments) == 2
        
        # Check utils.py group
        utils_comments = file_groups["src/utils.py"]
        assert len(utils_comments) == 1
    
    def test_estimate_combined_effort(self, update_workflow):
        """Test estimating combined effort for multiple comments."""
        quick_comments = [
            ProcessedComment(
                original_comment=ReviewComment(id=1, body="Quick fix", author="reviewer"),
                category=CommentCategory.STYLE,
                priority=CommentPriority.LOW,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=True,
                complexity_score=2,
                estimated_effort="quick"
            ),
            ProcessedComment(
                original_comment=ReviewComment(id=2, body="Another quick fix", author="reviewer"),
                category=CommentCategory.STYLE,
                priority=CommentPriority.LOW,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=True,
                complexity_score=3,
                estimated_effort="quick"
            )
        ]
        
        effort = update_workflow._estimate_combined_effort(quick_comments)
        assert effort == "quick"
        
        complex_comments = [
            ProcessedComment(
                original_comment=ReviewComment(id=1, body="Complex fix", author="reviewer"),
                category=CommentCategory.BUG,
                priority=CommentPriority.CRITICAL,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=True,
                complexity_score=8,
                estimated_effort="significant"
            )
        ]
        
        effort = update_workflow._estimate_combined_effort(complex_comments)
        assert effort == "significant"


class TestUpdateBatchOrganization:
    """Test update batch organization."""
    
    @pytest.mark.asyncio
    async def test_organize_update_batches(self, update_workflow):
        """Test organizing update plans into execution batches."""
        # Create test update plans
        plan1 = UpdatePlan(
            update_id="bug_fix_1",
            update_type=UpdateType.CODE_FIX,
            description="Fix bug in auth",
            target_files=["src/auth.py"],
            related_comments=[1],
            estimated_effort="medium",
            dependencies=[],
            automated=True
        )
        
        plan2 = UpdatePlan(
            update_id="style_fix_1",
            update_type=UpdateType.STYLE_IMPROVEMENT,
            description="Fix style issues",
            target_files=["src/utils.py"],
            related_comments=[2],
            estimated_effort="quick",
            dependencies=[],
            automated=True
        )
        
        plan3 = UpdatePlan(
            update_id="dependent_fix",
            update_type=UpdateType.PERFORMANCE_OPT,
            description="Performance optimization",
            target_files=["src/auth.py"],
            related_comments=[3],
            estimated_effort="medium",
            dependencies=["bug_fix_1"],  # Depends on bug fix
            automated=True
        )
        
        update_plans = [plan1, plan2, plan3]
        
        batches = await update_workflow._organize_update_batches(update_plans)
        
        assert len(batches) >= 2  # At least independent and dependent batches
        
        # Check independent batch
        independent_batch = next((b for b in batches if "independent" in b.batch_id), None)
        assert independent_batch is not None
        assert len(independent_batch.updates) == 2  # plan1 and plan2
        
        # Check dependent batch
        dependent_batch = next((b for b in batches if "dependent" in b.batch_id), None)
        assert dependent_batch is not None
        assert len(dependent_batch.updates) == 1  # plan3
    
    def test_estimate_execution_time(self, update_workflow):
        """Test execution time estimation."""
        quick_plan = UpdatePlan(
            update_id="quick_fix",
            update_type=UpdateType.STYLE_IMPROVEMENT,
            description="Quick fix",
            target_files=["file1.py"],
            related_comments=[1],
            estimated_effort="quick",
            dependencies=[],
            automated=True,
            validation_steps=["syntax_check"]
        )
        
        time_estimate = update_workflow._estimate_execution_time(quick_plan)
        assert time_estimate > 0
        assert time_estimate < 100  # Quick tasks should be under 100 seconds
        
        complex_plan = UpdatePlan(
            update_id="complex_fix",
            update_type=UpdateType.CODE_FIX,
            description="Complex fix",
            target_files=["file1.py", "file2.py", "file3.py"],
            related_comments=[1, 2, 3],
            estimated_effort="significant",
            dependencies=[],
            automated=True,
            validation_steps=["syntax_check", "test_execution", "performance_test"]
        )
        
        time_estimate = update_workflow._estimate_execution_time(complex_plan)
        assert time_estimate > 200  # Complex tasks should take longer


class TestUpdateExecution:
    """Test update execution functionality."""
    
    @pytest.mark.asyncio
    async def test_execute_single_update_success(self, update_workflow, mock_ai_integration, sample_issue):
        """Test successful execution of a single update."""
        # Setup mock AI response
        mock_ai_response = AIResponse(
            success=True,
            response_type="targeted_update",
            content="Successfully fixed the bug",
            file_changes=[{"path": "src/auth.py", "action": "modified"}],
            commands=["git add src/auth.py"],
            metadata={}
        )
        mock_ai_integration.execute_update_from_review.return_value = mock_ai_response
        
        update_plan = UpdatePlan(
            update_id="test_update",
            update_type=UpdateType.CODE_FIX,
            description="Fix authentication bug",
            target_files=["src/auth.py"],
            related_comments=[1],
            estimated_effort="medium",
            dependencies=[],
            automated=True,
            validation_steps=["syntax_check"]
        )
        
        with patch.object(update_workflow, '_run_update_validations', return_value={"syntax_check": True}):
            result = await update_workflow._execute_single_update(
                update_plan, "/test/worktree", "test/repo", sample_issue
            )
        
        assert result.status == UpdateStatus.COMPLETED
        assert result.update_id == "test_update"
        assert "src/auth.py" in result.files_modified
        assert result.ai_response == mock_ai_response
        assert result.execution_time > 0
    
    @pytest.mark.asyncio
    async def test_execute_single_update_failure(self, update_workflow, mock_ai_integration, sample_issue):
        """Test failed execution of a single update."""
        # Setup mock AI response failure
        mock_ai_response = AIResponse(
            success=False,
            response_type="targeted_update",
            content="Failed to apply update",
            file_changes=[],
            commands=[],
            metadata={}
        )
        mock_ai_integration.execute_update_from_review.return_value = mock_ai_response
        
        update_plan = UpdatePlan(
            update_id="test_update",
            update_type=UpdateType.CODE_FIX,
            description="Fix authentication bug",
            target_files=["src/auth.py"],
            related_comments=[1],
            estimated_effort="medium",
            dependencies=[],
            automated=True
        )
        
        result = await update_workflow._execute_single_update(
            update_plan, "/test/worktree", "test/repo", sample_issue
        )
        
        assert result.status == UpdateStatus.FAILED
        assert result.update_id == "test_update"
        assert len(result.files_modified) == 0
        assert result.error_message is not None
    
    @pytest.mark.asyncio
    async def test_execute_single_update_manual_required(self, update_workflow, sample_issue):
        """Test update that requires manual intervention."""
        update_plan = UpdatePlan(
            update_id="manual_update",
            update_type=UpdateType.REFACTORING,
            description="Complex refactoring",
            target_files=["src/auth.py"],
            related_comments=[1],
            estimated_effort="significant",
            dependencies=[],
            automated=False  # Requires manual intervention
        )
        
        result = await update_workflow._execute_single_update(
            update_plan, "/test/worktree", "test/repo", sample_issue
        )
        
        assert result.status == UpdateStatus.REQUIRES_MANUAL
        assert result.update_id == "manual_update"
        assert "manual intervention" in result.error_message
    
    @pytest.mark.asyncio
    async def test_build_update_context(self, update_workflow, sample_issue):
        """Test building context for AI update execution."""
        update_plan = UpdatePlan(
            update_id="test_update",
            update_type=UpdateType.CODE_FIX,
            description="Fix authentication bug",
            target_files=["src/auth.py"],
            related_comments=[1, 2],
            estimated_effort="medium",
            dependencies=[],
            automated=True,
            validation_steps=["syntax_check", "test_execution"]
        )
        
        context = await update_workflow._build_update_context(
            update_plan, sample_issue, "test/repo"
        )
        
        assert "Update Type: code_fix" in context
        assert "Fix authentication bug" in context
        assert "src/auth.py" in context
        assert "test/repo" in context
        assert "Add user authentication" in context  # Issue title
        assert "Comment IDs: 1, 2" in context
        assert "syntax_check" in context
        assert "test_execution" in context


class TestUpdateValidation:
    """Test update validation functionality."""
    
    @pytest.mark.asyncio
    async def test_run_update_validations(self, update_workflow):
        """Test running validation steps for updates."""
        update_plan = UpdatePlan(
            update_id="test_update",
            update_type=UpdateType.CODE_FIX,
            description="Test update",
            target_files=["src/test.py"],
            related_comments=[1],
            estimated_effort="medium",
            dependencies=[],
            automated=True,
            validation_steps=["syntax_check", "basic_functionality"]
        )
        
        modified_files = ["src/test.py"]
        
        with patch.object(update_workflow, '_validate_syntax', return_value=True), \
             patch.object(update_workflow, '_validate_basic_functionality', return_value=True):
            
            results = await update_workflow._run_update_validations(
                update_plan, modified_files, "/test/worktree"
            )
        
        assert "syntax_check" in results
        assert "basic_functionality" in results
        assert results["syntax_check"] is True
        assert results["basic_functionality"] is True
    
    @pytest.mark.asyncio
    async def test_validate_syntax(self, update_workflow):
        """Test syntax validation (placeholder)."""
        result = await update_workflow._validate_syntax(["test.py"], "/test/worktree")
        assert isinstance(result, bool)
        assert result is True  # Placeholder implementation returns True
    
    @pytest.mark.asyncio
    async def test_validate_update_requirements(self, update_workflow, sample_review_comments):
        """Test validating update requirements."""
        update_results = [
            UpdateResult(
                update_id="test_update_1",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/auth.py"],
                commands_executed=["test command"],
                execution_time=30.0,
                validation_results={"syntax_check": True}
            ),
            UpdateResult(
                update_id="test_update_2",
                status=UpdateStatus.FAILED,
                files_modified=[],
                commands_executed=[],
                execution_time=10.0,
                error_message="Update failed"
            )
        ]
        
        validations = await update_workflow.validate_update_requirements(
            update_results, "/test/worktree", sample_review_comments
        )
        
        assert len(validations) == 2
        
        # Check successful update validation
        assert validations[0].update_id == "test_update_1"
        assert validations[0].overall_valid is True
        
        # Check failed update validation
        assert validations[1].update_id == "test_update_2"
        assert validations[1].overall_valid is False
        assert len(validations[1].issues_found) > 0


class TestCommitStrategy:
    """Test commit strategy and commit creation."""
    
    @pytest.mark.asyncio
    async def test_commit_review_changes(self, update_workflow, mock_git_integration):
        """Test committing review changes."""
        update_results = [
            UpdateResult(
                update_id="bug_fix_auth",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/auth.py"],
                commands_executed=[],
                execution_time=30.0
            ),
            UpdateResult(
                update_id="style_utils",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/utils.py"],
                commands_executed=[],
                execution_time=15.0
            )
        ]
        
        commit_shas = await update_workflow.commit_review_changes(
            update_results, "/test/worktree", "test/repo", 123
        )
        
        assert len(commit_shas) > 0
        assert all(sha == "abc123" for sha in commit_shas)  # Mock returns abc123
        
        # Verify git operations were called
        assert mock_git_integration.add_file.call_count >= 2
        assert mock_git_integration.commit_changes.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_group_updates_for_commits(self, update_workflow):
        """Test grouping updates for commit creation."""
        update_results = [
            UpdateResult(
                update_id="bug_fix_auth",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/auth.py"],
                commands_executed=[],
                execution_time=30.0
            ),
            UpdateResult(
                update_id="bug_fix_utils",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/utils.py"],
                commands_executed=[],
                execution_time=20.0
            ),
            UpdateResult(
                update_id="style_formatting",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/format.py"],
                commands_executed=[],
                execution_time=10.0
            )
        ]
        
        # Test grouped strategy
        grouped_strategy = CommitStrategy(
            strategy_type="grouped",
            commit_message_template="fix: address {description}",
            group_by_category=True,
            include_comment_refs=True,
            conventional_commits=True
        )
        
        groups = await update_workflow._group_updates_for_commits(update_results, grouped_strategy)
        
        # Should group by update type (bug vs style)
        assert len(groups) >= 1
        
        # Test single strategy
        single_strategy = CommitStrategy(
            strategy_type="single",
            commit_message_template="fix: address review feedback",
            group_by_category=False,
            include_comment_refs=True,
            conventional_commits=True
        )
        
        single_groups = await update_workflow._group_updates_for_commits(update_results, single_strategy)
        assert len(single_groups) == 1
        assert len(single_groups[0]) == 3
    
    @pytest.mark.asyncio
    async def test_generate_commit_message(self, update_workflow):
        """Test generating commit messages."""
        update_group = [
            UpdateResult(
                update_id="bug_fix_auth",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/auth.py"],
                commands_executed=[],
                execution_time=30.0
            )
        ]
        
        commit_strategy = CommitStrategy(
            strategy_type="grouped",
            commit_message_template="fix: address {description}",
            group_by_category=True,
            include_comment_refs=True,
            conventional_commits=True
        )
        
        message = await update_workflow._generate_commit_message(
            update_group, commit_strategy, 123
        )
        
        assert "fix:" in message
        assert "bug" in message
        assert "PR #123" in message
        
        # Test multiple updates
        multi_group = [
            UpdateResult(
                update_id="bug_fix_auth",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/auth.py"],
                commands_executed=[],
                execution_time=30.0
            ),
            UpdateResult(
                update_id="style_utils",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/utils.py"],
                commands_executed=[],
                execution_time=15.0
            )
        ]
        
        multi_message = await update_workflow._generate_commit_message(
            multi_group, commit_strategy, 123
        )
        
        assert "fix:" in multi_message
        assert "review feedback" in multi_message
        assert "PR #123" in multi_message


class TestPRUpdateIntegration:
    """Test PR update integration functionality."""
    
    @pytest.mark.asyncio
    async def test_update_pr_with_changes(self, update_workflow, mock_git_integration, mock_github_integration):
        """Test updating PR with changes."""
        update_results = [
            UpdateResult(
                update_id="test_update",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/auth.py"],
                commands_executed=[],
                execution_time=30.0,
                commit_sha="abc123"
            )
        ]
        
        success = await update_workflow.update_pr_with_changes(
            123, "test/repo", "/test/worktree", update_results
        )
        
        assert success is True
        mock_git_integration.get_current_branch.assert_called_once()
        mock_git_integration.push_changes.assert_called_once()
        mock_github_integration.add_pr_comment.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_add_update_comment_to_pr(self, update_workflow, mock_github_integration):
        """Test adding update summary comment to PR."""
        update_results = [
            UpdateResult(
                update_id="bug_fix_auth",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/auth.py"],
                commands_executed=[],
                execution_time=30.0
            ),
            UpdateResult(
                update_id="failed_update",
                status=UpdateStatus.FAILED,
                files_modified=[],
                commands_executed=[],
                execution_time=10.0,
                error_message="Update failed"
            )
        ]
        
        await update_workflow._add_update_comment_to_pr(
            123, "test/repo", update_results
        )
        
        # Verify comment was added
        mock_github_integration.add_pr_comment.assert_called_once()
        
        # Check comment content
        call_args = mock_github_integration.add_pr_comment.call_args
        comment_body = call_args[0][2]  # Third argument is the comment body
        
        assert "Review Feedback Addressed" in comment_body
        assert "Completed Updates" in comment_body
        assert "Manual Attention" in comment_body
        assert "Bug Fix" in comment_body


class TestSuggestedChanges:
    """Test suggested changes application."""
    
    @pytest.mark.asyncio
    async def test_apply_suggested_changes(self, update_workflow):
        """Test applying reviewer-suggested changes."""
        suggestions = [
            ProcessedComment(
                original_comment=ReviewComment(
                    id=1,
                    body="```suggestion\nfixed_code_here\n```",
                    path="src/auth.py",
                    line=15,
                    author="reviewer"
                ),
                category=CommentCategory.SUGGESTION,
                priority=CommentPriority.MEDIUM,
                comment_type=CommentType.SUGGESTION,
                actionable=True,
                requires_code_change=True,
                suggested_change="fixed_code_here",
                complexity_score=3,
                estimated_effort="quick"
            )
        ]
        
        with patch.object(update_workflow, '_apply_single_suggestion') as mock_apply:
            mock_apply.return_value = UpdateResult(
                update_id="suggestion_1",
                status=UpdateStatus.COMPLETED,
                files_modified=["src/auth.py"],
                commands_executed=[],
                execution_time=10.0
            )
            
            results = await update_workflow.apply_suggested_changes(
                suggestions, "/test/worktree", "test/repo"
            )
        
        assert len(results) == 1
        assert results[0].status == UpdateStatus.COMPLETED
        mock_apply.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_apply_single_suggestion(self, update_workflow):
        """Test applying a single suggestion."""
        suggestion = ProcessedComment(
            original_comment=ReviewComment(
                id=1,
                body="```suggestion\nfixed_code\n```",
                path="src/test.py",
                line=10,
                author="reviewer"
            ),
            category=CommentCategory.SUGGESTION,
            priority=CommentPriority.MEDIUM,
            comment_type=CommentType.SUGGESTION,
            actionable=True,
            requires_code_change=True,
            suggested_change="fixed_code",
            complexity_score=3,
            estimated_effort="quick"
        )
        
        with patch('pathlib.Path.exists', return_value=True):
            result = await update_workflow._apply_single_suggestion(
                suggestion, "/test/worktree", "test/repo"
            )
        
        assert result is not None
        assert result.update_id == "suggestion_1"
        assert result.status == UpdateStatus.COMPLETED
        assert "src/test.py" in result.files_modified


class TestEndToEndWorkflow:
    """Test end-to-end review update workflow."""
    
    @pytest.mark.asyncio
    async def test_execute_review_updates_integration(
        self,
        update_workflow,
        mock_comment_processor,
        mock_ai_integration,
        mock_git_integration,
        sample_issue,
        sample_review_comments,
        sample_processing_result
    ):
        """Test complete review update workflow integration."""
        # Setup mocks
        mock_comment_processor.analyze_review_comments.return_value = sample_processing_result
        
        mock_ai_response = AIResponse(
            success=True,
            response_type="targeted_update",
            content="Successfully applied updates",
            file_changes=[{"path": "src/auth.py", "action": "modified"}],
            commands=[],
            metadata={}
        )
        mock_ai_integration.execute_update_from_review.return_value = mock_ai_response
        
        # Mock validation to always pass
        with patch.object(update_workflow, '_validate_all_updates') as mock_validate:
            mock_validate.return_value = [
                UpdateValidation(
                    update_id="test_update",
                    pre_conditions={"files_exist": True},
                    post_conditions={"changes_applied": True},
                    regression_checks={"syntax_check": True},
                    code_quality_checks={"basic_quality": True},
                    overall_valid=True,
                    issues_found=[]
                )
            ]
            
            results = await update_workflow.execute_review_updates(
                pr_number=123,
                repository="test/repo",
                worktree_path="/test/worktree",
                issue=sample_issue,
                comments=sample_review_comments
            )
        
        # Verify workflow execution
        assert len(results) > 0
        
        # Check that comment processing was called
        mock_comment_processor.analyze_review_comments.assert_called_once()
        
        # Check that AI updates were executed
        assert mock_ai_integration.execute_update_from_review.call_count > 0
        
        # Check that validation was performed
        mock_validate.assert_called_once()
        
        # Check that commits were created (since validation passed)
        assert mock_git_integration.commit_changes.call_count > 0


if __name__ == "__main__":
    pytest.main([__file__])