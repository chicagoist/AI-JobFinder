#!/bin/bash
# Setup script for local LLM (Ollama) — GDPR-compliant, no cloud dependency.
# Run: bash scripts/setup_local_llm.sh

set -e

echo "========================================"
echo "  Local LLM Setup — Ollama + Qwen2.5"
echo "  All inference stays on your machine."
echo "========================================"
echo ""

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Linux*)   MACHINE=Linux ;;
    Darwin*)  MACHINE=macOS ;;
    CYGWIN*|MINGW*|MSYS*)  MACHINE=Windows ;;
    *)        echo "❌ Unknown OS: $OS. Please install Ollama manually from https://ollama.com"
              exit 1 ;;
esac

echo "📦 Detected OS: $MACHINE"

# 1. Install Ollama
if command -v ollama &> /dev/null; then
    echo "✅ Ollama already installed ($(ollama --version 2>/dev/null || echo 'unknown'))"
else
    echo "⬇️  Installing Ollama..."
    if [ "$MACHINE" = "Linux" ]; then
        curl -fsSL https://ollama.com/install.sh | sh
    elif [ "$MACHINE" = "macOS" ]; then
        # macOS: download from website (no official brew formula for headless)
        echo "🍎 Downloading Ollama for macOS..."
        curl -fsSL https://ollama.com/download/Ollama-darwin.zip -o /tmp/ollama.zip
        echo "   Please install manually from /tmp/ollama.zip or visit https://ollama.com"
    elif [ "$MACHINE" = "Windows" ]; then
        echo "🪟 Windows detected. Please install Ollama manually:"
        echo "   https://ollama.com/download/windows"
        echo "   Or via WSL2: run this script inside WSL2."
    fi
fi

# 2. Start Ollama service (Linux)
if [ "$MACHINE" = "Linux" ]; then
    if systemctl is-active --quiet ollama 2>/dev/null; then
        echo "✅ Ollama service is running"
    else
        echo "🚀 Starting Ollama service..."
        sudo systemctl start ollama || ollama serve &
        sleep 2
    fi
fi

# 3. Wait for Ollama to be ready
echo "⏳ Waiting for Ollama to respond..."
for i in $(seq 1 30); do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✅ Ollama is ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "⚠️  Ollama did not start. Please run 'ollama serve' manually."
    fi
    sleep 1
done

# 4. Pull default model
MODEL=${1:-llama3.2:3b}
echo "📥 Pulling model: $MODEL (~4.4GB)"
echo "   This may take a while depending on your internet connection..."
ollama pull "$MODEL"

echo ""
echo "========================================"
echo "  ✅ Setup complete!"
echo "  Model: $MODEL"
echo "  API:   http://localhost:11434"
echo ""
echo "  To verify:"
echo "    python -c \"from job_agent.ollama_llm import call_ollama; print(call_ollama('Hallo'))\""
echo ""
echo "  To use as default LLM, set in config.yaml:"
echo "    llm:"
echo "      priority: local"
echo "      local_model: $MODEL"
echo "========================================"
