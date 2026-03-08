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
    """Exclude presets that are only used as automatic laptop fallbacks."""
    fallbacks = {
        p.get("laptop_fallback")
        for p in all_presets.values()
        if p.get("laptop_fallback")
    }
    return {name: data for name, data in all_presets.items() if name not in fallbacks}


class WorkspaceManagerApp(rumps.App):
    def __init__(self):
        super().__init__("⊞", quit_button="Quit")
        self._build_menu()

    def _build_menu(self):
        presets = visible_presets(load_presets())
        # Separate destructive presets (nuke/clear) from workspace presets
        workspace_presets = {n: d for n, d in presets.items() if not d.get("nuke") and not d.get("close_others", False) or d.get("open")}
        destructive_presets = {n: d for n, d in presets.items() if n not in workspace_presets}

        # Add workspace presets first (the ones you actually want to click)
        for name, _ in workspace_presets.items():
            display = name.replace("_", " ").title()
            self.menu.add(rumps.MenuItem(display, callback=self._make_handler(name, display)))

        # Separator before destructive presets
        if destructive_presets:
            self.menu.add(rumps.separator)
            for name, _ in destructive_presets.items():
                display = name.replace("_", " ").title()
                self.menu.add(rumps.MenuItem(display, callback=self._make_handler(name, display)))

    def _make_handler(self, preset_name, display_name):
        def handler(_):
            def run():
                # main.py now handles its own logging to LOG_FILE,
                # so we just need to run it and check the exit code.
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


if __name__ == "__main__":
    WorkspaceManagerApp().run()
