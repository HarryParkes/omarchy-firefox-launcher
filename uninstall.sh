#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLUGIN_ID=io.github.harryparkes.firefox-sessions
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
  python3 "$ROOT/scripts/firefox_sessions.py" reset --yes --configuration
else
  python3 "$ROOT/scripts/firefox_sessions.py" stop
fi

if [ ! -L "$LIBEXEC_DIR" ] && [ -f "$LIBEXEC_DIR/plugin-id" ] && [ "$(cat "$LIBEXEC_DIR/plugin-id")" = "$PLUGIN_ID" ]; then
  rm -rf "$LIBEXEC_DIR"
  rm -f "$BIN"
fi

printf '%s\n' "Firefox Sessions CLI removed. Remove the panel with: omarchy plugin remove $PLUGIN_ID"
