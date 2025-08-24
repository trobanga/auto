# auto - Automatic User Task Orchestrator

## Overview
A Python-based CLI tool that automates the complete workflow from issue to merged PR, including iterative review cycles with both AI and human reviewers.

## Primary Usage
```bash
auto <issue-id>  # Complete workflow with review cycles
```

This single command will:
1. Fetch issue from GitHub/Linear
2. Create git worktree with proper branch naming
3. Let AI implement the solution (using configured agent)
4. Run tests (if configured)
5. Create pull request
6. **Trigger AI review and post comments**
7. **Wait for human review**
8. **Iterate: Address review comments (AI + human) until approved**
9. Merge PR after approval
10. Clean up worktree
11. Update issue status

## Architecture
Python-based CLI tool with async support, integrating GitHub/Linear APIs and AI workflows with iterative review cycles.

### Project Structure
```
auto/
├── pyproject.toml           # Project dependencies & metadata
├── README.md                # User documentation
├── CLAUDE.md                # Enhanced project instructions
├── auto/
│   ├── __init__.py
│   ├── __main__.py         # Entry point for `python -m auto`
│   ├── cli.py              # Click CLI interface
│   ├── config.py           # Configuration management
│   ├── core.py             # Main workflow orchestrator
│   ├── models.py           # Data models (Issue, PR, etc.)
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── github.py       # GitHub integration via gh CLI
│   │   ├── linear.py       # Linear integration
│   │   ├── git.py          # Git worktree management
│   │   └── ai.py           # Claude AI integration
│   ├── workflows/
│   │   ├── __init__.py
│   │   ├── full.py         # Complete auto workflow
│   │   ├── fetch.py        # Issue fetching
│   │   ├── process.py      # AI processing
│   │   ├── review.py       # Review cycle workflow
│   │   ├── update.py       # PR update workflow
│   │   └── cleanup.py      # Worktree cleanup
│   └── utils/
│       ├── __init__.py
│       ├── logger.py       # Logging utilities
│       └── shell.py        # Shell command execution
├── tests/
│   └── test_*.py
└── scripts/
    └── install.sh          # Installation helper
```

## Review Cycle
The tool implements an iterative review process:
1. **AI Review**: Automatically reviews the PR and posts comments
2. **Human Review**: Waits for human reviewer feedback
3. **AI Updates**: Uses AI to address review comments
4. **Repeat**: Continues until PR is approved or max iterations reached

## Configuration
Nested config structure:
- `~/.auto/config.yaml` - User-wide settings
- `<project>/.auto/config.yaml` - Project-specific overrides
- Environment variables - Runtime overrides

### Config Schema
```yaml
# ~/.auto/config.yaml
version: 1.0
defaults:
  auto_merge: false
  delete_branch_on_merge: true
  worktree_base: "../{project}-worktrees"
  max_review_iterations: 10  # Safety limit
  
github:
  default_org: null
  default_reviewer: null
  pr_template: .github/pull_request_template.md
  
linear:
  api_key: ${LINEAR_API_KEY}
  workspace: null
  auto_assign: true
  
ai:
  command: "claude"
  implementation_agent: "coder"              # Initial implementation
  review_agent: "pull-request-reviewer"     # Review PRs
  update_agent: "coder"                     # Address review comments
  implementation_prompt: "Implement the following issue: {description}"
  review_prompt: "Review this PR critically for bugs, security issues, performance, and best practices. Be thorough and specific."
  update_prompt: "Address the following review comments: {comments}"
  
workflows:
  branch_naming: "auto/{issue_type}/{issue_id}"
  commit_convention: "conventional"
  ai_review_first: true          # AI reviews before human
  require_human_approval: true   # Must have human approval
  test_command: null            # e.g., "npm test", "pytest"
  review_check_interval: 60     # seconds between checking for new reviews
```

## Commands

### Primary Command
```bash
auto <id>                    # Complete workflow with review cycles
```

### Subcommands for Control
```bash
auto init                    # Initialize project config
auto issues                  # List available issues for current project
auto ls                      # Alias for 'auto issues'
auto fetch <id>              # Just fetch issue details
auto process <id>            # Fetch + AI implementation
auto review <pr-id>          # Trigger AI review on existing PR
auto update <pr-id>          # Update PR based on review comments
auto merge <pr-id>           # Complete merge after approval
auto cleanup                 # Remove completed worktrees
auto status                  # Show active worktrees/PRs with review status
auto config <get|set> <key>  # Configuration management
```

### Issue Listing Commands
```bash
auto issues                  # List open issues (default)
auto issues --state all      # List all issues (open + closed)
auto issues --state closed   # List only closed issues
auto issues --assignee user  # Filter by assignee
auto issues --label bug      # Filter by label (can use multiple times)
auto issues --limit 50       # Change result limit (default: 30)
auto issues --web            # Open issues in web browser
auto issues --verbose        # Show detailed information
auto ls                      # Short alias for 'auto issues'
```

## State Management
The tool maintains state for each PR in `.auto/state/` to handle:
- Resume interrupted workflows
- Track review iterations
- Monitor PR status
- Manage worktrees

State file example:
```yaml
# .auto/state/<pr-id>.yaml
pr_number: 123
issue_id: "ENG-456"
branch: "auto/feature/ENG-456"
worktree: "../project-worktrees/auto-feature-ENG-456"
status: "in_review"
review_iteration: 2
reviews:
  - type: "ai"
    timestamp: "2024-01-15T10:00:00Z"
    status: "comments_posted"
  - type: "human"
    reviewer: "john_doe"
    timestamp: "2024-01-15T11:00:00Z"
    status: "changes_requested"
  - type: "ai_update"
    timestamp: "2024-01-15T11:30:00Z"
    status: "completed"
```

## Issue ID Formats
- GitHub: `#123`, `gh-123`, or full URL
- Linear: `ENG-123` or full URL
- Auto-detection based on format

## Integration Details

### Python 
- Before finishing:
  - use `rust check auto tests --fix` and make sure there are no issues
  - use `rust format auto tests`
  - make sure `mypy auto` shows no issues
  - All tests musts pass: `pytest .`


### GitHub Integration
- Use `gh` CLI for all operations
- Support both issue and PR URLs as input
- Auto-detect repository from git remote

### Linear Integration
- Use Linear API or MCP tools
- Map Linear statuses to workflow stages
- Support Linear issue URLs

### AI Integration
- Wrap `claude` command with proper agent selection
- Support different agents for different tasks:
  - `coder` for implementation
  - `pull-request-reviewer` for PR reviews
  - `debugger` for fixing failed tests
- Include issue description, acceptance criteria
- Parse AI responses for actionable items

## Requirements
- Python 3.8+
- gh CLI (for GitHub)
- git 2.15+ (for worktrees)
- claude CLI
- Optional: Linear API access

## Installation
```bash
# Install globally
pip install --user .

# Or use pipx for isolated environment
pipx install .

# Initialize for current project
auto init

# Configure GitHub token (if not using gh auth)
auto config set github.token <token>

# Configure AI agent
auto config set ai.implementation_agent coder
```

## Shell Completions

### Zsh Plugin for Tab Completions
A zsh plugin is needed to provide intelligent tab completions for the auto CLI tool.

**Required Features:**
- Command completion for all subcommands (init, issues, ls, fetch, process, implement, review, update, merge, cleanup, status, config, show)
- Issue ID completion from available GitHub/Linear issues
- PR ID completion from open pull requests
- Config key completion for `auto config get/set` commands
- Option flag completion (--verbose, --state, --assignee, --label, etc.)
- File path completion for prompt files (--prompt-file)
- Template name completion for prompt templates (--prompt-template)
- Agent name completion (--agent)

**Plugin Structure:**
```
scripts/
├── auto.plugin.zsh          # Main plugin file
├── _auto                    # Zsh completion function
└── completions/
    ├── _auto_issues         # Issue ID completion helper
    ├── _auto_prs           # PR ID completion helper
    ├── _auto_config        # Config key completion helper
    └── _auto_templates     # Template completion helper
```

**Installation for Users:**
```bash
# For oh-my-zsh users
mkdir -p ~/.oh-my-zsh/custom/plugins/auto
cp scripts/* ~/.oh-my-zsh/custom/plugins/auto/
# Add 'auto' to plugins in ~/.zshrc

# For manual installation
cp scripts/_auto /usr/local/share/zsh/site-functions/
# Reload zsh completions
```

**Dynamic Completion Features:**
- Cache issue/PR lists for performance
- Refresh cache on command execution
- Context-aware completion based on current repository
- Support for both GitHub and Linear issue formats

## Implementation Timeline
1. **Phase 1**: Core structure, config system, basic CLI
2. **Phase 2**: GitHub integration, worktree management
3. **Phase 3**: AI implementation and initial PR creation
4. **Phase 4**: Review cycle implementation (AI review → human review → updates)
5. **Phase 5**: State management, error recovery, testing
6. **Phase 6**: Linear integration, polish, documentation
7. **Phase 7**: Zsh Plugin
