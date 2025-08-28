"""Merge conflict detection and handling for pull requests.

This module handles detection of merge conflicts and provides AI-assisted
guidance for resolving them during the merge process.
"""

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from auto.integrations.ai import ClaudeIntegration
from auto.models import (
    ConflictComplexity,
    ConflictDetail,
    ConflictResolution,
    ConflictType,
    GitHubRepository,
    ResolutionSuggestion,
)
from auto.utils.logger import get_logger
from auto.utils.shell import run_command_async as run_command

logger = get_logger(__name__)
console = Console()


class MergeConflictError(Exception):
    """Raised when merge conflicts are detected."""

    pass


async def _handle_merge_conflicts(
    pr_number: int, repository: GitHubRepository, conflict_details: str
) -> ConflictResolution:
    """
    Handle merge conflicts with AI-assisted resolution guidance.
    
    This function analyzes merge conflicts, provides detailed reporting, and offers
    AI-assisted resolution guidance using the established Claude AI integration patterns.

    Args:
        pr_number: Pull request number
        repository: Repository information
        conflict_details: Git conflict output and details

    Returns:
        ConflictResolution containing analysis and guidance
    """
    logger.info(f"Analyzing merge conflicts for PR #{pr_number} in {repository.full_name}")

    try:
        # Parse conflict details from Git output
        parsed_conflicts = await _parse_conflict_details(conflict_details, repository)
        
        if not parsed_conflicts:
            logger.warning("No conflicts parsed from git output")
            return ConflictResolution(
                conflicts_detected=[],
                resolution_suggestions=[],
                manual_steps=["No specific conflicts detected - check git status"],
                ai_assistance_available=False,
                estimated_resolution_time=5,
                complexity_score=1.0,
                priority_order=[],
                conflict_summary="No conflicts detected in provided details",
                resolution_report="Unable to analyze conflicts from provided git output"
            )

        # Get PR context for AI analysis
        pr_context = await _get_pr_context(pr_number, repository)

        # Generate AI-assisted resolution suggestions
        ai_resolution = await _generate_ai_resolution_suggestions(
            conflict_details, pr_context, repository, parsed_conflicts
        )

        # Calculate complexity and time estimation
        complexity_score = _calculate_complexity_score(parsed_conflicts)
        estimated_time = _estimate_resolution_time(parsed_conflicts, complexity_score)
        priority_order = _determine_priority_order(parsed_conflicts)

        # Generate comprehensive resolution report
        resolution_report = _generate_resolution_report(parsed_conflicts, ai_resolution)
        conflict_summary = _generate_conflict_summary(parsed_conflicts)

        # Create comprehensive conflict resolution
        conflict_resolution = ConflictResolution(
            conflicts_detected=parsed_conflicts,
            resolution_suggestions=ai_resolution.get("suggestions", []),
            manual_steps=ai_resolution.get("manual_steps", []),
            ai_assistance_available=True,
            estimated_resolution_time=estimated_time,
            complexity_score=complexity_score,
            priority_order=priority_order,
            conflict_summary=conflict_summary,
            resolution_report=resolution_report
        )

        # Display conflict analysis using Rich console
        _display_conflict_analysis(conflict_resolution)

        logger.info(f"Conflict analysis completed for PR #{pr_number}")
        return conflict_resolution

    except Exception as e:
        logger.error(f"Error analyzing merge conflicts: {e}")
        
        # Return fallback resolution with error details
        return ConflictResolution(
            conflicts_detected=[],
            resolution_suggestions=[],
            manual_steps=[
                "Manual conflict resolution required due to analysis error",
                f"Error: {str(e)}",
                "Check git status and resolve conflicts manually"
            ],
            ai_assistance_available=False,
            estimated_resolution_time=30,
            complexity_score=8.0,
            priority_order=[],
            conflict_summary=f"Conflict analysis failed: {str(e)}",
            resolution_report=f"Unable to analyze conflicts due to error: {str(e)}"
        )


async def _parse_conflict_details(conflict_details: str, repository: GitHubRepository) -> list[ConflictDetail]:
    """Parse Git conflict details into structured conflict information."""
    conflicts = []
    
    # Parse git status output for conflicted files
    conflicted_files = _extract_conflicted_files(conflict_details)
    
    for file_path in conflicted_files:
        try:
            # Get detailed conflict information for each file
            file_conflict_info = await _analyze_file_conflict(file_path, repository)
            conflicts.append(file_conflict_info)
        except Exception as e:
            logger.warning(f"Failed to analyze conflict in {file_path}: {e}")
            # Create basic conflict detail
            conflicts.append(ConflictDetail(
                file_path=file_path,
                conflict_type=ConflictType.CONTENT,
                complexity=ConflictComplexity.MODERATE,
                description=f"Merge conflict detected in {file_path}",
                line_numbers=[]
            ))
    
    return conflicts


def _extract_conflicted_files(git_output: str) -> list[str]:
    """Extract conflicted file paths from git status or merge output."""
    conflicted_files = []
    
    lines = git_output.split('\n')
    for line in lines:
        line = line.strip()
        
        # Look for git status conflict indicators
        if line.startswith('UU ') or line.startswith('AA ') or line.startswith('DD '):
            file_path = line[3:].strip()
            conflicted_files.append(file_path)
        elif 'both modified:' in line:
            file_path = line.split('both modified:')[-1].strip()
            conflicted_files.append(file_path)
        elif 'both added:' in line:
            file_path = line.split('both added:')[-1].strip()
            conflicted_files.append(file_path)
        elif 'both deleted:' in line:
            file_path = line.split('both deleted:')[-1].strip()
            conflicted_files.append(file_path)
    
    return list(set(conflicted_files))  # Remove duplicates


async def _analyze_file_conflict(file_path: str, repository: GitHubRepository) -> ConflictDetail:
    """Analyze conflict in a specific file."""
    try:
        # Try to read the conflicted file to analyze conflict markers
        result = await run_command(['cat', file_path])
        if result.returncode == 0:
            file_content = result.stdout
            
            # Detect conflict markers and analyze
            conflict_type, complexity, line_numbers, ours_content, theirs_content = _analyze_conflict_markers(file_content)
            
            return ConflictDetail(
                file_path=file_path,
                conflict_type=conflict_type,
                complexity=complexity,
                description=f"{conflict_type.value.title()} conflict in {file_path}",
                ours_content=ours_content,
                theirs_content=theirs_content,
                line_numbers=line_numbers,
                metadata={"file_size": len(file_content)}
            )
        else:
            # File might be deleted or renamed
            return ConflictDetail(
                file_path=file_path,
                conflict_type=ConflictType.DELETE,
                complexity=ConflictComplexity.MODERATE,
                description=f"Delete/modify conflict in {file_path}",
                line_numbers=[]
            )
            
    except Exception as e:
        logger.warning(f"Failed to analyze file conflict details: {e}")
        return ConflictDetail(
            file_path=file_path,
            conflict_type=ConflictType.CONTENT,
            complexity=ConflictComplexity.MODERATE,
            description=f"Conflict in {file_path} (details unavailable)",
            line_numbers=[]
        )


def _analyze_conflict_markers(content: str) -> tuple[ConflictType, ConflictComplexity, list[int], str | None, str | None]:
    """Analyze conflict markers in file content."""
    lines = content.split('\n')
    conflict_sections = []
    current_conflict = None
    line_num = 0
    
    for line in lines:
        line_num += 1
        
        if line.startswith('<<<<<<<'):
            # Start of conflict - "ours" version
            current_conflict = {
                'start_line': line_num,
                'ours_content': '',
                'theirs_content': '',
                'in_ours': True
            }
        elif line.startswith('=======') and current_conflict:
            # Separator - switch to "theirs" version
            current_conflict['in_ours'] = False
        elif line.startswith('>>>>>>>') and current_conflict:
            # End of conflict
            current_conflict['end_line'] = line_num
            conflict_sections.append(current_conflict)
            current_conflict = None
        elif current_conflict:
            # Inside conflict section
            if current_conflict['in_ours']:
                current_conflict['ours_content'] += line + '\n'
            else:
                current_conflict['theirs_content'] += line + '\n'
    
    if not conflict_sections:
        return ConflictType.CONTENT, ConflictComplexity.SIMPLE, [], None, None
    
    # Determine conflict type and complexity
    total_lines_conflicted = sum(
        section['end_line'] - section['start_line'] for section in conflict_sections
    )
    
    # Assess complexity based on number and size of conflicts
    if len(conflict_sections) == 1 and total_lines_conflicted < 10:
        complexity = ConflictComplexity.SIMPLE
    elif len(conflict_sections) <= 3 and total_lines_conflicted < 50:
        complexity = ConflictComplexity.MODERATE
    elif total_lines_conflicted < 100:
        complexity = ConflictComplexity.COMPLEX
    else:
        complexity = ConflictComplexity.CRITICAL
    
    # Extract line numbers and content samples
    line_numbers = []
    ours_sample = ""
    theirs_sample = ""
    
    for section in conflict_sections:
        line_numbers.extend(range(section['start_line'], section['end_line'] + 1))
        if not ours_sample:
            ours_sample = section['ours_content'][:200]  # First 200 chars
        if not theirs_sample:
            theirs_sample = section['theirs_content'][:200]  # First 200 chars
    
    return ConflictType.CONTENT, complexity, line_numbers, ours_sample, theirs_sample


async def _get_pr_context(pr_number: int, repository: GitHubRepository) -> dict[str, Any]:
    """Get PR context information for AI analysis."""
    try:
        cmd = [
            "gh", "pr", "view", str(pr_number),
            "--repo", repository.full_name,
            "--json", "title,body,files,baseRefName,headRefName"
        ]
        
        result = await run_command(cmd)
        if result.returncode == 0:
            pr_data = json.loads(result.stdout)
            
            # Extract file changes
            files_changed = []
            if "files" in pr_data:
                for file_info in pr_data["files"]:
                    files_changed.append(file_info.get("path", ""))
            
            return {
                "number": pr_number,
                "title": pr_data.get("title", ""),
                "description": pr_data.get("body", ""),
                "files_changed": files_changed,
                "base_branch": pr_data.get("baseRefName", "main"),
                "head_branch": pr_data.get("headRefName", "")
            }
        else:
            logger.warning(f"Failed to get PR context: {result.stderr}")
            return {"number": pr_number}
    
    except Exception as e:
        logger.warning(f"Error getting PR context: {e}")
        return {"number": pr_number}


async def _generate_ai_resolution_suggestions(
    conflict_details: str, pr_context: dict[str, Any], repository: GitHubRepository, parsed_conflicts: list[ConflictDetail]
) -> dict[str, Any]:
    """Generate AI-assisted resolution suggestions."""
    try:
        from auto.config import get_config
        config = get_config()
        
        ai_integration = ClaudeIntegration(config.ai)
        
        # Use the new analyze_merge_conflicts method
        ai_response = await ai_integration.analyze_merge_conflicts(
            conflict_details=conflict_details,
            pr_context=pr_context,
            repository=repository.full_name
        )
        
        if ai_response.success:
            # Parse AI response into structured suggestions
            suggestions = _parse_ai_suggestions(ai_response.content, parsed_conflicts)
            manual_steps = _extract_manual_steps_from_ai_response(ai_response.content)
            
            return {
                "suggestions": suggestions,
                "manual_steps": manual_steps,
                "ai_response": ai_response.content
            }
        else:
            logger.warning("AI conflict analysis failed")
            return {
                "suggestions": _generate_fallback_suggestions(parsed_conflicts),
                "manual_steps": _generate_fallback_manual_steps(parsed_conflicts),
                "ai_response": "AI analysis unavailable"
            }
    
    except Exception as e:
        logger.warning(f"Error generating AI suggestions: {e}")
        return {
            "suggestions": _generate_fallback_suggestions(parsed_conflicts),
            "manual_steps": _generate_fallback_manual_steps(parsed_conflicts),
            "ai_response": f"AI analysis error: {str(e)}"
        }


def _parse_ai_suggestions(ai_content: str, conflicts: list[ConflictDetail]) -> list[ResolutionSuggestion]:
    """Parse AI response into structured resolution suggestions."""
    suggestions = []
    
    for conflict in conflicts:
        # Create a basic suggestion structure
        # In a real implementation, this would parse the AI response more sophisticated
        suggestion = ResolutionSuggestion(
            file_path=conflict.file_path,
            suggested_resolution=f"Resolve {conflict.conflict_type.value} conflict in {conflict.file_path}",
            confidence=0.8,  # Default confidence
            rationale="AI-generated suggestion based on conflict analysis",
            manual_steps=[
                f"Open {conflict.file_path} in your editor",
                "Look for conflict markers (<<<<<<, ======, >>>>>>)",
                "Choose the correct version or merge both changes",
                "Remove conflict markers",
                "Test the changes"
            ],
            validation_steps=[
                "Compile/run tests to ensure changes work",
                "Review the merged code for logical consistency",
                f"git add {conflict.file_path}"
            ]
        )
        suggestions.append(suggestion)
    
    return suggestions


def _extract_manual_steps_from_ai_response(ai_content: str) -> list[str]:
    """Extract manual steps from AI response."""
    # Basic extraction - in practice would be more sophisticated
    return [
        "Review each conflicted file carefully",
        "Choose appropriate resolution strategy for each conflict",
        "Test changes after resolving conflicts",
        "Commit resolved conflicts with descriptive message"
    ]


def _generate_fallback_suggestions(conflicts: list[ConflictDetail]) -> list[ResolutionSuggestion]:
    """Generate fallback suggestions when AI is unavailable."""
    suggestions = []
    
    for conflict in conflicts:
        suggestion = ResolutionSuggestion(
            file_path=conflict.file_path,
            suggested_resolution=f"Manual resolution required for {conflict.file_path}",
            confidence=0.6,
            rationale="Fallback suggestion - AI analysis unavailable",
            manual_steps=[
                f"Open {conflict.file_path} in editor",
                "Locate conflict markers",
                "Choose appropriate resolution",
                "Remove markers and test"
            ]
        )
        suggestions.append(suggestion)
    
    return suggestions


def _generate_fallback_manual_steps(conflicts: list[ConflictDetail]) -> list[str]:
    """Generate fallback manual steps when AI is unavailable."""
    return [
        "Review git status to see all conflicted files",
        "Open each file and resolve conflicts manually",
        "Run tests to verify resolution",
        "Stage resolved files with git add",
        "Complete merge with git commit"
    ]


def _calculate_complexity_score(conflicts: list[ConflictDetail]) -> float:
    """Calculate overall complexity score for conflicts."""
    if not conflicts:
        return 0.0
    
    complexity_weights = {
        ConflictComplexity.SIMPLE: 1.0,
        ConflictComplexity.MODERATE: 3.0,
        ConflictComplexity.COMPLEX: 6.0,
        ConflictComplexity.CRITICAL: 10.0
    }
    
    total_score = sum(complexity_weights.get(conflict.complexity, 3.0) for conflict in conflicts)
    return min(total_score / len(conflicts), 10.0)


def _estimate_resolution_time(conflicts: list[ConflictDetail], complexity_score: float) -> int:
    """Estimate time to resolve conflicts in minutes."""
    base_time_per_conflict = 10  # minutes
    complexity_multiplier = complexity_score / 5.0  # Scale complexity to time multiplier
    
    total_time = len(conflicts) * base_time_per_conflict * complexity_multiplier
    return max(int(total_time), 5)  # Minimum 5 minutes


def _determine_priority_order(conflicts: list[ConflictDetail]) -> list[str]:
    """Determine priority order for resolving conflicts."""
    # Sort by complexity (critical first) and then by file path
    sorted_conflicts = sorted(
        conflicts, 
        key=lambda c: (
            -list(ConflictComplexity).index(c.complexity),  # Higher complexity first
            c.file_path
        )
    )
    
    return [conflict.file_path for conflict in sorted_conflicts]


def _generate_resolution_report(conflicts: list[ConflictDetail], ai_response: dict[str, Any]) -> str:
    """Generate comprehensive resolution report."""
    report_lines = []
    
    report_lines.append("# Merge Conflict Resolution Report")
    report_lines.append(f"**Total Conflicts:** {len(conflicts)}")
    report_lines.append("")
    
    for i, conflict in enumerate(conflicts, 1):
        report_lines.append(f"## Conflict {i}: {conflict.file_path}")
        report_lines.append(f"- **Type:** {conflict.conflict_type.value}")
        report_lines.append(f"- **Complexity:** {conflict.complexity.value}")
        report_lines.append(f"- **Description:** {conflict.description}")
        if conflict.line_numbers:
            report_lines.append(f"- **Lines Affected:** {len(conflict.line_numbers)} lines")
        report_lines.append("")
    
    if ai_response.get("ai_response"):
        report_lines.append("## AI Analysis")
        report_lines.append(ai_response["ai_response"])
    
    return "\n".join(report_lines)


def _generate_conflict_summary(conflicts: list[ConflictDetail]) -> str:
    """Generate human-readable conflict summary."""
    if not conflicts:
        return "No merge conflicts detected"
    
    complexity_counts = {}
    for conflict in conflicts:
        complexity_counts[conflict.complexity] = complexity_counts.get(conflict.complexity, 0) + 1
    
    summary_parts = [f"{len(conflicts)} merge conflict(s) detected"]
    
    for complexity, count in complexity_counts.items():
        summary_parts.append(f"{count} {complexity.value}")
    
    return " - ".join(summary_parts)


def _display_conflict_analysis(resolution: ConflictResolution) -> None:
    """Display conflict analysis using Rich console output."""
    # Summary panel
    summary_text = Text()
    summary_text.append("🔍 ", style="bold yellow")
    summary_text.append(resolution.conflict_summary, style="white")
    summary_text.append(f"\n⏱️  Estimated time: {resolution.estimated_resolution_time} minutes", style="cyan")
    summary_text.append(f"\n📊 Complexity score: {resolution.complexity_score:.1f}/10.0", style="magenta")
    
    console.print(Panel(summary_text, title="Conflict Analysis Summary", border_style="yellow"))
    
    # Conflicts table
    if resolution.conflicts_detected:
        table = Table(title="Detected Conflicts")
        table.add_column("File", style="cyan", no_wrap=True)
        table.add_column("Type", style="magenta")
        table.add_column("Complexity", style="green")
        table.add_column("Lines", justify="right", style="blue")
        
        for conflict in resolution.conflicts_detected:
            lines_str = str(len(conflict.line_numbers)) if conflict.line_numbers else "N/A"
            table.add_row(
                conflict.file_path,
                conflict.conflict_type.value,
                conflict.complexity.value,
                lines_str
            )
        
        console.print(table)
    
    # Manual steps
    if resolution.manual_steps:
        steps_text = Text()
        for i, step in enumerate(resolution.manual_steps, 1):
            steps_text.append(f"{i}. {step}\n", style="white")
        
        console.print(Panel(steps_text, title="Manual Resolution Steps", border_style="green"))


# Legacy compatibility functions
async def handle_merge_conflicts(pr_number: int, owner: str, repo: str) -> list[str] | None:
    """Detect and provide guidance for merge conflicts.

    Args:
        pr_number: Pull request number
        owner: Repository owner
        repo: Repository name

    Returns:
        List of conflict descriptions if conflicts exist, None otherwise
    """
    logger.debug(f"Checking for merge conflicts in PR #{pr_number}")

    try:
        # Get PR mergeable status
        pr_info = await _get_pr_info(pr_number, owner, repo)
        mergeable = pr_info.get("mergeable")

        if mergeable is False:
            # Get detailed conflict information using new implementation
            repository = GitHubRepository(owner=owner, name=repo)
            
            # Try to get actual conflict details from git
            conflict_details = await _get_detailed_conflict_info(pr_number, repository)
            
            # Use new conflict handler
            resolution = await _handle_merge_conflicts(pr_number, repository, conflict_details)
            
            # Return list format for backward compatibility
            conflict_descriptions = [conflict.description for conflict in resolution.conflicts_detected]
            logger.warning(f"Merge conflicts detected in PR #{pr_number}: {conflict_descriptions}")
            return conflict_descriptions or ["Merge conflicts detected - see detailed analysis above"]

        logger.debug(f"No merge conflicts detected for PR #{pr_number}")
        return None

    except Exception as e:
        logger.error(f"Error checking for merge conflicts: {e}")
        return [f"Error checking conflicts: {str(e)}"]


async def get_conflict_details(pr_number: int, owner: str, repo: str) -> list[str]:
    """Get detailed information about merge conflicts.

    Args:
        pr_number: Pull request number
        owner: Repository owner
        repo: Repository name

    Returns:
        List of conflict descriptions
    """
    try:
        repository = GitHubRepository(owner=owner, name=repo)
        conflict_details = await _get_detailed_conflict_info(pr_number, repository)
        resolution = await _handle_merge_conflicts(pr_number, repository, conflict_details)
        
        return [conflict.description for conflict in resolution.conflicts_detected]

    except Exception as e:
        return [f"Error getting conflict details: {str(e)}"]


async def _get_detailed_conflict_info(pr_number: int, repository: GitHubRepository) -> str:
    """Get detailed conflict information from git."""
    try:
        # Try to get merge conflict info by attempting a test merge
        cmd = [
            "gh", "pr", "checkout", str(pr_number),
            "--repo", repository.full_name
        ]
        
        result = await run_command(cmd)
        if result.returncode != 0:
            return result.stderr or "Failed to checkout PR for conflict analysis"
        
        # Check for conflicts after checkout
        status_result = await run_command(["git", "status", "--porcelain"])
        if status_result.returncode == 0:
            return status_result.stdout
        else:
            return "Unable to determine conflict status"
    
    except Exception as e:
        logger.warning(f"Failed to get detailed conflict info: {e}")
        return f"Conflict analysis error: {str(e)}"


async def _get_pr_info(pr_number: int, owner: str, repo: str) -> dict[str, Any]:
    """Get PR information from GitHub."""
    try:
        cmd = [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "state,draft,mergeable,reviews,statusCheckRollup,baseRefName",
        ]

        result = await run_command(cmd)

        if result.returncode == 0:
            return dict(json.loads(result.stdout))
        else:
            logger.error(f"Failed to get PR info: {result.stderr}")
            return {}

    except Exception as e:
        logger.error(f"Error getting PR info: {e}")
        return {}
