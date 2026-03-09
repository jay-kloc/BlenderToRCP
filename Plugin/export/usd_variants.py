"""
USD material variant authoring.

Creates materialVariant VariantSets on object Xform prims based on
Blender material variant definitions stored on objects.

The VariantSet is placed on the parent Xform so that material:binding
opinions inside the variant body (authored via ``over`` on the child
mesh) live at *Variant* strength in USD's LIVRPS composition order.
Any local material:binding on the mesh itself is cleared first so the
variant opinion wins.
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
# Public entry point
# ===================================================================

def author_material_variants(
    stage, context, settings, diagnostics=None,
) -> None:
    """Author materialVariant VariantSets on USD prims."""
    require_pxr()

    objects_with_variants = _collect_objects_with_variants(context)
    if not objects_with_variants:
        return

    all_variant_mat_names = _collect_variant_material_names(
        objects_with_variants,
    )
    existing_materials = _build_material_map(stage)

    force_unlit = bool(getattr(settings, "force_unlit_materials", False))
    manifest = load_manifest()
    builder = MaterialXGraphBuilder(manifest, diagnostics)

    # Ensure every material referenced by a variant exists on the stage.
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

    for obj_name, obj in objects_with_variants.items():
        mesh_path = prim_map.get(obj_name)
        if not mesh_path:
            mesh_path = prim_map.get(_sanitize_name(obj_name))
        if not mesh_path:
            if diagnostics:
                diagnostics.add_warning(
                    f"No USD prim found for object '{obj_name}'; "
                    "skipping material variants."
                )
            continue

        mesh_prim = stage.GetPrimAtPath(mesh_path)
        if not mesh_prim:
            continue

        # Place the VariantSet on the parent Xform so that variant
        # opinions live below local opinions in LIVRPS strength order.
        parent_prim = mesh_prim.GetParent()
        if parent_prim and parent_prim.IsA(UsdGeom.Xform):
            vset_prim = parent_prim
        else:
            vset_prim = mesh_prim

        variant_set_data = obj.blendertorcp_material_variants
        geom_subsets = _get_geom_subsets(mesh_prim)
        slot_to_subset = _map_slots_to_subsets(
            obj, geom_subsets, existing_materials,
        )

        # Clear local material:binding so variant opinions win.
        if geom_subsets and slot_to_subset:
            for subset_prim in slot_to_subset.values():
                _clear_direct_binding(subset_prim, layer)
        else:
            _clear_direct_binding(mesh_prim, layer)

        # Author the VariantSet via the Sdf layer API.
        vset_sdf_path = vset_prim.GetPath()
        mesh_sdf_path = mesh_prim.GetPath()

        vset_spec = layer.GetPrimAtPath(vset_sdf_path)
        if not vset_spec:
            continue

        if "materialVariant" not in vset_spec.variantSets:
            Sdf.VariantSetSpec(vset_spec, "materialVariant")

        vset_spec.SetInfo(
            "variantSetNames",
            Sdf.StringListOp.Create(prependedItems=["materialVariant"]),
        )

        variant_set_spec = vset_spec.variantSets["materialVariant"]
        first_variant_name = None

        for variant in variant_set_data.variants:
            if first_variant_name is None:
                first_variant_name = variant.name

            variant_spec = Sdf.VariantSpec(variant_set_spec, variant.name)

            if geom_subsets and slot_to_subset:
                _author_variant_multi_slot(
                    variant_spec, variant,
                    vset_sdf_path, mesh_sdf_path,
                    slot_to_subset, existing_materials,
                )
            else:
                _author_variant_single_slot(
                    variant_spec, variant,
                    vset_sdf_path, mesh_sdf_path,
                    existing_materials,
                )

        if first_variant_name:
            vset_spec.variantSelections["materialVariant"] = (
                first_variant_name
            )

        if diagnostics:
            names = [v.name for v in variant_set_data.variants]
            diagnostics.add_warning(
                f"Authored materialVariant on '{obj_name}': {names}"
            )


# ===================================================================
# Sdf-level variant authoring
# ===================================================================

def _author_variant_single_slot(
    variant_spec, variant,
    vset_sdf_path, mesh_sdf_path,
    material_map,
):
    """Author material:binding for a single-slot object."""
    if not variant.slot_assignments:
        return
    assignment = variant.slot_assignments[0]
    if not assignment.material:
        return
    mat_path = material_map.get(assignment.material.name)
    if not mat_path:
        return

    target = _variant_target_spec(
        variant_spec, vset_sdf_path, mesh_sdf_path,
    )
    _author_material_binding_rel(target, mat_path)


def _author_variant_multi_slot(
    variant_spec, variant,
    vset_sdf_path, mesh_sdf_path,
    slot_to_subset, material_map,
):
    """Author material:binding on GeomSubsets inside a variant."""
    mesh_over = _variant_target_spec(
        variant_spec, vset_sdf_path, mesh_sdf_path,
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


def _variant_target_spec(variant_spec, vset_sdf_path, mesh_sdf_path):
    """Return the prim spec to author material:binding on inside a variant.

    When the variant set lives on the parent Xform, we create an ``over``
    for the child mesh.  When it lives on the mesh itself, we author
    directly on the variant's prim spec.
    """
    if vset_sdf_path == mesh_sdf_path:
        return variant_spec.primSpec
    return _get_or_create_over(variant_spec.primSpec, mesh_sdf_path.name)


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
# Stage introspection helpers
# ===================================================================

def _collect_objects_with_variants(context) -> dict:
    """Return ``{obj_name: obj}`` for objects with at least one variant."""
    result = {}
    for obj in context.scene.objects:
        vset = getattr(obj, "blendertorcp_material_variants", None)
        if vset and vset.variants:
            result[obj.name] = obj
    return result


def _collect_variant_material_names(
    objects_with_variants: dict,
) -> set[str]:
    """Collect every unique material name referenced by any variant."""
    names: set[str] = set()
    for obj in objects_with_variants.values():
        for variant in obj.blendertorcp_material_variants.variants:
            for assignment in variant.slot_assignments:
                if assignment.material:
                    names.add(assignment.material.name)
    return names


def _build_material_map(stage) -> dict[str, str]:
    """Map Blender material name -> USD material prim path."""
    mat_map: dict[str, str] = {}
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Material):
            continue
        blender_name = _get_blender_data_name(prim) or prim.GetName()
        mat_map[blender_name] = str(prim.GetPath())
    return mat_map


def _build_object_prim_map(stage) -> dict[str, str]:
    """Map Blender object name -> USD mesh prim path.

    Entries are added for:
    * the mesh prim's ``data_name`` custom property
    * the mesh prim's leaf name
    * the parent Xform's ``object_name`` custom property (the Blender
      object name that carries the variant definitions)
    """
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
    """Return GeomSubset children of a mesh prim."""
    return [
        child for child in mesh_prim.GetChildren()
        if child.IsA(UsdGeom.Subset)
    ]


def _map_slots_to_subsets(obj, geom_subsets, material_map) -> dict:
    """Map Blender material slot indices to USD GeomSubset prims."""
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
# Material creation helpers
# ===================================================================

def _find_materials_scope(stage) -> str:
    """Find the existing materials scope on the stage."""
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
    """Generate a unique material prim path."""
    materials_scope = _find_materials_scope(stage)
    safe_name = _sanitize_name(material_name)
    candidate = f"{materials_scope}/{safe_name}"
    suffix = 1
    while stage.GetPrimAtPath(candidate):
        suffix += 1
        candidate = f"{materials_scope}/{safe_name}_{suffix}"
    return candidate


def _create_and_rewrite_material(
    stage,
    material_path: str,
    blender_material,
    manifest,
    builder: MaterialXGraphBuilder,
    force_unlit: bool,
    diagnostics,
) -> Optional[UsdShade.Material]:
    """Create a MaterialX material on the stage from a Blender material."""
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
