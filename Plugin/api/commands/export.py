"""export command — export scene to USD/USDZ."""

from __future__ import annotations

import os
import time
from pathlib import Path

from ._settings_common import INTERNAL_KEYS, get_settings, coerce_value


def handle(args: dict) -> dict:
    import bpy
    from Plugin.export import blender_usd_export, postprocess_usd, pack_usdz, diagnostics
    from Plugin.nodes import validate as rk_validate
    from Plugin import prefs as addon_prefs

    filepath = args.get("filepath")
    if not filepath:
        raise ValueError("'filepath' is required (output path).")

    settings = get_settings()

    # Apply overrides without persisting them
    overrides = args.get("overrides", {})
    prop_defs = {prop.identifier: prop for prop in settings.bl_rna.properties}
    for key, value in overrides.items():
        if key in INTERNAL_KEYS:
            continue
        prop = prop_defs.get(key)
        if prop is None:
            continue
        try:
            setattr(settings, key, coerce_value(prop, value))
        except Exception:
            pass

    # Apply format override
    fmt = args.get("format")
    if fmt:
        settings.export_format = fmt.upper()

    if args.get("selected_only"):
        settings.selected_objects_only = True

    # Enforce extension
    ext_map = {"USDA": ".usda", "USDC": ".usdc", "USDZ": ".usdz"}
    ext = ext_map.get(settings.export_format, ".usdz")
    filepath = str(Path(filepath).with_suffix(ext))
    settings.filepath = filepath

    no_diagnostics = args.get("no_diagnostics", False)

    # Validate materials (strict mode — same as the operator)
    materials = rk_validate.collect_scene_materials(bpy.context)
    for mat in materials:
        try:
            result = rk_validate.validate_material(mat, strict=True)
        except TypeError:
            result = rk_validate.validate_material(mat)
            if result.get("warnings"):
                result["errors"].extend(result["warnings"])
                result["warnings"] = []
            result["ok"] = not result["errors"]
        if result["errors"]:
            error_msgs = [
                f"{e.get('node_name', '?')} ({e.get('node_type', '?')}): {e.get('message', '')}"
                for e in result["errors"][:10]
            ]
            raise RuntimeError(
                f"Unsupported nodes in material '{mat.name}':\n" + "\n".join(error_msgs)
            )

    start_time = time.time()
    diag = diagnostics.ExportDiagnostics()

    # Step 1: Export from Blender to USD
    temp_usd_path = blender_usd_export.export_blender_scene(
        bpy.context, settings, filepath, diag
    )
    if not temp_usd_path or not os.path.exists(temp_usd_path):
        raise RuntimeError("Blender USD export failed.")

    # Step 2: Post-process (material rewrite)
    postprocess_usd.process_usd_stage(temp_usd_path, settings, bpy.context, diag)

    if diag.data.get("errors"):
        errors = diag.data["errors"][:5]
        raise RuntimeError(
            f"Post-processing errors ({len(diag.data['errors'])} total): "
            + "; ".join(str(e) for e in errors)
        )

    # Step 3: Package USDZ if needed
    if settings.export_format == "USDZ":
        pack_usdz.create_usdz(temp_usd_path, filepath, settings, bpy.context, diag)
    else:
        import shutil
        if temp_usd_path != filepath:
            shutil.move(temp_usd_path, filepath)

    duration = time.time() - start_time

    # Save diagnostics
    diagnostics_path = None
    if not no_diagnostics:
        prefs = addon_prefs.get_preferences(bpy.context)
        if prefs and prefs.enable_diagnostics:
            diag_path = Path(filepath).with_suffix(".diagnostics.json")
            diag.save(diag_path)
            diagnostics_path = str(diag_path)

    return {
        "ok": True,
        "export_path": filepath,
        "format": settings.export_format,
        "duration_seconds": round(duration, 2),
        "diagnostics_path": diagnostics_path,
    }
