"""Tests for merge conflict handling functionality.

This module tests the comprehensive merge conflict handling system including
AI-assisted resolution guidance and Rich console output.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from auto.integrations.ai import AIResponse
from auto.models import (
    ConflictComplexity,
    ConflictDetail,
    ConflictResolution,
    ConflictType,
    GitHubRepository,
    ResolutionSuggestion,
)
from auto.workflows.merge_conflicts import (
    MergeConflictError,
    _analyze_conflict_markers,
    _analyze_file_conflict,
    _calculate_complexity_score,
    _determine_priority_order,
    _estimate_resolution_time,
    _extract_conflicted_files,
    _generate_ai_resolution_suggestions,
    _generate_conflict_summary,
    _generate_fallback_suggestions,
    _generate_resolution_report,
    _get_pr_context,
    _handle_merge_conflicts,
    _parse_conflict_details,
    get_conflict_details,
    handle_merge_conflicts,
)
from auto.utils.shell import CommandResult


class TestMergeConflictHandling:
    """Test suite for comprehensive merge conflict handling."""

    @pytest.fixture
    def sample_repository(self):
        """Sample repository for testing."""
        return GitHubRepository(
            owner="test-owner",
            name="test-repo",
            default_branch="main"
        )

    @pytest.fixture
    def sample_conflict_details(self):
        """Sample conflict details from git output."""
        return """UU src/main.py
AA tests/test_feature.py
both modified:   README.md
both added:      new_file.txt"""

    @pytest.fixture
    def sample_file_content_with_conflicts(self):
        """Sample file content with merge conflict markers."""
        return """def hello_world():
<<<<<<< HEAD
    print("Hello from main branch")
    return "main"
=======
    print("Hello from feature branch")
    return "feature"
>>>>>>> feature-branch
    
def other_function():
    return "unchanged"
"""

    @pytest.fixture
    def mock_pr_context(self):
        """Mock PR context data."""
        return {
            "number": 123,
            "title": "Add new feature",
            "description": "This PR adds a new feature with tests",
            "files_changed": ["src/main.py", "tests/test_feature.py", "README.md"],
            "base_branch": "main",
            "head_branch": "feature-branch"
        }

    @pytest.fixture
    def mock_ai_response(self):
        """Mock AI response for conflict analysis."""
        return AIResponse(
            success=True,
            response_type="conflict_analysis",
            content="""# Merge Conflict Analysis

## File: src/main.py
- **Type**: Content conflict
- **Complexity**: Simple
- **Resolution**: Choose the feature branch implementation as it includes proper error handling

## Recommended Actions:
1. Review each conflict carefully
2. Choose feature branch changes for src/main.py
3. Merge both versions for README.md
4. Test all changes thoroughly""",
            file_changes=[],
            commands=[],
            metadata={}
        )

    async def test_handle_merge_conflicts_success(
        self, sample_repository, sample_conflict_details, mock_pr_context
    ):
        """Test successful merge conflict handling with AI assistance."""
        with patch("auto.workflows.merge_conflicts._get_pr_context") as mock_get_context, \
             patch("auto.workflows.merge_conflicts._parse_conflict_details") as mock_parse, \
             patch("auto.workflows.merge_conflicts._generate_ai_resolution_suggestions") as mock_ai, \
             patch("auto.workflows.merge_conflicts._display_conflict_analysis") as mock_display:

            # Setup mocks
            mock_get_context.return_value = mock_pr_context
            
            mock_conflicts = [
                ConflictDetail(
                    file_path="src/main.py",
                    conflict_type=ConflictType.CONTENT,
                    complexity=ConflictComplexity.SIMPLE,
                    description="Content conflict in src/main.py",
                    line_numbers=[2, 3, 4, 5, 6, 7]
                ),
                ConflictDetail(
                    file_path="README.md",
                    conflict_type=ConflictType.CONTENT,
                    complexity=ConflictComplexity.MODERATE,
                    description="Content conflict in README.md",
                    line_numbers=[10, 11, 12]
                )
            ]
            mock_parse.return_value = mock_conflicts

            mock_suggestions = [
                ResolutionSuggestion(
                    file_path="src/main.py",
                    suggested_resolution="Choose feature branch implementation",
                    confidence=0.9,
                    rationale="Feature branch has better error handling",
                    manual_steps=["Open file", "Choose feature version", "Remove markers"]
                )
            ]
            
            mock_ai.return_value = {
                "suggestions": mock_suggestions,
                "manual_steps": ["Review conflicts", "Test changes", "Commit resolution"],
                "ai_response": "Detailed AI analysis"
            }

            # Test the function
            result = await _handle_merge_conflicts(
                pr_number=123,
                repository=sample_repository,
                conflict_details=sample_conflict_details
            )

            # Verify result structure
            assert isinstance(result, ConflictResolution)
            assert len(result.conflicts_detected) == 2
            assert len(result.resolution_suggestions) == 1
            assert result.ai_assistance_available is True
            assert result.estimated_resolution_time > 0
            assert 0.0 <= result.complexity_score <= 10.0
            assert len(result.priority_order) == 2
            assert result.conflict_summary
            assert result.resolution_report

            # Verify mocks were called
            mock_get_context.assert_called_once_with(123, sample_repository)
            mock_parse.assert_called_once_with(sample_conflict_details, sample_repository)
            mock_ai.assert_called_once()
            mock_display.assert_called_once_with(result)

    async def test_handle_merge_conflicts_no_conflicts(self, sample_repository):
        """Test handling when no conflicts are detected."""
        with patch("auto.workflows.merge_conflicts._parse_conflict_details") as mock_parse:
            mock_parse.return_value = []

            result = await _handle_merge_conflicts(
                pr_number=123,
                repository=sample_repository,
                conflict_details=""
            )

            assert isinstance(result, ConflictResolution)
            assert len(result.conflicts_detected) == 0
            assert result.ai_assistance_available is False
            assert result.conflict_summary == "No conflicts detected in provided details"

    async def test_handle_merge_conflicts_error_handling(self, sample_repository):
        """Test error handling in merge conflict analysis."""
        with patch("auto.workflows.merge_conflicts._parse_conflict_details") as mock_parse:
            mock_parse.side_effect = Exception("Parse error")

            result = await _handle_merge_conflicts(
                pr_number=123,
                repository=sample_repository,
                conflict_details="invalid"
            )

            assert isinstance(result, ConflictResolution)
            assert len(result.conflicts_detected) == 0
            assert result.ai_assistance_available is False
            assert "Parse error" in result.conflict_summary
            assert result.complexity_score == 8.0  # Error fallback score

    def test_extract_conflicted_files(self, sample_conflict_details):
        """Test extraction of conflicted files from git output."""
        files = _extract_conflicted_files(sample_conflict_details)
        
        expected_files = ["src/main.py", "tests/test_feature.py", "README.md", "new_file.txt"]
        assert len(files) == len(expected_files)
        for expected_file in expected_files:
            assert expected_file in files

    def test_extract_conflicted_files_various_formats(self):
        """Test extraction with various git output formats."""
        git_outputs = [
            "UU file1.py",
            "AA file2.py", 
            "DD file3.py",
            "	both modified:   file4.py",
            "	both added:      file5.py",
            "	both deleted:    file6.py"
        ]
        
        for git_output in git_outputs:
            files = _extract_conflicted_files(git_output)
            assert len(files) == 1
            assert files[0] in ["file1.py", "file2.py", "file3.py", "file4.py", "file5.py", "file6.py"]

    def test_analyze_conflict_markers(self, sample_file_content_with_conflicts):
        """Test analysis of conflict markers in file content."""
        conflict_type, complexity, line_numbers, ours_content, theirs_content = \
            _analyze_conflict_markers(sample_file_content_with_conflicts)

        assert conflict_type == ConflictType.CONTENT
        assert complexity == ConflictComplexity.SIMPLE
        assert len(line_numbers) > 0
        assert ours_content is not None
        assert theirs_content is not None
        assert "main branch" in ours_content
        assert "feature branch" in theirs_content

    def test_analyze_conflict_markers_no_conflicts(self):
        """Test analysis when no conflict markers are present."""
        content = """def hello_world():
    print("Hello world")
    return "hello"
"""
        
        conflict_type, complexity, line_numbers, ours_content, theirs_content = \
            _analyze_conflict_markers(content)

        assert conflict_type == ConflictType.CONTENT
        assert complexity == ConflictComplexity.SIMPLE
        assert len(line_numbers) == 0
        assert ours_content is None
        assert theirs_content is None

    def test_analyze_conflict_markers_complex_conflicts(self):
        """Test analysis of complex conflicts with multiple sections."""
        content = """def function1():
<<<<<<< HEAD
    print("version 1 line 1")
    print("version 1 line 2")
    print("version 1 line 3")
=======
    print("version 2 line 1")
    print("version 2 line 2")
    print("version 2 line 3")
>>>>>>> branch

def function2():
    print("no conflict")

def function3():
<<<<<<< HEAD
    return "main implementation"
=======
    return "feature implementation"
>>>>>>> branch
"""
        
        conflict_type, complexity, line_numbers, ours_content, theirs_content = \
            _analyze_conflict_markers(content)

        assert conflict_type == ConflictType.CONTENT
        assert complexity in [ConflictComplexity.MODERATE, ConflictComplexity.SIMPLE]
        assert len(line_numbers) > 6  # Multiple conflict sections

    async def test_analyze_file_conflict_success(self, sample_repository, sample_file_content_with_conflicts):
        """Test successful file conflict analysis."""
        with patch("auto.workflows.merge_conflicts.run_command") as mock_run:
            mock_run.return_value = CommandResult(
                returncode=0,
                stdout=sample_file_content_with_conflicts,
                stderr=""
            )

            result = await _analyze_file_conflict("src/main.py", sample_repository)

            assert isinstance(result, ConflictDetail)
            assert result.file_path == "src/main.py"
            assert result.conflict_type == ConflictType.CONTENT
            assert result.complexity == ConflictComplexity.SIMPLE
            assert len(result.line_numbers) > 0
            assert result.ours_content is not None
            assert result.theirs_content is not None

    async def test_analyze_file_conflict_file_not_found(self, sample_repository):
        """Test file conflict analysis when file cannot be read."""
        with patch("auto.workflows.merge_conflicts.run_command") as mock_run:
            mock_run.return_value = CommandResult(
                returncode=1,
                stdout="",
                stderr="cat: src/main.py: No such file or directory"
            )

            result = await _analyze_file_conflict("src/main.py", sample_repository)

            assert isinstance(result, ConflictDetail)
            assert result.file_path == "src/main.py"
            assert result.conflict_type == ConflictType.DELETE
            assert result.complexity == ConflictComplexity.MODERATE

    async def test_get_pr_context_success(self, sample_repository):
        """Test successful PR context retrieval."""
        mock_pr_data = {
            "title": "Add new feature",
            "body": "This PR adds a new feature",
            "files": [{"path": "src/main.py"}, {"path": "README.md"}],
            "baseRefName": "main",
            "headRefName": "feature-branch"
        }

        with patch("auto.workflows.merge_conflicts.run_command") as mock_run:
            mock_run.return_value = CommandResult(
                returncode=0,
                stdout=json.dumps(mock_pr_data),
                stderr=""
            )

            result = await _get_pr_context(123, sample_repository)

            assert result["number"] == 123
            assert result["title"] == "Add new feature"
            assert result["description"] == "This PR adds a new feature"
            assert len(result["files_changed"]) == 2
            assert result["base_branch"] == "main"
            assert result["head_branch"] == "feature-branch"

    async def test_get_pr_context_error(self, sample_repository):
        """Test PR context retrieval with errors."""
        with patch("auto.workflows.merge_conflicts.run_command") as mock_run:
            mock_run.return_value = CommandResult(
                returncode=1,
                stdout="",
                stderr="Error: PR not found"
            )

            result = await _get_pr_context(123, sample_repository)

            assert result["number"] == 123
            assert len(result) == 1  # Only number field present

    async def test_generate_ai_resolution_suggestions_success(self, sample_repository, mock_ai_response):
        """Test successful AI resolution suggestion generation."""
        conflicts = [
            ConflictDetail(
                file_path="src/main.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.SIMPLE,
                description="Content conflict in src/main.py",
                line_numbers=[2, 3, 4]
            )
        ]

        with patch("auto.config.get_config") as mock_config, \
             patch("auto.integrations.ai.ClaudeIntegration") as mock_integration_class:

            # Setup mock AI integration
            mock_integration = MagicMock()
            mock_integration.analyze_merge_conflicts = AsyncMock(return_value=mock_ai_response)
            mock_integration_class.return_value = mock_integration

            # Setup mock config
            mock_config.return_value.ai = MagicMock()

            result = await _generate_ai_resolution_suggestions(
                conflict_details="sample conflicts",
                pr_context={"number": 123},
                repository=sample_repository,
                parsed_conflicts=conflicts
            )

            assert "suggestions" in result
            assert "manual_steps" in result
            assert "ai_response" in result
            assert len(result["suggestions"]) == 1
            assert isinstance(result["suggestions"][0], ResolutionSuggestion)

    async def test_generate_ai_resolution_suggestions_ai_failure(self, sample_repository):
        """Test AI resolution suggestion generation when AI fails."""
        conflicts = [
            ConflictDetail(
                file_path="src/main.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.SIMPLE,
                description="Content conflict in src/main.py",
                line_numbers=[2, 3, 4]
            )
        ]

        failed_ai_response = AIResponse(
            success=False,
            response_type="conflict_analysis",
            content="AI analysis failed",
            file_changes=[],
            commands=[],
            metadata={}
        )

        with patch("auto.config.get_config") as mock_config, \
             patch("auto.integrations.ai.ClaudeIntegration") as mock_integration_class:

            mock_integration = MagicMock()
            mock_integration.analyze_merge_conflicts = AsyncMock(return_value=failed_ai_response)
            mock_integration_class.return_value = mock_integration
            mock_config.return_value.ai = MagicMock()

            result = await _generate_ai_resolution_suggestions(
                conflict_details="sample conflicts",
                pr_context={"number": 123},
                repository=sample_repository,
                parsed_conflicts=conflicts
            )

            assert "suggestions" in result
            assert "manual_steps" in result
            assert result["ai_response"] == "AI analysis unavailable"
            assert len(result["suggestions"]) == 1  # Fallback suggestion

    def test_calculate_complexity_score(self):
        """Test complexity score calculation."""
        conflicts = [
            ConflictDetail(
                file_path="file1.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.SIMPLE,
                description="Simple conflict",
                line_numbers=[]
            ),
            ConflictDetail(
                file_path="file2.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.COMPLEX,
                description="Complex conflict",
                line_numbers=[]
            ),
            ConflictDetail(
                file_path="file3.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.CRITICAL,
                description="Critical conflict",
                line_numbers=[]
            )
        ]

        score = _calculate_complexity_score(conflicts)
        assert 0.0 <= score <= 10.0
        assert score > 1.0  # Should be higher due to complex/critical conflicts

    def test_calculate_complexity_score_empty(self):
        """Test complexity score calculation with no conflicts."""
        score = _calculate_complexity_score([])
        assert score == 0.0

    def test_estimate_resolution_time(self):
        """Test resolution time estimation."""
        conflicts = [
            ConflictDetail(
                file_path="file1.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.SIMPLE,
                description="Simple conflict",
                line_numbers=[]
            )
        ]

        time = _estimate_resolution_time(conflicts, 2.0)
        assert time >= 5  # Minimum time
        assert isinstance(time, int)

    def test_determine_priority_order(self):
        """Test conflict priority order determination."""
        conflicts = [
            ConflictDetail(
                file_path="simple.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.SIMPLE,
                description="Simple conflict",
                line_numbers=[]
            ),
            ConflictDetail(
                file_path="critical.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.CRITICAL,
                description="Critical conflict",
                line_numbers=[]
            ),
            ConflictDetail(
                file_path="moderate.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.MODERATE,
                description="Moderate conflict",
                line_numbers=[]
            )
        ]

        priority_order = _determine_priority_order(conflicts)
        
        assert len(priority_order) == 3
        # Critical should come first
        assert priority_order[0] == "critical.py"

    def test_generate_conflict_summary(self):
        """Test conflict summary generation."""
        conflicts = [
            ConflictDetail(
                file_path="file1.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.SIMPLE,
                description="Simple conflict",
                line_numbers=[]
            ),
            ConflictDetail(
                file_path="file2.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.SIMPLE,
                description="Simple conflict",
                line_numbers=[]
            )
        ]

        summary = _generate_conflict_summary(conflicts)
        assert "2 merge conflict(s) detected" in summary
        assert "2 simple" in summary

    def test_generate_conflict_summary_empty(self):
        """Test conflict summary generation with no conflicts."""
        summary = _generate_conflict_summary([])
        assert summary == "No merge conflicts detected"

    def test_generate_resolution_report(self):
        """Test resolution report generation."""
        conflicts = [
            ConflictDetail(
                file_path="src/main.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.MODERATE,
                description="Content conflict in main.py",
                line_numbers=[1, 2, 3]
            )
        ]

        ai_response = {"ai_response": "Detailed AI analysis of conflicts"}

        report = _generate_resolution_report(conflicts, ai_response)
        
        assert "# Merge Conflict Resolution Report" in report
        assert "**Total Conflicts:** 1" in report
        assert "## Conflict 1: src/main.py" in report
        assert "- **Type:** content" in report
        assert "- **Complexity:** moderate" in report
        assert "## AI Analysis" in report
        assert "Detailed AI analysis of conflicts" in report

    def test_generate_fallback_suggestions(self):
        """Test fallback suggestion generation."""
        conflicts = [
            ConflictDetail(
                file_path="src/main.py",
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.SIMPLE,
                description="Content conflict",
                line_numbers=[]
            )
        ]

        suggestions = _generate_fallback_suggestions(conflicts)
        
        assert len(suggestions) == 1
        assert isinstance(suggestions[0], ResolutionSuggestion)
        assert suggestions[0].file_path == "src/main.py"
        assert suggestions[0].confidence == 0.6
        assert "fallback" in suggestions[0].rationale.lower()

    # Legacy compatibility tests
    async def test_handle_merge_conflicts_legacy_compatibility(self):
        """Test legacy handle_merge_conflicts function."""
        with patch("auto.workflows.merge_conflicts._get_pr_info") as mock_pr_info, \
             patch("auto.workflows.merge_conflicts._handle_merge_conflicts") as mock_new_handler:

            # Setup mocks
            mock_pr_info.return_value = {"mergeable": False}
            
            mock_resolution = ConflictResolution(
                conflicts_detected=[
                    ConflictDetail(
                        file_path="src/main.py",
                        conflict_type=ConflictType.CONTENT,
                        complexity=ConflictComplexity.SIMPLE,
                        description="Content conflict in src/main.py",
                        line_numbers=[]
                    )
                ],
                resolution_suggestions=[],
                manual_steps=[],
                ai_assistance_available=True,
                estimated_resolution_time=10,
                complexity_score=2.0,
                priority_order=["src/main.py"],
                conflict_summary="1 conflict detected",
                resolution_report="Test report"
            )
            mock_new_handler.return_value = mock_resolution

            with patch("auto.workflows.merge_conflicts._get_detailed_conflict_info") as mock_details:
                mock_details.return_value = "UU src/main.py"

                result = await handle_merge_conflicts(123, "owner", "repo")

                assert result is not None
                assert len(result) == 1
                assert "Content conflict in src/main.py" in result

    async def test_handle_merge_conflicts_no_conflicts_legacy(self):
        """Test legacy function when no conflicts exist."""
        with patch("auto.workflows.merge_conflicts._get_pr_info") as mock_pr_info:
            mock_pr_info.return_value = {"mergeable": True}

            result = await handle_merge_conflicts(123, "owner", "repo")

            assert result is None

    async def test_get_conflict_details_legacy_compatibility(self):
        """Test legacy get_conflict_details function."""
        with patch("auto.workflows.merge_conflicts._handle_merge_conflicts") as mock_handler:
            mock_resolution = ConflictResolution(
                conflicts_detected=[
                    ConflictDetail(
                        file_path="file1.py",
                        conflict_type=ConflictType.CONTENT,
                        complexity=ConflictComplexity.SIMPLE,
                        description="Conflict 1",
                        line_numbers=[]
                    ),
                    ConflictDetail(
                        file_path="file2.py",
                        conflict_type=ConflictType.CONTENT,
                        complexity=ConflictComplexity.MODERATE,
                        description="Conflict 2",
                        line_numbers=[]
                    )
                ],
                resolution_suggestions=[],
                manual_steps=[],
                ai_assistance_available=True,
                estimated_resolution_time=15,
                complexity_score=3.0,
                priority_order=["file1.py", "file2.py"],
                conflict_summary="2 conflicts detected",
                resolution_report="Test report"
            )
            mock_handler.return_value = mock_resolution

            with patch("auto.workflows.merge_conflicts._get_detailed_conflict_info") as mock_details:
                mock_details.return_value = "UU file1.py\nUU file2.py"

                result = await get_conflict_details(123, "owner", "repo")

                assert len(result) == 2
                assert "Conflict 1" in result
                assert "Conflict 2" in result


@pytest.mark.asyncio
class TestMergeConflictIntegration:
    """Integration tests for merge conflict handling."""

    async def test_full_conflict_analysis_workflow(self):
        """Test the full conflict analysis workflow end-to-end."""
        # This would be an integration test with real git repositories
        # For now, we'll create a comprehensive mock test
        
        repository = GitHubRepository(owner="test", name="repo")
        conflict_details = """UU src/main.py
AA README.md"""

        # Mock all external dependencies
        with patch("auto.workflows.merge_conflicts._parse_conflict_details") as mock_parse, \
             patch("auto.workflows.merge_conflicts._get_pr_context") as mock_context, \
             patch("auto.workflows.merge_conflicts._generate_ai_resolution_suggestions") as mock_ai, \
             patch("auto.workflows.merge_conflicts._display_conflict_analysis"):

            # Setup comprehensive mocks
            mock_conflicts = [
                ConflictDetail(
                    file_path="src/main.py",
                    conflict_type=ConflictType.CONTENT,
                    complexity=ConflictComplexity.MODERATE,
                    description="Content conflict with complex merge logic",
                    ours_content="def main():\n    print('version 1')",
                    theirs_content="def main():\n    print('version 2')",
                    line_numbers=[5, 6, 7, 8, 9, 10],
                    metadata={"file_size": 150}
                ),
                ConflictDetail(
                    file_path="README.md",
                    conflict_type=ConflictType.ADD_ADD,
                    complexity=ConflictComplexity.SIMPLE,
                    description="Both branches added the same file",
                    line_numbers=[1, 2, 3],
                    metadata={"file_size": 50}
                )
            ]
            mock_parse.return_value = mock_conflicts

            mock_context.return_value = {
                "number": 456,
                "title": "Feature: Advanced conflict resolution",
                "description": "Implements comprehensive conflict resolution",
                "files_changed": ["src/main.py", "README.md", "tests/test_main.py"],
                "base_branch": "main",
                "head_branch": "feature/advanced-resolution"
            }

            mock_suggestions = [
                ResolutionSuggestion(
                    file_path="src/main.py",
                    suggested_resolution="Merge both implementations with conditional logic",
                    confidence=0.85,
                    rationale="Both versions have merit - conditional approach preserves functionality",
                    manual_steps=[
                        "Open src/main.py in your preferred editor",
                        "Locate conflict markers between lines 5-10",
                        "Create conditional logic to support both versions",
                        "Remove conflict markers after merging",
                        "Run tests to verify functionality"
                    ],
                    validation_steps=[
                        "Execute unit tests: python -m pytest tests/test_main.py",
                        "Check integration tests pass",
                        "Verify backward compatibility",
                        "git add src/main.py"
                    ],
                    alternative_approaches=[
                        "Choose feature branch version entirely",
                        "Refactor to extract common functionality",
                        "Create adapter pattern for version differences"
                    ]
                ),
                ResolutionSuggestion(
                    file_path="README.md",
                    suggested_resolution="Merge documentation from both branches",
                    confidence=0.95,
                    rationale="Documentation should be comprehensive",
                    manual_steps=[
                        "Review both README versions",
                        "Combine unique sections from each",
                        "Ensure formatting consistency",
                        "Remove conflict markers"
                    ],
                    validation_steps=[
                        "Check markdown formatting",
                        "Verify all links work",
                        "git add README.md"
                    ]
                )
            ]

            mock_ai.return_value = {
                "suggestions": mock_suggestions,
                "manual_steps": [
                    "Start with the most critical conflicts (src/main.py)",
                    "Use suggested merge strategy for complex logic conflicts",
                    "Combine documentation from both branches for README.md",
                    "Run comprehensive test suite after resolution",
                    "Review changes with team before committing",
                    "git commit -m 'resolve: merge conflicts with enhanced functionality'"
                ],
                "ai_response": """# Comprehensive Conflict Analysis

This PR contains 2 merge conflicts requiring careful attention:

## Priority 1: src/main.py (Moderate Complexity)
The conflict involves core functionality where both branches made significant improvements. 
Recommend merging both approaches with conditional logic to preserve all enhancements.

## Priority 2: README.md (Simple Complexity) 
Documentation conflict where both branches added valuable content.
Simple merge of unique sections from each branch recommended.

## Overall Strategy
1. Address core functionality first (src/main.py)
2. Merge documentation comprehensively (README.md)  
3. Validate with full test suite
4. Review merged functionality for edge cases

Estimated resolution time: 25-30 minutes with testing."""
            }

            # Execute the workflow
            result = await _handle_merge_conflicts(
                pr_number=456,
                repository=repository,
                conflict_details=conflict_details
            )

            # Comprehensive verification
            assert isinstance(result, ConflictResolution)
            
            # Verify conflict detection
            assert len(result.conflicts_detected) == 2
            assert result.conflicts_detected[0].file_path == "src/main.py"
            assert result.conflicts_detected[0].complexity == ConflictComplexity.MODERATE
            assert result.conflicts_detected[1].file_path == "README.md"
            assert result.conflicts_detected[1].conflict_type == ConflictType.ADD_ADD

            # Verify AI suggestions
            assert len(result.resolution_suggestions) == 2
            assert result.resolution_suggestions[0].confidence == 0.85
            assert len(result.resolution_suggestions[0].manual_steps) == 5
            assert len(result.resolution_suggestions[0].validation_steps) == 4

            # Verify metadata
            assert result.ai_assistance_available is True
            assert result.estimated_resolution_time > 20
            assert 2.0 <= result.complexity_score <= 5.0
            assert result.priority_order == ["src/main.py", "README.md"]
            
            # Verify reports
            assert "2 merge conflict(s) detected" in result.conflict_summary
            assert "# Merge Conflict Resolution Report" in result.resolution_report
            assert "src/main.py" in result.resolution_report
            assert "README.md" in result.resolution_report

            # Verify comprehensive guidance
            assert len(result.manual_steps) == 6
            assert "git commit" in result.manual_steps[-1]
            assert "test suite" in " ".join(result.manual_steps).lower()