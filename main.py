#!/usr/bin/env python3
"""
Workspace Manager
Loads a named preset: opens apps on the right monitors, closes everything else.
Usage: uv run main.py [preset_name]
       defaults to 'deep_work' if no preset given
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

try:
    from AppKit import NSScreen
except ImportError:
    print("Missing dependency. Run: uv add pyobjc-framework-Cocoa")
    sys.exit(1)

# Apps that should never be closed (managed/resized instead)
PROTECTED = {"Finder", "SystemUIServer", "Dock", "NotificationCenter",
             "Control Center", "WindowServer", "Spotlight", "Alfred",
             "Cursor", "Terminal", "iTerm2", "iTerm"}

OBSIDIAN_APP_SUPPORT = Path.home() / "Library" / "Application Support" / "obsidian"


def load_presets():
    path = Path(__file__).parent / "presets.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def get_screens():
    """
    Returns dict of screen name -> (x1, y1, x2, y2) in AppleScript coordinates.
    AppKit uses bottom-left origin, AppleScript uses top-left — this converts between them.
    Uses the visible frame (excludes menu bar and dock).
    """
    primary_height = NSScreen.mainScreen().frame().size.height
    screens = {}

    for screen in NSScreen.screens():
        name = screen.localizedName()
        vis = screen.visibleFrame()

        x1 = int(vis.origin.x)
        y1 = int(primary_height - vis.origin.y - vis.size.height)
        x2 = int(x1 + vis.size.width)
        y2 = int(y1 + vis.size.height)

        screens[name] = (x1, y1, x2, y2)

    return screens


def match_screen(screens, keyword):
    """Find a screen by partial name match (case-insensitive)."""
    for name, bounds in screens.items():
        if keyword.lower() in name.lower():
            return name, bounds
    return None, None


def run_as(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True)


def is_running(app):
    result = run_as(f'tell application "System Events" to return exists (process "{app}")')
    return result.stdout.strip() == "true"


def quit_app(app):
    run_as(f'tell application "{app}" to quit')


def open_app(app):
    run_as(f'tell application "{app}" to activate')
    time.sleep(2.0)


def find_obsidian_vault_state():
    """Return the path to Obsidian's open vault window-state JSON file."""
    obsidian_json = OBSIDIAN_APP_SUPPORT / "obsidian.json"
    if not obsidian_json.exists():
        return None
    with open(obsidian_json) as f:
        data = json.load(f)
    # Prefer the vault marked as open
    for vault_id, info in data.get("vaults", {}).items():
        if info.get("open"):
            state_file = OBSIDIAN_APP_SUPPORT / f"{vault_id}.json"
            if state_file.exists():
                return state_file
    # Fallback: first vault with a state file
    for vault_id in data.get("vaults", {}):
        state_file = OBSIDIAN_APP_SUPPORT / f"{vault_id}.json"
        if state_file.exists():
            return state_file
    return None


def set_obsidian_bounds_via_file(bounds, workspace_file=None):
    """
    Position Obsidian by writing its Electron window-state file and restarting it.
    Obsidian doesn't expose windows via the Accessibility API, so this is the only
    reliable way to move it to a specific screen.
    Optionally writes a workspace layout file to control sidebar/tab state.
    """
    state_file = find_obsidian_vault_state()
    if not state_file:
        print("    Warning: could not find Obsidian vault state file — skipping bounds")
        return

    x1, y1, x2, y2 = bounds
    state = {
        "x": x1 + 50,
        "y": y1 + 50,
        "width": x2 - x1,
        "height": y2 - y1,
        "isMaximized": True,
        "devTools": False,
    }

    print("    (Obsidian needs restart to reposition — quitting and relaunching...)")
    quit_app("Obsidian")
    time.sleep(1.5)

    with open(state_file, "w") as f:
        json.dump(state, f)

    if workspace_file:
        workspace_src = Path(__file__).parent / workspace_file
        # Derive vault path from the same obsidian.json we already use
        obsidian_json = OBSIDIAN_APP_SUPPORT / "obsidian.json"
        vault_path = None
        if obsidian_json.exists():
            with open(obsidian_json) as f:
                data = json.load(f)
            for info in data.get("vaults", {}).values():
                if info.get("open"):
                    vault_path = Path(info["path"])
                    break
        if vault_path and workspace_src.exists():
            import shutil
            shutil.copy2(workspace_src, vault_path / ".obsidian" / "workspace.json")
        else:
            print(f"    Warning: could not write workspace file")

    open_app("Obsidian")


def set_window_bounds(app, bounds, config=None):
    x1, y1, x2, y2 = bounds
    width = x2 - x1
    height = y2 - y1
    # Use System Events (Accessibility API)
    run_as(f'tell application "{app}" to activate')

    # Wait for the window to actually appear (Electron apps can be slow)
    script_check = f"""
tell application "System Events"
    tell process "{app}"
        return count of windows
    end tell
end tell
"""
    for _ in range(4):
        result = run_as(script_check)
        try:
            if int(result.stdout.strip()) > 0:
                break
        except ValueError:
            pass
        time.sleep(0.5)
    else:
        # Obsidian doesn't expose windows via AX API — use file-based fallback
        if app == "Obsidian":
            workspace_file = config.get("obsidian_workspace") if config else None
            set_obsidian_bounds_via_file(bounds, workspace_file)
        else:
            print(f"    Warning: no window appeared for {app} after 2s — skipping bounds")
        return

    script = f"""
tell application "System Events"
    tell process "{app}"
        set frontmost to true
        set position of front window to {{{x1}, {y1}}}
        set size of front window to {{{width}, {height}}}
    end tell
end tell
"""
    result = run_as(script)
    if result.returncode != 0 and result.stderr.strip():
        print(f"    Warning: could not set bounds for {app}: {result.stderr.strip()}")


def get_running_apps():
    script = (
        'tell application "System Events" to get name of every application process '
        "whose background only is false"
    )
    result = run_as(script)
    if result.stdout.strip():
        return [a.strip() for a in result.stdout.strip().split(",")]
    return []


def close_all_except(keep):
    keep_set = set(keep) | PROTECTED
    for app in get_running_apps():
        if app not in keep_set:
            print(f"  Closing {app}...")
            quit_app(app)
    time.sleep(1)


def run_preset(name):
    presets = load_presets()
    preset = presets.get(name)

    if not preset:
        print(f"Unknown preset '{name}'. Available: {list(presets.keys())}")
        sys.exit(1)

    screens = get_screens()
    print(f"Detected screens: {list(screens.keys())}")

    # Close everything we don't need
    if preset.get("close_others"):
        keep = list(preset.get("open", {}).keys()) + preset.get("background", []) + ["Finder"]
        print("\nClosing other apps...")
        close_all_except(keep)

    # Start background apps (no window management)
    for app in preset.get("background", []):
        if not is_running(app):
            print(f"Starting {app} in background...")
            open_app(app)

    # Open and position apps on their screens
    for app, config in preset.get("open", {}).items():
        screen_keyword = config["screen"]
        matched_name, bounds = match_screen(screens, screen_keyword)

        if not bounds:
            print(f"  Warning: no screen found matching '{screen_keyword}' — opening without positioning")
            open_app(app)
            continue

        print(f"  Opening {app} on '{matched_name}'...")
        open_app(app)
        set_window_bounds(app, bounds, config)

    # Bring Cursor to front at the end
    run_as('tell application "Cursor" to activate')

    print(f"\nPreset '{name}' loaded.")


if __name__ == "__main__":
    preset_name = sys.argv[1] if len(sys.argv) > 1 else "deep_work"
    run_preset(preset_name)
