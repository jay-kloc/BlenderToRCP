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

        # Promote texture file paths to Material-level interface inputs
        # (DiffuseTexture, NormalTexture, ORMTexture) so they are editable
        # at runtime in RealityKit.  This runs after ORM packing so the
        # graph already uses a single ORM image node.
        _promote_texture_inputs(ext_layer, mat_path)

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


# ------------------------------------------------------------------
# Interface input promotion (runs on the Sdf layer after ORM packing)
# ------------------------------------------------------------------

# PBR input names that map to interface inputs.
_PBR_INPUT_TO_IFACE = {
    "baseColor":        "DiffuseTexture",
    "normal":           "NormalTexture",
    "metallic":         "ORMTexture",
    "roughness":        "ORMTexture",
    "ambientOcclusion": "ORMTexture",
    "color":            "DiffuseTexture",
}


def _promote_texture_inputs(layer, mat_path) -> None:
    """Create Material-level interface inputs on the external layer.

    Traces PBR shader input connections to find texture ``file`` attributes,
    then creates ``DiffuseTexture``, ``NormalTexture``, ``ORMTexture``
    inputs on the Material prim and connects the texture nodes to them.
    """
    try:
        _promote_texture_inputs_impl(layer, mat_path)
    except Exception:
        pass


def _promote_texture_inputs_impl(layer, mat_path) -> None:
    mat_spec = layer.GetPrimAtPath(mat_path)
    if not mat_spec:
        return

    # Find the PBR surface shader among children.
    pbr_spec = None
    for child_spec in mat_spec.nameChildren.values():
        shader_id = child_spec.attributes.get("info:id")
        if not shader_id:
            continue
        sid = shader_id.default
        if sid and "surfaceshader" in str(sid).lower():
            pbr_spec = child_spec
            break

    if not pbr_spec:
        return

    # For each PBR input, walk the connection chain to find the image
    # node's ``file`` attribute and its asset path.
    # path_str → (iface_name, [(child_spec, attr_name)])
    collected = {}  # asset_path → iface_name
    file_attrs = []  # [(attr_spec holding file, asset_path)]

    for pbr_input_name, iface_name in _PBR_INPUT_TO_IFACE.items():
        attr_key = f"inputs:{pbr_input_name}"
        attr_spec = pbr_spec.attributes.get(attr_key)
        if not attr_spec:
            continue

        # Follow the connection chain to find the image node.
        image_file_attr, asset_path = _trace_to_file_attr(
            layer, mat_path, attr_spec
        )
        if not image_file_attr or not asset_path:
            continue

        if asset_path not in collected:
            collected[asset_path] = iface_name
        file_attrs.append((image_file_attr, asset_path))

    if not collected:
        return

    # Create interface inputs on the material spec.
    created = {}  # iface_name → Sdf.Path to the interface input
    for asset_path, iface_name in collected.items():
        if iface_name in created:
            continue
        input_attr_name = f"inputs:{iface_name}"
        input_attr = mat_spec.attributes.get(input_attr_name)
        if not input_attr:
            input_attr = Sdf.AttributeSpec(
                mat_spec, input_attr_name, Sdf.ValueTypeNames.Asset
            )
        input_attr.default = Sdf.AssetPath(asset_path)
        created[iface_name] = mat_path.AppendProperty(input_attr_name)

    # Connect each texture node's file input to the interface input
    # and clear the direct value.
    for file_attr, asset_path in file_attrs:
        iface_name = collected.get(asset_path)
        if not iface_name or iface_name not in created:
            continue
        iface_path = created[iface_name]
        file_attr.connectionPathList.prependedItems = [iface_path]
        file_attr.ClearDefaultValue()


def _trace_to_file_attr(layer, mat_path, attr_spec):
    """Follow a connection from a PBR input to the image node's ``file`` attr.

    Returns ``(file_attr_spec, asset_path_str)`` or ``(None, None)``.
    """
    # Walk up to 5 hops (PBR input → swizzle/separate → image).
    visited = set()
    current = attr_spec
    for _ in range(5):
        connections = current.connectionPathList.GetAddedOrExplicitItems()
        if not connections:
            break
        target_path = connections[0]
        if target_path in visited:
            break
        visited.add(target_path)

        # The target is an output on a shader node (e.g. /mat/image.outputs:out).
        target_prim_path = target_path.GetPrimPath()
        target_spec = layer.GetPrimAtPath(target_prim_path)
        if not target_spec:
            break

        # Check if this node has a ``file`` input with an asset path.
        file_attr = target_spec.attributes.get("inputs:file")
        if file_attr:
            val = file_attr.default
            if val:
                path_str = val.path if isinstance(val, Sdf.AssetPath) else str(val)
                if path_str:
                    return file_attr, path_str

        # Otherwise, follow this node's first connected input deeper.
        found_next = False
        for child_attr_name, child_attr in target_spec.attributes.items():
            if not child_attr_name.startswith("inputs:"):
                continue
            child_conns = child_attr.connectionPathList.GetAddedOrExplicitItems()
            if child_conns:
                current = child_attr
                found_next = True
                break
        if not found_next:
            break

    return None, None
