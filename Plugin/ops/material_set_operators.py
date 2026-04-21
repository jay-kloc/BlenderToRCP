"""
Operators for the Material Sets system.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator


# --- Slot operators ---

class BLENDERTORCP_OT_add_material_set_slot(Operator):
    """Add a material slot entry for material sets"""
    bl_idname = "blendertorcp.add_material_set_slot"
    bl_label = "Add Slot"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        collection = obj.blendertorcp_material_sets
        slot_sets = collection.slots.add()
        # Default to the next unassigned material slot name.
        used = {s.slot_name for s in collection.slots if s.slot_name}
        for ms in obj.material_slots:
            if ms.name not in used:
                slot_sets.slot_name = ms.name
                break
        collection.active_slot_index = len(collection.slots) - 1
        return {'FINISHED'}


class BLENDERTORCP_OT_remove_material_set_slot(Operator):
    """Remove the selected material slot entry"""
    bl_idname = "blendertorcp.remove_material_set_slot"
    bl_label = "Remove Slot"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        collection = obj.blendertorcp_material_sets
        idx = collection.active_slot_index
        if idx < 0 or idx >= len(collection.slots):
            return {'CANCELLED'}
        collection.slots.remove(idx)
        collection.active_slot_index = min(idx, max(0, len(collection.slots) - 1))
        return {'FINISHED'}


# --- Set operators ---

class BLENDERTORCP_OT_add_material_set(Operator):
    """Add a new material set to the active slot"""
    bl_idname = "blendertorcp.add_material_set"
    bl_label = "Add Material Set"
    bl_options = {'REGISTER', 'UNDO'}

    set_name: StringProperty(name="Name", default="Set")

    def invoke(self, context, event):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "No active object.")
            return {'CANCELLED'}
        collection = obj.blendertorcp_material_sets
        slot_idx = collection.active_slot_index
        if slot_idx < 0 or slot_idx >= len(collection.slots):
            self.report({'ERROR'}, "No slot selected.")
            return {'CANCELLED'}
        slot_sets = collection.slots[slot_idx]
        self.set_name = f"Set_{len(slot_sets.sets) + 1}"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        collection = obj.blendertorcp_material_sets
        slot_idx = collection.active_slot_index
        if slot_idx < 0 or slot_idx >= len(collection.slots):
            return {'CANCELLED'}
        slot_sets = collection.slots[slot_idx]
        new_set = slot_sets.sets.add()
        new_set.name = self.set_name
        slot_sets.active_set_index = len(slot_sets.sets) - 1
        return {'FINISHED'}


class BLENDERTORCP_OT_remove_material_set(Operator):
    """Remove the selected material set"""
    bl_idname = "blendertorcp.remove_material_set"
    bl_label = "Remove Material Set"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        collection = obj.blendertorcp_material_sets
        slot_idx = collection.active_slot_index
        if slot_idx < 0 or slot_idx >= len(collection.slots):
            return {'CANCELLED'}
        slot_sets = collection.slots[slot_idx]
        idx = slot_sets.active_set_index
        if idx < 0 or idx >= len(slot_sets.sets):
            return {'CANCELLED'}
        slot_sets.sets.remove(idx)
        slot_sets.active_set_index = min(idx, max(0, len(slot_sets.sets) - 1))
        return {'FINISHED'}


# --- Diffuse operators ---

class BLENDERTORCP_OT_add_material_set_diffuse(Operator):
    """Add a diffuse variation to the active material set"""
    bl_idname = "blendertorcp.add_material_set_diffuse"
    bl_label = "Add Diffuse"
    bl_options = {'REGISTER', 'UNDO'}

    diffuse_name: StringProperty(name="Name", default="Diffuse")

    def invoke(self, context, event):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "No active object.")
            return {'CANCELLED'}
        collection = obj.blendertorcp_material_sets
        slot_idx = collection.active_slot_index
        if slot_idx < 0 or slot_idx >= len(collection.slots):
            self.report({'ERROR'}, "No slot selected.")
            return {'CANCELLED'}
        slot_sets = collection.slots[slot_idx]
        set_idx = slot_sets.active_set_index
        if set_idx < 0 or set_idx >= len(slot_sets.sets):
            self.report({'ERROR'}, "No material set selected.")
            return {'CANCELLED'}
        mat_set = slot_sets.sets[set_idx]
        self.diffuse_name = f"Diffuse_{len(mat_set.diffuses) + 1}"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        collection = obj.blendertorcp_material_sets
        slot_idx = collection.active_slot_index
        if slot_idx < 0 or slot_idx >= len(collection.slots):
            return {'CANCELLED'}
        slot_sets = collection.slots[slot_idx]
        set_idx = slot_sets.active_set_index
        if set_idx < 0 or set_idx >= len(slot_sets.sets):
            return {'CANCELLED'}
        mat_set = slot_sets.sets[set_idx]
        diffuse = mat_set.diffuses.add()
        diffuse.name = self.diffuse_name
        mat_set.active_diffuse_index = len(mat_set.diffuses) - 1
        return {'FINISHED'}


class BLENDERTORCP_OT_remove_material_set_diffuse(Operator):
    """Remove the selected diffuse variation"""
    bl_idname = "blendertorcp.remove_material_set_diffuse"
    bl_label = "Remove Diffuse"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        collection = obj.blendertorcp_material_sets
        slot_idx = collection.active_slot_index
        if slot_idx < 0 or slot_idx >= len(collection.slots):
            return {'CANCELLED'}
        slot_sets = collection.slots[slot_idx]
        set_idx = slot_sets.active_set_index
        if set_idx < 0 or set_idx >= len(slot_sets.sets):
            return {'CANCELLED'}
        mat_set = slot_sets.sets[set_idx]
        diff_idx = mat_set.active_diffuse_index
        if diff_idx < 0 or diff_idx >= len(mat_set.diffuses):
            return {'CANCELLED'}
        mat_set.diffuses.remove(diff_idx)
        mat_set.active_diffuse_index = min(diff_idx, max(0, len(mat_set.diffuses) - 1))
        return {'FINISHED'}


_classes = (
    BLENDERTORCP_OT_add_material_set_slot,
    BLENDERTORCP_OT_remove_material_set_slot,
    BLENDERTORCP_OT_add_material_set,
    BLENDERTORCP_OT_remove_material_set,
    BLENDERTORCP_OT_add_material_set_diffuse,
    BLENDERTORCP_OT_remove_material_set_diffuse,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
