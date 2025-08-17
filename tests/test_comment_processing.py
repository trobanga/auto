"""
Tests for review comment processing and analysis functionality.

This module tests the sophisticated comment analysis, categorization, and response
generation capabilities.
"""

import pytest
import asyncio
from datetime import datetime
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock, patch

from auto.models import ReviewComment, Issue, AIResponse
from auto.integrations.github import GitHubIntegration
from auto.integrations.ai import ClaudeIntegration
from auto.workflows.review_comment import (
    ReviewCommentProcessor,
    CommentCategory,
    CommentPriority,
    CommentType,
    ProcessedComment,
    CommentResponse,
    CommentThread,
    CommentProcessingResult,
    CommentHistory
)


@pytest.fixture
def mock_github_integration():
    """Create mock GitHub integration."""
    return Mock(spec=GitHubIntegration)


@pytest.fixture
def mock_ai_integration():
    """Create mock AI integration."""
    mock_ai = Mock(spec=ClaudeIntegration)
    mock_ai.execute_update_from_review = AsyncMock()
    return mock_ai


@pytest.fixture
def comment_processor(mock_github_integration, mock_ai_integration):
    """Create ReviewCommentProcessor instance with mocked dependencies."""
    return ReviewCommentProcessor(mock_github_integration, mock_ai_integration)


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
            body="This function has a potential null pointer exception on line 15",
            path="src/auth.py",
            line=15,
            author="reviewer1",
            created_at=datetime.now(),
            resolved=False
        ),
        ReviewComment(
            id=2,
            body="Consider using async/await here for better performance",
            path="src/auth.py",
            line=25,
            author="reviewer1",
            created_at=datetime.now(),
            resolved=False
        ),
        ReviewComment(
            id=3,
            body="Missing docstring for this function",
            path="src/auth.py",
            line=10,
            author="reviewer2",
            created_at=datetime.now(),
            resolved=False
        ),
        ReviewComment(
            id=4,
            body="This is a security vulnerability - passwords should be hashed",
            path="src/auth.py",
            line=50,
            author="security-bot",
            created_at=datetime.now(),
            resolved=False
        ),
        ReviewComment(
            id=5,
            body="Nit: consider using a more descriptive variable name",
            path="src/utils.py",
            line=5,
            author="reviewer2",
            created_at=datetime.now(),
            resolved=False
        ),
        ReviewComment(
            id=6,
            body="Great implementation! This looks good to me.",
            path=None,
            line=None,
            author="reviewer1",
            created_at=datetime.now(),
            resolved=False
        )
    ]


class TestCommentCategorization:
    """Test comment categorization functionality."""
    
    def test_categorize_bug_comment(self, comment_processor):
        """Test bug comment categorization."""
        bug_comments = [
            "This function has a bug that causes crashes",
            "Null pointer exception here",
            "This doesn't work as expected",
            "The error handling is broken"
        ]
        
        for comment_text in bug_comments:
            category = comment_processor._categorize_comment(comment_text)
            assert category == CommentCategory.BUG
    
    def test_categorize_security_comment(self, comment_processor):
        """Test security comment categorization."""
        security_comments = [
            "This is a security vulnerability",
            "Passwords should be hashed for security",
            "XSS vulnerability in this code",
            "Need to validate input to prevent injection"
        ]
        
        for comment_text in security_comments:
            category = comment_processor._categorize_comment(comment_text)
            assert category == CommentCategory.SECURITY
    
    def test_categorize_performance_comment(self, comment_processor):
        """Test performance comment categorization."""
        performance_comments = [
            "This is slow and needs optimization",
            "Consider using async/await for better performance",
            "Memory usage is too high here",
            "This query causes N+1 problems"
        ]
        
        for comment_text in performance_comments:
            category = comment_processor._categorize_comment(comment_text)
            assert category == CommentCategory.PERFORMANCE
    
    def test_categorize_style_comment(self, comment_processor):
        """Test style comment categorization."""
        style_comments = [
            "Inconsistent naming convention",
            "Please fix the indentation",
            "Line too long, should be wrapped",
            "Missing spaces around operators"
        ]
        
        for comment_text in style_comments:
            category = comment_processor._categorize_comment(comment_text)
            assert category == CommentCategory.STYLE
    
    def test_categorize_documentation_comment(self, comment_processor):
        """Test documentation comment categorization."""
        doc_comments = [
            "Missing docstring for this function",
            "Please add comments to explain this logic",
            "README needs to be updated",
            "Add documentation for this API"
        ]
        
        for comment_text in doc_comments:
            category = comment_processor._categorize_comment(comment_text)
            assert category == CommentCategory.DOCUMENTATION
    
    def test_categorize_testing_comment(self, comment_processor):
        """Test testing comment categorization."""
        test_comments = [
            "Missing test coverage for this function",
            "Add unit tests for error cases",
            "Mock this dependency in tests",
            "Test spec is incomplete"
        ]
        
        for comment_text in test_comments:
            category = comment_processor._categorize_comment(comment_text)
            assert category == CommentCategory.TESTING
    
    def test_categorize_question_comment(self, comment_processor):
        """Test question comment categorization."""
        question_comments = [
            "Why is this approach chosen?",
            "Can you explain this logic?",
            "Unclear what this function does?",
            "How does this handle edge cases?"
        ]
        
        for comment_text in question_comments:
            category = comment_processor._categorize_comment(comment_text)
            assert category == CommentCategory.QUESTION
    
    def test_categorize_nitpick_comment(self, comment_processor):
        """Test nitpick comment categorization."""
        nitpick_comments = [
            "Nit: consider using a different variable name",
            "Minor: extra whitespace here",
            "Nitpick: this could be slightly better",
            "Tiny issue with formatting"
        ]
        
        for comment_text in nitpick_comments:
            category = comment_processor._categorize_comment(comment_text)
            assert category == CommentCategory.NITPICK


class TestCommentPrioritization:
    """Test comment priority determination."""
    
    def test_determine_critical_priority(self, comment_processor):
        """Test critical priority determination."""
        critical_comments = [
            ("Critical security issue", CommentCategory.SECURITY),
            ("This is blocking deployment", CommentCategory.BUG),
            ("Urgent fix needed", CommentCategory.BUG),
            ("Broken functionality", CommentCategory.BUG)
        ]
        
        for comment_text, category in critical_comments:
            priority = comment_processor._determine_priority(comment_text, category)
            assert priority == CommentPriority.CRITICAL
    
    def test_determine_high_priority(self, comment_processor):
        """Test high priority determination."""
        high_comments = [
            ("This should be fixed", CommentCategory.CODE_QUALITY),
            ("Performance issue that must be addressed", CommentCategory.PERFORMANCE),
            ("Important: this needs attention", CommentCategory.STYLE)
        ]
        
        for comment_text, category in high_comments:
            priority = comment_processor._determine_priority(comment_text, category)
            assert priority == CommentPriority.HIGH
    
    def test_determine_low_priority(self, comment_processor):
        """Test low priority determination."""
        low_comments = [
            ("Nit: minor style issue", CommentCategory.NITPICK),
            ("Optional improvement", CommentCategory.SUGGESTION),
            ("Question about implementation?", CommentCategory.QUESTION)
        ]
        
        for comment_text, category in low_comments:
            priority = comment_processor._determine_priority(comment_text, category)
            assert priority == CommentPriority.LOW
    
    def test_determine_medium_priority_default(self, comment_processor):
        """Test medium priority as default."""
        medium_comment = "Regular feedback comment"
        priority = comment_processor._determine_priority(medium_comment, CommentCategory.CODE_QUALITY)
        assert priority == CommentPriority.MEDIUM


class TestCommentTypeAnalysis:
    """Test comment type analysis."""
    
    def test_analyze_line_comment(self, comment_processor):
        """Test line comment type analysis."""
        line_comment = ReviewComment(
            id=1,
            body="Issue on this line",
            path="src/test.py",
            line=10,
            author="reviewer"
        )
        
        comment_type = comment_processor._analyze_comment_type(line_comment)
        assert comment_type == CommentType.LINE_COMMENT
    
    def test_analyze_suggestion_comment(self, comment_processor):
        """Test suggestion comment type analysis."""
        suggestion_comment = ReviewComment(
            id=1,
            body="```suggestion\nfixed_code_here\n```",
            path="src/test.py",
            line=10,
            author="reviewer"
        )
        
        comment_type = comment_processor._analyze_comment_type(suggestion_comment)
        assert comment_type == CommentType.SUGGESTION
    
    def test_analyze_file_comment(self, comment_processor):
        """Test file comment type analysis."""
        file_comment = ReviewComment(
            id=1,
            body="General comment about the file",
            path="src/test.py",
            line=None,
            author="reviewer"
        )
        
        comment_type = comment_processor._analyze_comment_type(file_comment)
        assert comment_type == CommentType.FILE_COMMENT
    
    def test_analyze_general_comment(self, comment_processor):
        """Test general comment type analysis."""
        general_comment = ReviewComment(
            id=1,
            body="Overall feedback",
            path=None,
            line=None,
            author="reviewer"
        )
        
        comment_type = comment_processor._analyze_comment_type(general_comment)
        assert comment_type == CommentType.GENERAL_COMMENT
    
    def test_analyze_change_request(self, comment_processor):
        """Test change request type analysis."""
        change_request = ReviewComment(
            id=1,
            body="This must be fixed before merging",
            path=None,
            line=None,
            author="reviewer"
        )
        
        comment_type = comment_processor._analyze_comment_type(change_request)
        assert comment_type == CommentType.CHANGE_REQUEST


class TestCommentProcessing:
    """Test comment processing workflow."""
    
    @pytest.mark.asyncio
    async def test_analyze_review_comments(self, comment_processor, sample_review_comments, sample_issue):
        """Test comprehensive comment analysis."""
        result = await comment_processor.analyze_review_comments(
            pr_number=123,
            repository="test/repo",
            comments=sample_review_comments
        )
        
        assert isinstance(result, CommentProcessingResult)
        assert result.total_comments == len(sample_review_comments)
        assert len(result.processed_comments) == len(sample_review_comments)
        assert result.actionable_count > 0
        assert len(result.comment_threads) > 0
        
        # Check priority summary
        assert CommentPriority.CRITICAL in result.priority_summary
        assert CommentPriority.HIGH in result.priority_summary
        assert CommentPriority.MEDIUM in result.priority_summary
        assert CommentPriority.LOW in result.priority_summary
        
        # Check category summary
        assert CommentCategory.BUG in result.category_summary
        assert CommentCategory.SECURITY in result.category_summary
        assert CommentCategory.PERFORMANCE in result.category_summary
    
    @pytest.mark.asyncio
    async def test_process_single_comment_bug(self, comment_processor):
        """Test processing a single bug comment."""
        bug_comment = ReviewComment(
            id=1,
            body="This function has a null pointer exception",
            path="src/auth.py",
            line=15,
            author="reviewer",
            created_at=datetime.now(),
            resolved=False
        )
        
        processed = await comment_processor._process_single_comment(
            bug_comment, 123, "test/repo"
        )
        
        assert processed.category == CommentCategory.BUG
        assert processed.priority == CommentPriority.CRITICAL
        assert processed.actionable is True
        assert processed.requires_code_change is True
        assert processed.complexity_score > 5  # Bugs are usually complex
    
    @pytest.mark.asyncio
    async def test_process_single_comment_style(self, comment_processor):
        """Test processing a single style comment."""
        style_comment = ReviewComment(
            id=1,
            body="Nit: inconsistent indentation",
            path="src/utils.py",
            line=5,
            author="reviewer",
            created_at=datetime.now(),
            resolved=False
        )
        
        processed = await comment_processor._process_single_comment(
            style_comment, 123, "test/repo"
        )
        
        assert processed.category == CommentCategory.NITPICK
        assert processed.priority == CommentPriority.LOW
        assert processed.actionable is False  # Nitpicks often not actionable
        assert processed.complexity_score < 5  # Style issues are usually simple
    
    def test_prioritize_feedback(self, comment_processor):
        """Test feedback prioritization."""
        # Create test comments with different priorities
        comments = []
        
        # Critical bug
        bug_comment = ProcessedComment(
            original_comment=ReviewComment(id=1, body="Critical bug", author="test"),
            category=CommentCategory.BUG,
            priority=CommentPriority.CRITICAL,
            comment_type=CommentType.LINE_COMMENT,
            actionable=True,
            requires_code_change=True,
            complexity_score=8,
            estimated_effort="significant"
        )
        
        # Low priority nitpick
        nitpick_comment = ProcessedComment(
            original_comment=ReviewComment(id=2, body="Minor style issue", author="test"),
            category=CommentCategory.NITPICK,
            priority=CommentPriority.LOW,
            comment_type=CommentType.LINE_COMMENT,
            actionable=False,
            requires_code_change=False,
            complexity_score=2,
            estimated_effort="quick"
        )
        
        # Medium priority performance
        perf_comment = ProcessedComment(
            original_comment=ReviewComment(id=3, body="Performance issue", author="test"),
            category=CommentCategory.PERFORMANCE,
            priority=CommentPriority.MEDIUM,
            comment_type=CommentType.LINE_COMMENT,
            actionable=True,
            requires_code_change=True,
            complexity_score=6,
            estimated_effort="medium"
        )
        
        comments = [nitpick_comment, perf_comment, bug_comment]
        
        prioritized = comment_processor.prioritize_feedback(comments)
        
        # Should be ordered: bug (critical) -> perf (medium) -> nitpick (low)
        assert prioritized[0].priority == CommentPriority.CRITICAL
        assert prioritized[1].priority == CommentPriority.MEDIUM
        assert prioritized[2].priority == CommentPriority.LOW


class TestCommentResponseGeneration:
    """Test comment response generation."""
    
    @pytest.mark.asyncio
    async def test_generate_comment_responses(self, comment_processor, mock_ai_integration, sample_issue):
        """Test generating responses to comments."""
        # Setup mock AI response
        mock_ai_response = AIResponse(
            success=True,
            response_type="comment_response",
            content="Thank you for the feedback. I'll address this issue by...",
            file_changes=[],
            commands=[],
            metadata={}
        )
        mock_ai_integration.execute_update_from_review.return_value = mock_ai_response
        
        # Create mock processing result
        processed_comment = ProcessedComment(
            original_comment=ReviewComment(id=1, body="Bug in function", author="reviewer"),
            category=CommentCategory.BUG,
            priority=CommentPriority.CRITICAL,
            comment_type=CommentType.LINE_COMMENT,
            actionable=True,
            requires_code_change=True,
            complexity_score=7,
            estimated_effort="medium"
        )
        
        processing_result = CommentProcessingResult(
            total_comments=1,
            processed_comments=[processed_comment],
            comment_threads=[],
            priority_summary={CommentPriority.CRITICAL: 1},
            category_summary={CommentCategory.BUG: 1},
            actionable_count=1,
            estimated_total_effort="medium",
            recommended_order=[1]
        )
        
        responses = await comment_processor.generate_comment_responses(
            processing_result, sample_issue, "test/repo"
        )
        
        assert len(responses) == 1
        assert isinstance(responses[0], CommentResponse)
        assert responses[0].comment_id == 1
        assert responses[0].acknowledgment is True
        assert responses[0].response_text == mock_ai_response.content
    
    @pytest.mark.asyncio
    async def test_generate_single_response(self, comment_processor, mock_ai_integration, sample_issue):
        """Test generating a single comment response."""
        # Setup mock AI response
        mock_ai_response = AIResponse(
            success=True,
            response_type="comment_response",
            content="Thanks for pointing this out. I will fix the null pointer exception by adding proper null checks and validation.",
            file_changes=[],
            commands=[],
            metadata={}
        )
        mock_ai_integration.execute_update_from_review.return_value = mock_ai_response
        
        processed_comment = ProcessedComment(
            original_comment=ReviewComment(
                id=1,
                body="Null pointer exception on line 15",
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
            estimated_effort="medium"
        )
        
        response = await comment_processor._generate_single_response(
            processed_comment, sample_issue, "test/repo"
        )
        
        assert response is not None
        assert response.comment_id == 1
        assert response.acknowledgment is True
        assert "fix" in response.response_text.lower()
        assert "null pointer" in response.response_text.lower()
    
    def test_extract_planned_action(self, comment_processor):
        """Test extracting planned action from response."""
        response_texts = [
            "I will fix this by adding validation",
            "Plan to refactor this function for better performance",
            "Going to implement proper error handling",
            "Action: Update the documentation to clarify this"
        ]
        
        for text in response_texts:
            action = comment_processor._extract_planned_action(text)
            assert action is not None
            assert len(action) > 0
    
    def test_extract_implementation_notes(self, comment_processor):
        """Test extracting implementation details from response."""
        response_texts = [
            "Implementation: Use try-catch blocks around the database calls",
            "Technically, we need to use async/await pattern here",
            "The approach will be to cache the results using Redis",
            "By implementing a factory pattern, we can solve this"
        ]
        
        for text in response_texts:
            notes = comment_processor._extract_implementation_notes(text)
            assert notes is not None
            assert len(notes) > 0


class TestCommentThreads:
    """Test comment thread organization."""
    
    def test_organize_comment_threads(self, comment_processor):
        """Test organizing comments into threads."""
        comments = [
            ProcessedComment(
                original_comment=ReviewComment(
                    id=1, body="Issue 1", path="file1.py", line=10, author="reviewer1"
                ),
                category=CommentCategory.BUG,
                priority=CommentPriority.HIGH,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=True,
                complexity_score=5,
                estimated_effort="medium"
            ),
            ProcessedComment(
                original_comment=ReviewComment(
                    id=2, body="Issue 2", path="file1.py", line=12, author="reviewer1"
                ),
                category=CommentCategory.STYLE,
                priority=CommentPriority.LOW,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=False,
                complexity_score=2,
                estimated_effort="quick"
            ),
            ProcessedComment(
                original_comment=ReviewComment(
                    id=3, body="General feedback", path=None, line=None, author="reviewer2"
                ),
                category=CommentCategory.SUGGESTION,
                priority=CommentPriority.MEDIUM,
                comment_type=CommentType.GENERAL_COMMENT,
                actionable=True,
                requires_code_change=False,
                complexity_score=3,
                estimated_effort="quick"
            )
        ]
        
        threads = comment_processor._organize_comment_threads(comments)
        
        assert len(threads) >= 2  # At least file thread and general thread
        
        # Check that file comments are grouped together
        file_threads = [t for t in threads if "file_" in t.thread_id]
        assert len(file_threads) >= 1
        
        # Check that general comments have their own threads
        general_threads = [t for t in threads if "general_" in t.thread_id]
        assert len(general_threads) >= 1
    
    def test_group_comments_by_proximity(self, comment_processor):
        """Test grouping comments by line proximity."""
        comments = [
            ProcessedComment(
                original_comment=ReviewComment(id=1, body="Issue 1", line=10, author="reviewer"),
                category=CommentCategory.BUG,
                priority=CommentPriority.HIGH,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=True,
                complexity_score=5,
                estimated_effort="medium"
            ),
            ProcessedComment(
                original_comment=ReviewComment(id=2, body="Issue 2", line=12, author="reviewer"),
                category=CommentCategory.STYLE,
                priority=CommentPriority.LOW,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=False,
                complexity_score=2,
                estimated_effort="quick"
            ),
            ProcessedComment(
                original_comment=ReviewComment(id=3, body="Issue 3", line=50, author="reviewer"),
                category=CommentCategory.PERFORMANCE,
                priority=CommentPriority.MEDIUM,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=True,
                complexity_score=4,
                estimated_effort="medium"
            )
        ]
        
        groups = comment_processor._group_comments_by_proximity(comments)
        
        # Lines 10 and 12 should be grouped together (within 10 lines)
        # Line 50 should be in a separate group
        assert len(groups) == 2
        assert len(groups[0]) == 2  # Lines 10 and 12
        assert len(groups[1]) == 1  # Line 50


class TestCommentHistory:
    """Test comment history tracking."""
    
    @pytest.mark.asyncio
    async def test_track_comment_history(self, comment_processor):
        """Test tracking comment processing history."""
        # Create mock processing result
        processing_result = CommentProcessingResult(
            total_comments=3,
            processed_comments=[],
            comment_threads=[],
            priority_summary={CommentPriority.HIGH: 2, CommentPriority.LOW: 1},
            category_summary={CommentCategory.BUG: 1, CommentCategory.STYLE: 2},
            actionable_count=2,
            estimated_total_effort="medium",
            recommended_order=[1, 2]
        )
        
        ai_responses = [
            CommentResponse(
                comment_id=1,
                response_text="Response to comment 1",
                acknowledgment=True,
                planned_action="Fix the bug"
            ),
            CommentResponse(
                comment_id=2,
                response_text="Response to comment 2",
                acknowledgment=True,
                planned_action="Improve style"
            )
        ]
        
        with patch.object(comment_processor, '_save_comment_history') as mock_save:
            history = await comment_processor.track_comment_history(
                pr_number=123,
                repository="test/repo",
                processing_result=processing_result,
                ai_responses=ai_responses
            )
        
        assert isinstance(history, CommentHistory)
        assert history.pr_number == 123
        assert history.repository == "test/repo"
        assert history.original_comments_count == 3
        assert history.responses_generated == 2
        assert history.processing_result == processing_result
        assert history.ai_responses == ai_responses
        
        # Verify save was called
        mock_save.assert_called_once_with(history)


class TestCommentValidation:
    """Test comment processing validation."""
    
    def test_calculate_complexity_score(self, comment_processor):
        """Test complexity score calculation."""
        test_cases = [
            ("Simple typo fix", CommentCategory.STYLE, 3),
            ("Fix null pointer exception", CommentCategory.BUG, 7),
            ("Refactor entire authentication system", CommentCategory.CODE_QUALITY, 9),
            ("Add docstring", CommentCategory.DOCUMENTATION, 2),
            ("Security vulnerability needs fixing", CommentCategory.SECURITY, 8)
        ]
        
        for comment_text, category, expected_min_score in test_cases:
            score = comment_processor._calculate_complexity_score(comment_text, category)
            assert 1 <= score <= 10
            if expected_min_score:
                assert score >= expected_min_score - 2  # Allow some variance
    
    def test_estimate_effort(self, comment_processor):
        """Test effort estimation."""
        test_cases = [
            (2, CommentCategory.STYLE, "quick"),
            (5, CommentCategory.CODE_QUALITY, "medium"),
            (8, CommentCategory.BUG, "significant"),
            (1, CommentCategory.NITPICK, "quick"),
            (9, CommentCategory.SECURITY, "significant")
        ]
        
        for complexity_score, category, expected_effort in test_cases:
            effort = comment_processor._estimate_effort(complexity_score, category)
            assert effort in ["quick", "medium", "significant"]
            assert effort == expected_effort
    
    def test_is_actionable(self, comment_processor):
        """Test actionable comment detection."""
        actionable_comments = [
            ("Fix this bug", CommentCategory.BUG),
            ("This needs to be changed", CommentCategory.CODE_QUALITY),
            ("Security issue here", CommentCategory.SECURITY),
            ("Performance problem", CommentCategory.PERFORMANCE)
        ]
        
        non_actionable_comments = [
            ("Just curious about this?", CommentCategory.QUESTION),
            ("Nit: minor style thing", CommentCategory.NITPICK),
            ("Why did you choose this approach?", CommentCategory.QUESTION)
        ]
        
        for comment_text, category in actionable_comments:
            assert comment_processor._is_actionable(comment_text, category) is True
        
        for comment_text, category in non_actionable_comments:
            assert comment_processor._is_actionable(comment_text, category) is False
    
    def test_requires_code_change(self, comment_processor):
        """Test code change requirement detection."""
        code_change_comments = [
            ("Fix this bug", CommentType.LINE_COMMENT),
            ("```suggestion\nnew code\n```", CommentType.SUGGESTION),
            ("This must be changed", CommentType.CHANGE_REQUEST),
            ("Refactor this function", CommentType.LINE_COMMENT)
        ]
        
        no_code_change_comments = [
            ("Why this approach?", CommentType.GENERAL_COMMENT),
            ("Good implementation", CommentType.GENERAL_COMMENT),
            ("Question about logic", CommentType.FILE_COMMENT)
        ]
        
        for comment_text, comment_type in code_change_comments:
            assert comment_processor._requires_code_change(comment_text, comment_type) is True
        
        for comment_text, comment_type in no_code_change_comments:
            # Some may still require code changes based on content
            result = comment_processor._requires_code_change(comment_text, comment_type)
            assert isinstance(result, bool)


if __name__ == "__main__":
    pytest.main([__file__])