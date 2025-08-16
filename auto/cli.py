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
def status() -> None:
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
            }.get(state.status, "")
            
            status_display = f"{status_style}{state.status}[/]" if status_style else state.status
            
            table.add_row(
                state.issue_id,
                status_display,
                pr_info,
                branch_info,
                updated,
            )
        
        console.print(table)
        
        # Show summary
        status_counts = {}
        for state in workflow_states:
            status_counts[state.status] = status_counts.get(state.status, 0) + 1
        
        console.print(f"\n[bold]Summary:[/bold] {len(workflow_states)} active workflows")
        for status, count in status_counts.items():
            console.print(f"  {status}: {count}")
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
def cleanup() -> None:
    """Clean up completed workflow states."""
    try:
        core = get_core()
        cleaned = core.cleanup_completed_states()
        
        if cleaned > 0:
            console.print(f"[green]✓[/green] Cleaned up {cleaned} completed workflow state(s)")
        else:
            console.print("[yellow]No completed workflows to clean up.[/yellow]")
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# Phase 1 stub commands - will be implemented in later phases
@cli.command()
@click.argument("issue_id")
def fetch(issue_id: str) -> None:
    """Fetch issue details (Phase 2+)."""
    try:
        identifier = IssueIdentifier.parse(issue_id)
        console.print(f"[blue]Info:[/blue] Would fetch {identifier.provider.value} issue: {identifier.issue_id}")
        console.print("[yellow]Note:[/yellow] Full implementation coming in Phase 2")
        
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.argument("issue_id")
def process(issue_id: str) -> None:
    """Process issue with AI implementation (Phase 3+)."""
    try:
        identifier = IssueIdentifier.parse(issue_id)
        console.print(f"[blue]Info:[/blue] Would process {identifier.provider.value} issue: {identifier.issue_id}")
        console.print("[yellow]Note:[/yellow] Full implementation coming in Phase 3")
        
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
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