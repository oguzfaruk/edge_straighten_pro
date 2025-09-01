import bpy
import bmesh
from mathutils import Vector, kdtree


# -----------------------------
# Helpers
# -----------------------------
def _smooth01(x: float) -> float:
    """Classic smoothstep in [0,1]."""
    x = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
    return x * x * (3.0 - 2.0 * x)


def _collect_single_selected_edge(bm: bmesh.types.BMesh):
    """Return the single selected edge (or None)."""
    bm.edges.ensure_lookup_table()
    sel_edges = [e for e in bm.edges if e.select]
    return sel_edges[0] if len(sel_edges) == 1 else None


def _expand_to_loop():
    """Use Blender operator to expand current edge selection to its loop."""
    # requires Edit Mode + 3D View context, but usually okay in operators
    try:
        bpy.ops.mesh.loop_multi_select(ring=False)
        return True
    except Exception:
        return False


# -----------------------------
# Operator
# -----------------------------
class MESH_OT_straighten_loop_and_propagate(bpy.types.Operator):
    """Straighten the loop of the selected edge along an axis, then propagate delta to the rest with falloff."""
    bl_idname = "mesh.estraighten_loop"
    bl_label = "Straighten Loop & Propagate"
    bl_options = {'REGISTER', 'UNDO'}

    # ---- UI Properties ----
    axis: bpy.props.EnumProperty(
        name="Axis",
        description="Line direction (the other two axes will be flattened)",
        items=[
            ("X", "X", "Line along X (flatten Y,Z)"),
            ("Y", "Y", "Line along Y (flatten X,Z)"),
            ("Z", "Z", "Line along Z (flatten X,Y)"),
        ],
        default="Y",
    ) # type: ignore

    flatten_to_zero: bpy.props.BoolProperty(
        name="Flatten to 0",
        description="Use 0 for the flattened components instead of loop centroid",
        default=False,
    ) # type: ignore

    radius: bpy.props.FloatProperty(
        name="Falloff Radius",
        description="Effect radius for propagating deformation (world units). 0 means apply fully everywhere.",
        default=2.0,
        min=0.0,
    ) # type: ignore

    strength: bpy.props.FloatProperty(
        name="Strength",
        description="Overall influence for propagation",
        default=1.0,
        min=0.0,
        max=1.0,
    ) # type: ignore

    smooth: bpy.props.BoolProperty(
        name="Smooth Falloff",
        description="Use smoothstep for falloff",
        default=True,
    ) # type: ignore

    k_nearest: bpy.props.IntProperty(
        name="Nearest (KD)",
        description="Sample this many nearest loop points to blend the delta",
        default=3,
        min=1,
        max=8,
    ) # type: ignore

    # ---- main ----
    def execute(self, ctx):
        obj = ctx.object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Active object must be a Mesh")
            return {'CANCELLED'}
        if obj.mode != 'EDIT':
            self.report({'ERROR'}, "Switch to Edit Mode")
            return {'CANCELLED'}

        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        # 1) exactly one edge?
        edge = _collect_single_selected_edge(bm)
        if edge is None:
            self.report({'ERROR'}, "Select exactly ONE edge (Edge Select mode)")
            return {'CANCELLED'}

        # 2) expand to its loop (or keep as-is if expansion fails)
        _expand_to_loop()

        # 3) collect loop verts
        loop_verts = {v for e in bm.edges if e.select for v in e.verts}
        if not loop_verts:
            self.report({'ERROR'}, "Could not detect an edge loop from the selection")
            return {'CANCELLED'}

        mw = obj.matrix_world
        imw = mw.inverted()

        # 4) world-space positions and centroid
        loop_world = [mw @ v.co for v in loop_verts]
        centroid = sum(loop_world, Vector((0, 0, 0))) / max(1, len(loop_world))

        # 5) determine components to flatten vs keep (line direction axis)
        keep_idx = {"X": 0, "Y": 1, "Z": 2}[self.axis]
        flat_idxs = [i for i in (0, 1, 2) if i != keep_idx]

        # 6) target values for flattened components
        target_vals = [centroid.x, centroid.y, centroid.z]
        if self.flatten_to_zero:
            target_vals[flat_idxs[0]] = 0.0
            target_vals[flat_idxs[1]] = 0.0

        # 7) flatten loop and store deltas (world-space)
        deltas = {}   # vid -> Vector delta (world)
        before = {}   # vid -> old world position
        for v in loop_verts:
            Pw = mw @ v.co
            newc = [Pw.x, Pw.y, Pw.z]
            newc[flat_idxs[0]] = target_vals[flat_idxs[0]]
            newc[flat_idxs[1]] = target_vals[flat_idxs[1]]
            newP = Vector(newc)

            before[v.index] = Pw
            deltas[v.index] = (newP - Pw)

        # write loop new positions immediately
        for v in loop_verts:
            v.co = imw @ (before[v.index] + deltas[v.index])

        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)

        # 8) build KD-tree from BEFORE positions of loop verts (for stable sampling)
        kd = kdtree.KDTree(len(before))
        index_to_vid = []
        for i, (vid, pos) in enumerate(before.items()):
            kd.insert(pos, i)
            index_to_vid.append(vid)
        kd.balance()

        R = self.radius
        S = self.strength
        K = max(1, self.k_nearest)

        affected = 0
        max_shift = 0.0

        # 9) propagate average delta to non-loop verts
        for v in bm.verts:
            if v in loop_verts:
                continue

            Pw = mw @ v.co
            # nearest K loop points (using BEFORE positions)
            near = kd.find_n(Pw, K)
            if not near:
                continue

            accum = Vector((0, 0, 0))
            wsum = 0.0
            for (pos, idx, dist) in near:
                vid = index_to_vid[idx]
                delta = deltas[vid]

                if R <= 0.0:
                    w = 1.0
                else:
                    t = 1.0 - max(0.0, min(1.0, dist / R))
                    w = _smooth01(t) if self.smooth else t

                accum += delta * w
                wsum += w

            if wsum <= 1e-12:
                continue

            avg_delta = (accum / wsum) * S
            newP = Pw + avg_delta
            v.co = imw @ newP

            affected += 1
            sh = avg_delta.length
            if sh > max_shift:
                max_shift = sh

        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
        self.report(
            {'INFO'},
            f"Loop: {len(loop_verts)} | Propagated: {affected} | Max shift: {max_shift:.6f}"
        )
        return {'FINISHED'}


# -----------------------------
# Register
# -----------------------------
CLASSES = (MESH_OT_straighten_loop_and_propagate,)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
