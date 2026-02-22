#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Install/upgrade dependencies
echo "Ensuring dependencies are installed..."
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# Run novel-builder with all passed arguments
python "$SCRIPT_DIR/novel-builder.py" "$@"
