---
name: "blendertorcp-setup"
description: "Use when a user wants to set up the BlenderToRCP CLI tool; locate the Blender executable and plugin install path, verify connectivity, and configure a shell alias. Also use to troubleshoot CLI errors like 'Blender not found' or 'Plugin not loaded'."
---

# BlenderToRCP CLI Setup

Configure the BlenderToRCP CLI so the agent can export scenes, bake textures, validate materials, and manage settings from the terminal.

## Prerequisites

- Blender 5.0+ installed
- BlenderToRCP addon installed and enabled in Blender's preferences
- Python 3.10+ available as `python3`

## Inputs

- `blender-path` (optional): explicit path to the Blender binary

## Workflow

### 1. Locate the Blender binary

If the user supplied a path, verify it exists. Otherwise probe common locations:

```bash
# macOS
test -x /Applications/Blender.app/Contents/MacOS/Blender && echo "found"

# Linux
command -v blender >/dev/null 2>&1 && echo "found"
which blender
```

If nothing is found, ask the user for the path before proceeding.

### 2. Locate the plugin install directory

The addon ships the CLI inside its `Plugin/` directory. Check the Blender extensions path:

```bash
# macOS
find ~/Library/Application\ Support/Blender -path "*/BlenderToRCP/Plugin/cli/__main__.py" 2>/dev/null

# Linux
find ~/.config/blender -path "*/BlenderToRCP/Plugin/cli/__main__.py" 2>/dev/null
```

For development installs, the `Plugin/` directory is at the repository root.

Verify the install by confirming both `Plugin/api/runner.py` and `Plugin/cli/__main__.py` exist.

### 3. Test the connection

Run a version check to confirm Blender, Python, and the addon are all wired up:

```bash
BLENDERTORCP_BLENDER=/path/to/blender python3 /path/to/Plugin version
# Or pass --blender directly:
python3 /path/to/Plugin --blender /path/to/blender version
```

Expected output — JSON with `plugin`, `blender`, and `python` keys. If this fails:

| Error | Exit Code | Cause | Fix |
|-------|-----------|-------|-----|
| `Blender not found` | 2 | Wrong binary path | Correct `BLENDERTORCP_BLENDER` or use `--blender <path>` |
| `No output from Blender` | 1 | Blender crashed on startup | Re-run with `--verbose` and inspect stderr |
| `Failed to import command registry` | 3 | Plugin path is wrong, addon not enabled, or files are missing | Enable BlenderToRCP in Blender preferences and re-check the install path |

### 4. Configure the shell

Add to the user's shell profile (`~/.zshrc`, `~/.bashrc`, or equivalent):

```bash
export BLENDERTORCP_BLENDER="/path/to/blender"
alias blendertorcp="python3 /path/to/Plugin"
```

After sourcing the profile, confirm the alias works:

```bash
blendertorcp version
```

### 5. Report result

Print the resolved paths and confirm the setup is complete:
- Blender binary path
- Plugin directory path
- Shell alias configured (yes/no)
- CLI version output
