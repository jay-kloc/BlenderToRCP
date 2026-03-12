"""
ORM texture packing for UsdPreviewSurface PBR materials.

Combines separate AO, Roughness and Metallic textures into a single
ORM image (R=AO, G=Roughness, B=Metallic) and rewires the USD material
graph to use per-channel outputs from the packed texture.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .usd_utils import Sdf, UsdShade


def pack_orm_textures(stage, usd_path: str, context, diagnostics=None, orm_resolution: int = 1024) -> None:
    """Find PBR materials and pack metallic/roughness/AO into ORM textures."""
    usd_dir = Path(usd_path).parent
    textures_dir = usd_dir / "textures"
    textures_dir.mkdir(exist_ok=True)

    # Gather all texture info in a read-only pass before any stage mutation.
    # RemovePrim invalidates the Traverse iterator and can destroy texture
    # prims shared across materials, causing subsequent reads to fail.
    materials_to_pack = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Material):
            continue
        material = UsdShade.Material(prim)
        surface_output = material.GetSurfaceOutput()
        if not surface_output:
            continue
        connected_source = surface_output.GetConnectedSource()
        if not connected_source or not connected_source[0]:
            continue

        pbr_shader = UsdShade.Shader(connected_source[0].GetPrim())
        shader_id = pbr_shader.GetIdAttr().Get()
        if shader_id != "UsdPreviewSurface":
            continue

        metallic_info = _get_texture_info(pbr_shader, "metallic", usd_dir)
        roughness_info = _get_texture_info(pbr_shader, "roughness", usd_dir)
        metallic_value = _get_scalar_value(pbr_shader, "metallic", 0.0)
        roughness_value = _get_scalar_value(pbr_shader, "roughness", 0.5)
        kept_infos = {}
        for input_name in ("diffuseColor", "normal", "emissiveColor", "opacity"):
            info = _get_texture_info(pbr_shader, input_name, usd_dir)
            if info:
                kept_infos[input_name] = info

        materials_to_pack.append((
            prim, pbr_shader, metallic_info, roughness_info,
            metallic_value, roughness_value, kept_infos,
        ))

    for entry in materials_to_pack:
        (prim, pbr_shader, metallic_info, roughness_info,
         metallic_value, roughness_value, kept_infos) = entry
        _pack_material_orm(
            stage, usd_dir, textures_dir, prim, pbr_shader,
            metallic_info, roughness_info,
            metallic_value, roughness_value,
            kept_infos, diagnostics, orm_resolution,
        )


def _pack_material_orm(
    stage, usd_dir, textures_dir, material_prim, pbr_shader,
    metallic_info, roughness_info,
    metallic_value, roughness_value,
    kept_infos, diagnostics, orm_resolution: int = 1024,
) -> None:
    """Pack ORM for a single UsdPreviewSurface material."""
    material_name = material_prim.GetName()

    # UsdPreviewSurface has no occlusion input; AO channel is packed as
    # R for glTF/ORM convention compatibility but not wired to the shader.
    occlusion_info = None

    width, height = orm_resolution, orm_resolution

    ao_pixels = _read_single_channel(
        occlusion_info["resolved_path"] if occlusion_info else None,
        occlusion_info.get("channel", "r") if occlusion_info else "r",
        width, height, default_value=1.0,
    )
    roughness_pixels = _read_single_channel(
        roughness_info["resolved_path"] if roughness_info else None,
        roughness_info.get("channel", "r") if roughness_info else "r",
        width, height, default_value=roughness_value,
    )
    metallic_pixels = _read_single_channel(
        metallic_info["resolved_path"] if metallic_info else None,
        metallic_info.get("channel", "r") if metallic_info else "r",
        width, height, default_value=metallic_value,
    )

    if ao_pixels is None or roughness_pixels is None or metallic_pixels is None:
        if diagnostics:
            diagnostics.add_warning(
                f"Material '{material_name}': Failed to read source textures for ORM packing."
            )
        return

    orm_filename = f"{material_name}_ORM.png"
    orm_path = textures_dir / orm_filename
    _write_orm_png(orm_path, width, height, ao_pixels, roughness_pixels, metallic_pixels)

    if diagnostics:
        diagnostics.add_warning(
            f"Material '{material_name}': Packed ORM texture -> {orm_filename}"
        )

    orm_relative = f"./textures/{orm_filename}"

    # Find a texcoord connection to reuse from any existing texture node.
    texcoord_source = None
    wrap_s = "repeat"
    wrap_t = "repeat"
    for info in (metallic_info, roughness_info, occlusion_info):
        if info and info.get("texcoord_source"):
            texcoord_source = info["texcoord_source"]
            wrap_s = info.get("wrap_s", "repeat")
            wrap_t = info.get("wrap_t", "repeat")
            break

    material_path = str(material_prim.GetPath())
    orm_node_name = "ORM_Texture"
    orm_node_path = f"{material_path}/{orm_node_name}"

    orm_prim = stage.DefinePrim(orm_node_path, "Shader")
    orm_shader = UsdShade.Shader(orm_prim)
    orm_shader.CreateIdAttr("UsdUVTexture")
    orm_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(
        Sdf.AssetPath(orm_relative)
    )
    orm_shader.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("raw")
    orm_shader.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set(wrap_s)
    orm_shader.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set(wrap_t)

    if texcoord_source:
        st_input = orm_shader.CreateInput("st", Sdf.ValueTypeNames.Float2)
        st_input.ConnectToSource(texcoord_source)

    orm_out_r = orm_shader.CreateOutput("r", Sdf.ValueTypeNames.Float)
    orm_out_g = orm_shader.CreateOutput("g", Sdf.ValueTypeNames.Float)
    orm_out_b = orm_shader.CreateOutput("b", Sdf.ValueTypeNames.Float)

    # Reconnect PBR inputs to packed ORM channels.
    # R = AO (reserved, not wired -- UsdPreviewSurface has no occlusion input)
    # G = Roughness, B = Metallic
    roughness_input = pbr_shader.GetInput("roughness")
    if roughness_input and roughness_info:
        roughness_input.ConnectToSource(orm_out_g)

    metallic_input = pbr_shader.GetInput("metallic")
    if metallic_input and metallic_info:
        metallic_input.ConnectToSource(orm_out_b)

    # Paths of texture nodes still in use by other PBR inputs (pre-gathered).
    kept_paths: Set[str] = {
        info["prim_path"] for info in kept_infos.values()
    }

    # Remove old standalone texture nodes that were replaced.
    _remove_old_texture_node(stage, metallic_info, kept_paths)
    _remove_old_texture_node(stage, roughness_info, kept_paths)
    _remove_old_texture_node(stage, occlusion_info, kept_paths)


def _get_scalar_value(pbr_shader, input_name: str, default: float) -> float:
    """Read the constant scalar value of a PBR shader input."""
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


def _get_texture_info(
    pbr_shader, input_name: str, usd_dir: Path
) -> Optional[Dict]:
    """Extract texture node info for a PBR shader input."""
    shader_input = pbr_shader.GetInput(input_name)
    if not shader_input or not shader_input.HasConnectedSource():
        return None

    connected = shader_input.GetConnectedSource()
    if not connected or not connected[0]:
        return None

    source_prim = connected[0].GetPrim()
    tex_shader = UsdShade.Shader(source_prim)
    if tex_shader.GetIdAttr().Get() != "UsdUVTexture":
        return None

    output_name = connected[1]
    channel = output_name if output_name in ("r", "g", "b", "a") else "r"

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

    texcoord_source = None
    st_input = tex_shader.GetInput("st")
    if st_input and st_input.HasConnectedSource():
        texcoord_source = st_input.GetConnectedSource()
        if texcoord_source and texcoord_source[0]:
            texcoord_source = UsdShade.Shader(texcoord_source[0].GetPrim()).GetOutput(
                texcoord_source[1]
            )
        else:
            texcoord_source = None

    wrap_s_input = tex_shader.GetInput("wrapS")
    wrap_s = wrap_s_input.Get() if wrap_s_input else "repeat"
    wrap_t_input = tex_shader.GetInput("wrapT")
    wrap_t = wrap_t_input.Get() if wrap_t_input else "repeat"

    return {
        "prim_path": str(source_prim.GetPath()),
        "resolved_path": str(resolved),
        "channel": channel,
        "texcoord_source": texcoord_source,
        "wrap_s": wrap_s or "repeat",
        "wrap_t": wrap_t or "repeat",
    }


def _remove_old_texture_node(
    stage, texture_info: Optional[Dict], all_kept_paths: set
) -> None:
    """Remove a texture prim that has been replaced by the ORM node."""
    if not texture_info:
        return
    prim_path = texture_info.get("prim_path")
    if not prim_path:
        return
    if prim_path in all_kept_paths:
        return
    prim = stage.GetPrimAtPath(prim_path)
    if prim and prim.IsValid():
        stage.RemovePrim(prim_path)


# ---------------------------------------------------------------------------
# Image I/O using Blender's Python API
# ---------------------------------------------------------------------------

def _read_image_size(image_path: str) -> Tuple[int, int]:
    """Read width and height of an image via bpy."""
    try:
        import bpy
        img = bpy.data.images.load(image_path, check_existing=True)
        w, h = img.size[0], img.size[1]
        return (w, h)
    except Exception:
        return (0, 0)


def _load_raw_image(image_path: str):
    """Load an image as Non-Color to get raw pixel values.

    Using check_existing=False avoids reusing an image that may already be
    loaded with sRGB colorspace, which would cause Blender to return
    linearized pixel values instead of the raw file data.
    """
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
    """Read a single channel from an image file, or return a flat default."""
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
    """Write a packed ORM PNG using bpy."""
    import bpy

    img_name = "__orm_pack_temp__"
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
