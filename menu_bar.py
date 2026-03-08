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
        for name, _ in presets.items():
            display = name.replace("_", " ").title()
            self.menu.add(rumps.MenuItem(display, callback=self._make_handler(name, display)))

    def _make_handler(self, preset_name, display_name):
        def handler(_):
            def run():
                result = subprocess.run(
                    ["uv", "run", "main.py", preset_name],
                    cwd=SCRIPT_DIR,
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    rumps.notification("Workspace Manager", "", f"{display_name} loaded")
                else:
                    msg = result.stderr.strip() or "Something went wrong"
                    rumps.notification("Workspace Manager", "Error", msg)

            threading.Thread(target=run, daemon=True).start()

        return handler


if __name__ == "__main__":
    WorkspaceManagerApp().run()
