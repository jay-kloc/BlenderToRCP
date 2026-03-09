"""
Operators for the geometry variant system.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

_OWNER_TYPES = {'MESH', 'EMPTY'}


class BLENDERTORCP_OT_add_geometry_variant(Operator):
    """Add a new geometry variant"""
    bl_idname = "blendertorcp.add_geometry_variant"
    bl_label = "Add Geometry Variant"
    bl_options = {'REGISTER', 'UNDO'}

    variant_name: StringProperty(name="Name", default="Variant")

    def invoke(self, context, event):
        obj = context.active_object
        if not obj or obj.type not in _OWNER_TYPES:
            self.report({'ERROR'}, "Select a mesh or empty object.")
            return {'CANCELLED'}
        variant_set = obj.blendertorcp_geometry_variants
        self.variant_name = f"Variant_{len(variant_set.variants) + 1}"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type not in _OWNER_TYPES:
            self.report({'ERROR'}, "No active mesh or empty object.")
            return {'CANCELLED'}

        variant_set = obj.blendertorcp_geometry_variants
        variant = variant_set.variants.add()
        variant.name = self.variant_name

        variant_set.active_variant_index = len(variant_set.variants) - 1
        return {'FINISHED'}


class BLENDERTORCP_OT_remove_geometry_variant(Operator):
    """Remove the selected geometry variant"""
    bl_idname = "blendertorcp.remove_geometry_variant"
    bl_label = "Remove Geometry Variant"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}

        variant_set = obj.blendertorcp_geometry_variants
        idx = variant_set.active_variant_index
        if idx < 0 or idx >= len(variant_set.variants):
            return {'CANCELLED'}

        variant_set.variants.remove(idx)
        variant_set.active_variant_index = min(
            idx, max(0, len(variant_set.variants) - 1)
        )
        return {'FINISHED'}


class BLENDERTORCP_OT_apply_geometry_variant(Operator):
    """Preview the selected variant by showing only its target mesh"""
    bl_idname = "blendertorcp.apply_geometry_variant"
    bl_label = "Preview Variant"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}

        variant_set = obj.blendertorcp_geometry_variants
        idx = variant_set.active_variant_index
        if idx < 0 or idx >= len(variant_set.variants):
            return {'CANCELLED'}

        active_target = variant_set.variants[idx].target_object

        for variant in variant_set.variants:
            target = variant.target_object
            if target:
                target.hide_set(target != active_target)

        if active_target:
            active_target.hide_set(False)
            self.report(
                {'INFO'},
                f"Previewing geometry variant '{variant_set.variants[idx].name}'",
            )

        return {'FINISHED'}


_classes = (
    BLENDERTORCP_OT_add_geometry_variant,
    BLENDERTORCP_OT_remove_geometry_variant,
    BLENDERTORCP_OT_apply_geometry_variant,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
