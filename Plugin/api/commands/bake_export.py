"""bake_export command — bake textures and export scene.

This runs synchronously inside background Blender (blocking).
The CLI invocation already runs Blender in the background so the caller
(the bridge) can handle timeouts externally.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from ._settings_common import INTERNAL_KEYS, get_settings, coerce_value


def handle(args: dict) -> dict:
    import bpy
    from Plugin.export import (
        bake_textures,
        blender_usd_export,
        postprocess_usd,
        pack_usdz,
        diagnostics,
    )
    from Plugin.nodes import validate as rk_validate
    from Plugin.ops import bake_export_operator as bake_ops
    from Plugin import prefs as addon_prefs

    filepath = args.get("filepath")
    if not filepath:
        raise ValueError("'filepath' is required (output path).")

    settings = get_settings()

    # Apply overrides
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

    # Apply direct args as setting overrides
    _DIRECT_OVERRIDES = {
        "format": "export_format",
        "bake_mode": "bake_mode",
        "resolution": None,  # handled specially
        "image_format": "bake_image_format",
        "margin": "bake_margin",
        "ibl_source": "bake_ibl_source",
        "ibl_filepath": "bake_ibl_filepath",
        "ibl_strength": "bake_ibl_strength",
        "ibl_rotation": "bake_ibl_rotation",
        "isolate_meshes": "bake_isolate_meshes_lit",
        "timeout": "bake_step_timeout_seconds",
    }
    for arg_key, setting_key in _DIRECT_OVERRIDES.items():
        if arg_key in args and setting_key is not None:
            prop = prop_defs.get(setting_key)
            if prop:
                try:
                    setattr(settings, setting_key, coerce_value(prop, args[arg_key]))
                except Exception:
                    pass

    # Handle resolution: could be a preset or custom int
    if "resolution" in args:
        res = args["resolution"]
        res_str = str(res)
        if res_str in ("512", "1024", "2048", "4096"):
            settings.bake_resolution = res_str
        else:
            settings.bake_resolution = "CUSTOM"
            settings.bake_resolution_custom = int(res)

    if args.get("selected_only"):
        settings.selected_objects_only = True
    if args.get("no_base_color"):
        settings.bake_base_color = False
    if args.get("no_opacity"):
        settings.bake_opacity = False
    if args.get("keep_materials"):
        settings.bake_keep_materials = True

    # Set format
    if "format" in args:
        settings.export_format = args["format"].upper()

    # Enforce extension
    ext_map = {"USDA": ".usda", "USDC": ".usdc", "USDZ": ".usdz"}
    ext = ext_map.get(settings.export_format, ".usdz")
    filepath = str(Path(filepath).with_suffix(ext))
    settings.filepath = filepath

    no_diagnostics = args.get("no_diagnostics", False)

    # Collect objects
    objects_to_export = bake_ops._collect_export_objects(bpy.context, settings)
    if not objects_to_export:
        raise RuntimeError("No exportable objects found.")

    # Save originals for cleanup
    original_selection = list(bpy.context.selected_objects)
    original_active = bpy.context.view_layer.objects.active
    original_mode = original_active.mode if original_active else "OBJECT"
    original_engine = bpy.context.scene.render.engine
    original_force_unlit = getattr(settings, "force_unlit_materials", False)

    bake_result = None
    diag = diagnostics.ExportDiagnostics()
    start_time = time.time()

    try:
        bake_ops._ensure_object_mode(bpy.context)
        bake_ops._set_render_engine(bpy.context.scene, "CYCLES")

        if settings.export_format == "USDZ":
            texture_dir = blender_usd_export.get_usdz_staging_dir(filepath) / "textures"
        else:
            texture_dir = Path(filepath).parent / "textures"

        # Bake
        bake_result = bake_textures.bake_materials_for_objects(
            bpy.context, settings, objects_to_export, texture_dir, diag
        )

        # Bake & Export always forces Unlit
        settings.force_unlit_materials = True

        if getattr(settings, "selected_objects_only", False):
            bake_ops._set_selection(bpy.context, objects_to_export)

        # Validate post-bake
        materials = bake_ops._collect_materials_from_objects(objects_to_export)
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
                    f"Unsupported nodes in material '{mat.name}' after baking:\n"
                    + "\n".join(error_msgs)
                )

        # Export
        temp_usd_path = blender_usd_export.export_blender_scene(
            bpy.context, settings, filepath, diag
        )
        if not temp_usd_path or not Path(temp_usd_path).exists():
            raise RuntimeError("Blender USD export failed.")

        # Post-process
        postprocess_usd.process_usd_stage(
            temp_usd_path, settings, bpy.context, diag
        )

        if diag.data.get("errors"):
            errors = diag.data["errors"][:5]
            raise RuntimeError(
                f"Post-processing errors ({len(diag.data['errors'])} total): "
                + "; ".join(str(e) for e in errors)
            )

        # Package
        if settings.export_format == "USDZ":
            pack_usdz.create_usdz(
                temp_usd_path, filepath, settings, bpy.context, diag
            )
        else:
            import shutil
            if temp_usd_path != filepath:
                shutil.move(temp_usd_path, filepath)

        duration = time.time() - start_time

        # Diagnostics
        diagnostics_path = None
        if not no_diagnostics:
            prefs = addon_prefs.get_preferences(bpy.context)
            if prefs and prefs.enable_diagnostics:
                diag_path = Path(filepath).with_suffix(".diagnostics.json")
                diag.save(diag_path)
                diagnostics_path = str(diag_path)

        # Bake stats
        bake_stats = {
            "objects_baked": len(objects_to_export),
            "resolution": (
                settings.bake_resolution_custom
                if settings.bake_resolution == "CUSTOM"
                else int(settings.bake_resolution)
            ),
            "image_format": settings.bake_image_format,
        }

        return {
            "ok": True,
            "export_path": filepath,
            "format": settings.export_format,
            "duration_seconds": round(duration, 2),
            "bake_stats": bake_stats,
            "diagnostics_path": diagnostics_path,
        }

    finally:
        settings.force_unlit_materials = original_force_unlit
        try:
            bpy.context.scene.render.engine = original_engine
        except Exception:
            pass
        if bake_result is not None:
            bake_textures.restore_baked_materials(
                bake_result,
                bool(getattr(settings, "bake_keep_materials", False)),
            )
        bake_ops._restore_selection(bpy.context, original_selection, original_active)
        bake_ops._restore_mode(bpy.context, original_active, original_mode)
