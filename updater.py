import bpy, urllib.request, json, tempfile, os

# Repo ayarları — bunları KENDİ repo adına göre düzenle
OWNER = "oguz-ozturk"
REPO  = "edge-straighten-pro"
MANIFEST_URL = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/main/update_manifest.json"
ZIP_URL      = "https://github.com/{OWNER}/{REPO}/releases/download/v{ver}/edge_straighten_pro_v{ver}.zip".format

def _get_local_version():
    # __package__ = "edge_straighten_pro"
    addon = bpy.context.preferences.addons.get(__package__)
    if addon:
        return addon.bl_info.get("version", (0,0,0))
    return (0,0,0)

def _tuple(v): return tuple(v) if isinstance(v,(list,tuple)) else (0,0,0)
def _newer(a,b): return a > b

def fetch_remote():
    try:
        with urllib.request.urlopen(MANIFEST_URL, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        return _tuple(data.get("version",(0,0,0))), data.get("notes","")
    except Exception as e:
        return None, f"Update check failed: {e}"

def install_latest():
    remote, _ = fetch_remote()
    if not remote: return "Cannot fetch remote manifest."
    local = _get_local_version()
    if not _newer(remote, local):
        return "Already up to date."
    ver = ".".join(map(str, remote))
    url = ZIP_URL(ver=ver)
    tmp = os.path.join(tempfile.gettempdir(), os.path.basename(url))
    try:
        urllib.request.urlretrieve(url, tmp)
        bpy.ops.preferences.addon_install(filepath=tmp, overwrite=True)
        bpy.ops.preferences.addon_enable(module=__package__)
        return f"Updated to v{ver}"
    except Exception as e:
        return f"Install failed: {e}"

# --- UI yardımcıları
def draw_notice(layout):
    remote, msg = fetch_remote()
    if not remote:
        layout.label(text="Update check failed", icon="ERROR")
        return
    local = _get_local_version()
    if _newer(remote, local):
        row = layout.row()
        row.alert = True
        row.operator("wm.estraighten_update", text=f"Update available: v{'.'.join(map(str,remote))}", icon="IMPORT")
    else:
        layout.label(text="Up to date", icon="CHECKMARK")

def draw_prefs(layout, prefs):
    col = layout.column(align=True)
    col.label(text="Updates")
    col.operator("wm.estraighten_update", text="Install Latest")

class WM_OT_estraighten_update(bpy.types.Operator):
    bl_idname = "wm.estraighten_update"
    bl_label = "Install Latest Edge Straighten Pro"
    bl_options = {'INTERNAL'}

    def execute(self, ctx):
        report = install_latest()
        self.report({'INFO'}, report)
        return {'FINISHED'}

def register():
    bpy.utils.register_class(WM_OT_estraighten_update)

def unregister():
    try:
        bpy.utils.unregister_class(WM_OT_estraighten_update)
    except Exception:
        pass
