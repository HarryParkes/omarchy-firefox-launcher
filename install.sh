#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLUGIN_ID=io.github.harryparkes.firefox-sessions
LIBEXEC_DIR="$HOME/.local/lib/firefox-sessions"
BIN_DIR="$HOME/.local/bin"

command -v python3 >/dev/null 2>&1 || {
  printf '%s\n' "Python 3 is required." >&2
  exit 1
}

if [ -L "$LIBEXEC_DIR" ] || [ -L "$BIN_DIR/firefox-sessions" ]; then
  printf '%s\n' "Refusing to replace a linked CLI installation." >&2
  exit 1
fi

mkdir -p "$LIBEXEC_DIR" "$BIN_DIR"
install -m 755 "$ROOT/scripts/firefox_sessions.py" "$LIBEXEC_DIR/firefox_sessions.py"
install -m 755 "$ROOT/scripts/firefox-sessions" "$BIN_DIR/firefox-sessions"
printf '%s\n' "$PLUGIN_ID" > "$LIBEXEC_DIR/plugin-id"

if ! command -v firefox >/dev/null 2>&1; then
  printf '%s\n' "Firefox was not found on PATH. Install Firefox before launching sessions."
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '%s\n' "Add $BIN_DIR to PATH before using firefox-sessions." ;;
esac

printf '%s\n' "Firefox Sessions CLI installed."
