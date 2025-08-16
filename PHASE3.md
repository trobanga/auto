# Auto Tool - Phase 3 Implementation Plan
## AI Implementation and Initial PR Creation

## Overview

Phase 3 implements AI integration for implementing solutions from issues and creating initial pull requests. This builds on the completed Phase 1 (core structure, config system, basic CLI) and Phase 2 (GitHub integration, worktree management) to add intelligent code implementation capabilities using the Claude CLI and agent system, culminating in automated PR creation.

## Files to Change

### New Files to Create

**AI Integration Module:**
- `/home/trobanga/code/auto/auto/integrations/ai.py` - Claude CLI integration with agent selection, prompt formatting, and response parsing
- `/home/trobanga/code/auto/auto/integrations/prompts.py` - Prompt management system with custom prompts and template support

**Enhanced Workflow Modules:**
- `/home/trobanga/code/auto/auto/workflows/implement.py` - AI implementation workflow using Claude agents within worktrees
- `/home/trobanga/code/auto/auto/workflows/pr_create.py` - Pull request creation workflow with template support and metadata

**Prompt Templates:**
- `/home/trobanga/code/auto/auto/templates/prompts/` - Default prompt templates directory
- `/home/trobanga/code/auto/auto/templates/prompts/implementation.yaml` - Standard implementation template
- `/home/trobanga/code/auto/auto/templates/prompts/security-focused.yaml` - Security-focused implementation template
- `/home/trobanga/code/auto/auto/templates/prompts/performance.yaml` - Performance optimization template

**Test Files:**
- `/home/trobanga/code/auto/tests/test_ai.py` - AI integration comprehensive testing with mock Claude responses
- `/home/trobanga/code/auto/tests/test_implement.py` - AI implementation workflow testing
- `/home/trobanga/code/auto/tests/test_pr_create.py` - PR creation workflow testing
- `/home/trobanga/code/auto/tests/test_prompts.py` - Prompt management and template system testing

### Files to Modify

**Core Workflow Enhancement:**
- `/home/trobanga/code/auto/auto/workflows/process.py` - Extend process workflow to include AI implementation after worktree creation
- `/home/trobanga/code/auto/auto/workflows/__init__.py` - Export new AI implementation and PR creation functions
- `/home/trobanga/code/auto/auto/cli.py` - Add `implement` command with custom prompt options and update `process` to include AI implementation
- `/home/trobanga/code/auto/auto/models.py` - Add AI response models, PR metadata structures, and enhanced AIConfig with prompt support
- `/home/trobanga/code/auto/auto/config.py` - Add prompt template discovery and custom prompt configuration support

**Core Integration:**
- `/home/trobanga/code/auto/auto/core.py` - Add AI integration coordination and PR state management

## Functions

### ClaudeIntegration (ai.py)
AI integration class providing Claude CLI command execution with agent selection, prompt formatting, and robust error handling for implementation, review, and update tasks.

### execute_ai_command (ai.py)
Command execution function that invokes Claude CLI with specific agents, handles process management, captures output, and provides detailed error reporting.

### format_implementation_prompt (ai.py)
Prompt formatting function that combines issue description, acceptance criteria, repository context, and configuration into Claude-optimized implementation prompts.

### parse_ai_response (ai.py)
Response parsing function that extracts actionable items, file changes, commands to run, and metadata from Claude AI responses for workflow automation.

### PromptManager (prompts.py)
Prompt management class providing custom prompt resolution, template loading, variable expansion, and prompt validation for AI command customization.

### resolve_prompt (prompts.py)
Prompt resolution function that handles CLI overrides, template loading, variable substitution, and prompt validation with fallback to default prompts.

### load_prompt_template (prompts.py)
Template loading function that discovers and loads named prompt templates from user and project directories with YAML parsing and validation.

### expand_prompt_variables (prompts.py)
Variable expansion function that substitutes issue context, repository information, and custom variables into prompt templates.

### implement_issue_workflow (implement.py)
Complete AI implementation workflow that changes to worktree directory, invokes Claude with implementation agent, applies changes, and updates workflow state.

### create_pull_request_workflow (pr_create.py)
PR creation workflow that validates implementation, commits changes, pushes branch, creates GitHub PR with templates, and updates workflow state.

### validate_ai_prerequisites (ai.py)
Prerequisites validation function checking Claude CLI availability, agent configuration, and workspace readiness for AI operations.

### apply_ai_changes (implement.py)
Change application function that interprets AI responses, applies file modifications, executes suggested commands, and handles conflicts.

### generate_pr_description (pr_create.py)
PR description generation function combining issue context, implementation summary, and template formatting for comprehensive pull request documentation.

### enhanced_process_issue_workflow (process.py)
Enhanced process workflow combining existing worktree creation with AI implementation and PR creation for complete issue-to-PR automation.

## Tests

### test_claude_cli_integration_with_valid_agent
Verify Claude CLI integration with configured implementation agent

### test_claude_cli_integration_with_invalid_agent
Verify error handling for missing or invalid Claude agents

### test_ai_prompt_formatting_includes_issue_context
Verify prompt formatting includes issue description and repository context

### test_ai_response_parsing_extracts_file_changes
Verify AI response parsing correctly identifies file modifications

### test_ai_response_parsing_handles_malformed_output
Verify robust error handling for unexpected AI response formats

### test_prompt_manager_resolves_custom_prompts
Verify PromptManager correctly handles CLI prompt overrides

### test_prompt_manager_loads_templates
Verify template loading from user and project directories

### test_prompt_variable_expansion
Verify issue context variables are properly substituted in templates

### test_prompt_manager_handles_missing_templates
Verify graceful fallback when named templates are not found

### test_implement_workflow_applies_changes_in_worktree
Verify AI implementation workflow executes within correct worktree

### test_implement_workflow_updates_state_on_success
Verify implementation workflow properly updates WorkflowState

### test_implement_workflow_handles_ai_command_failure
Verify error handling when Claude CLI command fails

### test_pr_creation_workflow_commits_and_pushes_changes
Verify PR creation workflow properly commits and pushes implementation

### test_pr_creation_workflow_uses_pr_template
Verify PR creation uses configured GitHub PR template

### test_pr_creation_workflow_updates_state_with_pr_number
Verify PR creation updates workflow state with GitHub PR metadata

### test_enhanced_process_workflow_end_to_end
Verify complete process workflow from issue fetch to PR creation

### test_cli_implement_command_with_valid_issue
Verify CLI implement command works with existing workflow state

### test_cli_process_command_includes_ai_implementation
Verify updated CLI process command includes AI implementation step

## Implementation Order and Dependencies

### Phase 3.1: AI Integration Foundation (2-3 days)
1. **Create ai.py integration module** - Claude CLI wrapper with agent selection
2. **Create prompts.py management module** - Custom prompt and template system
3. **Add ClaudeIntegration class** - Command execution and error handling
4. **Add PromptManager class** - Custom prompt resolution and template loading
5. **Implement prompt formatting** - Issue context to Claude prompts with custom support
6. **Add response parsing logic** - Extract actionable items from AI responses
7. **Create comprehensive AI and prompt tests** - Mock Claude CLI interactions and template testing

### Phase 3.2: AI Implementation Workflow (2-3 days)
1. **Create implement.py workflow** - AI-driven code implementation
2. **Implement issue processing** - Worktree-based AI implementation
3. **Add change application logic** - Apply AI-suggested modifications
4. **Update workflow state tracking** - Track AI implementation progress
5. **Create implementation tests** - End-to-end AI workflow validation

### Phase 3.3: PR Creation Workflow (2-3 days)
1. **Create pr_create.py workflow** - GitHub PR creation automation
2. **Implement PR description generation** - Template-based PR documentation
3. **Add commit and push logic** - Git operations for PR preparation
4. **Integrate with GitHub API** - PR creation via gh CLI
5. **Create PR workflow tests** - Validate PR creation process

### Phase 3.4: Enhanced Process Workflow (1-2 days)
1. **Extend process.py workflow** - Include AI implementation step
2. **Add process flow coordination** - Fetch → Worktree → AI → PR
3. **Update error handling** - Handle AI and PR creation failures
4. **Add configuration validation** - Ensure AI agents are configured
5. **Update existing process tests** - Include AI implementation validation

### Phase 3.5: CLI Integration (1-2 days)
1. **Add implement command with prompt options** - Standalone AI implementation with custom prompt support
2. **Update process command with prompt options** - Include AI implementation and custom prompts in process workflow
3. **Add prompt CLI options** - --prompt, --prompt-file, --prompt-template, --prompt-append, --show-prompt
4. **Enhance status command** - Show AI implementation and PR status
5. **Update core.py coordination** - Integrate AI workflows with state management
6. **Add CLI integration tests** - Command-line interface validation including prompt options

### Phase 3.6: Testing and Polish (1-2 days)
1. **Create comprehensive test suite** - All AI integration scenarios including custom prompts
2. **Create default prompt templates** - Standard templates for common use cases
3. **Add error handling improvements** - Claude CLI failures, network issues, template errors
4. **Update configuration examples** - AI agent and prompt template configuration guidance
5. **Documentation updates** - Usage examples, custom prompt guide, and troubleshooting

## Integration Points with Existing Code

### Building on Phase 2 Foundation
- **Leverage WorktreeInfo** - Execute AI commands within created worktrees
- **Extend WorkflowState** - Track AI implementation progress and PR details
- **Use GitHubIntegration** - Create PRs using existing GitHub API integration
- **Build on branch management** - Commit changes to worktree branches

### Configuration Integration
- **Use existing AIConfig** - Leverage ai.implementation_agent and ai.implementation_prompt
- **Extend error handling** - Build on existing GitHub and git error patterns
- **Maintain state consistency** - Use established .auto/state/ directory patterns
- **Follow logging standards** - Use existing logger infrastructure

### Workflow Coordination
- **Enhance process_issue_workflow** - Add AI implementation as middle step
- **Coordinate with fetch workflow** - Use fetched issue data for AI prompts
- **Integrate with cleanup** - Handle AI artifacts in cleanup operations
- **Maintain status reporting** - Show AI progress in status command

## AI Integration Architecture

### Claude CLI Integration Pattern
```python
class ClaudeIntegration:
    def __init__(self, config: AIConfig):
        self.command = config.command  # "claude"
        self.implementation_agent = config.implementation_agent  # "coder"
        self.implementation_prompt = config.implementation_prompt
    
    def execute_implementation(self, issue: Issue, worktree_path: str) -> AIResponse:
        # Format prompt with issue context
        # Execute claude command with agent
        # Parse response for actionable items
        # Return structured response
```

### Prompt Engineering Strategy
- **Include issue context** - Title, description, acceptance criteria, labels
- **Add repository context** - File structure, existing patterns, conventions
- **Specify output format** - Request structured responses for parsing
- **Include constraints** - File patterns, coding standards, test requirements

### Response Parsing Strategy
- **Structured output** - Parse Claude responses for file changes and commands
- **Error handling** - Handle malformed or incomplete AI responses gracefully
- **Validation** - Verify suggested changes are safe and applicable
- **Feedback loop** - Track success/failure for prompt optimization

## CLI Command Enhancements

### New implement Command
```bash
# Run AI implementation for existing issue
auto implement 123

# Implement with custom prompt
auto implement 123 --prompt "Implement this focusing on performance and testing"

# Implement with prompt from file
auto implement 123 --prompt-file ./custom-prompt.txt

# Implement with named template
auto implement 123 --prompt-template security-focused

# Append to default prompt
auto implement 123 --prompt-append "Ensure comprehensive error handling"

# Preview prompt before execution
auto implement 123 --show-prompt

# Implement with custom agent
auto implement 123 --agent custom-coder

# Example output:
# ✓ Found issue #123 in worktree: ../myproject-worktrees/auto-feature-123
# ✓ Using prompt template: security-focused
# ✓ Running AI implementation with agent: coder
# ✓ AI implementation completed: 3 files modified
#   - src/components/DarkModeToggle.tsx (created)
#   - src/hooks/useDarkMode.ts (created)  
#   - src/App.tsx (modified)
# ✓ Changes applied successfully
# ✓ Workflow state updated
```

### Enhanced process Command
```bash
# Process with AI implementation (new default behavior)
auto process 123

# Process with custom prompt options
auto process 123 --prompt-template performance --prompt-append "Focus on mobile optimization"

# Process without AI implementation  
auto process 123 --no-ai

# Preview what prompt would be used
auto process 123 --show-prompt

# Example output:
# ✓ Fetched GitHub issue #123: "Add dark mode support"
# ✓ Created worktree: ../myproject-worktrees/auto-feature-123
# ✓ Created branch: auto/feature/123
# ✓ Using prompt template: performance with custom additions
# ✓ Running AI implementation with agent: coder
# ✓ AI implementation completed: 3 files modified
# ✓ Creating pull request...
# ✓ Pull request created: #456
# ✓ Ready for review: https://github.com/owner/repo/pull/456
```

### Enhanced status Command
```bash
# Show AI implementation and PR status
auto status

# Example output:
# Active Workflows
# ┌──────────┬──────────────┬─────────┬──────────────────┬────────────────┐
# │ Issue ID │ Status       │ PR      │ Branch           │ AI Status      │
# ├──────────┼──────────────┼─────────┼──────────────────┼────────────────┤
# │ #123     │ creating_pr  │ #456    │ auto/feature/123 │ implemented    │
# │ #789     │ implementing │ N/A     │ auto/bug/789     │ in_progress    │
# └──────────┴──────────────┴─────────┴──────────────────┴────────────────┘
```

## Configuration Schema Updates

### Enhanced AIConfig
```yaml
ai:
  command: "claude"                    # AI command executable
  implementation_agent: "coder"        # Agent for implementation
  review_agent: "pull-request-reviewer" # Agent for PR reviews (Phase 4)
  update_agent: "coder"               # Agent for addressing comments (Phase 4)
  implementation_prompt: "Implement the following issue: {description}"
  review_prompt: "Review this PR critically for bugs, security issues, performance, and best practices."
  update_prompt: "Address the following review comments: {comments}"
  timeout: 300                        # AI command timeout (seconds)
  max_retries: 2                      # Maximum retries for failed commands
  include_file_context: true          # Include relevant file content in prompts
  response_format: "structured"       # structured|freeform
  
  # Custom prompt support
  prompt_templates_dir: "~/.auto/prompts"  # User prompt templates directory
  allow_custom_prompts: true          # Enable custom prompt CLI options
  default_template: "implementation"  # Default template name
  prompt_variables:                   # Available template variables
    - issue_id
    - issue_title  
    - issue_description
    - acceptance_criteria
    - repository
    - branch
    - labels
    - assignee
```

### Enhanced WorkflowsConfig  
```yaml
workflows:
  branch_naming: "auto/{issue_type}/{issue_id}"
  commit_convention: "conventional"
  ai_review_first: true               # AI reviews before human (Phase 4)
  require_human_approval: true        # Require human approval (Phase 4)
  test_command: "npm test"            # Run tests after implementation
  auto_create_pr: true                # Auto-create PR after implementation
  pr_draft_mode: false                # Create draft PRs by default
  implementation_commit_message: "feat: implement {issue_id} - {issue_title}"
```

## Error Handling & Edge Cases

### AI Integration Errors
- **Claude CLI not available** - Clear installation and setup guidance
- **Invalid agent configuration** - Validate agent names and provide examples
- **AI command timeout** - Handle long-running AI operations gracefully
- **Malformed AI responses** - Parse partial responses, request clarification
- **Network connectivity** - Handle offline scenarios and API failures

### Custom Prompt Errors
- **Template not found** - Graceful fallback to default prompts with clear error messages
- **Invalid template format** - YAML parsing errors with helpful validation feedback
- **Missing template variables** - Handle undefined variables with defaults or warnings
- **Prompt file not accessible** - File permission and existence error handling
- **Prompt too long** - Handle prompts exceeding AI command limits

### Implementation Workflow Errors
- **File modification conflicts** - Handle cases where AI suggests conflicting changes
- **Permission issues** - Ensure worktree has proper file system permissions
- **Test failures** - Handle cases where AI implementation breaks existing tests
- **Invalid code generation** - Validate AI-generated code before application
- **Workspace contamination** - Prevent AI changes from affecting main branch

### PR Creation Errors
- **GitHub API failures** - Handle rate limits, authentication, and network issues
- **Branch push failures** - Handle cases where branch cannot be pushed
- **PR template not found** - Graceful fallback when template is missing
- **Duplicate PR creation** - Prevent creating multiple PRs for same issue
- **Empty commits** - Handle cases where AI doesn't generate any changes

## Success Criteria for Phase 3

### Functional Requirements Met
- ✅ `auto implement <id>` successfully runs AI implementation for existing issues
- ✅ `auto process <id>` completes full workflow from issue to PR creation
- ✅ AI integration uses configured Claude agents appropriately
- ✅ Custom prompt support via CLI options (--prompt, --prompt-file, --prompt-template, --prompt-append, --show-prompt)
- ✅ Prompt template system with named templates and variable substitution
- ✅ PR creation includes proper templates and issue context
- ✅ Robust error handling for AI failures, prompt errors, and edge cases

### Technical Requirements Met  
- ✅ Claude CLI integration with agent selection and prompt formatting
- ✅ Custom prompt management system with template loading and variable expansion
- ✅ AI response parsing and automated change application
- ✅ Enhanced workflow state tracking for AI implementation progress
- ✅ GitHub PR creation with metadata and template support
- ✅ Comprehensive test coverage for all AI integration and prompt management scenarios

### Readiness for Phase 4
- ✅ PRs created with proper context for AI review workflows
- ✅ Workflow state tracking supports review cycle management
- ✅ AI integration foundation enables review and update agents
- ✅ Custom prompt system ready for review-specific templates
- ✅ Error handling patterns support complex review scenarios

This Phase 3 implementation provides the intelligent automation capabilities needed to transform issues into implemented solutions and pull requests, with comprehensive custom prompt support for tailored AI behavior. It sets the foundation for Phase 4's review cycle implementation while maintaining the robust architecture established in Phases 1 and 2.