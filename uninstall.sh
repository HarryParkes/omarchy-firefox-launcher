#!/bin/sh
set -eu

XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-"$HOME/.config"}
XDG_DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
PLUGIN_ID=io.github.harryparkes.firefox-sessions
PLUGIN_DIR="$XDG_CONFIG_HOME/omarchy/plugins/$PLUGIN_ID"
LIBEXEC_DIR="$HOME/.local/lib/firefox-sessions"
BIN="$HOME/.local/bin/firefox-sessions"
PURGE=0
YES=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1 ;;
    --yes|-y) YES=1 ;;
    *) printf '%s\n' "Usage: ./uninstall.sh [--purge] [--yes]" >&2; exit 1 ;;
  esac
  shift
done

if [ -x "$BIN" ]; then
  "$BIN" stop >/dev/null 2>&1 || true
fi

SYSTEMD_USER_DIR="$XDG_CONFIG_HOME/systemd/user"
if command -v systemctl >/dev/null 2>&1; then
  for timer in "$SYSTEMD_USER_DIR"/firefox-sessions-*.timer; do
    [ -e "$timer" ] || continue
    systemctl --user disable --now "$(basename "$timer")" >/dev/null 2>&1 || true
  done
fi
rm -f "$SYSTEMD_USER_DIR"/firefox-sessions-*.timer "$SYSTEMD_USER_DIR"/firefox-sessions-*.service
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

if command -v omarchy >/dev/null 2>&1 && [ -e "$PLUGIN_DIR" ]; then
  omarchy plugin disable "$PLUGIN_ID" >/dev/null 2>&1 || true
fi

if [ -f "$PLUGIN_DIR/manifest.json" ] && grep -q "\"id\": \"$PLUGIN_ID\"" "$PLUGIN_DIR/manifest.json"; then
  rm -rf "$PLUGIN_DIR"
fi

if [ -f "$LIBEXEC_DIR/plugin-id" ] && [ "$(cat "$LIBEXEC_DIR/plugin-id")" = "$PLUGIN_ID" ]; then
  rm -rf "$LIBEXEC_DIR"
  rm -f "$BIN"
fi

if [ "$PURGE" -eq 1 ]; then
  if [ "$YES" -ne 1 ]; then
    if [ ! -t 0 ]; then
      printf '%s\n' "Profile deletion requires --yes when no terminal is attached." >&2
      exit 1
    fi
    printf '%s' "Delete all Firefox Sessions profiles and configuration? [y/N] "
    read -r answer
    case "$answer" in y|Y|yes|YES) ;; *) printf '%s\n' "Profiles kept."; exit 0 ;; esac
  fi
  rm -rf "$XDG_DATA_HOME/firefox-sessions" "$XDG_CONFIG_HOME/firefox-sessions"
fi

if command -v omarchy-shell >/dev/null 2>&1; then
  omarchy-shell -q shell rescanPlugins >/dev/null 2>&1 || true
fi

printf '%s\n' "Firefox Sessions removed."
