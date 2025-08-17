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
            
            cmd = [self.command]
            
            # Add streaming output if enabled
            if self.config.enable_streaming and self.config.output_format:
                cmd.extend(["--output-format", self.config.output_format])
                # Claude CLI requires --verbose with stream-json when using -p
                if self.config.output_format == "stream-json":
                    cmd.append("--verbose")
            
            cmd.extend(["-p", prompt])
            return cmd
        
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
        Execute Claude CLI command with activity monitoring and stale detection.
        
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
            
            self.logger.info(f"Executing AI command: {' '.join(cmd[:3])}... (prompt truncated)")
            self.logger.debug(f"Full command: {' '.join(cmd)}")
            
            # Execute command
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=working_directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024  # 1MB limit for output
            )
            
            # Activity monitoring with stale detection
            if self.config.enable_activity_monitoring:
                return await self._monitor_ai_command_with_activity(process, start_time, agent, prompt)
            else:
                # Fallback to simple communicate() for backward compatibility
                stdout, stderr = await process.communicate()
                duration = time.time() - start_time
                
                output = stdout.decode('utf-8', errors='replace')
                error = stderr.decode('utf-8', errors='replace')
                success = process.returncode == 0
                
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

    async def _monitor_ai_command_with_activity(
        self,
        process: asyncio.subprocess.Process,
        start_time: float,
        agent: str,
        prompt: str
    ) -> AICommandResult:
        """
        Monitor AI command execution with activity tracking and stale detection.
        
        Args:
            process: The subprocess to monitor
            start_time: Command start time
            agent: Agent name for display
            prompt: Prompt sent to the agent
            
        Returns:
            AICommandResult with execution details
        """
        import time
        from rich.console import Console
        from rich.live import Live
        from rich.text import Text
        from rich.spinner import Spinner
        from rich.panel import Panel
        
        console = Console()
        
        # Activity tracking
        last_activity = None  # Will be set when first output is received
        output_lines = []
        error_lines = []
        total_output = ""
        total_error = ""
        output_bytes = 0
        error_bytes = 0
        
        # Output display setting
        import os
        show_output_toggle = self.config.show_ai_output or os.getenv('AUTO_SHOW_AI_OUTPUT', '').lower() in ('1', 'true', 'yes')
        
        # JSON streaming support
        streaming_enabled = self.config.enable_streaming and self.config.output_format == "stream-json"
        
        def parse_streaming_json(line: str) -> Optional[str]:
            """Parse a line of streaming JSON and extract content."""
            try:
                import json
                data = json.loads(line.strip())
                
                # Extract content based on common streaming JSON formats
                if isinstance(data, dict):
                    # Try different common field names for content
                    for field in ['content', 'text', 'message', 'data', 'output']:
                        if field in data and data[field]:
                            return str(data[field])
                    
                    # For tool use or other structured data, show the type
                    if 'type' in data:
                        type_name = data['type']
                        if type_name == 'tool_use' and 'name' in data:
                            return f"[Using tool: {data['name']}]"
                        elif type_name == 'message' and 'content' in data:
                            return str(data['content'])
                        else:
                            return f"[{type_name}]"
                
                # Fallback: convert entire object to string
                return str(data)
                
            except (json.JSONDecodeError, KeyError, TypeError):
                # Not valid JSON or unexpected format - return as-is
                return line.strip() if line.strip() else None
        
        # Progress display setup
        spinner = Spinner("dots", style="cyan")
        
        def create_status_display():
            """Create the status display panel."""
            elapsed = time.time() - start_time
            elapsed_str = f"{elapsed:.1f}s"
            
            # Calculate time since last activity
            if last_activity is None:
                activity_str = "Waiting for first output..."
                activity_style = "dim yellow"
                time_since_activity = 0  # Initialize for use in stale check
            else:
                time_since_activity = time.time() - last_activity
                activity_str = f"{time_since_activity:.1f}s ago" if time_since_activity > 0 else "now"
                activity_style = "bright_green"
            
            # Determine status state
            if last_activity is None:
                status_state = "🔄 Starting"
                status_style = "yellow"
            elif self.config.stale_timeout > 0 and time_since_activity > (self.config.stale_timeout * 0.8):
                status_state = "⚠️  Stale Warning"
                status_style = "red"
            else:
                status_state = "✅ Active"
                status_style = "green"
            
            # Status text
            status_text = Text()
            status_text.append(f"🤖 AI Agent: ", style="bold cyan")
            status_text.append(f"{agent}\n", style="bright_blue")
            
            # Show prompt (truncated)
            status_text.append(f"💬 Prompt: ", style="bold magenta")
            prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
            # Remove agent prefix if present
            if prompt_preview.startswith(f"agent-{agent}, "):
                prompt_preview = prompt_preview[len(f"agent-{agent}, "):]
            status_text.append(f"{prompt_preview}\n", style="dim white")
            
            status_text.append(f"⏱️  Elapsed: ", style="bold yellow")
            status_text.append(f"{elapsed_str}\n", style="bright_yellow")
            status_text.append(f"📡 Last Activity: ", style="bold green")
            status_text.append(f"{activity_str}\n", style=activity_style)
            status_text.append(f"📊 Status: ", style="bold magenta")
            status_text.append(f"{status_state}\n", style=status_style)
            
            # Output statistics
            if output_bytes > 0 or error_bytes > 0:
                status_text.append(f"📈 Output: ", style="bold blue")
                status_text.append(f"{len(output_lines)} lines, {output_bytes} bytes", style="bright_blue")
                if error_bytes > 0:
                    status_text.append(f" | {len(error_lines)} errors, {error_bytes} bytes", style="bright_red")
                status_text.append("\n")
            
            # Show command being executed
            status_text.append(f"🔧 Command: ", style="bold white")
            cmd_parts = ["claude"]
            if streaming_enabled:
                cmd_parts.extend(["--output-format", "stream-json", "--verbose"])
            cmd_parts.extend(["-p", f"\"agent-{agent}, ...\""])
            cmd_preview = " ".join(cmd_parts)
            status_text.append(f"{cmd_preview}\n", style="dim cyan")
            
            # Show process PID if available
            if hasattr(process, 'pid') and process.pid:
                status_text.append(f"🆔 PID: ", style="bold white")
                status_text.append(f"{process.pid}\n", style="dim white")
            
            # Show output status
            if show_output_toggle:
                status_text.append(f"📺 Output Display: ", style="bold white")

            if show_output_toggle and output_lines:
                # Show recent output lines
                recent_lines = output_lines[-3:] if len(output_lines) > 3 else output_lines
                if recent_lines:
                    status_text.append(f"\n📝 Recent Output:\n", style="bold blue")
                    for line in recent_lines:
                        if line.strip():
                            truncated = line[:80] + "..." if len(line) > 80 else line
                            status_text.append(f"   {truncated}\n", style="bright_black")
            
            # Stale warning
            if self.config.stale_timeout > 0 and last_activity is not None and time_since_activity > (self.config.stale_timeout * 0.8):
                remaining = self.config.stale_timeout - time_since_activity
                status_text.append(f"\n⚠️  Stale warning: {remaining:.1f}s remaining", style="bold red")
            
            return Panel(status_text, title="AI Command Monitor", border_style="cyan")
        
        # No special keyboard handling needed - Ctrl+C works by default
        
        # Start monitoring with Rich Live display
        try:
            with Live(create_status_display(), console=console, refresh_per_second=2) as live:
                while True:
                    # Check if process completed
                    if process.returncode is not None:
                        break
                    
                    # Try to read output
                    try:
                        # Read stdout with small timeout
                        if process.stdout:
                            try:
                                line = await asyncio.wait_for(
                                    process.stdout.readline(),
                                    timeout=0.1
                                )
                                if line:
                                    decoded_line = line.decode('utf-8', errors='replace').rstrip()
                                    content = None  # Initialize content variable
                                    
                                    # Process line based on streaming format
                                    if streaming_enabled:
                                        # Parse JSON streaming format
                                        content = parse_streaming_json(decoded_line)
                                        if content:
                                            output_lines.append(content)
                                            total_output += content + "\n"
                                        # Always add raw line for debugging
                                        total_output += f"[RAW] {decoded_line}\n"
                                    else:
                                        # Standard text output
                                        output_lines.append(decoded_line)
                                        total_output += decoded_line + "\n"
                                        content = decoded_line
                                    
                                    output_bytes += len(line)
                                    last_activity = time.time()
                                    
                                    if show_output_toggle:
                                        # Show parsed content or raw line
                                        display_line = content if content else decoded_line
                                        self.logger.info(f"AI: {display_line}")
                            except asyncio.TimeoutError:
                                pass
                        
                        # Read stderr with small timeout
                        if process.stderr:
                            try:
                                line = await asyncio.wait_for(
                                    process.stderr.readline(),
                                    timeout=0.1
                                )
                                if line:
                                    decoded_line = line.decode('utf-8', errors='replace').rstrip()
                                    error_lines.append(decoded_line)
                                    total_error += decoded_line + "\n"
                                    error_bytes += len(line)
                                    last_activity = time.time()
                                    
                                    if self.config.show_ai_output:
                                        self.logger.warning(f"AI Error: {decoded_line}")
                            except asyncio.TimeoutError:
                                pass
                    
                    except Exception as e:
                        self.logger.debug(f"Error reading AI output: {e}")
                    
                    # Check for stale timeout
                    if self.config.stale_timeout > 0 and last_activity is not None:
                        time_since_activity = time.time() - last_activity
                        if time_since_activity > self.config.stale_timeout:
                            self.logger.warning(f"AI command stalled - no output for {self.config.stale_timeout} seconds")
                            
                            # Kill the process
                            try:
                                process.kill()
                                await process.wait()
                            except:
                                pass
                            
                            duration = time.time() - start_time
                            return AICommandResult(
                                success=False,
                                output=total_output,
                                error=f"AI agent stalled - no output for {self.config.stale_timeout} seconds\n{total_error}",
                                exit_code=-1,
                                duration=duration
                            )
                    
                    # Update display
                    live.update(create_status_display())
                    
                    # Small sleep to prevent busy waiting
                    await asyncio.sleep(0.1)
                
                # Process completed - get final return code
                await process.wait()
                
                # Read any remaining output
                if process.stdout:
                    remaining_stdout = await process.stdout.read()
                    if remaining_stdout:
                        remaining_decoded = remaining_stdout.decode('utf-8', errors='replace')
                        total_output += remaining_decoded
                
                if process.stderr:
                    remaining_stderr = await process.stderr.read()
                    if remaining_stderr:
                        remaining_decoded = remaining_stderr.decode('utf-8', errors='replace')
                        total_error += remaining_decoded
        
        except Exception as e:
            self.logger.error(f"Error during AI command monitoring: {e}")
            # Try to kill process and get whatever output we have
            try:
                process.kill()
                await process.wait()
            except:
                pass
            
            duration = time.time() - start_time
            return AICommandResult(
                success=False,
                output=total_output,
                error=f"Monitoring error: {e}\n{total_error}",
                exit_code=-1,
                duration=duration
            )
        finally:
            # No cleanup needed for keyboard handling
            pass
        
        duration = time.time() - start_time
        success = process.returncode == 0
        
        if not success:
            self.logger.warning(f"AI command failed with exit code {process.returncode}")
        
        # Final status update
        console.print(f"\n✅ AI command completed in {duration:.1f}s", style="bold green" if success else "bold red")
        
        return AICommandResult(
            success=success,
            output=total_output,
            error=total_error,
            exit_code=process.returncode or 0,
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
