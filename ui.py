import bpy
from . import updater

class VIEW3D_PT_edge_straighten(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Straighten"
    bl_label = "Edge Straighten Pro"

    def draw(self, ctx):
        layout = self.layout
        updater.draw_notice(layout)

        col = layout.column(align=True)
        col.label(text="Edit Mode • ONE edge/LOOP selected")
        col.operator("mesh.estraighten_loop", text="Straighten Loop & Propagate")

        box = layout.box()
        box.prop(ctx.scene, "esp_axis")
        box.prop(ctx.scene, "esp_flatten_zero")
        box.prop(ctx.scene, "esp_radius")        # 0 = Auto
        box.prop(ctx.scene, "esp_strength")
        box.prop(ctx.scene, "esp_smooth")
        box.prop(ctx.scene, "esp_knearest")
        box.prop(ctx.scene, "esp_only_same_island")
        box.prop(ctx.scene, "esp_keep_y_when_y_axis")

        op = layout.operator("mesh.estraighten_loop", text="Run with Scene Settings")
        op.axis = ctx.scene.esp_axis
        op.flatten_to_zero = ctx.scene.esp_flatten_zero
        op.radius = ctx.scene.esp_radius
        op.strength = ctx.scene.esp_strength
        op.smooth = ctx.scene.esp_smooth
        op.k_nearest = ctx.scene.esp_knearest
        op.only_same_island = ctx.scene.esp_only_same_island
        op.keep_Y_when_Y_axis = ctx.scene.esp_keep_y_when_y_axis


class ADDON_PREFERENCES_edge_straighten(bpy.types.AddonPreferences):
    bl_idname = __package__
    auto_check: bpy.props.BoolProperty(name="Auto check updates", default=True)
    def draw(self, ctx):
        updater.draw_prefs(self.layout, self)


CLASSES = (VIEW3D_PT_edge_straighten, ADDON_PREFERENCES_edge_straighten)

def register():
    for c in CLASSES:
        bpy.utils.register_class(c)

    # Scene props
    bpy.types.Scene.esp_axis = bpy.props.EnumProperty(
        items=[("X","X",""),("Y","Y",""),("Z","Z","")], default="Y", name="Axis")
    bpy.types.Scene.esp_flatten_zero = bpy.props.BoolProperty(default=False, name="Flatten to 0")
    bpy.types.Scene.esp_radius = bpy.props.FloatProperty(default=0.0, min=0.0, name="Radius (0=Auto)")
    bpy.types.Scene.esp_strength = bpy.props.FloatProperty(default=1.0, min=0.0, max=1.0, name="Strength")
    bpy.types.Scene.esp_smooth = bpy.props.BoolProperty(default=True, name="Smooth Falloff")
    bpy.types.Scene.esp_knearest = bpy.props.IntProperty(default=5, min=1, max=12, name="Nearest (KD)")
    bpy.types.Scene.esp_only_same_island = bpy.props.BoolProperty(default=True, name="Only Same Island")
    bpy.types.Scene.esp_keep_y_when_y_axis = bpy.props.BoolProperty(
        default=True, name="Keep Y when Axis=Y")

def unregister():
    del bpy.types.Scene.esp_axis
    del bpy.types.Scene.esp_flatten_zero
    del bpy.types.Scene.esp_radius
    del bpy.types.Scene.esp_strength
    del bpy.types.Scene.esp_smooth
    del bpy.types.Scene.esp_knearest
    del bpy.types.Scene.esp_only_same_island
    del bpy.types.Scene.esp_keep_y_when_y_axis
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
