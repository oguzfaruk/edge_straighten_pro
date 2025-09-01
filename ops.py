import bpy
import bmesh
from mathutils import Vector, kdtree


# -----------------------------
# Helpers
# -----------------------------
def _smooth01(x: float) -> float:
    x = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
    return x * x * (3.0 - 2.0 * x)


def _selected_edges(bm: bmesh.types.BMesh):
    bm.edges.ensure_lookup_table()
    return [e for e in bm.edges if e.select]


def _bbox_world_radius(obj: bpy.types.Object, frac: float = 0.15) -> float:
    """Return a radius based on object's world-space bounding box."""
    mw = obj.matrix_world
    coords = [mw @ Vector(corner) for corner in obj.bound_box]
    minv = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
    maxv = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
    diag = (maxv - minv).length
    return diag * frac


# -----------------------------
# Operator
# -----------------------------
class MESH_OT_straighten_loop_and_propagate(bpy.types.Operator):
    """Straighten the SELECTED EDGE LOOP along an axis, then propagate delta with falloff.
    NOTE: En iyi sonuç için önce Alt+Click ile merkez edge loop'u seç.
    """
    bl_idname = "mesh.estraighten_loop"
    bl_label = "Straighten Loop & Propagate"
    bl_options = {'REGISTER', 'UNDO'}

    axis = bpy.props.EnumProperty(
        name="Axis",
        description="Line direction (the other two axes will be flattened)",
        items=[
            ("X", "X", "Line along X (flatten Y,Z)"),
            ("Y", "Y", "Line along Y (flatten X,Z)"),
            ("Z", "Z", "Line along Z (flatten X,Y)"),
        ],
        default="Y",
    )

    flatten_to_zero = bpy.props.BoolProperty(
        name="Flatten to 0",
        description="Use 0 for the flattened components instead of loop centroid",
        default=False,
    )

    radius = bpy.props.FloatProperty(
        name="Falloff Radius",
        description="0 = Auto (bbox-based). World units.",
        default=0.0,  # 0 → Auto
        min=0.0,
    )

    strength = bpy.props.FloatProperty(
        name="Strength",
        description="Overall influence for propagation",
        default=1.0,
        min=0.0,
        max=1.0,
    )

    smooth = bpy.props.BoolProperty(
        name="Smooth Falloff",
        description="Use smoothstep for falloff",
        default=True,
    )

    k_nearest = bpy.props.IntProperty(
        name="Nearest (KD)",
        description="Sample this many nearest loop points to blend the delta",
        default=5,
        min=1,
        max=12,
    )

    only_same_island = bpy.props.BoolProperty(
        name="Only Same Island",
        description="Aynı bağlı ada içindeki vertex'leri etkile",
        default=True,
    )

    keep_Y_when_Y_axis = bpy.props.BoolProperty(
        name="Keep Y (when Axis=Y)",
        description="Axis=Y iken yayılımda Y'yi sabit tut (yükseklik/düşey korunur)",
        default=True,
    )

    # --- Yeni: Vertex Group ile etkileyebilme ---
    use_vgroup = bpy.props.BoolProperty(
        name="Use Vertex Group",
        description="Modulate propagation by a vertex group weight (0..1)",
        default=False,
    )

    vgroup_name = bpy.props.StringProperty(
        name="Vertex Group",
        description="Name of the vertex group used to modulate propagation strength",
        default="",
    )

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

        sel_edges = _selected_edges(bm)
        if len(sel_edges) == 0:
            self.report({'ERROR'}, "Select an EDGE LOOP (Alt+Click) or at least ONE edge")
            return {'CANCELLED'}

        # ---- Loop'ı belirle (tercihen kullanıcının seçtiği kenarlar) ----
        # Eğer birden fazla edge seçiliyse: onu loop olarak kabul et.
        # Eğer tek edge seçiliyse: Blender operatörüyle loop'a genişlet (yalnızca tek halka kalsın).
        if len(sel_edges) == 1:
            try:
                # Geçerli edit selection'dan loop'u genişlet
                bpy.ops.mesh.loop_select()  # Alt+Click'e denk davranış
            except Exception:
                pass
            sel_edges = _selected_edges(bm)

        # Loop verteks seti:
        loop_verts = {v for e in sel_edges for v in e.verts}
        if len(loop_verts) < 2:
            self.report({'ERROR'}, "Edge loop could not be determined. Alt+Click ile loop'u seçmeyi dene.")
            return {'CANCELLED'}

        # ---- Ada filtresi (isteğe bağlı) ----
        island_mask = None
        if self.only_same_island:
            # basit bağlı bileşen: loop'taki vertexlerden BFS
            stack = list(loop_verts)
            seen = {v.index for v in loop_verts}
            while stack:
                v = stack.pop()
                for e in v.link_edges:
                    for nv in e.verts:
                        if nv.index not in seen:
                            seen.add(nv.index)
                            stack.append(nv)
            island_mask = seen  # vertex index set

        mw = obj.matrix_world
        imw = mw.inverted()

        # ---- Auto Radius (gerekirse) ----
        R = self.radius if self.radius > 0.0 else _bbox_world_radius(obj, 0.15)

        # ---- Loop world-space pozisyonları ve centroid ----
        loop_world = [mw @ v.co for v in loop_verts]
        centroid = sum(loop_world, Vector((0, 0, 0))) / max(1, len(loop_world))

        keep_idx = {"X": 0, "Y": 1, "Z": 2}[self.axis]
        flat_idxs = [i for i in (0, 1, 2) if i != keep_idx]

        target_vals = [centroid.x, centroid.y, centroid.z]
        if self.flatten_to_zero:
            target_vals[flat_idxs[0]] = 0.0
            target_vals[flat_idxs[1]] = 0.0

        # ---- Loop'u düzleştir & delta'ları kaydet ----
        deltas = {}
        before = {}
        for v in loop_verts:
            Pw = mw @ v.co
            newc = [Pw.x, Pw.y, Pw.z]
            newc[flat_idxs[0]] = target_vals[flat_idxs[0]]
            newc[flat_idxs[1]] = target_vals[flat_idxs[1]]
            newP = Vector(newc)
            before[v.index] = Pw
            deltas[v.index] = (newP - Pw)

        for v in loop_verts:
            v.co = imw @ (before[v.index] + deltas[v.index])

        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)

        # ---- KD-tree: LOOP'un ESKİ pozisyonları ----
        kd = kdtree.KDTree(len(before))
        index_to_vid = []
        for i, (vid, pos) in enumerate(before.items()):
            kd.insert(pos, i)
            index_to_vid.append(vid)
        kd.balance()

        # Local copies for speed
        S = self.strength
        K = max(1, self.k_nearest)
        keepY = (self.axis == "Y") and self.keep_Y_when_Y_axis

        # Vertex group pre-setup
        use_vg = self.use_vgroup and bool(self.vgroup_name)
        vg_index = None
        deform_layer = None
        if use_vg:
            vg = obj.vertex_groups.get(self.vgroup_name)
            if vg is None:
                self.report({'WARNING'}, f"Vertex group '{self.vgroup_name}' not found — disabling vgroup modulation")
                use_vg = False
            else:
                vg_index = vg.index
                deform_layer = bm.verts.layers.deform.active

        affected = 0
        max_shift = 0.0

        # ---- Yayılım ----
        for v in bm.verts:
            if v in loop_verts:
                continue
            if island_mask and (v.index not in island_mask):
                continue

            Pw = mw @ v.co
            near = kd.find_n(Pw, K)
            if not near:
                continue

            accum = Vector((0, 0, 0))
            wsum = 0.0
            for (pos, idx, dist) in near:
                vid = index_to_vid[idx]
                delta = deltas[vid]

                t = 1.0 - max(0.0, min(1.0, dist / R))
                w = _smooth01(t) if self.smooth else t

                accum += delta * w
                wsum += w

            if wsum <= 1e-12:
                continue

            avg_delta = (accum / wsum) * S

            # Vertex group ile modülasyon (0..1)
            if use_vg and deform_layer is not None:
                try:
                    vg_w = v[deform_layer].get(vg_index, 0.0)
                except Exception:
                    vg_w = 0.0
                avg_delta *= vg_w

            newP = Pw + avg_delta

            if keepY:
                newP.y = Pw.y  # Y ekseninde yükseklik korunur

            v.co = imw @ newP
            affected += 1
            sh = (avg_delta if not keepY else Vector((avg_delta.x, 0.0, avg_delta.z))).length
            if sh > max_shift:
                max_shift = sh

        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
        self.report({'INFO'}, f"Loop: {len(loop_verts)} | Propagated: {affected} | Max shift: {max_shift:.5f} | Radius: {R:.2f}")
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
