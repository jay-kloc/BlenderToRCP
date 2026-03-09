"""
Property groups for the geometry variant system.

Each geometry variant references one or more Blender mesh objects
parented under the owner.  At USD export time the child prim specs
are moved into variant bodies so that switching the geometryVariant
swaps the visible geometry.
"""

import bpy
from bpy.props import IntProperty, PointerProperty, CollectionProperty
from bpy.types import PropertyGroup


def _mesh_object_poll(self, obj):
    return obj.type == 'MESH'


class BLENDERTORCP_GeometryVariantTarget(PropertyGroup):
    """A single mesh-object pointer inside a geometry variant."""
    target_object: PointerProperty(
        type=bpy.types.Object,
        name="Mesh Object",
        poll=_mesh_object_poll,
    )


class BLENDERTORCP_GeometryVariantEntry(PropertyGroup):
    """A named geometry variant containing one or more mesh targets."""
    targets: CollectionProperty(
        type=BLENDERTORCP_GeometryVariantTarget,
    )
    active_target_index: IntProperty(default=0)


class BLENDERTORCP_GeometryVariantSet(PropertyGroup):
    """Collection of geometry variants on an object."""
    variants: CollectionProperty(
        type=BLENDERTORCP_GeometryVariantEntry,
    )
    active_variant_index: IntProperty(default=0)


_classes = (
    BLENDERTORCP_GeometryVariantTarget,
    BLENDERTORCP_GeometryVariantEntry,
    BLENDERTORCP_GeometryVariantSet,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.blendertorcp_geometry_variants = PointerProperty(
        type=BLENDERTORCP_GeometryVariantSet,
    )


def unregister():
    del bpy.types.Object.blendertorcp_geometry_variants
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
