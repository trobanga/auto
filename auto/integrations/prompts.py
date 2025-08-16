"""Prompt management system with custom prompts and template support."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from auto.models import AIConfig, Issue
from auto.utils.logger import get_logger
from auto.utils.shell import get_git_root

logger = get_logger(__name__)


class PromptError(Exception):
    """Prompt management error."""
    pass


class PromptTemplate(BaseModel):
    """Prompt template model."""
    
    name: str = Field(description="Template name")
    description: Optional[str] = Field(default=None, description="Template description")
    prompt: str = Field(description="Prompt template content")
    variables: List[str] = Field(default_factory=list, description="Available variables")
    tags: List[str] = Field(default_factory=list, description="Template tags")
    agent: Optional[str] = Field(default=None, description="Preferred agent for this template")


class PromptManager:
    """Prompt management with custom prompt resolution and template support."""
    
    def __init__(self, config: AIConfig):
        """Initialize prompt manager.
        
        Args:
            config: AI configuration
        """
        self.config = config
        self.prompt_templates_dir = Path(config.prompt_templates_dir).expanduser()
        self.allow_custom_prompts = config.allow_custom_prompts
        self.default_template = config.default_template
        self.available_variables = config.prompt_variables
        self._template_cache: Dict[str, PromptTemplate] = {}
    
    def resolve_prompt(
        self,
        prompt_override: Optional[str] = None,
        prompt_file: Optional[str] = None,
        prompt_template: Optional[str] = None,
        prompt_append: Optional[str] = None,
        base_prompt: Optional[str] = None
    ) -> str:
        """Resolve prompt from various sources with precedence.
        
        Precedence order:
        1. prompt_override (direct CLI prompt)
        2. prompt_file (file-based prompt)
        3. prompt_template (named template)
        4. base_prompt (default prompt)
        
        Args:
            prompt_override: Direct prompt override
            prompt_file: Path to prompt file
            prompt_template: Named template
            prompt_append: Text to append to final prompt
            base_prompt: Base prompt to use if no overrides
            
        Returns:
            Resolved prompt text
            
        Raises:
            PromptError: If prompt resolution fails
        """
        if not self.allow_custom_prompts and any([prompt_override, prompt_file, prompt_template]):
            logger.warning("Custom prompts are disabled in configuration")
            resolved_prompt = base_prompt or self.config.implementation_prompt
        elif prompt_override:
            logger.debug("Using direct prompt override")
            resolved_prompt = prompt_override
        elif prompt_file:
            logger.debug(f"Loading prompt from file: {prompt_file}")
            resolved_prompt = self._load_prompt_from_file(prompt_file)
        elif prompt_template:
            logger.debug(f"Loading prompt template: {prompt_template}")
            template = self.load_prompt_template(prompt_template)
            resolved_prompt = template.prompt
        else:
            # Use base prompt or default
            resolved_prompt = base_prompt or self.config.implementation_prompt
        
        # Append additional text if provided
        if prompt_append:
            resolved_prompt = f"{resolved_prompt}\n\n{prompt_append}"
        
        return resolved_prompt
    
    def load_prompt_template(self, template_name: str) -> PromptTemplate:
        """Load named prompt template from user and project directories.
        
        Search order:
        1. Project .auto/prompts/ directory
        2. User ~/.auto/prompts/ directory
        3. Built-in templates
        
        Args:
            template_name: Name of template to load
            
        Returns:
            Loaded prompt template
            
        Raises:
            PromptError: If template cannot be found or loaded
        """
        # Check cache first
        if template_name in self._template_cache:
            return self._template_cache[template_name]
        
        # Search paths in order
        search_paths = []
        
        # 1. Project .auto/prompts/ directory
        git_root = get_git_root()
        if git_root:
            project_prompts = git_root / ".auto" / "prompts"
            if project_prompts.exists():
                search_paths.append(project_prompts)
        
        # 2. User ~/.auto/prompts/ directory
        if self.prompt_templates_dir.exists():
            search_paths.append(self.prompt_templates_dir)
        
        # Try to load template from search paths
        for search_path in search_paths:
            template_file = search_path / f"{template_name}.yaml"
            if template_file.exists():
                try:
                    template = self._load_template_file(template_file, template_name)
                    self._template_cache[template_name] = template
                    logger.debug(f"Loaded template '{template_name}' from {template_file}")
                    return template
                except Exception as e:
                    logger.warning(f"Failed to load template from {template_file}: {e}")
                    continue
        
        # Try built-in templates
        try:
            template = self._load_builtin_template(template_name)
            self._template_cache[template_name] = template
            return template
        except PromptError:
            pass
        
        raise PromptError(f"Prompt template '{template_name}' not found in search paths: {search_paths}")
    
    def _load_template_file(self, template_file: Path, template_name: str) -> PromptTemplate:
        """Load template from YAML file.
        
        Args:
            template_file: Path to template file
            template_name: Template name
            
        Returns:
            Loaded template
            
        Raises:
            PromptError: If template cannot be loaded
        """
        try:
            with open(template_file, 'r') as f:
                data = yaml.safe_load(f)
            
            if not isinstance(data, dict):
                raise PromptError(f"Template file must contain a YAML object: {template_file}")
            
            # Ensure required fields
            if 'prompt' not in data:
                raise PromptError(f"Template file missing 'prompt' field: {template_file}")
            
            # Set default name if not provided
            if 'name' not in data:
                data['name'] = template_name
            
            return PromptTemplate.model_validate(data)
            
        except yaml.YAMLError as e:
            raise PromptError(f"Invalid YAML in template file {template_file}: {e}")
        except Exception as e:
            raise PromptError(f"Failed to load template file {template_file}: {e}")
    
    def _load_builtin_template(self, template_name: str) -> PromptTemplate:
        """Load built-in template.
        
        Args:
            template_name: Template name
            
        Returns:
            Built-in template
            
        Raises:
            PromptError: If template is not found
        """
        builtin_templates = {
            "implementation": PromptTemplate(
                name="implementation",
                description="Standard implementation template",
                prompt="""Implement the following issue: {issue_description}

## Issue Details
- **ID**: {issue_id}
- **Title**: {issue_title}
- **Labels**: {labels}
- **Assignee**: {assignee}

## Repository Context
- **Repository**: {repository}
- **Branch**: {branch}

{acceptance_criteria}

Please implement this feature following best practices for code quality, testing, and documentation.""",
                variables=self.available_variables,
                tags=["default", "implementation"]
            ),
            "security-focused": PromptTemplate(
                name="security-focused",
                description="Security-focused implementation template",
                prompt="""Implement the following issue with a strong focus on security: {issue_description}

## Issue Details
- **ID**: {issue_id}
- **Title**: {issue_title}
- **Labels**: {labels}
- **Assignee**: {assignee}

## Repository Context
- **Repository**: {repository}
- **Branch**: {branch}

{acceptance_criteria}

## Security Requirements
Please ensure your implementation:
1. Validates all inputs and sanitizes data
2. Uses secure authentication and authorization patterns
3. Follows OWASP security guidelines
4. Implements proper error handling without information disclosure
5. Uses secure communication protocols where applicable
6. Follows the principle of least privilege
7. Includes security testing considerations

Prioritize security over convenience and document any security considerations.""",
                variables=self.available_variables,
                tags=["security", "implementation"]
            ),
            "performance": PromptTemplate(
                name="performance",
                description="Performance-focused implementation template",
                prompt="""Implement the following issue with a strong focus on performance optimization: {issue_description}

## Issue Details
- **ID**: {issue_id}
- **Title**: {issue_title}
- **Labels**: {labels}
- **Assignee**: {assignee}

## Repository Context
- **Repository**: {repository}
- **Branch**: {branch}

{acceptance_criteria}

## Performance Requirements
Please ensure your implementation:
1. Optimizes for speed and efficiency
2. Minimizes memory usage and prevents memory leaks
3. Uses efficient algorithms and data structures
4. Implements caching where appropriate
5. Considers lazy loading and asynchronous patterns
6. Minimizes network requests and database queries
7. Includes performance benchmarks and monitoring
8. Considers scalability for high-load scenarios

Document performance considerations and any trade-offs made.""",
                variables=self.available_variables,
                tags=["performance", "optimization", "implementation"]
            )
        }
        
        if template_name not in builtin_templates:
            raise PromptError(f"Built-in template '{template_name}' not found")
        
        return builtin_templates[template_name]
    
    def _load_prompt_from_file(self, prompt_file: str) -> str:
        """Load prompt from file.
        
        Args:
            prompt_file: Path to prompt file
            
        Returns:
            Prompt content
            
        Raises:
            PromptError: If file cannot be loaded
        """
        try:
            file_path = Path(prompt_file).expanduser()
            if not file_path.exists():
                raise PromptError(f"Prompt file not found: {file_path}")
            
            with open(file_path, 'r') as f:
                content = f.read().strip()
            
            if not content:
                raise PromptError(f"Prompt file is empty: {file_path}")
            
            return content
            
        except Exception as e:
            raise PromptError(f"Failed to load prompt file {prompt_file}: {e}")
    
    def expand_prompt_variables(
        self,
        prompt: str,
        issue: Issue,
        repository_context: Optional[Dict[str, Any]] = None,
        custom_variables: Optional[Dict[str, str]] = None
    ) -> str:
        """Expand variables in prompt template.
        
        Args:
            prompt: Prompt template with variables
            issue: Issue context
            repository_context: Repository context
            custom_variables: Additional custom variables
            
        Returns:
            Prompt with expanded variables
        """
        # Prepare variable context
        variables = {
            "issue_id": issue.id,
            "issue_title": issue.title,
            "issue_description": issue.description,
            "acceptance_criteria": self._extract_acceptance_criteria(issue.description),
            "labels": ", ".join(issue.labels) if issue.labels else "None",
            "assignee": issue.assignee or "None",
            "repository": repository_context.get("name", "Unknown") if repository_context else "Unknown",
            "branch": repository_context.get("branch", "main") if repository_context else "main"
        }
        
        # Add custom variables
        if custom_variables:
            variables.update(custom_variables)
        
        # Add repository context variables
        if repository_context:
            variables.update({
                f"repo_{key}": value for key, value in repository_context.items()
                if isinstance(value, (str, int, float, bool))
            })
        
        # Expand variables with error handling
        try:
            expanded_prompt = prompt.format(**variables)
        except KeyError as e:
            missing_var = str(e).strip("'\"")
            logger.warning(f"Missing variable '{missing_var}' in prompt template")
            # Try to expand with available variables only
            available_variables = {k: v for k, v in variables.items() if f"{{{k}}}" in prompt}
            try:
                expanded_prompt = prompt.format(**available_variables)
            except KeyError:
                # If still failing, return original prompt with warning
                logger.warning("Could not expand prompt variables, using original prompt")
                expanded_prompt = prompt
        
        return expanded_prompt
    
    def _extract_acceptance_criteria(self, description: str) -> str:
        """Extract acceptance criteria from issue description.
        
        Args:
            description: Issue description
            
        Returns:
            Extracted acceptance criteria with formatting
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
                criteria = match.group(1).strip()
                return f"## Acceptance Criteria\n{criteria}"
        
        return ""
    
    def list_templates(self) -> List[PromptTemplate]:
        """List all available prompt templates.
        
        Returns:
            List of available templates
        """
        templates = []
        
        # Built-in templates
        builtin_names = ["implementation", "security-focused", "performance"]
        for name in builtin_names:
            try:
                template = self._load_builtin_template(name)
                templates.append(template)
            except PromptError:
                pass
        
        # Search paths for custom templates
        search_paths = []
        
        # Project templates
        git_root = get_git_root()
        if git_root:
            project_prompts = git_root / ".auto" / "prompts"
            if project_prompts.exists():
                search_paths.append(project_prompts)
        
        # User templates
        if self.prompt_templates_dir.exists():
            search_paths.append(self.prompt_templates_dir)
        
        # Load custom templates
        for search_path in search_paths:
            for template_file in search_path.glob("*.yaml"):
                template_name = template_file.stem
                # Skip if already loaded as built-in
                if template_name in builtin_names:
                    continue
                
                try:
                    template = self._load_template_file(template_file, template_name)
                    templates.append(template)
                except Exception as e:
                    logger.warning(f"Failed to load template {template_file}: {e}")
        
        return templates
    
    def validate_template(self, template: PromptTemplate) -> List[str]:
        """Validate prompt template.
        
        Args:
            template: Template to validate
            
        Returns:
            List of validation warnings (empty if valid)
        """
        warnings = []
        
        # Check for required variables
        prompt_text = template.prompt
        used_variables = re.findall(r'\{([^}]+)\}', prompt_text)
        
        for var in used_variables:
            if var not in self.available_variables:
                warnings.append(f"Variable '{var}' not in available variables list")
        
        # Check for unused declared variables
        for var in template.variables:
            if f"{{{var}}}" not in prompt_text:
                warnings.append(f"Declared variable '{var}' not used in prompt")
        
        # Check prompt length
        if len(prompt_text) < 10:
            warnings.append("Prompt is very short, may not provide enough context")
        elif len(prompt_text) > 5000:
            warnings.append("Prompt is very long, may exceed AI command limits")
        
        return warnings
    
    def create_template_directory(self, user_level: bool = True) -> Path:
        """Create prompt templates directory.
        
        Args:
            user_level: If True, create user directory; if False, create project directory
            
        Returns:
            Path to created directory
        """
        if user_level:
            templates_dir = self.prompt_templates_dir
        else:
            git_root = get_git_root()
            if git_root:
                templates_dir = git_root / ".auto" / "prompts"
            else:
                templates_dir = Path.cwd() / ".auto" / "prompts"
        
        templates_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created prompt templates directory: {templates_dir}")
        
        return templates_dir


def resolve_prompt(
    config: AIConfig,
    prompt_override: Optional[str] = None,
    prompt_file: Optional[str] = None,
    prompt_template: Optional[str] = None,
    prompt_append: Optional[str] = None,
    base_prompt: Optional[str] = None
) -> str:
    """Resolve prompt from various sources.
    
    Args:
        config: AI configuration
        prompt_override: Direct prompt override
        prompt_file: Path to prompt file
        prompt_template: Named template
        prompt_append: Text to append to final prompt
        base_prompt: Base prompt to use if no overrides
        
    Returns:
        Resolved prompt text
    """
    manager = PromptManager(config)
    return manager.resolve_prompt(
        prompt_override=prompt_override,
        prompt_file=prompt_file,
        prompt_template=prompt_template,
        prompt_append=prompt_append,
        base_prompt=base_prompt
    )


def load_prompt_template(config: AIConfig, template_name: str) -> PromptTemplate:
    """Load named prompt template.
    
    Args:
        config: AI configuration
        template_name: Name of template to load
        
    Returns:
        Loaded prompt template
    """
    manager = PromptManager(config)
    return manager.load_prompt_template(template_name)


def expand_prompt_variables(
    prompt: str,
    issue: Issue,
    config: AIConfig,
    repository_context: Optional[Dict[str, Any]] = None,
    custom_variables: Optional[Dict[str, str]] = None
) -> str:
    """Expand variables in prompt template.
    
    Args:
        prompt: Prompt template with variables
        issue: Issue context
        config: AI configuration
        repository_context: Repository context
        custom_variables: Additional custom variables
        
    Returns:
        Prompt with expanded variables
    """
    manager = PromptManager(config)
    return manager.expand_prompt_variables(
        prompt=prompt,
        issue=issue,
        repository_context=repository_context,
        custom_variables=custom_variables
    )