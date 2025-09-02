import bpy, urllib.request, json, tempfile, os, ssl, time

# --- Cache settings ---
THIS_DIR = os.path.dirname(__file__)
CACHE_DIR = os.path.join(THIS_DIR, ".cache_updater")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_MANIFEST = os.path.join(CACHE_DIR, "manifest.json")
# Zip cache path template
ZIP_CACHE_TPL = os.path.join(CACHE_DIR, "edge_straighten_pro_v{ver}.zip")
# How long (seconds) to trust cached manifest before re-fetching
MANIFEST_TTL = 60 * 60 * 24  # 24 hours

# >>> REPO AYARLARI (seninkiler) <<<
OWNER  = "oguzfaruk"
REPO   = "edge_straighten_pro"    # alt çizgili
BRANCH = "main"

MANIFEST_URL = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/update_manifest.json"
ZIP_URL      = "https://github.com/{OWNER}/{REPO}/releases/download/v{ver}/edge_straighten_pro_v{ver}.zip".format

# GitHub bazı ortamlarda User-Agent isteyebiliyor; SSL context de ekleyelim:
_CTX = ssl.create_default_context()
_HEADERS = {"User-Agent": "EdgeStraightenPro-Updater/1.0"}

def _get_local_version():
    try:
        pkg = __package__ if isinstance(__package__, str) and __package__ else None
        if not pkg:
            return (0, 0, 0)

        prefs = getattr(bpy, "context", None)
        if prefs is None:
            return (0, 0, 0)
        addons = getattr(prefs.preferences, "addons", None)
        bl_info = None

        if addons is not None:
            addon = addons.get(pkg)
            if addon is not None:
                # Some Blender builds expose bl_info directly on the Addon proxy,
                # others do not. Try both addon.bl_info and importing the module.
                bl_info = getattr(addon, "bl_info", None)
                if bl_info is None:
                    modname = getattr(addon, "module", None)
                    if isinstance(modname, str):
                        try:
                            import importlib
                            mod = importlib.import_module(modname)
                            bl_info = getattr(mod, "bl_info", None)
                        except Exception:
                            bl_info = None

        # Fallback: try importing package by name
        if bl_info is None:
            try:
                import importlib
                mod = importlib.import_module(pkg)
                bl_info = getattr(mod, "bl_info", None)
            except Exception:
                bl_info = None

        if bl_info:
            ver = bl_info.get("version")
            if isinstance(ver, (list, tuple)):
                return tuple(ver)
        return (0, 0, 0)
    except Exception:
        return (0, 0, 0)

def _tuple(v): return tuple(v) if isinstance(v,(list,tuple)) else (0,0,0)
def _newer(a,b): return a > b

def fetch_remote():
    # Use cached manifest if recent enough
    try:
        if os.path.exists(CACHE_MANIFEST):
            mtime = os.path.getmtime(CACHE_MANIFEST)
            if time.time() - mtime < MANIFEST_TTL:
                with open(CACHE_MANIFEST, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return _tuple(data.get("version", (0, 0, 0))), data.get("notes", "")

        # Otherwise fetch from network and cache
        req = urllib.request.Request(MANIFEST_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10, context=_CTX) as r:
            raw = r.read().decode("utf-8")
            data = json.loads(raw)

        # write cache safely
        try:
            with open(CACHE_MANIFEST, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

        return _tuple(data.get("version", (0, 0, 0))), data.get("notes", "")
    except Exception as e:
        # If network failed but cache exists, fall back to it
        if os.path.exists(CACHE_MANIFEST):
            try:
                with open(CACHE_MANIFEST, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return _tuple(data.get("version", (0, 0, 0))), data.get("notes", "(cached)")
            except Exception:
                pass
        return None, f"{type(e).__name__}: {e}"


def read_cached_manifest():
    """Read manifest from local cache only (no network). Returns (version_tuple, notes) or (None, msg)."""
    try:
        if os.path.exists(CACHE_MANIFEST):
            with open(CACHE_MANIFEST, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _tuple(data.get("version", (0, 0, 0))), data.get("notes", "")
        return None, "No cached manifest"
    except Exception as e:
        return None, f"Cache read error: {type(e).__name__}"

def install_latest():
    remote, msg = fetch_remote()
    if not remote:
        return f"Cannot fetch remote manifest. {msg}"
    local = _get_local_version()
    if not _newer(remote, local):
        return "Already up to date."

    ver = ".".join(map(str, remote))
    url = ZIP_URL(ver=ver)

    # Prefer cached zip if available to avoid re-downloading
    cached_zip = ZIP_CACHE_TPL.format(ver=ver)
    if os.path.exists(cached_zip):
        zip_path = cached_zip
    else:
        # download to cache
        zip_path = cached_zip
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as r, open(zip_path, "wb") as f:
                f.write(r.read())
        except Exception as e:
            return f"Download failed: {e}"

    try:
        bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
        bpy.ops.preferences.addon_enable(module=__package__)
        return f"Updated to v{ver} (installed from {'cache' if os.path.exists(cached_zip) else 'download'})"
    except Exception as e:
        return f"Install failed: {e}"

# ---- UI helpers ----
def draw_notice(layout):
    # IMPORTANT: avoid network calls inside draw() — use cached manifest only.
    try:
        remote, msg = read_cached_manifest()
        local = _get_local_version()

        if remote and _newer(remote, local):
            row = layout.row(); row.alert = True
            row.label(text=f"Update available (v{'.'.join(map(str,remote))})", icon="IMPORT")
            row.operator("wm.estraighten_update", text="Install")
            # allow user to see release notes briefly
            if msg:
                layout.label(text=str(msg))
            return

        # No cached newer version found — show status and a manual check button
        if remote:
            layout.label(text="Up to date (cached)", icon="CHECKMARK")
        else:
            layout.label(text=msg or "No cached update info", icon="INFO")

        # Manual 'check now' button: this runs the network-fetching operator.
        layout.operator("wm.estraighten_update", text="Check & Install Latest")
    except Exception:
        # Keep UI safe — do nothing if anything goes wrong
        try:
            layout.label(text="Updater unavailable", icon="ERROR")
        except Exception:
            pass

class WM_OT_estraighten_update(bpy.types.Operator):
    bl_idname = "wm.estraighten_update"
    bl_label = "Install Latest Edge Straighten Pro"
    bl_options = {'INTERNAL'}
    def execute(self, ctx):
        self.report({'INFO'}, install_latest())
        return {'FINISHED'}

def register(): bpy.utils.register_class(WM_OT_estraighten_update)
def unregister():
    try: bpy.utils.unregister_class(WM_OT_estraighten_update)
    except Exception: pass
