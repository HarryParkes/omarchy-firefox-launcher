#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


APP = "firefox-sessions"
SESSIONS_PER_WORKSPACE = 16
DEFAULT_CONFIG = {
    "count": 48,
    "url": "about:blank",
    "workspaces": ["special:firefox-sessions"],
}
CLASS_PREFIX = "firefox-sessions-"


def xdg_path(variable, fallback):
    return Path(os.environ.get(variable, Path.home() / fallback)).expanduser()


CONFIG_ROOT = xdg_path("XDG_CONFIG_HOME", ".config") / APP
DATA_ROOT = xdg_path("XDG_DATA_HOME", ".local/share") / APP
RUNTIME_ROOT = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/{APP}-{os.getuid()}")) / APP
CONFIG_FILE = CONFIG_ROOT / "config.json"
SCHEDULE_FILE = CONFIG_ROOT / "schedules.json"
STATE_FILE = RUNTIME_ROOT / "state.json"
LOCK_FILE = RUNTIME_ROOT / "manager.lock"
SYSTEMD_ROOT = CONFIG_ROOT.parent / "systemd" / "user"


class UserError(Exception):
    pass


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def read_json(path, fallback):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else fallback.copy()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback.copy()


@contextmanager
def locked():
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with LOCK_FILE.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def validate_count(value):
    count = int(value)
    if not 1 <= count <= 999:
        raise UserError("session count must be between 1 and 999")
    return count


def validate_url(value):
    value = value.strip()
    parsed = urlparse(value)
    if value == "about:blank":
        return value
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UserError("URL must use http or https, or be about:blank")
    return value


def validate_workspaces(value):
    items = [item.strip() for item in value.split(",") if item.strip()]
    pattern = re.compile(r"^(?:[1-9][0-9]*|[A-Za-z0-9._-]+|special:[A-Za-z0-9._-]+)$")
    if not items or any(not pattern.fullmatch(item) for item in items):
        raise UserError("workspaces must be comma-separated names, numbers, or special:name values")
    return items


def workspace_targets(workspaces, count):
    required = (count + SESSIONS_PER_WORKSPACE - 1) // SESSIONS_PER_WORKSPACE
    targets = list(workspaces[:required])
    if len(targets) >= required:
        return targets
    base = targets[-1]
    while len(targets) < required:
        if base.isdigit():
            targets.append(str(int(base) + len(targets) - len(workspaces) + 1))
        else:
            targets.append(f"{base}-{len(targets) - len(workspaces) + 2}")
    return targets


def workspace_for_session(index, targets):
    return targets[(index - 1) // SESSIONS_PER_WORKSPACE]


def grid_cells(monitor, count):
    columns = min(4, count)
    rows = (count + columns - 1) // columns
    scale = float(monitor.get("scale", 1)) or 1
    width = round(monitor["width"] / scale)
    height = round(monitor["height"] / scale)
    left, top, right, bottom = monitor.get("reserved", [0, 0, 0, 0])
    outer = 10
    inner = 5
    cell_width = (width - left - right - 2 * outer - inner * (columns - 1)) // columns
    cell_height = (height - top - bottom - 2 * outer - inner * (rows - 1)) // rows
    origin_x = monitor.get("x", 0) + left + outer
    origin_y = monitor.get("y", 0) + top + outer
    return [
        (
            origin_x + column * (cell_width + inner),
            origin_y + row * (cell_height + inner),
            cell_width,
            cell_height,
        )
        for row in range(rows)
        for column in range(columns)
    ][:count]


def load_config():
    raw = read_json(CONFIG_FILE, DEFAULT_CONFIG)
    try:
        return {
            "count": validate_count(raw.get("count", DEFAULT_CONFIG["count"])),
            "url": validate_url(str(raw.get("url", DEFAULT_CONFIG["url"]))),
            "workspaces": validate_workspaces(",".join(raw.get("workspaces", DEFAULT_CONFIG["workspaces"]))),
        }
    except (UserError, TypeError, ValueError):
        return DEFAULT_CONFIG.copy()


def process_start_time(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat[stat.rfind(")") + 2 :].split()[19]
    except (FileNotFoundError, IndexError, OSError):
        return None


def process_args(pid):
    try:
        return [part.decode(errors="replace") for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if part]
    except (FileNotFoundError, PermissionError, OSError):
        return []


def is_managed(record):
    pid = record.get("pid")
    profile = record.get("profile")
    start_time = record.get("start_time")
    if not isinstance(pid, int) or not isinstance(profile, str) or not start_time:
        return False
    if process_start_time(pid) != str(start_time):
        return False
    args = process_args(pid)
    return any(args[index] == "--profile" and args[index + 1] == profile for index in range(len(args) - 1))


def live_state():
    state = read_json(STATE_FILE, {"sessions": {}})
    sessions = state.get("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
    live = {key: value for key, value in sessions.items() if isinstance(value, dict) and is_managed(value)}
    result = {"sessions": live, "workspace_index": int(state.get("workspace_index", -1))}
    if result != state:
        atomic_json(STATE_FILE, result)
    return result


def profile_path(index):
    return DATA_ROOT / f"profile-{index:02d}"


def class_name(index):
    return f"{CLASS_PREFIX}{index:02d}"


def status_value(config, state):
    return {
        "configured": config["count"],
        "running": len(state["sessions"]),
        "url": config["url"],
        "workspaces": config["workspaces"],
        "profiles": str(DATA_ROOT),
        "sessions": sorted(int(key) for key in state["sessions"]),
    }


def print_value(value, as_json):
    if as_json:
        print(json.dumps(value), flush=True)
    else:
        print(value, flush=True)


def configure(args):
    config = load_config()
    if args.count is not None:
        config["count"] = validate_count(args.count)
    if args.url is not None:
        config["url"] = validate_url(args.url)
    if args.workspaces is not None:
        config["workspaces"] = validate_workspaces(args.workspaces)
    atomic_json(CONFIG_FILE, config)
    print(f"Configured {config['count']} sessions")


def firefox_binary():
    candidate = os.environ.get("FIREFOX_SESSIONS_FIREFOX", "firefox")
    resolved = shutil.which(candidate) if "/" not in candidate else candidate
    if not resolved or not Path(resolved).is_file():
        raise UserError(f"Firefox executable not found: {candidate}")
    return resolved


def launch(args):
    with locked():
        config = load_config()
        if args.count is not None:
            config["count"] = validate_count(args.count)
        if args.url is not None:
            config["url"] = validate_url(args.url)
        if args.workspaces is not None:
            config["workspaces"] = validate_workspaces(args.workspaces)
        atomic_json(CONFIG_FILE, config)
        state = live_state()
        binary = firefox_binary()
        missing = [index for index in range(1, config["count"] + 1) if str(index) not in state["sessions"]]
        launched = 0
        targets = workspace_targets(config["workspaces"], config["count"])
        assignments = {
            record["class"]: workspace_for_session(int(index), targets)
            for index, record in state["sessions"].items()
            if int(index) <= config["count"] and record.get("class")
        }
        for index in missing:
            profile = profile_path(index)
            profile.mkdir(parents=True, exist_ok=True, mode=0o700)
            identity = class_name(index)
            process = subprocess.Popen(
                [
                    binary,
                    "--new-instance",
                    "--no-remote",
                    "--profile",
                    str(profile.resolve()),
                    "--name",
                    identity,
                    "--class",
                    identity,
                    "--new-window",
                    config["url"],
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            start_time = None
            for _ in range(20):
                start_time = process_start_time(process.pid)
                if start_time:
                    break
                time.sleep(0.01)
            state["sessions"][str(index)] = {
                "pid": process.pid,
                "start_time": start_time,
                "profile": str(profile.resolve()),
                "class": identity,
            }
            assignments[identity] = workspace_for_session(index, targets)
            atomic_json(STATE_FILE, state)
            launched += 1
            print_value(
                {
                    "event": "progress",
                    "current": launched,
                    "total": len(missing),
                    "session": index,
                    "running": len(state["sessions"]),
                }
                if args.json
                else f"Launching {launched} / {len(missing)}",
                args.json,
            )
            if launched < len(missing):
                time.sleep(args.stagger_ms / 1000)
        final = status_value(config, state) | {"event": "complete", "launched": launched}
        print_value(final if args.json else f"Running {final['running']} / {final['configured']}", args.json)
    if assignments and shutil.which("hyprctl"):
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_place", json.dumps(assignments)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def stop_managed(timeout=8):
    state = live_state()
    records = list(state["sessions"].values())
    for record in records:
        if is_managed(record):
            try:
                os.kill(record["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(is_managed(record) for record in records):
        time.sleep(0.1)
    remaining = [record for record in records if is_managed(record)]
    for record in remaining:
        try:
            os.kill(record["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass
    atomic_json(STATE_FILE, {"sessions": {}, "workspace_index": state.get("workspace_index", -1)})
    return len(records), len(remaining)


def stop(_args):
    with locked():
        stopped, forced = stop_managed()
    suffix = f"; forced {forced}" if forced else ""
    print(f"Stopped {stopped} managed sessions{suffix}")


def relaunch(args):
    with locked():
        stopped, _ = stop_managed()
    if not args.json:
        print(f"Stopped {stopped} managed sessions")
    launch(args)


def reset(args):
    if not args.yes:
        raise UserError("reset requires --yes")
    data_home = xdg_path("XDG_DATA_HOME", ".local/share").resolve(strict=False)
    expected = data_home / APP
    if DATA_ROOT.is_symlink():
        raise UserError("refusing to reset a linked profile path")
    actual = DATA_ROOT.resolve(strict=False)
    if actual != expected or actual == Path.home().resolve() or actual == Path("/"):
        raise UserError("refusing to reset an unexpected profile path")
    with locked():
        stop_managed()
        if actual.exists():
            shutil.rmtree(actual)
    print(f"Removed profiles from {actual}")


def hyprctl(*arguments, check=False):
    try:
        return subprocess.run(
            ["hyprctl", *arguments], text=True, capture_output=True, check=True, timeout=3
        ).stdout
    except subprocess.CalledProcessError as error:
        if check:
            raise UserError(error.stderr.strip() or error.stdout.strip() or "hyprctl failed") from error
        return ""
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        if check:
            raise UserError("hyprctl is unavailable") from error
        return ""


def dispatch(expression):
    return hyprctl("eval", f"hl.dispatch({expression})", check=True)


def clients():
    try:
        value = json.loads(hyprctl("clients", "-j"))
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def monitors():
    try:
        value = json.loads(hyprctl("monitors", "-j"))
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def arrange(placed):
    available = {monitor.get("id"): monitor for monitor in monitors()}
    for windows in placed.values():
        windows.sort(key=lambda client: client.get("initialClass") or client.get("class", ""))
        monitor = available.get(windows[0].get("monitor")) if windows else None
        if not monitor:
            continue
        for client, (x, y, width, height) in zip(windows, grid_cells(monitor, len(windows))):
            address = f"address:{client['address']}"
            dispatch(f'hl.dsp.window.float({{ action = "enable", window = "{address}" }})')
            dispatch(
                f'hl.dsp.window.resize({{ x = {width}, y = {height}, relative = false, window = "{address}" }})'
            )
            dispatch(f'hl.dsp.window.move({{ x = {x}, y = {y}, relative = false, window = "{address}" }})')


def place(args):
    assignments = json.loads(args.assignments)
    pending = dict(assignments)
    placed = {target: [] for target in set(assignments.values())}
    deadline = time.monotonic() + 30
    while pending and time.monotonic() < deadline:
        for client in clients():
            identity = client.get("initialClass") or client.get("class")
            if identity not in pending or not client.get("address"):
                continue
            target = pending.pop(identity)
            dispatch(
                f'hl.dsp.window.move({{ workspace = {json.dumps(target)}, follow = false, '
                f'window = "address:{client["address"]}" }})'
            )
            placed[target].append(client)
        if pending:
            time.sleep(0.25)
    arrange(placed)


def focus(_args):
    with locked():
        config = load_config()
        state = live_state()
        targets = workspace_targets(config["workspaces"], config["count"])
        state["workspace_index"] = (state.get("workspace_index", -1) + 1) % len(targets)
        target = targets[state["workspace_index"]]
        atomic_json(STATE_FILE, state)
    if target.startswith("special:"):
        dispatch(f"hl.dsp.workspace.toggle_special({json.dumps(target.removeprefix('special:'))})")
    else:
        dispatch(f"hl.dsp.focus({{ workspace = {json.dumps(target)} }})")
    print(f"Opened workspace {target}")


def next_session(_args):
    managed = sorted(
        (
            client
            for client in clients()
            if re.fullmatch(rf"{re.escape(CLASS_PREFIX)}[0-9]+", client.get("initialClass") or client.get("class", ""))
            and client.get("address")
        ),
        key=lambda client: client.get("initialClass") or client.get("class"),
    )
    if not managed:
        raise UserError("no managed Firefox windows found")
    try:
        active = json.loads(hyprctl("activewindow", "-j")).get("address")
    except json.JSONDecodeError:
        active = None
    current = next((index for index, client in enumerate(managed) if client["address"] == active), -1)
    target = managed[(current + 1) % len(managed)]
    dispatch(f'hl.dsp.focus({{ window = "address:{target["address"]}" }})')
    print(f"Focused {target.get('initialClass') or target.get('class')}")


def parse_schedule_time(value):
    try:
        scheduled = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise UserError("time must use YYYY-MM-DD HH:MM or an ISO 8601 value") from error
    scheduled = scheduled.astimezone()
    if scheduled <= datetime.now().astimezone():
        raise UserError("scheduled time must be in the future")
    return scheduled.replace(microsecond=0)


def schedules():
    value = read_json(SCHEDULE_FILE, {"schedules": []}).get("schedules", [])
    if not isinstance(value, list):
        return []
    return sorted((item for item in value if isinstance(item, dict)), key=lambda item: item.get("at", ""))


def save_schedules(value):
    atomic_json(SCHEDULE_FILE, {"schedules": value})


def unit_escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def systemctl(*arguments, check=True):
    if not shutil.which("systemctl"):
        raise UserError("systemctl is required for scheduling")
    try:
        return subprocess.run(
            ["systemctl", "--user", *arguments], text=True, capture_output=True, check=check, timeout=10
        )
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or error.stdout.strip() or "systemctl failed"
        raise UserError(message) from error


def schedule_paths(unit):
    return SYSTEMD_ROOT / f"{unit}.timer", SYSTEMD_ROOT / f"{unit}.service"


def remove_schedule(schedule_id, disable):
    if not re.fullmatch(r"[0-9a-f]{12}", schedule_id):
        raise UserError(f"invalid schedule id: {schedule_id}")
    records = schedules()
    record = next((item for item in records if item.get("id") == schedule_id), None)
    if not record:
        raise UserError(f"unknown schedule: {schedule_id}")
    timer, service = schedule_paths(f"firefox-sessions-{schedule_id}")
    if disable:
        systemctl("disable", "--now", timer.name, check=False)
    timer.unlink(missing_ok=True)
    service.unlink(missing_ok=True)
    save_schedules([item for item in records if item.get("id") != schedule_id])
    systemctl("daemon-reload")


def schedule_add(args):
    scheduled = parse_schedule_time(args.at)
    schedule_id = uuid.uuid4().hex[:12]
    unit = f"firefox-sessions-{schedule_id}"
    record = {
        "id": schedule_id,
        "at": scheduled.isoformat(timespec="seconds"),
        "action": args.action,
        "unit": unit,
    }
    timer, service = schedule_paths(unit)
    SYSTEMD_ROOT.mkdir(parents=True, exist_ok=True)
    command = f'"{unit_escape(sys.executable)}" "{unit_escape(str(Path(__file__).resolve()))}" _scheduled {schedule_id}'
    service.write_text(
        "[Unit]\n"
        f"Description=Firefox Sessions one-off {args.action}\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={command}\n"
    )
    timer.write_text(
        "[Unit]\n"
        f"Description=Firefox Sessions at {scheduled.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "[Timer]\n"
        f"OnCalendar={scheduled.strftime('%Y-%m-%d %H:%M:%S')}\n"
        "Persistent=true\n"
        "AccuracySec=1s\n"
        f"Unit={service.name}\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    with locked():
        save_schedules(schedules() + [record])
    try:
        systemctl("daemon-reload")
        systemctl("enable", "--now", timer.name)
    except UserError:
        timer.unlink(missing_ok=True)
        service.unlink(missing_ok=True)
        with locked():
            save_schedules([item for item in schedules() if item.get("id") != schedule_id])
        raise
    print_value(record if args.json else f"Scheduled {args.action} for {record['at']} ({schedule_id})", args.json)


def schedule_list(args):
    value = schedules()
    if args.json:
        print(json.dumps(value))
        return
    if not value:
        print("No scheduled actions")
        return
    for record in value:
        print(f"{record['id']}  {record['at']}  {record['action']}")


def schedule_cancel(args):
    with locked():
        remove_schedule(args.schedule_id, True)
    print(f"Cancelled {args.schedule_id}")


def scheduled_action(args):
    record = next((item for item in schedules() if item.get("id") == args.schedule_id), None)
    if not record:
        raise UserError(f"unknown schedule: {args.schedule_id}")
    try:
        if record["action"] == "stop":
            stop(argparse.Namespace())
        else:
            action_args = argparse.Namespace(count=None, url=None, workspaces=None, stagger_ms=150, json=False)
            if record["action"] == "relaunch":
                relaunch(action_args)
            else:
                launch(action_args)
    finally:
        with locked():
            remove_schedule(args.schedule_id, False)


def status(args):
    with locked():
        value = status_value(load_config(), live_state())
    if args.json:
        print(json.dumps(value))
    else:
        print(f"Running {value['running']} / {value['configured']}")
        print(f"URL: {value['url']}")
        print(f"Workspaces: {', '.join(value['workspaces'])}")
        print(f"Profiles: {value['profiles']}")


def parser():
    result = argparse.ArgumentParser(prog="firefox-sessions")
    commands = result.add_subparsers(dest="command", required=True)

    configure_parser = commands.add_parser("configure")
    add_configuration_options(configure_parser)
    configure_parser.set_defaults(handler=configure)

    for name, handler in (("launch", launch), ("relaunch", relaunch)):
        command = commands.add_parser(name)
        add_configuration_options(command)
        command.add_argument("--stagger-ms", type=int, default=150)
        command.add_argument("--json", action="store_true")
        command.set_defaults(handler=handler)

    status_parser = commands.add_parser("status")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(handler=status)
    commands.add_parser("stop").set_defaults(handler=stop)
    reset_parser = commands.add_parser("reset")
    reset_parser.add_argument("--yes", action="store_true")
    reset_parser.set_defaults(handler=reset)
    commands.add_parser("focus").set_defaults(handler=focus)
    commands.add_parser("next").set_defaults(handler=next_session)
    schedule_parser = commands.add_parser("schedule")
    schedule_commands = schedule_parser.add_subparsers(dest="schedule_command", required=True)
    schedule_add_parser = schedule_commands.add_parser("add")
    schedule_add_parser.add_argument("--at", required=True)
    schedule_add_parser.add_argument("--action", choices=["launch", "stop", "relaunch"], default="launch")
    schedule_add_parser.add_argument("--json", action="store_true")
    schedule_add_parser.set_defaults(handler=schedule_add)
    schedule_list_parser = schedule_commands.add_parser("list")
    schedule_list_parser.add_argument("--json", action="store_true")
    schedule_list_parser.set_defaults(handler=schedule_list)
    schedule_cancel_parser = schedule_commands.add_parser("cancel")
    schedule_cancel_parser.add_argument("schedule_id")
    schedule_cancel_parser.set_defaults(handler=schedule_cancel)
    scheduled_parser = commands.add_parser("_scheduled", help=argparse.SUPPRESS)
    scheduled_parser.add_argument("schedule_id")
    scheduled_parser.set_defaults(handler=scheduled_action)
    place_parser = commands.add_parser("_place", help=argparse.SUPPRESS)
    place_parser.add_argument("assignments")
    place_parser.set_defaults(handler=place)
    return result


def add_configuration_options(command):
    command.add_argument("--count", type=int)
    command.add_argument("--url")
    command.add_argument("--workspaces")


def main():
    try:
        args = parser().parse_args()
        if hasattr(args, "stagger_ms") and not 0 <= args.stagger_ms <= 10000:
            raise UserError("stagger must be between 0 and 10000 milliseconds")
        args.handler(args)
    except (UserError, ValueError, OSError) as error:
        print(f"firefox-sessions: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
