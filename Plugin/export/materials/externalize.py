"""
Extract inline materials into separate USD files.

After materials are authored inline in the main stage, this module
moves each material subtree into its own file under ``materials/``
and replaces the inline definition with a USD reference.
"""

from pathlib import Path

from ..usd_utils import Usd, UsdShade, UsdGeom, Sdf


def _collect_bound_material_paths(stage):
    """Return the set of material prim paths actually bound to geometry."""
    bound = set()
    for prim in stage.Traverse():
        if not (prim.IsA(UsdGeom.Mesh) or prim.IsA(UsdGeom.Subset)):
            continue
        binding = UsdShade.MaterialBindingAPI(prim)
        mat = binding.GetDirectBinding().GetMaterial()
        if mat:
            bound.add(mat.GetPrim().GetPath())
    return bound


def externalize_materials(stage, usd_path: str, diagnostics=None) -> None:
    """Move each bound Material prim into a separate USD file under materials/.

    Materials that are not bound to any geometry in the stage are removed.
    """
    usd_dir = Path(usd_path).parent
    materials_dir = usd_dir / "materials"

    main_layer = stage.GetRootLayer()
    bound_paths = _collect_bound_material_paths(stage)

    # Collect all material prims (snapshot to avoid mutation during iteration).
    mat_prims = [
        prim for prim in stage.Traverse()
        if prim.IsA(UsdShade.Material)
    ]

    if not mat_prims:
        return

    materials_dir.mkdir(exist_ok=True)

    for mat_prim in mat_prims:
        mat_path = mat_prim.GetPath()

        # Skip (and remove) materials not bound to any exported geometry.
        if mat_path not in bound_paths:
            stage.RemovePrim(mat_path)
            continue
        mat_name = mat_prim.GetName()
        mat_path = mat_prim.GetPath()

        ext_file = materials_dir / f"{mat_name}.usda"
        ext_layer = Sdf.Layer.CreateNew(str(ext_file))
        if not ext_layer:
            if diagnostics:
                diagnostics.add_warning(
                    f"Failed to create material layer for '{mat_name}'"
                )
            continue

        # Ensure ancestor prims exist in the external layer so the
        # full prim path is valid (e.g. /Scene/_materials/MatName).
        _ensure_ancestor_specs(ext_layer, mat_path)

        # Copy the full material subtree (properties + children).
        if not Sdf.CopySpec(main_layer, mat_path, ext_layer, mat_path):
            if diagnostics:
                diagnostics.add_warning(
                    f"Sdf.CopySpec failed for material '{mat_name}'"
                )
            continue

        # Rewrite texture asset paths inside the external layer so they
        # resolve relative to materials/ (i.e. ../textures/foo.png).
        _rewrite_asset_paths(ext_layer)

        ext_layer.Save()

        # --- Replace inline definition with a reference. ---

        # Remove children (shader nodes) from the main layer.
        children = [child.GetPath() for child in mat_prim.GetChildren()]
        for child_path in children:
            stage.RemovePrim(child_path)

        # Remove authored properties on the material prim itself
        # (outputs:mtlx:surface, etc.) — these now come via the reference.
        mat_spec = main_layer.GetPrimAtPath(mat_path)
        if mat_spec:
            prop_names = list(mat_spec.properties.keys())
            for prop_name in prop_names:
                del mat_spec.properties[prop_name]

        # Add reference to the external file with explicit prim path.
        mat_prim.GetReferences().AddReference(
            f"./materials/{mat_name}.usda",
            mat_path,
        )


def _ensure_ancestor_specs(layer, prim_path):
    """Create Over specs for every ancestor of *prim_path* that is missing."""
    ancestors = []
    current = prim_path.GetParentPath()
    while current != Sdf.Path.absoluteRootPath:
        ancestors.append(current)
        current = current.GetParentPath()
    # Create from root downward.
    for anc in reversed(ancestors):
        if not layer.GetPrimAtPath(anc):
            Sdf.CreatePrimInLayer(layer, anc)


def _rewrite_asset_paths(layer):
    """Prepend ``../`` to relative texture paths so they resolve from materials/."""
    def _visit(prim_spec):
        for attr_spec in prim_spec.attributes.values():
            if attr_spec.typeName != Sdf.ValueTypeNames.Asset:
                continue
            val = attr_spec.default
            if not val:
                continue
            path_str = val.path if isinstance(val, Sdf.AssetPath) else str(val)
            if not path_str:
                continue
            # Only rewrite relative paths that point into textures/.
            if path_str.startswith("textures/"):
                attr_spec.default = Sdf.AssetPath(f"../{path_str}")
        for child in prim_spec.nameChildren.values():
            _visit(child)

    for prim_spec in layer.rootPrims:
        _visit(prim_spec)
