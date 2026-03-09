"""
Property groups for the material variant system.
"""

import bpy
from bpy.props import IntProperty, PointerProperty, CollectionProperty
from bpy.types import PropertyGroup


class BLENDERTORCP_MaterialSlotAssignment(PropertyGroup):
    """A single material assignment within a variant."""
    material: PointerProperty(
        type=bpy.types.Material,
        name="Material",
    )


class BLENDERTORCP_MaterialVariant(PropertyGroup):
    """A named material variant containing slot assignments."""
    slot_assignments: CollectionProperty(
        type=BLENDERTORCP_MaterialSlotAssignment,
    )


class BLENDERTORCP_MaterialVariantSet(PropertyGroup):
    """Collection of material variants on an object."""
    variants: CollectionProperty(
        type=BLENDERTORCP_MaterialVariant,
    )
    active_variant_index: IntProperty(default=0)


_classes = (
    BLENDERTORCP_MaterialSlotAssignment,
    BLENDERTORCP_MaterialVariant,
    BLENDERTORCP_MaterialVariantSet,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.blendertorcp_material_variants = PointerProperty(
        type=BLENDERTORCP_MaterialVariantSet,
    )


def unregister():
    del bpy.types.Object.blendertorcp_material_variants
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
