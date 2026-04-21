"""
USD post-processing pipeline for RealityKit compatibility.

Runs scene normalization, material rewriting, and texture preparation.
"""

from .materials.rewrite import rewrite_materials
from .materials.externalize import externalize_materials
from .material_sets_export import export_material_sets, rebuild_materials_from_sets
from .materialx_orm_packing import pack_materialx_orm_textures
from .pbr_texture_packing import pack_orm_textures
from .usd_animation_library import author_animation_library
from .usd_scene import normalize_scene
from .usd_tangents import author_mesh_tangents
from .usd_textures import prepare_textures
from .usd_variants import author_material_variants
from .usd_geometry_variants import author_geometry_variants
from .usd_variants_realitykit import (
    author_material_variants_realitykit,
    author_geometry_variants_realitykit,
)
from .usd_utils import Usd, require_pxr


def process_usd_stage(usd_path: str, settings, context, diagnostics=None) -> None:
    """Post-process a USD stage for RealityKit compatibility."""
    require_pxr()

    stage = Usd.Stage.Open(usd_path, Usd.Stage.LoadAll)
    if not stage:
        raise RuntimeError(f"Failed to open USD stage: {usd_path}")

    normalize_scene(stage, settings)
    author_mesh_tangents(stage, context, settings, diagnostics)

    material_mode = getattr(settings, "material_mode", "SHADER_GRAPH")

    orm_resolution = int(getattr(settings, "orm_texture_resolution", "1024"))

    if material_mode == 'SHADER_GRAPH':
        rewrite_materials(stage, settings, context, diagnostics)
        pack_materialx_orm_textures(
            stage, usd_path, context, diagnostics,
            orm_resolution=orm_resolution,
        )
    elif material_mode == 'PBR':
        pack_orm_textures(stage, usd_path, context, diagnostics, orm_resolution=orm_resolution)

    variant_mode = getattr(settings, "variant_mode", "RCP")

    if variant_mode == "REALITYKIT":
        # Material variants run first so they can find all mesh prims
        # (before geometry variants move some into variant bodies).
        # Material bindings are NOT cleared in RealityKit mode;
        # the materialVariant is listed first in variantSetNames so
        # its opinions win via USD composition ordering.
        author_material_variants_realitykit(stage, context, settings, diagnostics)
        author_geometry_variants_realitykit(stage, context, settings, diagnostics)
    else:
        author_material_variants(stage, context, settings, diagnostics)
        author_geometry_variants(stage, context, settings, diagnostics)

    author_animation_library(stage, settings, diagnostics)

    prepare_textures(stage, usd_path, settings, diagnostics)
    externalize_materials(stage, usd_path, diagnostics)
    export_material_sets(stage, usd_path, settings, context, diagnostics)
    rebuild_materials_from_sets(stage, usd_path, context, diagnostics)

    stage.Save()

    if diagnostics:
        diagnostics.add_warning("USD stage post-processed for RealityKit compatibility")
