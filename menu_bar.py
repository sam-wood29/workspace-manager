#!/usr/bin/env python3
"""
Workspace Manager — menu bar launcher.
Reads presets from presets.yaml and shows them as clickable menu items.
Laptop fallback presets are hidden (they run automatically via main.py).
"""

import threading
import subprocess
from pathlib import Path

import rumps
import yaml

SCRIPT_DIR = Path(__file__).parent
UV_BIN = Path.home() / ".local" / "bin" / "uv"
LOG_FILE = SCRIPT_DIR / "workspace-manager.log"


def load_presets():
    with open(SCRIPT_DIR / "presets.yaml") as f:
        return yaml.safe_load(f)


def visible_presets(all_presets):
    """Exclude presets that are only used as automatic laptop fallbacks, and the actions block."""
    fallbacks = {
        p.get("laptop_fallback")
        for p in all_presets.values()
        if isinstance(p, dict) and p.get("laptop_fallback")
    }
    return {
        name: data
        for name, data in all_presets.items()
        if name not in fallbacks and name != "actions"
    }


def _section_header(title):
    """Return a disabled MenuItem styled as a section label."""
    item = rumps.MenuItem(title)
    item.set_callback(None)
    return item


class WorkspaceManagerApp(rumps.App):
    def __init__(self):
        super().__init__("⊞", quit_button="Quit")
        self._build_menu()

    def _build_menu(self):
        all_data = load_presets()
        presets = visible_presets(all_data)
        actions = all_data.get("actions", {})

        # Separate workspace presets from destructive ones (nuke/clear)
        workspace_presets = {
            n: d for n, d in presets.items()
            if not d.get("nuke") and not d.get("close_others", False) or d.get("open")
        }
        destructive_presets = {n: d for n, d in presets.items() if n not in workspace_presets}

        # --- WORKSPACES section ---
        self.menu.add(_section_header("WORKSPACES"))
        self.menu.add(rumps.separator)
        for name, _ in workspace_presets.items():
            display = name.replace("_", " ").title()
            self.menu.add(rumps.MenuItem(display, callback=self._make_preset_handler(name, display)))

        if destructive_presets:
            self.menu.add(rumps.separator)
            for name, _ in destructive_presets.items():
                display = name.replace("_", " ").title()
                self.menu.add(rumps.MenuItem(display, callback=self._make_preset_handler(name, display)))

        # --- ACTIONS section ---
        if actions:
            self.menu.add(rumps.separator)
            self.menu.add(_section_header("ACTIONS"))
            self.menu.add(rumps.separator)
            for name, cfg in actions.items():
                label = cfg.get("label") or name.replace("_", " ").title()
                self.menu.add(rumps.MenuItem(label, callback=self._make_action_handler(name, label)))

    def _make_preset_handler(self, preset_name, display_name):
        def handler(_):
            def run():
                try:
                    result = subprocess.run(
                        [str(UV_BIN), "run", "main.py", preset_name],
                        cwd=SCRIPT_DIR,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode == 0:
                        rumps.notification("Workspace Manager", "", f"{display_name} loaded")
                    else:
                        msg = result.stderr.strip().split("\n")[-1] if result.stderr.strip() else "Something went wrong"
                        rumps.notification("Workspace Manager", "Error", msg)
                except subprocess.TimeoutExpired:
                    rumps.notification("Workspace Manager", "Error", f"{display_name} timed out after 2 minutes")

            threading.Thread(target=run, daemon=True).start()

        return handler

    def _make_action_handler(self, action_name, display_name):
        def handler(_):
            def run():
                try:
                    result = subprocess.run(
                        [str(UV_BIN), "run", "main.py", "--action", action_name],
                        cwd=SCRIPT_DIR,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode != 0:
                        msg = result.stderr.strip().split("\n")[-1] if result.stderr.strip() else "Something went wrong"
                        rumps.notification("Workspace Manager", "Error", msg)
                except subprocess.TimeoutExpired:
                    rumps.notification("Workspace Manager", "Error", f"{display_name} timed out")

            threading.Thread(target=run, daemon=True).start()

        return handler


if __name__ == "__main__":
    WorkspaceManagerApp().run()
