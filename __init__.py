bl_info = {
    "name": "Edge Straighten Pro",
    "author": "Oguz Ozturk + ChatGPT",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport > N Panel > Straighten",
    "description": "Select ONE edge: straighten its loop on a chosen axis and propagate the deformation to the rest of the mesh with falloff.",
    "category": "Mesh",
}

import bpy
from . import ops, ui, updater

def register():
    ops.register()
    ui.register()
    updater.register()

def unregister():
    updater.unregister()
    ui.unregister()
    ops.unregister()

if __name__ == "__main__":
    register()
