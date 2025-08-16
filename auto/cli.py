"""Click CLI interface for the auto tool."""

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from auto import __version__
from auto.config import ConfigError, config_manager
from auto.core import get_core
from auto.models import IssueIdentifier
from auto.utils.logger import get_logger

logger = get_logger(__name__)
console = Console()


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
        import logging
        logging.getLogger("auto").setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")
    
    # If no subcommand and no flags, show help
    if ctx.invoked_subcommand is None and not version:
        click.echo(ctx.get_help())


@cli.command()
@click.option(
    "--project", "-p", is_flag=True,
    help="Initialize project config instead of user config"
)
def init(project: bool) -> None:
    """Initialize auto configuration."""
    try:
        config_path = config_manager.create_default_config(user_level=not project)
        
        config_type = "project" if project else "user"
        console.print(f"[green]✓[/green] {config_type.title()} configuration initialized: {config_path}")
        
        # Show next steps
        console.print("\n[bold]Next steps:[/bold]")
        console.print("1. Edit the configuration file to customize settings")
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
        table.add_column("Path", style="white")
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
            }.get(state.status.value if hasattr(state.status, 'value') else str(state.status), "")
            
            status_display = f"{status_style}{state.status}[/]" if status_style else str(state.status)
            
            row_data = [
                state.issue_id,
                status_display,
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
        worktree_count = 0
        for state in workflow_states:
            status_key = state.status.value if hasattr(state.status, 'value') else str(state.status)
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            if state.worktree_info:
                worktree_count += 1
        
        console.print(f"\n[bold]Summary:[/bold] {len(workflow_states)} active workflows")
        for status, count in status_counts.items():
            console.print(f"  {status}: {count}")
        
        if verbose and worktree_count > 0:
            console.print(f"  Active worktrees: {worktree_count}")
        
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
                                console.print(f"  [green]✓[/green] Worktree cleaned up")
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
            console.print(f"\n[red]Errors encountered:[/red]")
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
        from auto.workflows import fetch_issue_workflow_sync, validate_issue_access, FetchWorkflowError
        
        # Parse and validate issue identifier
        identifier = IssueIdentifier.parse(issue_id)
        
        if verbose:
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
            
            console.print(f"[green]✓[/green] Workflow state created")
            
            if verbose:
                console.print(f"  State file: .auto/state/{identifier.issue_id}.yaml")
                console.print(f"  Status: {state.status.value}")
        else:
            console.print(f"[red]Error:[/red] Failed to fetch issue details")
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
@click.option("--base-branch", "-b", help="Base branch for worktree (auto-detected if not specified)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def process(issue_id: str, base_branch: str, verbose: bool) -> None:
    """Process issue by fetching details and creating worktree for development."""
    try:
        from auto.workflows import (
            process_issue_workflow, 
            validate_process_prerequisites, 
            ProcessWorkflowError
        )
        
        # Parse issue identifier
        identifier = IssueIdentifier.parse(issue_id)
        
        if verbose:
            console.print(f"[blue]Info:[/blue] Processing {identifier.provider.value} issue: {identifier.issue_id}")
        
        # Validate prerequisites
        console.print("[blue]Info:[/blue] Validating prerequisites...")
        errors = validate_process_prerequisites(identifier.issue_id)
        
        if errors:
            console.print(f"[red]Error:[/red] Prerequisites not met:")
            for error in errors:
                console.print(f"  - {error}")
            sys.exit(1)
        
        if verbose:
            console.print("[green]✓[/green] Prerequisites validated")
        
        # Run process workflow
        console.print(f"[blue]Info:[/blue] Processing issue {identifier.issue_id}...")
        
        state = process_issue_workflow(identifier.issue_id, base_branch)
        
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
        
        console.print(f"[green]✓[/green] Ready for development")
        
        if verbose:
            console.print(f"  State file: .auto/state/{identifier.issue_id}.yaml")
            console.print(f"  Status: {state.status.value}")
        
        # Show next steps
        console.print("\n[bold]Next steps:[/bold]")
        if state.worktree_info:
            console.print(f"1. Change to worktree directory: [cyan]cd {state.worktree_info.path}[/cyan]")
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
def review(pr_id: str) -> None:
    """Trigger AI review on existing PR (Phase 4+)."""
    console.print(f"[blue]Info:[/blue] Would trigger AI review on PR: {pr_id}")
    console.print("[yellow]Note:[/yellow] Full implementation coming in Phase 4")


@cli.command()
@click.argument("pr_id")
def update(pr_id: str) -> None:
    """Update PR based on review comments (Phase 4+)."""
    console.print(f"[blue]Info:[/blue] Would update PR based on reviews: {pr_id}")
    console.print("[yellow]Note:[/yellow] Full implementation coming in Phase 4")


@cli.command()
@click.argument("pr_id")
def merge(pr_id: str) -> None:
    """Merge PR after approval (Phase 5+)."""
    console.print(f"[blue]Info:[/blue] Would merge PR: {pr_id}")
    console.print("[yellow]Note:[/yellow] Full implementation coming in Phase 5")


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