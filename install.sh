#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-"$HOME/.config"}
XDG_DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
PLUGIN_ID=io.github.harryparkes.firefox-sessions
PLUGIN_DIR="$XDG_CONFIG_HOME/omarchy/plugins/$PLUGIN_ID"
LIBEXEC_DIR="$HOME/.local/lib/firefox-sessions"
BIN_DIR="$HOME/.local/bin"

command -v python3 >/dev/null 2>&1 || {
  printf '%s\n' "Python 3 is required." >&2
  exit 1
}

if [ -e "$PLUGIN_DIR" ] || [ -L "$PLUGIN_DIR" ]; then
  if [ ! -f "$PLUGIN_DIR/manifest.json" ] || ! grep -q "\"id\": \"$PLUGIN_ID\"" "$PLUGIN_DIR/manifest.json"; then
    printf '%s\n' "Refusing to replace $PLUGIN_DIR because it is not this plugin." >&2
    exit 1
  fi
fi

mkdir -p "$PLUGIN_DIR" "$LIBEXEC_DIR" "$BIN_DIR" "$XDG_CONFIG_HOME/firefox-sessions" "$XDG_DATA_HOME/firefox-sessions"

SYSTEMD_USER_DIR="$XDG_CONFIG_HOME/systemd/user"
if command -v systemctl >/dev/null 2>&1; then
  for timer in "$SYSTEMD_USER_DIR"/firefox-sessions-*.timer; do
    [ -e "$timer" ] || continue
    systemctl --user disable --now "$(basename "$timer")" >/dev/null 2>&1 || true
  done
fi
rm -f "$SYSTEMD_USER_DIR"/firefox-sessions-*.timer "$SYSTEMD_USER_DIR"/firefox-sessions-*.service
rm -f "$XDG_CONFIG_HOME/firefox-sessions/schedules.json"
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

cp "$ROOT/quickshell/manifest.json" "$ROOT/quickshell/Panel.qml" "$PLUGIN_DIR/"
install -m 755 "$ROOT/scripts/firefox_sessions.py" "$LIBEXEC_DIR/firefox_sessions.py"
install -m 755 "$ROOT/scripts/firefox-sessions" "$BIN_DIR/firefox-sessions"
printf '%s\n' "$PLUGIN_ID" > "$LIBEXEC_DIR/plugin-id"

if command -v omarchy >/dev/null 2>&1; then
  if ! omarchy plugin validate "$PLUGIN_DIR"; then
    printf '%s\n' "Omarchy rejected the plugin. Installed files were kept for inspection." >&2
    exit 1
  fi
  if command -v omarchy-shell >/dev/null 2>&1 && omarchy-shell -q shell ping >/dev/null 2>&1; then
    omarchy-shell shell rescanPlugins >/dev/null
    omarchy plugin enable "$PLUGIN_ID" --section right
  else
    printf '%s\n' "The Omarchy shell is not running. Enable later with: omarchy plugin enable $PLUGIN_ID --section right"
  fi
else
  printf '%s\n' "Omarchy was not found. The CLI is installed; the panel can be enabled after Omarchy v4 is installed."
fi

if ! command -v firefox >/dev/null 2>&1; then
  printf '%s\n' "Firefox was not found on PATH. Install Firefox before launching sessions."
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '%s\n' "Add $BIN_DIR to PATH before using firefox-sessions." ;;
esac

printf '%s\n' "Firefox Sessions installed."
