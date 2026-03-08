# Workspace Manager

macOS workspace switcher that loads named presets — opens apps on the right monitors and closes everything else.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Your Mac must have **Accessibility** permissions granted to Terminal (or whatever runs the script) in System Settings > Privacy & Security.

## Usage

```bash
uv run main.py [preset_name]
```

Defaults to `deep_work` if no preset is given.

### Built-in presets

| Preset | What it does |
|---|---|
| `deep_work` | Nukes everything, opens Cursor + Terminal on Dell, Obsidian on HP, Wispr Flow in background. Falls back to `laptop` if external screens aren't connected. |
| `laptop` | Closes other apps, opens Cursor + Terminal + Obsidian on built-in display. |
| `nuke` | Closes all non-system apps. |
| `clear` | Closes non-protected apps (keeps Cursor, Terminal, etc.). |

## Presets

Defined in `presets.yaml`. Each preset can specify:

- **`open`** — apps to launch, each with a `screen` keyword for monitor placement
- **`background`** — apps to launch without window management
- **`close_others`** / **`nuke_first`** — whether to close other apps before loading
- **`laptop_fallback`** — preset to use when external monitors aren't connected

## How it works

- Detects connected monitors via `NSScreen` (pyobjc) and converts coordinates from AppKit's bottom-left origin to AppleScript's top-left origin
- Opens/closes apps via `osascript` (AppleScript)
- Positions windows using the macOS Accessibility API (`System Events`)
- Obsidian gets special handling — its Electron window state file is written directly since it doesn't expose windows via the Accessibility API
