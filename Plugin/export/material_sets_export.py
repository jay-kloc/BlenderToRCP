"""
Export Material Sets as a JSON manifest.

Packs separate occlusion / roughness / metallic images into a single
ORM texture, then writes ``material_sets.json`` alongside the exported
USD with texture filenames relative to ``textures/``.

After the JSON is written, ``rebuild_materials_from_sets`` regenerates
each slot's material ``.usda`` using the first set's textures so the
default materials are consistent with the sets.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .pbr_texture_packing import _read_single_channel, _write_orm_png
from .usd_utils import Usd, UsdShade, Sdf, require_pxr


def export_material_sets(
    stage,
    usd_path: str,
    settings,
    context,
    diagnostics=None,
) -> None:
    """Write ``material_sets.json`` next to the exported USD."""
    usd_dir = Path(usd_path).parent
    textures_dir = usd_dir / "textures"

    manifest = _collect_manifest(context, textures_dir, diagnostics)
    if not manifest:
        return

    textures_dir.mkdir(exist_ok=True)

    out_path = usd_dir / "material_sets.json"
    try:
        out_path.write_text(json.dumps(manifest, indent=4, ensure_ascii=False))
    except Exception as exc:
        if diagnostics:
            diagnostics.add_warning(f"Failed to write material_sets.json: {exc}")


def _collect_manifest(
    context,
    textures_dir: Path,
    diagnostics,
) -> Optional[Dict[str, Any]]:
    """Build the JSON structure from all objects' material sets."""
    slot_entries: List[Dict[str, Any]] = []

    orm_resolution = 1024  # default ORM resolution

    for obj in context.scene.objects:
        collection = getattr(obj, "blendertorcp_material_sets", None)
        if not collection or not collection.slots:
            continue

        for slot_sets in collection.slots:
            if not slot_sets.slot_name or not slot_sets.sets:
                continue

            sets_list: List[Dict[str, Any]] = []
            for mat_set in slot_sets.sets:
                normal_name = _stage_image(mat_set.normal, textures_dir, diagnostics)

                orm_name = _pack_orm(
                    mat_set.name,
                    mat_set.occlusion,
                    mat_set.roughness,
                    mat_set.metallic,
                    textures_dir,
                    orm_resolution,
                    diagnostics,
                )

                diffuse_names: List[str] = []
                for diff in mat_set.diffuses:
                    name = _stage_image(diff.image, textures_dir, diagnostics)
                    if name:
                        diffuse_names.append(name)

                sets_list.append({
                    "name": mat_set.name,
                    "normal": normal_name or "",
                    "orm": orm_name or "",
                    "diffuses": diffuse_names,
                })

            slot_entries.append({
                "slot_name": slot_sets.slot_name,
                "material_sets": sets_list,
            })

    if not slot_entries:
        return None

    return {"material_slots": slot_entries}


# ------------------------------------------------------------------
# ORM packing
# ------------------------------------------------------------------

def _pack_orm(
    set_name: str,
    occlusion_image,
    roughness_image,
    metallic_image,
    textures_dir: Path,
    resolution: int,
    diagnostics,
    ao_fallback: float = 1.0,
    rough_fallback: float = 0.5,
    metal_fallback: float = 0.0,
) -> Optional[str]:
    """Pack O/R/M into a single PNG and return the filename.

    When no texture is provided for a channel, the corresponding
    fallback float value is used to fill the entire channel.
    """
    ao_path = _resolve_image_path(occlusion_image)
    rough_path = _resolve_image_path(roughness_image)
    metal_path = _resolve_image_path(metallic_image)

    width = height = resolution

    ao_pixels = _read_single_channel(ao_path, "r", width, height, default_value=ao_fallback)
    rough_pixels = _read_single_channel(rough_path, "r", width, height, default_value=rough_fallback)
    metal_pixels = _read_single_channel(metal_path, "r", width, height, default_value=metal_fallback)

    if ao_pixels is None or rough_pixels is None or metal_pixels is None:
        if diagnostics:
            diagnostics.add_warning(
                f"Material set '{set_name}': failed to read O/R/M channels."
            )
        return None

    textures_dir.mkdir(exist_ok=True)
    orm_filename = f"{set_name}_ORM.png"
    orm_path = textures_dir / orm_filename

    try:
        _write_orm_png(orm_path, width, height, ao_pixels, rough_pixels, metal_pixels)
    except Exception as exc:
        if diagnostics:
            diagnostics.add_warning(
                f"Material set '{set_name}': failed to write ORM texture: {exc}"
            )
        return None

    return orm_filename


# ------------------------------------------------------------------
# Image helpers
# ------------------------------------------------------------------

def _stage_image(image, textures_dir: Path, diagnostics) -> Optional[str]:
    """Copy image to textures/ if needed and return its filename."""
    if not image:
        return None

    src = _resolve_image_path(image)
    if not src:
        if diagnostics:
            diagnostics.add_warning(
                f"Material set image '{image.name}' could not be resolved to a file."
            )
        return None

    src_path = Path(src)
    dest = textures_dir / src_path.name

    if not dest.exists():
        try:
            textures_dir.mkdir(exist_ok=True)
            shutil.copy2(src_path, dest)
        except Exception as exc:
            if diagnostics:
                diagnostics.add_warning(
                    f"Failed to copy '{src_path.name}' to textures/: {exc}"
                )
            return None

    return dest.name


def _resolve_image_path(image) -> Optional[str]:
    """Resolve a Blender Image datablock to an absolute file path."""
    if not image:
        return None
    try:
        import bpy
        filepath = image.filepath or image.filepath_raw or ""
        if filepath:
            filepath = bpy.path.abspath(filepath)
            p = Path(filepath).resolve()
            if p.is_file():
                return str(p)

        from .materials.extract.core import _resolve_image_path as _extract_resolve
        return _extract_resolve(image)
    except Exception:
        return None


# ------------------------------------------------------------------
# Rebuild material .usda files from the first set
# ------------------------------------------------------------------

def rebuild_materials_from_sets(
    stage,
    usd_path: str,
    context,
    diagnostics=None,
) -> None:
    """Overwrite material .usda files using the first set of each slot.

    For every material slot that has Material Sets defined, the
    corresponding externalized ``.usda`` is regenerated with the first
    set's normal, packed ORM, and first diffuse textures.
    """
    require_pxr()

    usd_dir = Path(usd_path).parent
    materials_dir = usd_dir / "materials"
    textures_dir = usd_dir / "textures"

    if not materials_dir.exists():
        return

    # Build slot_name → (material prim name, prim path) from the stage.
    slot_to_mat = _map_slots_to_materials(stage, context)

    from ..manifest.materialx_nodes import load_manifest
    from .materials.graph import MaterialXGraphBuilder
    from .materials.author import create_materialx_material
    from .materials.externalize import _ensure_ancestor_specs

    manifest = load_manifest()
    builder = MaterialXGraphBuilder(manifest, diagnostics)

    for obj in context.scene.objects:
        collection = getattr(obj, "blendertorcp_material_sets", None)
        if not collection or not collection.slots:
            continue

        for slot_sets in collection.slots:
            if not slot_sets.slot_name or not slot_sets.sets:
                continue

            first_set = slot_sets.sets[0]
            mat_info = slot_to_mat.get(slot_sets.slot_name)
            if not mat_info:
                continue

            mat_name, mat_prim_path = mat_info
            mat_file = materials_dir / f"{mat_name}.usda"

            # Resolve the first set's textures (already staged by export_material_sets).
            normal_file = _find_staged(first_set.normal, textures_dir)
            orm_file = f"{first_set.name}_ORM.png"
            first_diffuse_file = None
            if first_set.diffuses:
                first_diffuse_file = _find_staged(first_set.diffuses[0].image, textures_dir)

            # Build material_data with only baseColor + normal.  The ORM
            # is wired manually below as a single ORM_Image + ORM_Separate
            # node feeding AO/Roughness/Metallic, matching the structure
            # produced by pack_materialx_orm_textures.
            material_data: Dict[str, Any] = {"type": "principled"}

            if first_diffuse_file:
                material_data["base_color_texture"] = str(textures_dir / first_diffuse_file)
                material_data["base_color_texture_colorspace"] = "srgb_texture"

            if normal_file:
                material_data["normal_texture"] = str(textures_dir / normal_file)
                material_data["normal_texture_colorspace"] = "raw"

            try:
                graph = builder.build_pbr_material(material_data)
            except Exception as exc:
                if diagnostics:
                    diagnostics.add_warning(
                        f"Failed to build material from set for slot '{slot_sets.slot_name}': {exc}"
                    )
                continue

            orm_path = textures_dir / orm_file
            orm_relative = f"../textures/{orm_file}" if orm_path.exists() else None

            # Overwrite the .usda file.  externalize_materials may have
            # already loaded this layer into USD's registry, so prefer
            # Find() to reuse it; otherwise create new.
            try:
                layer = Sdf.Layer.Find(str(mat_file))
                if layer is not None:
                    layer.Clear()
                else:
                    if mat_file.exists():
                        mat_file.unlink()
                    layer = Sdf.Layer.CreateNew(str(mat_file))
                if not layer:
                    if diagnostics:
                        diagnostics.add_warning(
                            f"Could not create material layer for '{mat_name}'"
                        )
                    continue
                tmp_stage = Usd.Stage.Open(layer)
                prim_sdf_path = Sdf.Path(mat_prim_path)
                _ensure_ancestor_specs(layer, prim_sdf_path)
                create_materialx_material(
                    tmp_stage, mat_prim_path, mat_name, graph, manifest, diagnostics,
                )
                if orm_relative:
                    _wire_orm_to_pbr(tmp_stage, mat_prim_path, orm_relative)

                # Re-promote texture file paths to Material-level interface
                # inputs (DiffuseTexture, NormalTexture, ORMTexture).  We
                # just re-authored the material from scratch, so any
                # interface inputs that existed from externalize were
                # cleared with the rest of the layer.
                from .materials.externalize import _promote_texture_inputs
                _promote_texture_inputs(layer, prim_sdf_path, usd_dir)

                tmp_stage.Save()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                if diagnostics:
                    diagnostics.add_warning(
                        f"Failed to write material for slot '{slot_sets.slot_name}': {exc}"
                    )


def _wire_orm_to_pbr(stage, material_path: str, orm_relative: str) -> None:
    """Add ORM_Image + ORM_Separate and wire AO/Roughness/Metallic to it."""
    material_prim = stage.GetPrimAtPath(material_path)
    if not material_prim or not material_prim.IsValid():
        return

    pbr_shader = None
    for child in material_prim.GetChildren():
        if child.GetTypeName() != "Shader":
            continue
        shader = UsdShade.Shader(child)
        sid = shader.GetIdAttr().Get()
        if sid and "surfaceshader" in str(sid).lower():
            pbr_shader = shader
            break
    if not pbr_shader:
        return

    # ORM_Image: ND_image_color3 reading the packed PNG.
    orm_image_path = f"{material_path}/ORM_Image"
    orm_prim = stage.DefinePrim(orm_image_path, "Shader")
    orm_shader = UsdShade.Shader(orm_prim)
    orm_shader.CreateIdAttr("ND_image_color3")
    orm_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(
        Sdf.AssetPath(orm_relative)
    )
    orm_out = orm_shader.CreateOutput("out", Sdf.ValueTypeNames.Color3f)

    # ORM_Separate: ND_separate3_color3 splitting into R/G/B.
    sep_path = f"{material_path}/ORM_Separate"
    sep_prim = stage.DefinePrim(sep_path, "Shader")
    sep_shader = UsdShade.Shader(sep_prim)
    sep_shader.CreateIdAttr("ND_separate3_color3")
    sep_in = sep_shader.CreateInput("in", Sdf.ValueTypeNames.Color3f)
    sep_in.ConnectToSource(orm_out)
    sep_outr = sep_shader.CreateOutput("outr", Sdf.ValueTypeNames.Float)
    sep_outg = sep_shader.CreateOutput("outg", Sdf.ValueTypeNames.Float)
    sep_outb = sep_shader.CreateOutput("outb", Sdf.ValueTypeNames.Float)

    channel_outputs = {
        "ambientOcclusion": sep_outr,
        "roughness": sep_outg,
        "metallic": sep_outb,
    }

    pbr_prim = pbr_shader.GetPrim()
    for input_name, source_output in channel_outputs.items():
        attr_name = f"inputs:{input_name}"
        had_value = (
            pbr_prim.HasAttribute(attr_name)
            and pbr_prim.GetAttribute(attr_name).HasAuthoredValue()
        )
        if had_value:
            pbr_prim.GetAttribute(attr_name).Clear()
        pbr_input = pbr_shader.CreateInput(
            input_name, Sdf.ValueTypeNames.Float
        )
        pbr_input.ConnectToSource(source_output)


def _map_slots_to_materials(stage, context) -> Dict[str, tuple]:
    """Map Blender material slot names to (mat prim name, prim path)."""
    from .materials.helpers import _get_blender_data_name

    # Blender material name → USD prim path
    blender_to_usd: Dict[str, tuple] = {}
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Material):
            continue
        prim_name = prim.GetName()
        blender_name = _get_blender_data_name(prim) or prim_name
        path_str = str(prim.GetPath())
        blender_to_usd.setdefault(blender_name, (prim_name, path_str))
        blender_to_usd.setdefault(prim_name, (prim_name, path_str))

    # Slot name → (mat prim name, prim path)
    result: Dict[str, tuple] = {}
    for obj in context.scene.objects:
        for slot in obj.material_slots:
            if slot.material and slot.name not in result:
                info = blender_to_usd.get(slot.material.name)
                if info:
                    result[slot.name] = info

    return result


def _find_staged(image, textures_dir: Path) -> Optional[str]:
    """Return the filename of a staged image, or None."""
    if not image:
        return None
    src = _resolve_image_path(image)
    if not src:
        return None
    name = Path(src).name
    if (textures_dir / name).exists():
        return name
    return None
