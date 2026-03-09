"""
USD geometry variant authoring.

Creates geometryVariant VariantSets on object Xform prims based on
Blender geometry variant definitions stored on objects.

Each geometry variant references one or more Blender mesh objects
parented under the owner.  At export time the child prim specs are
copied into the corresponding variant body and the originals are
removed.  Switching the geometryVariant in Reality Composer Pro swaps
the entire child prim tree, preserving material variants and bindings.
"""

from __future__ import annotations

from typing import Optional

from .usd_utils import UsdGeom, Sdf, require_pxr
from .materials.helpers import _sanitize_name


_BLENDER_NAME_ATTRS = (
    "userProperties:blenderName:object",
    "userProperties:blender:object_name",
)


# ===================================================================
# Public entry point
# ===================================================================

def author_geometry_variants(
    stage, context, settings, diagnostics=None,
) -> None:
    """Author geometryVariant VariantSets on USD prims."""
    require_pxr()

    objects_with_variants = _collect_objects_with_geometry_variants(context)
    if not objects_with_variants:
        return

    layer = stage.GetRootLayer()

    for obj_name, obj in objects_with_variants.items():
        variant_set_data = obj.blendertorcp_geometry_variants

        xform_prim = _find_xform_for_object(stage, obj_name)
        if not xform_prim:
            if diagnostics:
                diagnostics.add_warning(
                    f"No USD Xform found for object '{obj_name}'; "
                    "skipping geometry variants."
                )
            continue

        variant_entries = _resolve_variant_children(
            obj, variant_set_data, xform_prim, diagnostics,
        )
        if not variant_entries:
            continue

        _author_variant_set(
            layer, xform_prim.GetPath(), variant_entries,
            variant_set_data, diagnostics, obj_name,
        )


# ===================================================================
# Variant resolution
# ===================================================================

def _resolve_variant_children(obj, variant_set_data, xform_prim, diagnostics):
    """Map each variant to its child prim names under *xform_prim*.

    Returns a list of ``(variant_name, [child_prim_name, ...])`` pairs.
    """
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
                        f"parented under '{obj.name}'. "
                        "Parent it (Ctrl+P > Object) for variants to work."
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
# Sdf-level authoring
# ===================================================================

def _author_variant_set(
    layer, vset_path, variant_entries, variant_set_data,
    diagnostics, obj_name,
):
    """Create the geometryVariant VariantSet on *vset_path*.

    Each child prim spec is copied into its variant body and the
    original is removed from the parent Xform.
    """
    vset_spec = layer.GetPrimAtPath(vset_path)
    if not vset_spec:
        return

    if "geometryVariant" not in vset_spec.variantSets:
        Sdf.VariantSetSpec(vset_spec, "geometryVariant")

    _merge_variant_set_name(vset_spec, "geometryVariant")

    variant_set_spec = vset_spec.variantSets["geometryVariant"]
    first_variant_name = None
    moved_children: set[str] = set()

    for variant_name, child_names in variant_entries:
        if first_variant_name is None:
            first_variant_name = variant_name

        variant_spec = Sdf.VariantSpec(variant_set_spec, variant_name)

        for child_name in child_names:
            src_path = vset_path.AppendChild(child_name)
            dst_path = variant_spec.primSpec.path.AppendChild(child_name)

            if not Sdf.CopySpec(layer, src_path, layer, dst_path):
                if diagnostics:
                    diagnostics.add_warning(
                        f"Failed to copy '{src_path}' into variant "
                        f"'{variant_name}'; skipping."
                    )
                continue

            moved_children.add(child_name)

    for child_name in moved_children:
        if child_name in vset_spec.nameChildren:
            del vset_spec.nameChildren[child_name]

    if first_variant_name:
        vset_spec.variantSelections["geometryVariant"] = first_variant_name

    if diagnostics:
        names = [v.name for v in variant_set_data.variants]
        diagnostics.add_warning(
            f"Authored geometryVariant on '{obj_name}': {names}"
        )


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
# Stage introspection
# ===================================================================

def _collect_objects_with_geometry_variants(context) -> dict:
    """Return ``{obj_name: obj}`` for objects with geometry variants."""
    result = {}
    for obj in context.scene.objects:
        vset = getattr(obj, "blendertorcp_geometry_variants", None)
        if vset and vset.variants:
            result[obj.name] = obj
    return result


def _find_xform_for_object(stage, obj_name: str):
    """Find the Xform prim that corresponds to a Blender object."""
    sanitized = _sanitize_name(obj_name)
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Xform):
            continue
        if prim.GetName() in (obj_name, sanitized):
            return prim
        if _blender_name_matches(prim, obj_name):
            return prim
    return None


def _find_child_prim_name(
    xform_prim, target_obj_name: str, is_self: bool,
) -> Optional[str]:
    """Find a child prim name under *xform_prim* for a variant target.

    *is_self* is True when the target is the owner object itself; in
    that case the owner's direct Mesh child is returned.
    """
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
    """Return True if any Blender-name attribute on *prim* equals *name*."""
    for attr_name in _BLENDER_NAME_ATTRS:
        attr = prim.GetAttribute(attr_name)
        if attr and attr.IsValid():
            val = attr.Get()
            if val and str(val) == name:
                return True
    return False
