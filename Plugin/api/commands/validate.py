"""validate command — check materials for RealityKit compatibility."""

from __future__ import annotations


def handle(args: dict) -> dict:
    import bpy
    from Plugin.nodes import validate as rk_validate

    material_name = args.get("material")
    strict = args.get("strict", False)
    only_errors = args.get("only_errors", False)

    if material_name:
        mat = bpy.data.materials.get(material_name)
        if mat is None:
            raise ValueError(f"Material not found: '{material_name}'")
        materials = [mat]
    else:
        materials = rk_validate.collect_scene_materials(bpy.context)

    results = []
    total_errors = 0
    total_warnings = 0

    for mat in materials:
        result = rk_validate.validate_material(mat, strict=strict)
        entry = {
            "name": result["material"],
            "ok": result["ok"],
            "errors": [
                {
                    "node_name": e.get("node_name", ""),
                    "node_type": e.get("node_type", ""),
                    "message": e.get("message", ""),
                }
                for e in result["errors"]
            ],
        }
        if not only_errors:
            entry["warnings"] = [
                {
                    "node_name": w.get("node_name", ""),
                    "node_type": w.get("node_type", ""),
                    "message": w.get("message", ""),
                }
                for w in result["warnings"]
            ]
            total_warnings += len(result["warnings"])
        total_errors += len(result["errors"])
        results.append(entry)

    all_ok = total_errors == 0
    summary = {
        "ok": all_ok,
        "error_count": total_errors,
        "materials": results,
    }
    if not only_errors:
        summary["warning_count"] = total_warnings
    return summary
