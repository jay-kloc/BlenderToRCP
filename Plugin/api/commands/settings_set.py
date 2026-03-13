"""settings_set command — modify export settings in a .blend file."""

from __future__ import annotations

from ._settings_common import INTERNAL_KEYS, get_settings, coerce_value


def handle(args: dict) -> dict:
    settings_dict = args.get("settings", {})
    save = args.get("save", False)
    dry_run = args.get("dry_run", False)

    if not settings_dict:
        raise ValueError("No settings provided. Pass 'settings': {'key': value, ...}")

    settings = get_settings()
    prop_defs = {prop.identifier: prop for prop in settings.bl_rna.properties}

    # Validate all keys and values first
    to_apply = []
    for key, value in settings_dict.items():
        if key in INTERNAL_KEYS:
            raise ValueError(f"Cannot set internal key: '{key}'")
        prop = prop_defs.get(key)
        if prop is None:
            raise ValueError(f"Unknown setting key: '{key}'")
        coerced = coerce_value(prop, value)
        to_apply.append((key, coerced))

    if dry_run:
        return {
            "valid": True,
            "would_update": [k for k, _ in to_apply],
        }

    updated = []
    for key, value in to_apply:
        try:
            setattr(settings, key, value)
            updated.append(key)
        except Exception as exc:
            raise ValueError(f"Failed to set '{key}': {exc}") from exc

    saved = False
    if save:
        import bpy
        if bpy.data.filepath:
            bpy.ops.wm.save_mainfile()
            saved = True

    return {"updated": updated, "saved": saved}
