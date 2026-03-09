"""
Operators for the material variant system.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator


class BLENDERTORCP_OT_add_material_variant(Operator):
    """Capture current material slot assignments as a new variant"""
    bl_idname = "blendertorcp.add_material_variant"
    bl_label = "Add Material Variant"
    bl_options = {'REGISTER', 'UNDO'}

    variant_name: StringProperty(
        name="Name",
        default="Variant",
    )

    def invoke(self, context, event):
        obj = context.active_object
        if not obj or not obj.material_slots:
            self.report({'ERROR'}, "Select an object with material slots.")
            return {'CANCELLED'}
        variant_set = obj.blendertorcp_material_variants
        self.variant_name = f"Variant_{len(variant_set.variants) + 1}"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "No active object.")
            return {'CANCELLED'}

        variant_set = obj.blendertorcp_material_variants
        variant = variant_set.variants.add()
        variant.name = self.variant_name

        for slot in obj.material_slots:
            assignment = variant.slot_assignments.add()
            assignment.material = slot.material

        variant_set.active_variant_index = len(variant_set.variants) - 1
        return {'FINISHED'}


class BLENDERTORCP_OT_remove_material_variant(Operator):
    """Remove the selected material variant"""
    bl_idname = "blendertorcp.remove_material_variant"
    bl_label = "Remove Material Variant"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}

        variant_set = obj.blendertorcp_material_variants
        idx = variant_set.active_variant_index
        if idx < 0 or idx >= len(variant_set.variants):
            return {'CANCELLED'}

        variant_set.variants.remove(idx)
        variant_set.active_variant_index = min(
            idx, max(0, len(variant_set.variants) - 1)
        )
        return {'FINISHED'}


class BLENDERTORCP_OT_apply_material_variant(Operator):
    """Apply the selected variant's materials to the object slots"""
    bl_idname = "blendertorcp.apply_material_variant"
    bl_label = "Apply Variant"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}

        variant_set = obj.blendertorcp_material_variants
        idx = variant_set.active_variant_index
        if idx < 0 or idx >= len(variant_set.variants):
            return {'CANCELLED'}

        variant = variant_set.variants[idx]
        for i, assignment in enumerate(variant.slot_assignments):
            if i < len(obj.material_slots):
                obj.material_slots[i].material = assignment.material

        self.report({'INFO'}, f"Applied variant '{variant.name}'")
        return {'FINISHED'}


class BLENDERTORCP_OT_update_material_variant(Operator):
    """Update the selected variant with current material assignments"""
    bl_idname = "blendertorcp.update_material_variant"
    bl_label = "Update Variant"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}

        variant_set = obj.blendertorcp_material_variants
        idx = variant_set.active_variant_index
        if idx < 0 or idx >= len(variant_set.variants):
            return {'CANCELLED'}

        variant = variant_set.variants[idx]
        variant.slot_assignments.clear()
        for slot in obj.material_slots:
            assignment = variant.slot_assignments.add()
            assignment.material = slot.material

        self.report({'INFO'}, f"Updated variant '{variant.name}'")
        return {'FINISHED'}


_classes = (
    BLENDERTORCP_OT_add_material_variant,
    BLENDERTORCP_OT_remove_material_variant,
    BLENDERTORCP_OT_apply_material_variant,
    BLENDERTORCP_OT_update_material_variant,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
