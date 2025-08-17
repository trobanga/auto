"""
AI Integration Module

Provides Claude CLI integration for automated code implementation, review, and updates.
Includes agent selection, prompt formatting, response parsing, and error handling.
"""

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from ..models import Issue, AIConfig, AIResponse
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AICommandResult:
    """Result from executing an AI command."""
    success: bool
    output: str
    error: str
    exit_code: int
    duration: float


class ClaudeIntegration:
    """
    Claude CLI integration providing AI-powered code implementation, review, and updates.
    
    Handles agent selection, prompt formatting, command execution, and response parsing
    for seamless integration with the auto workflow system.
    """

    def __init__(self, config: AIConfig):
        """Initialize Claude integration with configuration."""
        self.config = config
        self.command = config.command or "claude"
        self.logger = get_logger(f"{__name__}.ClaudeIntegration")

    async def execute_implementation(
        self, 
        issue: Issue, 
        worktree_path: str,
        custom_prompt: Optional[str] = None
    ) -> AIResponse:
        """
        Execute AI implementation for an issue in the specified worktree.
        
        Args:
            issue: Issue to implement
            worktree_path: Path to worktree for implementation
            custom_prompt: Optional custom prompt override
            
        Returns:
            AIResponse containing implementation results
            
        Raises:
            AIIntegrationError: If AI command fails or response is invalid
        """
        try:
            # Validate prerequisites
            await self._validate_prerequisites()
            
            # Format implementation prompt
            prompt = self._format_implementation_prompt(issue, worktree_path, custom_prompt)
            
            # Execute AI command
            self.logger.info(f"Running AI implementation for issue {issue.id} in {worktree_path}")
            result = await self._execute_ai_command(
                prompt=prompt,
                agent=self.config.implementation_agent,
                working_directory=worktree_path
            )
            
            if not result.success:
                raise AIIntegrationError(
                    f"AI implementation failed: {result.error}",
                    exit_code=result.exit_code
                )
            
            # Parse AI response
            ai_response = self._parse_ai_response(result.output, "implementation")
            
            self.logger.info(f"AI implementation completed for issue {issue.id}")
            return ai_response
            
        except Exception as e:
            self.logger.error(f"AI implementation failed for issue {issue.id}: {e}")
            raise

    async def execute_review(
        self, 
        pr_number: int, 
        repository: str,
        custom_prompt: Optional[str] = None
    ) -> AIResponse:
        """
        Execute AI review for a pull request.
        
        Args:
            pr_number: Pull request number
            repository: Repository name
            custom_prompt: Optional custom prompt override
            
        Returns:
            AIResponse containing review results
        """
        try:
            await self._validate_prerequisites()
            
            prompt = self._format_review_prompt(pr_number, repository, custom_prompt)
            
            self.logger.info(f"Running AI review for PR #{pr_number}")
            result = await self._execute_ai_command(
                prompt=prompt,
                agent=self.config.review_agent
            )
            
            if not result.success:
                raise AIIntegrationError(
                    f"AI review failed: {result.error}",
                    exit_code=result.exit_code
                )
            
            ai_response = self._parse_ai_response(result.output, "review")
            
            self.logger.info(f"AI review completed for PR #{pr_number}")
            return ai_response
            
        except Exception as e:
            self.logger.error(f"AI review failed for PR #{pr_number}: {e}")
            raise

    async def execute_update(
        self, 
        issue: Issue, 
        review_comments: List[str],
        worktree_path: str,
        custom_prompt: Optional[str] = None
    ) -> AIResponse:
        """
        Execute AI update to address review comments.
        
        Args:
            issue: Original issue
            review_comments: List of review comments to address
            worktree_path: Path to worktree for updates
            custom_prompt: Optional custom prompt override
            
        Returns:
            AIResponse containing update results
        """
        try:
            await self._validate_prerequisites()
            
            prompt = self._format_update_prompt(issue, review_comments, custom_prompt)
            
            self.logger.info(f"Running AI update for issue {issue.id}")
            result = await self._execute_ai_command(
                prompt=prompt,
                agent=self.config.update_agent,
                working_directory=worktree_path
            )
            
            if not result.success:
                raise AIIntegrationError(
                    f"AI update failed: {result.error}",
                    exit_code=result.exit_code
                )
            
            ai_response = self._parse_ai_response(result.output, "update")
            
            self.logger.info(f"AI update completed for issue {issue.id}")
            return ai_response
            
        except Exception as e:
            self.logger.error(f"AI update failed for issue {issue.id}: {e}")
            raise

    def _build_ai_command(self, prompt: str, agent: Optional[str] = None) -> List[str]:
        """
        Build AI command based on configured format.
        
        Args:
            prompt: The prompt to send to the AI
            agent: Optional agent name
            
        Returns:
            List of command arguments ready for execution
        """
        command_format = getattr(self.config, 'command_format', 'claude')
        
        if command_format == "claude":
            # Claude Code style: agent invocation in prompt, use -p flag
            if agent:
                prompt = f"agent-{agent}, {prompt}"
            return [self.command, "-p", prompt]
        
        elif command_format == "openai":
            # OpenAI CLI style (hypothetical example)
            cmd = [self.command]
            if agent:
                cmd.extend(["--model", agent])
            cmd.extend(["--prompt", prompt])
            return cmd
        
        elif command_format == "ollama":
            # Ollama style (hypothetical example)
            cmd = [self.command, "run"]
            if agent:
                cmd.append(agent)
            else:
                cmd.append("llama2")  # default model
            cmd.append(prompt)
            return cmd
        
        elif command_format == "custom":
            # User-defined template from config
            template = getattr(self.config, 'command_template', None)
            if template:
                return self._parse_custom_template(template, prompt, agent)
            else:
                self.logger.warning("Custom command format specified but no command_template provided, falling back to legacy")
                return self._build_legacy_command(prompt, agent)
        
        else:
            # Default/legacy behavior for backward compatibility
            return self._build_legacy_command(prompt, agent)
    
    def _build_legacy_command(self, prompt: str, agent: Optional[str] = None) -> List[str]:
        """Build command using legacy format for backward compatibility."""
        cmd = [self.command]
        if agent:
            cmd.extend(["--agent", agent])
        cmd.append(prompt)
        return cmd
    
    def _parse_custom_template(self, template: str, prompt: str, agent: Optional[str] = None) -> List[str]:
        """
        Parse custom command template.
        
        Template variables:
        - {command}: The AI command
        - {agent}: The agent name (if provided)
        - {prompt}: The prompt text
        
        Example: "{command} -p \"agent-{agent}, {prompt}\""
        """
        # Replace template variables
        formatted = template.format(
            command=self.command,
            agent=agent or "",
            prompt=prompt
        )
        
        # Simple parsing - split by spaces but respect quoted strings
        import shlex
        try:
            return shlex.split(formatted)
        except ValueError as e:
            self.logger.error(f"Failed to parse custom command template: {e}")
            # Fallback to legacy format
            return self._build_legacy_command(prompt, agent)

    async def _execute_ai_command(
        self,
        prompt: str,
        agent: str,
        working_directory: Optional[str] = None
    ) -> AICommandResult:
        """
        Execute Claude CLI command with specified agent and prompt.
        
        Args:
            prompt: Formatted prompt for AI
            agent: Agent name to use
            working_directory: Working directory for command execution
            
        Returns:
            AICommandResult with execution details
        """
        import time
        start_time = time.time()
        
        try:
            # Build command using flexible command builder
            cmd = self._build_ai_command(prompt, agent)
            
            self.logger.debug(f"Executing AI command: {' '.join(cmd[:3])}... (prompt truncated)")
            
            # Execute command
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=working_directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024  # 1MB limit for output
            )
            
            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.config.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration = time.time() - start_time
                return AICommandResult(
                    success=False,
                    output="",
                    error=f"AI command timed out after {self.config.timeout} seconds",
                    exit_code=-1,
                    duration=duration
                )
            
            duration = time.time() - start_time
            
            output = stdout.decode('utf-8', errors='replace')
            error = stderr.decode('utf-8', errors='replace')
            
            success = process.returncode == 0
            
            if not success:
                self.logger.warning(f"AI command failed with exit code {process.returncode}")
                self.logger.debug(f"Error output: {error}")
            
            return AICommandResult(
                success=success,
                output=output,
                error=error,
                exit_code=process.returncode or 0,
                duration=duration
            )
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"Failed to execute AI command: {e}")
            return AICommandResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
                duration=duration
            )

    def _format_implementation_prompt(
        self, 
        issue: Issue, 
        worktree_path: str,
        custom_prompt: Optional[str] = None
    ) -> str:
        """
        Format implementation prompt with issue context and repository information.
        
        Args:
            issue: Issue to implement
            worktree_path: Path to worktree
            custom_prompt: Optional custom prompt override
            
        Returns:
            Formatted prompt for AI implementation
        """
        if custom_prompt:
            # Use custom prompt but include basic issue context
            context = f"Issue #{issue.id}: {issue.title}\n\n{issue.description}\n\n"
            return context + custom_prompt
        
        # Use configured template with variable substitution
        template = self.config.implementation_prompt
        
        # Build context information
        context_parts = [
            f"Issue ID: {issue.id}",
            f"Title: {issue.title}",
            f"Description:\n{issue.description}",
        ]
        
        if issue.labels:
            context_parts.append(f"Labels: {', '.join(issue.labels)}")
        
        if issue.assignee:
            context_parts.append(f"Assignee: {issue.assignee}")
        
        # Add repository context
        repo_context = self._get_repository_context(worktree_path)
        if repo_context:
            context_parts.append(f"Repository Context:\n{repo_context}")
        
        context = "\n".join(context_parts)
        
        # Format template with variables
        try:
            formatted_prompt = template.format(
                issue_id=issue.id,
                title=issue.title,
                description=issue.description,
                context=context,
                labels=", ".join(issue.labels) if issue.labels else "",
                assignee=issue.assignee or ""
            )
        except KeyError as e:
            self.logger.warning(f"Template variable {e} not found, using fallback")
            formatted_prompt = f"{template}\n\n{context}"
        
        return formatted_prompt

    def _format_review_prompt(
        self, 
        pr_number: int, 
        repository: str,
        custom_prompt: Optional[str] = None
    ) -> str:
        """Format review prompt for PR review."""
        if custom_prompt:
            return f"Review PR #{pr_number} in {repository}:\n\n{custom_prompt}"
        
        template = self.config.review_prompt
        return f"Review PR #{pr_number} in {repository}:\n\n{template}"

    def _format_update_prompt(
        self, 
        issue: Issue, 
        review_comments: List[str],
        custom_prompt: Optional[str] = None
    ) -> str:
        """Format update prompt to address review comments."""
        comments_text = "\n".join(f"- {comment}" for comment in review_comments)
        
        if custom_prompt:
            return f"Issue #{issue.id}: {issue.title}\n\nReview Comments:\n{comments_text}\n\n{custom_prompt}"
        
        template = self.config.update_prompt
        try:
            formatted_prompt = template.format(
                issue_id=issue.id,
                title=issue.title,
                comments=comments_text
            )
        except KeyError:
            formatted_prompt = f"{template}\n\nIssue #{issue.id}: {issue.title}\n\nReview Comments:\n{comments_text}"
        
        return formatted_prompt

    def _parse_ai_response(self, output: str, response_type: str) -> AIResponse:
        """
        Parse AI response and extract actionable items.
        
        Args:
            output: Raw AI response output
            response_type: Type of response (implementation, review, update)
            
        Returns:
            Structured AIResponse
        """
        try:
            # Try to parse as structured JSON first
            if output.strip().startswith('{'):
                try:
                    data = json.loads(output)
                    return AIResponse(
                        success=True,
                        response_type=response_type,
                        content=data.get('content', output),
                        file_changes=data.get('file_changes', []),
                        commands=data.get('commands', []),
                        metadata=data.get('metadata', {})
                    )
                except json.JSONDecodeError:
                    pass
            
            # Parse freeform response
            file_changes = self._extract_file_changes(output)
            commands = self._extract_commands(output)
            
            return AIResponse(
                success=True,
                response_type=response_type,
                content=output,
                file_changes=file_changes,
                commands=commands,
                metadata={}
            )
            
        except Exception as e:
            self.logger.error(f"Failed to parse AI response: {e}")
            # Return basic response even if parsing fails
            return AIResponse(
                success=False,
                response_type=response_type,
                content=output,
                file_changes=[],
                commands=[],
                metadata={"parse_error": str(e)}
            )

    def _extract_file_changes(self, output: str) -> List[Dict[str, str]]:
        """Extract file changes from AI response text."""
        file_changes = []
        
        # Look for common patterns indicating file changes
        lines = output.split('\n')
        for line in lines:
            line = line.strip()
            
            # Pattern: "Modified: path/to/file.py"
            if line.startswith(('Modified:', 'Created:', 'Updated:', 'Changed:')):
                parts = line.split(':', 1)
                if len(parts) == 2:
                    action = parts[0].lower()
                    file_path = parts[1].strip()
                    file_changes.append({
                        'action': action,
                        'path': file_path
                    })
            
            # Pattern: "- src/components/Button.tsx (modified)"
            elif line.startswith('-') and ('(modified)' in line or '(created)' in line):
                if '(modified)' in line:
                    file_path = line.replace('-', '').replace('(modified)', '').strip()
                    file_changes.append({'action': 'modified', 'path': file_path})
                elif '(created)' in line:
                    file_path = line.replace('-', '').replace('(created)', '').strip()
                    file_changes.append({'action': 'created', 'path': file_path})
        
        return file_changes

    def _extract_commands(self, output: str) -> List[str]:
        """Extract commands from AI response text."""
        commands = []
        
        lines = output.split('\n')
        in_code_block = False
        
        for line in lines:
            line = line.strip()
            
            # Check for code blocks
            if line.startswith('```'):
                in_code_block = not in_code_block
                continue
            
            # Extract commands from code blocks or command patterns
            if in_code_block and line and not line.startswith('#'):
                commands.append(line)
            elif line.startswith('Run:') or line.startswith('Execute:'):
                cmd = line.split(':', 1)[1].strip()
                if cmd:
                    commands.append(cmd)
        
        return commands

    def _get_repository_context(self, worktree_path: str) -> str:
        """Get repository context for AI prompts."""
        try:
            repo_path = Path(worktree_path)
            if not repo_path.exists():
                return ""
            
            context_parts = []
            
            # Add basic file structure
            try:
                result = subprocess.run(
                    ["find", ".", "-type", "f", "-name", "*.py", "-o", "-name", "*.js", "-o", "-name", "*.ts", "-o", "-name", "*.tsx"],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    files = result.stdout.strip().split('\n')[:20]  # Limit to 20 files
                    context_parts.append(f"Key files:\n" + "\n".join(files))
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass
            
            # Add package.json or requirements.txt if present
            for config_file in ["package.json", "requirements.txt", "pyproject.toml"]:
                config_path = repo_path / config_file
                if config_path.exists():
                    try:
                        content = config_path.read_text()[:500]  # First 500 chars
                        context_parts.append(f"{config_file}:\n{content}")
                    except Exception:
                        pass
            
            return "\n\n".join(context_parts)
        
        except Exception as e:
            self.logger.debug(f"Failed to get repository context: {e}")
            return ""

    async def _validate_prerequisites(self) -> None:
        """Validate AI prerequisites are met."""
        # Check if Claude CLI is available
        try:
            result = await asyncio.create_subprocess_exec(
                self.command, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(result.communicate(), timeout=10)
            
            if result.returncode != 0:
                raise AIIntegrationError(f"Claude CLI not working properly (exit code: {result.returncode})")
                
        except (asyncio.TimeoutError, FileNotFoundError):
            raise AIIntegrationError(f"Claude CLI not found or not responding. Please install and configure the claude command.")
        
        # Validate agent configuration
        if not self.config.implementation_agent:
            raise AIIntegrationError("Implementation agent not configured. Please set ai.implementation_agent in config.")


class AIIntegrationError(Exception):
    """Exception raised for AI integration errors."""
    
    def __init__(self, message: str, exit_code: Optional[int] = None):
        super().__init__(message)
        self.exit_code = exit_code


async def execute_ai_command(
    config: AIConfig,
    prompt: str,
    agent: str,
    working_directory: Optional[str] = None
) -> AICommandResult:
    """
    Execute Claude CLI command with specified parameters.
    
    Convenience function for direct AI command execution without full integration setup.
    
    Args:
        config: AI configuration
        prompt: Prompt to send to AI
        agent: Agent name to use
        working_directory: Working directory for command
        
    Returns:
        AICommandResult with execution details
    """
    integration = ClaudeIntegration(config)
    return await integration._execute_ai_command(prompt, agent, working_directory)


def format_implementation_prompt(
    issue: Issue,
    worktree_path: str,
    custom_prompt: Optional[str] = None,
    config: Optional[AIConfig] = None
) -> str:
    """
    Format implementation prompt for AI command.
    
    Convenience function for prompt formatting without full integration setup.
    
    Args:
        issue: Issue to implement
        worktree_path: Path to worktree
        custom_prompt: Optional custom prompt
        config: AI configuration (uses default if not provided)
        
    Returns:
        Formatted prompt string
    """
    from ..config import Config
    
    if not config:
        app_config = Config()
        config = app_config.ai
    
    integration = ClaudeIntegration(config)
    return integration._format_implementation_prompt(issue, worktree_path, custom_prompt)


def parse_ai_response(output: str, response_type: str = "implementation") -> AIResponse:
    """
    Parse AI response and extract actionable items.
    
    Convenience function for response parsing without full integration setup.
    
    Args:
        output: Raw AI response output
        response_type: Type of response
        
    Returns:
        Structured AIResponse
    """
    from ..config import Config
    
    config = Config().ai
    integration = ClaudeIntegration(config)
    return integration._parse_ai_response(output, response_type)


async def validate_ai_prerequisites(config: AIConfig) -> None:
    """
    Validate AI prerequisites are met.
    
    Convenience function for prerequisite validation.
    
    Args:
        config: AI configuration
        
    Raises:
        AIIntegrationError: If prerequisites are not met
    """
    integration = ClaudeIntegration(config)
    await integration._validate_prerequisites()
