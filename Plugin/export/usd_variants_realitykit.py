"""
USD variant authoring for RealityKit / QuickLook.

Places all VariantSets on the stage's **default prim** so that
QuickLook and the RealityKit API can discover and switch them at
runtime.  Each Blender object that carries variants gets its own
distinctly-named VariantSet on the default prim (e.g.
``MyObject_materialVariant``, ``MyObject_geometryVariant``).

This is separate from the RCP-mode authoring (usd_variants.py and
usd_geometry_variants.py) which places VariantSets on per-object
Xform prims for the Reality Composer Pro dropdown UI.
"""

from __future__ import annotations

from typing import Any, Optional

import bpy

from .usd_utils import Usd, UsdShade, UsdGeom, Sdf, require_pxr
from .materials.extract import (
    extract_blender_material_data,
    collect_material_warnings,
)
from .materials.graph import MaterialXGraphBuilder
from .materials.author import create_materialx_material
from .materials.helpers import _get_blender_data_name, _sanitize_name
from ..manifest.materialx_nodes import load_manifest


# ===================================================================
# Public entry points
# ===================================================================

def author_material_variants_realitykit(
    stage, context, settings, diagnostics=None,
) -> None:
    """Author per-object materialVariant VariantSets on the default prim."""
    require_pxr()

    objects_with_variants = _collect_objects_with_material_variants(context)
    if not objects_with_variants:
        return

    default_prim = stage.GetDefaultPrim()
    if not default_prim:
        if diagnostics:
            diagnostics.add_warning(
                "No default prim on stage; cannot author RealityKit variants."
            )
        return

    all_variant_mat_names = _collect_variant_material_names(
        objects_with_variants,
    )
    existing_materials = _build_material_map(stage)

    force_unlit = bool(getattr(settings, "force_unlit_materials", False))
    manifest = load_manifest()
    builder = MaterialXGraphBuilder(manifest, diagnostics)

    for mat_name in all_variant_mat_names:
        if mat_name in existing_materials:
            continue
        blender_mat = bpy.data.materials.get(mat_name)
        if not blender_mat:
            if diagnostics:
                diagnostics.add_warning(
                    f"Variant material '{mat_name}' not found in blend file."
                )
            continue
        mat_prim_path = _new_material_path(stage, mat_name)
        result = _create_and_rewrite_material(
            stage, mat_prim_path, blender_mat, manifest, builder,
            force_unlit, diagnostics,
        )
        if result:
            existing_materials[mat_name] = mat_prim_path

    prim_map = _build_object_prim_map(stage)
    layer = stage.GetRootLayer()
    default_prim_path = default_prim.GetPath()
    default_spec = layer.GetPrimAtPath(default_prim_path)
    if not default_spec:
        return

    for obj_name, obj in objects_with_variants.items():
        mesh_path = prim_map.get(obj_name)
        if not mesh_path:
            mesh_path = prim_map.get(_sanitize_name(obj_name))
        if not mesh_path:
            if diagnostics:
                diagnostics.add_warning(
                    f"No USD prim found for object '{obj_name}'; "
                    "skipping RealityKit material variants."
                )
            continue

        mesh_prim = stage.GetPrimAtPath(mesh_path)
        if not mesh_prim:
            continue

        variant_set_data = obj.blendertorcp_material_variants
        geom_subsets = _get_geom_subsets(mesh_prim)
        slot_to_subset = _map_slots_to_subsets(
            obj, geom_subsets, existing_materials,
        )

        _clear_direct_binding(mesh_prim, layer)
        if geom_subsets and slot_to_subset:
            for subset_prim in slot_to_subset.values():
                _clear_direct_binding(subset_prim, layer)

        vset_name = f"{_sanitize_name(obj_name)}_materialVariant"

        if vset_name not in default_spec.variantSets:
            Sdf.VariantSetSpec(default_spec, vset_name)

        _merge_variant_set_name(default_spec, vset_name)

        variant_set_spec = default_spec.variantSets[vset_name]
        first_variant_name = None

        mesh_rel_path = _relative_path(default_prim_path, mesh_path)

        for variant in variant_set_data.variants:
            if first_variant_name is None:
                first_variant_name = variant.name

            variant_spec = Sdf.VariantSpec(variant_set_spec, variant.name)

            if geom_subsets and slot_to_subset:
                _author_rk_variant_multi_slot(
                    variant_spec, variant,
                    default_prim_path, mesh_rel_path,
                    slot_to_subset, existing_materials,
                )
            else:
                _author_rk_variant_single_slot(
                    variant_spec, variant,
                    default_prim_path, mesh_rel_path,
                    existing_materials,
                )

        if first_variant_name:
            default_spec.variantSelections[vset_name] = first_variant_name

        if diagnostics:
            names = [v.name for v in variant_set_data.variants]
            diagnostics.add_warning(
                f"Authored RealityKit {vset_name} on default prim: {names}"
            )


def author_geometry_variants_realitykit(
    stage, context, settings, diagnostics=None,
) -> None:
    """Author per-object geometryVariant VariantSets on the default prim."""
    require_pxr()

    objects_with_variants = _collect_objects_with_geometry_variants(context)
    if not objects_with_variants:
        return

    default_prim = stage.GetDefaultPrim()
    if not default_prim:
        if diagnostics:
            diagnostics.add_warning(
                "No default prim on stage; cannot author RealityKit geometry variants."
            )
        return

    layer = stage.GetRootLayer()
    default_prim_path = default_prim.GetPath()
    default_spec = layer.GetPrimAtPath(default_prim_path)
    if not default_spec:
        return

    for obj_name, obj in objects_with_variants.items():
        variant_set_data = obj.blendertorcp_geometry_variants

        xform_prim = _find_xform_for_object(stage, obj_name)
        if not xform_prim:
            if diagnostics:
                diagnostics.add_warning(
                    f"No USD Xform found for object '{obj_name}'; "
                    "skipping RealityKit geometry variants."
                )
            continue

        variant_entries = _resolve_variant_children(
            obj, variant_set_data, xform_prim, diagnostics,
        )
        if not variant_entries:
            continue

        vset_name = f"{_sanitize_name(obj_name)}_geometryVariant"

        if vset_name not in default_spec.variantSets:
            Sdf.VariantSetSpec(default_spec, vset_name)

        _merge_variant_set_name(default_spec, vset_name)

        variant_set_spec = default_spec.variantSets[vset_name]
        first_variant_name = None
        moved_children: set[str] = set()

        xform_path = xform_prim.GetPath()
        xform_rel = _relative_path(default_prim_path, str(xform_path))

        for variant_name, child_names in variant_entries:
            if first_variant_name is None:
                first_variant_name = variant_name

            variant_spec = Sdf.VariantSpec(variant_set_spec, variant_name)

            xform_over = _ensure_over_hierarchy(
                variant_spec.primSpec, default_prim_path, xform_rel,
            )

            for child_name in child_names:
                src_path = xform_path.AppendChild(child_name)
                dst_path = xform_over.path.AppendChild(child_name)

                if not Sdf.CopySpec(layer, src_path, layer, dst_path):
                    if diagnostics:
                        diagnostics.add_warning(
                            f"Failed to copy '{src_path}' into RealityKit "
                            f"variant '{variant_name}'; skipping."
                        )
                    continue

                moved_children.add(child_name)

        xform_spec = layer.GetPrimAtPath(xform_path)
        if xform_spec:
            for child_name in moved_children:
                if child_name in xform_spec.nameChildren:
                    del xform_spec.nameChildren[child_name]

        if first_variant_name:
            default_spec.variantSelections[vset_name] = first_variant_name

        if diagnostics:
            names = [v.name for v in variant_set_data.variants]
            diagnostics.add_warning(
                f"Authored RealityKit {vset_name} on default prim: {names}"
            )


# ===================================================================
# Path helpers
# ===================================================================

def _relative_path(root_path, target_path_str: str) -> str:
    """Return the portion of *target_path_str* below *root_path*.

    Example: root ``/root``, target ``/root/Cube/CubeMesh``
    returns ``Cube/CubeMesh``.
    """
    root_str = str(root_path)
    target = str(target_path_str)
    if target.startswith(root_str + "/"):
        return target[len(root_str) + 1:]
    return target.lstrip("/")


def _ensure_over_hierarchy(parent_spec, root_path, rel_path: str):
    """Create nested ``over`` specs for each segment of *rel_path*
    under *parent_spec* and return the leaf spec.
    """
    parts = rel_path.split("/")
    current = parent_spec
    for part in parts:
        child_path = current.path.AppendChild(part)
        child_spec = current.layer.GetPrimAtPath(child_path)
        if not child_spec:
            child_spec = Sdf.PrimSpec(current, part, Sdf.SpecifierOver)
        current = child_spec
    return current


# ===================================================================
# Material variant Sdf-level authoring
# ===================================================================

def _author_rk_variant_single_slot(
    variant_spec, variant,
    default_prim_path, mesh_rel_path,
    material_map,
):
    """Author material:binding inside a RealityKit variant body."""
    if not variant.slot_assignments:
        return
    assignment = variant.slot_assignments[0]
    if not assignment.material:
        return
    mat_path = material_map.get(assignment.material.name)
    if not mat_path:
        return

    mesh_over = _ensure_over_hierarchy(
        variant_spec.primSpec, default_prim_path, mesh_rel_path,
    )
    _author_material_binding_rel(mesh_over, mat_path)


def _author_rk_variant_multi_slot(
    variant_spec, variant,
    default_prim_path, mesh_rel_path,
    slot_to_subset, material_map,
):
    """Author material:binding on GeomSubsets inside a RealityKit variant body."""
    mesh_over = _ensure_over_hierarchy(
        variant_spec.primSpec, default_prim_path, mesh_rel_path,
    )
    for slot_idx, assignment in enumerate(variant.slot_assignments):
        if not assignment.material:
            continue
        mat_path = material_map.get(assignment.material.name)
        if not mat_path:
            continue
        subset_prim = slot_to_subset.get(slot_idx)
        if not subset_prim:
            continue
        subset_over = _get_or_create_over(mesh_over, subset_prim.GetName())
        _author_material_binding_rel(subset_over, mat_path)


def _get_or_create_over(parent_spec, child_name: str):
    """Get or create an ``over`` child prim spec."""
    child_path = parent_spec.path.AppendChild(child_name)
    child_spec = parent_spec.layer.GetPrimAtPath(child_path)
    if child_spec:
        return child_spec
    return Sdf.PrimSpec(parent_spec, child_name, Sdf.SpecifierOver)


def _author_material_binding_rel(prim_spec, material_path: str):
    """Author a ``material:binding`` relationship on *prim_spec*."""
    binding_path = "material:binding"
    if binding_path not in prim_spec.relationships:
        rel_spec = Sdf.RelationshipSpec(
            prim_spec, binding_path, custom=False,
        )
    else:
        rel_spec = prim_spec.relationships[binding_path]
    rel_spec.targetPathList.explicitItems = [Sdf.Path(material_path)]


# ===================================================================
# Clear helpers
# ===================================================================

def _clear_direct_binding(prim, layer=None) -> None:
    """Remove a direct ``material:binding`` so variant opinions win."""
    try:
        prim.RemoveProperty("material:binding")
    except Exception:
        pass
    if layer:
        prim_spec = layer.GetPrimAtPath(prim.GetPath())
        if prim_spec:
            try:
                rel = prim_spec.relationships.get("material:binding")
                if rel:
                    prim_spec.RemoveProperty(rel)
            except Exception:
                pass


# ===================================================================
# VariantSet name merging
# ===================================================================

def _merge_variant_set_name(prim_spec, name: str):
    """Prepend *name* to the prim's ``variantSetNames`` list op."""
    existing = []
    info = prim_spec.GetInfo("variantSetNames")
    if info:
        existing = list(info.prependedItems or [])
    if name not in existing:
        existing.insert(0, name)
    prim_spec.SetInfo(
        "variantSetNames",
        Sdf.StringListOp.Create(prependedItems=existing),
    )


# ===================================================================
# Stage introspection helpers (shared logic)
# ===================================================================

def _collect_objects_with_material_variants(context) -> dict:
    result = {}
    for obj in context.scene.objects:
        vset = getattr(obj, "blendertorcp_material_variants", None)
        if vset and vset.variants:
            result[obj.name] = obj
    return result


def _collect_objects_with_geometry_variants(context) -> dict:
    result = {}
    for obj in context.scene.objects:
        vset = getattr(obj, "blendertorcp_geometry_variants", None)
        if vset and vset.variants:
            result[obj.name] = obj
    return result


def _collect_variant_material_names(objects_with_variants: dict) -> set[str]:
    names: set[str] = set()
    for obj in objects_with_variants.values():
        for variant in obj.blendertorcp_material_variants.variants:
            for assignment in variant.slot_assignments:
                if assignment.material:
                    names.add(assignment.material.name)
    return names


def _build_material_map(stage) -> dict[str, str]:
    mat_map: dict[str, str] = {}
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Material):
            continue
        blender_name = _get_blender_data_name(prim) or prim.GetName()
        mat_map[blender_name] = str(prim.GetPath())
    return mat_map


def _build_object_prim_map(stage) -> dict[str, str]:
    prim_map: dict[str, str] = {}
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh_path = str(prim.GetPath())
        blender_name = _get_blender_data_name(prim) or prim.GetName()
        if blender_name and blender_name not in prim_map:
            prim_map[blender_name] = mesh_path
        leaf = prim.GetName()
        if leaf not in prim_map:
            prim_map[leaf] = mesh_path
        parent = prim.GetParent()
        if parent:
            for attr_name in (
                "userProperties:blenderName:object",
                "userProperties:blender:object_name",
            ):
                attr = parent.GetAttribute(attr_name)
                if attr and attr.IsValid():
                    val = attr.Get()
                    if val and str(val) not in prim_map:
                        prim_map[str(val)] = mesh_path
    return prim_map


def _get_geom_subsets(mesh_prim) -> list:
    return [
        child for child in mesh_prim.GetChildren()
        if child.IsA(UsdGeom.Subset)
    ]


def _map_slots_to_subsets(obj, geom_subsets, material_map) -> dict:
    if not geom_subsets:
        return {}
    mat_name_to_slot: dict[str, int] = {}
    for i, slot in enumerate(obj.material_slots):
        if slot.material:
            mat_name_to_slot[slot.material.name] = i
    slot_to_subset: dict[int, Any] = {}
    for subset in geom_subsets:
        binding = UsdShade.MaterialBindingAPI(subset)
        bound_mat = binding.GetDirectBinding().GetMaterial()
        if not bound_mat:
            continue
        mat_prim = bound_mat.GetPrim()
        blender_name = (
            _get_blender_data_name(mat_prim) or mat_prim.GetName()
        )
        slot_idx = mat_name_to_slot.get(blender_name)
        if slot_idx is not None:
            slot_to_subset[slot_idx] = subset
    return slot_to_subset


# ===================================================================
# Geometry variant helpers
# ===================================================================

_BLENDER_NAME_ATTRS = (
    "userProperties:blenderName:object",
    "userProperties:blender:object_name",
)


def _find_xform_for_object(stage, obj_name: str):
    sanitized = _sanitize_name(obj_name)
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Xform):
            continue
        if prim.GetName() in (obj_name, sanitized):
            return prim
        if _blender_name_matches(prim, obj_name):
            return prim
    return None


def _find_child_prim_name(xform_prim, target_obj_name: str, is_self: bool):
    if is_self:
        for child in xform_prim.GetChildren():
            if child.IsA(UsdGeom.Mesh):
                return child.GetName()
        return None
    sanitized = _sanitize_name(target_obj_name)
    for child in xform_prim.GetChildren():
        if child.GetName() in (target_obj_name, sanitized):
            return child.GetName()
        if _blender_name_matches(child, target_obj_name):
            return child.GetName()
    return None


def _blender_name_matches(prim, name: str) -> bool:
    for attr_name in _BLENDER_NAME_ATTRS:
        attr = prim.GetAttribute(attr_name)
        if attr and attr.IsValid():
            val = attr.Get()
            if val and str(val) == name:
                return True
    return False


def _resolve_variant_children(obj, variant_set_data, xform_prim, diagnostics):
    entries = []
    vset_path = xform_prim.GetPath()
    for variant in variant_set_data.variants:
        child_names = []
        for target_entry in variant.targets:
            target_obj = target_entry.target_object
            if not target_obj:
                continue
            if target_obj != obj and target_obj.parent != obj:
                if diagnostics:
                    diagnostics.add_warning(
                        f"Geometry variant target '{target_obj.name}' is not "
                        f"parented under '{obj.name}'."
                    )
                continue
            is_self = (target_obj == obj)
            child_name = _find_child_prim_name(
                xform_prim, target_obj.name, is_self,
            )
            if not child_name:
                if diagnostics:
                    diagnostics.add_warning(
                        f"No child prim found for '{target_obj.name}' "
                        f"under Xform '{vset_path}'; skipping."
                    )
                continue
            child_names.append(child_name)
        if child_names:
            entries.append((variant.name, child_names))
    return entries


# ===================================================================
# Material creation helpers
# ===================================================================

def _find_materials_scope(stage) -> str:
    default_prim = stage.GetDefaultPrim()
    root_path = str(default_prim.GetPath()) if default_prim else ""
    for scope_name in ("_materials", "Materials", "Looks"):
        scope_path = f"{root_path}/{scope_name}"
        if stage.GetPrimAtPath(scope_path):
            return scope_path
    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Material):
            return str(prim.GetParent().GetPath())
    scope_path = f"{root_path}/_materials"
    stage.DefinePrim(scope_path, "Scope")
    return scope_path


def _new_material_path(stage, material_name: str) -> str:
    materials_scope = _find_materials_scope(stage)
    safe_name = _sanitize_name(material_name)
    candidate = f"{materials_scope}/{safe_name}"
    suffix = 1
    while stage.GetPrimAtPath(candidate):
        suffix += 1
        candidate = f"{materials_scope}/{safe_name}_{suffix}"
    return candidate


def _create_and_rewrite_material(
    stage, material_path, blender_material, manifest, builder,
    force_unlit, diagnostics,
) -> Optional[UsdShade.Material]:
    warnings = collect_material_warnings(blender_material)
    if diagnostics:
        for warning in warnings:
            diagnostics.add_warning(warning)

    material_data = extract_blender_material_data(blender_material)
    unresolved = material_data.get("unresolved_warnings") or []
    if diagnostics:
        for warning in unresolved:
            diagnostics.add_warning(warning)
            diagnostics.add_error(warning)

    try:
        mat_type = material_data["type"]
        if force_unlit and mat_type in {"principled", "emission", "simple"}:
            graph = builder.build_unlit_material(material_data)
        elif mat_type == "principled":
            graph = builder.build_pbr_material(material_data)
        elif mat_type in {"emission", "simple"}:
            graph = builder.build_unlit_material(material_data)
        elif mat_type == "rk_graph":
            graph = builder.build_rk_graph(material_data.get("rk_graph"))
        elif mat_type == "rk_group":
            graph = builder.build_rk_material(
                material_data.get("rk_node_id"),
                material_data.get("rk_inputs", {}),
            )
        else:
            graph = None

        if graph:
            material = create_materialx_material(
                stage, material_path, blender_material.name,
                graph, manifest, diagnostics,
            )
            if diagnostics:
                diagnostics.add_material_converted(blender_material.name)
            return material
    except Exception as e:
        if diagnostics:
            diagnostics.add_material_failed(blender_material.name, str(e))
    return None
