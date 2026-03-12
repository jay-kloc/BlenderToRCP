"""Author tangent primvars on exported USD meshes from Blender mesh data."""

from collections import defaultdict

from .usd_utils import Gf, Sdf, UsdGeom, Vt


_BLENDER_OBJECT_ATTRS = (
    "userProperties:blenderName:object",
    "userProperties:blender:object_name",
)

_BLENDER_DATA_ATTRS = (
    "userProperties:blender:data_name",
)

_TANGENT_PRIMVAR_NAMES = (
    ("tangent", "tangents"),
    ("bitangent", "bitangents"),
)


def author_mesh_tangents(stage, context, settings, diagnostics=None) -> None:
    """Author face-varying tangent primvars from Blender loop tangents."""
    if not getattr(settings, "export_tangents", True):
        return

    try:
        import bpy  # noqa: F401
    except Exception:
        if diagnostics:
            diagnostics.add_warning("Blender Python API unavailable; tangent primvars were not authored.")
        return

    depsgraph = context.evaluated_depsgraph_get()
    object_names, data_names = _collect_mesh_objects(context, settings)

    authored = 0
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue

        mesh_obj = _resolve_blender_mesh_object(prim, object_names, data_names)
        if mesh_obj is None:
            continue

        tangent_data = _build_tangent_data(mesh_obj, depsgraph, prim, settings, diagnostics)
        if tangent_data is None:
            continue

        tangents, bitangents = tangent_data
        primvars = UsdGeom.PrimvarsAPI(prim)
        _set_vec3_face_varying_primvar(primvars, "tangent", tangents)
        _set_vec3_face_varying_primvar(primvars, "bitangent", bitangents)
        _remove_legacy_tangent_primvars(primvars)
        authored += 1

    if diagnostics and authored:
        diagnostics.add_warning(f"Authored tangent primvars for {authored} USD mesh(es)")


def _collect_mesh_objects(context, settings):
    object_names = defaultdict(list)
    data_names = defaultdict(list)

    selected_only = bool(getattr(settings, "selected_objects_only", False))
    for obj in context.scene.objects:
        if obj.type != 'MESH':
            continue
        if selected_only and not obj.select_get():
            continue
        object_names[obj.name].append(obj)
        data = getattr(obj, "data", None)
        if data is not None:
            data_names[data.name].append(obj)

    return object_names, data_names


def _set_vec3_face_varying_primvar(primvars, name, values):
    primvar = primvars.CreatePrimvar(
        name,
        Sdf.ValueTypeNames.Float3Array,
        UsdGeom.Tokens.faceVarying,
    )
    primvar.Set(values)


def _remove_legacy_tangent_primvars(primvars):
    for canonical_name, legacy_name in _TANGENT_PRIMVAR_NAMES:
        if legacy_name == canonical_name:
            continue
        legacy_primvar = primvars.GetPrimvar(legacy_name)
        if legacy_primvar and legacy_primvar.IsDefined():
            primvars.RemovePrimvar(legacy_name)


def _resolve_blender_mesh_object(prim, object_names, data_names):
    obj_name = _find_attr_in_hierarchy(prim, _BLENDER_OBJECT_ATTRS)
    if obj_name and object_names.get(obj_name):
        return object_names[obj_name][0]

    data_name = _find_attr_in_hierarchy(prim, _BLENDER_DATA_ATTRS)
    if data_name and data_names.get(data_name):
        return data_names[data_name][0]

    if object_names.get(prim.GetName()):
        return object_names[prim.GetName()][0]
    if data_names.get(prim.GetName()):
        return data_names[prim.GetName()][0]
    return None


def _find_attr_in_hierarchy(prim, attr_names):
    current = prim
    while current and current.IsValid():
        for attr_name in attr_names:
            attr = current.GetAttribute(attr_name)
            if attr and attr.IsValid():
                value = attr.Get()
                if value:
                    return str(value)
        current = current.GetParent()
    return None


def _build_tangent_data(obj, depsgraph, prim, settings, diagnostics=None):
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = None
    try:
        mesh = eval_obj.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        if mesh is None or not mesh.polygons:
            return None

        face_counts = _prim_face_counts(prim)
        if not face_counts:
            return None

        uv_name = _resolve_uvmap_name(mesh)
        if not uv_name:
            if diagnostics:
                diagnostics.add_warning(f"Mesh '{obj.name}' has no UV map; tangent primvars were skipped.")
            return None

        has_ngons = any(poly.loop_total > 4 for poly in mesh.polygons)
        if has_ngons:
            if all(int(count) == 3 for count in face_counts):
                _triangulate_temp_mesh(mesh, settings)
            else:
                if diagnostics:
                    diagnostics.add_warning(
                        f"Mesh '{obj.name}' contains n-gons. Enable 'Triangulate Meshes' so tangent primvars can be authored reliably."
                    )
                return None

        mesh.calc_tangents(uvmap=uv_name)
        loop_indices = _resolve_loop_index_order(mesh, face_counts)
        if loop_indices is None:
            if diagnostics:
                diagnostics.add_warning(
                    f"Mesh '{obj.name}' topology did not match the exported USD mesh; tangent primvars were skipped."
                )
            return None

        tangents = []
        bitangents = []
        for loop_index in loop_indices:
            loop = mesh.loops[loop_index]
            tangents.append(Gf.Vec3f(*loop.tangent))
            bitangent = getattr(loop, "bitangent", None)
            if bitangent is None:
                bitangent = _compute_bitangent(loop.normal, loop.tangent, getattr(loop, "bitangent_sign", 1.0))
            bitangents.append(Gf.Vec3f(*bitangent))

        return Vt.Vec3fArray(tangents), Vt.Vec3fArray(bitangents)
    except Exception as exc:
        if diagnostics:
            diagnostics.add_warning(f"Mesh '{obj.name}' tangent export failed: {exc}")
        return None
    finally:
        if mesh is not None:
            try:
                mesh.free_tangents()
            except Exception:
                pass
            try:
                eval_obj.to_mesh_clear()
            except Exception:
                pass


def _resolve_uvmap_name(mesh):
    uv_layers = getattr(mesh, "uv_layers", None)
    if not uv_layers:
        return None
    if getattr(uv_layers, "active_render", None):
        return uv_layers.active_render.name
    if getattr(uv_layers, "active", None):
        return uv_layers.active.name
    if len(uv_layers):
        return uv_layers[0].name
    return None


def _prim_face_counts(prim):
    counts_attr = prim.GetAttribute("faceVertexCounts")
    return list(counts_attr.Get() or []) if counts_attr else []


def _resolve_loop_index_order(mesh, counts):
    total_face_vertices = sum(int(count) for count in counts)
    if total_face_vertices == len(mesh.loops):
        return list(range(len(mesh.loops)))

    mesh.calc_loop_triangles()
    if all(int(count) == 3 for count in counts) and total_face_vertices == len(mesh.loop_triangles) * 3:
        ordered = []
        for tri in mesh.loop_triangles:
            ordered.extend(tri.loops)
        return ordered

    return None


def _triangulate_temp_mesh(mesh, settings):
    import bmesh

    quad_method = {
        "SHORTEST_DIAGONAL": "SHORT_EDGE",
        "BEAUTY": "BEAUTY",
        "FIXED": "FIXED",
        "FIXED_ALTERNATE": "ALTERNATE",
    }.get(str(getattr(settings, "quad_method", "SHORTEST_DIAGONAL") or "SHORTEST_DIAGONAL"), "SHORT_EDGE")
    ngon_method = {
        "BEAUTY": "BEAUTY",
        "EAR_CLIP": "EAR_CLIP",
    }.get(str(getattr(settings, "ngon_method", "BEAUTY") or "BEAUTY"), "BEAUTY")

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(
            bm,
            faces=list(bm.faces),
            quad_method=quad_method,
            ngon_method=ngon_method,
        )
        bm.to_mesh(mesh)
        mesh.update()
    finally:
        bm.free()


def _compute_bitangent(normal, tangent, sign):
    return (
        (normal[1] * tangent[2] - normal[2] * tangent[1]) * sign,
        (normal[2] * tangent[0] - normal[0] * tangent[2]) * sign,
        (normal[0] * tangent[1] - normal[1] * tangent[0]) * sign,
    )
