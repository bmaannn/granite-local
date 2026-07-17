#!/usr/bin/env bash
# setup.sh — First-time setup for granite-local.
#
# Checks and installs:
#   1. Homebrew (macOS package manager)
#   2. PortAudio (required by sounddevice)
#   3. Python 3.11+ virtual environment + pip packages
#   4. Ollama (local LLM / speech server)
#   5. Granite 4.1 models (gabegoodhart/granite4.1 + granite-4.1-speech)
#
# Safe to re-run — each step is idempotent.

set -eo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

info()    { echo -e "${GREEN}[setup]${NC} $*"; }
warn()    { echo -e "${YELLOW}[setup]${NC} $*"; }
error()   { echo -e "${RED}[setup] ERROR:${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Homebrew ───────────────────────────────────────────────────────────────

info "Checking Homebrew…"
if ! command -v brew &>/dev/null; then
    warn "Homebrew not found. Installing…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for Apple Silicon if needed.
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
else
    info "Homebrew already installed — $(brew --version | head -1)"
fi

# ── 2. Xcode Command Line Tools ───────────────────────────────────────────────
# Required to compile C extensions (pyobjc-core, sounddevice, etc.).
# xcode-select --install is interactive; skip if already present.

info "Checking Xcode Command Line Tools…"
if ! xcode-select -p &>/dev/null; then
    warn "Xcode Command Line Tools not found. Installing…"
    xcode-select --install
    # Wait for the user to complete the GUI install prompt.
    echo ""
    warn "A dialog has appeared asking you to install the Xcode Command Line Tools."
    warn "Click 'Install', wait for it to finish, then press Enter here to continue."
    read -r
else
    info "Xcode Command Line Tools found at $(xcode-select -p)."
fi

# ── 3. PortAudio ──────────────────────────────────────────────────────────────

info "Checking PortAudio…"
if ! brew list portaudio &>/dev/null; then
    warn "PortAudio not found. Installing via Homebrew…"
    brew install portaudio
else
    info "PortAudio already installed."
fi

# ── 4. Python virtual environment + pip packages ──────────────────────────────

MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11
BREW_PYTHON="python@3.11"

# Helper: print "major.minor.micro" for a binary, inline (no subshell).
# Usage: ver=$(_pyver python3.11)
_pyver() {
    "$1" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}')" 2>/dev/null || echo "unknown"
}

# Helper: return 0 if a binary exists and meets minimum version, 1 otherwise.
# Safe to call under set -e when wrapped in an if.
_pyok() {
    command -v "$1" &>/dev/null || return 1
    "$1" -c "import sys; sys.exit(0 if sys.version_info >= (${MIN_PYTHON_MAJOR},${MIN_PYTHON_MINOR}) else 1)" 2>/dev/null
}

info "Checking Python version…"
PYTHON_BIN=""
PYTHON_UPGRADED=false

# Search order: python3 first (the command this system uses),
# then explicit versioned binaries that Homebrew installs.
for _candidate in python3 python3.13 python3.12 python3.11; do
    if _pyok "$_candidate"; then
        PYTHON_BIN="$_candidate"
        break
    fi
done

if [[ -n "$PYTHON_BIN" ]]; then
    info "Found $(command -v "$PYTHON_BIN") ($(_pyver "$PYTHON_BIN")) — OK."
else
    # Report what python3 currently is so the user can see why it was rejected.
    if command -v python3 &>/dev/null; then
        warn "python3 found at $(command -v python3) ($(_pyver python3)) — below required ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}."
    else
        warn "python3 not found on PATH."
    fi
    warn "Installing Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR} via Homebrew…"

    brew install "$BREW_PYTHON"
    PYTHON_UPGRADED=true

    # macOS protects /usr/bin/python3 — Homebrew never overwrites it.
    # The new binary lands as a versioned name (python3.11) in the Homebrew
    # prefix. Prepend those dirs so it is found without a shell restart.
    for _prefix in /opt/homebrew/bin /usr/local/bin; do
        if [[ -d "$_prefix" && ":$PATH:" != *":$_prefix:"* ]]; then
            export PATH="$_prefix:$PATH"
        fi
    done

    # Re-scan with updated PATH.
    PYTHON_BIN=""
    for _candidate in python3.11 python3.12 python3.13 python3; do
        if _pyok "$_candidate"; then
            PYTHON_BIN="$_candidate"
            break
        fi
    done

    if [[ -n "$PYTHON_BIN" ]]; then
        info "Now using $(command -v "$PYTHON_BIN") ($(_pyver "$PYTHON_BIN"))."
    else
        error "Could not find a usable Python after brew install $BREW_PYTHON."
        error "Open a new terminal and re-run ./setup.sh, or run manually:"
        error "  brew install $BREW_PYTHON && python3.11 -m venv venv"
        exit 1
    fi
fi

VENV_DIR="$SCRIPT_DIR/venv"

# Rebuild the venv if:
#   a) Python was just upgraded (old interpreter), OR
#   b) The venv Python is outside the tested 3.11–3.13 range.
#      Python 3.14+ has no pre-built wheels for pyobjc-core (a C extension
#      pulled in by pyautogui on macOS), causing a source build failure.
if [[ -d "$VENV_DIR" ]]; then
    venv_major=$("$VENV_DIR/bin/python" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo "0")
    venv_minor=$("$VENV_DIR/bin/python" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
    if [[ "$PYTHON_UPGRADED" == true ]]; then
        warn "Python was upgraded — rebuilding venv with new interpreter…"
        rm -rf "$VENV_DIR"
    elif [[ "$venv_major" -ne 3 || "$venv_minor" -lt 11 || "$venv_minor" -gt 13 ]]; then
        warn "Venv is Python ${venv_major}.${venv_minor} (outside tested range 3.11–3.13)."
        warn "Rebuilding venv with $PYTHON_BIN to ensure pre-built wheels are available…"
        rm -rf "$VENV_DIR"
    fi
fi

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at $VENV_DIR using $PYTHON_BIN…"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    venv_ver=$("$VENV_DIR/bin/python" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}')" 2>/dev/null || echo "unknown")
    info "Virtual environment already exists (Python $venv_ver)."
fi

VENV_PYTHON="$VENV_DIR/bin/python"

# ── Ensure pip is present and new enough inside the venv ─────────────────────
# Minimum pip version required:
#   pip 23.0+ — needed for torch>=2.1.0 (PEP 658 fast metadata) and
#               openai>=1.30.0 (PEP 517 build backend support).
# We never rely on the system pip binary — all pip operations go through
# the venv Python so the correct environment is always targeted.

MIN_PIP_MAJOR=23
MIN_PIP_MINOR=0

_pip_version_ok() {
    # Returns 0 if pip inside the venv is >= MIN_PIP_MAJOR.MIN_PIP_MINOR.
    "$VENV_PYTHON" -m pip --version &>/dev/null || return 1
    "$VENV_PYTHON" -m pip --version 2>/dev/null \
        | awk '{split($2,v,"."); exit (v[1]>'"$MIN_PIP_MAJOR"' || (v[1]=='"$MIN_PIP_MAJOR"' && v[2]>='"$MIN_PIP_MINOR"')) ? 0 : 1}'
}

info "Checking pip inside venv…"
if ! "$VENV_PYTHON" -m pip --version &>/dev/null; then
    warn "pip not found inside venv. Bootstrapping via ensurepip…"
    "$VENV_PYTHON" -m ensurepip --upgrade
fi

# Read current pip version for reporting.
pip_current=$("$VENV_PYTHON" -m pip --version 2>/dev/null | awk '{print $2}' || echo "unknown")

if _pip_version_ok; then
    info "pip $pip_current — OK (>= ${MIN_PIP_MAJOR}.${MIN_PIP_MINOR})."
else
    warn "pip $pip_current is below required ${MIN_PIP_MAJOR}.${MIN_PIP_MINOR}. Upgrading…"
    "$VENV_PYTHON" -m pip install --upgrade "pip>=${MIN_PIP_MAJOR}.${MIN_PIP_MINOR}" --quiet
    pip_new=$("$VENV_PYTHON" -m pip --version 2>/dev/null | awk '{print $2}' || echo "unknown")
    info "pip upgraded: $pip_current → $pip_new."
fi

info "Installing Python packages from requirements.txt…"
"$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt"

# ── 4. Ollama ─────────────────────────────────────────────────────────────────

info "Checking Ollama…"
if ! command -v ollama &>/dev/null; then
    warn "Ollama not found. Installing…"
    curl -fsSL https://ollama.com/install.sh | sh
else
    info "Ollama already installed — $(ollama --version 2>/dev/null || echo 'version unknown')"
fi

# Ensure Ollama server is running (start in background if not).
if ! curl -sf http://localhost:11434 &>/dev/null; then
    warn "Ollama server not running. Starting in background…"
    ollama serve &>/dev/null &
    OLLAMA_PID=$!
    # Wait up to 10 s for the server to become ready.
    for i in $(seq 1 10); do
        sleep 1
        if curl -sf http://localhost:11434 &>/dev/null; then
            info "Ollama server ready."
            break
        fi
        if [[ $i -eq 10 ]]; then
            error "Ollama server did not start in time. Run 'ollama serve' manually."
            exit 1
        fi
    done
else
    info "Ollama server already running."
fi

# ── 5. Granite 4.1 models ─────────────────────────────────────────────────────

pull_if_missing() {
    local model="$1"
    # `ollama list` output format: "name:tag   id   size   modified"
    # Match the model name literally at the start of a line (before the colon+tag).
    if ollama list 2>/dev/null | grep -qF "$model"; then
        info "Model '$model' already pulled."
    else
        info "Pulling model '$model' (this may take several minutes)…"
        ollama pull "$model"
    fi
}

pull_if_missing "gabegoodhart/granite4.1:3b"
pull_if_missing "gabegoodhart/granite4.1-speech:2b"

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
info "Setup complete! To start the app:"
echo ""
echo "  IBM Granite stack (default):"
echo "    source venv/bin/activate"
echo "    ollama serve &   # skip if already running"
echo "    python main.py"
echo ""
