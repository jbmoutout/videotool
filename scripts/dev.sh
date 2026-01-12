#!/bin/bash
# Development setup script for vodtool

set -e

echo "Setting up vodtool development environment..."

# Check if Python 3.9+ is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Found Python $PYTHON_VERSION"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install package in editable mode
echo "Installing vodtool in development mode..."
pip install -e .

echo ""
echo "Development environment ready!"
echo "To activate the environment, run: source .venv/bin/activate"
echo "To test the CLI, run: vodtool --help"
