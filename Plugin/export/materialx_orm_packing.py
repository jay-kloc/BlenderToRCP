"""
ORM texture packing for MaterialX Shader Graph materials.

Finds ND_realitykit_pbr_surfaceshader nodes with separate metallic,
roughness and ambientOcclusion ND_image_float textures, packs them
into a single ORM image (R=AO, G=Roughness, B=Metallic), and rewires
the shader graph through ND_image_color3 + ND_separate3_color3.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .usd_utils import Sdf, UsdShade


# PBR inputs eligible for ORM packing (input_name -> ORM channel).
_ORM_INPUTS = {
    "ambientOcclusion": "r",
    "roughness": "g",
    "metallic": "b",
}


def pack_materialx_orm_textures(
    stage, usd_path: str, context, diagnostics=None, orm_resolution: int = 1024,
) -> None:
    """Pack metallic/roughness/AO into ORM textures for MaterialX materials."""
    usd_dir = Path(usd_path).parent
    textures_dir = usd_dir / "textures"
    textures_dir.mkdir(exist_ok=True)

    materials_info = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Material):
            continue
        material = UsdShade.Material(prim)
        surface_output = material.GetSurfaceOutput("mtlx")
        if not surface_output:
            continue
        connected = surface_output.GetConnectedSource()
        if not connected or not connected[0]:
            continue

        pbr_shader = UsdShade.Shader(connected[0].GetPrim())
        shader_id = pbr_shader.GetIdAttr().Get()
        if shader_id != "ND_realitykit_pbr_surfaceshader":
            continue

        tex_infos = {}
        scalar_values = {}
        for input_name in _ORM_INPUTS:
            info = _get_mtlx_texture_info(pbr_shader, input_name, usd_dir)
            if info:
                tex_infos[input_name] = info
            else:
                scalar_values[input_name] = _get_scalar_value(
                    pbr_shader, input_name,
                    0.0 if input_name == "metallic" else
                    0.5 if input_name == "roughness" else 1.0,
                )

        materials_info.append((
            prim, pbr_shader, tex_infos, scalar_values,
        ))

    for prim, pbr_shader, tex_infos, scalar_values in materials_info:
        _pack_single_material(
            stage, usd_dir, textures_dir, prim, pbr_shader,
            tex_infos, scalar_values, diagnostics, orm_resolution,
        )


def _pack_single_material(
    stage, usd_dir, textures_dir, material_prim, pbr_shader,
    tex_infos, scalar_values, diagnostics, orm_resolution,
) -> None:
    material_name = material_prim.GetName()
    material_path = str(material_prim.GetPath())
    width, height = orm_resolution, orm_resolution

    defaults = {
        "ambientOcclusion": 1.0,
        "roughness": 0.5,
        "metallic": 0.0,
    }

    channels = {}
    for input_name in ("ambientOcclusion", "roughness", "metallic"):
        info = tex_infos.get(input_name)
        if info:
            channels[input_name] = _read_single_channel(
                info["resolved_path"],
                info.get("channel", "r"),
                width, height,
                default_value=defaults[input_name],
            )
        else:
            val = scalar_values.get(input_name, defaults[input_name])
            channels[input_name] = [val] * (width * height)

    if any(v is None for v in channels.values()):
        if diagnostics:
            diagnostics.add_warning(
                f"Material '{material_name}': failed to read textures for ORM packing."
            )
        return

    orm_filename = f"{material_name}_ORM.png"
    orm_path = textures_dir / orm_filename
    _write_orm_png(
        orm_path, width, height,
        channels["ambientOcclusion"],
        channels["roughness"],
        channels["metallic"],
    )

    orm_relative = f"textures/{orm_filename}"

    if diagnostics:
        diagnostics.add_warning(
            f"Material '{material_name}': packed ORM texture -> {orm_filename}"
        )

    orm_image_name = "ORM_Image"
    orm_image_path = f"{material_path}/{orm_image_name}"
    orm_prim = stage.DefinePrim(orm_image_path, "Shader")
    orm_shader = UsdShade.Shader(orm_prim)
    orm_shader.CreateIdAttr("ND_image_color3")
    orm_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(
        Sdf.AssetPath(orm_relative)
    )
    orm_out = orm_shader.CreateOutput("out", Sdf.ValueTypeNames.Color3f)

    sep_name = "ORM_Separate"
    sep_path = f"{material_path}/{sep_name}"
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

    old_prim_paths: Set[str] = set()

    # Connect ALL three PBR inputs to the ORM separate channels,
    # regardless of whether they originally had textures or scalars.
    for input_name in ("ambientOcclusion", "roughness", "metallic"):
        pbr_input = pbr_shader.GetInput(input_name)
        if not pbr_input:
            pbr_input = pbr_shader.CreateInput(
                input_name, Sdf.ValueTypeNames.Float
            )
        pbr_input.GetAttr().Clear()
        pbr_input.ConnectToSource(channel_outputs[input_name])

        info = tex_infos.get(input_name)
        if info and info.get("prim_path"):
            old_prim_paths.add(info["prim_path"])

    _collect_still_used_paths(pbr_shader, old_prim_paths, tex_infos)

    for old_path in old_prim_paths:
        prim = stage.GetPrimAtPath(old_path)
        if prim and prim.IsValid():
            stage.RemovePrim(old_path)


def _collect_still_used_paths(pbr_shader, candidates: Set[str], tex_infos) -> None:
    """Remove paths from *candidates* if still referenced by other inputs."""
    packed_paths = {info["prim_path"] for info in tex_infos.values() if info.get("prim_path")}
    still_used = set()
    for inp in pbr_shader.GetInputs():
        if not inp.HasConnectedSource():
            continue
        src = inp.GetConnectedSource()
        if not src or not src[0]:
            continue
        src_path = str(src[0].GetPrim().GetPath())
        if src_path in candidates and src_path not in packed_paths:
            still_used.add(src_path)
        if src_path in packed_paths:
            continue
        if src_path in candidates:
            still_used.add(src_path)
    candidates -= still_used


# ===================================================================
# Stage introspection
# ===================================================================

def _get_mtlx_texture_info(pbr_shader, input_name: str, usd_dir: Path) -> Optional[Dict]:
    """Extract texture node info for a MaterialX PBR shader input."""
    shader_input = pbr_shader.GetInput(input_name)
    if not shader_input or not shader_input.HasConnectedSource():
        return None

    connected = shader_input.GetConnectedSource()
    if not connected or not connected[0]:
        return None

    source_prim = connected[0].GetPrim()
    tex_shader = UsdShade.Shader(source_prim)
    shader_id = tex_shader.GetIdAttr().Get()

    if shader_id == "ND_image_float":
        channel = "r"
    elif shader_id == "ND_image_color3":
        channel = "r"
    else:
        return None

    file_input = tex_shader.GetInput("file")
    if not file_input:
        return None
    asset_val = file_input.Get()
    if not asset_val:
        return None
    asset_path = asset_val.path if isinstance(asset_val, Sdf.AssetPath) else str(asset_val)
    if not asset_path:
        return None

    resolved = Path(asset_path)
    if not resolved.is_absolute():
        resolved = (usd_dir / resolved).resolve()

    return {
        "prim_path": str(source_prim.GetPath()),
        "resolved_path": str(resolved),
        "channel": channel,
    }


def _get_scalar_value(pbr_shader, input_name: str, default: float) -> float:
    shader_input = pbr_shader.GetInput(input_name)
    if not shader_input:
        return default
    val = shader_input.Get()
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ===================================================================
# Image I/O using Blender's Python API
# ===================================================================

def _load_raw_image(image_path: str):
    import bpy
    img = bpy.data.images.load(image_path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"
    return img


def _read_single_channel(
    image_path: Optional[str],
    channel: str,
    width: int,
    height: int,
    default_value: float = 0.0,
) -> Optional[List[float]]:
    pixel_count = width * height
    if not image_path or not Path(image_path).exists():
        return [default_value] * pixel_count
    try:
        import bpy
        img = _load_raw_image(image_path)
        if img.size[0] != width or img.size[1] != height:
            img.scale(width, height)
        pixels = list(img.pixels[:])
        channels = img.channels
        channel_idx = {"r": 0, "g": 1, "b": 2, "a": 3}.get(channel, 0)
        if channel_idx >= channels:
            channel_idx = 0
        result = [pixels[i * channels + channel_idx] for i in range(pixel_count)]
        bpy.data.images.remove(img)
        return result
    except Exception:
        return None


def _write_orm_png(
    output_path: Path,
    width: int,
    height: int,
    ao: List[float],
    roughness: List[float],
    metallic: List[float],
) -> None:
    import bpy
    img_name = "__mtlx_orm_pack_temp__"
    if img_name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[img_name])
    img = bpy.data.images.new(img_name, width=width, height=height, alpha=False)
    img.colorspace_settings.name = "Non-Color"
    pixel_count = width * height
    pixels = [0.0] * (pixel_count * 4)
    for i in range(pixel_count):
        base = i * 4
        pixels[base] = ao[i]
        pixels[base + 1] = roughness[i]
        pixels[base + 2] = metallic[i]
        pixels[base + 3] = 1.0
    img.pixels[:] = pixels
    img.filepath_raw = str(output_path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
