"""
Property groups for the Material Sets system.

Each set defines shared PBR textures (normal, occlusion, roughness,
metallic) and multiple diffuse variations.  On export the O/R/M channels
are packed into a single ORM texture and a JSON manifest is written.
"""

import bpy
from bpy.props import IntProperty, PointerProperty, CollectionProperty, StringProperty
from bpy.types import PropertyGroup


class BLENDERTORCP_MaterialSetDiffuse(PropertyGroup):
    """A single diffuse variation within a material set."""
    image: PointerProperty(
        type=bpy.types.Image,
        name="Diffuse",
    )


class BLENDERTORCP_MaterialSet(PropertyGroup):
    """A named material set with shared PBR textures and multiple diffuses."""
    normal: PointerProperty(
        type=bpy.types.Image,
        name="Normal",
    )
    occlusion: PointerProperty(
        type=bpy.types.Image,
        name="Occlusion",
    )
    roughness: PointerProperty(
        type=bpy.types.Image,
        name="Roughness",
    )
    metallic: PointerProperty(
        type=bpy.types.Image,
        name="Metallic",
    )
    diffuses: CollectionProperty(
        type=BLENDERTORCP_MaterialSetDiffuse,
    )
    active_diffuse_index: IntProperty(default=0)


class BLENDERTORCP_MaterialSlotSets(PropertyGroup):
    """Material sets assigned to a single material slot."""
    slot_name: StringProperty(
        name="Material Slot",
        description="Name of the material slot these sets belong to",
    )
    sets: CollectionProperty(
        type=BLENDERTORCP_MaterialSet,
    )
    active_set_index: IntProperty(default=0)


class BLENDERTORCP_MaterialSetCollection(PropertyGroup):
    """All material slot sets on an object."""
    slots: CollectionProperty(
        type=BLENDERTORCP_MaterialSlotSets,
    )
    active_slot_index: IntProperty(default=0)


_classes = (
    BLENDERTORCP_MaterialSetDiffuse,
    BLENDERTORCP_MaterialSet,
    BLENDERTORCP_MaterialSlotSets,
    BLENDERTORCP_MaterialSetCollection,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.blendertorcp_material_sets = PointerProperty(
        type=BLENDERTORCP_MaterialSetCollection,
    )


def unregister():
    del bpy.types.Object.blendertorcp_material_sets
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
