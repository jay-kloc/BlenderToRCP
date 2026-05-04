"""
USD post-processing pipeline for RealityKit compatibility.

Runs scene normalization, material rewriting, and texture preparation.
"""

import shutil
from pathlib import Path

from .materials.rewrite import rewrite_materials
from .materials.externalize import externalize_materials, prune_unbound_materials
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

    # Clean prior export artifacts so the asset folder reflects only this run.
    _clean_export_artifacts(usd_path)

    normalize_scene(stage, settings)
    author_mesh_tangents(stage, context, settings, diagnostics)

    material_mode = getattr(settings, "material_mode", "SHADER_GRAPH")

    orm_resolution = int(getattr(settings, "orm_texture_resolution", "1024"))
    use_material_sets = bool(getattr(settings, "use_material_sets", False))

    if material_mode == 'SHADER_GRAPH':
        rewrite_materials(stage, settings, context, diagnostics)
        # Skip ORM packing for bound materials when material sets drive
        # the final .usda — the rebuild overwrites those materials so
        # their per-material ORM textures would be orphaned.
        if not use_material_sets:
            pack_materialx_orm_textures(
                stage, usd_path, context, diagnostics,
                orm_resolution=orm_resolution,
            )
    elif material_mode == 'PBR' and not use_material_sets:
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

    # Drop materials that aren't bound to any geometry so their textures
    # won't be staged.  Blender's USD exporter dumps every scene material
    # by default, including unused ones.
    prune_unbound_materials(stage)

    if use_material_sets:
        # Material sets mode: only export material sets materials and textures.
        # Default textures from the Blender scene are NOT staged.
        externalize_materials(stage, usd_path, diagnostics)
        export_material_sets(stage, usd_path, settings, context, diagnostics)
        rebuild_materials_from_sets(stage, usd_path, context, diagnostics)
    else:
        # Default mode: only export the default materials and textures.
        prepare_textures(stage, usd_path, settings, diagnostics)
        externalize_materials(stage, usd_path, diagnostics)

    stage.Save()

    if diagnostics:
        diagnostics.add_warning("USD stage post-processed for RealityKit compatibility")


def _clean_export_artifacts(usd_path: str) -> None:
    """Remove stale materials/, textures/, and material_sets.json from prior exports."""
    usd_dir = Path(usd_path).parent
    for sub in ("materials", "textures"):
        target = usd_dir / sub
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
    json_file = usd_dir / "material_sets.json"
    if json_file.is_file():
        try:
            json_file.unlink()
        except OSError:
            pass
