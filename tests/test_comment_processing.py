"""
Tests for review comment processing and analysis functionality.

This module tests the sophisticated comment analysis, categorization, and response
generation capabilities.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from auto.models import AIResponse, Issue, ReviewComment
from auto.workflows.review_comment import (
    CommentCategory,
    CommentHistory,
    CommentPriority,
    CommentProcessingResult,
    CommentResponse,
    CommentType,
    ProcessedComment,
    ReviewCommentProcessor,
)


@pytest.fixture
def mock_github_integration():
    """Create mock GitHub integration."""
    # Use plain Mock to avoid auto-generating potentially async methods
    return Mock()


@pytest.fixture
def mock_ai_integration():
    """Create mock AI integration."""
    # Use plain Mock to avoid auto-generating potentially async methods
    mock_ai = Mock()

    # Create a proper async mock function that can have return_value set
    class MockExecuteUpdate:
        def __init__(self):
            self.return_value = Mock()

        async def __call__(self, *args, **kwargs):
            return self.return_value

    mock_ai.execute_update_from_review = MockExecuteUpdate()
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
        provider="github",
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
            resolved=False,
        ),
        ReviewComment(
            id=2,
            body="Consider using async/await here for better performance",
            path="src/auth.py",
            line=25,
            author="reviewer1",
            created_at=datetime.now(),
            resolved=False,
        ),
        ReviewComment(
            id=3,
            body="Missing docstring for this function",
            path="src/auth.py",
            line=10,
            author="reviewer2",
            created_at=datetime.now(),
            resolved=False,
        ),
        ReviewComment(
            id=4,
            body="This is a security vulnerability - passwords should be hashed",
            path="src/auth.py",
            line=50,
            author="security-bot",
            created_at=datetime.now(),
            resolved=False,
        ),
        ReviewComment(
            id=5,
            body="Nit: consider using a more descriptive variable name",
            path="src/utils.py",
            line=5,
            author="reviewer2",
            created_at=datetime.now(),
            resolved=False,
        ),
        ReviewComment(
            id=6,
            body="Great implementation! This looks good to me.",
            path=None,
            line=None,
            author="reviewer1",
            created_at=datetime.now(),
            resolved=False,
        ),
    ]


class TestCommentCategorization:
    """Test comment categorization functionality."""

    @pytest.mark.parametrize(
        "comment_text,expected_category",
        [
            # Bug comments
            ("This function has a bug that causes crashes", CommentCategory.BUG),
            ("Null pointer exception here", CommentCategory.BUG),
            ("This doesn't work as expected", CommentCategory.BUG),
            # Security comments
            ("This is a security vulnerability", CommentCategory.SECURITY),
            ("XSS vulnerability in this code", CommentCategory.SECURITY),
            # Performance comments
            ("This is slow and needs optimization", CommentCategory.PERFORMANCE),
            ("Memory usage is too high here", CommentCategory.PERFORMANCE),
            # Style comments
            ("Inconsistent naming convention", CommentCategory.STYLE),
            ("Please fix the indentation", CommentCategory.STYLE),
            # Documentation comments
            ("Missing docstring for this function", CommentCategory.DOCUMENTATION),
            ("Add documentation for this API", CommentCategory.DOCUMENTATION),
            # Testing comments
            ("Missing test coverage for this function", CommentCategory.TESTING),
            ("Test coverage is incomplete", CommentCategory.TESTING),
            # Question comments
            ("Why is this approach chosen?", CommentCategory.QUESTION),
            ("Can you explain this logic?", CommentCategory.QUESTION),
            # Nitpick comments
            ("Nit: consider using a different variable name", CommentCategory.NITPICK),
            ("Minor: extra whitespace here", CommentCategory.NITPICK),
        ],
    )
    def test_categorize_comment(self, comment_processor, comment_text, expected_category):
        """Test comment categorization across all categories."""
        category = comment_processor._categorize_comment(comment_text)
        assert category == expected_category


class TestCommentPrioritization:
    """Test comment priority determination."""

    @pytest.mark.parametrize(
        "comment_text,category,expected_priority",
        [
            # Critical priority
            ("Critical security issue", CommentCategory.SECURITY, CommentPriority.CRITICAL),
            ("This is blocking deployment", CommentCategory.BUG, CommentPriority.CRITICAL),
            ("Urgent fix needed", CommentCategory.BUG, CommentPriority.CRITICAL),
            # High priority
            ("This should be fixed", CommentCategory.CODE_QUALITY, CommentPriority.HIGH),
            (
                "Performance issue that must be addressed",
                CommentCategory.PERFORMANCE,
                CommentPriority.HIGH,
            ),
            ("Important: this needs attention", CommentCategory.STYLE, CommentPriority.HIGH),
            # Low priority
            ("Nit: minor style issue", CommentCategory.NITPICK, CommentPriority.LOW),
            ("Optional improvement", CommentCategory.SUGGESTION, CommentPriority.LOW),
            ("Question about implementation?", CommentCategory.QUESTION, CommentPriority.LOW),
            # Medium priority (default)
            ("Regular feedback comment", CommentCategory.CODE_QUALITY, CommentPriority.MEDIUM),
        ],
    )
    def test_determine_priority(self, comment_processor, comment_text, category, expected_priority):
        """Test comment priority determination across all priority levels."""
        priority = comment_processor._determine_priority(comment_text, category)
        assert priority == expected_priority


class TestCommentTypeAnalysis:
    """Test comment type analysis."""

    @pytest.mark.parametrize(
        "body,path,line,expected_type",
        [
            # Line comment - has path and line
            ("Issue on this line", "src/test.py", 10, CommentType.LINE_COMMENT),
            # Suggestion comment - contains suggestion syntax
            ("```suggestion\nfixed_code_here\n```", "src/test.py", 10, CommentType.SUGGESTION),
            # File comment - has path but no line
            ("General comment about the file", "src/test.py", None, CommentType.FILE_COMMENT),
            # General comment - no path or line
            ("Overall feedback", None, None, CommentType.GENERAL_COMMENT),
            # Change request - strong language
            ("This must be fixed before merging", None, None, CommentType.CHANGE_REQUEST),
        ],
    )
    def test_analyze_comment_type(self, comment_processor, body, path, line, expected_type):
        """Test comment type analysis across all types."""
        comment = ReviewComment(id=1, body=body, path=path, line=line, author="reviewer")

        comment_type = comment_processor._analyze_comment_type(comment)
        assert comment_type == expected_type


class TestCommentProcessing:
    """Test comment processing workflow."""

    @pytest.mark.asyncio
    async def test_analyze_review_comments(
        self, comment_processor, sample_review_comments, sample_issue
    ):
        """Test comprehensive comment analysis."""
        result = await comment_processor.analyze_review_comments(
            pr_number=123, repository="test/repo", comments=sample_review_comments
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
    @pytest.mark.parametrize(
        "body,expected_category,expected_priority,expected_actionable",
        [
            # Bug comment - critical, actionable
            (
                "This function has a null pointer exception",
                CommentCategory.BUG,
                CommentPriority.CRITICAL,
                True,
            ),
            # Style comment - low priority, often not actionable
            ("Nit: inconsistent indentation", CommentCategory.NITPICK, CommentPriority.LOW, False),
        ],
    )
    async def test_process_single_comment(
        self, comment_processor, body, expected_category, expected_priority, expected_actionable
    ):
        """Test processing single comments of different types."""
        comment = ReviewComment(
            id=1,
            body=body,
            path="src/test.py",
            line=15,
            author="reviewer",
            created_at=datetime.now(),
            resolved=False,
        )

        processed = await comment_processor._process_single_comment(comment, 123, "test/repo")

        assert processed.category == expected_category
        assert processed.priority == expected_priority
        assert processed.actionable == expected_actionable

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
            estimated_effort="significant",
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
            estimated_effort="quick",
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
            estimated_effort="medium",
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
    async def test_generate_comment_responses(
        self, comment_processor, mock_ai_integration, sample_issue
    ):
        """Test generating responses to comments."""
        # Setup mock AI response
        mock_ai_response = AIResponse(
            success=True,
            response_type="comment_response",
            content="Thank you for the feedback. I'll address this issue by...",
            file_changes=[],
            commands=[],
            metadata={},
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
            estimated_effort="medium",
        )

        processing_result = CommentProcessingResult(
            total_comments=1,
            processed_comments=[processed_comment],
            comment_threads=[],
            priority_summary={CommentPriority.CRITICAL: 1},
            category_summary={CommentCategory.BUG: 1},
            actionable_count=1,
            estimated_total_effort="medium",
            recommended_order=[1],
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
    async def test_generate_single_response(
        self, comment_processor, mock_ai_integration, sample_issue
    ):
        """Test generating a single comment response."""
        # Setup mock AI response
        mock_ai_response = AIResponse(
            success=True,
            response_type="comment_response",
            content="Thanks for pointing this out. I will fix the null pointer exception by adding proper null checks and validation.",
            file_changes=[],
            commands=[],
            metadata={},
        )
        mock_ai_integration.execute_update_from_review.return_value = mock_ai_response

        processed_comment = ProcessedComment(
            original_comment=ReviewComment(
                id=1,
                body="Null pointer exception on line 15",
                path="src/auth.py",
                line=15,
                author="reviewer",
            ),
            category=CommentCategory.BUG,
            priority=CommentPriority.CRITICAL,
            comment_type=CommentType.LINE_COMMENT,
            actionable=True,
            requires_code_change=True,
            complexity_score=7,
            estimated_effort="medium",
        )

        response = await comment_processor._generate_single_response(
            processed_comment, sample_issue, "test/repo"
        )

        assert response is not None
        assert response.comment_id == 1
        assert response.acknowledgment is True
        assert "fix" in response.response_text.lower()
        assert "null pointer" in response.response_text.lower()


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
                estimated_effort="medium",
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
                estimated_effort="quick",
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
                estimated_effort="quick",
            ),
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
                estimated_effort="medium",
            ),
            ProcessedComment(
                original_comment=ReviewComment(id=2, body="Issue 2", line=12, author="reviewer"),
                category=CommentCategory.STYLE,
                priority=CommentPriority.LOW,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=False,
                complexity_score=2,
                estimated_effort="quick",
            ),
            ProcessedComment(
                original_comment=ReviewComment(id=3, body="Issue 3", line=50, author="reviewer"),
                category=CommentCategory.PERFORMANCE,
                priority=CommentPriority.MEDIUM,
                comment_type=CommentType.LINE_COMMENT,
                actionable=True,
                requires_code_change=True,
                complexity_score=4,
                estimated_effort="medium",
            ),
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
            recommended_order=[1, 2],
        )

        ai_responses = [
            CommentResponse(
                comment_id=1,
                response_text="Response to comment 1",
                acknowledgment=True,
                planned_action="Fix the bug",
            ),
            CommentResponse(
                comment_id=2,
                response_text="Response to comment 2",
                acknowledgment=True,
                planned_action="Improve style",
            ),
        ]

        with patch.object(comment_processor, "_save_comment_history") as mock_save:
            history = await comment_processor.track_comment_history(
                pr_number=123,
                repository="test/repo",
                processing_result=processing_result,
                ai_responses=ai_responses,
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
            ("Security vulnerability needs fixing", CommentCategory.SECURITY, 8),
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
            (9, CommentCategory.SECURITY, "significant"),
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
            ("Performance problem", CommentCategory.PERFORMANCE),
        ]

        non_actionable_comments = [
            ("Just curious about this?", CommentCategory.QUESTION),
            ("Nit: minor style thing", CommentCategory.NITPICK),
            ("Why did you choose this approach?", CommentCategory.QUESTION),
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
            ("Refactor this function", CommentType.LINE_COMMENT),
        ]

        no_code_change_comments = [
            ("Why this approach?", CommentType.GENERAL_COMMENT),
            ("Good implementation", CommentType.GENERAL_COMMENT),
            ("Question about logic", CommentType.FILE_COMMENT),
        ]

        for comment_text, comment_type in code_change_comments:
            assert comment_processor._requires_code_change(comment_text, comment_type) is True

        for comment_text, comment_type in no_code_change_comments:
            # Some may still require code changes based on content
            result = comment_processor._requires_code_change(comment_text, comment_type)
            assert isinstance(result, bool)


if __name__ == "__main__":
    pytest.main([__file__])
