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


class BLENDERTORCP_OT_add_geometry_variant_target(Operator):
    """Add a mesh target to the selected geometry variant"""
    bl_idname = "blendertorcp.add_geometry_variant_target"
    bl_label = "Add Target"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}

        variant_set = obj.blendertorcp_geometry_variants
        idx = variant_set.active_variant_index
        if idx < 0 or idx >= len(variant_set.variants):
            self.report({'ERROR'}, "No variant selected.")
            return {'CANCELLED'}

        variant = variant_set.variants[idx]
        variant.targets.add()
        variant.active_target_index = len(variant.targets) - 1
        return {'FINISHED'}


class BLENDERTORCP_OT_remove_geometry_variant_target(Operator):
    """Remove the selected mesh target from the geometry variant"""
    bl_idname = "blendertorcp.remove_geometry_variant_target"
    bl_label = "Remove Target"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}

        variant_set = obj.blendertorcp_geometry_variants
        vidx = variant_set.active_variant_index
        if vidx < 0 or vidx >= len(variant_set.variants):
            return {'CANCELLED'}

        variant = variant_set.variants[vidx]
        tidx = variant.active_target_index
        if tidx < 0 or tidx >= len(variant.targets):
            return {'CANCELLED'}

        variant.targets.remove(tidx)
        variant.active_target_index = min(
            tidx, max(0, len(variant.targets) - 1)
        )
        return {'FINISHED'}


class BLENDERTORCP_OT_apply_geometry_variant(Operator):
    """Preview the selected variant by showing only its target meshes"""
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

        active_variant = variant_set.variants[idx]
        active_targets = {
            t.target_object for t in active_variant.targets if t.target_object
        }

        all_targets = set()
        for variant in variant_set.variants:
            for t in variant.targets:
                if t.target_object:
                    all_targets.add(t.target_object)

        for target in all_targets:
            target.hide_set(target not in active_targets)

        if active_targets:
            self.report(
                {'INFO'},
                f"Previewing geometry variant '{active_variant.name}' "
                f"({len(active_targets)} mesh{'es' if len(active_targets) != 1 else ''})",
            )

        return {'FINISHED'}


_classes = (
    BLENDERTORCP_OT_add_geometry_variant,
    BLENDERTORCP_OT_remove_geometry_variant,
    BLENDERTORCP_OT_add_geometry_variant_target,
    BLENDERTORCP_OT_remove_geometry_variant_target,
    BLENDERTORCP_OT_apply_geometry_variant,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
