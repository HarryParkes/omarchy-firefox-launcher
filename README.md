# Firefox Sessions for Omarchy v4

Firefox Sessions is an Omarchy-styled Quickshell bar plugin and an independent CLI. It launches isolated Firefox instances, places them across Hyprland workspaces, and manages only the processes that it started.

## Architecture

```text
Quickshell panel
      │ JSON lines and status
      ▼
firefox-sessions CLI
      ├── XDG configuration
      ├── PID, start-time, and profile tracking
      ├── Firefox processes with one profile and window class each
      └── hyprctl placement and focus
```

The panel contains presentation only. The Python CLI owns configuration, launch staggering, process identity, profile deletion, and Hyprland actions. The CLI does not use `pkill`, process-name matching, or a global Firefox window rule.

Each session uses:

```text
firefox --new-instance --no-remote \
  --profile ~/.local/share/firefox-sessions/profile-XX \
  --name firefox-sessions-XX \
  --class firefox-sessions-XX \
  --new-window URL
```

Current Firefox documentation states that `--new-instance` opens a separate instance, `--profile` selects a profile path, and `--new-window` opens the URL. `--no-remote` is included for compatibility. Unique `--name` and `--class` values let Hyprland identify managed windows on native Wayland and XWayland.

## Install on Omarchy v4

```bash
git clone https://github.com/HarryParkes/omarchy-firefox-launcher.git
cd omarchy-firefox-launcher
./install.sh
```

The installer copies files to user-owned locations:

```text
~/.config/omarchy/plugins/io.github.harryparkes.firefox-sessions/
~/.local/bin/firefox-sessions
~/.local/lib/firefox-sessions/
```

It validates the plugin with `omarchy plugin validate` and enables it in the right bar section when the Omarchy shell is running. If the shell is not running, use:

```bash
omarchy plugin enable io.github.harryparkes.firefox-sessions --section right
```

No Omarchy core file or Hyprland configuration file is changed.

## Launch and use

Select the Firefox glyph in the Omarchy bar. The panel provides:

- persisted target URL;
- 12, 24, and 48 presets, with 48 as the default;
- a custom count from 1 to 999;
- equal grids with up to 16 sessions per workspace;
- Launch Sessions and Launch Missing;
- Stop All, Relaunch, and confirmed Reset Profiles;
- Open Workspace and Next Session;
- running count and launch progress;
- one-off Launch, Stop All, and Relaunch schedules.

Launch Sessions and Launch Missing are both safe ensure operations. They start only missing session numbers. Relaunch stops all managed sessions and starts the configured set again.

The CLI works without Quickshell:

```bash
firefox-sessions launch --count 48 --url "https://example.com"
firefox-sessions status
firefox-sessions focus
firefox-sessions next
firefox-sessions stop
firefox-sessions relaunch
firefox-sessions reset --yes
```

## One-off schedules

Create one-time actions with a local date and time:

```bash
firefox-sessions schedule add --at "2026-10-02 09:00" --action launch
firefox-sessions schedule add --at "2026-10-02 18:00" --action stop
firefox-sessions schedule add --at "2026-10-03 08:30" --action relaunch
firefox-sessions schedule list
firefox-sessions schedule cancel <id>
```

The panel provides the same actions, shows pending schedules, and lets you cancel each one. Times use the machine's local timezone. Past times are rejected.

Each schedule is a persistent systemd user timer under `~/.config/systemd/user`. If the machine is off at the selected time, systemd runs the action once after the next login. The timer, service, and schedule record remove themselves after the action runs. Uninstall also disables and removes all pending Firefox Sessions timers.

## Multiple workspaces

Enter a comma-separated workspace list in the panel or CLI:

```bash
firefox-sessions configure --workspaces "4,5,6"
firefox-sessions configure --workspaces "special:firefox-sessions"
firefox-sessions configure --workspaces "special:research-a,special:research-b"
```

Sessions are assigned in groups of 16 and arranged in equal grids. For example, sessions 1–16 use workspace `4`, sessions 17–32 use `5`, and sessions 33–48 use `6`. If the configured list is too short, numeric workspaces continue in sequence and named workspaces get a numeric suffix. Open Workspace cycles through every used workspace. Running Launch Sessions again also reapplies placement to existing managed windows.

The default is `special:firefox-sessions`. With 48 sessions, overflow uses `special:firefox-sessions-2` and `special:firefox-sessions-3`. A normal workspace value can be a positive number or a Hyprland workspace name. A special workspace must use `special:name`.

## Configuration and state

XDG locations are used when their environment variables are set:

```text
$XDG_CONFIG_HOME/firefox-sessions/config.json
$XDG_CONFIG_HOME/firefox-sessions/schedules.json
$XDG_DATA_HOME/firefox-sessions/profile-XX
$XDG_RUNTIME_DIR/firefox-sessions/state.json
$XDG_CONFIG_HOME/systemd/user/firefox-sessions-*.{timer,service}
```

Defaults are `~/.config`, `~/.local/share`, and the current user runtime directory. Every profile has independent cookies, storage, cache, preferences, extensions, and browser state.

The runtime state records a PID, Linux process start time, exact profile path, and unique window class. Before sending a signal, the manager verifies all process identity data again. Stale PIDs and normal Firefox instances are ignored. Stop first sends `SIGTERM`, waits up to eight seconds, and uses `SIGKILL` only for a still-verified managed process.

Profile reset requires `--yes` in the CLI and a confirmation dialog in the panel. It canonicalises the XDG data path, rejects a symbolic-link profile root, stops managed sessions, and deletes only the Firefox Sessions profile root.

## Files in this repository

```text
install.sh
uninstall.sh
quickshell/Panel.qml
quickshell/manifest.json
scripts/firefox-sessions
scripts/firefox_sessions.py
tests/test_manager.py
README.md
LICENSE
```

## Remove

Remove the plugin and CLI but keep profiles and configuration:

```bash
./uninstall.sh
```

Remove everything, including all managed Firefox profiles and settings:

```bash
./uninstall.sh --purge
```

For unattended complete removal:

```bash
./uninstall.sh --purge --yes
```

## Remote verification limits

This development VM does not have Firefox, Quickshell, Hyprland, or a running Omarchy shell. The CLI was tested with real Linux processes that emulate long-running Firefox instances. The project was validated with the current Omarchy v4 plugin validator and current Omarchy QML APIs. A real Firefox launch, Hyprland placement, and rendered panel could not be exercised on this VM and must be checked on the target Omarchy machine.
