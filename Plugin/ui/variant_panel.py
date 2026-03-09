"""
UI panel and list for the material variant system.
"""

import bpy
from bpy.types import Panel, UIList


class BLENDERTORCP_UL_material_variants(UIList):
    bl_idname = "BLENDERTORCP_UL_material_variants"

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False, icon='MATERIAL')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='MATERIAL')


class BLENDERTORCP_PT_material_variants(Panel):
    bl_label = "USD Material Variants"
    bl_idname = "BLENDERTORCP_PT_material_variants"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.material_slots

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        variant_set = obj.blendertorcp_material_variants

        row = layout.row()
        row.template_list(
            "BLENDERTORCP_UL_material_variants",
            "",
            variant_set,
            "variants",
            variant_set,
            "active_variant_index",
            rows=3,
        )

        col = row.column(align=True)
        col.operator("blendertorcp.add_material_variant", icon='ADD', text="")
        col.operator("blendertorcp.remove_material_variant", icon='REMOVE', text="")

        if not variant_set.variants:
            return

        idx = variant_set.active_variant_index
        if idx < 0 or idx >= len(variant_set.variants):
            return

        variant = variant_set.variants[idx]
        box = layout.box()
        box.label(text="Slot Assignments:", icon='NODE_MATERIAL')
        for i, assignment in enumerate(variant.slot_assignments):
            row = box.row(align=True)
            row.label(text=f"Slot {i}")
            row.prop(assignment, "material", text="")

        row = layout.row(align=True)
        row.operator(
            "blendertorcp.apply_material_variant",
            icon='CHECKMARK',
            text="Apply",
        )
        row.operator(
            "blendertorcp.update_material_variant",
            icon='FILE_REFRESH',
            text="Update",
        )


_classes = (
    BLENDERTORCP_UL_material_variants,
    BLENDERTORCP_PT_material_variants,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
