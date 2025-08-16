#!/bin/bash
# Installation helper for the auto tool

set -e

echo "Installing auto tool..."

# Check Python version
python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1-2)
required_version="3.8"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
    echo "Error: Python 3.8+ is required. Found Python $python_version"
    exit 1
fi

echo "✓ Python $python_version detected"

# Install package
if command -v pipx >/dev/null 2>&1; then
    echo "Installing with pipx (recommended)..."
    pipx install .
else
    echo "Installing with pip..."
    pip install --user .
fi

echo "✓ auto tool installed successfully"

# Check required dependencies
echo "Checking dependencies..."

if ! command -v gh >/dev/null 2>&1; then
    echo "⚠️  Warning: GitHub CLI (gh) not found. Install it for GitHub integration:"
    echo "   https://cli.github.com/"
fi

if ! command -v git >/dev/null 2>&1; then
    echo "❌ Error: git is required but not found"
    exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
    echo "⚠️  Warning: Claude CLI not found. Install it for AI integration:"
    echo "   https://github.com/anthropics/claude-cli"
fi

echo "✓ Dependencies checked"

# Initialize configuration
echo "Initializing configuration..."
auto init

echo ""
echo "🎉 auto tool installation complete!"
echo ""
echo "Next steps:"
echo "1. Configure GitHub CLI: gh auth login"
echo "2. Set up AI agent: auto config set ai.command claude"
echo "3. Run 'auto --help' to see available commands"
echo ""