"""Click CLI interface for the auto tool."""

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from auto import __version__
from auto.config import ConfigError, config_manager, get_config
from auto.core import get_core
from auto.models import IssueIdentifier
from auto.utils.logger import get_logger
from auto.utils.shell import run_command
from auto.workflows.fetch import (
    fetch_issue_workflow_sync, validate_issue_access
)

logger = get_logger(__name__)
console = Console()



def enable_verbose_logging() -> None:
    """Enable debug logging for both logger and console handler."""
    import logging
    from rich.logging import RichHandler
    
    auto_logger = logging.getLogger("auto")
    auto_logger.setLevel(logging.DEBUG)
    
    # Also set all child loggers to DEBUG level
    for name, child_logger in logging.Logger.manager.loggerDict.items():
        if isinstance(child_logger, logging.Logger) and name.startswith("auto"):
            child_logger.setLevel(logging.DEBUG)
    
    # Also set console handler to DEBUG level
    for handler in auto_logger.handlers:
        if isinstance(handler, (RichHandler, logging.StreamHandler)) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(logging.DEBUG)
    
    logger.debug("Verbose logging enabled")


@click.group(invoke_without_command=True)
@click.option("--version", is_flag=True, help="Show version and exit")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx: click.Context, version: bool, verbose: bool) -> None:
    """Auto - Automatic User Task Orchestrator.
    
    Automates the complete workflow from issue to merged PR, including
    iterative review cycles with both AI and human reviewers.
    """
    if version:
        click.echo(f"auto version {__version__}")
        sys.exit(0)
    
    if verbose:
        enable_verbose_logging()
    
    # If no subcommand and no flags, show help
    if ctx.invoked_subcommand is None and not version:
        click.echo(ctx.get_help())


@cli.command()
def init() -> None:
    """Initialize auto configuration for the current project."""
    try:
        # Ensure user config exists
        user_config_path = Path.home() / ".auto" / "config.yaml"
        if not user_config_path.exists():
            config_manager.create_default_config(user_level=True)
            console.print(f"[green]✓[/green] User configuration created: {user_config_path}")
        
        # Create project config
        project_config_path = config_manager.create_default_config(user_level=False)
        console.print(f"[green]✓[/green] Project configuration initialized: {project_config_path}")
        
        # Show next steps
        console.print("\n[bold]Next steps:[/bold]")
        console.print("1. Edit the project configuration file to customize settings")
        console.print("2. Set up GitHub CLI: [cyan]gh auth login[/cyan]")
        console.print("3. Configure AI agent: [cyan]auto config set ai.command claude[/cyan]")
        console.print("4. Run [cyan]auto --help[/cyan] to see available commands")
        
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.group()
def config() -> None:
    """Configuration management."""
    pass


@config.command("get")
@click.argument("key")
def config_get(key: str) -> None:
    """Get configuration value by key.
    
    KEY: Dot-separated configuration key (e.g., 'github.token', 'ai.command')
    """
    try:
        value = config_manager.get_config_value(key)
        console.print(f"{key}: {value}")
        
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.option(
    "--project", "-p", is_flag=True,
    help="Set in project config instead of user config"
)
def config_set(key: str, value: str, project: bool) -> None:
    """Set configuration value.
    
    KEY: Dot-separated configuration key (e.g., 'github.token', 'ai.command')
    VALUE: Value to set
    """
    try:
        # Convert string values to appropriate types
        parsed_value = value
        if value.lower() in ("true", "false"):
            parsed_value = value.lower() == "true"
        elif value.isdigit():
            parsed_value = int(value)
        else:
            try:
                parsed_value = float(value)
            except ValueError:
                parsed_value = value
        
        config_manager.set_config_value(key, parsed_value, user_level=not project)
        
        config_type = "project" if project else "user"
        console.print(f"[green]✓[/green] {config_type.title()} config updated: {key} = {parsed_value}")
        
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@config.command("list")
def config_list() -> None:
    """List all configuration files and their status."""
    try:
        config_files = config_manager.list_config_files()
        
        table = Table(title="Configuration Files")
        table.add_column("Type", style="cyan")
        table.add_column("Path")
        table.add_column("Status", style="green")
        
        for config_type, path in config_files.items():
            if path and path.exists():
                status = "✓ Exists"
                path_str = str(path)
            else:
                status = "✗ Not found"
                path_str = "N/A" if path is None else str(path)
            
            table.add_row(config_type.title(), path_str, status)
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@config.command("show")
@click.option("--format", "-f", type=click.Choice(["table", "yaml", "json"]), default="table", help="Output format (default: table)")
@click.option("--section", "-s", help="Show only specific section (e.g., 'github', 'ai', 'workflows')")
def config_show(format: str, section: str) -> None:
    """Show current configuration values."""
    try:
        current_config = config_manager.get_config()
        config_dict = current_config.model_dump()
        
        # Filter by section if specified
        if section:
            if section not in config_dict:
                console.print(f"[red]Error:[/red] Section '{section}' not found in configuration")
                console.print(f"[dim]Available sections: {', '.join(config_dict.keys())}[/dim]")
                sys.exit(1)
            config_dict = {section: config_dict[section]}
        
        if format == "yaml":
            import yaml
            console.print(yaml.dump(config_dict, default_flow_style=False, sort_keys=True))
        elif format == "json":
            import json
            console.print(json.dumps(config_dict, indent=2, sort_keys=True, default=str))
        else:  # table format
            def add_config_rows(table: Table, data: dict, prefix: str = "") -> None:
                """Recursively add configuration rows to table."""
                for key, value in data.items():
                    full_key = f"{prefix}.{key}" if prefix else key
                    
                    if isinstance(value, dict):
                        # Add section header
                        table.add_row(f"[bold cyan]{full_key}[/bold cyan]", "", "")
                        add_config_rows(table, value, full_key)
                    elif isinstance(value, list):
                        # Handle lists
                        if value:
                            table.add_row(full_key, f"[{len(value)} items]", str(value))
                        else:
                            table.add_row(full_key, "[empty list]", "[]")
                    else:
                        # Handle primitive values
                        if value is None:
                            display_value = "[dim]None[/dim]"
                        elif isinstance(value, bool):
                            display_value = f"[{'green' if value else 'red'}]{value}[/]"
                        elif isinstance(value, str) and not value:
                            display_value = "[dim](empty)[/dim]"
                        else:
                            display_value = str(value)
                        
                        table.add_row(full_key, type(value).__name__, display_value)
            
            title = "Current Configuration"
            if section:
                title += f" - {section.title()} Section"
            
            table = Table(title=title)
            table.add_column("Setting", style="cyan", min_width=20)
            table.add_column("Type", style="dim", width=10)
            table.add_column("Value", min_width=30)
            
            add_config_rows(table, config_dict)
            console.print(table)
            
            # Show configuration sources
            console.print("\n[bold]Configuration Sources:[/bold]")
            config_files = config_manager.list_config_files()
            for config_type, path in config_files.items():
                if path and path.exists():
                    console.print(f"  [green]✓[/green] {config_type}: {path}")
                else:
                    console.print(f"  [dim]✗ {config_type}: Not found[/dim]")
        
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to load configuration: {e}")
        sys.exit(1)


@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Show detailed worktree information")
def status(verbose: bool) -> None:
    """Show status of active workflows and PRs."""
    try:
        core = get_core()
        workflow_states = core.get_workflow_states()
        
        if not workflow_states:
            console.print("[yellow]No active workflows found.[/yellow]")
            return
        
        table = Table(title="Active Workflows")
        table.add_column("Issue ID", style="cyan")
        table.add_column("Status", style="white")
        table.add_column("AI Status", style="yellow")
        table.add_column("PR", style="green")
        table.add_column("Branch", style="blue")
        if verbose:
            table.add_column("Worktree", style="magenta")
            table.add_column("Repository", style="dim")
        table.add_column("Updated", style="dim")
        
        for state in sorted(workflow_states, key=lambda s: s.updated_at, reverse=True):
            pr_info = f"#{state.pr_number}" if state.pr_number else "N/A"
            branch_info = state.branch or "N/A"
            updated = state.updated_at.strftime("%Y-%m-%d %H:%M") if state.updated_at else "N/A"
            
            # Add status styling
            status_style = {
                "completed": "[green]",
                "failed": "[red]",
                "in_review": "[yellow]",
                "ready_to_merge": "[blue]",
                "implementing": "[cyan]",
                "fetching": "[blue]",
                "creating_pr": "[magenta]",
            }.get(state.status.value if hasattr(state.status, 'value') else str(state.status), "")
            
            status_display = f"{status_style}{state.status}[/]" if status_style else str(state.status)
            
            # Add AI status styling
            ai_status_value = state.ai_status.value if hasattr(state.ai_status, 'value') else str(state.ai_status)
            ai_status_style = {
                "not_started": "[dim]",
                "in_progress": "[yellow]",
                "implemented": "[green]",
                "failed": "[red]",
            }.get(ai_status_value, "")
            
            ai_status_display = f"{ai_status_style}{ai_status_value}[/]" if ai_status_style else ai_status_value
            
            row_data = [
                state.issue_id,
                status_display,
                ai_status_display,
                pr_info,
                branch_info,
            ]
            
            if verbose:
                # Add worktree info
                if state.worktree_info:
                    worktree_display = state.worktree_info.path
                    if state.worktree_info.exists():
                        worktree_display = f"✓ {worktree_display}"
                    else:
                        worktree_display = f"✗ {worktree_display}"
                    row_data.append(worktree_display)
                else:
                    row_data.append("N/A")
                
                # Add repository info
                if state.repository:
                    row_data.append(state.repository.full_name)
                else:
                    row_data.append("N/A")
            
            row_data.append(updated)
            table.add_row(*row_data)
        
        console.print(table)
        
        # Show summary
        status_counts = {}
        ai_status_counts = {}
        worktree_count = 0
        pr_count = 0
        
        for state in workflow_states:
            status_key = state.status.value if hasattr(state.status, 'value') else str(state.status)
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            
            ai_status_key = state.ai_status.value if hasattr(state.ai_status, 'value') else str(state.ai_status)
            ai_status_counts[ai_status_key] = ai_status_counts.get(ai_status_key, 0) + 1
            
            if state.worktree_info:
                worktree_count += 1
            if state.pr_number:
                pr_count += 1
        
        console.print(f"\n[bold]Summary:[/bold] {len(workflow_states)} active workflows")
        
        # Show workflow status breakdown
        console.print("  [bold]Workflow Status:[/bold]")
        for status, count in status_counts.items():
            console.print(f"    {status}: {count}")
        
        # Show AI status breakdown
        console.print("  [bold]AI Implementation:[/bold]")
        for ai_status, count in ai_status_counts.items():
            console.print(f"    {ai_status}: {count}")
        
        if verbose:
            console.print("  [bold]Resources:[/bold]")
            console.print(f"    Active worktrees: {worktree_count}")
            console.print(f"    Pull requests: {pr_count}")
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option("--force", "-f", is_flag=True, help="Force cleanup including active worktrees")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed cleanup information")
def cleanup(force: bool, verbose: bool) -> None:
    """Clean up completed workflow states and worktrees."""
    try:
        from auto.workflows import cleanup_process_workflow
        
        core = get_core()
        workflow_states = core.get_workflow_states()
        
        if not workflow_states:
            console.print("[yellow]No workflows to clean up.[/yellow]")
            return
        
        cleaned_count = 0
        worktree_cleaned_count = 0
        errors = []
        
        for state in workflow_states:
            should_cleanup = False
            
            # Determine if we should clean up this workflow
            if force:
                should_cleanup = True
                reason = "forced cleanup"
            elif state.status.value in ["completed", "failed"]:
                should_cleanup = True
                reason = f"status: {state.status.value}"
            
            if should_cleanup:
                if verbose:
                    console.print(f"[blue]Info:[/blue] Cleaning up {state.issue_id} ({reason})")
                
                try:
                    # Clean up worktree if it exists
                    if state.worktree_info:
                        if verbose:
                            console.print(f"  Removing worktree: {state.worktree_info.path}")
                        
                        success = cleanup_process_workflow(state.issue_id)
                        if success:
                            worktree_cleaned_count += 1
                            if verbose:
                                console.print("  [green]✓[/green] Worktree cleaned up")
                        else:
                            errors.append(f"Failed to clean up worktree for {state.issue_id}")
                    
                    cleaned_count += 1
                    
                except Exception as e:
                    error_msg = f"Failed to clean up {state.issue_id}: {e}"
                    errors.append(error_msg)
                    if verbose:
                        console.print(f"  [red]✗[/red] {error_msg}")
        
        # Also clean up completed states
        try:
            state_cleaned = core.cleanup_completed_states()
            if verbose and state_cleaned > 0:
                console.print(f"[green]✓[/green] Cleaned up {state_cleaned} workflow state file(s)")
        except Exception as e:
            errors.append(f"Failed to clean up state files: {e}")
        
        # Show results
        if cleaned_count > 0:
            console.print(f"[green]✓[/green] Cleaned up {cleaned_count} workflow(s)")
            if worktree_cleaned_count > 0:
                console.print(f"[green]✓[/green] Cleaned up {worktree_cleaned_count} worktree(s)")
        else:
            console.print("[yellow]No workflows needed cleanup.[/yellow]")
        
        if errors:
            console.print("\n[red]Errors encountered:[/red]")
            for error in errors:
                console.print(f"  - {error}")
            
            if not force:
                console.print("\n[yellow]Hint:[/yellow] Use --force to clean up all workflows including active ones")
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# Phase 2 implemented commands
@cli.command()
@click.argument("issue_id")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def fetch(issue_id: str, verbose: bool) -> None:
    """Fetch issue details and create workflow state."""
    try:
        from auto.workflows.fetch import FetchWorkflowError
        
        # Parse and validate issue identifier
        identifier = IssueIdentifier.parse(issue_id)
        
        if verbose:
            enable_verbose_logging()
            console.print(f"[blue]Info:[/blue] Parsing {identifier.provider.value} issue: {identifier.issue_id}")
        
        # Validate prerequisites
        if not validate_issue_access(identifier.issue_id):
            console.print(f"[red]Error:[/red] Cannot access issue {identifier.issue_id}")
            console.print("[yellow]Hint:[/yellow] Check authentication and repository access")
            sys.exit(1)
        
        # Run fetch workflow
        console.print(f"[blue]Info:[/blue] Fetching {identifier.provider.value} issue: {identifier.issue_id}")
        
        state = fetch_issue_workflow_sync(identifier.issue_id)
        
        if state.issue:
            # Success - show issue details
            console.print(f"[green]✓[/green] Fetched GitHub issue {state.issue.id}: [bold]{state.issue.title}[/bold]")
            
            if verbose:
                console.print(f"  Status: {state.issue.status}")
                console.print(f"  Type: {state.issue.issue_type.value if state.issue.issue_type else 'Unknown'}")
                if state.issue.assignee:
                    console.print(f"  Assignee: {state.issue.assignee}")
                if state.issue.labels:
                    console.print(f"  Labels: {', '.join(state.issue.labels)}")
                if state.issue.url:
                    console.print(f"  URL: {state.issue.url}")
            
            console.print("[green]✓[/green] Workflow state created")
            
            if verbose:
                console.print(f"  State file: .auto/state/{identifier.issue_id}.yaml")
                console.print(f"  Status: {state.status.value}")
        else:
            console.print("[red]Error:[/red] Failed to fetch issue details")
            sys.exit(1)
        
    except FetchWorkflowError as e:
        console.print(f"[red]Error:[/red] {e}")
        if "authentication" in str(e).lower():
            console.print("[yellow]Hint:[/yellow] Run 'gh auth login' to authenticate with GitHub")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Unexpected error: {e}")
        if verbose:
            import traceback
            console.print("[dim]" + traceback.format_exc() + "[/dim]")
        sys.exit(1)


@cli.command()
@click.argument("issue_id")
@click.option("--prompt", help="Custom prompt text for AI implementation")
@click.option("--prompt-file", help="Path to file containing custom prompt")
@click.option("--prompt-template", help="Named prompt template to use")
@click.option("--prompt-append", help="Text to append to default prompt")
@click.option("--show-prompt", is_flag=True, help="Show resolved prompt without execution")
@click.option("--agent", help="Custom AI agent to use for implementation")
@click.option("--no-pr", is_flag=True, help="Skip PR creation after implementation")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def implement(
    issue_id: str, 
    prompt: str, 
    prompt_file: str, 
    prompt_template: str, 
    prompt_append: str, 
    show_prompt: bool, 
    agent: str, 
    no_pr: bool, 
    verbose: bool
) -> None:
    """Run AI implementation for existing issue with custom prompt options."""
    try:
        from auto.workflows import (
            implement_issue_workflow, 
            create_pull_request_workflow,
            get_issue_from_state,
            validate_implementation_prerequisites,
            ImplementationError
        )
        from auto.workflows.pr_create import PRCreationError
        import asyncio
        
        # Parse issue identifier
        identifier = IssueIdentifier.parse(issue_id)
        
        if verbose:
            enable_verbose_logging()
            console.print(f"[blue]Info:[/blue] Implementing {identifier.provider.value} issue: {identifier.issue_id}")
        
        # Get core and existing state
        core = get_core()
        state = core.get_workflow_state(identifier.issue_id)
        
        if state is None:
            console.print(f"[red]Error:[/red] No workflow state found for {identifier.issue_id}")
            console.print("[yellow]Hint:[/yellow] Run 'auto fetch' or 'auto process' first to create the workflow")
            sys.exit(1)
        
        # Get issue from state
        issue = get_issue_from_state(identifier.issue_id)
        if issue is None:
            console.print(f"[red]Error:[/red] Issue details not found for {identifier.issue_id}")
            console.print("[yellow]Hint:[/yellow] Run 'auto fetch' first to load issue details")
            sys.exit(1)
        
        # Validate prerequisites
        try:
            validate_implementation_prerequisites(state)
        except ImplementationError as e:
            console.print(f"[red]Error:[/red] Prerequisites not met: {e}")
            console.print("[yellow]Hint:[/yellow] Ensure worktree exists and is properly configured")
            sys.exit(1)
        
        if verbose:
            console.print(f"[green]✓[/green] Found issue in worktree: {state.worktree}")
            if prompt_template:
                console.print(f"[blue]Info:[/blue] Using prompt template: {prompt_template}")
            if agent:
                console.print(f"[blue]Info:[/blue] Using custom agent: {agent}")
        
        # Override agent if specified
        if agent:
            config = get_config()
            original_agent = config.ai.implementation_agent
            config.ai.implementation_agent = agent
            if verbose:
                console.print(f"[blue]Info:[/blue] Agent override: {original_agent} → {agent}")
        
        # Run AI implementation
        console.print("[blue]Info:[/blue] Running AI implementation...")
        
        try:
            state = asyncio.run(implement_issue_workflow(
                issue=issue,
                workflow_state=state,
                prompt_override=prompt,
                prompt_file=prompt_file,
                prompt_template=prompt_template,
                prompt_append=prompt_append,
                show_prompt=show_prompt
            ))
            
            # Save state after implementation
            core.save_workflow_state(state)
            
            if show_prompt:
                console.print("[green]✓[/green] Prompt displayed")
                return
            
            # Show implementation results
            if state.ai_response and state.ai_response.success:
                console.print("[green]✓[/green] AI implementation completed")
                
                if verbose and state.ai_response:
                    file_count = len(state.ai_response.file_changes)
                    cmd_count = len(state.ai_response.commands)
                    console.print(f"  Files modified: {file_count}")
                    console.print(f"  Commands executed: {cmd_count}")
                    
                    if state.ai_response.file_changes:
                        console.print("  Changed files:")
                        for change in state.ai_response.file_changes[:5]:  # Show first 5
                            action = change.get('action', 'modified')
                            path = change.get('path', 'unknown')
                            console.print(f"    - {action.title()}: {path}")
                        if len(state.ai_response.file_changes) > 5:
                            console.print(f"    ... and {len(state.ai_response.file_changes) - 5} more")
                
                console.print("[green]✓[/green] Changes applied successfully")
                console.print("[green]✓[/green] Workflow state updated")
                
                # Create PR if not disabled
                if not no_pr:
                    console.print("[blue]Info:[/blue] Creating pull request...")
                    try:
                        state = asyncio.run(create_pull_request_workflow(
                            issue=issue,
                            workflow_state=state
                        ))
                        
                        core.save_workflow_state(state)
                        
                        if state.pr_number:
                            console.print(f"[green]✓[/green] Pull request created: #{state.pr_number}")
                            if verbose and state.repository:
                                pr_url = f"https://github.com/{state.repository.full_name}/pull/{state.pr_number}"
                                console.print(f"  URL: {pr_url}")
                        else:
                            console.print("[yellow]Warning:[/yellow] PR creation completed but no PR number available")
                        
                    except PRCreationError as e:
                        console.print(f"[red]Error:[/red] Failed to create PR: {e}")
                        console.print("[yellow]Note:[/yellow] Implementation completed successfully")
                        sys.exit(1)
                else:
                    console.print("[blue]Info:[/blue] PR creation skipped (--no-pr)")
                
            else:
                console.print("[red]Error:[/red] AI implementation failed")
                if state.ai_response and state.ai_response.content:
                    console.print(f"  Reason: {state.ai_response.content}")
                sys.exit(1)
            
        except ImplementationError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        
        # Show next steps
        if not no_pr and state.pr_number:
            console.print("\n[bold]Next steps:[/bold]")
            console.print("1. Review the created pull request")
            console.print("2. Address any review comments")
            console.print("3. Merge when approved")
        elif no_pr:
            console.print("\n[bold]Next steps:[/bold]")
            console.print("1. Review the implementation in the worktree")
            console.print("2. Run [cyan]auto status[/cyan] to check progress")
            console.print("3. Create PR manually when ready")
            
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Unexpected error: {e}")
        if verbose:
            import traceback
            console.print("[dim]" + traceback.format_exc() + "[/dim]")
        sys.exit(1)


@cli.command()
@click.argument("issue_id")
@click.option("--base-branch", "-b", help="Base branch for worktree (auto-detected if not specified)")
@click.option("--prompt", help="Custom prompt text for AI implementation")
@click.option("--prompt-file", help="Path to file containing custom prompt")
@click.option("--prompt-template", help="Named prompt template to use")
@click.option("--prompt-append", help="Text to append to default prompt")
@click.option("--show-prompt", is_flag=True, help="Show resolved prompt without execution")
@click.option("--agent", help="Custom AI agent to use for implementation")
@click.option("--no-ai", is_flag=True, help="Skip AI implementation step")
@click.option("--no-pr", is_flag=True, help="Skip PR creation step")
@click.option("--resume", is_flag=True, help="Resume interrupted workflow from saved state")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def process(
    issue_id: str, 
    base_branch: str, 
    prompt: str, 
    prompt_file: str, 
    prompt_template: str, 
    prompt_append: str, 
    show_prompt: bool, 
    agent: str, 
    no_ai: bool, 
    no_pr: bool, 
    resume: bool,
    verbose: bool
) -> None:
    """Process issue: fetch details, create worktree, run AI implementation, and create PR."""
    # Import workflow components
    from auto.workflows import (
        process_issue_workflow, 
        validate_process_prerequisites, 
        ProcessWorkflowError
    )
    
    try:
        
        # Parse issue identifier
        identifier = IssueIdentifier.parse(issue_id)
        
        if verbose:
            enable_verbose_logging()
            console.print(f"[blue]Info:[/blue] Processing {identifier.provider.value} issue: {identifier.issue_id}")
            if resume:
                console.print("[blue]Info:[/blue] Resuming from existing workflow state")
            if no_ai:
                console.print("[blue]Info:[/blue] AI implementation step will be skipped")
            if no_pr:
                console.print("[blue]Info:[/blue] PR creation step will be skipped")
            if prompt_template:
                console.print(f"[blue]Info:[/blue] Using prompt template: {prompt_template}")
            if agent:
                console.print(f"[blue]Info:[/blue] Using custom agent: {agent}")
        
        # Validate prerequisites (skip for resume if existing state is valid)
        if not resume:
            console.print("[blue]Info:[/blue] Validating prerequisites...")
            errors = validate_process_prerequisites(identifier.issue_id)
            
            if errors:
                console.print("[red]Error:[/red] Prerequisites not met:")
                for error in errors:
                    console.print(f"  - {error}")
                sys.exit(1)
            
            if verbose:
                console.print("[green]✓[/green] Prerequisites validated")
        else:
            # For resume, just check if state exists
            core = get_core()
            existing_state = core.get_workflow_state(identifier.issue_id)
            if existing_state is None:
                console.print(f"[red]Error:[/red] No existing workflow state found for {identifier.issue_id}")
                console.print("[yellow]Hint:[/yellow] Use 'auto process' without --resume to start a new workflow")
                sys.exit(1)
            
            if verbose:
                console.print(f"[green]✓[/green] Found existing workflow state (status: {existing_state.status.value})")
        
        # Override agent if specified
        if agent:
            config = get_config()
            original_agent = config.ai.implementation_agent
            config.ai.implementation_agent = agent
            if verbose:
                console.print(f"[blue]Info:[/blue] Agent override: {original_agent} → {agent}")
        
        # Run enhanced process workflow
        console.print(f"[blue]Info:[/blue] Processing issue {identifier.issue_id}...")
        
        state = process_issue_workflow(
            issue_id=identifier.issue_id, 
            base_branch=base_branch,
            enable_ai=not no_ai,
            enable_pr=not no_pr,
            prompt_override=prompt,
            prompt_file=prompt_file,
            prompt_template=prompt_template,
            prompt_append=prompt_append,
            show_prompt=show_prompt,
            resume=resume
        )
        
        # Handle show prompt early exit
        if show_prompt:
            console.print("[green]✓[/green] Prompt displayed")
            return
        
        # Success - show results
        if state.issue:
            console.print(f"[green]✓[/green] Processed issue {state.issue.id}: [bold]{state.issue.title}[/bold]")
        else:
            console.print(f"[green]✓[/green] Processed issue {identifier.issue_id}")
        
        if state.worktree_info:
            console.print(f"[green]✓[/green] Created worktree: [cyan]{state.worktree_info.path}[/cyan]")
            console.print(f"[green]✓[/green] Created branch: [cyan]{state.worktree_info.branch}[/cyan]")
            
            if verbose:
                base_branch_used = state.metadata.get('base_branch', 'unknown')
                console.print(f"  Base branch: {base_branch_used}")
                console.print(f"  Worktree exists: {state.worktree_info.exists()}")
                if state.repository:
                    console.print(f"  Repository: {state.repository.full_name}")
        
        # Show AI implementation results
        if not no_ai and state.ai_response:
            if state.ai_response.success:
                console.print("[green]✓[/green] AI implementation completed")
                if verbose:
                    file_count = len(state.ai_response.file_changes)
                    cmd_count = len(state.ai_response.commands)
                    console.print(f"  Files modified: {file_count}")
                    console.print(f"  Commands executed: {cmd_count}")
            else:
                console.print("[yellow]Warning:[/yellow] AI implementation failed")
        elif no_ai:
            console.print("[blue]Info:[/blue] AI implementation skipped")
        
        # Show PR creation results
        if not no_pr and state.pr_number:
            console.print(f"[green]✓[/green] Pull request created: #{state.pr_number}")
            if verbose and state.repository:
                pr_url = f"https://github.com/{state.repository.full_name}/pull/{state.pr_number}"
                console.print(f"  URL: {pr_url}")
        elif no_pr:
            console.print("[blue]Info:[/blue] PR creation skipped")
        
        console.print("[green]✓[/green] Process workflow completed")
        
        if verbose:
            console.print(f"  State file: .auto/state/{identifier.issue_id}.yaml")
            console.print(f"  Status: {state.status.value}")
        
        # Show next steps based on what was completed
        console.print("\n[bold]Next steps:[/bold]")
        if state.pr_number:
            console.print("1. Review the created pull request")
            console.print("2. Address any review comments")  
            console.print("3. Merge when approved")
        elif not no_ai and not no_pr:
            console.print("1. Review the implementation in the worktree")
            console.print("2. Create PR manually when ready")
            console.print("3. Run [cyan]auto status[/cyan] to check progress")
        elif state.worktree_info:
            console.print(f"1. Change to worktree directory: [cyan]cd {state.worktree_info.path}[/cyan]")
            if no_ai:
                console.print("2. Start implementing the issue")
            console.print("3. Run [cyan]auto status[/cyan] to check progress")
        
    except ProcessWorkflowError as e:
        console.print(f"[red]Error:[/red] {e}")
        if "authentication" in str(e).lower():
            console.print("[yellow]Hint:[/yellow] Run 'gh auth login' to authenticate with GitHub")
        elif "git repository" in str(e).lower():
            console.print("[yellow]Hint:[/yellow] Run this command from within a git repository")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Unexpected error: {e}")
        if verbose:
            import traceback
            console.print("[dim]" + traceback.format_exc() + "[/dim]")
        sys.exit(1)


@cli.command()
@click.argument("pr_id")
@click.option("--force", is_flag=True, help="Force review even if already reviewed")
@click.option("--agent", default=None, help="Override AI agent for review")
def review(pr_id: str, force: bool, agent: Optional[str]) -> None:
    """Trigger AI review on existing PR."""
    try:
        from auto.integrations.github import detect_repository
        from auto.workflows.review import trigger_ai_review
        
        console.print(f"[blue]Starting AI review for PR #{pr_id}...[/blue]")
        
        # Detect repository
        try:
            repo = detect_repository()
        except Exception as e:
            console.print(f"[red]Error:[/red] Could not detect repository: {e}")
            sys.exit(1)
        
        # Parse PR ID
        pr_number = int(pr_id) if pr_id.isdigit() else int(pr_id.lstrip('#'))
        
        # Trigger AI review
        import asyncio
        success = asyncio.run(trigger_ai_review(
            pr_number=pr_number,
            owner=repo.owner,
            repo=repo.name,
            force_review=force,
            agent_override=agent
        ))
        
        if success:
            console.print(f"[green]✓[/green] AI review completed for PR #{pr_number}")
            console.print(f"[blue]View the review:[/blue] https://github.com/{repo.owner}/{repo.name}/pull/{pr_number}")
        else:
            console.print(f"[red]✗[/red] AI review failed for PR #{pr_number}")
            sys.exit(1)
            
    except ValueError as e:
        console.print(f"[red]Error:[/red] Invalid PR ID format: {pr_id}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Review command failed: {e}")
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.argument("pr_id")
@click.option("--force", is_flag=True, help="Force update even if no unresolved comments")
@click.option("--agent", default=None, help="Override AI agent for updates")
def update(pr_id: str, force: bool, agent: Optional[str]) -> None:
    """Update PR based on review comments."""
    try:
        from auto.integrations.github import detect_repository
        from auto.workflows.review_update import execute_review_update
        
        console.print(f"[blue]Updating PR #{pr_id} based on review comments...[/blue]")
        
        # Detect repository
        try:
            repo = detect_repository()
        except Exception as e:
            console.print(f"[red]Error:[/red] Could not detect repository: {e}")
            sys.exit(1)
        
        # Parse PR ID
        pr_number = int(pr_id) if pr_id.isdigit() else int(pr_id.lstrip('#'))
        
        # Execute review update
        import asyncio
        success = asyncio.run(execute_review_update(
            pr_number=pr_number,
            owner=repo.owner,
            repo=repo.name,
            force_update=force,
            agent_override=agent
        ))
        
        if success:
            console.print(f"[green]✓[/green] PR #{pr_number} updated successfully")
            console.print(f"[blue]View the updates:[/blue] https://github.com/{repo.owner}/{repo.name}/pull/{pr_number}")
        else:
            console.print(f"[red]✗[/red] Failed to update PR #{pr_number}")
            sys.exit(1)
            
    except ValueError as e:
        console.print(f"[red]Error:[/red] Invalid PR ID format: {pr_id}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Update command failed: {e}")
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.argument("pr_id")
@click.option("--force", is_flag=True, help="Force merge even if some checks fail")
@click.option("--method", type=click.Choice(["merge", "squash", "rebase"]), default="merge", help="Merge method")
@click.option("--cleanup/--no-cleanup", default=True, help="Clean up worktree after merge")
def merge(pr_id: str, force: bool, method: str, cleanup: bool) -> None:
    """Merge PR after approval validation."""
    try:
        from auto.integrations.github import detect_repository
        from auto.workflows.merge import execute_auto_merge
        from auto.core import get_core
        
        console.print(f"[blue]Starting merge process for PR #{pr_id}...[/blue]")
        
        # Detect repository
        try:
            repo = detect_repository()
        except Exception as e:
            console.print(f"[red]Error:[/red] Could not detect repository: {e}")
            sys.exit(1)
        
        # Parse PR ID
        pr_number = int(pr_id) if pr_id.isdigit() else int(pr_id.lstrip('#'))
        
        # Get worktree path if cleanup is enabled
        worktree_path = None
        if cleanup:
            try:
                core = get_core()
                # Try to find associated worktree for this PR
                # This would need to be implemented based on state management
                pass
            except Exception:
                logger.warning("Could not determine worktree path for cleanup")
        
        # Execute merge
        import asyncio
        success = asyncio.run(execute_auto_merge(
            pr_number=pr_number,
            owner=repo.owner,
            repo=repo.name,
            worktree_path=worktree_path,
            force=force
        ))
        
        if success:
            console.print(f"[green]✓[/green] PR #{pr_number} merged successfully")
            if cleanup and worktree_path:
                console.print(f"[green]✓[/green] Worktree cleaned up")
        else:
            console.print(f"[red]✗[/red] Failed to merge PR #{pr_number}")
            sys.exit(1)
            
    except ValueError as e:
        console.print(f"[red]Error:[/red] Invalid PR ID format: {pr_id}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Merge command failed: {e}")
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option("--state", "-s", default="open", type=click.Choice(["open", "closed", "all"]), help="Filter by state (default: open)")
@click.option("--assignee", "-a", help="Filter by assignee username")
@click.option("--label", "-l", "labels", multiple=True, help="Filter by label (can be used multiple times)")
@click.option("--limit", "-L", default=30, type=int, help="Maximum number of issues to fetch (default: 30)")
@click.option("--web", "-w", is_flag=True, help="Open issues in web browser")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed issue information")
def issues(state: str, assignee: str, labels: tuple, limit: int, web: bool, verbose: bool) -> None:
    """List available issues for the current project."""
    try:
        from auto.integrations.github import GitHubIntegration, GitHubIntegrationError
        
        # If web flag is set, delegate to gh CLI
        if web:
            try:
                result = run_command("gh issue list --web", check=True)
                return
            except Exception as e:
                console.print(f"[red]Error:[/red] Failed to open issues in browser: {e}")
                sys.exit(1)
        
        # Initialize GitHub integration
        try:
            github = GitHubIntegration()
        except GitHubIntegrationError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        
        # Convert labels tuple to list
        labels_list = list(labels) if labels else None
        
        if verbose:
            enable_verbose_logging()
            console.print(f"[blue]Info:[/blue] Fetching issues (state: {state}, limit: {limit})")
            if assignee:
                console.print(f"  Assignee filter: {assignee}")
            if labels_list:
                console.print(f"  Label filters: {', '.join(labels_list)}")
        
        # Fetch issues
        try:
            issues_list = github.list_issues(
                state=state,
                assignee=assignee,
                labels=labels_list,
                limit=limit
            )
        except GitHubIntegrationError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        
        if not issues_list:
            console.print(f"[yellow]No {state} issues found.[/yellow]")
            return
        
        # Display issues in a table
        table = Table(title=f"GitHub Issues ({state})")
        table.add_column("ID", style="cyan", width=8)
        table.add_column("Title", min_width=30, max_width=60)
        table.add_column("State", style="green", width=8)
        table.add_column("Assignee", style="blue", width=12)
        table.add_column("Labels", style="magenta", width=20)
        table.add_column("Updated", style="dim", width=12)
        
        for issue in issues_list:
            # Format title - truncate if too long but ensure beginning is shown
            title_display = issue.title
            if len(title_display) > 57:  # Leave room for ellipsis
                title_display = title_display[:57] + "..."
            
            # Format assignee
            assignee_display = issue.assignee or "—"
            
            # Format labels
            labels_display = ", ".join(issue.labels[:3]) if issue.labels else "—"
            if len(issue.labels) > 3:
                labels_display += f" (+{len(issue.labels) - 3})"
            
            # Format updated time
            if issue.updated_at:
                updated_display = issue.updated_at.strftime("%Y-%m-%d")
            else:
                updated_display = "—"
            
            # Add status styling
            status_style = {
                "open": "[green]open[/green]",
                "closed": "[red]closed[/red]",
            }.get(issue.status.value.lower(), str(issue.status.value))
            
            table.add_row(
                issue.id,
                title_display,
                status_style,
                assignee_display,
                labels_display,
                updated_display
            )
        
        console.print(table)
        
        # Show summary
        console.print(f"\n[bold]Found {len(issues_list)} {state} issue(s)[/bold]")
        
        if verbose:
            console.print("[dim]Use 'auto fetch <issue-id>' to start working on an issue[/dim]")
            console.print("[dim]Use 'auto issues --web' to view issues in browser[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error:[/red] Unexpected error: {e}")
        if verbose:
            import traceback
            console.print("[dim]" + traceback.format_exc() + "[/dim]")
        sys.exit(1)


# Add alias for issues command
@cli.command("ls")
@click.option("--state", "-s", default="open", type=click.Choice(["open", "closed", "all"]), help="Filter by state (default: open)")
@click.option("--assignee", "-a", help="Filter by assignee username")
@click.option("--label", "-l", "labels", multiple=True, help="Filter by label (can be used multiple times)")
@click.option("--limit", "-L", default=30, type=int, help="Maximum number of issues to fetch (default: 30)")
@click.option("--web", "-w", is_flag=True, help="Open issues in web browser")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed issue information")
def ls_alias(state: str, assignee: str, labels: tuple, limit: int, web: bool, verbose: bool) -> None:
    """List available issues for the current project (alias for 'issues')."""
    # Call the main issues command with same parameters
    ctx = click.get_current_context()
    ctx.invoke(issues, state=state, assignee=assignee, labels=labels, limit=limit, web=web, verbose=verbose)


@cli.command()
@click.argument("issue_id")
@click.option("--web", "-w", is_flag=True, help="Open issue in web browser")
@click.option("--verbose", "-v", is_flag=True, help="Show additional metadata")
def show(issue_id: str, web: bool, verbose: bool) -> None:
    """Show detailed information for a specific issue."""
    try:
        from auto.integrations.github import GitHubIntegration, GitHubIntegrationError
        
        # Parse issue identifier
        identifier = IssueIdentifier.parse(issue_id)
        
        # If web flag is set, delegate to gh CLI
        if web:
            try:
                result = run_command(f"gh issue view {identifier.issue_id} --web", check=True)
                return
            except Exception as e:
                console.print(f"[red]Error:[/red] Failed to open issue in browser: {e}")
                sys.exit(1)
        
        # Initialize GitHub integration
        try:
            github = GitHubIntegration()
        except GitHubIntegrationError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        
        if verbose:
            enable_verbose_logging()
            console.print(f"[blue]Info:[/blue] Fetching {identifier.provider.value} issue: {identifier.issue_id}")
        
        # Fetch issue details
        try:
            issue = github.fetch_issue(identifier.issue_id)
        except GitHubIntegrationError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        
        # Display issue details
        console.print(f"[bold cyan]Issue {issue.id}[/bold cyan]: [bold]{issue.title}[/bold]")
        console.print()
        
        # Show metadata
        metadata_table = Table(show_header=False, box=None, padding=(0, 1))
        metadata_table.add_column("Field", style="dim", width=12)
        metadata_table.add_column("Value")
        
        metadata_table.add_row("Status:", f"[{'green' if issue.status.value.lower() == 'open' else 'red'}]{issue.status.value}[/]")
        metadata_table.add_row("Assignee:", issue.assignee or "Unassigned")
        
        if issue.labels:
            labels_display = ", ".join([f"[magenta]{label}[/magenta]" for label in issue.labels])
            metadata_table.add_row("Labels:", labels_display)
        else:
            metadata_table.add_row("Labels:", "None")
        
        if verbose:
            if issue.created_at:
                metadata_table.add_row("Created:", issue.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
            if issue.updated_at:
                metadata_table.add_row("Updated:", issue.updated_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
            if issue.url:
                metadata_table.add_row("URL:", issue.url)
        
        console.print(metadata_table)
        console.print()
        
        # Show description
        if issue.description and issue.description.strip():
            console.print("[bold]Description:[/bold]")
            console.print()
            # Render markdown-like content with basic formatting
            description_lines = issue.description.strip().split('\n')
            for line in description_lines:
                if line.strip().startswith('# '):
                    console.print(f"[bold]{line.strip()[2:]}[/bold]")
                elif line.strip().startswith('## '):
                    console.print(f"[bold]{line.strip()[3:]}[/bold]")
                elif line.strip().startswith('- ') or line.strip().startswith('* '):
                    console.print(f"  • {line.strip()[2:]}")
                elif line.strip().startswith('```'):
                    console.print(f"[dim]{line}[/dim]")
                else:
                    console.print(line)
        else:
            console.print("[dim]No description provided[/dim]")
        
        console.print()
        
        if not web and not verbose:
            console.print(f"[dim]Use 'auto show {issue_id} --web' to view in browser[/dim]")
            console.print(f"[dim]Use 'auto fetch {issue_id}' to start working on this issue[/dim]")
        
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Unexpected error: {e}")
        if verbose:
            import traceback
            console.print("[dim]" + traceback.format_exc() + "[/dim]")
        sys.exit(1)


@cli.command()
@click.argument("issue_id")
def run(issue_id: str) -> None:
    """Run complete workflow for issue (Phase 6+)."""
    try:
        identifier = IssueIdentifier.parse(issue_id)
        console.print(f"[blue]Info:[/blue] Would run complete workflow for {identifier.provider.value} issue: {identifier.issue_id}")
        console.print("[yellow]Note:[/yellow] Full implementation coming in Phase 6")
        
        # For Phase 1, just create a workflow state
        core = get_core()
        state = core.create_workflow_state(identifier.issue_id)
        console.print(f"[green]✓[/green] Created workflow state for {identifier.issue_id}")
        
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to create workflow: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
