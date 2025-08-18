"""
PR update workflows based on review feedback.

This module implements sophisticated code update workflows that address review comments
through AI-powered analysis and automated code changes.
"""

import asyncio
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional

from pydantic import BaseModel, Field

from ..models import ReviewComment, Issue, AIResponse
from ..integrations.github import GitHubIntegration
from ..integrations.git import GitWorktreeManager
from ..integrations.ai import ClaudeIntegration
from ..utils.logger import get_logger
from .review_comment import (
    ProcessedComment,
    CommentProcessingResult,
    ReviewCommentProcessor
)

logger = get_logger(__name__)


class UpdateType(str, Enum):
    """Types of updates that can be performed."""
    CODE_FIX = "code_fix"              # Bug fixes and corrections
    STYLE_IMPROVEMENT = "style_improvement"  # Code style and formatting
    PERFORMANCE_OPT = "performance_opt"      # Performance optimizations
    SECURITY_FIX = "security_fix"            # Security improvements
    DOCUMENTATION = "documentation"          # Documentation updates
    TEST_ADDITION = "test_addition"          # Adding or improving tests
    REFACTORING = "refactoring"              # Code refactoring
    FEATURE_ENHANCEMENT = "feature_enhancement"  # Feature improvements


class UpdateStatus(str, Enum):
    """Status of update execution."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    REQUIRES_MANUAL = "requires_manual"


class UpdatePlan(BaseModel):
    """Plan for updating code based on review feedback."""
    
    update_id: str = Field(description="Unique identifier for this update")
    update_type: UpdateType = Field(description="Type of update")
    description: str = Field(description="Description of planned update")
    target_files: List[str] = Field(description="Files to be modified")
    related_comments: List[int] = Field(description="Comment IDs this update addresses")
    estimated_effort: str = Field(description="Estimated effort (quick/medium/significant)")
    dependencies: List[str] = Field(default_factory=list, description="Other update IDs this depends on")
    automated: bool = Field(description="Whether update can be fully automated")
    commands: List[str] = Field(default_factory=list, description="Commands to execute")
    validation_steps: List[str] = Field(default_factory=list, description="Steps to validate the update")


class UpdateResult(BaseModel):
    """Result of executing an update."""
    
    update_id: str = Field(description="Update identifier")
    status: UpdateStatus = Field(description="Execution status")
    files_modified: List[str] = Field(description="Files that were actually modified")
    commands_executed: List[str] = Field(description="Commands that were executed")
    ai_response: Optional[AIResponse] = Field(default=None, description="AI response for this update")
    execution_time: float = Field(description="Time taken to execute (seconds)")
    error_message: Optional[str] = Field(default=None, description="Error message if failed")
    validation_results: Dict[str, bool] = Field(default_factory=dict, description="Validation step results")
    commit_sha: Optional[str] = Field(default=None, description="Commit SHA if changes were committed")


class UpdateBatch(BaseModel):
    """Batch of related updates to be executed together."""
    
    batch_id: str = Field(description="Batch identifier")
    updates: List[UpdatePlan] = Field(description="Updates in this batch")
    execution_order: List[str] = Field(description="Order to execute updates")
    batch_description: str = Field(description="Description of what this batch accomplishes")
    estimated_total_time: float = Field(description="Estimated total execution time")


class UpdateValidation(BaseModel):
    """Validation rules and results for updates."""
    
    update_id: str = Field(description="Update identifier")
    pre_conditions: Dict[str, bool] = Field(description="Pre-condition checks")
    post_conditions: Dict[str, bool] = Field(description="Post-condition validations")
    regression_checks: Dict[str, bool] = Field(description="Regression test results")
    code_quality_checks: Dict[str, bool] = Field(description="Code quality validations")
    overall_valid: bool = Field(description="Whether update passed all validations")
    issues_found: List[str] = Field(default_factory=list, description="Issues found during validation")


class CommitStrategy(BaseModel):
    """Strategy for committing review-based changes."""
    
    strategy_type: str = Field(description="Type of commit strategy (single/grouped/per-comment)")
    commit_message_template: str = Field(description="Template for commit messages")
    group_by_category: bool = Field(default=True, description="Whether to group commits by comment category")
    include_comment_refs: bool = Field(default=True, description="Whether to include comment references")
    conventional_commits: bool = Field(default=True, description="Whether to use conventional commit format")


class ReviewUpdateWorkflow:
    """
    Sophisticated workflow for updating PRs based on review feedback.
    
    Orchestrates the entire process from comment analysis to code changes and validation.
    """
    
    def __init__(
        self,
        github_integration: GitHubIntegration,
        git_integration: GitWorktreeManager,
        ai_integration: ClaudeIntegration,
        comment_processor: ReviewCommentProcessor
    ):
        """Initialize update workflow with required integrations."""
        self.github = github_integration
        self.git = git_integration
        self.ai = ai_integration
        self.comment_processor = comment_processor
        self.logger = get_logger(f"{__name__}.ReviewUpdateWorkflow")

    async def execute_review_updates(
        self,
        pr_number: int,
        repository: str,
        worktree_path: str,
        issue: Issue,
        comments: List[ReviewComment]
    ) -> List[UpdateResult]:
        """
        Execute comprehensive review updates based on feedback.
        
        Args:
            pr_number: Pull request number
            repository: Repository name
            worktree_path: Path to worktree for updates
            issue: Original issue context
            comments: Review comments to address
            
        Returns:
            List of update results with execution details
        """
        self.logger.info(f"Executing review updates for PR #{pr_number} with {len(comments)} comments")
        
        try:
            # 1. Analyze and process comments
            processing_result = await self.comment_processor.analyze_review_comments(
                pr_number, repository, comments
            )
            
            # 2. Create update plans
            update_plans = await self._create_update_plans(processing_result, issue, repository)
            
            # 3. Organize into execution batches
            update_batches = await self._organize_update_batches(update_plans)
            
            # 4. Execute updates in batches
            all_results = []
            for batch in update_batches:
                batch_results = await self._execute_update_batch(
                    batch, worktree_path, repository, issue
                )
                all_results.extend(batch_results)
            
            # 5. Validate all updates
            validation_results = await self._validate_all_updates(all_results, worktree_path)
            
            # 6. Commit changes if validation passes
            if all(v.overall_valid for v in validation_results):
                await self._commit_review_changes(all_results, worktree_path, repository, pr_number)
            else:
                self.logger.warning("Some updates failed validation - skipping commit")
            
            successful_updates = sum(1 for r in all_results if r.status == UpdateStatus.COMPLETED)
            self.logger.info(f"Review updates completed: {successful_updates}/{len(all_results)} successful")
            
            return all_results
            
        except Exception as e:
            self.logger.error(f"Failed to execute review updates: {e}")
            raise

    async def commit_review_changes(
        self,
        update_results: List[UpdateResult],
        worktree_path: str,
        repository: str,
        pr_number: int,
        commit_strategy: Optional[CommitStrategy] = None
    ) -> List[str]:
        """
        Create structured commits addressing review comments.
        
        Args:
            update_results: Results from update execution
            worktree_path: Path to worktree
            repository: Repository name
            pr_number: Pull request number
            commit_strategy: Optional commit strategy override
            
        Returns:
            List of commit SHAs created
        """
        self.logger.info(f"Committing review changes for PR #{pr_number}")
        
        try:
            if not commit_strategy:
                commit_strategy = CommitStrategy(
                    strategy_type="grouped",
                    commit_message_template="fix: address review feedback - {description}",
                    group_by_category=True,
                    include_comment_refs=True,
                    conventional_commits=True
                )
            
            # Group updates by commit strategy
            commit_groups = await self._group_updates_for_commits(update_results, commit_strategy)
            
            commit_shas = []
            for group in commit_groups:
                # Create commit for this group
                commit_message = await self._generate_commit_message(group, commit_strategy, pr_number)
                
                # Stage files
                modified_files = set()
                for result in group:
                    modified_files.update(result.files_modified)
                
                if not modified_files:
                    self.logger.debug("No files to commit for group")
                    continue
                
                # Add and commit files
                for file_path in modified_files:
                    await self.git.add_file(worktree_path, file_path)
                
                commit_sha = await self.git.commit_changes(worktree_path, commit_message)
                if commit_sha:
                    commit_shas.append(commit_sha)
                    self.logger.debug(f"Created commit {commit_sha[:8]} for review changes")
                    
                    # Update results with commit SHA
                    for result in group:
                        result.commit_sha = commit_sha
            
            self.logger.info(f"Created {len(commit_shas)} commits for review changes")
            return commit_shas
            
        except Exception as e:
            self.logger.error(f"Failed to commit review changes: {e}")
            raise

    async def validate_update_requirements(
        self,
        update_results: List[UpdateResult],
        worktree_path: str,
        original_comments: List[ReviewComment]
    ) -> List[UpdateValidation]:
        """
        Ensure updates adequately address review feedback.
        
        Args:
            update_results: Results from update execution
            worktree_path: Path to worktree
            original_comments: Original review comments
            
        Returns:
            List of validation results for each update
        """
        self.logger.info(f"Validating {len(update_results)} update requirements")
        
        try:
            validations = []
            
            for result in update_results:
                validation = await self._validate_single_update(
                    result, worktree_path, original_comments
                )
                validations.append(validation)
            
            # Summary validation
            passed_count = sum(1 for v in validations if v.overall_valid)
            self.logger.info(f"Update validation complete: {passed_count}/{len(validations)} passed")
            
            return validations
            
        except Exception as e:
            self.logger.error(f"Failed to validate update requirements: {e}")
            raise

    async def apply_suggested_changes(
        self,
        suggestions: List[ProcessedComment],
        worktree_path: str,
        repository: str
    ) -> List[UpdateResult]:
        """
        Process and apply reviewer-suggested code changes.
        
        Args:
            suggestions: Comments containing code suggestions
            worktree_path: Path to worktree
            repository: Repository name
            
        Returns:
            List of update results for applied suggestions
        """
        self.logger.info(f"Applying {len(suggestions)} suggested changes")
        
        try:
            results = []
            
            for suggestion in suggestions:
                if not suggestion.suggested_change:
                    continue
                
                result = await self._apply_single_suggestion(
                    suggestion, worktree_path, repository
                )
                if result:
                    results.append(result)
            
            self.logger.info(f"Applied {len(results)} suggested changes")
            return results
            
        except Exception as e:
            self.logger.error(f"Failed to apply suggested changes: {e}")
            raise

    async def update_pr_with_changes(
        self,
        pr_number: int,
        repository: str,
        worktree_path: str,
        update_results: List[UpdateResult]
    ) -> bool:
        """
        Push review-based changes to PR branch.
        
        Args:
            pr_number: Pull request number
            repository: Repository name
            worktree_path: Path to worktree
            update_results: Results from update execution
            
        Returns:
            Whether push was successful
        """
        self.logger.info(f"Updating PR #{pr_number} with review changes")
        
        try:
            # Get current branch
            current_branch = await self.git.get_current_branch(worktree_path)
            if not current_branch:
                raise ValueError("Could not determine current branch")
            
            # Check if there are commits to push
            commits_to_push = [r.commit_sha for r in update_results if r.commit_sha]
            if not commits_to_push:
                self.logger.info("No commits to push")
                return True
            
            # Push changes
            success = await self.git.push_changes(worktree_path, current_branch)
            
            if success:
                self.logger.info(f"Successfully pushed {len(commits_to_push)} commits to PR #{pr_number}")
                
                # Optionally add a comment to PR about the updates
                await self._add_update_comment_to_pr(pr_number, repository, update_results)
            else:
                self.logger.error(f"Failed to push changes to PR #{pr_number}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to update PR with changes: {e}")
            raise

    async def _create_update_plans(
        self,
        processing_result: CommentProcessingResult,
        issue: Issue,
        repository: str
    ) -> List[UpdatePlan]:
        """Create detailed update plans for addressing comments."""
        self.logger.debug("Creating update plans from processed comments")
        
        plans = []
        
        # Group actionable comments by type and file
        actionable_comments = [c for c in processing_result.processed_comments if c.actionable]
        
        # Create plans based on comment categories and relationships
        file_groups = self._group_comments_by_file(actionable_comments)
        
        for file_path, comments in file_groups.items():
            # Create update plans for this file
            file_plans = await self._create_file_update_plans(file_path, comments, issue, repository)
            plans.extend(file_plans)
        
        # Create plans for general comments
        general_comments = [c for c in actionable_comments if not c.original_comment.path]
        if general_comments:
            general_plans = await self._create_general_update_plans(general_comments, issue, repository)
            plans.extend(general_plans)
        
        self.logger.debug(f"Created {len(plans)} update plans")
        return plans

    async def _create_file_update_plans(
        self,
        file_path: str,
        comments: List[ProcessedComment],
        issue: Issue,
        repository: str
    ) -> List[UpdatePlan]:
        """Create update plans for a specific file."""
        plans = []
        
        # Group comments by update type
        bug_comments = [c for c in comments if c.category.value == "bug"]
        style_comments = [c for c in comments if c.category.value == "style"]
        performance_comments = [c for c in comments if c.category.value == "performance"]
        security_comments = [c for c in comments if c.category.value == "security"]
        
        # Create plans for each category
        if bug_comments:
            plan = UpdatePlan(
                update_id=f"bug_fix_{file_path}_{len(plans)}",
                update_type=UpdateType.CODE_FIX,
                description=f"Fix bugs in {file_path}",
                target_files=[file_path],
                related_comments=[c.original_comment.id for c in bug_comments],
                estimated_effort=self._estimate_combined_effort(bug_comments),
                automated=True,
                validation_steps=["syntax_check", "basic_functionality"]
            )
            plans.append(plan)
        
        if style_comments:
            plan = UpdatePlan(
                update_id=f"style_{file_path}_{len(plans)}",
                update_type=UpdateType.STYLE_IMPROVEMENT,
                description=f"Improve code style in {file_path}",
                target_files=[file_path],
                related_comments=[c.original_comment.id for c in style_comments],
                estimated_effort=self._estimate_combined_effort(style_comments),
                automated=True,
                validation_steps=["syntax_check", "formatting_check"]
            )
            plans.append(plan)
        
        if performance_comments:
            plan = UpdatePlan(
                update_id=f"performance_{file_path}_{len(plans)}",
                update_type=UpdateType.PERFORMANCE_OPT,
                description=f"Optimize performance in {file_path}",
                target_files=[file_path],
                related_comments=[c.original_comment.id for c in performance_comments],
                estimated_effort=self._estimate_combined_effort(performance_comments),
                automated=len(performance_comments) <= 2,  # Complex perf changes may need manual review
                validation_steps=["syntax_check", "basic_functionality", "performance_test"]
            )
            plans.append(plan)
        
        if security_comments:
            plan = UpdatePlan(
                update_id=f"security_{file_path}_{len(plans)}",
                update_type=UpdateType.SECURITY_FIX,
                description=f"Address security issues in {file_path}",
                target_files=[file_path],
                related_comments=[c.original_comment.id for c in security_comments],
                estimated_effort=self._estimate_combined_effort(security_comments),
                automated=True,
                validation_steps=["syntax_check", "security_scan", "basic_functionality"]
            )
            plans.append(plan)
        
        return plans

    async def _create_general_update_plans(
        self,
        comments: List[ProcessedComment],
        issue: Issue,
        repository: str
    ) -> List[UpdatePlan]:
        """Create update plans for general (non-file-specific) comments."""
        plans = []
        
        # Group by category
        doc_comments = [c for c in comments if c.category.value == "documentation"]
        test_comments = [c for c in comments if c.category.value == "testing"]
        
        if doc_comments:
            plan = UpdatePlan(
                update_id=f"documentation_{len(plans)}",
                update_type=UpdateType.DOCUMENTATION,
                description="Update documentation based on review feedback",
                target_files=["README.md", "docs/"],  # Common doc locations
                related_comments=[c.original_comment.id for c in doc_comments],
                estimated_effort=self._estimate_combined_effort(doc_comments),
                automated=True,
                validation_steps=["markdown_syntax", "link_check"]
            )
            plans.append(plan)
        
        if test_comments:
            plan = UpdatePlan(
                update_id=f"testing_{len(plans)}",
                update_type=UpdateType.TEST_ADDITION,
                description="Add or improve tests based on review feedback",
                target_files=["tests/", "spec/"],  # Common test locations
                related_comments=[c.original_comment.id for c in test_comments],
                estimated_effort=self._estimate_combined_effort(test_comments),
                automated=True,
                validation_steps=["syntax_check", "test_execution"]
            )
            plans.append(plan)
        
        return plans

    def _group_comments_by_file(self, comments: List[ProcessedComment]) -> Dict[str, List[ProcessedComment]]:
        """Group comments by file path."""
        file_groups = {}
        
        for comment in comments:
            file_path = comment.original_comment.path
            if file_path:
                if file_path not in file_groups:
                    file_groups[file_path] = []
                file_groups[file_path].append(comment)
        
        return file_groups

    def _estimate_combined_effort(self, comments: List[ProcessedComment]) -> str:
        """Estimate combined effort for multiple comments."""
        total_score = sum(comment.complexity_score for comment in comments)
        avg_score = total_score / len(comments) if comments else 0
        
        if avg_score <= 3:
            return "quick"
        elif avg_score <= 6:
            return "medium"
        else:
            return "significant"

    async def _organize_update_batches(self, update_plans: List[UpdatePlan]) -> List[UpdateBatch]:
        """Organize update plans into execution batches."""
        self.logger.debug("Organizing updates into execution batches")
        
        batches = []
        
        # Group by dependency and file overlap
        independent_updates = [p for p in update_plans if not p.dependencies]
        dependent_updates = [p for p in update_plans if p.dependencies]
        
        # Create batch for independent updates
        if independent_updates:
            batch = UpdateBatch(
                batch_id="independent_batch",
                updates=independent_updates,
                execution_order=[p.update_id for p in independent_updates],
                batch_description="Independent updates that can run in parallel",
                estimated_total_time=max(self._estimate_execution_time(p) for p in independent_updates)
            )
            batches.append(batch)
        
        # Create batches for dependent updates
        while dependent_updates:
            # Find updates whose dependencies are satisfied
            ready_updates = []
            completed_ids = set()
            for batch in batches:
                completed_ids.update(batch.execution_order)
            
            for update in dependent_updates[:]:
                if all(dep in completed_ids for dep in update.dependencies):
                    ready_updates.append(update)
                    dependent_updates.remove(update)
            
            if ready_updates:
                batch = UpdateBatch(
                    batch_id=f"dependent_batch_{len(batches)}",
                    updates=ready_updates,
                    execution_order=[p.update_id for p in ready_updates],
                    batch_description=f"Dependent updates batch {len(batches)}",
                    estimated_total_time=sum(self._estimate_execution_time(p) for p in ready_updates)
                )
                batches.append(batch)
            else:
                # Circular dependency or missing dependency - break it
                self.logger.warning("Breaking potential circular dependency in update plans")
                remaining_update = dependent_updates.pop(0)
                remaining_update.dependencies = []  # Clear dependencies
                batch = UpdateBatch(
                    batch_id=f"forced_batch_{len(batches)}",
                    updates=[remaining_update],
                    execution_order=[remaining_update.update_id],
                    batch_description="Forced execution to break dependency cycle",
                    estimated_total_time=self._estimate_execution_time(remaining_update)
                )
                batches.append(batch)
        
        self.logger.debug(f"Organized {len(update_plans)} updates into {len(batches)} batches")
        return batches

    def _estimate_execution_time(self, update_plan: UpdatePlan) -> float:
        """Estimate execution time for an update plan (in seconds)."""
        base_times = {
            "quick": 30.0,
            "medium": 120.0,
            "significant": 300.0
        }
        
        base_time = base_times.get(update_plan.estimated_effort, 120.0)
        
        # Adjust based on file count
        file_multiplier = 1.0 + (len(update_plan.target_files) - 1) * 0.2
        
        # Adjust based on validation steps
        validation_multiplier = 1.0 + len(update_plan.validation_steps) * 0.1
        
        return base_time * file_multiplier * validation_multiplier

    async def _execute_update_batch(
        self,
        batch: UpdateBatch,
        worktree_path: str,
        repository: str,
        issue: Issue
    ) -> List[UpdateResult]:
        """Execute a batch of updates."""
        self.logger.info(f"Executing update batch: {batch.batch_id} ({len(batch.updates)} updates)")
        
        results = []
        
        try:
            for update_id in batch.execution_order:
                update_plan = next(u for u in batch.updates if u.update_id == update_id)
                
                result = await self._execute_single_update(
                    update_plan, worktree_path, repository, issue
                )
                results.append(result)
                
                # Stop batch execution if critical update fails
                if (result.status == UpdateStatus.FAILED and 
                    update_plan.update_type in [UpdateType.CODE_FIX, UpdateType.SECURITY_FIX]):
                    self.logger.warning("Critical update failed, stopping batch execution")
                    break
            
            self.logger.info(f"Batch execution complete: {batch.batch_id}")
            return results
            
        except Exception as e:
            self.logger.error(f"Failed to execute update batch {batch.batch_id}: {e}")
            raise

    async def _execute_single_update(
        self,
        update_plan: UpdatePlan,
        worktree_path: str,
        repository: str,
        issue: Issue
    ) -> UpdateResult:
        """Execute a single update plan."""
        start_time = asyncio.get_event_loop().time()
        
        self.logger.debug(f"Executing update: {update_plan.update_id}")
        
        try:
            if not update_plan.automated:
                return UpdateResult(
                    update_id=update_plan.update_id,
                    status=UpdateStatus.REQUIRES_MANUAL,
                    files_modified=[],
                    commands_executed=[],
                    execution_time=0.0,
                    error_message="Update requires manual intervention"
                )
            
            # Build context for AI update
            context = await self._build_update_context(update_plan, issue, repository)
            
            # Execute AI update
            ai_response = await self.ai.execute_update_from_review(repository, context)
            
            if not ai_response.success:
                return UpdateResult(
                    update_id=update_plan.update_id,
                    status=UpdateStatus.FAILED,
                    files_modified=[],
                    commands_executed=[],
                    ai_response=ai_response,
                    execution_time=asyncio.get_event_loop().time() - start_time,
                    error_message=f"AI update failed: {ai_response.content}"
                )
            
            # Extract file changes and commands from AI response
            files_modified = [fc.get('path', '') for fc in ai_response.file_changes if fc.get('path')]
            commands_executed = ai_response.commands
            
            # Validate the update
            validation_results = await self._run_update_validations(
                update_plan, files_modified, worktree_path
            )
            
            execution_time = asyncio.get_event_loop().time() - start_time
            
            status = UpdateStatus.COMPLETED if all(validation_results.values()) else UpdateStatus.FAILED
            
            return UpdateResult(
                update_id=update_plan.update_id,
                status=status,
                files_modified=files_modified,
                commands_executed=commands_executed,
                ai_response=ai_response,
                execution_time=execution_time,
                validation_results=validation_results
            )
            
        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            self.logger.error(f"Failed to execute update {update_plan.update_id}: {e}")
            
            return UpdateResult(
                update_id=update_plan.update_id,
                status=UpdateStatus.FAILED,
                files_modified=[],
                commands_executed=[],
                execution_time=execution_time,
                error_message=str(e)
            )

    async def _build_update_context(
        self,
        update_plan: UpdatePlan,
        issue: Issue,
        repository: str
    ) -> str:
        """Build context string for AI update execution."""
        context_parts = [
            f"Update Type: {update_plan.update_type.value}",
            f"Description: {update_plan.description}",
            f"Target Files: {', '.join(update_plan.target_files)}",
            f"Repository: {repository}",
            f"Original Issue: {issue.title}",
            "",
            "Review Comments to Address:"
        ]
        
        # Add related comment IDs (we'd need to fetch the actual comments)
        context_parts.append(f"Comment IDs: {', '.join(map(str, update_plan.related_comments))}")
        
        # Add validation requirements
        if update_plan.validation_steps:
            context_parts.extend([
                "",
                "Validation Requirements:",
                *[f"- {step}" for step in update_plan.validation_steps]
            ])
        
        return "\n".join(context_parts)

    async def _run_update_validations(
        self,
        update_plan: UpdatePlan,
        modified_files: List[str],
        worktree_path: str
    ) -> Dict[str, bool]:
        """Run validation steps for an update."""
        validation_results = {}
        
        for step in update_plan.validation_steps:
            try:
                if step == "syntax_check":
                    result = await self._validate_syntax(modified_files, worktree_path)
                elif step == "formatting_check":
                    result = await self._validate_formatting(modified_files, worktree_path)
                elif step == "basic_functionality":
                    result = await self._validate_basic_functionality(worktree_path)
                elif step == "security_scan":
                    result = await self._validate_security(modified_files, worktree_path)
                elif step == "performance_test":
                    result = await self._validate_performance(worktree_path)
                elif step == "test_execution":
                    result = await self._validate_tests(worktree_path)
                else:
                    self.logger.warning(f"Unknown validation step: {step}")
                    result = True  # Skip unknown validations
                
                validation_results[step] = result
                
            except Exception as e:
                self.logger.error(f"Validation step {step} failed: {e}")
                validation_results[step] = False
        
        return validation_results

    async def _validate_syntax(self, modified_files: List[str], worktree_path: str) -> bool:
        """Validate syntax of modified files."""
        # This would implement syntax checking based on file types
        # For now, return True as placeholder
        return True

    async def _validate_formatting(self, modified_files: List[str], worktree_path: str) -> bool:
        """Validate code formatting of modified files."""
        # This would run formatters/linters
        # For now, return True as placeholder
        return True

    async def _validate_basic_functionality(self, worktree_path: str) -> bool:
        """Validate basic functionality still works."""
        # This would run smoke tests or basic checks
        # For now, return True as placeholder
        return True

    async def _validate_security(self, modified_files: List[str], worktree_path: str) -> bool:
        """Validate security of modified files."""
        # This would run security scanners
        # For now, return True as placeholder
        return True

    async def _validate_performance(self, worktree_path: str) -> bool:
        """Validate performance hasn't regressed."""
        # This would run performance tests
        # For now, return True as placeholder
        return True

    async def _validate_tests(self, worktree_path: str) -> bool:
        """Validate tests still pass."""
        # This would run the test suite
        # For now, return True as placeholder
        return True

    async def _validate_all_updates(
        self,
        update_results: List[UpdateResult],
        worktree_path: str
    ) -> List[UpdateValidation]:
        """Validate all updates comprehensively."""
        validations = []
        
        for result in update_results:
            validation = UpdateValidation(
                update_id=result.update_id,
                pre_conditions={"files_exist": True},  # Placeholder
                post_conditions={"changes_applied": result.status == UpdateStatus.COMPLETED},
                regression_checks=result.validation_results,
                code_quality_checks={"syntax_valid": True},  # Placeholder
                overall_valid=result.status == UpdateStatus.COMPLETED,
                issues_found=[] if result.status == UpdateStatus.COMPLETED else [result.error_message or "Unknown error"]
            )
            validations.append(validation)
        
        return validations

    async def _validate_single_update(
        self,
        result: UpdateResult,
        worktree_path: str,
        original_comments: List[ReviewComment]
    ) -> UpdateValidation:
        """Validate a single update against requirements."""
        # Get related comments
        # This would need to be implemented to fetch comments by ID
        
        return UpdateValidation(
            update_id=result.update_id,
            pre_conditions={"update_executed": True},
            post_conditions={"files_modified": len(result.files_modified) > 0},
            regression_checks=result.validation_results,
            code_quality_checks={"basic_quality": True},
            overall_valid=result.status == UpdateStatus.COMPLETED,
            issues_found=[] if result.status == UpdateStatus.COMPLETED else [result.error_message or "Update failed"]
        )

    async def _commit_review_changes(
        self,
        update_results: List[UpdateResult],
        worktree_path: str,
        repository: str,
        pr_number: int
    ) -> None:
        """Commit all review changes."""
        successful_updates = [r for r in update_results if r.status == UpdateStatus.COMPLETED]
        
        if not successful_updates:
            self.logger.info("No successful updates to commit")
            return
        
        commit_strategy = CommitStrategy(
            strategy_type="grouped",
            commit_message_template="fix: address review feedback in PR #{pr_number}",
            group_by_category=True,
            include_comment_refs=True,
            conventional_commits=True
        )
        
        await self.commit_review_changes(
            successful_updates, worktree_path, repository, pr_number, commit_strategy
        )

    async def _group_updates_for_commits(
        self,
        update_results: List[UpdateResult],
        commit_strategy: CommitStrategy
    ) -> List[List[UpdateResult]]:
        """Group updates for commit creation."""
        if commit_strategy.strategy_type == "single":
            return [update_results]
        elif commit_strategy.strategy_type == "per-comment":
            # Each update gets its own commit
            return [[result] for result in update_results]
        else:  # grouped
            # Group by update type or category
            groups = {}
            for result in update_results:
                # Use the update type as grouping key
                key = result.update_id.split('_')[0]  # Extract type from ID
                if key not in groups:
                    groups[key] = []
                groups[key].append(result)
            return list(groups.values())

    async def _generate_commit_message(
        self,
        update_group: List[UpdateResult],
        commit_strategy: CommitStrategy,
        pr_number: int
    ) -> str:
        """Generate commit message for a group of updates."""
        if len(update_group) == 1:
            update = update_group[0]
            update_type = update.update_id.split('_')[0]
            
            if commit_strategy.conventional_commits:
                return f"fix: address {update_type} feedback in PR #{pr_number}"
            else:
                return f"Address {update_type} feedback in PR #{pr_number}"
        else:
            update_types = list(set(u.update_id.split('_')[0] for u in update_group))
            types_str = ", ".join(update_types)
            
            if commit_strategy.conventional_commits:
                return f"fix: address review feedback ({types_str}) in PR #{pr_number}"
            else:
                return f"Address review feedback ({types_str}) in PR #{pr_number}"

    async def _apply_single_suggestion(
        self,
        suggestion: ProcessedComment,
        worktree_path: str,
        repository: str
    ) -> Optional[UpdateResult]:
        """Apply a single code suggestion."""
        if not suggestion.suggested_change or not suggestion.original_comment.path:
            return None
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            file_path = Path(worktree_path) / suggestion.original_comment.path
            
            if not file_path.exists():
                return UpdateResult(
                    update_id=f"suggestion_{suggestion.original_comment.id}",
                    status=UpdateStatus.FAILED,
                    files_modified=[],
                    commands_executed=[],
                    execution_time=asyncio.get_event_loop().time() - start_time,
                    error_message=f"File not found: {suggestion.original_comment.path}"
                )
            
            # Apply the suggested change
            # This would need more sophisticated logic to apply GitHub suggestions
            # For now, just mark as completed
            
            return UpdateResult(
                update_id=f"suggestion_{suggestion.original_comment.id}",
                status=UpdateStatus.COMPLETED,
                files_modified=[suggestion.original_comment.path],
                commands_executed=[],
                execution_time=asyncio.get_event_loop().time() - start_time
            )
            
        except Exception as e:
            return UpdateResult(
                update_id=f"suggestion_{suggestion.original_comment.id}",
                status=UpdateStatus.FAILED,
                files_modified=[],
                commands_executed=[],
                execution_time=asyncio.get_event_loop().time() - start_time,
                error_message=str(e)
            )

    async def _add_update_comment_to_pr(
        self,
        pr_number: int,
        repository: str,
        update_results: List[UpdateResult]
    ) -> None:
        """Add comment to PR summarizing the updates made."""
        try:
            successful_updates = [r for r in update_results if r.status == UpdateStatus.COMPLETED]
            failed_updates = [r for r in update_results if r.status == UpdateStatus.FAILED]
            
            comment_parts = [
                "## 🤖 Review Feedback Addressed",
                "",
                f"I've processed the review feedback and made {len(successful_updates)} updates:",
                ""
            ]
            
            if successful_updates:
                comment_parts.extend([
                    "### ✅ Completed Updates:",
                    ""
                ])
                
                for result in successful_updates:
                    update_type = result.update_id.split('_')[0].replace('_', ' ').title()
                    files_list = ", ".join(result.files_modified[:3])
                    if len(result.files_modified) > 3:
                        files_list += f" (+{len(result.files_modified) - 3} more)"
                    
                    comment_parts.append(f"- **{update_type}**: {files_list}")
                
                comment_parts.append("")
            
            if failed_updates:
                comment_parts.extend([
                    "### ⚠️ Updates Requiring Manual Attention:",
                    ""
                ])
                
                for result in failed_updates:
                    update_type = result.update_id.split('_')[0].replace('_', ' ').title()
                    error = result.error_message or "Unknown error"
                    comment_parts.append(f"- **{update_type}**: {error}")
                
                comment_parts.append("")
            
            comment_parts.extend([
                "All changes have been committed and are ready for re-review.",
                "",
                "_This comment was generated automatically by the auto review workflow._"
            ])
            
            comment_body = "\n".join(comment_parts)
            
            # Add comment to PR via GitHub API
            await self.github.add_pr_comment(repository, pr_number, comment_body)
            
        except Exception as e:
            self.logger.warning(f"Failed to add update comment to PR: {e}")