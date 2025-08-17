"""
AI Implementation Workflow

Handles AI-driven code implementation within worktrees, including prompt resolution,
AI command execution, change application, and state tracking.
"""

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from ..integrations.ai import ClaudeIntegration, AIIntegrationError
from ..integrations.prompts import PromptManager, PromptError
from ..models import Issue, WorkflowState, AIStatus, AIResponse, WorkflowStatus
from ..utils.logger import get_logger
from ..config import Config

logger = get_logger(__name__)


class ImplementationError(Exception):
    """Exception raised for implementation workflow errors."""
    pass


async def implement_issue_workflow(
    issue: Issue,
    workflow_state: WorkflowState,
    prompt_override: Optional[str] = None,
    prompt_file: Optional[str] = None,
    prompt_template: Optional[str] = None,
    prompt_append: Optional[str] = None,
    show_prompt: bool = False
) -> WorkflowState:
    """
    Complete AI implementation workflow for an issue.
    
    Changes to worktree directory, invokes Claude with implementation agent,
    applies changes, and updates workflow state.
    
    Args:
        issue: Issue to implement
        workflow_state: Current workflow state
        prompt_override: Direct prompt override
        prompt_file: Path to prompt file
        prompt_template: Named template to use
        prompt_append: Text to append to prompt
        show_prompt: Show resolved prompt instead of executing
        
    Returns:
        Updated workflow state
        
    Raises:
        ImplementationError: If implementation fails
    """
    logger.info(f"Starting AI implementation for issue {issue.id}")
    
    try:
        # Validate prerequisites
        if not workflow_state.worktree:
            raise ImplementationError("No worktree available for implementation")
        
        if not Path(workflow_state.worktree).exists():
            raise ImplementationError(f"Worktree path does not exist: {workflow_state.worktree}")
        
        # Update state to implementing
        workflow_state.update_ai_status(AIStatus.IN_PROGRESS)
        workflow_state.update_status(WorkflowStatus.IMPLEMENTING)
        
        config = Config()
        
        # Resolve prompt
        prompt_manager = PromptManager()
        
        try:
            resolved_prompt = prompt_manager.resolve_prompt(
                issue=issue,
                prompt_override=prompt_override,
                prompt_file=prompt_file,
                prompt_template=prompt_template,
                prompt_append=prompt_append,
                default_prompt=config.ai.implementation_prompt
            )
        except PromptError as e:
            raise ImplementationError(f"Failed to resolve prompt: {e}")
        
        # Show prompt if requested
        if show_prompt:
            logger.info("Resolved prompt:")
            logger.info("=" * 50)
            logger.info(resolved_prompt)
            logger.info("=" * 50)
            return workflow_state
        
        # Execute AI implementation
        ai_integration = ClaudeIntegration(config.ai)
        
        logger.info(f"Executing AI implementation in worktree: {workflow_state.worktree}")
        ai_response = await ai_integration.execute_implementation(
            issue=issue,
            worktree_path=workflow_state.worktree,
            custom_prompt=resolved_prompt
        )
        
        # Apply AI changes
        if ai_response.success:
            logger.info("AI implementation successful, applying changes")
            await apply_ai_changes(
                ai_response=ai_response,
                worktree_path=workflow_state.worktree,
                config=config
            )
            
            # Update state to implemented
            workflow_state.update_ai_status(AIStatus.IMPLEMENTED, ai_response)
            logger.info(f"AI implementation completed for issue {issue.id}")
            
        else:
            # Handle AI failure
            workflow_state.update_ai_status(AIStatus.FAILED, ai_response)
            workflow_state.update_status(WorkflowStatus.FAILED)
            raise ImplementationError(f"AI implementation failed: {ai_response.content}")
        
        return workflow_state
        
    except AIIntegrationError as e:
        # Don't log here - error already logged at AI integration level
        workflow_state.update_ai_status(AIStatus.FAILED)
        workflow_state.update_status(WorkflowStatus.FAILED)
        raise ImplementationError(f"AI integration failed: {e}")
    
    except Exception as e:
        logger.error(f"Unexpected error during implementation: {e}")
        workflow_state.update_ai_status(AIStatus.FAILED)
        workflow_state.update_status(WorkflowStatus.FAILED)
        raise ImplementationError(f"Implementation failed: {e}")


async def apply_ai_changes(
    ai_response: AIResponse,
    worktree_path: str,
    config: Config
) -> None:
    """
    Apply AI-suggested changes to the worktree.
    
    Interprets AI responses, applies file modifications, executes suggested commands,
    and handles conflicts.
    
    Args:
        ai_response: AI response with changes to apply
        worktree_path: Path to worktree
        config: Configuration object
        
    Raises:
        ImplementationError: If changes cannot be applied
    """
    logger.debug(f"Applying AI changes in {worktree_path}")
    
    # Change to worktree directory
    original_cwd = os.getcwd()
    
    try:
        os.chdir(worktree_path)
        logger.debug(f"Changed to worktree directory: {worktree_path}")
        
        # Apply file changes
        if ai_response.file_changes:
            logger.info(f"Applying {len(ai_response.file_changes)} file changes")
            await _apply_file_changes(ai_response.file_changes, worktree_path)
        
        # Execute suggested commands
        if ai_response.commands:
            logger.info(f"Executing {len(ai_response.commands)} commands")
            await _execute_ai_commands(ai_response.commands, worktree_path)
        
        logger.info("Successfully applied all AI changes")
        
    except Exception as e:
        logger.error(f"Failed to apply AI changes: {e}")
        raise ImplementationError(f"Failed to apply changes: {e}")
    
    finally:
        # Always restore original directory
        os.chdir(original_cwd)


async def _apply_file_changes(
    file_changes: List[Dict[str, str]], 
    worktree_path: str
) -> None:
    """Apply file changes from AI response."""
    for change in file_changes:
        action = change.get('action', '').lower()
        file_path = change.get('path', '')
        
        if not file_path:
            logger.warning("Skipping file change with no path")
            continue
        
        full_path = Path(worktree_path) / file_path
        
        try:
            if action in ['create', 'created']:
                await _create_file(full_path, change.get('content', ''))
            elif action in ['modify', 'modified', 'update', 'updated']:
                await _modify_file(full_path, change.get('content', ''))
            elif action in ['delete', 'deleted', 'remove', 'removed']:
                await _delete_file(full_path)
            else:
                logger.warning(f"Unknown file action: {action} for {file_path}")
                
        except Exception as e:
            logger.error(f"Failed to apply {action} to {file_path}: {e}")
            # Continue with other changes rather than failing completely
            continue


async def _create_file(file_path: Path, content: str) -> None:
    """Create a new file with content."""
    logger.debug(f"Creating file: {file_path}")
    
    # Ensure parent directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write content to file
    file_path.write_text(content, encoding='utf-8')
    logger.debug(f"Created file: {file_path}")


async def _modify_file(file_path: Path, content: str) -> None:
    """Modify an existing file with new content."""
    logger.debug(f"Modifying file: {file_path}")
    
    if not file_path.exists():
        logger.warning(f"File to modify does not exist, creating: {file_path}")
        await _create_file(file_path, content)
        return
    
    # For now, simple replacement. Could be enhanced with patch application
    if content:
        file_path.write_text(content, encoding='utf-8')
        logger.debug(f"Modified file: {file_path}")
    else:
        logger.warning(f"No content provided for modifying {file_path}")


async def _delete_file(file_path: Path) -> None:
    """Delete a file."""
    logger.debug(f"Deleting file: {file_path}")
    
    if file_path.exists():
        file_path.unlink()
        logger.debug(f"Deleted file: {file_path}")
    else:
        logger.warning(f"File to delete does not exist: {file_path}")


async def _execute_ai_commands(commands: List[str], worktree_path: str) -> None:
    """Execute AI-suggested commands in the worktree."""
    for command in commands:
        if not command.strip():
            continue
            
        logger.info(f"Executing command: {command}")
        
        try:
            # Execute command in worktree directory
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.debug(f"Command succeeded: {command}")
                if stdout:
                    logger.debug(f"Command output: {stdout.decode()}")
            else:
                logger.warning(f"Command failed (exit {process.returncode}): {command}")
                if stderr:
                    logger.warning(f"Command error: {stderr.decode()}")
                
                # Don't fail the entire process for command failures
                # Some commands might be optional or have different success criteria
                continue
                
        except Exception as e:
            logger.warning(f"Failed to execute command '{command}': {e}")
            # Continue with other commands
            continue


def validate_implementation_prerequisites(workflow_state: WorkflowState) -> None:
    """
    Validate that prerequisites for AI implementation are met.
    
    Args:
        workflow_state: Current workflow state
        
    Raises:
        ImplementationError: If prerequisites are not met
    """
    if not workflow_state.worktree:
        raise ImplementationError("No worktree configured for implementation")
    
    worktree_path = Path(workflow_state.worktree)
    if not worktree_path.exists():
        raise ImplementationError(f"Worktree path does not exist: {workflow_state.worktree}")
    
    if not worktree_path.is_dir():
        raise ImplementationError(f"Worktree path is not a directory: {workflow_state.worktree}")
    
    # Check if it's a git repository
    git_dir = worktree_path / ".git"
    if not git_dir.exists():
        raise ImplementationError(f"Worktree is not a git repository: {workflow_state.worktree}")
    
    config = Config()
    if not config.ai.implementation_agent:
        raise ImplementationError("No AI implementation agent configured")


async def get_implementation_status(workflow_state: WorkflowState) -> Dict[str, any]:
    """
    Get detailed implementation status information.
    
    Args:
        workflow_state: Current workflow state
        
    Returns:
        Dictionary with implementation status details
    """
    status = {
        "ai_status": workflow_state.ai_status.value,
        "has_ai_response": workflow_state.ai_response is not None,
        "file_changes_count": 0,
        "commands_count": 0,
        "implementation_successful": False
    }
    
    if workflow_state.ai_response:
        status["file_changes_count"] = len(workflow_state.ai_response.file_changes)
        status["commands_count"] = len(workflow_state.ai_response.commands)
        status["implementation_successful"] = workflow_state.ai_response.success
        status["response_type"] = workflow_state.ai_response.response_type
    
    return status


def has_uncommitted_changes(worktree_path: str) -> bool:
    """
    Check if the worktree has uncommitted changes.
    
    Args:
        worktree_path: Path to worktree
        
    Returns:
        True if there are uncommitted changes
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # If there's output, there are changes
        return bool(result.stdout.strip())
        
    except (subprocess.SubprocessError, subprocess.TimeoutExpired):
        logger.warning(f"Failed to check git status in {worktree_path}")
        return False


def get_implementation_summary(workflow_state: WorkflowState) -> str:
    """
    Get a human-readable summary of the implementation.
    
    Args:
        workflow_state: Current workflow state
        
    Returns:
        Summary string
    """
    if workflow_state.ai_status == AIStatus.NOT_STARTED:
        return "AI implementation not started"
    
    if workflow_state.ai_status == AIStatus.IN_PROGRESS:
        return "AI implementation in progress"
    
    if workflow_state.ai_status == AIStatus.FAILED:
        if workflow_state.ai_response:
            content = workflow_state.ai_response.content
            if len(content) > 50:
                return f"AI implementation failed: {content[:50]}..."
            return f"AI implementation failed: {content}"
        return "AI implementation failed"
    
    if workflow_state.ai_status == AIStatus.IMPLEMENTED:
        if workflow_state.ai_response:
            file_count = len(workflow_state.ai_response.file_changes)
            cmd_count = len(workflow_state.ai_response.commands)
            return f"AI implementation completed: {file_count} files modified, {cmd_count} commands executed"
        return "AI implementation completed"
    
    return f"AI implementation status: {workflow_state.ai_status.value}"