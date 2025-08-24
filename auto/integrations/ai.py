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
from typing import Any

from ..models import AIConfig, AIResponse, Issue
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
        self, issue: Issue, worktree_path: str, custom_prompt: str | None = None
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
                working_directory=worktree_path,
            )

            if not result.success:
                raise AIIntegrationError(
                    f"AI implementation failed: {result.error}", exit_code=result.exit_code
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
        custom_prompt: str | None = None,
        worktree_path: str | None = None,
    ) -> AIResponse:
        """
        Execute AI review for a pull request.

        Args:
            pr_number: Pull request number
            repository: Repository name
            custom_prompt: Optional custom prompt override
            worktree_path: Optional worktree path for review context

        Returns:
            AIResponse containing review results
        """
        try:
            await self._validate_prerequisites()

            prompt = await self._format_review_prompt(pr_number, repository, custom_prompt)

            self.logger.info(f"Running AI review for PR #{pr_number}")
            result = await self._execute_ai_command(
                prompt=prompt, agent=self.config.review_agent, working_directory=worktree_path
            )

            if not result.success:
                raise AIIntegrationError(
                    f"AI review failed: {result.error}", exit_code=result.exit_code
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
        review_comments: list[str],
        worktree_path: str,
        custom_prompt: str | None = None,
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
                prompt=prompt, agent=self.config.update_agent, working_directory=worktree_path
            )

            if not result.success:
                raise AIIntegrationError(
                    f"AI update failed: {result.error}", exit_code=result.exit_code
                )

            ai_response = self._parse_ai_response(result.output, "update")

            self.logger.info(f"AI update completed for issue {issue.id}")
            return ai_response

        except Exception as e:
            self.logger.error(f"AI update failed for issue {issue.id}: {e}")
            raise

    async def execute_update_from_review(
        self,
        repository: str,
        comments: str,
        custom_prompt: str | None = None,
        worktree_path: str | None = None,
    ) -> AIResponse:
        """
        Execute AI update to address review comments (review workflow variant).

        Args:
            repository: Repository name
            comments: Formatted review comments to address
            custom_prompt: Optional custom prompt override
            worktree_path: Optional worktree path for updates

        Returns:
            AIResponse containing update results
        """
        try:
            await self._validate_prerequisites()

            prompt = self._format_review_update_prompt(repository, comments, custom_prompt)

            self.logger.info(f"Running AI update for review comments in {repository}")
            result = await self._execute_ai_command(
                prompt=prompt, agent=self.config.update_agent, working_directory=worktree_path
            )

            if not result.success:
                raise AIIntegrationError(
                    f"AI review update failed: {result.error}", exit_code=result.exit_code
                )

            ai_response = self._parse_ai_response(result.output, "review_update")

            self.logger.info(f"AI review update completed for {repository}")
            return ai_response

        except Exception as e:
            self.logger.error(f"AI review update failed for {repository}: {e}")
            raise

    async def analyze_review_comments(
        self,
        comments: str,
        repository: str,
        custom_prompt: str | None = None,
        worktree_path: str | None = None,
    ) -> AIResponse:
        """
        Analyze review comments using AI for categorization and prioritization.

        Args:
            comments: Formatted review comments to analyze
            repository: Repository name
            custom_prompt: Optional custom prompt override
            worktree_path: Optional worktree path for analysis context

        Returns:
            AIResponse containing comment analysis results
        """
        try:
            await self._validate_prerequisites()

            if custom_prompt:
                prompt = custom_prompt
            else:
                prompt = f"""Analyze the following review comments and provide structured analysis:

Repository: {repository}

Review Comments:
{comments}

Please provide analysis in the following format:
1. Categorize each comment (bug, security, performance, code_quality, style, documentation, testing, suggestion, question, nitpick)
2. Assign priority (critical, high, medium, low)
3. Determine if actionable (requires code changes)
4. Estimate complexity (1-10 scale)
5. Suggest addressing order

Focus on identifying the most critical issues that need immediate attention."""

            self.logger.info(f"Analyzing review comments for {repository}")
            result = await self._execute_ai_command(
                prompt=prompt,
                agent=self.config.review_agent or "pull-request-reviewer",
                working_directory=worktree_path,
            )

            if not result.success:
                raise AIIntegrationError(
                    f"Comment analysis failed: {result.error}", exit_code=result.exit_code
                )

            ai_response = self._parse_ai_response(result.output, "comment_analysis")

            self.logger.info(f"Comment analysis completed for {repository}")
            return ai_response

        except Exception as e:
            self.logger.error(f"Comment analysis failed for {repository}: {e}")
            raise

    async def generate_comment_response(
        self,
        comment: str,
        context: dict[str, Any],
        repository: str,
        custom_prompt: str | None = None,
        worktree_path: str | None = None,
    ) -> AIResponse:
        """
        Generate professional response to a specific review comment.

        Args:
            comment: Individual review comment to respond to
            context: Additional context (file, line, issue details)
            repository: Repository name
            custom_prompt: Optional custom prompt override
            worktree_path: Optional worktree path for context

        Returns:
            AIResponse containing generated response
        """
        try:
            await self._validate_prerequisites()

            if custom_prompt:
                prompt = custom_prompt
            else:
                # Build context information
                context_info = []
                if context.get("file_path"):
                    context_info.append(f"File: {context['file_path']}")
                if context.get("line_number"):
                    context_info.append(f"Line: {context['line_number']}")
                if context.get("issue_title"):
                    context_info.append(f"Original Issue: {context['issue_title']}")

                context_str = "\n".join(context_info) if context_info else "General comment"

                prompt = f"""Generate a professional response to this review comment:

Comment: {comment}

Context:
{context_str}
Repository: {repository}

Please provide:
1. Acknowledgment of the feedback
2. Planned action to address the comment (if actionable)
3. Implementation approach (if code changes needed)
4. Any questions or clarifications needed

Keep the response professional, concise, and constructive. Show that you understand the concern and have a plan to address it."""

            self.logger.debug(f"Generating response for comment in {repository}")
            result = await self._execute_ai_command(
                prompt=prompt,
                agent=self.config.update_agent or "coder",
                working_directory=worktree_path,
            )

            if not result.success:
                raise AIIntegrationError(
                    f"Comment response generation failed: {result.error}",
                    exit_code=result.exit_code,
                )

            ai_response = self._parse_ai_response(result.output, "comment_response")

            self.logger.debug(f"Comment response generated for {repository}")
            return ai_response

        except Exception as e:
            self.logger.error(f"Comment response generation failed for {repository}: {e}")
            raise

    async def execute_targeted_update(
        self,
        update_description: str,
        target_files: list[str],
        worktree_path: str,
        repository: str,
        validation_steps: list[str] | None = None,
        custom_prompt: str | None = None,
    ) -> AIResponse:
        """
        Execute targeted code update for specific files and requirements.

        Args:
            update_description: Description of what needs to be updated
            target_files: List of files to focus on
            worktree_path: Path to worktree for updates
            repository: Repository name
            validation_steps: Optional validation steps to perform
            custom_prompt: Optional custom prompt override

        Returns:
            AIResponse containing update results
        """
        try:
            await self._validate_prerequisites()

            if custom_prompt:
                prompt = custom_prompt
            else:
                files_str = "\n".join(f"- {file}" for file in target_files)
                validation_str = ""
                if validation_steps:
                    validation_str = f"""

Validation Requirements:
{chr(10).join(f"- {step}" for step in validation_steps)}"""

                prompt = f"""Implement the following targeted update:

Update Description: {update_description}

Target Files:
{files_str}

Repository: {repository}{validation_str}

Please:
1. Focus on the specified files
2. Make precise, targeted changes to address the requirements
3. Ensure changes are consistent with existing code style
4. Test your changes if possible
5. Provide clear documentation of what was changed

Be thorough but focused - only modify what's necessary to address the specific requirements."""

            self.logger.info(f"Executing targeted update in {repository}")
            result = await self._execute_ai_command(
                prompt=prompt,
                agent=self.config.update_agent or "coder",
                working_directory=worktree_path,
            )

            if not result.success:
                raise AIIntegrationError(
                    f"Targeted update failed: {result.error}", exit_code=result.exit_code
                )

            ai_response = self._parse_ai_response(result.output, "targeted_update")

            self.logger.info(f"Targeted update completed for {repository}")
            return ai_response

        except Exception as e:
            self.logger.error(f"Targeted update failed for {repository}: {e}")
            raise

    async def generate_pr_description(
        self, issue: Issue, worktree_path: str, file_changes: list[dict], commands: list[str]
    ) -> str:
        """
        Generate a pull request description by asking Claude to analyze the changes.

        Uses a separate Claude call to create a concise, meaningful PR description
        based on the actual implementation rather than dumping the conversation.

        Args:
            issue: The issue that was implemented
            worktree_path: Path to the worktree with changes
            file_changes: List of file changes from AI implementation
            commands: List of commands executed during implementation

        Returns:
            Generated PR description as markdown text

        Raises:
            AIIntegrationError: If PR description generation fails
        """
        try:
            await self._validate_prerequisites()

            # Build context about the changes
            changes_summary = ""
            if file_changes:
                changes_summary += "\nFiles Changed:\n"
                for change in file_changes[:10]:  # Limit to first 10 files
                    action = change.get("action", "modified")
                    path = change.get("path", "unknown")
                    changes_summary += f"- {action.title()}: {path}\n"
                if len(file_changes) > 10:
                    changes_summary += f"... and {len(file_changes) - 10} more files\n"

            commands_summary = ""
            if commands:
                commands_summary += "\nCommands Executed:\n"
                for command in commands[:5]:  # Limit to first 5 commands
                    commands_summary += f"- {command}\n"
                if len(commands) > 5:
                    commands_summary += f"... and {len(commands) - 5} more commands\n"

            # Create prompt for PR description generation
            prompt = f"""Generate a professional pull request description for the following implementation:

Issue Title: {issue.title}
Issue Description: {issue.description}
{changes_summary}
{commands_summary}

Please create a concise, well-structured PR description that includes:
1. A brief summary of what was implemented
2. Key changes and their purpose
3. Any important notes for reviewers

Format as proper markdown for GitHub. Keep it professional and informative but concise.
Do not include the full file list or command list - just highlight the most important changes.
Include appropriate sections like ## Summary, ## Changes, etc."""

            self.logger.info(f"Generating PR description for issue {issue.id}")
            result = await self._execute_ai_command(
                prompt=prompt,
                agent="git-commit-expert",  # Use commit expert for documentation
                working_directory=worktree_path,
            )

            if not result.success:
                raise AIIntegrationError(
                    f"PR description generation failed: {result.error}", exit_code=result.exit_code
                )

            # Extract the actual PR description from the streaming JSON output
            description = self._extract_result_from_output(result.output)

            # GitHub has a 65536 character limit for PR bodies - truncate if necessary
            from ..workflows.pr_create import truncate_pr_description

            description = truncate_pr_description(description)

            self.logger.info(
                f"PR description generated for issue {issue.id} ({len(description)} characters)"
            )
            return description

        except Exception as e:
            self.logger.error(f"PR description generation failed for issue {issue.id}: {e}")
            # Fall back to a simple description rather than failing
            fallback = f"""## Summary

Implemented: {issue.title}

## Description

{issue.description}

## Changes

This PR implements the requested functionality with {len(file_changes)} file changes and {len(commands)} commands executed.
"""
            self.logger.warning(f"Using fallback PR description for issue {issue.id}")
            return fallback

    def _build_ai_command(self, prompt: str, agent: str | None = None) -> list[str]:
        """
        Build AI command based on configured format.

        Args:
            prompt: The prompt to send to the AI
            agent: Optional agent name

        Returns:
            List of command arguments ready for execution
        """
        command_format = getattr(self.config, "command_format", "claude")

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
            template = getattr(self.config, "command_template", None)
            if template:
                return self._parse_custom_template(template, prompt, agent)
            else:
                self.logger.warning(
                    "Custom command format specified but no command_template provided, falling back to legacy"
                )
                return self._build_legacy_command(prompt, agent)

        else:
            # Default/legacy behavior for backward compatibility
            return self._build_legacy_command(prompt, agent)

    def _build_legacy_command(self, prompt: str, agent: str | None = None) -> list[str]:
        """Build command using legacy format for backward compatibility."""
        cmd = [self.command]
        if agent:
            cmd.extend(["--agent", agent])
        cmd.append(prompt)
        return cmd

    def _parse_custom_template(
        self, template: str, prompt: str, agent: str | None = None
    ) -> list[str]:
        """
        Parse custom command template.

        Template variables:
        - {command}: The AI command
        - {agent}: The agent name (if provided)
        - {prompt}: The prompt text

        Example: "{command} -p \"agent-{agent}, {prompt}\""
        """
        # Replace template variables
        formatted = template.format(command=self.command, agent=agent or "", prompt=prompt)

        # Simple parsing - split by spaces but respect quoted strings
        import shlex

        try:
            return shlex.split(formatted)
        except ValueError as e:
            self.logger.error(f"Failed to parse custom command template: {e}")
            # Fallback to legacy format
            return self._build_legacy_command(prompt, agent)

    async def _execute_ai_command(
        self, prompt: str, agent: str, working_directory: str | None = None
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
                limit=1024 * 1024,  # 1MB limit for output
            )

            # Activity monitoring with stale detection
            if self.config.enable_activity_monitoring:
                return await self._monitor_ai_command_with_activity(
                    process, start_time, agent, prompt
                )
            else:
                # Fallback to simple communicate() for backward compatibility
                stdout, stderr = await process.communicate()
                duration = time.time() - start_time

                output = stdout.decode("utf-8", errors="replace")
                error = stderr.decode("utf-8", errors="replace")
                success = process.returncode == 0

                return AICommandResult(
                    success=success,
                    output=output,
                    error=error,
                    exit_code=process.returncode or 0,
                    duration=duration,
                )

        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"Failed to execute AI command: {e}")
            return AICommandResult(
                success=False, output="", error=str(e), exit_code=-1, duration=duration
            )

    async def _monitor_ai_command_with_activity(
        self, process: asyncio.subprocess.Process, start_time: float, agent: str, prompt: str
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
        from rich.panel import Panel
        from rich.text import Text

        console = Console()

        # Activity tracking
        last_activity = None  # Will be set when first output is received
        output_lines: list[str] = []
        error_lines: list[str] = []
        total_output = ""
        total_error = ""
        output_bytes = 0
        error_bytes = 0

        # Output display setting
        import os

        show_output_toggle = self.config.show_ai_output or os.getenv(
            "AUTO_SHOW_AI_OUTPUT", ""
        ).lower() in ("1", "true", "yes")

        # JSON streaming support
        streaming_enabled = (
            self.config.enable_streaming and self.config.output_format == "stream-json"
        )

        def parse_streaming_json(line: str) -> str | None:
            """Parse a line of streaming JSON and extract content."""
            try:
                import json

                data = json.loads(line.strip())

                # Extract content based on common streaming JSON formats
                if isinstance(data, dict):
                    # Try different common field names for content
                    for field in ["content", "text", "message", "data", "output"]:
                        if field in data and data[field]:
                            return str(data[field])

                    # For tool use or other structured data, show the type
                    if "type" in data:
                        type_name = data["type"]
                        if type_name == "tool_use" and "name" in data:
                            return f"[Using tool: {data['name']}]"
                        elif type_name == "message" and "content" in data:
                            return str(data["content"])
                        else:
                            return f"[{type_name}]"

                # Fallback: convert entire object to string
                return str(data)

            except (json.JSONDecodeError, KeyError, TypeError):
                # Not valid JSON or unexpected format - return as-is
                return line.strip() if line.strip() else None

        # Progress display setup
        # Note: Spinner setup removed as it was unused

        def create_status_display() -> Any:
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
                activity_str = (
                    f"{time_since_activity:.1f}s ago" if time_since_activity > 0 else "now"
                )
                activity_style = "bright_green"

            # Determine status state
            if last_activity is None:
                status_state = "🔄 Starting"
                status_style = "yellow"
            elif self.config.stale_timeout > 0 and time_since_activity > (
                self.config.stale_timeout * 0.8
            ):
                status_state = "⚠️  Stale Warning"
                status_style = "red"
            else:
                status_state = "✅ Active"
                status_style = "green"

            # Status text
            status_text = Text()
            status_text.append("🤖 AI Agent: ", style="bold cyan")
            status_text.append(f"{agent}\n", style="bright_blue")

            # Show prompt (truncated)
            status_text.append("💬 Prompt: ", style="bold magenta")
            prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
            # Remove agent prefix if present
            if prompt_preview.startswith(f"agent-{agent}, "):
                prompt_preview = prompt_preview[len(f"agent-{agent}, ") :]
            status_text.append(f"{prompt_preview}\n", style="dim white")

            status_text.append("⏱️  Elapsed: ", style="bold yellow")
            status_text.append(f"{elapsed_str}\n", style="bright_yellow")
            status_text.append("📡 Last Activity: ", style="bold green")
            status_text.append(f"{activity_str}\n", style=activity_style)
            status_text.append("📊 Status: ", style="bold magenta")
            status_text.append(f"{status_state}\n", style=status_style)

            # Output statistics
            if output_bytes > 0 or error_bytes > 0:
                status_text.append("📈 Output: ", style="bold blue")
                status_text.append(
                    f"{len(output_lines)} lines, {output_bytes} bytes", style="bright_blue"
                )
                if error_bytes > 0:
                    status_text.append(
                        f" | {len(error_lines)} errors, {error_bytes} bytes", style="bright_red"
                    )
                status_text.append("\n")

            # Show command being executed
            status_text.append("🔧 Command: ", style="bold white")
            cmd_parts = ["claude"]
            if streaming_enabled:
                cmd_parts.extend(["--output-format", "stream-json", "--verbose"])
            cmd_parts.extend(["-p", f'"agent-{agent}, ..."'])
            cmd_preview = " ".join(cmd_parts)
            status_text.append(f"{cmd_preview}\n", style="dim cyan")

            # Show process PID if available
            if hasattr(process, "pid") and process.pid:
                status_text.append("🆔 PID: ", style="bold white")
                status_text.append(f"{process.pid}\n", style="dim white")

            # Show output status
            if show_output_toggle:
                status_text.append("📺 Output Display: ", style="bold white")

            if show_output_toggle and output_lines:
                # Show recent output lines
                recent_lines = output_lines[-3:] if len(output_lines) > 3 else output_lines
                if recent_lines:
                    status_text.append("\n📝 Recent Output:\n", style="bold blue")
                    for line in recent_lines:
                        if line.strip():
                            truncated = line[:80] + "..." if len(line) > 80 else line
                            status_text.append(f"   {truncated}\n", style="bright_black")

            # Stale warning
            if (
                self.config.stale_timeout > 0
                and last_activity is not None
                and time_since_activity > (self.config.stale_timeout * 0.8)
            ):
                remaining = self.config.stale_timeout - time_since_activity
                status_text.append(
                    f"\n⚠️  Stale warning: {remaining:.1f}s remaining", style="bold red"
                )

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
                                    process.stdout.readline(), timeout=0.1
                                )
                                if line:
                                    decoded_line = line.decode("utf-8", errors="replace").rstrip()
                                    content = None  # Initialize content variable

                                    # Process line based on streaming format
                                    if streaming_enabled:
                                        # Parse JSON streaming format
                                        content = parse_streaming_json(decoded_line)
                                        if content:
                                            output_lines.append(content)
                                        # Add raw JSON line for processing by extract_result_from_output
                                        total_output += decoded_line + "\n"
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
                            except TimeoutError:
                                pass

                        # Read stderr with small timeout
                        if process.stderr:
                            try:
                                line = await asyncio.wait_for(
                                    process.stderr.readline(), timeout=0.1
                                )
                                if line:
                                    decoded_line = line.decode("utf-8", errors="replace").rstrip()
                                    error_lines.append(decoded_line)
                                    total_error += decoded_line + "\n"
                                    error_bytes += len(line)
                                    last_activity = time.time()

                                    if self.config.show_ai_output:
                                        self.logger.warning(f"AI Error: {decoded_line}")
                            except TimeoutError:
                                pass

                    except Exception as e:
                        self.logger.debug(f"Error reading AI output: {e}")

                    # Check for stale timeout
                    if self.config.stale_timeout > 0 and last_activity is not None:
                        time_since_activity = time.time() - last_activity
                        if time_since_activity > self.config.stale_timeout:
                            self.logger.warning(
                                f"AI command stalled - no output for {self.config.stale_timeout} seconds"
                            )

                            # Kill the process
                            try:
                                process.kill()
                                await process.wait()
                            except Exception:
                                pass

                            duration = time.time() - start_time
                            return AICommandResult(
                                success=False,
                                output=total_output,
                                error=f"AI agent stalled - no output for {self.config.stale_timeout} seconds\n{total_error}",
                                exit_code=-1,
                                duration=duration,
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
                        remaining_decoded = remaining_stdout.decode("utf-8", errors="replace")
                        total_output += remaining_decoded

                if process.stderr:
                    remaining_stderr = await process.stderr.read()
                    if remaining_stderr:
                        remaining_decoded = remaining_stderr.decode("utf-8", errors="replace")
                        total_error += remaining_decoded

        except Exception as e:
            self.logger.error(f"Error during AI command monitoring: {e}")
            # Try to kill process and get whatever output we have
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass

            duration = time.time() - start_time
            return AICommandResult(
                success=False,
                output=total_output,
                error=f"Monitoring error: {e}\n{total_error}",
                exit_code=-1,
                duration=duration,
            )
        finally:
            # No cleanup needed for keyboard handling
            pass

        duration = time.time() - start_time
        success = process.returncode == 0

        if not success:
            self.logger.warning(f"AI command failed with exit code {process.returncode}")

        # Final status update
        console.print(
            f"\n✅ AI command completed in {duration:.1f}s",
            style="bold green" if success else "bold red",
        )

        return AICommandResult(
            success=success,
            output=total_output,
            error=total_error,
            exit_code=process.returncode or 0,
            duration=duration,
        )

    def _format_implementation_prompt(
        self, issue: Issue, worktree_path: str, custom_prompt: str | None = None
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
                assignee=issue.assignee or "",
            )
        except KeyError as e:
            self.logger.warning(f"Template variable {e} not found, using fallback")
            formatted_prompt = f"{template}\n\n{context}"

        return formatted_prompt

    async def _format_review_prompt(
        self, pr_number: int, repository: str, custom_prompt: str | None = None
    ) -> str:
        """
        Format comprehensive review prompt for PR review.

        Gathers PR details, diff, and applies review template with proper context.
        """
        if custom_prompt:
            return f"Review PR #{pr_number} in {repository}:\n\n{custom_prompt}"

        try:
            # Import here to avoid circular imports
            from ..integrations.prompts import PromptManager

            # Get PR details
            pr_details = await self._get_pr_details(pr_number, repository)

            # Get PR diff
            pr_diff = await self._get_pr_diff(pr_number, repository)

            # Load review template
            prompt_manager = PromptManager()
            try:
                template = prompt_manager.load_prompt_template("review")

                # Format template with variables
                formatted_prompt = template.content.format(
                    repository=repository,
                    pr_number=pr_number,
                    pr_description=pr_details.get("description", ""),
                    changed_files=", ".join(pr_details.get("changed_files", [])),
                    diff_content=pr_diff,
                )

                return formatted_prompt

            except Exception as e:
                self.logger.warning(f"Failed to load review template: {e}")
                # Fallback to basic template
                return self._create_fallback_review_prompt(
                    pr_number, repository, pr_details, pr_diff
                )

        except Exception as e:
            self.logger.error(f"Error formatting review prompt: {e}")
            # Final fallback
            fallback_prompt = (
                self.config.review_prompt
                or "Please review this pull request thoroughly for bugs, security issues, performance, and code quality."
            )
            return f"Review PR #{pr_number} in {repository}:\n\n{fallback_prompt}"

    async def _get_pr_details(self, pr_number: int, repository: str) -> dict[str, Any]:
        """
        Get PR details including description and changed files.

        Args:
            pr_number: Pull request number
            repository: Repository name

        Returns:
            Dictionary with PR details
        """
        try:
            from ..utils.shell import run_command

            # Get PR basic details
            result = run_command(
                f"gh pr view {pr_number} --repo {repository} --json title,body,files", timeout=30
            )

            pr_data = json.loads(result.stdout)

            # Extract changed files
            changed_files = []
            if "files" in pr_data:
                for file_info in pr_data["files"]:
                    changed_files.append(file_info.get("path", ""))

            return {
                "title": pr_data.get("title", ""),
                "description": f"{pr_data.get('title', '')}\n\n{pr_data.get('body', '')}",
                "changed_files": changed_files,
            }

        except Exception as e:
            self.logger.warning(f"Failed to get PR details: {e}")
            return {
                "title": f"PR #{pr_number}",
                "description": f"Pull request #{pr_number} in {repository}",
                "changed_files": [],
            }

    async def _get_pr_diff(self, pr_number: int, repository: str) -> str:
        """
        Get PR diff content.

        Args:
            pr_number: Pull request number
            repository: Repository name

        Returns:
            PR diff as string
        """
        try:
            from ..utils.shell import run_command

            # Get PR diff
            result = run_command(f"gh pr diff {pr_number} --repo {repository}", timeout=30)

            return result.stdout

        except Exception as e:
            self.logger.warning(f"Failed to get PR diff: {e}")
            return f"[Unable to fetch diff for PR #{pr_number}]"

    def _create_fallback_review_prompt(
        self, pr_number: int, repository: str, pr_details: dict[str, Any], pr_diff: str
    ) -> str:
        """
        Create fallback review prompt when template loading fails.

        Args:
            pr_number: Pull request number
            repository: Repository name
            pr_details: PR details dictionary
            pr_diff: PR diff content

        Returns:
            Fallback review prompt
        """
        prompt = f"""Review this pull request thoroughly for bugs, security issues, performance, and code quality.

**PR Context:**
Repository: {repository}
PR Number: #{pr_number}
Title: {pr_details.get("title", "N/A")}

**Description:**
{pr_details.get("description", "No description available")}

**Files Changed:**
{", ".join(pr_details.get("changed_files", [])) or "No files listed"}

**Code Changes:**
```diff
{pr_diff}
```

**Please provide:**
1. Overall assessment of the code quality
2. Any bugs or potential issues identified
3. Security concerns
4. Performance considerations
5. Suggestions for improvement
6. Recommendation: APPROVE, REQUEST_CHANGES, or COMMENT

Be thorough and specific in your feedback."""

        return prompt

    def _format_review_update_prompt(
        self, repository: str, comments: str, custom_prompt: str | None = None
    ) -> str:
        """
        Format prompt for addressing review comments.

        Args:
            repository: Repository name
            comments: Formatted review comments
            custom_prompt: Optional custom prompt override

        Returns:
            Formatted prompt for AI update
        """
        if custom_prompt:
            return f"Repository: {repository}\n\nReview Comments:\n{comments}\n\n{custom_prompt}"

        try:
            # Try to load review update template
            from ..integrations.prompts import PromptManager

            prompt_manager = PromptManager()
            try:
                template = prompt_manager.load_prompt_template("review-update")

                # Format template with variables
                formatted_prompt = template.content.format(
                    repository=repository,
                    review_comments=comments,
                    pr_description="Review comments update",  # Basic fallback
                )

                return formatted_prompt

            except Exception as e:
                self.logger.warning(f"Failed to load review-update template: {e}")
                # Fallback to basic template
                return self._create_fallback_update_prompt(repository, comments)

        except Exception as e:
            self.logger.error(f"Error formatting review update prompt: {e}")
            # Final fallback
            fallback_prompt = (
                self.config.update_prompt or "Please address the following review comments:"
            )
            return f"Repository: {repository}\n\n{fallback_prompt}\n\nReview Comments:\n{comments}"

    def _create_fallback_update_prompt(self, repository: str, comments: str) -> str:
        """Create fallback update prompt when template loading fails."""
        return f"""You are tasked with addressing review comments on a pull request.

**Repository:** {repository}

**Review Comments to Address:**
{comments}

**Instructions:**
1. Carefully read and understand each review comment
2. Make the necessary code changes to address the feedback
3. Ensure your changes don't introduce new issues
4. Test your changes if possible
5. Commit your changes with clear commit messages

**Focus Areas:**
- Fix any bugs or logic errors mentioned
- Address security concerns
- Implement performance improvements
- Improve code quality and readability
- Add or update tests as needed

Please implement the necessary changes to address all valid review feedback."""

    def _format_update_prompt(
        self, issue: Issue, review_comments: list[str], custom_prompt: str | None = None
    ) -> str:
        """Format update prompt to address review comments."""
        comments_text = "\n".join(f"- {comment}" for comment in review_comments)

        if custom_prompt:
            return f"Issue #{issue.id}: {issue.title}\n\nReview Comments:\n{comments_text}\n\n{custom_prompt}"

        template = self.config.update_prompt
        try:
            formatted_prompt = template.format(
                issue_id=issue.id, title=issue.title, comments=comments_text
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
            # First, extract the actual result from Claude's streaming JSON output
            extracted_output = self._extract_result_from_output(output)

            # Try to parse as structured JSON first
            if extracted_output.strip().startswith("{"):
                try:
                    data = json.loads(extracted_output)

                    # Use provided content or create summary
                    content = data.get("content")
                    if not content or len(content) > 1000:
                        # Create summary if content is missing or too long
                        file_changes = data.get("file_changes", [])
                        commands = data.get("commands", [])
                        content = self._create_response_summary(
                            extracted_output, response_type, file_changes, commands
                        )

                    return AIResponse(
                        success=True,
                        response_type=response_type,
                        content=content,
                        file_changes=data.get("file_changes", []),
                        commands=data.get("commands", []),
                        metadata=data.get("metadata", {}),
                    )
                except json.JSONDecodeError:
                    pass

            # Parse freeform response
            file_changes = self._extract_file_changes(extracted_output)
            commands = self._extract_commands(extracted_output)

            # Create a summary instead of storing the entire output
            summary = self._create_response_summary(
                extracted_output, response_type, file_changes, commands
            )

            return AIResponse(
                success=True,
                response_type=response_type,
                content=summary,
                file_changes=file_changes,
                commands=commands,
                metadata={},
            )

        except Exception as e:
            self.logger.error(f"Failed to parse AI response: {e}")
            # Return basic response even if parsing fails
            # In case of error, try to extract result from original output
            try:
                extracted_output = self._extract_result_from_output(output)
            except Exception:
                extracted_output = output

            return AIResponse(
                success=False,
                response_type=response_type,
                content=extracted_output,
                file_changes=[],
                commands=[],
                metadata={"parse_error": str(e)},
            )

    def _create_response_summary(
        self, output: str, response_type: str, file_changes: list[dict], commands: list[str]
    ) -> str:
        """
        Create a concise summary of the AI response instead of storing the entire output.

        Args:
            output: Full AI response output
            response_type: Type of response (implementation, review, update)
            file_changes: Extracted file changes
            commands: Extracted commands

        Returns:
            Concise summary string
        """
        # Create a summary based on what was accomplished
        summary_parts = []

        if response_type == "implementation":
            summary_parts.append("✅ AI implementation completed successfully")
        elif response_type == "review":
            summary_parts.append("✅ AI review completed")
        elif response_type == "update":
            summary_parts.append("✅ AI update completed")
        else:
            summary_parts.append(f"✅ AI {response_type} completed")

        # Add file changes summary
        if file_changes:
            summary_parts.append(f"📁 Modified {len(file_changes)} file(s)")

        # Add commands summary
        if commands:
            summary_parts.append(f"⚡ Executed {len(commands)} command(s)")

        # Try to extract a brief summary from the beginning of the output
        lines = output.split("\n")
        brief_summary = ""
        for line in lines[:10]:  # Look at first 10 lines
            line = line.strip()
            if line and not line.startswith("[") and not line.startswith("{") and len(line) > 20:
                # Found a meaningful line
                brief_summary = line[:200] + ("..." if len(line) > 200 else "")
                break

        if brief_summary:
            summary_parts.append(f"📝 {brief_summary}")

        return " | ".join(summary_parts)

    def _extract_file_changes(self, output: str) -> list[dict[str, str]]:
        """Extract file changes from AI response text."""
        file_changes = []

        # Look for common patterns indicating file changes
        lines = output.split("\n")
        for line in lines:
            line = line.strip()

            # Pattern: "Modified: path/to/file.py"
            if line.startswith(("Modified:", "Created:", "Updated:", "Changed:")):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    action = parts[0].lower()
                    file_path = parts[1].strip()
                    file_changes.append({"action": action, "path": file_path})

            # Pattern: "- src/components/Button.tsx (modified)"
            elif line.startswith("-") and ("(modified)" in line or "(created)" in line):
                if "(modified)" in line:
                    file_path = line.replace("-", "").replace("(modified)", "").strip()
                    file_changes.append({"action": "modified", "path": file_path})
                elif "(created)" in line:
                    file_path = line.replace("-", "").replace("(created)", "").strip()
                    file_changes.append({"action": "created", "path": file_path})

        return file_changes

    def _extract_commands(self, output: str) -> list[str]:
        """Extract commands from AI response text."""
        commands = []

        lines = output.split("\n")
        in_code_block = False

        for line in lines:
            line = line.strip()

            # Check for code blocks
            if line.startswith("```"):
                in_code_block = not in_code_block
                continue

            # Extract commands from code blocks or command patterns
            if in_code_block and line and not line.startswith("#"):
                commands.append(line)
            elif line.startswith("Run:") or line.startswith("Execute:"):
                cmd = line.split(":", 1)[1].strip()
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
                    [
                        "find",
                        ".",
                        "-type",
                        "f",
                        "-name",
                        "*.py",
                        "-o",
                        "-name",
                        "*.js",
                        "-o",
                        "-name",
                        "*.ts",
                        "-o",
                        "-name",
                        "*.tsx",
                    ],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    files = result.stdout.strip().split("\n")[:20]  # Limit to 20 files
                    context_parts.append("Key files:\n" + "\n".join(files))
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

    def _extract_result_from_output(self, output: str) -> str:
        """
        Extract the final result from Claude's JSON stream output.

        Claude with --output-format stream-json outputs multiple JSON objects,
        with the final result in format: {type: "result", result: "actual content"}

        Args:
            output: Raw output from Claude command

        Returns:
            Extracted result content, or original output if no result found
        """
        try:
            import json

            lines = output.split("\n")
            last_result = None

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Skip raw debug lines
                if line.startswith("[RAW]"):
                    continue

                try:
                    data = json.loads(line)
                    if isinstance(data, dict) and data.get("type") == "result":
                        # Found a result object, store it (we want the last one)
                        last_result = str(data.get("result", ""))
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Not valid JSON or wrong format, skip
                    continue

            if last_result is not None:
                self.logger.debug(
                    f"Extracted result from JSON stream: {len(last_result)} characters"
                )
                return last_result
            else:
                # No result object found, return original output (fallback for non-streaming)
                self.logger.debug("No result object found in output, using full output")
                return output.strip()

        except Exception as e:
            self.logger.warning(f"Failed to extract result from output: {e}")
            # Fallback to original output
            return output.strip()

    async def _validate_prerequisites(self) -> None:
        """Validate AI prerequisites are met."""
        # Check if Claude CLI is available
        try:
            result = await asyncio.create_subprocess_exec(
                self.command,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(result.communicate(), timeout=10)

            if result.returncode != 0:
                raise AIIntegrationError(
                    f"Claude CLI not working properly (exit code: {result.returncode})"
                )

        except (TimeoutError, FileNotFoundError) as e:
            raise AIIntegrationError(
                "Claude CLI not found or not responding. Please install and configure the claude command."
            ) from e

        # Validate agent configuration
        if not self.config.implementation_agent:
            raise AIIntegrationError(
                "Implementation agent not configured. Please set ai.implementation_agent in config."
            )


class AIIntegrationError(Exception):
    """Exception raised for AI integration errors."""

    def __init__(self, message: str, exit_code: int | None = None):
        super().__init__(message)
        self.exit_code = exit_code


async def execute_ai_command(
    config: AIConfig, prompt: str, agent: str, working_directory: str | None = None
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
    custom_prompt: str | None = None,
    config: AIConfig | None = None,
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


__all__ = [
    "ClaudeIntegration",
    "AICommandResult",
    "AIIntegrationError",
    "execute_ai_command",
    "format_implementation_prompt",
    "parse_ai_response",
    "validate_ai_prerequisites",
]
