"""
Prompt Management Module

Provides custom prompt resolution, template loading, variable expansion, and validation
for AI command customization in the auto workflow system.
"""

import os
import re
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union, Any
from ..models import Issue
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PromptTemplate:
    """A prompt template with metadata and content."""
    name: str
    content: str
    description: str = ""
    variables: List[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.variables is None:
            self.variables = []
        if self.metadata is None:
            self.metadata = {}


class PromptManager:
    """
    Prompt management system providing custom prompt resolution, template loading,
    variable expansion, and prompt validation for AI command customization.
    """

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize prompt manager.
        
        Args:
            config_dir: Optional configuration directory override
        """
        self.logger = get_logger(f"{__name__}.PromptManager")
        self.config_dir = config_dir
        self._template_cache = {}

    def resolve_prompt(
        self,
        issue: Issue,
        prompt_override: Optional[str] = None,
        prompt_file: Optional[str] = None,
        prompt_template: Optional[str] = None,
        prompt_append: Optional[str] = None,
        default_prompt: Optional[str] = None,
        variables: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Resolve final prompt from various sources with proper precedence.
        
        Args:
            issue: Issue context for variable expansion
            prompt_override: Direct prompt override (highest precedence)
            prompt_file: Path to prompt file
            prompt_template: Named template to load
            prompt_append: Text to append to base prompt
            default_prompt: Default prompt if no other source
            variables: Additional variables for expansion
            
        Returns:
            Final resolved and expanded prompt
            
        Raises:
            PromptError: If prompt resolution fails
        """
        try:
            base_prompt = None
            
            # Resolve base prompt in order of precedence
            if prompt_override:
                base_prompt = prompt_override
                self.logger.debug("Using direct prompt override")
                
            elif prompt_file:
                base_prompt = self._load_prompt_from_file(prompt_file)
                self.logger.debug(f"Loaded prompt from file: {prompt_file}")
                
            elif prompt_template:
                template = self.load_prompt_template(prompt_template)
                base_prompt = template.content
                self.logger.debug(f"Loaded prompt template: {prompt_template}")
                
            elif default_prompt:
                base_prompt = default_prompt
                self.logger.debug("Using default prompt")
                
            else:
                raise PromptError("No prompt source provided")
            
            # Expand variables in base prompt
            expanded_prompt = self.expand_prompt_variables(
                base_prompt, 
                issue, 
                variables or {}
            )
            
            # Append additional content if specified
            if prompt_append:
                expanded_prompt = f"{expanded_prompt}\n\n{prompt_append}"
                self.logger.debug("Appended additional prompt content")
            
            return expanded_prompt
            
        except Exception as e:
            self.logger.error(f"Failed to resolve prompt: {e}")
            raise PromptError(f"Prompt resolution failed: {e}")

    def load_prompt_template(self, template_name: str) -> PromptTemplate:
        """
        Load named prompt template from user and project directories.
        
        Args:
            template_name: Name of template to load
            
        Returns:
            PromptTemplate object
            
        Raises:
            PromptError: If template is not found or invalid
        """
        # Check cache first
        if template_name in self._template_cache:
            return self._template_cache[template_name]
        
        template_paths = self._get_template_search_paths()
        
        for search_path in template_paths:
            template_file = search_path / f"{template_name}.yaml"
            if template_file.exists():
                try:
                    template = self._load_template_file(template_file)
                    template.name = template_name
                    
                    # Cache the template
                    self._template_cache[template_name] = template
                    
                    self.logger.debug(f"Loaded template '{template_name}' from {template_file}")
                    return template
                    
                except Exception as e:
                    self.logger.warning(f"Failed to load template from {template_file}: {e}")
                    continue
        
        raise PromptError(f"Template '{template_name}' not found in search paths: {template_paths}")

    def expand_prompt_variables(
        self, 
        prompt: str, 
        issue: Issue, 
        additional_variables: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Expand variables in prompt template using issue context and additional variables.
        
        Args:
            prompt: Prompt template with variables
            issue: Issue providing context variables
            additional_variables: Additional custom variables
            
        Returns:
            Prompt with variables expanded
        """
        variables = self._build_variable_context(issue, additional_variables or {})
        
        try:
            # Use safe string formatting to handle missing variables gracefully
            return self._safe_format(prompt, variables)
            
        except Exception as e:
            self.logger.warning(f"Variable expansion failed, using original prompt: {e}")
            return prompt

    def list_available_templates(self) -> List[str]:
        """
        List all available prompt templates.
        
        Returns:
            List of template names
        """
        templates = set()
        
        for search_path in self._get_template_search_paths():
            if search_path.exists():
                for template_file in search_path.glob("*.yaml"):
                    templates.add(template_file.stem)
        
        return sorted(list(templates))

    def validate_template(self, template_name: str) -> bool:
        """
        Validate that a template exists and is properly formatted.
        
        Args:
            template_name: Name of template to validate
            
        Returns:
            True if template is valid
        """
        try:
            self.load_prompt_template(template_name)
            return True
        except PromptError:
            return False

    def create_template(
        self, 
        template_name: str, 
        content: str, 
        description: str = "",
        user_template: bool = True
    ) -> Path:
        """
        Create a new prompt template.
        
        Args:
            template_name: Name for the new template
            content: Template content
            description: Template description
            user_template: Create in user directory if True, project if False
            
        Returns:
            Path to created template file
        """
        template_data = {
            'description': description,
            'content': content,
            'variables': self._extract_template_variables(content)
        }
        
        # Choose directory
        if user_template:
            template_dir = self._get_user_templates_dir()
        else:
            template_dir = self._get_project_templates_dir()
        
        template_dir.mkdir(parents=True, exist_ok=True)
        template_file = template_dir / f"{template_name}.yaml"
        
        with open(template_file, 'w') as f:
            yaml.dump(template_data, f, default_flow_style=False)
        
        self.logger.info(f"Created template '{template_name}' at {template_file}")
        return template_file

    def _load_prompt_from_file(self, file_path: str) -> str:
        """Load prompt content from file."""
        try:
            path = Path(file_path)
            if not path.exists():
                raise PromptError(f"Prompt file not found: {file_path}")
            
            if not path.is_file():
                raise PromptError(f"Prompt path is not a file: {file_path}")
            
            content = path.read_text(encoding='utf-8')
            if not content.strip():
                raise PromptError(f"Prompt file is empty: {file_path}")
            
            return content
            
        except Exception as e:
            raise PromptError(f"Failed to load prompt file {file_path}: {e}")

    def _load_template_file(self, template_file: Path) -> PromptTemplate:
        """Load template from YAML file."""
        try:
            with open(template_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            if not isinstance(data, dict):
                raise PromptError(f"Template file must contain YAML dictionary: {template_file}")
            
            if 'content' not in data:
                raise PromptError(f"Template file missing 'content' field: {template_file}")
            
            return PromptTemplate(
                name=template_file.stem,
                content=data['content'],
                description=data.get('description', ''),
                variables=data.get('variables', []),
                metadata=data.get('metadata', {})
            )
            
        except yaml.YAMLError as e:
            raise PromptError(f"Invalid YAML in template file {template_file}: {e}")

    def _get_template_search_paths(self) -> List[Path]:
        """Get template search paths in order of precedence."""
        paths = []
        
        # Project-specific templates (highest precedence)
        project_dir = self._get_project_templates_dir()
        if project_dir:
            paths.append(project_dir)
        
        # User-specific templates
        user_dir = self._get_user_templates_dir()
        if user_dir:
            paths.append(user_dir)
        
        # Built-in templates (lowest precedence)
        builtin_dir = self._get_builtin_templates_dir()
        if builtin_dir:
            paths.append(builtin_dir)
        
        return paths

    def _get_project_templates_dir(self) -> Optional[Path]:
        """Get project-specific templates directory."""
        if self.config_dir:
            return Path(self.config_dir) / "templates" / "prompts"
        
        # Try to find .auto directory
        current = Path.cwd()
        while current != current.parent:
            auto_dir = current / ".auto"
            if auto_dir.exists():
                return auto_dir / "templates" / "prompts"
            current = current.parent
        
        return None

    def _get_user_templates_dir(self) -> Path:
        """Get user-specific templates directory."""
        home = Path.home()
        return home / ".auto" / "templates" / "prompts"

    def _get_builtin_templates_dir(self) -> Path:
        """Get built-in templates directory."""
        # Relative to this file
        module_dir = Path(__file__).parent.parent
        return module_dir / "templates" / "prompts"

    def _build_variable_context(
        self, 
        issue: Issue, 
        additional_variables: Dict[str, str]
    ) -> Dict[str, str]:
        """Build variable context for template expansion."""
        variables = {
            'issue_id': str(issue.id),
            'issue_title': issue.title or '',
            'issue_description': issue.description or '',
            'issue_labels': ', '.join(issue.labels) if issue.labels else '',
            'issue_assignee': issue.assignee or '',
            'repository': getattr(issue, 'repository', ''),
            'branch': getattr(issue, 'branch', ''),
        }
        
        # Add additional variables (can override defaults)
        variables.update(additional_variables)
        
        return variables

    def _safe_format(self, template: str, variables: Dict[str, str]) -> str:
        """
        Safely format template with variables, handling missing variables gracefully.
        """
        # First pass: use standard format for available variables
        try:
            formatted = template.format(**variables)
            return formatted
        except KeyError as e:
            # Second pass: replace missing variables with placeholder
            missing_var = str(e).strip("'\"")
            self.logger.warning(f"Template variable '{missing_var}' not found, using placeholder")
            
            # Create a copy with placeholder for missing variable
            safe_variables = variables.copy()
            safe_variables[missing_var] = f"[{missing_var}]"
            
            # Try again with placeholder
            try:
                return template.format(**safe_variables)
            except KeyError:
                # If still failing, use regex replacement for all variables
                return self._regex_format(template, variables)

    def _regex_format(self, template: str, variables: Dict[str, str]) -> str:
        """Format template using regex replacement for better error handling."""
        def replace_var(match):
            var_name = match.group(1)
            return variables.get(var_name, f"[{var_name}]")
        
        # Replace {variable_name} patterns
        return re.sub(r'\{([^}]+)\}', replace_var, template)

    def _extract_template_variables(self, content: str) -> List[str]:
        """Extract variable names from template content."""
        variables = re.findall(r'\{([^}]+)\}', content)
        return sorted(list(set(variables)))


class PromptError(Exception):
    """Exception raised for prompt management errors."""
    pass


def resolve_prompt(
    issue: Issue,
    prompt_override: Optional[str] = None,
    prompt_file: Optional[str] = None,
    prompt_template: Optional[str] = None,
    prompt_append: Optional[str] = None,
    default_prompt: Optional[str] = None,
    variables: Optional[Dict[str, str]] = None
) -> str:
    """
    Convenience function for prompt resolution.
    
    Args:
        issue: Issue context
        prompt_override: Direct prompt override
        prompt_file: Path to prompt file
        prompt_template: Named template to load
        prompt_append: Text to append
        default_prompt: Default prompt
        variables: Additional variables
        
    Returns:
        Resolved prompt
    """
    manager = PromptManager()
    return manager.resolve_prompt(
        issue=issue,
        prompt_override=prompt_override,
        prompt_file=prompt_file,
        prompt_template=prompt_template,
        prompt_append=prompt_append,
        default_prompt=default_prompt,
        variables=variables
    )


def load_prompt_template(template_name: str) -> PromptTemplate:
    """
    Convenience function for template loading.
    
    Args:
        template_name: Name of template to load
        
    Returns:
        PromptTemplate object
    """
    manager = PromptManager()
    return manager.load_prompt_template(template_name)


def expand_prompt_variables(
    prompt: str, 
    issue: Issue, 
    additional_variables: Optional[Dict[str, str]] = None
) -> str:
    """
    Convenience function for variable expansion.
    
    Args:
        prompt: Prompt template
        issue: Issue context
        additional_variables: Additional variables
        
    Returns:
        Expanded prompt
    """
    manager = PromptManager()
    return manager.expand_prompt_variables(prompt, issue, additional_variables)


def list_available_templates() -> List[str]:
    """
    Convenience function to list available templates.
    
    Returns:
        List of template names
    """
    manager = PromptManager()
    return manager.list_available_templates()