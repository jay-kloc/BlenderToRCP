"""
UI panel and lists for the Material Sets system.
"""

import bpy
from bpy.types import Panel, UIList


class BLENDERTORCP_UL_material_set_slots(UIList):
    bl_idname = "BLENDERTORCP_UL_material_set_slots"

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "slot_name", text="", emboss=False, icon='NODE_MATERIAL')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='NODE_MATERIAL')


class BLENDERTORCP_UL_material_sets(UIList):
    bl_idname = "BLENDERTORCP_UL_material_sets"

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False, icon='MATERIAL')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='MATERIAL')


class BLENDERTORCP_UL_material_set_diffuses(UIList):
    bl_idname = "BLENDERTORCP_UL_material_set_diffuses"

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False, icon='IMAGE_DATA')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='IMAGE_DATA')


class BLENDERTORCP_PT_material_sets(Panel):
    bl_label = "Material Sets"
    bl_idname = "BLENDERTORCP_PT_material_sets"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        collection = obj.blendertorcp_material_sets

        # --- Slot list ---
        layout.label(text="Material Slots:", icon='NODE_MATERIAL')
        row = layout.row()
        row.template_list(
            "BLENDERTORCP_UL_material_set_slots",
            "",
            collection,
            "slots",
            collection,
            "active_slot_index",
            rows=2,
        )

        col = row.column(align=True)
        col.operator("blendertorcp.add_material_set_slot", icon='ADD', text="")
        col.operator("blendertorcp.remove_material_set_slot", icon='REMOVE', text="")

        if not collection.slots:
            return

        slot_idx = collection.active_slot_index
        if slot_idx < 0 or slot_idx >= len(collection.slots):
            return

        slot_sets = collection.slots[slot_idx]

        # Slot assignment
        row = layout.row(align=True)
        row.label(text="Slot:")
        row.prop_search(slot_sets, "slot_name", obj, "material_slots", text="")

        # --- Sets list ---
        layout.separator()
        layout.label(text="Sets:", icon='MATERIAL')
        row = layout.row()
        row.template_list(
            "BLENDERTORCP_UL_material_sets",
            "",
            slot_sets,
            "sets",
            slot_sets,
            "active_set_index",
            rows=3,
        )

        col = row.column(align=True)
        col.operator("blendertorcp.add_material_set", icon='ADD', text="")
        col.operator("blendertorcp.remove_material_set", icon='REMOVE', text="")

        if not slot_sets.sets:
            return

        set_idx = slot_sets.active_set_index
        if set_idx < 0 or set_idx >= len(slot_sets.sets):
            return

        mat_set = slot_sets.sets[set_idx]

        # --- Shared textures ---
        box = layout.box()
        box.label(text="Shared Textures:", icon='TEXTURE')
        box.prop_search(mat_set, "normal", bpy.data, "images", text="Normal")
        box.prop_search(mat_set, "occlusion", bpy.data, "images", text="Occlusion")
        box.prop_search(mat_set, "roughness", bpy.data, "images", text="Roughness")
        box.prop_search(mat_set, "metallic", bpy.data, "images", text="Metallic")

        # --- Diffuse variations ---
        box = layout.box()
        box.label(text="Diffuse Variations:", icon='IMAGE_DATA')

        row = box.row()
        row.template_list(
            "BLENDERTORCP_UL_material_set_diffuses",
            "",
            mat_set,
            "diffuses",
            mat_set,
            "active_diffuse_index",
            rows=3,
        )

        col = row.column(align=True)
        col.operator("blendertorcp.add_material_set_diffuse", icon='ADD', text="")
        col.operator("blendertorcp.remove_material_set_diffuse", icon='REMOVE', text="")

        if mat_set.diffuses:
            d_idx = mat_set.active_diffuse_index
            if 0 <= d_idx < len(mat_set.diffuses):
                diffuse = mat_set.diffuses[d_idx]
                box.prop_search(diffuse, "image", bpy.data, "images", text="Image")


_classes = (
    BLENDERTORCP_UL_material_set_slots,
    BLENDERTORCP_UL_material_sets,
    BLENDERTORCP_UL_material_set_diffuses,
    BLENDERTORCP_PT_material_sets,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
