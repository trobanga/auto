# Auto Tool - Phase 2 Implementation Plan
## GitHub Integration & Git Worktree Management

## Overview

Phase 2 implements GitHub integration and git worktree management, building on Phase 1's foundation to make `auto fetch <id>` and `auto process <id>` fully functional for GitHub issues. This phase focuses on real issue fetching via `gh` CLI and automated worktree creation with proper branch naming, without AI processing capabilities.

## Files to Change

### New Files to Create

**Integration Modules:**
- `/home/trobanga/code/auto/auto/integrations/github.py` - GitHub API integration via `gh` CLI with issue fetching and repository detection
- `/home/trobanga/code/auto/auto/integrations/git.py` - Git worktree management with branch creation and cleanup

**Workflow Modules:**  
- `/home/trobanga/code/auto/auto/workflows/fetch.py` - Issue fetching workflow implementation
- `/home/trobanga/code/auto/auto/workflows/process.py` - Process workflow with worktree setup and branch creation

**Test Files:**
- `/home/trobanga/code/auto/tests/test_github.py` - GitHub integration comprehensive testing
- `/home/trobanga/code/auto/tests/test_git.py` - Git worktree management testing
- `/home/trobanga/code/auto/tests/test_workflows.py` - End-to-end workflow testing

### Files to Modify

**Core System:**
- `/home/trobanga/code/auto/auto/models.py` - Add GitHubRepository and WorktreeInfo models
- `/home/trobanga/code/auto/auto/cli.py` - Replace fetch/process command stubs with real implementations  
- `/home/trobanga/code/auto/auto/core.py` - Add GitHub/git integration coordination and enhanced state management
- `/home/trobanga/code/auto/auto/workflows/__init__.py` - Export new workflow functions

## Functions

### GitHubIntegration (github.py)
GitHub integration class providing issue fetching and repository management via `gh` CLI with robust error handling and authentication validation.

### GitHubRepository (github.py)  
Repository context model containing owner, name, default branch, and remote URL information for GitHub operations.

### GitWorktreeManager (git.py)
Git worktree lifecycle management including creation with branch naming patterns, cleanup operations, and conflict resolution.

### WorktreeInfo (models.py)
Data model for tracking worktree path, branch name, issue association, and creation timestamp for state management.

### fetch_issue_workflow (fetch.py)
Complete issue fetching workflow that validates issue ID, fetches from GitHub, updates workflow state, and handles errors.

### process_issue_workflow (process.py)
Process workflow combining issue fetching with worktree creation, branch setup, and state tracking for development preparation.

### create_worktree (git.py)
Worktree creation function generating branch names from issue types, creating isolated development environments, and updating workflow state.

### cleanup_worktree (git.py)
Worktree cleanup function removing worktree directories, deleting branches, and updating state tracking.

### detect_repository (github.py)
Repository detection function parsing git remote origin to extract GitHub owner/repo information for context.

### validate_github_auth (github.py)
Authentication validation function checking `gh` CLI authentication status and providing setup guidance.

## Tests

### test_github_issue_fetching_valid_id
Verify GitHub issue fetching with valid issue ID

### test_github_issue_fetching_invalid_id  
Verify error handling for invalid GitHub issue IDs

### test_github_repository_detection_from_remote
Verify repository detection from git remote origin URL

### test_github_authentication_validation_success
Verify successful GitHub authentication detection via gh CLI

### test_github_authentication_validation_failure
Verify proper error handling for missing GitHub authentication

### test_git_worktree_creation_with_branch_naming
Verify worktree creation follows branch naming conventions

### test_git_worktree_creation_handles_conflicts
Verify worktree creation handles existing branch conflicts gracefully

### test_git_worktree_cleanup_removes_directory_and_branch
Verify worktree cleanup removes both directory and git branch

### test_git_worktree_base_directory_configuration
Verify worktree base directory respects configuration settings

### test_fetch_workflow_updates_state_correctly
Verify fetch workflow properly updates WorkflowState throughout process

### test_process_workflow_creates_worktree_and_updates_state
Verify process workflow combines fetching with worktree creation

### test_cli_fetch_command_with_github_issue
Verify CLI fetch command works end-to-end with GitHub issues

### test_cli_process_command_creates_working_environment
Verify CLI process command creates complete development environment

## Implementation Order and Dependencies

### Phase 2.1: Models and Foundation (1-2 days)
1. **Extend models.py** - Add GitHubRepository and WorktreeInfo models
2. **Create integration base** - Set up `/home/trobanga/code/auto/auto/integrations/github.py` skeleton
3. **Create git integration base** - Set up `/home/trobanga/code/auto/auto/integrations/git.py` skeleton

### Phase 2.2: GitHub Integration (2-3 days)  
1. **Implement GitHubRepository** - Repository detection and metadata
2. **Implement GitHubIntegration** - Issue fetching via `gh` CLI
3. **Add authentication validation** - Check `gh auth` status
4. **Create comprehensive tests** - Cover success and error cases

### Phase 2.3: Git Worktree Management (2-3 days)
1. **Implement WorktreeInfo model** - Worktree metadata tracking
2. **Implement GitWorktreeManager** - Creation, cleanup, conflict handling
3. **Add branch naming logic** - Follow configuration patterns
4. **Create worktree tests** - Cover lifecycle and edge cases

### Phase 2.4: Workflow Implementation (2-3 days)
1. **Create fetch.py workflow** - Issue fetching with state management
2. **Create process.py workflow** - Combined fetch + worktree creation
3. **Update workflows/__init__.py** - Export new functions
4. **Add workflow tests** - End-to-end functionality verification

### Phase 2.5: CLI Integration (1-2 days)
1. **Replace fetch command stub** - Real GitHub issue fetching  
2. **Replace process command stub** - Real worktree creation workflow
3. **Update core.py integration** - Coordinate GitHub/git operations
4. **Add CLI integration tests** - Command-line interface validation

### Phase 2.6: Testing and Polish (1-2 days)
1. **Create comprehensive test suite** - All integration scenarios
2. **Add error handling improvements** - Network, auth, filesystem errors
3. **Update configuration examples** - GitHub-specific settings
4. **Documentation updates** - Usage examples and troubleshooting

## Configuration Schema Updates

### Enhanced GitHubConfig
```yaml
github:
  default_org: null                    # Default GitHub organization  
  default_reviewer: null               # Default PR reviewer
  pr_template: .github/pull_request_template.md  # PR template path
  token: null                         # GitHub token (optional with gh CLI)
  base_branch_detection: true         # Auto-detect main/master branch
  issue_fetch_timeout: 30             # Timeout for issue fetching (seconds)
```

### Enhanced WorkflowsConfig  
```yaml
workflows:
  branch_naming: "auto/{issue_type}/{issue_id}"  # Branch naming pattern
  commit_convention: "conventional"               # Commit message convention
  worktree_cleanup_on_merge: true                # Auto-cleanup merged worktrees
  worktree_conflict_resolution: "prompt"         # prompt|force|skip
```

## CLI Command Enhancements

### Enhanced fetch Command
```bash
# Fetch GitHub issue by number
auto fetch 123

# Fetch GitHub issue by URL  
auto fetch https://github.com/owner/repo/issues/123

# Fetch with verbose output
auto fetch 123 --verbose

# Example output:
# ✓ Fetched GitHub issue #123: "Add dark mode support"
# ✓ Issue type: feature (inferred from labels)
# ✓ Assignee: john_doe
# ✓ Status: open
# ✓ Workflow state created: .auto/state/123.yaml
```

### Enhanced process Command
```bash
# Process GitHub issue with worktree creation
auto process 123

# Process with custom worktree base
auto process 123 --worktree-base /custom/path

# Example output:
# ✓ Fetched GitHub issue #123: "Add dark mode support" 
# ✓ Created worktree: ../myproject-worktrees/auto-feature-123
# ✓ Created branch: auto/feature/123 (from main)
# ✓ Switched to worktree directory
# ✓ Ready for development: /path/to/worktree
```

### Enhanced status Command
```bash
# Show worktree status in addition to workflow status
auto status

# Example output:
# Active Workflows
# ┌──────────┬─────────────┬─────────┬──────────────────┬─────────────────┐
# │ Issue ID │ Status      │ PR      │ Branch           │ Worktree        │
# ├──────────┼─────────────┼─────────┼──────────────────┼─────────────────┤
# │ #123     │ implementing│ N/A     │ auto/feature/123 │ ../wt/auto-feat │
# │ #456     │ in_review   │ #789    │ auto/bug/456     │ ../wt/auto-bug  │
# └──────────┴─────────────┴─────────┴──────────────────┴─────────────────┘
```

### Enhanced cleanup Command
```bash
# Clean up completed worktrees
auto cleanup

# Force cleanup including active worktrees  
auto cleanup --force

# Example output:
# ✓ Cleaned up completed worktree: auto-feature-123
# ✓ Removed branch: auto/feature/123
# ✓ Cleaned up 1 workflow state(s)
```

## Integration Patterns with Phase 1

### Building on Existing Foundation
- **Leverage IssueIdentifier parsing** - Use existing GitHub ID detection logic
- **Extend WorkflowState model** - Add worktree tracking fields
- **Use ConfigManager hierarchy** - GitHub settings from user/project config
- **Utilize shell utilities** - Build on existing git operations
- **Integrate with state management** - Use existing `.auto/state/` directory

### Maintaining Compatibility
- **Preserve existing CLI interface** - Enhance rather than replace commands
- **Keep configuration backwards compatible** - Add new fields as optional
- **Maintain logging consistency** - Use existing logger infrastructure  
- **Follow established patterns** - Error handling, async support, typing

## Error Handling & Edge Cases

### GitHub Integration Errors
- **Network connectivity issues** - Timeout handling, retry logic, offline graceful degradation
- **Authentication failures** - Clear guidance to run `gh auth login`
- **Repository not found** - Validate repository existence before operations
- **Invalid issue IDs** - Clear error messages for malformed identifiers
- **API rate limiting** - Respect GitHub API limits, provide helpful messages

### Git Worktree Errors
- **Repository not found** - Ensure current directory is in a git repository
- **Insufficient permissions** - Handle filesystem permission errors gracefully
- **Disk space issues** - Check available space before worktree creation
- **Branch conflicts** - Handle existing branches with same name
- **Worktree conflicts** - Handle existing worktrees at same path
- **Invalid branch names** - Sanitize issue IDs for valid git branch names

### State Management Errors  
- **State file corruption** - Validate and recover from invalid YAML
- **Concurrent access** - Handle multiple auto processes safely
- **Orphaned worktrees** - Detect and clean up abandoned worktrees
- **Missing worktrees** - Handle state pointing to non-existent worktrees

### Configuration Errors
- **Missing configuration** - Provide defaults and initialization guidance
- **Invalid paths** - Validate worktree base directory accessibility
- **Environment variables** - Clear errors for missing required variables

## Success Criteria for Phase 2

### Functional Requirements Met
- ✅ `auto fetch <id>` successfully fetches GitHub issues and creates workflow state
- ✅ `auto process <id>` fetches issues and creates working worktree environment  
- ✅ `auto status` shows active worktrees and their locations
- ✅ `auto cleanup` removes completed worktrees and branches
- ✅ Proper error handling for network, auth, and filesystem issues

### Technical Requirements Met
- ✅ GitHub integration via `gh` CLI with comprehensive error handling
- ✅ Git worktree management with configurable branch naming patterns
- ✅ Enhanced workflow state tracking including worktree information
- ✅ Backwards compatible configuration and CLI interface
- ✅ Comprehensive test coverage for all new functionality

### Readiness for Phase 3
- ✅ Working development environments created by `auto process`
- ✅ Issue data properly fetched and stored for AI processing
- ✅ Worktree state tracking enables AI implementation workflow
- ✅ Error handling foundation supports complex AI integration scenarios

This Phase 2 implementation provides the essential GitHub and git foundation needed for Phase 3's AI processing capabilities, while maintaining the robust architecture and user experience established in Phase 1.