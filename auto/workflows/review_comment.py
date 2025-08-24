"""
Review comment processing and response workflows.

This module provides sophisticated comment analysis, categorization, and AI-powered
response generation for review feedback.
"""

import json
import re
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from ..integrations.ai import ClaudeIntegration
from ..integrations.github import GitHubIntegration
from ..models import Issue, ReviewComment
from ..utils.logger import get_logger

logger = get_logger(__name__)


class CommentCategory(str, Enum):
    """Categories for review comments."""

    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    CODE_QUALITY = "code_quality"
    STYLE = "style"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    SUGGESTION = "suggestion"
    QUESTION = "question"
    NITPICK = "nitpick"


class CommentPriority(str, Enum):
    """Priority levels for review comments."""

    CRITICAL = "critical"  # Must fix (bugs, security)
    HIGH = "high"  # Should fix (performance, major quality issues)
    MEDIUM = "medium"  # Nice to fix (style, minor issues)
    LOW = "low"  # Optional (nitpicks, questions)


class CommentType(str, Enum):
    """Types of review comments."""

    LINE_COMMENT = "line_comment"  # Specific to a line of code
    FILE_COMMENT = "file_comment"  # About entire file
    GENERAL_COMMENT = "general_comment"  # General PR comment
    SUGGESTION = "suggestion"  # GitHub suggestion format
    CHANGE_REQUEST = "change_request"  # Requires code changes


class ProcessedComment(BaseModel):
    """Processed review comment with analysis metadata."""

    original_comment: ReviewComment = Field(description="Original review comment")
    category: CommentCategory = Field(description="Comment category")
    priority: CommentPriority = Field(description="Comment priority")
    comment_type: CommentType = Field(description="Type of comment")
    actionable: bool = Field(description="Whether comment requires action")
    requires_code_change: bool = Field(description="Whether comment requires code modification")
    suggested_change: str | None = Field(
        default=None, description="Suggested code change if applicable"
    )
    keywords: list[str] = Field(default_factory=list, description="Extracted keywords")
    complexity_score: int = Field(description="Complexity score (1-10)", ge=1, le=10)
    estimated_effort: str = Field(description="Estimated effort (quick/medium/significant)")
    related_files: list[str] = Field(
        default_factory=list, description="Files that might be affected"
    )
    dependencies: list[int] = Field(
        default_factory=list, description="IDs of comments this depends on"
    )


class CommentResponse(BaseModel):
    """AI-generated response to a review comment."""

    comment_id: int = Field(description="ID of comment being responded to")
    response_text: str = Field(description="AI-generated response")
    acknowledgment: bool = Field(description="Whether comment is acknowledged")
    planned_action: str | None = Field(
        default=None, description="Planned action to address comment"
    )
    implementation_notes: str | None = Field(default=None, description="Implementation details")
    requires_discussion: bool = Field(
        default=False, description="Whether comment needs human discussion"
    )


class CommentThread(BaseModel):
    """Thread of related comments and responses."""

    thread_id: str = Field(description="Thread identifier")
    primary_comment: ProcessedComment = Field(description="Main comment in thread")
    related_comments: list[ProcessedComment] = Field(
        default_factory=list, description="Related comments"
    )
    responses: list[CommentResponse] = Field(
        default_factory=list, description="AI responses in thread"
    )
    resolved: bool = Field(default=False, description="Whether thread is resolved")
    resolution_summary: str | None = Field(default=None, description="Summary of resolution")


class CommentProcessingResult(BaseModel):
    """Result of comment processing analysis."""

    total_comments: int = Field(description="Total number of comments processed")
    processed_comments: list[ProcessedComment] = Field(description="All processed comments")
    comment_threads: list[CommentThread] = Field(description="Organized comment threads")
    priority_summary: dict[CommentPriority, int] = Field(description="Count by priority")
    category_summary: dict[CommentCategory, int] = Field(description="Count by category")
    actionable_count: int = Field(description="Number of actionable comments")
    estimated_total_effort: str = Field(description="Total estimated effort")
    recommended_order: list[int] = Field(description="Recommended order of addressing comments")


class CommentHistory(BaseModel):
    """History of comment processing and responses."""

    pr_number: int = Field(description="Pull request number")
    repository: str = Field(description="Repository name")
    processing_timestamp: datetime = Field(description="When comments were processed")
    original_comments_count: int = Field(description="Number of original comments")
    responses_generated: int = Field(description="Number of responses generated")
    comments_resolved: int = Field(description="Number of comments resolved")
    processing_result: CommentProcessingResult = Field(description="Processing analysis result")
    ai_responses: list[CommentResponse] = Field(description="Generated AI responses")


class ReviewCommentProcessor:
    """
    Sophisticated review comment processor for analyzing, categorizing, and responding to feedback.

    Provides intelligent comment analysis, response generation, and workflow orchestration.
    """

    def __init__(self, github_integration: GitHubIntegration, ai_integration: ClaudeIntegration):
        """Initialize comment processor with integrations."""
        self.github = github_integration
        self.ai = ai_integration
        self.logger = get_logger(f"{__name__}.ReviewCommentProcessor")

        # Comment analysis patterns
        self._bug_patterns = [
            r"\b(bug|error|broken|fail|crash|exception|null pointer|undefined|breaks)\b",
            r"\b(doesn\'t work|not working|incorrect|wrong)\b",
            r"\b(should be|expected|missing|forgot)\b",
        ]

        self._security_patterns = [
            r"\b(security|vulnerable|exploit|injection|xss|csrf|auth)\b",
            r"\b(sanitize|validate|escape|permission|access control)\b",
            r"\b(password|secret|token|key|credential)\b",
        ]

        self._performance_patterns = [
            r"\b(performance|slow|optimize|cache|memory|cpu|inefficient)\b",
            r"\b(n\+1|query|database|async|parallel|concurrent)\b",
            r"\b(bottleneck|scalability|load|latency)\b",
        ]

        self._style_patterns = [
            r"\b(style|format|naming|convention|consistent|inconsistent)\b",
            r"\b(indent|indentation|spacing|spaces|line length|long|camelCase|snake_case)\b",
            r"\b(typo|grammar|wrapped|wrap)\b",
        ]

        self._documentation_patterns = [
            r"\b(document|documentation|docstring|readme|comment|explain)\b",
            r"\b(add.*comment|missing.*comment|missing.*docstring)\b",
            r"\b(update.*readme|api.*documentation)\b",
        ]

    async def analyze_review_comments(
        self, pr_number: int, repository: str, comments: list[ReviewComment]
    ) -> CommentProcessingResult:
        """
        Analyze and categorize review comments with priority and complexity assessment.

        Args:
            pr_number: Pull request number
            repository: Repository name
            comments: List of review comments to analyze

        Returns:
            CommentProcessingResult with comprehensive analysis
        """
        self.logger.info(f"Analyzing {len(comments)} review comments for PR #{pr_number}")

        try:
            # Process each comment individually
            processed_comments = []
            for comment in comments:
                processed = await self._process_single_comment(comment, pr_number, repository)
                processed_comments.append(processed)

            # Organize into threads
            comment_threads = self._organize_comment_threads(processed_comments)

            # Generate priority and category summaries
            priority_summary = self._calculate_priority_summary(processed_comments)
            category_summary = self._calculate_category_summary(processed_comments)

            # Calculate metrics
            actionable_count = sum(1 for c in processed_comments if c.actionable)
            estimated_total_effort = self._estimate_total_effort(processed_comments)
            recommended_order = self._recommend_addressing_order(processed_comments)

            result = CommentProcessingResult(
                total_comments=len(comments),
                processed_comments=processed_comments,
                comment_threads=comment_threads,
                priority_summary=priority_summary,
                category_summary=category_summary,
                actionable_count=actionable_count,
                estimated_total_effort=estimated_total_effort,
                recommended_order=recommended_order,
            )

            self.logger.info(
                f"Comment analysis complete: {actionable_count}/{len(comments)} actionable, "
                f"effort: {estimated_total_effort}"
            )

            return result

        except Exception as e:
            self.logger.error(f"Failed to analyze review comments: {e}")
            raise

    async def generate_comment_responses(
        self, processing_result: CommentProcessingResult, issue: Issue, repository: str
    ) -> list[CommentResponse]:
        """
        Generate AI-powered responses to review comments.

        Args:
            processing_result: Result from comment analysis
            issue: Original issue context
            repository: Repository name

        Returns:
            List of AI-generated comment responses
        """
        self.logger.info(
            f"Generating responses for {processing_result.actionable_count} actionable comments"
        )

        try:
            responses = []

            # Process comments by priority order
            for comment_id in processing_result.recommended_order:
                comment = next(
                    (
                        c
                        for c in processing_result.processed_comments
                        if c.original_comment.id == comment_id
                    ),
                    None,
                )
                if not comment or not comment.actionable:
                    continue

                response = await self._generate_single_response(comment, issue, repository)
                if response:
                    responses.append(response)

            self.logger.info(f"Generated {len(responses)} comment responses")
            return responses

        except Exception as e:
            self.logger.error(f"Failed to generate comment responses: {e}")
            raise

    async def resolve_comment_threads(
        self, threads: list[CommentThread], repository: str, pr_number: int
    ) -> dict[str, bool]:
        """
        Process comment resolution with code changes.

        Args:
            threads: Comment threads to resolve
            repository: Repository name
            pr_number: Pull request number

        Returns:
            Dictionary mapping thread IDs to resolution status
        """
        self.logger.info(f"Resolving {len(threads)} comment threads for PR #{pr_number}")

        resolution_status = {}

        try:
            for thread in threads:
                thread_id = thread.thread_id
                self.logger.debug(f"Processing thread {thread_id}")

                # Determine if thread can be auto-resolved
                can_auto_resolve = self._can_auto_resolve_thread(thread)

                if can_auto_resolve:
                    # Generate resolution summary
                    resolution_summary = await self._generate_resolution_summary(thread)

                    # Mark thread as resolved
                    thread.resolved = True
                    thread.resolution_summary = resolution_summary

                    resolution_status[thread_id] = True
                    self.logger.info(f"Auto-resolved thread {thread_id}: {resolution_summary}")
                else:
                    resolution_status[thread_id] = False
                    self.logger.debug(f"Thread {thread_id} requires manual resolution")

            resolved_count = sum(1 for status in resolution_status.values() if status)
            self.logger.info(f"Resolved {resolved_count}/{len(threads)} comment threads")

            return resolution_status

        except Exception as e:
            self.logger.error(f"Failed to resolve comment threads: {e}")
            raise

    def prioritize_feedback(
        self, processed_comments: list[ProcessedComment]
    ) -> list[ProcessedComment]:
        """
        Sort review comments by criticality and complexity.

        Args:
            processed_comments: List of processed comments

        Returns:
            Comments sorted by priority and addressing order
        """
        self.logger.debug(f"Prioritizing {len(processed_comments)} comments")

        def priority_score(comment: ProcessedComment) -> tuple[int, int, int]:
            # Priority weights (lower number = higher priority)
            priority_weights = {
                CommentPriority.CRITICAL: 1,
                CommentPriority.HIGH: 2,
                CommentPriority.MEDIUM: 3,
                CommentPriority.LOW: 4,
            }

            # Category weights for tiebreaking
            category_weights = {
                CommentCategory.BUG: 1,
                CommentCategory.SECURITY: 2,
                CommentCategory.PERFORMANCE: 3,
                CommentCategory.CODE_QUALITY: 4,
                CommentCategory.TESTING: 5,
                CommentCategory.DOCUMENTATION: 6,
                CommentCategory.STYLE: 7,
                CommentCategory.SUGGESTION: 8,
                CommentCategory.QUESTION: 9,
                CommentCategory.NITPICK: 10,
            }

            return (
                priority_weights.get(comment.priority, 10),
                category_weights.get(comment.category, 10),
                comment.complexity_score,  # Lower complexity first for easier wins
            )

        sorted_comments = sorted(processed_comments, key=priority_score)

        self.logger.debug(
            f"Prioritization complete: "
            f"{sum(1 for c in sorted_comments if c.priority == CommentPriority.CRITICAL)} critical, "
            f"{sum(1 for c in sorted_comments if c.priority == CommentPriority.HIGH)} high priority"
        )

        return sorted_comments

    async def track_comment_history(
        self,
        pr_number: int,
        repository: str,
        processing_result: CommentProcessingResult,
        ai_responses: list[CommentResponse],
    ) -> CommentHistory:
        """
        Maintain detailed history of comment processing.

        Args:
            pr_number: Pull request number
            repository: Repository name
            processing_result: Comment processing results
            ai_responses: Generated AI responses

        Returns:
            CommentHistory with tracking information
        """
        self.logger.debug(f"Tracking comment history for PR #{pr_number}")

        try:
            history = CommentHistory(
                pr_number=pr_number,
                repository=repository,
                processing_timestamp=datetime.now(),
                original_comments_count=processing_result.total_comments,
                responses_generated=len(ai_responses),
                comments_resolved=sum(1 for t in processing_result.comment_threads if t.resolved),
                processing_result=processing_result,
                ai_responses=ai_responses,
            )

            # Save history to file (optional persistence)
            await self._save_comment_history(history)

            self.logger.info(f"Comment history tracked for PR #{pr_number}")
            return history

        except Exception as e:
            self.logger.error(f"Failed to track comment history: {e}")
            raise

    async def _process_single_comment(
        self, comment: ReviewComment, pr_number: int, repository: str
    ) -> ProcessedComment:
        """Process and analyze a single review comment."""
        try:
            # Categorize comment
            category = self._categorize_comment(comment.body)

            # Determine priority
            priority = self._determine_priority(comment.body, category)

            # Analyze comment type
            comment_type = self._analyze_comment_type(comment)

            # Check if actionable
            actionable = self._is_actionable(comment.body, category)

            # Check if requires code change
            requires_code_change = self._requires_code_change(comment.body, comment_type)

            # Extract suggested change if present
            suggested_change = self._extract_suggested_change(comment.body)

            # Extract keywords
            keywords = self._extract_keywords(comment.body)

            # Calculate complexity score
            complexity_score = self._calculate_complexity_score(comment.body, category)

            # Estimate effort
            estimated_effort = self._estimate_effort(complexity_score, category)

            # Identify related files
            related_files = self._identify_related_files(comment, pr_number, repository)

            return ProcessedComment(
                original_comment=comment,
                category=category,
                priority=priority,
                comment_type=comment_type,
                actionable=actionable,
                requires_code_change=requires_code_change,
                suggested_change=suggested_change,
                keywords=keywords,
                complexity_score=complexity_score,
                estimated_effort=estimated_effort,
                related_files=related_files,
                dependencies=[],  # Will be populated later if needed
            )

        except Exception as e:
            self.logger.error(f"Failed to process comment {comment.id}: {e}")
            # Return basic processed comment on failure
            return ProcessedComment(
                original_comment=comment,
                category=CommentCategory.SUGGESTION,
                priority=CommentPriority.MEDIUM,
                comment_type=CommentType.GENERAL_COMMENT,
                actionable=True,
                requires_code_change=False,
                complexity_score=5,
                estimated_effort="medium",
            )

    def _categorize_comment(self, comment_text: str) -> CommentCategory:
        """Categorize comment based on content analysis."""
        comment_lower = comment_text.lower()

        # Check for security first - highest priority
        for pattern in self._security_patterns:
            if re.search(pattern, comment_lower, re.IGNORECASE):
                return CommentCategory.SECURITY

        # Check for questions first - they might contain words like "explain" that could match documentation
        if re.search(r"\?|unclear|explain.*\?|why|how.*\?", comment_lower) or re.search(
            r"\b(why|how|what|where|when|can you explain|unclear)\b", comment_lower
        ):
            return CommentCategory.QUESTION

        # Check for testing early - test-related issues should be testing, not bugs
        if re.search(r"\b(test|spec|coverage|mock)\b", comment_lower):
            return CommentCategory.TESTING

        # Check for documentation context - override bug if clearly documentation-related
        has_doc_context = re.search(r"\b(readme|docs|docstring)\b", comment_lower)
        has_doc_indicators = any(
            re.search(pattern, comment_lower, re.IGNORECASE)
            for pattern in self._documentation_patterns
        )
        if has_doc_context or (
            has_doc_indicators and re.search(r"\b(document|documentation)\b", comment_lower)
        ):
            return CommentCategory.DOCUMENTATION

        # Check for nitpicks first - they override other categories like style
        if re.search(r"\b(nit|nitpick|minor|tiny)\b", comment_lower):
            return CommentCategory.NITPICK

        # Check for bugs and performance next - they have higher priority than style
        has_bug_indicators = any(
            re.search(pattern, comment_lower, re.IGNORECASE) for pattern in self._bug_patterns
        )
        has_performance_indicators = any(
            re.search(pattern, comment_lower, re.IGNORECASE)
            for pattern in self._performance_patterns
        )
        has_style_indicators = any(
            re.search(pattern, comment_lower, re.IGNORECASE) for pattern in self._style_patterns
        )

        # If it has both bug and performance indicators, check which takes priority
        if has_bug_indicators and has_performance_indicators:
            # Bug takes priority if it mentions breaking functionality
            if re.search(
                r"\b(break|broken|fail|crash|doesn\'t work|not working)\b|breaks functionality",
                comment_lower,
            ):
                return CommentCategory.BUG
            else:
                return CommentCategory.PERFORMANCE
        elif has_bug_indicators:
            return CommentCategory.BUG
        elif has_performance_indicators:
            return CommentCategory.PERFORMANCE

        # Check for style after performance/bug - style has lower priority
        if has_style_indicators:
            return CommentCategory.STYLE

        for pattern in self._documentation_patterns:
            if re.search(pattern, comment_lower, re.IGNORECASE):
                return CommentCategory.DOCUMENTATION

        # Additional category detection

        if re.search(r"\b(suggest|recommend|consider|maybe|could)\b", comment_lower):
            return CommentCategory.SUGGESTION

        return CommentCategory.CODE_QUALITY

    def _determine_priority(self, comment_text: str, category: CommentCategory) -> CommentPriority:
        """Determine comment priority based on content and category."""
        comment_lower = comment_text.lower()

        # Critical indicators
        if any(
            word in comment_lower
            for word in ["critical", "urgent", "blocking", "broken", "security"]
        ):
            return CommentPriority.CRITICAL

        if category == CommentCategory.BUG:
            return CommentPriority.CRITICAL

        if category == CommentCategory.SECURITY:
            return CommentPriority.CRITICAL

        # High priority indicators
        if any(word in comment_lower for word in ["important", "should", "must", "required"]):
            return CommentPriority.HIGH

        if category == CommentCategory.PERFORMANCE:
            return CommentPriority.HIGH

        # Low priority indicators
        if any(word in comment_lower for word in ["nit", "nitpick", "minor", "optional"]):
            return CommentPriority.LOW

        if category in [CommentCategory.NITPICK, CommentCategory.QUESTION]:
            return CommentPriority.LOW

        # Default to medium
        return CommentPriority.MEDIUM

    def _analyze_comment_type(self, comment: ReviewComment) -> CommentType:
        """Analyze the type of review comment."""
        if comment.line is not None:
            # Check for GitHub suggestion format
            if "```suggestion" in comment.body:
                return CommentType.SUGGESTION
            return CommentType.LINE_COMMENT

        if comment.path is not None:
            return CommentType.FILE_COMMENT

        # Check if it's a change request
        if any(
            word in comment.body.lower() for word in ["must", "required", "needs", "should fix"]
        ):
            return CommentType.CHANGE_REQUEST

        return CommentType.GENERAL_COMMENT

    def _is_actionable(self, comment_text: str, category: CommentCategory) -> bool:
        """Determine if comment requires action."""
        comment_lower = comment_text.lower()

        # Positive/praise comments are not actionable
        positive_indicators = [
            "great",
            "good",
            "nice",
            "excellent",
            "perfect",
            "love",
            "awesome",
            "well done",
            "looks good",
            "clean",
            "elegant",
            "solid",
            "impressive",
        ]
        if any(word in comment_lower for word in positive_indicators):
            # Unless they also contain actionable language
            if not any(
                word in comment_lower
                for word in ["but", "however", "should", "could", "might", "consider"]
            ):
                return False

        # Questions might not be actionable
        if category == CommentCategory.QUESTION and not any(
            word in comment_lower for word in ["should", "must", "fix", "change"]
        ):
            return False

        # Nitpicks are often not actionable
        if category == CommentCategory.NITPICK:
            return False

        # Everything else is generally actionable
        return True

    def _requires_code_change(self, comment_text: str, comment_type: CommentType) -> bool:
        """Determine if comment requires code modification."""
        if comment_type == CommentType.SUGGESTION:
            return True

        if comment_type == CommentType.CHANGE_REQUEST:
            return True

        comment_lower = comment_text.lower()

        # Check for positive/praise contexts first
        positive_contexts = [
            "great",
            "good",
            "nice",
            "excellent",
            "perfect",
            "well done",
            "looks good",
            "clean",
        ]
        if any(positive in comment_lower for positive in positive_contexts):
            return False

        # Directive change indicators with word boundaries
        change_patterns = [
            r"\bfix\b",
            r"\bchange\b",
            r"\bupdate\b",
            r"\bmodify\b",
            r"\brefactor\b",
            r"\bremove\b",
            r"\badd\b",
            r"\breplace\b",
            r"\bcorrect\b",
            r"\badjust\b",
            r"\bshould.*(?:fix|change|update|modify|refactor|remove|add|replace)\b",
        ]

        return any(re.search(pattern, comment_lower) for pattern in change_patterns)

    def _extract_suggested_change(self, comment_text: str) -> str | None:
        """Extract suggested code change from comment."""
        # Look for GitHub suggestion format
        suggestion_match = re.search(r"```suggestion\n(.*?)\n```", comment_text, re.DOTALL)
        if suggestion_match:
            return suggestion_match.group(1).strip()

        # Look for code blocks
        code_match = re.search(r"```(?:\w+)?\n(.*?)\n```", comment_text, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()

        return None

    def _extract_keywords(self, comment_text: str) -> list[str]:
        """Extract relevant keywords from comment."""
        # Simple keyword extraction
        keywords = []

        # Technical terms
        tech_terms = re.findall(
            r"\b(?:async|await|promise|callback|cache|database|api|http|json|xml|sql)\b",
            comment_text.lower(),
        )
        keywords.extend(tech_terms)

        # Code elements
        code_elements = re.findall(
            r"\b(?:function|method|class|variable|parameter|return|exception)\b",
            comment_text.lower(),
        )
        keywords.extend(code_elements)

        return list(set(keywords))

    def _calculate_complexity_score(self, comment_text: str, category: CommentCategory) -> int:
        """Calculate complexity score (1-10) for addressing the comment."""
        score = 5  # Base score

        # Category-based adjustments
        if category == CommentCategory.BUG:
            score += 2
        elif category == CommentCategory.SECURITY:
            score += 3
        elif category == CommentCategory.PERFORMANCE:
            score += 2
        elif category == CommentCategory.STYLE:
            score -= 2
        elif category == CommentCategory.NITPICK:
            score -= 3

        # Content-based adjustments
        comment_lower = comment_text.lower()
        if any(word in comment_lower for word in ["refactor", "redesign", "architecture"]):
            score += 3
        elif any(word in comment_lower for word in ["test", "coverage", "mock"]):
            score += 1
        elif any(word in comment_lower for word in ["typo", "spacing", "format"]):
            score -= 2

        # Length-based adjustment
        if len(comment_text) > 200:
            score += 1

        return max(1, min(10, score))

    def _estimate_effort(self, complexity_score: int, category: CommentCategory) -> str:
        """Estimate effort required to address comment."""
        if complexity_score <= 3:
            return "quick"
        elif complexity_score <= 6:
            return "medium"
        else:
            return "significant"

    def _identify_related_files(
        self, comment: ReviewComment, pr_number: int, repository: str
    ) -> list[str]:
        """Identify files that might be affected by addressing this comment."""
        related_files = []

        # Add the file the comment is on
        if comment.path:
            related_files.append(comment.path)

        # TODO: Add logic to identify related files based on comment content
        # This could include:
        # - Files mentioned in the comment
        # - Files that import/use the commented code
        # - Test files for the commented code

        return related_files

    def _organize_comment_threads(
        self, processed_comments: list[ProcessedComment]
    ) -> list[CommentThread]:
        """Organize comments into logical threads."""
        threads = []

        # Group by file path first
        file_groups: dict[str, list[ProcessedComment]] = {}
        general_comments = []

        for comment in processed_comments:
            if comment.original_comment.path:
                if comment.original_comment.path not in file_groups:
                    file_groups[comment.original_comment.path] = []
                file_groups[comment.original_comment.path].append(comment)
            else:
                general_comments.append(comment)

        # Create threads for each file
        for file_path, comments in file_groups.items():
            # Group by line number or create single thread per file
            if len(comments) == 1:
                thread = CommentThread(
                    thread_id=f"file_{file_path}_{comments[0].original_comment.id}",
                    primary_comment=comments[0],
                    related_comments=[],
                    responses=[],
                    resolved=False,
                )
                threads.append(thread)
            else:
                # Multiple comments in same file - group by proximity
                line_groups = self._group_comments_by_proximity(comments)
                for i, group in enumerate(line_groups):
                    thread = CommentThread(
                        thread_id=f"file_{file_path}_group_{i}",
                        primary_comment=group[0],
                        related_comments=group[1:],
                        responses=[],
                        resolved=False,
                    )
                    threads.append(thread)

        # Create threads for general comments
        for comment in general_comments:
            thread = CommentThread(
                thread_id=f"general_{comment.original_comment.id}",
                primary_comment=comment,
                related_comments=[],
                responses=[],
                resolved=False,
            )
            threads.append(thread)

        return threads

    def _group_comments_by_proximity(
        self, comments: list[ProcessedComment]
    ) -> list[list[ProcessedComment]]:
        """Group comments by line number proximity."""
        # Sort by line number
        sorted_comments = sorted(
            [c for c in comments if c.original_comment.line is not None],
            key=lambda c: c.original_comment.line or 0,
        )

        if not sorted_comments:
            return [comments]

        groups = []
        current_group = [sorted_comments[0]]

        for comment in sorted_comments[1:]:
            # Group comments within 10 lines of each other
            if (comment.original_comment.line or 0) - (
                current_group[-1].original_comment.line or 0
            ) <= 10:
                current_group.append(comment)
            else:
                groups.append(current_group)
                current_group = [comment]

        groups.append(current_group)

        # Add comments without line numbers to last group
        no_line_comments = [c for c in comments if c.original_comment.line is None]
        if no_line_comments:
            if groups:
                groups[-1].extend(no_line_comments)
            else:
                groups.append(no_line_comments)

        return groups

    def _calculate_priority_summary(
        self, processed_comments: list[ProcessedComment]
    ) -> dict[CommentPriority, int]:
        """Calculate summary of comments by priority."""
        summary = dict.fromkeys(CommentPriority, 0)
        for comment in processed_comments:
            summary[comment.priority] += 1
        return summary

    def _calculate_category_summary(
        self, processed_comments: list[ProcessedComment]
    ) -> dict[CommentCategory, int]:
        """Calculate summary of comments by category."""
        summary = dict.fromkeys(CommentCategory, 0)
        for comment in processed_comments:
            summary[comment.category] += 1
        return summary

    def _estimate_total_effort(self, processed_comments: list[ProcessedComment]) -> str:
        """Estimate total effort for addressing all comments."""
        effort_scores = {"quick": 1, "medium": 3, "significant": 7}
        total_score = sum(
            effort_scores.get(comment.estimated_effort, 3)
            for comment in processed_comments
            if comment.actionable
        )

        if total_score <= 5:
            return "quick"
        elif total_score <= 15:
            return "medium"
        else:
            return "significant"

    def _recommend_addressing_order(self, processed_comments: list[ProcessedComment]) -> list[int]:
        """Recommend order for addressing comments."""
        prioritized = self.prioritize_feedback(processed_comments)
        return [comment.original_comment.id for comment in prioritized if comment.actionable]

    async def _generate_single_response(
        self, comment: ProcessedComment, issue: Issue, repository: str
    ) -> CommentResponse | None:
        """Generate AI response for a single comment."""
        try:
            # Build context for AI response
            # TODO: Use this context for AI response generation
            _context = {
                "comment": comment.original_comment.body,
                "category": comment.category.value,
                "priority": comment.priority.value,
                "file_path": comment.original_comment.path,
                "line_number": comment.original_comment.line,
                "issue_title": issue.title,
                "issue_description": issue.description,
            }

            # Create prompt for response generation
            prompt = f"""Generate a professional response to this review comment:

Comment: {comment.original_comment.body}
Category: {comment.category.value}
Priority: {comment.priority.value}
File: {comment.original_comment.path or "General"}
Line: {comment.original_comment.line or "N/A"}

Context:
- Original Issue: {issue.title}
- Repository: {repository}

Please provide:
1. Acknowledgment of the feedback
2. Planned action to address the comment (if actionable)
3. Implementation approach (if code changes needed)
4. Any questions or clarifications needed

Keep the response professional, concise, and constructive."""

            # Get AI response (no worktree needed for comment responses)
            ai_result = await self.ai.execute_update_from_review(
                repository, prompt, worktree_path=None
            )

            if not ai_result.success:
                self.logger.warning(
                    f"Failed to generate response for comment {comment.original_comment.id}"
                )
                return None

            # Parse response content
            response_text = ai_result.content

            # Determine if acknowledgment is present
            acknowledgment = any(
                word in response_text.lower()
                for word in ["acknowledge", "thank", "thanks", "agree", "understand", "good point"]
            )

            # Extract planned action
            planned_action = self._extract_planned_action(response_text)

            # Extract implementation notes
            implementation_notes = self._extract_implementation_notes(response_text)

            # Check if requires discussion
            requires_discussion = any(
                phrase in response_text.lower()
                for phrase in ["discuss", "clarification", "question", "not sure", "unclear"]
            )

            return CommentResponse(
                comment_id=comment.original_comment.id,
                response_text=response_text,
                acknowledgment=acknowledgment,
                planned_action=planned_action,
                implementation_notes=implementation_notes,
                requires_discussion=requires_discussion,
            )

        except Exception as e:
            self.logger.error(
                f"Failed to generate response for comment {comment.original_comment.id}: {e}"
            )
            return None

    def _extract_planned_action(self, response_text: str) -> str | None:
        """Extract planned action from AI response."""
        # Look for action-oriented phrases
        action_patterns = [
            r"(?:will|plan to|going to|intend to)\s+([^.]+)",
            r"(?:action|approach|fix|solution):\s*([^.]+)",
            r"(?:to address this|to fix this|to resolve this),?\s+([^.]+)",
        ]

        for pattern in action_patterns:
            match = re.search(pattern, response_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _extract_implementation_notes(self, response_text: str) -> str | None:
        """Extract implementation details from AI response."""
        # Look for implementation-specific content
        impl_patterns = [
            r"(?:implementation|approach|method):\s*([^.\n]+)",
            r"(?:technically|specifically|details)[,:]?\s*([^.\n]+)",
            r"(?:by|through|using)\s+([^.\n]+)",
            r"(?:will be to|pattern[,:])\s*([^.\n]+)",
        ]

        for pattern in impl_patterns:
            match = re.search(pattern, response_text, re.IGNORECASE)
            if match:
                extracted = match.group(1).strip()
                if len(extracted) > 3:  # Ensure meaningful content
                    return extracted

        return None

    def _can_auto_resolve_thread(self, thread: CommentThread) -> bool:
        """Determine if a comment thread can be automatically resolved."""
        # Only auto-resolve if all comments in thread are low priority or questions
        all_comments = [thread.primary_comment] + thread.related_comments

        for comment in all_comments:
            if comment.priority in [CommentPriority.CRITICAL, CommentPriority.HIGH]:
                return False
            if comment.category == CommentCategory.BUG:
                return False
            if comment.requires_code_change:
                return False

        return True

    async def _generate_resolution_summary(self, thread: CommentThread) -> str:
        """Generate summary of thread resolution."""
        all_comments = [thread.primary_comment] + thread.related_comments

        if len(all_comments) == 1:
            comment = all_comments[0]
            return f"Addressed {comment.category.value} comment: {comment.original_comment.body[:100]}..."
        else:
            categories = list({c.category.value for c in all_comments})
            return f"Addressed {len(all_comments)} comments ({', '.join(categories)})"

    async def _save_comment_history(self, history: CommentHistory) -> None:
        """Save comment history to file (optional persistence)."""
        try:
            # Create history directory if it doesn't exist
            history_dir = Path(".auto/history/comments")
            history_dir.mkdir(parents=True, exist_ok=True)

            # Save history file
            history_file = (
                history_dir
                / f"pr_{history.pr_number}_{history.processing_timestamp.isoformat()}.json"
            )

            with open(history_file, "w") as f:
                json.dump(history.dict(), f, indent=2, default=str)

            self.logger.debug(f"Comment history saved to {history_file}")

        except Exception as e:
            self.logger.warning(f"Failed to save comment history: {e}")
