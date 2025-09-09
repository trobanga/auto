# Auto Tool Codebase Knowledge

## AI Integration Architecture

### Core AI Integration System

The auto tool implements a sophisticated AI integration system centered around the `ClaudeIntegration` class in `auto/integrations/ai.py`. This system provides structured, type-safe AI interactions with comprehensive error handling, activity monitoring, and streaming support.

#### Key Components

1. **ClaudeIntegration Class** (`auto/integrations/ai.py`)
   - Primary interface for all AI operations
   - Supports multiple AI agents (implementation, review, update)
   - Includes activity monitoring with Rich console output
   - Handles streaming JSON responses
   - Provides comprehensive error handling and recovery

2. **AI Configuration** (`auto/models.py:AIConfig`)
   - Flexible command format support (Claude, OpenAI, Ollama, custom)
   - Configurable agents for different tasks
   - Streaming and activity monitoring controls
   - Timeout and retry configurations
   - Custom prompt template support

3. **Structured Response Parsing**
   - `AIResponse` model for consistent response handling
   - Automatic extraction from streaming JSON output
   - File change and command extraction
   - Metadata and error information preservation

### AI Integration Patterns

#### Standard Implementation Pattern
```python
# Initialize AI integration with config
ai_integration = ClaudeIntegration(config.ai)

# Execute AI task with specific agent
result = await ai_integration.execute_implementation(
    issue=issue,
    worktree_path=worktree_path,
    custom_prompt=custom_prompt  # Optional override
)

# Handle response
if result.success:
    # Process file changes, commands, etc.
    for change in result.file_changes:
        # Handle file modifications
    
    for command in result.commands:
        # Execute suggested commands
```

#### Agent Selection Strategy
- **Implementation Agent** (`coder`): Initial code implementation
- **Review Agent** (`pull-request-reviewer`): Code review and analysis
- **Update Agent** (`coder`): Addressing review comments and updates
- **Specialized Agents**: Domain-specific tasks (git-commit-expert, etc.)

#### Error Handling Pattern
```python
try:
    ai_response = await ai_integration.execute_task(...)
    if not ai_response.success:
        # Handle AI task failure
        fallback_action()
except AIIntegrationError as e:
    # Handle integration-level errors
    logger.error(f"AI integration failed: {e}")
    # Implement fallback behavior
```

## Merge Conflict Handling System

### Architecture Overview

The merge conflict handling system implements comprehensive AI-assisted conflict resolution with Rich console visualization and structured guidance generation.

#### Core Components

1. **Conflict Detection and Analysis** (`auto/workflows/merge_conflicts.py`)
   - Git output parsing for conflict identification
   - File-level conflict analysis with markers detection
   - Complexity assessment and classification
   - Rich console visualization

2. **AI-Assisted Resolution** 
   - Integration with `ClaudeIntegration.analyze_merge_conflicts()`
   - Structured conflict analysis prompts
   - Resolution strategy generation
   - Confidence scoring and validation steps

3. **Data Models** (`auto/models.py`)
   - `ConflictType`: Content, rename, delete, modify-delete, add-add, mode
   - `ConflictComplexity`: Simple, moderate, complex, critical
   - `ConflictDetail`: Individual conflict information
   - `ResolutionSuggestion`: AI-generated resolution guidance
   - `ConflictResolution`: Complete analysis and recommendations

### Implementation Details

#### Main Conflict Handler
```python
async def _handle_merge_conflicts(
    pr_number: int, 
    repository: GitHubRepository, 
    conflict_details: str
) -> ConflictResolution
```

**Workflow:**
1. Parse Git conflict output into structured data
2. Analyze each conflicted file for markers and complexity
3. Gather PR context for AI analysis
4. Generate AI-assisted resolution suggestions
5. Calculate complexity scores and time estimates
6. Create comprehensive resolution report
7. Display Rich console visualization

#### AI Integration for Conflict Analysis

**New Method in ClaudeIntegration:**
```python
async def analyze_merge_conflicts(
    self,
    conflict_details: str,
    pr_context: dict[str, Any],
    repository: str,
    custom_prompt: str | None = None,
    worktree_path: str | None = None,
) -> AIResponse
```

**Comprehensive Analysis Prompt Structure:**
- Context information (PR details, files changed)
- Conflict classification requirements
- Complexity assessment criteria
- Resolution strategy expectations
- Output format specifications

#### Rich Console Visualization

The system provides comprehensive visual feedback:
- **Summary Panel**: Conflict count, estimated time, complexity score
- **Conflicts Table**: File-by-file breakdown with types and complexity
- **Resolution Steps**: Structured manual guidance
- **Progress Indicators**: Real-time AI analysis feedback

### Conflict Analysis Pipeline

1. **Git Output Parsing**
   - Extracts conflicted files from various Git status formats
   - Handles different conflict indicators (UU, AA, DD, "both modified")
   - Removes duplicates and normalizes file paths

2. **File-Level Analysis**
   - Reads conflicted files to analyze conflict markers
   - Detects `<<<<<<<`, `=======`, `>>>>>>>` patterns
   - Extracts "ours" vs "theirs" content samples
   - Counts affected lines and conflict sections

3. **Complexity Assessment**
   - **Simple**: Single conflict, <10 lines
   - **Moderate**: Few conflicts, <50 lines
   - **Complex**: Multiple conflicts, <100 lines
   - **Critical**: Extensive conflicts, >100 lines

4. **AI Resolution Generation**
   - Sends comprehensive prompt to Claude
   - Requests structured analysis and recommendations
   - Parses response into actionable suggestions
   - Provides fallback guidance if AI fails

5. **Prioritization and Reporting**
   - Orders conflicts by complexity (critical first)
   - Estimates resolution time based on complexity
   - Generates markdown reports
   - Creates step-by-step manual workflows

### Integration Points

#### With Existing Merge Workflow
The conflict handler integrates with the existing merge automation:
- Called from `auto/workflows/merge.py:execute_auto_merge()`
- Maintains backward compatibility with legacy functions
- Provides enhanced analysis while preserving existing interfaces

#### With AI Integration System
- Follows established AI integration patterns
- Uses consistent error handling and logging
- Leverages existing configuration and agent selection
- Maintains streaming support and activity monitoring

### Error Handling and Resilience

1. **Graceful Degradation**
   - AI analysis failure → Fallback to rule-based suggestions
   - File read errors → Basic conflict information
   - Git command failures → Error reporting with manual steps

2. **Comprehensive Logging**
   - Debug information for troubleshooting
   - Warning messages for recoverable errors
   - Error details for investigation

3. **Fallback Mechanisms**
   - Manual resolution guidance when AI unavailable
   - Basic conflict detection when parsing fails
   - Generic suggestions based on conflict types

### Testing Strategy

Comprehensive test coverage includes:
- **Unit Tests**: Individual function testing with mocks
- **Integration Tests**: Full workflow testing
- **Error Scenarios**: Failure mode validation
- **Edge Cases**: Various conflict types and complexities
- **Performance Tests**: Large conflict handling

Key test scenarios:
- Simple content conflicts with AI analysis
- Complex multi-file conflicts with prioritization
- AI failure scenarios with fallback behavior
- Legacy compatibility maintenance
- Rich console output verification

### Usage Examples

#### Basic Conflict Analysis
```python
from auto.models import GitHubRepository
from auto.workflows.merge_conflicts import _handle_merge_conflicts

repository = GitHubRepository(owner="org", name="repo")
conflict_output = "UU src/main.py\nAA README.md"

resolution = await _handle_merge_conflicts(
    pr_number=123,
    repository=repository,
    conflict_details=conflict_output
)

# Access structured results
for conflict in resolution.conflicts_detected:
    print(f"Conflict in {conflict.file_path}: {conflict.complexity}")

for suggestion in resolution.resolution_suggestions:
    print(f"Suggestion: {suggestion.suggested_resolution}")
```

#### Legacy Compatibility
```python
# Existing merge workflow continues to work
conflicts = await handle_merge_conflicts(123, "owner", "repo")
if conflicts:
    print("Conflicts detected:", conflicts)
```

### Performance Considerations

1. **Lazy Evaluation**
   - File analysis only when conflicts detected
   - AI analysis only for complex scenarios
   - Rich output only when terminal supports it

2. **Caching**
   - PR context caching to avoid repeated API calls
   - Conflict analysis caching for repeated runs
   - AI response caching for similar conflict patterns

3. **Concurrent Processing**
   - Parallel file analysis for multiple conflicts
   - Async AI analysis with proper error handling
   - Non-blocking Rich console updates

### Future Extensibility

The system is designed for future enhancements:
- **Additional Conflict Types**: Easy to add new conflict classifications
- **Custom Resolution Strategies**: Pluggable resolution approach
- **Enhanced AI Prompts**: Template-based prompt management
- **Integration Extensions**: Support for different VCS systems
- **Visualization Improvements**: Web-based conflict visualization

This architecture provides a robust foundation for sophisticated merge conflict handling while maintaining simplicity and reliability for common cases.