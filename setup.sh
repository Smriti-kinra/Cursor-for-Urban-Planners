#!/bin/bash

# Portkey API Configuration Setup Script
# - Exports env vars into shell RC file
# - Writes JSON config to ~/.claude/settings.json

set -e
# Colors
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
MAGENTA='\033[35m'
RESET='\033[0m'

APP_TYPE='Claude Code'
ENV='¯\_(ツ)_/¯'

echo ""
printf "${MAGENTA}                              ████████████████${RESET}\n"
printf "${MAGENTA}                              ████████████████${RESET}\n"
printf "${MAGENTA}              ██████████████  ██████████████${RESET}     ${BOLD}Portkey Setup${RESET}\n"
printf "${MAGENTA}              ██████████    ████████████████${RESET}     ${DIM}App Type:${RESET}    ${GREEN}${APP_TYPE}${RESET}\n"
printf "${MAGENTA}  ██████████  ██████████    ██████████████${RESET}       ${DIM}Environment:${RESET} ${YELLOW}${ENV}${RESET}\n"
printf "${MAGENTA}    ████████    ████████    ██████████████${RESET}\n"
printf "${MAGENTA}      ██████    ████████    ████████████${RESET}\n"
printf "${MAGENTA}        ██████  ████████    ████████████${RESET}\n"
printf "${MAGENTA}          ████  ████████    ██████████${RESET}\n"

# Prompt for Portkey API key
read -rsp "Enter your Portkey API key: " PORTKEY_API_KEY
echo ""

if [[ -z "$PORTKEY_API_KEY" ]]; then
  echo "Error: Portkey API key cannot be empty."
  exit 1
fi

# ── 1. Shell RC exports ───────────────────────────────────────────────────────

if [[ "$SHELL" == */zsh ]]; then
  SHELL_RC="$HOME/.zshrc"
elif [[ "$SHELL" == */bash ]]; then
  [[ "$(uname)" == "Darwin" ]] && SHELL_RC="$HOME/.bash_profile" || SHELL_RC="$HOME/.bashrc"
else
  SHELL_RC="$HOME/.profile"
fi

echo "Detected shell config: $SHELL_RC"

MARKER="# >>> Portkey Claude Code config <<<"
END_MARKER="# <<< Portkey Claude Code config <<<"

# Remove existing block if present (use grep -F for literal match, awk -v to avoid regex delimiter issues)
if grep -qF "$MARKER" "$SHELL_RC" 2>/dev/null; then
  echo "Removing existing Portkey config block..."
  TMP=$(mktemp)
  awk -v start="$MARKER" -v end="$END_MARKER" \
    '$0 == start { found=1 } !found { print } $0 == end { found=0 }' \
    "$SHELL_RC" > "$TMP"
  mv "$TMP" "$SHELL_RC"
fi

cat >> "$SHELL_RC" << EOF

$MARKER
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1
$END_MARKER
EOF

echo "✅ Shell exports written to $SHELL_RC"

# Export into current session too
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1

# ── 2. ~/.claude/settings.json ────────────────────────────────────────────────

SETTINGS_FILE="$HOME/.claude/settings.json"
mkdir -p "$(dirname "$SETTINGS_FILE")"

# Read existing JSON or start fresh
if [[ -f "$SETTINGS_FILE" ]]; then
  EXISTING=$(cat "$SETTINGS_FILE")
else
  EXISTING="{}"
fi

# Check for jq
if ! command -v jq &>/dev/null; then
  echo ""
  echo "⚠️  jq not found — writing settings.json without merging existing content."
  cat > "$SETTINGS_FILE" << EOF
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.portkey.ai",
    "ANTHROPIC_AUTH_TOKEN": "$PORTKEY_API_KEY",
    "ANTHROPIC_CUSTOM_HEADERS": "x-portkey-api-key: $PORTKEY_API_KEY\nx-portkey-provider: @aws-us-east-1",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "global.anthropic.claude-sonnet-4-6",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "global.anthropic.claude-opus-4-6-v1",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "global.anthropic.claude-haiku-4-5-20251001-v1:0"
  },
  "model": "opus"
}
EOF
else
  # Use printf to get a real newline into the variable (works in both bash and zsh)
  CUSTOM_HEADERS=$(printf 'x-portkey-api-key: %s\nx-portkey-provider: @aws-us-east-1' "$PORTKEY_API_KEY")
  echo "$EXISTING" | jq \
    --arg base_url "https://api.portkey.ai" \
    --arg auth_token "$PORTKEY_API_KEY" \
    --arg custom_headers "$CUSTOM_HEADERS" \
    --arg sonnet "global.anthropic.claude-sonnet-4-6" \
    --arg opus "global.anthropic.claude-opus-4-6-v1" \
    --arg haiku "global.anthropic.claude-haiku-4-5-20251001-v1:0" \
    '.env.ANTHROPIC_BASE_URL = $base_url
    | .env.ANTHROPIC_AUTH_TOKEN = $auth_token
    | .env.ANTHROPIC_CUSTOM_HEADERS = $custom_headers
    | .env.ANTHROPIC_DEFAULT_SONNET_MODEL = $sonnet
    | .env.ANTHROPIC_DEFAULT_OPUS_MODEL = $opus
    | .env.ANTHROPIC_DEFAULT_HAIKU_MODEL = $haiku
    | .model = "opus"' \
    > "$SETTINGS_FILE"
fi

echo "✅ ~/.claude/settings.json updated"

# ── 3. Summary ────────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "Shell RC ($SHELL_RC):"
echo "  CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS = 1"
echo ""
echo "~/.claude/settings.json:"
echo "  ANTHROPIC_BASE_URL          = https://api.portkey.ai"
echo "  ANTHROPIC_AUTH_TOKEN        = ${PORTKEY_API_KEY:0:8}... (hidden)"
echo "  ANTHROPIC_DEFAULT_SONNET    = global.anthropic.claude-sonnet-4-6"
echo "  ANTHROPIC_DEFAULT_OPUS      = global.anthropic.claude-opus-4-6-v1"
echo "  ANTHROPIC_DEFAULT_HAIKU     = global.anthropic.claude-haiku-4-5-20251001-v1:0"
echo "  model                       = opus"
echo ""
echo "To apply shell exports in future sessions:"
echo "  source $SHELL_RC"