"""AI integration module for Claude CLI command execution."""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from auto.models import AICommand, AIConfig, AIFileChange, AIResponse, Issue
from auto.utils.logger import get_logger
from auto.utils.shell import run_command

logger = get_logger(__name__)


class AIError(Exception):
    """AI integration error."""
    pass


class ClaudeIntegration:
    """Claude CLI integration with agent selection and prompt formatting."""
    
    def __init__(self, config: AIConfig):
        """Initialize Claude integration.
        
        Args:
            config: AI configuration
        """
        self.config = config
        self.command = config.command
        self.implementation_agent = config.implementation_agent
        self.review_agent = config.review_agent
        self.update_agent = config.update_agent
        self.timeout = config.timeout
        self.max_retries = config.max_retries
        self.include_file_context = config.include_file_context
        self.response_format = config.response_format
    
    def validate_ai_prerequisites(self) -> None:
        """Validate Claude CLI availability and agent configuration.
        
        Raises:
            AIError: If prerequisites are not met
        """
        try:
            # Check if Claude CLI is available
            result = run_command([self.command, "--version"], capture_output=True, timeout=10)
            if result.returncode != 0:
                raise AIError(f"Claude CLI not available. Please install {self.command}")
            
            logger.debug(f"Claude CLI version: {result.stdout.strip()}")
            
            # Validate agent configuration
            agents = [self.implementation_agent, self.review_agent, self.update_agent]
            for agent in agents:
                if not agent or not isinstance(agent, str):
                    raise AIError(f"Invalid agent configuration: {agent}")
            
        except subprocess.TimeoutExpired:
            raise AIError(f"Claude CLI command timed out. Check {self.command} installation")
        except Exception as e:
            raise AIError(f"Failed to validate Claude CLI: {e}")
    
    def execute_ai_command(
        self,
        prompt: str,
        agent: str,
        working_directory: Optional[str] = None,
        additional_args: Optional[List[str]] = None
    ) -> str:
        """Execute Claude CLI command with specific agent.
        
        Args:
            prompt: Prompt to send to Claude
            agent: Agent name to use
            working_directory: Working directory for command execution
            additional_args: Additional command-line arguments
            
        Returns:
            Raw Claude response
            
        Raises:
            AIError: If command fails or times out
        """
        # Prepare command
        cmd = [self.command]
        if agent:
            cmd.extend(["--agent", agent])
        
        if additional_args:
            cmd.extend(additional_args)
        
        # Add prompt as final argument or use stdin
        if len(prompt) < 1000:  # Use command line for short prompts
            cmd.append(prompt)
            stdin_input = None
        else:  # Use stdin for longer prompts
            stdin_input = prompt
        
        logger.debug(f"Executing AI command: {' '.join(cmd[:3])}... (agent: {agent})")
        
        # Execute with retries
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                result = run_command(
                    cmd,
                    capture_output=True,
                    timeout=self.timeout,
                    cwd=working_directory,
                    input=stdin_input
                )
                
                if result.returncode == 0:
                    response = result.stdout.strip()
                    logger.debug(f"AI command succeeded (attempt {attempt + 1})")
                    return response
                else:
                    error_msg = result.stderr.strip() or "Unknown error"
                    last_error = AIError(f"Claude CLI failed: {error_msg}")
                    
                    if attempt < self.max_retries:
                        logger.warning(f"AI command failed (attempt {attempt + 1}), retrying: {error_msg}")
                    else:
                        logger.error(f"AI command failed after {self.max_retries + 1} attempts: {error_msg}")
                        
            except subprocess.TimeoutExpired:
                last_error = AIError(f"Claude CLI command timed out after {self.timeout} seconds")
                if attempt < self.max_retries:
                    logger.warning(f"AI command timed out (attempt {attempt + 1}), retrying")
                else:
                    logger.error(f"AI command timed out after {self.max_retries + 1} attempts")
            except Exception as e:
                last_error = AIError(f"Failed to execute Claude CLI: {e}")
                if attempt < self.max_retries:
                    logger.warning(f"AI command error (attempt {attempt + 1}), retrying: {e}")
                else:
                    logger.error(f"AI command error after {self.max_retries + 1} attempts: {e}")
        
        raise last_error or AIError("AI command failed for unknown reasons")
    
    def format_implementation_prompt(
        self,
        issue: Issue,
        repository_context: Optional[Dict[str, Any]] = None,
        custom_prompt: Optional[str] = None
    ) -> str:
        """Format implementation prompt with issue context.
        
        Args:
            issue: Issue to implement
            repository_context: Additional repository context
            custom_prompt: Custom prompt override
            
        Returns:
            Formatted prompt for Claude
        """
        if custom_prompt:
            # Use custom prompt, still expand variables
            base_prompt = custom_prompt
        else:
            base_prompt = self.config.implementation_prompt
        
        # Prepare context variables
        context = {
            "issue_id": issue.id,
            "issue_title": issue.title,
            "issue_description": issue.description,
            "acceptance_criteria": self._extract_acceptance_criteria(issue.description),
            "labels": ", ".join(issue.labels) if issue.labels else "None",
            "assignee": issue.assignee or "None",
            "repository": repository_context.get("name", "Unknown") if repository_context else "Unknown",
            "branch": repository_context.get("branch", "main") if repository_context else "main"
        }
        
        # Format prompt with context variables
        try:
            formatted_prompt = base_prompt.format(**context)
        except KeyError as e:
            # If variable is missing, provide a warning but continue
            logger.warning(f"Missing variable in prompt template: {e}")
            formatted_prompt = base_prompt
        
        # Add repository context if enabled
        if self.include_file_context and repository_context:
            formatted_prompt += self._add_repository_context(repository_context)
        
        # Add response format instructions for structured responses
        if self.response_format == "structured":
            formatted_prompt += self._add_structured_response_instructions()
        
        return formatted_prompt
    
    def _extract_acceptance_criteria(self, description: str) -> str:
        """Extract acceptance criteria from issue description.
        
        Args:
            description: Issue description
            
        Returns:
            Extracted acceptance criteria or empty string
        """
        # Look for common acceptance criteria patterns
        patterns = [
            r"(?i)acceptance criteria:?\s*\n(.*?)(?=\n\s*\n|\n\s*#|\Z)",
            r"(?i)ac:?\s*\n(.*?)(?=\n\s*\n|\n\s*#|\Z)",
            r"(?i)requirements:?\s*\n(.*?)(?=\n\s*\n|\n\s*#|\Z)",
            r"(?i)definition of done:?\s*\n(.*?)(?=\n\s*\n|\n\s*#|\Z)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, description, re.MULTILINE | re.DOTALL)
            if match:
                return match.group(1).strip()
        
        return ""
    
    def _add_repository_context(self, repository_context: Dict[str, Any]) -> str:
        """Add repository context to prompt.
        
        Args:
            repository_context: Repository context information
            
        Returns:
            Additional prompt content with repository context
        """
        context_lines = ["\n\n## Repository Context"]
        
        if "file_structure" in repository_context:
            context_lines.append("### File Structure")
            context_lines.append(repository_context["file_structure"])
        
        if "coding_standards" in repository_context:
            context_lines.append("### Coding Standards")
            context_lines.append(repository_context["coding_standards"])
        
        if "existing_patterns" in repository_context:
            context_lines.append("### Existing Patterns")
            context_lines.append(repository_context["existing_patterns"])
        
        return "\n".join(context_lines)
    
    def _add_structured_response_instructions(self) -> str:
        """Add instructions for structured response format.
        
        Returns:
            Instructions for Claude to provide structured output
        """
        return """

## Response Format

Please provide your response in the following structured format:

**IMPLEMENTATION SUMMARY:**
Brief description of what you implemented

**FILES MODIFIED:**
For each file changed, specify:
- File path
- Action (create/modify/delete)
- Brief description of changes

**COMMANDS TO RUN:**
Any commands that should be executed after implementation (e.g., npm install, pip install, tests)

**NOTES:**
Any additional notes or considerations
"""
    
    def parse_ai_response(self, raw_response: str) -> AIResponse:
        """Parse AI response into structured format.
        
        Args:
            raw_response: Raw response from Claude
            
        Returns:
            Structured AI response
        """
        try:
            if self.response_format == "structured":
                return self._parse_structured_response(raw_response)
            else:
                return self._parse_freeform_response(raw_response)
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}")
            return AIResponse(
                success=False,
                error_message=f"Failed to parse AI response: {e}",
                raw_output=raw_response
            )
    
    def _parse_structured_response(self, raw_response: str) -> AIResponse:
        """Parse structured AI response.
        
        Args:
            raw_response: Raw structured response
            
        Returns:
            Parsed AI response
        """
        file_changes = []
        commands = []
        summary = None
        
        try:
            # Extract summary
            summary_match = re.search(
                r"\*\*IMPLEMENTATION SUMMARY:\*\*\s*\n(.*?)(?=\n\s*\*\*|\Z)",
                raw_response,
                re.MULTILINE | re.DOTALL
            )
            if summary_match:
                summary = summary_match.group(1).strip()
            
            # Extract file changes
            files_section = re.search(
                r"\*\*FILES MODIFIED:\*\*\s*\n(.*?)(?=\n\s*\*\*|\Z)",
                raw_response,
                re.MULTILINE | re.DOTALL
            )
            if files_section:
                files_text = files_section.group(1)
                file_changes = self._parse_file_changes(files_text)
            
            # Extract commands
            commands_section = re.search(
                r"\*\*COMMANDS TO RUN:\*\*\s*\n(.*?)(?=\n\s*\*\*|\Z)",
                raw_response,
                re.MULTILINE | re.DOTALL
            )
            if commands_section:
                commands_text = commands_section.group(1)
                commands = self._parse_commands(commands_text)
            
            return AIResponse(
                success=True,
                summary=summary,
                file_changes=file_changes,
                commands=commands,
                raw_output=raw_response
            )
            
        except Exception as e:
            logger.warning(f"Failed to parse structured response, falling back to freeform: {e}")
            return self._parse_freeform_response(raw_response)
    
    def _parse_freeform_response(self, raw_response: str) -> AIResponse:
        """Parse freeform AI response using heuristics.
        
        Args:
            raw_response: Raw freeform response
            
        Returns:
            Parsed AI response with basic structure
        """
        # For freeform responses, use simple heuristics
        file_changes = []
        commands = []
        
        # Look for common file patterns
        file_patterns = [
            r"(?:create|modify|update|edit)\s+(?:file\s+)?[`\"']?([^\s`\"'\n]+\.[a-zA-Z0-9]+)[`\"']?",
            r"[`\"']([^\s`\"'\n]+\.[a-zA-Z0-9]+)[`\"']?\s+(?:file\s+)?(?:create|modify|update|edit)",
        ]
        
        for pattern in file_patterns:
            matches = re.findall(pattern, raw_response, re.IGNORECASE)
            for match in matches:
                if match not in [fc.path for fc in file_changes]:
                    file_changes.append(AIFileChange(
                        path=match,
                        action="modify",  # Default to modify
                        description="File mentioned in AI response"
                    ))
        
        # Look for command patterns
        command_patterns = [
            r"(?:run|execute)\s+[`\"']([^`\"'\n]+)[`\"']",
            r"[`\"']([^`\"'\n]*(?:npm|pip|yarn|go|cargo|mvn|gradle)[^`\"'\n]*)[`\"']",
        ]
        
        for pattern in command_patterns:
            matches = re.findall(pattern, raw_response, re.IGNORECASE)
            for match in matches:
                commands.append(AICommand(
                    command=match,
                    description="Command mentioned in AI response"
                ))
        
        # Extract first paragraph as summary
        lines = raw_response.strip().split('\n')
        summary = None
        for line in lines:
            if line.strip():
                summary = line.strip()
                break
        
        return AIResponse(
            success=True,
            summary=summary,
            file_changes=file_changes,
            commands=commands,
            raw_output=raw_response
        )
    
    def _parse_file_changes(self, files_text: str) -> List[AIFileChange]:
        """Parse file changes from structured text.
        
        Args:
            files_text: Text containing file change descriptions
            
        Returns:
            List of file changes
        """
        file_changes = []
        
        # Look for bullet points or lines with file paths
        lines = files_text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Remove bullet points
            line = re.sub(r'^[-*•]\s*', '', line)
            
            # Try to parse "path - action - description" format
            parts = [p.strip() for p in line.split(' - ', 2)]
            if len(parts) >= 2:
                path = parts[0]
                action = parts[1].lower()
                description = parts[2] if len(parts) > 2 else None
                
                # Validate action
                if action not in ['create', 'modify', 'delete', 'update', 'edit']:
                    action = 'modify'  # Default
                if action in ['update', 'edit']:
                    action = 'modify'
                
                file_changes.append(AIFileChange(
                    path=path,
                    action=action,
                    description=description
                ))
            else:
                # Try to extract file path from line
                # Look for file extensions
                file_match = re.search(r'([^\s]+\.[a-zA-Z0-9]+)', line)
                if file_match:
                    file_changes.append(AIFileChange(
                        path=file_match.group(1),
                        action='modify',
                        description=line
                    ))
        
        return file_changes
    
    def _parse_commands(self, commands_text: str) -> List[AICommand]:
        """Parse commands from structured text.
        
        Args:
            commands_text: Text containing command descriptions
            
        Returns:
            List of commands
        """
        commands = []
        
        lines = commands_text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Remove bullet points
            line = re.sub(r'^[-*•]\s*', '', line)
            
            # Look for commands in backticks or quotes
            command_match = re.search(r'[`"\']([^`"\']+)[`"\']', line)
            if command_match:
                command = command_match.group(1)
                description = re.sub(r'[`"\'][^`"\']+[`"\']', '', line).strip()
                if description.startswith('- '):
                    description = description[2:]
                
                commands.append(AICommand(
                    command=command,
                    description=description if description else None
                ))
            else:
                # Assume the whole line is a command if it looks like one
                if any(word in line.lower() for word in ['npm', 'pip', 'yarn', 'go', 'cargo', 'mvn', 'gradle', 'python', 'node']):
                    commands.append(AICommand(
                        command=line,
                        description="Command from AI response"
                    ))
        
        return commands


def execute_ai_command(
    prompt: str,
    agent: str,
    config: AIConfig,
    working_directory: Optional[str] = None,
    additional_args: Optional[List[str]] = None
) -> str:
    """Execute Claude CLI command with specified agent.
    
    Args:
        prompt: Prompt to send to Claude
        agent: Agent name to use
        config: AI configuration
        working_directory: Working directory for command execution
        additional_args: Additional command-line arguments
        
    Returns:
        Raw Claude response
        
    Raises:
        AIError: If command fails
    """
    integration = ClaudeIntegration(config)
    integration.validate_ai_prerequisites()
    return integration.execute_ai_command(prompt, agent, working_directory, additional_args)


def format_implementation_prompt(
    issue: Issue,
    config: AIConfig,
    repository_context: Optional[Dict[str, Any]] = None,
    custom_prompt: Optional[str] = None
) -> str:
    """Format implementation prompt with issue context.
    
    Args:
        issue: Issue to implement
        config: AI configuration
        repository_context: Additional repository context
        custom_prompt: Custom prompt override
        
    Returns:
        Formatted prompt for Claude
    """
    integration = ClaudeIntegration(config)
    return integration.format_implementation_prompt(issue, repository_context, custom_prompt)


def parse_ai_response(raw_response: str, config: AIConfig) -> AIResponse:
    """Parse AI response into structured format.
    
    Args:
        raw_response: Raw response from Claude
        config: AI configuration
        
    Returns:
        Structured AI response
    """
    integration = ClaudeIntegration(config)
    return integration.parse_ai_response(raw_response)


def validate_ai_prerequisites(config: AIConfig) -> None:
    """Validate AI prerequisites.
    
    Args:
        config: AI configuration
        
    Raises:
        AIError: If prerequisites are not met
    """
    integration = ClaudeIntegration(config)
    integration.validate_ai_prerequisites()