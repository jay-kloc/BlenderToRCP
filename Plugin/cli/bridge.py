"""
Blender bridge — spawns ``blender --background`` and parses the JSON result.

All CLI commands go through this module. It handles:
- Locating the Blender binary
- Constructing the command line
- Extracting the JSON result from Blender's noisy stdout
- Error handling and timeouts
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

OUTPUT_MARKER = "---BLENDERTORCP_JSON---"
# runner.py is at Plugin/api/runner.py — one level up from cli/
RUNNER_PATH = str(Path(__file__).resolve().parent.parent / "api" / "runner.py")


def find_blender() -> str:
    """Resolve the Blender binary path.

    Priority:
    1. ``--blender`` CLI flag (handled by caller, passed as argument)
    2. ``BLENDERTORCP_BLENDER`` environment variable
    3. ``blender`` on PATH
    """
    env = os.environ.get("BLENDERTORCP_BLENDER")
    if env:
        return env
    return "blender"


def run(
    command: str,
    args: dict,
    blend_file: str | None = None,
    blender_path: str | None = None,
    timeout: int = 600,
    verbose: bool = False,
) -> dict:
    """Execute a command via ``blender --background`` and return the result dict.

    Parameters
    ----------
    command:
        The API command name (e.g. ``"export"``, ``"validate"``).
    args:
        Arguments dict passed to the command handler.
    blend_file:
        Optional ``.blend`` file to open before running.
    blender_path:
        Path to the Blender executable. If ``None`` uses :func:`find_blender`.
    timeout:
        Maximum seconds to wait for Blender to finish.
    verbose:
        If ``True``, Blender's stderr is printed to the terminal.

    Returns
    -------
    dict
        The ``result`` value from the API response on success.

    Raises
    ------
    RuntimeError
        On any failure (Blender not found, command error, timeout, etc.).
    """
    blender = blender_path or find_blender()
    payload = json.dumps({"command": command, "args": args})

    cmd: list[str] = [blender, "--background"]
    if blend_file:
        cmd.append(blend_file)
    cmd.extend(["--python", RUNNER_PATH, "--", payload])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            f"Blender not found at '{blender}'. "
            "Set BLENDERTORCP_BLENDER or use --blender <path>."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Blender timed out after {timeout}s.")

    if verbose:
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)

    return extract_result(proc.stdout or "", proc.stderr or "", proc.returncode, blender)


def extract_result(
    stdout: str,
    stderr: str,
    returncode: int,
    blender: str = "blender",
) -> dict:
    """Extract the JSON result from Blender's stdout.

    Split out from :func:`run` so it can be unit-tested without spawning
    a subprocess.

    Returns
    -------
    dict
        The ``result`` value from the API response on success.

    Raises
    ------
    RuntimeError
        On any failure (missing markers, invalid JSON, command error, etc.).
    """
    pattern = re.escape(OUTPUT_MARKER) + r"(.+?)" + re.escape(OUTPUT_MARKER)
    match = re.search(pattern, stdout, re.DOTALL)

    if not match:
        snippet = (stderr or stdout)[-500:]
        if returncode == 127:
            raise RuntimeError(
                f"Blender not found at '{blender}'. "
                "Set BLENDERTORCP_BLENDER or use --blender <path>."
            )
        raise RuntimeError(
            f"No output from Blender (exit code {returncode}). "
            f"Last output:\n{snippet}"
        )

    try:
        response = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse Blender output: {exc}")

    if not response.get("ok"):
        error = response.get("error", "Unknown error")
        raise RuntimeError(error)

    return response["result"]
