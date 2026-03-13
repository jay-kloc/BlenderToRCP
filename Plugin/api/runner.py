"""
BlenderToRCP headless API runner.

Designed to be invoked by Blender in background mode::

    blender --background [file.blend] --python -m Plugin.api.runner -- '{"command":"...","args":{...}}'

Or as a standalone script::

    blender --background [file.blend] --python /path/to/runner.py -- '{"command":"...","args":{...}}'

Prints a JSON result to stdout delimited by markers so the CLI bridge
can extract it from Blender's noisy startup output.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Ensure the repo root is on sys.path so ``from Plugin.…`` imports work
# when invoked via ``--python /absolute/path/to/runner.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

OUTPUT_MARKER = "---BLENDERTORCP_JSON---"


def _ensure_addon_loaded() -> None:
    """Enable the BlenderToRCP addon if it isn't already registered."""
    import bpy

    if hasattr(bpy.types.Scene, "blender_to_rcp_export_settings"):
        return
    for module_name in ("bl_ext.blender_local_addons.BlenderToRCP", "BlenderToRCP"):
        try:
            bpy.ops.preferences.addon_enable(module=module_name)
        except Exception:
            continue
        if hasattr(bpy.types.Scene, "blender_to_rcp_export_settings"):
            return


def _output(data: dict) -> None:
    """Print JSON result wrapped in markers so the bridge can parse it."""
    print(f"{OUTPUT_MARKER}{json.dumps(data)}{OUTPUT_MARKER}", flush=True)


def main() -> int:
    argv = sys.argv
    if "--" not in argv:
        _output({"ok": False, "error": "No request payload. Pass JSON after '--'."})
        return 1

    raw = argv[argv.index("--") + 1]
    try:
        request = json.loads(raw)
    except (json.JSONDecodeError, IndexError) as exc:
        _output({"ok": False, "error": f"Invalid JSON payload: {exc}"})
        return 1

    command = request.get("command")
    args = request.get("args", {})

    if not command:
        _output({"ok": False, "error": "Missing 'command' in request."})
        return 1

    # Commands that don't need blender scene loaded
    NO_BLEND_COMMANDS = {"version", "settings_list"}

    if command not in NO_BLEND_COMMANDS:
        _ensure_addon_loaded()

    try:
        from Plugin.api.commands import REGISTRY
    except Exception as exc:
        _output({"ok": False, "error": f"Failed to import command registry: {exc}"})
        traceback.print_exc()
        return 1

    handler = REGISTRY.get(command)
    if handler is None:
        _output({
            "ok": False,
            "error": f"Unknown command: '{command}'",
            "available": sorted(REGISTRY.keys()),
        })
        return 1

    try:
        result = handler(args)
        _output({"ok": True, "result": result})
        return 0
    except Exception as exc:
        _output({"ok": False, "error": str(exc)})
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
