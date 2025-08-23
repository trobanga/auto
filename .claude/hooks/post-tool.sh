#!/bin/bash
#
# Claude Code post-tool hook
# Runs ruff formatting and linting after code modifications
#

# Check if this is a tool that modifies files
if [[ "$CLAUDE_TOOL_NAME" =~ ^(Edit|MultiEdit|Write|NotebookEdit)$ ]]; then
    echo "🧹 Running ruff format and check..."
    
    # Change to project directory
    cd "$(dirname "$0")/../.." || exit 1
    
    # Run ruff format and check
    if command -v ruff >/dev/null 2>&1; then
        echo "  📝 Formatting code..."
        ruff format auto tests
        
        echo "  🔍 Checking and fixing linting issues..."
        ruff check --fix auto tests
        
        echo "✅ Code formatted and linted with ruff"
    else
        echo "⚠️  ruff not found, skipping formatting"
        exit 1
    fi
fi