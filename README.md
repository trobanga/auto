# auto - Automatic User Task Orchestrator

A Python-based CLI tool that automates the complete workflow from issue to merged PR, including iterative review cycles with both AI and human reviewers.

## Overview

`auto` streamlines your development workflow by automating the entire process from issue creation to PR merge. Simply run `auto <issue-id>` and watch as it:

1. 🔍 Fetches the issue from GitHub or Linear
2. 🌿 Creates a git worktree with proper branch naming
3. 🤖 Implements the solution using AI (configurable agents)
4. 🧪 Runs tests (if configured)
5. 📝 Creates a pull request
6. 👁️ Triggers AI review and posts comments
7. ⏳ Waits for human review
8. 🔄 Iterates: Addresses review comments until approved
9. ✅ Merges PR after approval
10. 🧹 Cleans up worktree and updates issue status

## Installation

### Prerequisites

- Python 3.8+
- [GitHub CLI (`gh`)](https://cli.github.com/) for GitHub integration
- Git 2.15+ (for worktree support)
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) for AI integration
- Optional: Linear API access for Linear integration

### Install auto

```bash
# Install globally
pip install --user .

# Or use pipx for isolated environment (recommended)
pipx install .

# Initialize for current project
cd your-project
auto init
```

### Configure GitHub

If you haven't already authenticated with GitHub CLI:

```bash
gh auth login
```

### Configure AI Agent

```bash
# Set your preferred AI agent for implementation
auto config set ai.implementation_agent coder

# Set AI agent for reviews
auto config set ai.review_agent pull-request-reviewer
```

## Quick Start

1. **Initialize in your project:**
   ```bash
   cd your-project
   auto init
   ```

2. **List available issues:**
   ```bash
   auto issues
   # or
   auto ls
   ```

3. **Run the complete workflow:**
   ```bash
   auto <issue-id>
   ```

That's it! The tool will handle the entire workflow automatically.

## Usage

### Primary Command

```bash
auto <id>                    # Complete workflow with review cycles
```

**Supported issue ID formats:**
- GitHub: `#123`, `gh-123`, or full GitHub issue URL
- Linear: `ENG-123` or full Linear issue URL

### Issue Management

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

### Workflow Control

```bash
auto fetch <id>              # Just fetch issue details
auto process <id>            # Fetch + AI implementation
auto review <pr-id>          # Trigger AI review on existing PR
auto update <pr-id>          # Update PR based on review comments
auto merge <pr-id>           # Complete merge after approval
auto cleanup                 # Remove completed worktrees
auto status                  # Show active worktrees/PRs with review status
```

### Configuration

```bash
auto config <get|set> <key>  # Configuration management
auto config get ai.implementation_agent
auto config set github.default_reviewer username
```

## Configuration

The tool uses a nested configuration system with three levels:

1. `~/.auto/config.yaml` - User-wide settings
2. `<project>/.auto/config.yaml` - Project-specific overrides
3. Environment variables - Runtime overrides

### Example Configuration

```yaml
# ~/.auto/config.yaml
version: 1.0
defaults:
  auto_merge: false
  delete_branch_on_merge: true
  worktree_base: "../{project}-worktrees"
  max_review_iterations: 10

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
  implementation_agent: "coder"
  review_agent: "pull-request-reviewer"
  update_agent: "coder"
  implementation_prompt: "Implement the following issue: {description}"
  review_prompt: "Review this PR critically for bugs, security issues, performance, and best practices."
  update_prompt: "Address the following review comments: {comments}"

workflows:
  branch_naming: "auto/{issue_type}/{issue_id}"
  commit_convention: "conventional"
  ai_review_first: true
  require_human_approval: true
  test_command: null  # e.g., "npm test", "pytest"
  review_check_interval: 60  # seconds between checking for new reviews
```

### Key Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| `ai.implementation_agent` | AI agent for initial implementation | `coder` |
| `ai.review_agent` | AI agent for PR reviews | `pull-request-reviewer` |
| `ai.update_agent` | AI agent for addressing review comments | `coder` |
| `workflows.test_command` | Command to run tests | `null` |
| `workflows.ai_review_first` | AI reviews before human | `true` |
| `workflows.require_human_approval` | Require human approval to merge | `true` |
| `defaults.max_review_iterations` | Safety limit for review cycles | `10` |

## Review Cycle

The tool implements an intelligent iterative review process:

1. **AI Review**: Automatically analyzes the PR and posts detailed comments
2. **Human Review**: Waits for human reviewer feedback and approval
3. **AI Updates**: Uses AI to address both AI and human review comments
4. **Repeat**: Continues until PR is approved or max iterations reached

### Review States

- `draft` - Initial implementation complete
- `ai_reviewing` - AI is analyzing the PR
- `awaiting_human_review` - Waiting for human reviewer
- `addressing_comments` - AI is updating code based on feedback
- `approved` - Ready to merge
- `merged` - Workflow complete

## Project Structure

```
auto/
├── pyproject.toml           # Project dependencies & metadata
├── README.md                # This file
├── CLAUDE.md                # Project instructions for AI
├── auto/
│   ├── __init__.py
│   ├── __main__.py         # Entry point for `python -m auto`
│   ├── cli.py              # Click CLI interface
│   ├── config.py           # Configuration management
│   ├── core.py             # Main workflow orchestrator
│   ├── models.py           # Data models (Issue, PR, etc.)
│   ├── integrations/
│   │   ├── github.py       # GitHub integration via gh CLI
│   │   ├── linear.py       # Linear integration
│   │   ├── git.py          # Git worktree management
│   │   └── ai.py           # Claude AI integration
│   ├── workflows/
│   │   ├── full.py         # Complete auto workflow
│   │   ├── fetch.py        # Issue fetching
│   │   ├── process.py      # AI processing
│   │   ├── review.py       # Review cycle workflow
│   │   ├── update.py       # PR update workflow
│   │   └── cleanup.py      # Worktree cleanup
│   └── utils/
│       ├── logger.py       # Logging utilities
│       └── shell.py        # Shell command execution
├── tests/
└── scripts/
    ├── install.sh          # Installation helper
    └── auto.plugin.zsh     # Zsh completions (planned)
```

## State Management

The tool maintains state for each PR in `.auto/state/` to handle:

- Resume interrupted workflows
- Track review iterations
- Monitor PR status
- Manage worktrees

State files enable you to safely interrupt and resume workflows at any point.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Troubleshooting

### Common Issues

**"No issues found"**
- Ensure you're in a Git repository
- Check that GitHub CLI is authenticated: `gh auth status`
- Verify the repository has issues

**"AI agent not found"**
- Ensure Claude CLI is installed and configured
- Check that the specified agent exists: `claude --help`

**"Worktree creation failed"**
- Ensure Git 2.15+ is installed
- Check that the worktree base directory is writable
- Verify no conflicting branches exist

**Review cycle stuck**
- Check PR status: `auto status`
- Manually trigger review: `auto review <pr-id>`
- Clear state and restart: `rm .auto/state/<pr-id>.yaml`

### Debug Mode

```bash
export AUTO_DEBUG=1
auto <command>  # Will show detailed logging
```

For more help, check the [issues page](https://github.com/trobanga/auto/issues) or create a new issue.