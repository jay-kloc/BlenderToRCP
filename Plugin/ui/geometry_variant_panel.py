"""
UI panel and lists for the geometry variant system.
"""

import bpy
from bpy.types import Panel, UIList


class BLENDERTORCP_UL_geometry_variants(UIList):
    bl_idname = "BLENDERTORCP_UL_geometry_variants"

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "name", text="", emboss=False, icon='MESH_DATA')
            count = len(item.targets)
            row.label(
                text=f"{count} mesh{'es' if count != 1 else ''}" if count else "(empty)",
                icon='OBJECT_DATA' if count else 'ERROR',
            )
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='MESH_DATA')


class BLENDERTORCP_UL_geometry_variant_targets(UIList):
    bl_idname = "BLENDERTORCP_UL_geometry_variant_targets"

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "target_object", text="", icon='OBJECT_DATA')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OBJECT_DATA')


class BLENDERTORCP_PT_geometry_variants(Panel):
    bl_label = "USD Geometry Variants"
    bl_idname = "BLENDERTORCP_PT_geometry_variants"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in {'MESH', 'EMPTY'}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        variant_set = obj.blendertorcp_geometry_variants

        row = layout.row()
        row.template_list(
            "BLENDERTORCP_UL_geometry_variants", "",
            variant_set, "variants",
            variant_set, "active_variant_index",
            rows=3,
        )

        col = row.column(align=True)
        col.operator("blendertorcp.add_geometry_variant", icon='ADD', text="")
        col.operator("blendertorcp.remove_geometry_variant", icon='REMOVE', text="")

        if not variant_set.variants:
            return

        idx = variant_set.active_variant_index
        if idx < 0 or idx >= len(variant_set.variants):
            return

        variant = variant_set.variants[idx]

        box = layout.box()
        box.label(text="Mesh Targets:", icon='OUTLINER_OB_MESH')

        row = box.row()
        row.template_list(
            "BLENDERTORCP_UL_geometry_variant_targets", "",
            variant, "targets",
            variant, "active_target_index",
            rows=2,
        )

        col = row.column(align=True)
        col.operator("blendertorcp.add_geometry_variant_target", icon='ADD', text="")
        col.operator("blendertorcp.remove_geometry_variant_target", icon='REMOVE', text="")

        for t in variant.targets:
            target = t.target_object
            if target and target != obj and target.parent != obj:
                box.label(
                    text=f"'{target.name}' must be parented under this object",
                    icon='ERROR',
                )

        layout.operator(
            "blendertorcp.apply_geometry_variant",
            icon='HIDE_OFF',
            text="Preview",
        )


_classes = (
    BLENDERTORCP_UL_geometry_variants,
    BLENDERTORCP_UL_geometry_variant_targets,
    BLENDERTORCP_PT_geometry_variants,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
