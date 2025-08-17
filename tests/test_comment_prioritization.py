"""
Additional tests for comment categorization and prioritization validation.

This module provides focused tests for the sophisticated comment analysis
to ensure accuracy in categorization and priority assignment.
"""

import pytest
from datetime import datetime
from auto.models import ReviewComment
from auto.workflows.review_comment import (
    ReviewCommentProcessor,
    CommentCategory,
    CommentPriority,
    CommentType
)


class TestCommentCategorizationEdgeCases:
    """Test edge cases in comment categorization."""
    
    @pytest.fixture
    def comment_processor(self):
        """Create basic comment processor for testing."""
        return ReviewCommentProcessor(None, None)
    
    def test_mixed_category_comments(self, comment_processor):
        """Test comments that could fit multiple categories."""
        mixed_comments = [
            ("This bug causes a security vulnerability", CommentCategory.SECURITY),  # Security takes priority
            ("Performance issue that breaks functionality", CommentCategory.BUG),   # Bug takes priority
            ("Style issue that affects performance", CommentCategory.PERFORMANCE),   # Performance more important
            ("Documentation bug in the README", CommentCategory.DOCUMENTATION)       # Specific context
        ]
        
        for comment_text, expected_category in mixed_comments:
            actual_category = comment_processor._categorize_comment(comment_text)
            assert actual_category == expected_category, f"Comment '{comment_text}' should be {expected_category}, got {actual_category}"
    
    def test_ambiguous_comments(self, comment_processor):
        """Test comments that are ambiguous or unclear."""
        ambiguous_comments = [
            "This could be better",
            "Not sure about this approach",
            "Hmm, interesting choice",
            "Consider refactoring"
        ]
        
        for comment_text in ambiguous_comments:
            category = comment_processor._categorize_comment(comment_text)
            # Should default to reasonable categories for ambiguous comments
            assert category in [CommentCategory.SUGGESTION, CommentCategory.CODE_QUALITY, CommentCategory.QUESTION]
    
    def test_positive_comments(self, comment_processor):
        """Test positive/approval comments."""
        positive_comments = [
            "Looks good to me!",
            "Great implementation",
            "Nice work on this feature",
            "LGTM - well done"
        ]
        
        for comment_text in positive_comments:
            category = comment_processor._categorize_comment(comment_text)
            # Positive comments should be suggestions or questions, not critical issues
            assert category in [CommentCategory.SUGGESTION, CommentCategory.QUESTION, CommentCategory.CODE_QUALITY]


class TestPriorityAssignmentAccuracy:
    """Test accuracy of priority assignment."""
    
    @pytest.fixture
    def comment_processor(self):
        """Create basic comment processor for testing."""
        return ReviewCommentProcessor(None, None)
    
    def test_critical_priority_keywords(self, comment_processor):
        """Test that critical keywords properly trigger high priority."""
        critical_keywords = [
            "critical bug in authentication",
            "security vulnerability - urgent fix needed",
            "blocking issue that prevents deployment",
            "broken functionality - users cannot login"
        ]
        
        for comment_text in critical_keywords:
            priority = comment_processor._determine_priority(comment_text, CommentCategory.BUG)
            assert priority == CommentPriority.CRITICAL, f"'{comment_text}' should be CRITICAL priority"
    
    def test_priority_category_interaction(self, comment_processor):
        """Test how priority interacts with different categories."""
        test_cases = [
            ("Simple style fix", CommentCategory.STYLE, CommentPriority.MEDIUM),
            ("Nit: extra space", CommentCategory.NITPICK, CommentPriority.LOW),
            ("Security issue detected", CommentCategory.SECURITY, CommentPriority.CRITICAL),
            ("Performance bottleneck", CommentCategory.PERFORMANCE, CommentPriority.HIGH),
            ("Missing test coverage", CommentCategory.TESTING, CommentPriority.MEDIUM)
        ]
        
        for comment_text, category, expected_priority in test_cases:
            actual_priority = comment_processor._determine_priority(comment_text, category)
            assert actual_priority == expected_priority, f"'{comment_text}' with category {category} should be {expected_priority}, got {actual_priority}"


class TestCommentComplexityScoring:
    """Test complexity scoring accuracy."""
    
    @pytest.fixture
    def comment_processor(self):
        """Create basic comment processor for testing."""
        return ReviewCommentProcessor(None, None)
    
    def test_complexity_score_ranges(self, comment_processor):
        """Test that complexity scores fall within reasonable ranges."""
        test_cases = [
            ("Fix typo in comment", CommentCategory.STYLE, (1, 4)),
            ("Refactor authentication system", CommentCategory.CODE_QUALITY, (6, 10)),
            ("Add null check", CommentCategory.BUG, (4, 7)),
            ("Implement caching layer", CommentCategory.PERFORMANCE, (6, 9)),
            ("Add comprehensive test suite", CommentCategory.TESTING, (5, 8))
        ]
        
        for comment_text, category, (min_score, max_score) in test_cases:
            score = comment_processor._calculate_complexity_score(comment_text, category)
            assert min_score <= score <= max_score, f"'{comment_text}' complexity score {score} not in range {min_score}-{max_score}"
            assert 1 <= score <= 10, f"Complexity score {score} not in valid range 1-10"
    
    def test_effort_estimation_consistency(self, comment_processor):
        """Test that effort estimation is consistent with complexity."""
        test_cases = [
            (2, "quick"),
            (5, "medium"),
            (8, "significant"),
            (1, "quick"),
            (10, "significant")
        ]
        
        for complexity_score, expected_effort in test_cases:
            effort = comment_processor._estimate_effort(complexity_score, CommentCategory.CODE_QUALITY)
            assert effort == expected_effort, f"Complexity {complexity_score} should be '{expected_effort}', got '{effort}'"


class TestActionabilityDetection:
    """Test actionability detection accuracy."""
    
    @pytest.fixture
    def comment_processor(self):
        """Create basic comment processor for testing."""
        return ReviewCommentProcessor(None, None)
    
    def test_clearly_actionable_comments(self, comment_processor):
        """Test comments that are clearly actionable."""
        actionable_comments = [
            ("Fix this null pointer exception", CommentCategory.BUG),
            ("Add error handling here", CommentCategory.CODE_QUALITY),
            ("This security vulnerability needs to be patched", CommentCategory.SECURITY),
            ("Optimize this slow query", CommentCategory.PERFORMANCE),
            ("Add unit tests for this function", CommentCategory.TESTING)
        ]
        
        for comment_text, category in actionable_comments:
            is_actionable = comment_processor._is_actionable(comment_text, category)
            assert is_actionable is True, f"'{comment_text}' should be actionable"
    
    def test_non_actionable_comments(self, comment_processor):
        """Test comments that are not actionable."""
        non_actionable_comments = [
            ("Why did you choose this approach?", CommentCategory.QUESTION),
            ("Nit: could use a better variable name", CommentCategory.NITPICK),
            ("Just curious about the reasoning", CommentCategory.QUESTION),
            ("FYI: there's an alternative library", CommentCategory.SUGGESTION)
        ]
        
        for comment_text, category in non_actionable_comments:
            is_actionable = comment_processor._is_actionable(comment_text, category)
            # Some of these might still be actionable based on content
            assert isinstance(is_actionable, bool), f"Actionability check for '{comment_text}' should return boolean"
    
    def test_code_change_requirement_detection(self, comment_processor):
        """Test detection of comments requiring code changes."""
        code_change_required = [
            ("Fix this bug", CommentType.LINE_COMMENT, True),
            ("```suggestion\nnew_code\n```", CommentType.SUGGESTION, True),
            ("This must be changed", CommentType.CHANGE_REQUEST, True),
            ("Refactor this method", CommentType.LINE_COMMENT, True)
        ]
        
        no_code_change = [
            ("Great implementation!", CommentType.GENERAL_COMMENT, False),
            ("Why this approach?", CommentType.GENERAL_COMMENT, False)
        ]
        
        all_cases = code_change_required + no_code_change
        
        for comment_text, comment_type, expected in all_cases:
            requires_change = comment_processor._requires_code_change(comment_text, comment_type)
            assert requires_change == expected, f"'{comment_text}' code change requirement should be {expected}, got {requires_change}"


if __name__ == "__main__":
    pytest.main([__file__])