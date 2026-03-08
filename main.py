#!/usr/bin/env python3
"""
Workspace Manager
Loads a named preset: opens apps on the right monitors, closes everything else.
Usage: uv run main.py [preset_name]
       defaults to 'deep_work' if no preset given
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

LOG_FILE = Path(__file__).parent / "workspace-manager.log"

# Set up logging to both file and stdout
log = logging.getLogger("workspace-manager")
log.setLevel(logging.DEBUG)
_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

_fh = logging.FileHandler(LOG_FILE)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_formatter)
log.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(_sh)

try:
    from AppKit import NSScreen
except ImportError:
    log.error("Missing dependency. Run: uv add pyobjc-framework-Cocoa")
    sys.exit(1)

# Apps that should never be closed (managed/resized instead)
PROTECTED = {"Finder", "SystemUIServer", "Dock", "NotificationCenter",
             "Control Center", "WindowServer", "Spotlight", "Alfred",
             "Cursor", "Terminal", "iTerm2", "iTerm",
             "macOS InstantView"}

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
    log.debug(f"osascript: {script.strip()[:120]}")
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    if result.returncode != 0 and result.stderr.strip():
        log.debug(f"osascript failed (rc={result.returncode}): {result.stderr.strip()}")
    return result


def is_running(app):
    result = run_as(f'tell application "System Events" to return exists (process "{app}")')
    return result.stdout.strip() == "true"


def quit_app(app, force=False):
    if force:
        log.info(f"  Force-quitting '{app}'")
        # Use killall which matches by process name — more reliable than AppleScript
        subprocess.run(["killall", "-9", app], capture_output=True, text=True)
        return
    log.info(f"  Quitting '{app}'")
    result = run_as(f'tell application "{app}" to quit')
    if result.returncode != 0 and result.stderr.strip():
        log.warning(f"quit_app('{app}') failed: {result.stderr.strip()}")


def open_app(app):
    """Launch an app."""
    app_path = f"/Applications/{app}.app"
    target = [app_path] if os.path.isdir(app_path) else ["-a", app]

    log.info(f"  Launching '{app}'...")
    subprocess.run(["open"] + target, capture_output=True, text=True)
    time.sleep(1.0)
    run_as(f'tell application "{app}" to activate')
    time.sleep(2.0)
    log.debug(f"  '{app}' open done")


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
        log.warning("Could not find Obsidian vault state file — skipping bounds")
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

    log.info("Obsidian needs restart to reposition — quitting and relaunching...")
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
            log.warning("Could not write workspace file")

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
            log.warning(f"No window appeared for {app} after 2s — skipping bounds")
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
        log.warning(f"Could not set bounds for {app}: {result.stderr.strip()}")


def get_running_apps(include_background=False):
    if include_background:
        script = (
            'tell application "System Events" to get name of every application process'
        )
    else:
        script = (
            'tell application "System Events" to get name of every application process '
            "whose background only is false"
        )
    result = run_as(script)
    apps = []
    if result.stdout.strip():
        apps = [a.strip() for a in result.stdout.strip().split(",")]
    log.debug(f"get_running_apps(include_background={include_background}): {apps}")
    return apps


# Processes that should never be closed under any circumstances.
# Includes macOS system daemons, this app's own processes, and helpers for protected apps.
SYSTEM_ONLY = {
    # macOS core
    "Finder", "Dock", "SystemUIServer", "NotificationCenter", "WindowServer",
    "Spotlight", "loginwindow", "WindowManager", "WallpaperAgent",
    "ControlCenter", "Control Center", "ControlStrip",
    "System Events", "com.apple.dock.extra",
    # macOS agents / daemons
    "AirPlayUIAgent", "CoreLocationAgent", "CoreServicesUIAgent",
    "TextInputMenuAgent", "WiFiAgent", "UniversalControl",
    "UIKitSystem", "Siri", "SiriNCService",
    "universalAccessAuthWarn", "universalaccessd",
    "Keychain Circle Notification", "chronod", "familycircled", "studentd",
    "AppSSODaemon", "EmojiFunctionRowIM_Extension", "PAH_Extension",
    "ThemeWidgetControlViewService", "ThumbnailExtension_macOS",
    "QuickLookUIService", "ViewBridgeAuxiliary", "CursorUIViewService",
    # This app + its runtime
    "Python", "Workspace Manager", "osascript", "node",
    # macOS InstantView (external display driver)
    "macOS InstantView",
}


def _is_protected(app, extra_keep=None):
    """Check if an app should be kept alive (exact match or helper of a protected app)."""
    all_keep = PROTECTED | SYSTEM_ONLY | (extra_keep or set())
    if app in all_keep:
        return True
    # Protect helper processes for kept/protected apps (e.g. "Cursor Helper (Plugin)")
    for parent in PROTECTED | (extra_keep or set()):
        if app.startswith(parent + " "):
            return True
    return False


def close_all_except(keep):
    keep_set = set(keep)
    # Close foreground apps that aren't needed
    for app in get_running_apps():
        if _is_protected(app, keep_set):
            log.debug(f"Keeping {app}")
        else:
            log.info(f"  Closing {app}...")
            quit_app(app)
    # Close background apps — but only ones explicitly NOT in the keep list.
    # Skip anything that looks like a system daemon or helper for a protected app.
    for app in get_running_apps(include_background=True):
        if _is_protected(app, keep_set):
            log.debug(f"Keeping background app {app}")
        elif is_running(app):
            log.info(f"  Closing background app {app}...")
            quit_app(app)
    time.sleep(1)


# Nuke mode: only protect macOS system daemons and this app's own processes.
# Everything else (Cursor, Terminal, Finder, Alfred, etc.) gets closed.
NUKE_PROTECTED = {
    # macOS core — killing these causes logout or visual breakage
    "Finder", "Dock", "SystemUIServer", "NotificationCenter", "WindowServer",
    "Spotlight", "loginwindow", "WindowManager", "WallpaperAgent",
    "ControlCenter", "Control Center", "ControlStrip",
    "System Events", "com.apple.dock.extra",
    # macOS agents / daemons
    "AirPlayUIAgent", "CoreLocationAgent", "CoreServicesUIAgent",
    "TextInputMenuAgent", "WiFiAgent", "UniversalControl",
    "UIKitSystem", "Siri", "SiriNCService",
    "universalAccessAuthWarn", "universalaccessd",
    "Keychain Circle Notification", "chronod", "familycircled", "studentd",
    "AppSSODaemon", "EmojiFunctionRowIM_Extension", "PAH_Extension",
    "ThemeWidgetControlViewService", "ThumbnailExtension_macOS",
    "QuickLookUIService", "ViewBridgeAuxiliary", "CursorUIViewService",
    # This app's own processes
    "Python", "Workspace Manager", "osascript",
    # External display driver
    "macOS InstantView",
}


def _is_nuke_protected(app):
    """For nuke mode: only protect system daemons and this app."""
    if app in NUKE_PROTECTED:
        return True
    # Protect helper processes for nuke-protected apps only
    for parent in NUKE_PROTECTED:
        if app.startswith(parent + " "):
            return True
    return False


def nuke_all():
    # Pass 1: graceful quit for all foreground apps
    for app in get_running_apps():
        if _is_nuke_protected(app):
            log.debug(f"Nuke-skipping: {app}")
        else:
            quit_app(app)

    # Pass 2: graceful quit for non-system background apps
    for app in get_running_apps(include_background=True):
        if _is_nuke_protected(app):
            log.debug(f"Nuke-skipping background: {app}")
        elif is_running(app):
            quit_app(app)

    # Give apps a moment to close gracefully
    time.sleep(2)

    # Pass 3: force-quit anything that survived
    survivors = []
    for app in get_running_apps():
        if not _is_nuke_protected(app):
            survivors.append(app)
    for app in get_running_apps(include_background=True):
        if not _is_nuke_protected(app) and app not in survivors and is_running(app):
            survivors.append(app)

    if survivors:
        log.info(f"Force-quitting {len(survivors)} stubborn app(s): {survivors}")
        for app in survivors:
            quit_app(app, force=True)
        time.sleep(1)

        # Final check
        still_alive = [
            app for app in get_running_apps()
            if not _is_nuke_protected(app)
        ]
        if still_alive:
            log.warning(f"Still running after force-quit: {still_alive}")
        else:
            log.info("All non-protected apps closed successfully.")
    else:
        log.info("All non-protected apps closed successfully.")


def run_preset(name):
    presets = load_presets()
    preset = presets.get(name)

    if not preset:
        log.error(f"Unknown preset '{name}'. Available: {list(presets.keys())}")
        sys.exit(1)

    if preset.get("nuke"):
        log.info("Nuking all apps...")
        log.debug(f"SYSTEM_ONLY = {SYSTEM_ONLY}")
        nuke_all()
        log.info("Done.")
        return

    screens = get_screens()
    log.info(f"Detected screens: {list(screens.keys())}")

    # Auto-switch to laptop_fallback if any required screen isn't connected
    fallback = preset.get("laptop_fallback")
    if fallback:
        missing = any(
            not match_screen(screens, cfg["screen"])[0]
            for cfg in preset.get("open", {}).values()
            if "screen" in cfg
        )
        if missing:
            log.info(f"External screens not found — switching to '{fallback}' preset")
            name = fallback
            preset = presets.get(name)
            if not preset:
                log.error(f"Fallback preset '{fallback}' not found in presets.yaml")
                sys.exit(1)

    # Nuke everything first if requested (aggressive clean slate)
    if preset.get("nuke_first"):
        log.info("Nuking all apps before loading preset...")
        nuke_all()
    # Close everything we don't need
    elif preset.get("close_others"):
        keep = list(preset.get("open", {}).keys()) + preset.get("background", []) + ["Finder"]
        log.info("Closing other apps...")
        close_all_except(keep)

    # Start background apps (no window management)
    for app in preset.get("background", []):
        if not is_running(app):
            log.info(f"Starting {app} in background...")
            open_app(app)

    # Open and position apps on their screens
    for app, config in preset.get("open", {}).items():
        screen_keyword = config.get("screen")

        if not screen_keyword:
            open_app(app)
            continue

        matched_name, bounds = match_screen(screens, screen_keyword)

        if not bounds:
            log.warning(f"No screen found matching '{screen_keyword}' — opening without positioning")
            open_app(app)
            continue

        log.info(f"  Opening {app} on '{matched_name}'...")
        open_app(app)
        set_window_bounds(app, bounds, config)

    # Bring Cursor to front at the end
    run_as('tell application "Cursor" to activate')

    log.info(f"Preset '{name}' loaded.")


if __name__ == "__main__":
    preset_name = sys.argv[1] if len(sys.argv) > 1 else "deep_work"
    try:
        log.info(f"=== Starting preset '{preset_name}' ===")
        run_preset(preset_name)
    except Exception:
        log.exception("Unhandled exception in workspace manager")
        sys.exit(1)
