#!/usr/bin/env python3
"""
Entry point for running BlenderToRCP as a CLI tool.

Usage::

    python3 /path/to/Plugin <command> [options]
    python3 -m Plugin.cli <command> [options]

This allows the installed Blender addon to double as a CLI tool
without any additional installation.
"""

import sys
from pathlib import Path

# When invoked as ``python3 /path/to/Plugin``, Python sets __name__ to
# "__main__" and the package isn't on sys.path.  Add the parent directory
# so ``from Plugin.cli…`` resolves correctly.
_plugin_dir = Path(__file__).resolve().parent
_parent = str(_plugin_dir.parent)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from Plugin.cli.__main__ import main  # noqa: E402

sys.exit(main())
