#!/usr/bin/env bash
set -euo pipefail

echo "=== Setting up Functualize Examples Dev Container ==="

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Navigate to the repo root (one level above examples/)
cd /workspace

# Install all workspace packages in development mode
uv sync --all-packages

echo ""
echo "=== Setup complete ==="
echo ""
echo "Available commands:"
echo "  func --help                     # Functualize CLI"
echo "  cd examples/quickstart          # README Quick Start, step by step"
echo "  cd examples/standalone          # Feature reference examples"
echo "  cd examples/project             # Full project examples"
echo "  cd examples/plugins             # Plugin authoring examples"
echo ""
echo "Run tests:"
echo "  uv run pytest examples/ -v      # All example tests"
echo ""
