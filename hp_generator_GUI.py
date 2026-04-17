#!/usr/bin/env python3
"""
=============================================================================
  EaW Hardpoint Generator — Full GUI
  For Star Wars: Empire at War
=============================================================================

  Run from the same directory as hp_generator.py:
    python hp_generator_GUI.py
    python hp_generator_GUI.py path/to/ship_config.json

=============================================================================
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import io
import sys
import os
import contextlib
import copy
import threading
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# Generator import
# When running as a PyInstaller one-file bundle, all bundled
# data lands in sys._MEIPASS at runtime.  We add that directory
# (and the directory of this script) to sys.path so that
# hp_generator.py can always be found regardless of whether the
# user runs the .py source or a compiled executable.
# ─────────────────────────────────────────────────────────────

def _ensure_gen_importable():
    """Add the correct directory to sys.path so hp_generator can be imported."""
    import sys, os
    candidates = []
    # 1. PyInstaller one-file bundle unpacks to sys._MEIPASS
    if hasattr(sys, '_MEIPASS'):
        candidates.append(sys._MEIPASS)
    # 2. Directory of this script (covers normal .py usage and one-folder builds)
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    # 3. Current working directory (fallback)
    candidates.append(os.getcwd())
    for d in candidates:
        if d and d not in sys.path:
            sys.path.insert(0, d)

_ensure_gen_importable()

_GEN_AVAILABLE = False
try:
    import hp_generator as gen
    _GEN_AVAILABLE = True
except ImportError:
    pass

_ALO_AVAILABLE = False
try:
    import alo_reader
    _ALO_AVAILABLE = True
except ImportError:
    pass

_XML_IMPORTER_AVAILABLE = False
try:
    import hp_xml_importer
    _XML_IMPORTER_AVAILABLE = True
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────
# Constants & Palette
# ─────────────────────────────────────────────────────────────

APP_TITLE   = "Venator's EaW Hardpoint Generator"
APP_VERSION = "1.0"
MIN_W, MIN_H = 1400, 860

P = {                            # Catppuccin Mocha palette
    'bg':        '#1e1e2e',
    'crust':     '#11111b',
    'mantle':    '#181825',
    's0':        '#313244',
    's1':        '#45475a',
    's2':        '#585b70',
    'ov0':       '#6c7086',
    'ov1':       '#7f849c',
    'text':      '#cdd6f4',
    'sub0':      '#a6adc8',
    'sub1':      '#bac2de',
    'blue':      '#89b4fa',
    'sapphire':  '#74c7ec',
    'sky':       '#89dceb',
    'teal':      '#94e2d5',
    'green':     '#a6e3a1',
    'yellow':    '#f9e2af',
    'peach':     '#fab387',
    'maroon':    '#eba0ac',
    'red':       '#f38ba8',
    'mauve':     '#cba6f7',
    'pink':      '#f5c2e7',
    'rosewater': '#f5e0dc',
}

def _script_dir() -> str:
    """Return the directory that should be treated as the application root.

    This is the folder the user sees — the one containing the .exe (or .py).
    It is used for default paths: Templates/, Hardpoints/, Ship Configs/, etc.

    PyInstaller deployment modes:
      one-file  : sys.executable = path to the .exe itself.
                  sys._MEIPASS   = temp extraction folder (NOT what we want).
                  → use dirname(sys.executable)
      one-dir   : sys.executable = <dist_dir>/_internal/HardpointGenerator.exe
                  The user-facing folder is one level up.
                  → use dirname(dirname(sys.executable))  when _internal exists

    Running as a .py script:
      → use dirname(__file__)
    """
    import sys, os
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        # One-dir builds place the exe inside an _internal subfolder
        if os.path.basename(exe_dir).lower() == '_internal':
            return os.path.dirname(exe_dir)
        return exe_dir
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        # Last resort — should never happen in normal usage
        return os.path.abspath('.')


def _default_output() -> str:
    """Default output path: <script_dir>/Hardpoints/Hardpoints_NewShip.xml"""
    return str(Path(_script_dir()) / "Hardpoints" / "Hardpoints_NewShip.xml")


def _default_templates() -> str:
    """Default templates path: <script_dir>/Templates"""
    return str(Path(_script_dir()) / "Templates")


def _default_components() -> str:
    """Default output path: <script_dir>/Components"""
    return str(Path(_script_dir()) / "Components")


def _make_blank_config() -> dict:
    """Build a fresh blank config with default paths set to script-relative dirs."""
    return {
        "_comment":           "EaW Hardpoint Generator Ship Config",
        "ship_name":          "NewShip",
        "output_file":        _default_output(),
        "templates":          _default_templates(),
        "template_excludes":  [],
        "template_includes":  [],
        "components":         _default_components(),
        "component_excludes": [],
        "component_includes": [],
        "turret_models":      {"start": 1, "format": "02d"},
        "damage_particles":   {"start": 1, "format": "02d"},
        "bone_pool":          [],
        "groups":             [],
    }


# Keep a module-level BLANK_CONFIG for any code that imports it directly,
# but _new_config() always calls _make_blank_config() for fresh instances.
BLANK_CONFIG = _make_blank_config()


# ─────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────

def run_generator(func, *args, **kwargs):
    out_buf, err_buf = io.StringIO(), io.StringIO()
    success = True
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        try:
            func(*args, **kwargs)
        except SystemExit as e:
            success = e.code in (0, None)
        except Exception:
            import traceback
            err_buf.write(traceback.format_exc())
            success = False
    return success, out_buf.getvalue(), err_buf.getvalue()


def load_templates_safe(abs_path: str, excludes=None, includes=None):
    """
    Load and inheritance-resolve templates without calling sys.exit.

    excludes : list[str]  Absolute paths of files/folders to skip.
    includes : list[str]  Extra absolute paths (files or folders) to load in addition
                          to the main templates path.
    Returns (resolved_registry, raw_registry, errors).
    """
    import re as _re
    errors = []
    raw_registry = {}

    # Resolve filter paths
    excl_paths = []
    for e in (excludes or []):
        try:
            excl_paths.append(Path(e).resolve())
        except Exception:
            errors.append(f"Invalid exclude path: {e!r}")

    incl_paths = []
    for i in (includes or []):
        try:
            incl_paths.append(Path(i).resolve())
        except Exception:
            errors.append(f"Invalid include path: {i!r}")

    # Collect files from main path
    main_files = []
    if abs_path:
        p = Path(abs_path)
        if not p.exists():
            errors.append(f"Templates path not found: {abs_path}")
        elif p.is_file():
            main_files = [p.resolve()]
        else:
            main_files = [f.resolve() for f in sorted(p.rglob("*.json"))]

    # Collect extra files from includes
    extra_files = []
    for inc in incl_paths:
        if not inc.exists():
            errors.append(f"Include path not found: {inc}")
            continue
        if inc.is_file():
            if inc.suffix.lower() == '.json':
                extra_files.append(inc)
        elif inc.is_dir():
            extra_files.extend(f.resolve() for f in sorted(inc.rglob("*.json")))

    # Merge, deduplicate, preserve order (main first, then includes)
    seen: set = set()
    all_files = []
    for f in main_files + extra_files:
        if f not in seen:
            seen.add(f)
            all_files.append(f)

    # Apply excludes
    def _is_excluded(fpath: Path) -> bool:
        for excl in excl_paths:
            try:
                fpath.relative_to(excl)
                return True        # inside an excluded directory
            except ValueError:
                pass
            if fpath == excl:
                return True        # exact file match
        return False

    n_before = len(all_files)
    files = [f for f in all_files if not _is_excluded(f)]
    n_excl = n_before - len(files)
    if n_excl:
        errors.append(f"{n_excl} template file(s) excluded by filter settings.")

    if not files:
        if not abs_path and not incl_paths:
            return {}, {}, errors + ["No templates path configured."]
        elif all_files:
            return {}, {}, errors + ["All template files matched exclude filters — nothing to load."]
        else:
            return {}, {}, errors + ["No .json template files found."]

    for fpath in files:
        try:
            with open(fpath, encoding='utf-8') as f:
                text = f.read()
            text = _re.sub(r',\s*([}\]])', r'\1', text)
            data = json.loads(text)
            for tpl in data.get("templates", []):
                name = tpl.get("name", "").strip()
                if not name:
                    continue
                if name in raw_registry:
                    errors.append(f"Duplicate template '{name}' in {fpath.name}")
                tpl["_source_file"] = str(fpath)
                raw_registry[name] = tpl
        except json.JSONDecodeError as e:
            errors.append(f"JSON error in {fpath.name}: {e}")
        except Exception as e:
            errors.append(f"Error loading {fpath.name}: {e}")

    if not _GEN_AVAILABLE:
        return raw_registry, raw_registry, errors

    resolved = raw_registry
    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        try:
            resolved = gen.resolve_all_inheritance(raw_registry)
        except SystemExit:
            errors.append("Inheritance resolution failed (circular or missing parent)")
        except Exception as e:
            errors.append(f"Inheritance error: {e}")

    if err_buf.getvalue():
        errors.append(err_buf.getvalue().strip())
    return resolved, raw_registry, errors

def _default_components() -> str:
    """Default components path: <script_dir>/Components"""
    return str(Path(_script_dir()) / "Components")


def load_components_safe(abs_path: str, excludes=None, includes=None):
    """
    Load and inheritance-resolve components without calling sys.exit.
    Components share the same JSON format as templates.

    excludes : list[str]  Absolute paths of files/folders to skip.
    includes : list[str]  Extra absolute paths (files or folders) to load in addition
                          to the main components path.
    Returns (resolved_registry, raw_registry, errors).
    """
    import re as _re
    errors = []
    raw_registry = {}

    # Resolve filter paths
    excl_paths = []
    for e in (excludes or []):
        try:
            excl_paths.append(Path(e).resolve())
        except Exception:
            errors.append(f"Invalid exclude path: {e!r}")

    incl_paths = []
    for i in (includes or []):
        try:
            incl_paths.append(Path(i).resolve())
        except Exception:
            errors.append(f"Invalid include path: {i!r}")

    # Collect files from main path
    main_files = []
    if abs_path:
        p = Path(abs_path)
        if not p.exists():
            errors.append(f"Components path not found: {abs_path}")
        elif p.is_file():
            main_files = [p.resolve()]
        else:
            main_files = [f.resolve() for f in sorted(p.rglob("*.json"))]

    # Collect extra files from includes
    extra_files = []
    for inc in incl_paths:
        if not inc.exists():
            errors.append(f"Include path not found: {inc}")
            continue
        if inc.is_file():
            if inc.suffix.lower() == '.json':
                extra_files.append(inc)
        elif inc.is_dir():
            extra_files.extend(f.resolve() for f in sorted(inc.rglob("*.json")))

    # Merge, deduplicate, preserve order
    seen: set = set()
    all_files = []
    for f in main_files + extra_files:
        if f not in seen:
            seen.add(f)
            all_files.append(f)

    # Apply excludes
    def _is_excluded(fpath: Path) -> bool:
        for excl in excl_paths:
            try:
                fpath.relative_to(excl)
                return True
            except ValueError:
                pass
            if fpath == excl:
                return True
        return False

    n_before = len(all_files)
    files = [f for f in all_files if not _is_excluded(f)]
    n_excl = n_before - len(files)
    if n_excl:
        errors.append(f"{n_excl} component file(s) excluded by filter settings.")

    if not files:
        if not abs_path and not incl_paths:
            return {}, {}, errors + ["No components path configured."]
        elif all_files:
            return {}, {}, errors + ["All component files matched exclude filters — nothing to load."]
        else:
            return {}, {}, errors + ["No .json component files found."]

    for fpath in files:
        try:
            with open(fpath, encoding='utf-8') as f:
                text = f.read()
            text = _re.sub(r',\s*([}\]])', r'\1', text)
            data = json.loads(text)
            for tpl in data.get("templates", []):
                name = tpl.get("name", "").strip()
                if not name:
                    continue
                if name in raw_registry:
                    errors.append(f"Duplicate component '{name}' in {fpath.name}")
                tpl["_source_file"] = str(fpath)
                raw_registry[name] = tpl
        except json.JSONDecodeError as e:
            errors.append(f"JSON error in {fpath.name}: {e}")
        except Exception as e:
            errors.append(f"Error loading {fpath.name}: {e}")

    if not _GEN_AVAILABLE:
        return raw_registry, raw_registry, errors

    resolved = raw_registry
    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        try:
            resolved = gen.resolve_component_inheritance(raw_registry)
        except SystemExit:
            errors.append("Component inheritance resolution failed")
        except Exception as e:
            errors.append(f"Component inheritance error: {e}")

    if err_buf.getvalue():
        errors.append(err_buf.getvalue().strip())
    return resolved, raw_registry, errors

def bone_name(entry) -> str:
    """Return the primary bone (bone_a). Works for all entry formats."""
    if isinstance(entry, str):  return entry
    if isinstance(entry, dict): return entry.get("bone_a") or entry.get("bone", "")
    return ""

def bone_b_val(entry) -> str:
    """Return bone_b if explicitly set and different from bone_a, else ''."""
    if isinstance(entry, dict):
        a = entry.get("bone_a") or entry.get("bone", "")
        b = entry.get("bone_b", "")
        return b if b and b != a else ""
    return ""

def bone_c_val(entry) -> str:
    """Return bone_c if set, else ''."""
    if isinstance(entry, dict):
        return entry.get("bone_c", "")
    return ""

def bone_d_val(entry) -> str:
    """Return bone_d if set, else ''."""
    if isinstance(entry, dict):
        return entry.get("bone_d", "")
    return ""

def bone_e_val(entry) -> str:
    """Return bone_e if set, else ''."""
    if isinstance(entry, dict):
        return entry.get("bone_e", "")
    return ""

def bone_f_val(entry) -> str:
    """Return bone_f if set, else ''."""
    if isinstance(entry, dict):
        return entry.get("bone_f", "")
    return ""

def bone_custom(entry) -> str:
    if isinstance(entry, dict): return entry.get("name", "")
    return ""

def make_bone_entry(b: str, custom: str = ""):
    """Create a simple pool bone entry (bone_a = bone_b = b)."""
    return {"bone": b, "name": custom} if custom else b

def make_group_bone_entry(bone_a: str, bone_b: str = "", bone_c: str = "",
                          bone_d: str = "", bone_e: str = "", bone_f: str = "",
                          custom: str = ""):
    """
    Create a group bone entry storing bone_a through bone_f and optional custom name.
    Uses minimal representation: plain string when possible, dict only when needed.
    """
    has_dual   = bone_b and bone_b != bone_a
    has_c      = bool(bone_c)
    has_d      = bool(bone_d)
    has_e      = bool(bone_e)
    has_f      = bool(bone_f)
    has_custom = bool(custom)
    has_extra  = has_dual or has_c or has_d or has_e or has_f or has_custom

    if not has_extra:
        return bone_a

    entry: dict = {"bone_a": bone_a}
    if has_dual:   entry["bone_b"] = bone_b
    if has_c:      entry["bone_c"] = bone_c
    if has_d:      entry["bone_d"] = bone_d
    if has_e:      entry["bone_e"] = bone_e
    if has_f:      entry["bone_f"] = bone_f
    if has_custom: entry["name"]   = custom
    return entry

def resolve_path(base, rel: str) -> str:
    """Resolve *rel* to an absolute path, always anchoring relative paths to
    the program root (_script_dir()), NOT to the config file's location.

    This makes relative paths in ship configs fully portable: a config saved in
    "Ship Configs/" can reference "Templates", "Components", "Hardpoints" etc.
    using simple top-level names that resolve correctly for any user, regardless
    of where the config file itself lives within the install tree.

    Absolute paths are returned unchanged.
    The *base* parameter is accepted for API compatibility but is intentionally
    not used for relative resolution — all relative paths anchor to the program
    root so that shared configs never embed machine-specific absolute paths.
    """
    if not rel:
        return rel
    p = Path(rel)
    if p.is_absolute():
        return str(p)
    return str(Path(_script_dir()) / p)


def _setup_tv_autofit(tv: 'ttk.Treeview', col_weights: dict, scrollbar_w: int = 20):
    """
    Make a Treeview's columns auto-distribute their widths to fill the widget.

    col_weights : {column_id: relative_weight}  — the proportions are preserved
                  but the total width always equals the treeview's current width.
    scrollbar_w : pixels to reserve for the vertical scrollbar (default 20).

    Binds <Configure> so the distribution updates whenever the widget is resized.
    Two deferred passes are also scheduled so the initial layout is correct even
    before the window has fully mapped.
    """
    total_weight = sum(col_weights.values())

    def _resize(event=None):
        w = tv.winfo_width()
        if w <= 1:
            return
        avail = max(w - scrollbar_w, 60)
        for col, weight in col_weights.items():
            tv.column(col, width=max(24, int(avail * weight / total_weight)))

    tv.bind('<Configure>', lambda e: _resize())
    tv.after(150, _resize)
    tv.after(600, _resize)
    return _resize


# ─────────────────────────────────────────────────────────────
# SearchableCombobox
# A drop-in replacement for ttk.Combobox that shows a filtered
# popup listbox as the user types, supporting 100s of entries.
# ─────────────────────────────────────────────────────────────

class SearchableCombobox(ttk.Frame):
    """
    A filterable combobox widget.

    Looks like a normal entry+button pair.  When focused or clicked it
    opens a themed Toplevel containing a search entry and a scrollable
    Listbox.  Typing in the search box narrows the list in real time.

    Public API (mirrors the subset of ttk.Combobox used in this app):
      .get()              — current text value
      .set(value)         — set current value programmatically
      .configure_values(values)  — replace the full item list
      .bind_selected(callback)  — called with no args on selection
      .textvariable       — the underlying tk.StringVar
    """

    def __init__(self, parent, textvariable=None, values=(), width=30,
                 placeholder="", **kw):
        super().__init__(parent, **kw)

        self._all_values   = list(values)
        self._placeholder  = placeholder
        self._on_selected  = None        # callback
        self._popup        = None        # Toplevel when open

        self.textvariable = textvariable or tk.StringVar()
        self._entry_var   = tk.StringVar(value=self.textvariable.get())

        # Sync external textvariable → entry display
        def _ext_changed(*_):
            self._entry_var.set(self.textvariable.get())
        self.textvariable.trace_add('write', _ext_changed)

        # ── Layout: Entry + dropdown arrow button ────────────────────────
        self.columnconfigure(0, weight=1)
        self._entry = ttk.Entry(self, textvariable=self._entry_var, width=width)
        self._entry.grid(row=0, column=0, sticky='ew')
        self._btn = ttk.Button(self, text='▾', width=2,
                               command=self._toggle_popup)
        self._btn.grid(row=0, column=1, sticky='ns', padx=(1, 0))

        # Open popup on entry click / any keystroke in entry
        self._entry.bind('<Button-1>',  lambda e: self._open_popup())
        self._entry.bind('<KeyRelease>', self._on_entry_key)
        self._entry.bind('<FocusOut>',  self._on_entry_focus_out)
        self._entry.bind('<Return>',    lambda e: self._commit_entry_text())
        self._entry.bind('<Escape>',    lambda e: self._close_popup())

    # ── Public API ───────────────────────────────────────────────────────

    def get(self):
        return self.textvariable.get()

    def set(self, value):
        self.textvariable.set(value)
        self._entry_var.set(value)
        self._close_popup()

    def configure_values(self, values):
        self._all_values = list(values)
        if self._popup and self._popup.winfo_exists():
            self._refresh_list(self._search_var.get() if hasattr(self, '_search_var') else '')

    def bind_selected(self, callback):
        self._on_selected = callback

    # ── Popup management ────────────────────────────────────────────────

    def _toggle_popup(self):
        if self._popup and self._popup.winfo_exists():
            self._close_popup()
        else:
            self._open_popup()

    def _open_popup(self):
        if self._popup and self._popup.winfo_exists():
            return
        self._entry.focus_set()

        pw = tk.Toplevel(self)
        pw.wm_overrideredirect(True)
        pw.configure(bg=P['s1'])
        self._popup = pw

        # ── Search bar inside popup ──────────────────────────────────────
        self._search_var = tk.StringVar()
        search_entry = ttk.Entry(pw, textvariable=self._search_var)
        search_entry.pack(fill=tk.X, padx=2, pady=(2, 1))
        search_entry.bind('<KeyRelease>',
                          lambda e: self._refresh_list(self._search_var.get()))
        search_entry.bind('<Down>',   lambda e: self._lb_focus())
        search_entry.bind('<Return>', lambda e: self._select_focused())
        search_entry.bind('<Escape>', lambda e: self._close_popup())

        # Pre-fill search with whatever is already in the entry if it looks
        # like a partial match (i.e. not an exact full match)
        cur = self._entry_var.get()
        if cur and cur not in self._all_values:
            self._search_var.set(cur)

        # ── Listbox + scrollbar ──────────────────────────────────────────
        lbf = tk.Frame(pw, bg=P['s0'])
        lbf.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 2))

        self._lb = tk.Listbox(
            lbf, height=12, bg=P['s0'], fg=P['text'],
            selectbackground=P['blue'], selectforeground=P['bg'],
            activestyle='none', font=('Segoe UI', 9),
            relief='flat', borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(lbf, command=self._lb.yview)
        self._lb.configure(yscrollcommand=vsb.set)
        self._lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._lb.bind('<ButtonRelease-1>', lambda e: self._select_focused())
        self._lb.bind('<Return>',          lambda e: self._select_focused())
        self._lb.bind('<Escape>',          lambda e: self._close_popup())
        self._lb.bind('<Up>', lambda e: (
            search_entry.focus_set() if self._lb.curselection() == (0,) else None))

        self._refresh_list(self._search_var.get())
        self._position_popup()

        # Close when user clicks anywhere outside
        pw.bind('<FocusOut>', self._on_popup_focus_out)
        search_entry.focus_set()

    def _position_popup(self):
        if not self._popup:
            return
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        w = self.winfo_width()
        # Make popup at least 300 px wide
        pw = max(w, 300)
        self._popup.geometry(f"{pw}x240+{x}+{y}")

    def _close_popup(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
        self._popup = None

    def _on_popup_focus_out(self, event):
        # Only close if focus moved to something outside our own widgets
        self.after(100, self._check_focus_gone)

    def _check_focus_gone(self):
        try:
            focused = self.focus_displayof()
        except Exception:
            self._close_popup()
            return
        if focused is None:
            self._close_popup()
            return
        # Walk up widget hierarchy to see if focus is still inside popup or self
        w = focused
        seen = set()
        while w:
            wid = str(w)
            if wid in seen:
                break  # cycle detected (reached root) — stop
            seen.add(wid)
            if w is self or (self._popup and w is self._popup):
                return
            try:
                parent_name = w.winfo_parent()
                if not parent_name:
                    break
                w = w.nametowidget(parent_name)
            except Exception:
                break
        self._close_popup()

    # ── List filtering & selection ───────────────────────────────────────

    def _refresh_list(self, query):
        self._lb.delete(0, tk.END)
        q = query.strip().lower()
        matches = [v for v in self._all_values
                   if q in v.lower()] if q else list(self._all_values)
        for v in matches:
            self._lb.insert(tk.END, v)
        # Pre-select current value if visible
        cur = self.textvariable.get()
        if cur in matches:
            idx = matches.index(cur)
            self._lb.selection_set(idx)
            self._lb.see(idx)
        elif matches:
            self._lb.selection_set(0)

    def _lb_focus(self):
        self._lb.focus_set()
        if not self._lb.curselection() and self._lb.size():
            self._lb.selection_set(0)

    def _select_focused(self):
        sel = self._lb.curselection()
        if sel:
            value = self._lb.get(sel[0])
            self.set(value)
            if self._on_selected:
                self._on_selected()

    def _commit_entry_text(self):
        """Accept whatever is typed if it exactly matches a value."""
        cur = self._entry_var.get().strip()
        if cur in self._all_values:
            self.set(cur)
            if self._on_selected:
                self._on_selected()
        self._close_popup()

    def _on_entry_key(self, event):
        if event.keysym in ('Return', 'Escape', 'Tab'):
            return
        # Re-open popup and filter by what's typed
        if not (self._popup and self._popup.winfo_exists()):
            self._open_popup()
        if hasattr(self, '_search_var'):
            self._search_var.set(self._entry_var.get())
            self._refresh_list(self._entry_var.get())

    def _on_entry_focus_out(self, event):
        # Small delay so clicking the popup listbox doesn't close it first
        self.after(150, self._check_focus_gone)


# ─────────────────────────────────────────────────────────────
# Dialogs
# ─────────────────────────────────────────────────────────────

class BoneDialog(tk.Toplevel):
    def __init__(self, parent, title="Add Bone", bone="", custom=""):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.configure(bg=P['bg'])
        self.result = None
        self._build(bone, custom)
        self.transient(parent)
        self.grab_set()
        self.wait_window()

    def _build(self, bone, custom):
        f = ttk.Frame(self, padding=16)
        f.pack(fill=tk.BOTH, expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Bone Name:").grid(row=0, column=0, sticky='w', padx=6, pady=4)
        self.bv = tk.StringVar(value=bone)
        e = ttk.Entry(f, textvariable=self.bv, width=36)
        e.grid(row=0, column=1, sticky='ew', padx=6, pady=4)
        e.focus_set()

        ttk.Label(f, text="Custom HP Name:").grid(row=1, column=0, sticky='w', padx=6, pady=4)
        self.cv = tk.StringVar(value=custom)
        ttk.Entry(f, textvariable=self.cv, width=36).grid(row=1, column=1, sticky='ew', padx=6, pady=4)
        ttk.Label(f, text="Optional — overrides the auto-numbered hardpoint name",
                  style='Small.TLabel').grid(row=2, column=1, sticky='w', padx=6)

        bf = ttk.Frame(f)
        bf.grid(row=3, column=0, columnspan=2, pady=12)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="OK", style='Accent.TButton', command=self._ok).pack(side=tk.RIGHT, padx=4)
        self.bind('<Return>', lambda _: self._ok())
        self.bind('<Escape>', lambda _: self.destroy())

    def _ok(self):
        b = self.bv.get().strip()
        if not b:
            messagebox.showerror("Required", "Bone name cannot be empty.", parent=self)
            return
        self.result = (b, self.cv.get().strip())
        self.destroy()


class BoneSequenceDialog(tk.Toplevel):
    def __init__(self, parent, existing_pool=None):
        super().__init__(parent)
        self.title("Add Bone Sequence")
        self.configure(bg=P['bg'])
        self.resizable(True, False)
        self.result = None
        self._existing_names = {bone_name(e) for e in (existing_pool or [])}
        self._build()
        self.transient(parent)
        self.grab_set()
        self.wait_window()

    def _build(self):
        f = ttk.Frame(self, padding=16)
        f.pack(fill=tk.BOTH, expand=True)
        f.columnconfigure(1, weight=1)

        fields = [
            ("Prefix:",  "HP_Weapon_",  'entry'),
            ("From #:",  1,          'spin'),
            ("Count:",   10,         'spin'),
            ("Format:",  "02d",      'entry'),
            ("Suffix:",  "",       'entry'),
        ]
        self._vars = []
        for row, (label, default, kind) in enumerate(fields):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky='w', padx=8, pady=3)
            if kind == 'spin':
                v = tk.IntVar(value=default)
                sb = ttk.Spinbox(f, textvariable=v, from_=1, to=9999, width=8)
                sb.grid(row=row, column=1, sticky='w', padx=8, pady=3)
                # Place "Find Next #" button next to "From #"
                if label == "From #:":
                    ttk.Button(f, text="↑ Find Next",
                               command=self._find_next).grid(
                                   row=row, column=2, padx=(0,8), pady=3)
            else:
                v = tk.StringVar(value=default)
                ttk.Entry(f, textvariable=v, width=24
                          ).grid(row=row, column=1, sticky='ew', padx=8, pady=3)
            self._vars.append(v)
            v.trace_add('write', lambda *_: self._preview())

        # Help text for Find Next — placed below all input rows to avoid overlap
        # (inserted after the field loop ends, using a dedicated row)

        # Help hint shown below all input fields — no overlap
        # ttk.Label(f, text="↑ Find Next: auto-detects highest existing number for this pattern",
        #           style='Small.TLabel').grid(row=len(fields)+1, column=1, columnspan=2,
        #                                       sticky='w', padx=8, pady=(0, 4))

        self._skip_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Skip bones already in pool",
                        variable=self._skip_var,
                        command=self._preview).grid(
            row=len(fields), column=0, columnspan=3, sticky='w', padx=8, pady=4)

        ttk.Separator(f, orient='h').grid(row=len(fields)+1, column=0,
                                           columnspan=3, sticky='ew', pady=6)

        ttk.Label(f, text="Preview:").grid(row=len(fields)+2, column=0, sticky='nw', padx=8, pady=3)
        self.prev_text = tk.Text(f, height=8, width=30, state='disabled',
                                  bg=P['s0'], fg=P['text'], font=('Consolas', 9), relief='flat')
        self.prev_text.grid(row=len(fields)+2, column=1, columnspan=2,
                             sticky='ew', padx=8, pady=3)

        self.sv_preview_count = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.sv_preview_count,
                  style='Small.TLabel').grid(row=len(fields)+3, column=1,
                                              sticky='w', padx=8)

        bf = ttk.Frame(f)
        bf.grid(row=len(fields)+4, column=0, columnspan=3, pady=10)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Add Sequence", style='Accent.TButton',
                   command=self._ok).pack(side=tk.RIGHT, padx=4)

        self._preview()

    def _get_all_bones(self) -> list[str]:
        """Generate the full candidate list (before de-dup)."""
        try:
            prefix = self._vars[0].get()
            from_n = int(self._vars[1].get())
            count  = int(self._vars[2].get())
            fmt    = self._vars[3].get() or "d"
            suffix = self._vars[4].get()
            return [f"{prefix}{format(i, fmt)}{suffix}"
                    for i in range(from_n, from_n + count)]
        except Exception:
            return []

    def _get_bones(self) -> list[str]:
        """Return bones that will actually be added (respects skip toggle)."""
        all_b = self._get_all_bones()
        if self._skip_var.get():
            return [b for b in all_b if b not in self._existing_names]
        return all_b

    def _find_next(self):
        """Scan existing pool for the highest number matching this pattern, set From # to N+1."""
        try:
            prefix = self._vars[0].get()
            fmt    = self._vars[3].get() or "d"
            suffix = self._vars[4].get()
        except Exception:
            return

        highest = 0
        for bname in self._existing_names:
            if bname.startswith(prefix) and bname.endswith(suffix):
                mid = bname[len(prefix): len(bname) - len(suffix) if suffix else None]
                try:
                    n = int(mid)
                    if n > highest:
                        highest = n
                except ValueError:
                    pass
        next_n = highest + 1
        self._vars[1].set(next_n)   # From #

    def _preview(self):
        all_b  = self._get_all_bones()
        show_b = self._get_bones()
        skip_c = len(all_b) - len(show_b)

        self.prev_text.config(state='normal')
        self.prev_text.delete('1.0', tk.END)
        display = show_b[:30]
        self.prev_text.insert('1.0', '\n'.join(display))
        if len(show_b) > 30:
            self.prev_text.insert(tk.END, f"\n… ({len(show_b)} total)")
        # Grey out already-existing bones in preview
        for b in (set(all_b) - set(show_b)):
            pass  # stripped by skip filter
        self.prev_text.config(state='disabled')

        info = f"{len(show_b)} to add"
        if skip_c:
            info += f"  ({skip_c} already in pool — skipped)"
        self.sv_preview_count.set(info)

    def _ok(self):
        bones = self._get_bones()
        if not bones:
            messagebox.showerror("Error", "No new bones to add — all already exist or sequence is empty.",
                                 parent=self)
            return
        self.result = bones
        self.destroy()


class BulkAssignDialog(tk.Toplevel):
    """Select multiple bones and assign to a target group."""
    def __init__(self, parent, bones_pool, groups, current_group_idx=None):
        super().__init__(parent)
        self.title("Bulk Assign Bones to Group")
        self.geometry("560x540")
        self.configure(bg=P['bg'])
        self.result = None   # (bone_names_list, group_idx)
        self._bones_pool = bones_pool
        self._groups = groups
        self._build(current_group_idx)
        self.transient(parent)
        self.grab_set()
        self.wait_window()

    def _build(self, current_group_idx):
        f = ttk.Frame(self, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        f.rowconfigure(1, weight=1)
        f.columnconfigure(0, weight=1)

        ttk.Label(f, text="Target Group:", style='Header.TLabel').grid(row=0, column=0, sticky='w', pady=(0,4))
        gnames = [(f"[{i+1}] " + (g.get("group_comment") or g.get("name_prefix", f"Group {i+1}")))
                  for i, g in enumerate(self._groups)]
        self.gv = tk.StringVar()
        gcb = SearchableCombobox(f, textvariable=self.gv, values=gnames, width=55)
        gcb.grid(row=0, column=0, sticky='ew', pady=(0,8))
        if current_group_idx is not None and current_group_idx < len(gnames):
            gcb.set(gnames[current_group_idx])

        ttk.Label(f, text="Select bones to assign (Ctrl/Shift for multi-select):",
                  style='Header.TLabel').grid(row=1, column=0, sticky='w', pady=(4,2))

        inner = ttk.Frame(f)
        inner.grid(row=2, column=0, sticky='nsew')
        inner.rowconfigure(0, weight=1)
        inner.columnconfigure(0, weight=1)
        f.rowconfigure(2, weight=1)

        self.lb = tk.Listbox(inner, selectmode='extended', height=16,
                              bg=P['s0'], fg=P['text'],
                              selectbackground=P['blue'], selectforeground=P['bg'],
                              font=('Consolas', 9))
        lbsb = ttk.Scrollbar(inner, command=self.lb.yview)
        self.lb.configure(yscrollcommand=lbsb.set)
        self.lb.grid(row=0, column=0, sticky='nsew')
        lbsb.grid(row=0, column=1, sticky='ns')

        for e in self._bones_pool:
            bn = bone_name(e); bc = bone_custom(e)
            label = bn + (f"  ({bc})" if bc else "")
            self.lb.insert(tk.END, label)

        self.sv_count = tk.StringVar(value="0 selected")
        ttk.Label(f, textvariable=self.sv_count, style='Small.TLabel').grid(row=3, column=0, sticky='w', pady=2)
        self.lb.bind('<<ListboxSelect>>', lambda _: self.sv_count.set(f"{len(self.lb.curselection())} selected"))

        bf = ttk.Frame(f)
        bf.grid(row=4, column=0, sticky='ew', pady=8)
        ttk.Button(bf, text="Select All", command=lambda: self.lb.select_set(0, tk.END)).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="Clear", command=lambda: self.lb.selection_clear(0, tk.END)).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Assign Selected", style='Accent.TButton', command=self._ok).pack(side=tk.RIGHT, padx=4)

    def _ok(self):
        idxs = self.lb.curselection()
        if not idxs:
            messagebox.showinfo("Nothing Selected", "Select at least one bone.", parent=self); return
        gsel = self.gv.get()
        if not gsel:
            messagebox.showinfo("No Group", "Select a target group.", parent=self); return
        # Parse group index from label "[N] ..."
        try:
            gi = int(gsel.split("]")[0].lstrip("[")) - 1
        except Exception:
            gi = 0
        selected_bones = [bone_name(self._bones_pool[i]) for i in idxs]
        self.result = (selected_bones, gi)
        self.destroy()


class DumpTemplateDialog(tk.Toplevel):
    """Choose a template to dump."""
    def __init__(self, parent, template_names):
        super().__init__(parent)
        self.title("Dump Template")
        self.resizable(False, False)
        self.configure(bg=P['bg'])
        self.result = None
        self._build(template_names)
        self.transient(parent)
        self.grab_set()
        self.wait_window()

    def _build(self, names):
        f = ttk.Frame(self, padding=14)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="Select template to dump:").pack(anchor='w', pady=(0,4))
        self.tv = tk.StringVar()
        cb = SearchableCombobox(f, textvariable=self.tv, values=sorted(names), width=44)
        cb.pack(fill=tk.X, pady=4)
        if names:
            cb.set(sorted(names)[0])
        bf = ttk.Frame(f)
        bf.pack(fill=tk.X, pady=8)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Dump", style='Accent.TButton', command=self._ok).pack(side=tk.RIGHT, padx=4)

    def _ok(self):
        v = self.tv.get().strip()
        if v:
            self.result = v
        self.destroy()



class BoneColumnAssignDialog(tk.Toplevel):
    """
    Unified bone-assignment dialog used by all three assignment paths:
      • "▶ Assign Selected to Group" (pool panel)
      • "🔀 Bulk Assign…"           (pool panel)
      • "+ From Pool"               (group editor)

    The user selects bones from the pool on the left, picks a target bone
    column (A–E) and a starting row, and sees a live preview table on the
    right showing exactly which rows will change.

    Assignment rules
    ----------------
    Column A:   new rows are *inserted* at the chosen start row, pushing
                existing rows downward.  Start row = 1 means prepend;
                start row = N+1 (or beyond) means append at the end.
    Column B–E: existing rows *before* the start row are left untouched.
                From the start row onwards the first empty slot in the
                target column is filled.  Bones that cannot fit into
                existing rows overflow as new rows (bone_a left blank).

    Preview colour coding
    ---------------------
        White  — existing row, unchanged
        Teal   — existing row whose slot will be filled
        Blue   — new row with bone_a present
        Yellow — new row where bone_a is still blank (B–E overflow)

    result : None | (target_gi: int, new_bones: list)
    """

    _COL_KEYS = {
        'A': 'bone_a', 'B': 'bone_b', 'C': 'bone_c',
        'D': 'bone_d', 'E': 'bone_e', 'F': 'bone_f',
    }

    def __init__(self, parent, bone_pool: list, groups: list,
                 preselected_bones: list | None = None,
                 current_group_idx: int | None = None):
        super().__init__(parent)
        self.title("Assign Bones to Group")
        self.geometry("1020x600")
        self.minsize(800, 440)
        self.configure(bg=P['bg'])
        self.result = None

        self._pool   = bone_pool
        self._groups = groups
        self._presel = set(b if isinstance(b, str) else bone_name(b)
                           for b in (preselected_bones or []))
        self._gi     = current_group_idx

        # Reactive state
        self._col_var      = tk.StringVar(value='A')
        self._start_row_var = tk.IntVar(value=1)
        self._filter_var   = tk.StringVar()
        self._pool_entries: list = []

        self._filter_var.trace_add('write',    lambda *_: self._refresh_pool())
        self._col_var.trace_add('write',       lambda *_: self._refresh_preview())
        self._start_row_var.trace_add('write', lambda *_: self._refresh_preview())

        self._build()
        self.transient(parent)
        self.grab_set()

        self._refresh_pool()
        if self._presel:
            for i, e in enumerate(self._pool_entries):
                if bone_name(e) in self._presel:
                    self._lb.selection_set(i)
        self._reset_start_row()   # set correct default (Column A → append at end)
        self.wait_window()

    # ── UI construction ────────────────────────────────────────────────────

    def _build(self):
        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(1, weight=1)

        # ── Target group (spans full width) ─────────────────────────────
        gh = ttk.Frame(root)
        gh.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 6))
        gh.columnconfigure(1, weight=1)
        ttk.Label(gh, text="Target Group:", style='Header.TLabel').grid(
            row=0, column=0, sticky='w', padx=(0, 8))
        gnames = [
            f"[{i+1}] " + (g.get("group_comment") or g.get("name_prefix", f"Group {i+1}"))
            for i, g in enumerate(self._groups)
        ]
        self._gv = tk.StringVar()
        gcb = SearchableCombobox(gh, textvariable=self._gv, values=gnames, width=70)
        gcb.grid(row=0, column=1, sticky='ew')
        gcb.bind_selected(self._on_group_changed)
        if self._gi is not None and self._gi < len(gnames):
            gcb.set(gnames[self._gi])

        # ── LEFT: bone pool picker ───────────────────────────────────────
        lf = ttk.LabelFrame(root, text=" Bone Pool ")
        lf.grid(row=1, column=0, sticky='nsew', padx=(0, 5))
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(1, weight=1)

        fr = ttk.Frame(lf)
        fr.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))
        fr.columnconfigure(1, weight=1)
        ttk.Label(fr, text="Filter:").grid(row=0, column=0, sticky='w', padx=(0, 4))
        ttk.Entry(fr, textvariable=self._filter_var).grid(row=0, column=1, sticky='ew')
        ttk.Button(fr, text="✕", width=3,
                   command=lambda: self._filter_var.set('')).grid(
            row=0, column=2, padx=(2, 0))

        lbf = ttk.Frame(lf)
        lbf.grid(row=1, column=0, sticky='nsew', padx=4, pady=(0, 2))
        lbf.rowconfigure(0, weight=1); lbf.columnconfigure(0, weight=1)
        self._lb = tk.Listbox(
            lbf, selectmode='extended', height=14,
            bg=P['s0'], fg=P['text'],
            selectbackground=P['blue'], selectforeground=P['bg'],
            font=('Consolas', 9), activestyle='none',
            highlightthickness=0, relief='flat')
        lbsb = ttk.Scrollbar(lbf, command=self._lb.yview)
        self._lb.configure(yscrollcommand=lbsb.set)
        self._lb.grid(row=0, column=0, sticky='nsew')
        lbsb.grid(row=0, column=1, sticky='ns')
        self._lb.bind('<<ListboxSelect>>', lambda _: self._refresh_preview())

        qbf = ttk.Frame(lf)
        qbf.grid(row=2, column=0, sticky='ew', padx=4, pady=(0, 4))
        ttk.Button(qbf, text="All",
                   command=lambda: (self._lb.select_set(0, tk.END),
                                    self._refresh_preview())).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(qbf, text="None",
                   command=lambda: (self._lb.selection_clear(0, tk.END),
                                    self._refresh_preview())).pack(side=tk.LEFT)
        self._sv_sel = tk.StringVar(value="0 selected")
        ttk.Label(qbf, textvariable=self._sv_sel,
                  style='Small.TLabel').pack(side=tk.RIGHT)

        # ── RIGHT: controls + preview ────────────────────────────────────
        rf = ttk.Frame(root)
        rf.grid(row=1, column=1, sticky='nsew')
        rf.columnconfigure(0, weight=1)
        rf.rowconfigure(2, weight=1)

        # ── Control row 1: column selector ──────────────────────────────
        col_row = ttk.Frame(rf)
        col_row.grid(row=0, column=0, sticky='ew', pady=(0, 2))
        ttk.Label(col_row, text="Assign to Column:",
                  style='Header.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        for letter in ('A', 'B', 'C', 'D', 'E', 'F'):
            ttk.Radiobutton(col_row, text=f"  {letter}  ",
                            variable=self._col_var,
                            value=letter).pack(side=tk.LEFT, padx=1)

        ttk.Separator(col_row, orient='vertical').pack(
            side=tk.LEFT, fill=tk.Y, padx=10, pady=2)

        ttk.Label(col_row, text="Start from Row:",
                  style='Header.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        self._row_spin = ttk.Spinbox(
            col_row, textvariable=self._start_row_var,
            from_=1, to=9999, width=5)
        self._row_spin.pack(side=tk.LEFT)
        ttk.Button(col_row, text="↺ Reset", width=7,
                   command=self._reset_start_row).pack(side=tk.LEFT, padx=(4, 0))

        # ── Control row 2: dynamic hint ──────────────────────────────────
        hint_row = ttk.Frame(rf)
        hint_row.grid(row=1, column=0, sticky='ew', pady=(0, 4))
        self._sv_hint = tk.StringVar(value="")
        ttk.Label(hint_row, textvariable=self._sv_hint,
                  style='Small.TLabel').pack(side=tk.LEFT, padx=2)

        # ── Preview treeview ─────────────────────────────────────────────
        pf = ttk.LabelFrame(rf, text=" Preview — Assigned Bones ")
        pf.grid(row=2, column=0, sticky='nsew')
        pf.rowconfigure(0, weight=1)
        pf.columnconfigure(0, weight=1)

        tvf = ttk.Frame(pf)
        tvf.grid(row=0, column=0, sticky='nsew', padx=4, pady=4)
        tvf.rowconfigure(0, weight=1); tvf.columnconfigure(0, weight=1)

        cols = ('idx', 'bone_a', 'bone_b', 'bone_c', 'bone_d', 'bone_e', 'bone_f', 'custom')
        self._tv = ttk.Treeview(tvf, columns=cols, show='headings',
                                selectmode='browse', height=10)
        for col, txt, w in [
            ('idx',    '#',               28),
            ('bone_a', 'Bone A',         110),
            ('bone_b', 'Bone B',          90),
            ('bone_c', 'Bone C (ATT)',    90),
            ('bone_d', 'Bone D (COL)',    90),
            ('bone_e', 'Bone E (DMG)',    90),
            ('bone_f', 'Bone F (DCL)',    90),
            ('custom', 'Custom HP Name',  95),
        ]:
            self._tv.heading(col, text=txt)
            self._tv.column(col, width=w, minwidth=24)

        self._tv.tag_configure('existing', foreground=P['text'])
        self._tv.tag_configure('modified', foreground=P['teal'])
        self._tv.tag_configure('newrow',   foreground=P['blue'])
        self._tv.tag_configure('empty_a',  foreground=P['yellow'])
        self._tv.tag_configure('skipped',  foreground=P['ov0'])

        tv_vsb = ttk.Scrollbar(tvf, orient='vertical',   command=self._tv.yview)
        tv_hsb = ttk.Scrollbar(tvf, orient='horizontal', command=self._tv.xview)
        self._tv.configure(yscrollcommand=tv_vsb.set, xscrollcommand=tv_hsb.set)
        self._tv.grid(row=0, column=0, sticky='nsew')
        tv_vsb.grid(row=0, column=1, sticky='ns')
        tv_hsb.grid(row=1, column=0, sticky='ew')

        # Clicking a preview row snaps start row; clicking a Bone A–E column also sets the bone column
        self._tv.bind('<Button-1>', self._on_preview_click)

        # Legend
        leg = ttk.Frame(pf)
        leg.grid(row=1, column=0, sticky='w', padx=6, pady=(2, 0))
        for fg, txt in [
            (P['text'],   "unchanged"),
            (P['ov0'],    "skipped (before start row)"),
            (P['teal'],   "slot filled"),
            (P['blue'],   "new row"),
            (P['yellow'], "new row — Bone A empty"),
        ]:
            tk.Label(leg, text="●", fg=fg, bg=P['bg'],
                     font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(4, 0))
            ttk.Label(leg, text=txt, style='Small.TLabel').pack(
                side=tk.LEFT, padx=(0, 10))

        self._sv_info = tk.StringVar(value="")
        ttk.Label(pf, textvariable=self._sv_info,
                  style='Small.TLabel').grid(row=2, column=0, sticky='w',
                                             padx=6, pady=(0, 4))

        # ── Bottom buttons ───────────────────────────────────────────────
        bf = ttk.Frame(root)
        bf.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        ttk.Label(bf, text="Click a preview row to set start row · Click a Bone A–E column to also set the bone column.",
                  style='Small.TLabel').pack(side=tk.LEFT)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Assign", style='Accent.TButton',
                   command=self._ok).pack(side=tk.RIGHT, padx=4)
        self.bind('<Escape>', lambda _: self.destroy())

    # ── Pool helpers ───────────────────────────────────────────────────────

    def _refresh_pool(self):
        sel_names = self._selected_bone_names()
        self._lb.delete(0, tk.END)
        self._pool_entries.clear()
        filt = self._filter_var.get().lower()
        # Display pool sorted alphabetically so order matches the Bone Pool panel
        pool_sorted = sorted(self._pool, key=lambda e: bone_name(e).lower())
        for e in pool_sorted:
            bn = bone_name(e)
            bc = bone_custom(e)
            if filt and filt not in bn.lower() and filt not in bc.lower():
                continue
            label = bn + (f"  ({bc})" if bc else "")
            self._lb.insert(tk.END, label)
            self._pool_entries.append(e)
        gi = self._target_gi()
        in_group: set[str] = set()
        if gi is not None:
            for e in self._groups[gi].get("bones", []):
                in_group.add(bone_name(e))
        for i, e in enumerate(self._pool_entries):
            bn = bone_name(e)
            if bn in sel_names:
                self._lb.selection_set(i)
            if bn in in_group:
                self._lb.itemconfig(i, fg=P['ov0'])
        self._refresh_preview()

    def _selected_bone_names(self) -> list[str]:
        return [bone_name(self._pool_entries[i])
                for i in self._lb.curselection()
                if i < len(self._pool_entries)]

    def _target_gi(self) -> int | None:
        gsel = self._gv.get()
        if not gsel:
            return None
        try:
            return int(gsel.split("]")[0].lstrip("[")) - 1
        except Exception:
            return None

    def _on_group_changed(self):
        """Reset start row to correct default and refresh when the target group changes."""
        self._reset_start_row()
        self._refresh_pool()

    def _on_preview_click(self, event=None):
        """Snap start row to clicked row; set bone column from the clicked Bone A–E column."""
        # Identify the clicked row using event position — this works before
        # <<TreeviewSelect>> fires, unlike self._tv.selection() which may lag.
        iid = None
        if event and hasattr(event, 'y'):
            iid = self._tv.identify_row(event.y)
        if not iid:
            sel = self._tv.selection()
            iid = sel[0] if sel else None
        if not iid:
            return

        try:
            vals = self._tv.item(iid)['values']
            row_num = int(vals[0])
        except (IndexError, ValueError):
            return

        # Detect which column was clicked and update the bone column selector.
        # Columns: #1=idx, #2=bone_a, #3=bone_b, #4=bone_c, #5=bone_d, #6=bone_e, #7=custom
        if event and hasattr(event, 'x'):
            col_id = self._tv.identify_column(event.x)
            col_map = {'#2': 'A', '#3': 'B', '#4': 'C', '#5': 'D', '#6': 'E', '#7': 'F'}
            col_letter = col_map.get(col_id)
            if col_letter and col_letter != self._col_var.get():
                # Setting _col_var triggers _refresh_preview via trace.
                # row_num is already captured, so the subsequent set is safe.
                self._col_var.set(col_letter)

        # Preserve pool listbox selection — setting _start_row_var triggers
        # _refresh_preview which rebuilds the TV but must not clear the lb.
        lb_sel = list(self._lb.curselection())
        self._start_row_var.set(row_num)
        # Restore listbox selection in case focus-shift cleared it visually
        for i in lb_sel:
            if i < self._lb.size():
                self._lb.selection_set(i)

    def _reset_start_row(self):
        """Reset start row to the natural default for the current column."""
        col = self._col_var.get()
        n   = len(self._current_bones_as_dicts())
        if col == 'A':
            self._start_row_var.set(n + 1)   # default: append at end
        else:
            self._start_row_var.set(1)        # default: fill from row 1 (B–F)

    # ── Bone data helpers ──────────────────────────────────────────────────

    def _current_bones_as_dicts(self) -> list[dict]:
        gi = self._target_gi()
        if gi is None:
            return []
        result = []
        for e in self._groups[gi].get("bones", []):
            result.append({
                'bone_a': bone_name(e),
                'bone_b': bone_b_val(e),
                'bone_c': bone_c_val(e),
                'bone_d': bone_d_val(e),
                'bone_e': bone_e_val(e),
                'bone_f': bone_f_val(e),
                'custom': bone_custom(e),
            })
        return result

    # ── Preview computation ────────────────────────────────────────────────

    def _compute_result(self) -> tuple[list[dict], dict[int, str]]:
        """
        Compute the final bones list and per-row highlight tags.

        Column A  — inserts new rows at start_row position (1-based),
                    pushing existing rows from that point downward.
        Column B–E — rows before start_row receive tag 'skipped' and are
                    left untouched; filling begins from start_row onwards.

        Returns (new_bones_list, hi_map  {row_index_0based: treeview_tag})
        """
        existing   = self._current_bones_as_dicts()
        selected   = self._selected_bone_names()
        col_letter = self._col_var.get()
        col_key    = self._COL_KEYS[col_letter]
        n_exist    = len(existing)

        # 0-based insertion / scan start
        start_0 = max(0, self._start_row_var.get() - 1)

        result  = [dict(d) for d in existing]
        hi_map: dict[int, str] = {}

        if col_letter == 'A':
            # Insert new rows at start_0, clamped to valid range
            insert_at = min(start_0, n_exist)
            new_rows  = [
                {'bone_a': bn, 'bone_b': '', 'bone_c': '',
                 'bone_d': '', 'bone_e': '', 'bone_f': '', 'custom': ''}
                for bn in selected
            ]
            result = result[:insert_at] + new_rows + result[insert_at:]
            for i in range(insert_at, insert_at + len(new_rows)):
                hi_map[i] = 'newrow'
            # rows before insert_at and after are 'existing' (default)

        else:
            # Rows before start_0 are skipped (marked grey)
            for i in range(min(start_0, n_exist)):
                hi_map[i] = 'skipped'

            queue = list(selected)
            for row_idx, d in enumerate(result):
                if not queue:
                    break
                if row_idx < start_0:
                    continue
                if d.get('bone_a') and not d.get(col_key):
                    d[col_key] = queue.pop(0)
                    hi_map[row_idx] = 'modified'
            # Overflow → new rows appended at end
            for bname in queue:
                idx = len(result)
                new_d = {'bone_a': '', 'bone_b': '', 'bone_c': '',
                         'bone_d': '', 'bone_e': '', 'bone_f': '', 'custom': ''}
                new_d[col_key] = bname
                result.append(new_d)
                hi_map[idx] = 'empty_a'

        return result, hi_map

    def _dynamic_hint(self) -> str:
        """Return a context-sensitive hint based on current col + start row."""
        col   = self._col_var.get()
        row   = self._start_row_var.get()
        n     = len(self._current_bones_as_dicts())
        n_sel = len(self._lb.curselection())

        if col == 'A':
            if n == 0:
                return f"{n_sel} new row(s) will be created."
            elif row <= 1:
                return (f"New rows inserted before row 1 (prepend). "
                        f"Existing rows shift down by {n_sel}.")
            elif row > n:
                return (f"New rows appended after row {n} (end). "
                        f"No existing rows affected.")
            else:
                return (f"New rows inserted at row {row}. "
                        f"Rows {row}–{n} shift down by {n_sel}.")
        else:
            if n == 0:
                return (f"No existing rows — {n_sel} new row(s) with Bone {col} set "
                        f"and Bone A blank.")
            elif row > n:
                return (f"Start row {row} is beyond the last row ({n}). "
                        f"All {n_sel} bone(s) will create new rows with Bone A blank.")
            else:
                skipped = max(0, row - 1)
                active  = n - skipped
                return (f"Skipping {skipped} row(s). Filling empty Bone {col} slots "
                        f"in rows {row}–{n} ({active} row(s) eligible); overflow → new rows.")

    def _refresh_preview(self, *_):
        """Rebuild the preview treeview from the current pool selection and column."""
        col_letter = self._col_var.get()
        n_exist    = len(self._current_bones_as_dicts())

        # Update spinbox upper bound: for col A allow up to n+1 (append at end);
        # for B-E allow up to n (last row) or at least 1.
        max_row = max(1, n_exist + 1) if col_letter == 'A' else max(1, n_exist)
        try:
            self._row_spin.configure(to=max_row)
        except Exception:
            pass

        # Update hint
        self._sv_hint.set(self._dynamic_hint())

        # Update selected count
        n_sel = len(self._lb.curselection())
        self._sv_sel.set(f"{n_sel} selected")

        new_bones, hi_map = self._compute_result()

        self._tv.delete(*self._tv.get_children())
        for i, d in enumerate(new_bones):
            tag = hi_map.get(i, 'existing')
            self._tv.insert('', 'end',
                values=(
                    i + 1,
                    d.get('bone_a') or ('—' if tag not in ('newrow', 'empty_a') else ''),
                    d.get('bone_b') or '',
                    d.get('bone_c') or '',
                    d.get('bone_d') or '',
                    d.get('bone_e') or '',
                    d.get('bone_f') or '',
                    d.get('custom') or '',
                ),
                tags=(tag,))

        n_skip  = sum(1 for t in hi_map.values() if t == 'skipped')
        n_mod   = sum(1 for t in hi_map.values() if t == 'modified')
        n_new   = sum(1 for t in hi_map.values() if t == 'newrow')
        n_empty = sum(1 for t in hi_map.values() if t == 'empty_a')
        parts   = [f"{n_exist} existing"]
        if n_skip:  parts.append(f"{n_skip} skipped")
        if n_mod:   parts.append(f"{n_mod} slots filled")
        if n_new:   parts.append(f"{n_new} new rows")
        if n_empty: parts.append(f"{n_empty} new rows (Bone A blank)")
        self._sv_info.set("  ·  ".join(parts))

    # ── OK ─────────────────────────────────────────────────────────────────

    def _ok(self):
        gi = self._target_gi()
        if gi is None:
            messagebox.showinfo("No Group", "Select a target group.", parent=self)
            return
        if not self._lb.curselection():
            messagebox.showinfo("No Bones",
                                "Select at least one bone from the pool.", parent=self)
            return
        new_bones, _ = self._compute_result()
        final = [
            make_group_bone_entry(
                d.get('bone_a', ''),
                d.get('bone_b', ''),
                d.get('bone_c', ''),
                d.get('bone_d', ''),
                d.get('bone_e', ''),
                d.get('bone_f', ''),
                d.get('custom', ''),
            )
            for d in new_bones
        ]
        self.result = (gi, final)
        self.destroy()


class GroupBoneEditDialog(tk.Toplevel):
    """Edit a single bone entry inside a group: Bone A–E and custom HP name.

    Each bone slot has a SearchableCombobox populated from the bone pool so the
    user can pick a bone without typing.  Bone B–E default to Bone A (empty =
    use Bone A) and can be cleared by selecting the blank entry at the top of
    the dropdown.
    """
    def __init__(self, parent, bone_pool=None,
                 bone_a="", bone_b="", bone_c="", bone_d="", bone_e="", bone_f="", custom=""):
        super().__init__(parent)
        self.title("Edit Bone Entry")
        self.resizable(True, False)
        self.configure(bg=P['bg'])
        self.result = None   # (bone_a, bone_b, bone_c, bone_d, bone_e, bone_f, custom)
        # Build the pool name list for the comboboxes ("" = use bone_a default)
        self._pool_names = [""] + [
            bone_name(e) for e in (bone_pool or []) if bone_name(e)
        ]
        self._build(bone_a, bone_b, bone_c, bone_d, bone_e, bone_f, custom)
        self.transient(parent)
        self.grab_set()
        self.wait_window()

    def _build(self, bone_a, bone_b, bone_c, bone_d, bone_e, bone_f, custom):
        f = ttk.Frame(self, padding=16)
        f.pack(fill=tk.BOTH, expand=True)
        f.columnconfigure(1, weight=1)

        # Each tuple: (label, initial_value, hint_text, required)
        bone_specs = [
            ("Fire Bone A (primary):",      bone_a, "Used for {bone_a} / {bone} in template fields.",              True),
            ("Fire Bone B (secondary):",    bone_b, "Used for {bone_b}. Blank → same as Bone A.",                  False),
            ("Bone C (Attachment Bone):",   bone_c, "Used for {bone_c}. Blank → same as Bone A.",                  False),
            ("Bone D (Collision Mesh):",    bone_d, "Used for {bone_d}. Blank → same as Bone A.",                  False),
            ("Bone E (Damage Particles):",  bone_e, "Used for {bone_e}. Blank → stays empty in output (no fallback to Bone A).",  False),
            ("Bone F (Damage Decal):",      bone_f, "Used for {bone_f}. Blank → same as Bone E.",  False),
        ]

        self._bone_vars: list[tk.StringVar] = []
        row = 0
        for i, (label, val, hint, _required) in enumerate(bone_specs):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky='w', padx=6, pady=(6, 0))
            sv = tk.StringVar(value=val)
            self._bone_vars.append(sv)
            # Bone A allows free typing; B-E offer the pool as a dropdown too
            cb = SearchableCombobox(f, textvariable=sv,
                                    values=self._pool_names if i > 0 else [""] + self._pool_names[1:],
                                    width=38)
            cb.grid(row=row, column=1, sticky='ew', padx=6, pady=(6, 0))
            if i == 0:
                # Focus the first entry box inside the combobox
                cb._entry.focus_set()
            row += 1
            ttk.Label(f, text=hint, style='Small.TLabel').grid(
                row=row, column=1, sticky='w', padx=6, pady=(0, 2))
            row += 1

        ttk.Separator(f, orient='h').grid(row=row, column=0, columnspan=2,
                                           sticky='ew', pady=8)
        row += 1

        ttk.Label(f, text="Custom HP Name:").grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.cv = tk.StringVar(value=custom)
        ttk.Entry(f, textvariable=self.cv, width=38).grid(
            row=row, column=1, sticky='ew', padx=6, pady=4)
        row += 1
        ttk.Label(f, text="Optional — overrides the auto-numbered hardpoint name.",
                  style='Small.TLabel').grid(row=row, column=1, sticky='w', padx=6)
        row += 1

        bf = ttk.Frame(f)
        bf.grid(row=row, column=0, columnspan=2, pady=12)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="OK", style='Accent.TButton',
                   command=self._ok).pack(side=tk.RIGHT, padx=4)
        self.bind('<Return>', lambda _: self._ok())
        self.bind('<Escape>', lambda _: self.destroy())

    def _ok(self):
        a = self._bone_vars[0].get().strip()
        if not a:
            messagebox.showerror("Required", "Fire Bone A cannot be empty.", parent=self)
            return
        self.result = (
            a,
            self._bone_vars[1].get().strip(),
            self._bone_vars[2].get().strip(),
            self._bone_vars[3].get().strip(),
            self._bone_vars[4].get().strip(),
            self._bone_vars[5].get().strip(),
            self.cv.get().strip(),
        )
        self.destroy()


class AloImportDialog(tk.Toplevel):
    """
    Import bones from one or more .ALO model files into the bone pool.

    Features
    --------
    • Browse for multiple .ALO files at once.
    • Preview the extracted bones in a filterable list before committing.
    • Per-bone checkboxes let the user de-select bones they don't need
      (e.g. collision meshes, particle emitters, shadow meshes).
    • Quick-select buttons for common patterns:
        - "HP_ bones only"       — only names starting with HP_
        - "All except Root"      — everything but the skeleton root
        - "All"                  — every bone
        - "None"                 - clear all
    • Warns about bones already in the pool (shown in a different colour).
    • Duplicate names within the file are deduplicated automatically.
    • On OK, returns the list of bone name strings to add.

    result : list[str] | None
        None if the user cancelled.
        Otherwise a (possibly empty) list of bone names to add.
    """

    _EXCLUDE_PATTERNS = (
        # Mesh/shadow/collision objects — not real hardpoint bones
        'shadowmesh', 'shadow', 'collision', 'collission',
        # Particle emitters and engine effects
        'p_fire', 'p_blink', 'pe_', 'pte_', 'lenseffect',
        'engine_particle',
        # Generic render objects
        'plane', 'objobject',
    )

    def __init__(self, parent, existing_pool: list | None = None,
                 initial_paths: list[str] | None = None):
        super().__init__(parent)
        self.title("Import Bones from .ALO File(s)")
        self.geometry("740x620")
        self.minsize(600, 480)
        self.configure(bg=P['bg'])
        self.result: list[str] | None = None

        self._existing_names: set[str] = {
            bone_name(e) for e in (existing_pool or [])
        }
        # list of (bone_name, BooleanVar, already_in_pool)
        self._rows: list[tuple[str, tk.BooleanVar, bool]] = []
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add('write', lambda *_: self._refresh_list())

        self._build()
        self.transient(parent)
        self.grab_set()

        if initial_paths:
            self._load_files(initial_paths)

        self.wait_window()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        root_f = ttk.Frame(self, padding=10)
        root_f.pack(fill=tk.BOTH, expand=True)
        root_f.rowconfigure(2, weight=1)
        root_f.columnconfigure(0, weight=1)

        # ── File picker bar ──
        file_row = ttk.Frame(root_f)
        file_row.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        file_row.columnconfigure(1, weight=1)

        ttk.Label(file_row, text="File(s):").grid(row=0, column=0, sticky='w', padx=(0, 6))
        self._file_sv = tk.StringVar(value="No file loaded")
        ttk.Label(file_row, textvariable=self._file_sv, style='Small.TLabel',
                  wraplength=480, justify='left').grid(row=0, column=1, sticky='w')

        btn_row = ttk.Frame(root_f)
        btn_row.grid(row=1, column=0, sticky='ew', pady=(0, 6))
        ttk.Button(btn_row, text="📂 Browse .ALO File(s)…",
                   command=self._browse).pack(side=tk.LEFT, padx=(0, 6))
        self._sv_status = tk.StringVar(value="")
        ttk.Label(btn_row, textvariable=self._sv_status,
                  style='Small.TLabel').pack(side=tk.LEFT)

        # ── Bone list ────────────────────────────────────────────────────────
        list_frame = ttk.LabelFrame(root_f, text=" Bones Found ")
        list_frame.grid(row=2, column=0, sticky='nsew')
        list_frame.rowconfigure(1, weight=1)
        list_frame.columnconfigure(0, weight=1)

        # Filter + quick-select
        ctrl = ttk.Frame(list_frame)
        ctrl.grid(row=0, column=0, sticky='ew', padx=6, pady=(4, 2))
        ctrl.columnconfigure(1, weight=1)

        ttk.Label(ctrl, text="Filter:").grid(row=0, column=0, sticky='w', padx=(0,4))
        ttk.Entry(ctrl, textvariable=self._filter_var
                  ).grid(row=0, column=1, sticky='ew', padx=(0,6))
        ttk.Button(ctrl, text="✕", width=3,
                   command=lambda: self._filter_var.set('')
                   ).grid(row=0, column=2, padx=(0,10))

        ttk.Button(ctrl, text="Suggested",
                   command=self._sel_suggested
                   ).grid(row=0, column=3, padx=2)
        ttk.Button(ctrl, text="All excl. Root",
                   command=self._sel_all_except_root
                   ).grid(row=0, column=4, padx=2)
        ttk.Button(ctrl, text="All",
                   command=self._sel_all
                   ).grid(row=0, column=5, padx=2)
        ttk.Button(ctrl, text="None",
                   command=self._sel_none
                   ).grid(row=0, column=6, padx=2)

        # Scrollable checkbox list in a Canvas
        cf = ttk.Frame(list_frame)
        cf.grid(row=1, column=0, sticky='nsew', padx=6, pady=(0, 4))
        cf.rowconfigure(0, weight=1); cf.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(cf, bg=P['s0'], highlightthickness=0)
        vsb = ttk.Scrollbar(cf, orient='vertical', command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        self._list_inner = ttk.Frame(self._canvas)
        self._cwin = self._canvas.create_window((0, 0), window=self._list_inner,
                                                 anchor='nw')
        self._list_inner.bind('<Configure>',
                              lambda e: self._canvas.configure(
                                  scrollregion=self._canvas.bbox('all')))
        self._canvas.bind('<Configure>',
                          lambda e: self._canvas.itemconfig(self._cwin, width=e.width))
        self._canvas.bind('<MouseWheel>',
                          lambda e: self._canvas.yview_scroll(
                              int(-e.delta/120), 'units'))

        # Count label
        self._sv_count = tk.StringVar(value="0 selected / 0 total")
        ttk.Label(list_frame, textvariable=self._sv_count,
                  style='Small.TLabel').grid(row=2, column=0, sticky='w', padx=8, pady=2)

        # Legend
        leg = ttk.Frame(list_frame)
        leg.grid(row=3, column=0, sticky='w', padx=8, pady=(0, 4))
        for fg, txt in [(P['text'], "new bone"),
                        (P['ov0'],  "already in pool"),
                        (P['yellow'], "suggested exclude")]:
            tk.Label(leg, text="●", fg=fg, bg=P['bg'],
                     font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(4, 0))
            ttk.Label(leg, text=txt, style='Small.TLabel').pack(side=tk.LEFT, padx=(0, 8))

        # ── OK / Cancel ──────────────────────────────────────────────────────
        bf = ttk.Frame(root_f)
        bf.grid(row=3, column=0, sticky='ew', pady=(8, 0))
        self._ok_btn = ttk.Button(bf, text="Add Selected to Pool",
                                   style='Accent.TButton',
                                   command=self._ok, state='disabled')
        self._ok_btn.pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=4)

        self.bind('<Return>', lambda _: self._ok())
        self.bind('<Escape>', lambda _: self.destroy())

    # ── File loading ─────────────────────────────────────────────────────────

    def _browse(self):
        paths = filedialog.askopenfilenames(
            title="Select .ALO File(s)",
            filetypes=[("ALAMO Model", "*.ALO *.alo"), ("All files", "*.*")]
        )
        if paths:
            self._load_files(list(paths))

    def _load_files(self, paths: list[str]):
        if not _ALO_AVAILABLE:
            messagebox.showerror(
                "ALO Reader Unavailable",
                "alo_reader.py could not be imported.\n"
                "Make sure it is in the same directory as hp_generator_GUI.py.",
                parent=self)
            return

        all_bones: list[str] = []
        all_warns: list[str] = []
        loaded_names = []

        for p in paths:
            try:
                bones, warns = alo_reader.read_alo_bones(p)
                all_bones.extend(bones)
                all_warns.extend(warns)
                loaded_names.append(Path(p).name)
            except alo_reader.AloReadError as exc:
                all_warns.append(f"{Path(p).name}: {exc}")

        # De-duplicate across files while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for b in all_bones:
            if b not in seen:
                seen.add(b)
                unique.append(b)

        cross_dups = len(all_bones) - len(unique)
        if cross_dups:
            all_warns.append(f"{cross_dups} cross-file duplicate(s) removed.")

        # Determine a smart default selection
        # Bones whose lowercase name contains any exclude pattern → unchecked
        def _should_exclude(name: str) -> bool:
            nl = name.lower()
            return any(pat in nl for pat in self._EXCLUDE_PATTERNS)

        self._rows = []
        for name in unique:
            already = name in self._existing_names
            bv = tk.BooleanVar(value=(not already and not _should_exclude(name)))
            bv.trace_add('write', lambda *_: self._update_count())
            self._rows.append((name, bv, already))

        # Update file label
        if len(loaded_names) == 1:
            self._file_sv.set(loaded_names[0])
        else:
            self._file_sv.set(f"{len(loaded_names)} files: " + ", ".join(loaded_names))

        if all_warns:
            self._sv_status.set("⚠ " + " | ".join(all_warns[:3]))
        else:
            self._sv_status.set(f"✓ {len(unique)} unique bones loaded")

        self._ok_btn.configure(state='normal' if self._rows else 'disabled')
        self._refresh_list()

    # ── List management ───────────────────────────────────────────────────────

    def _refresh_list(self):
        for w in self._list_inner.winfo_children():
            w.destroy()

        filt = self._filter_var.get().lower()
        visible = 0

        for name, bv, already in self._rows:
            if filt and filt not in name.lower():
                continue

            row = ttk.Frame(self._list_inner)
            row.pack(fill=tk.X, padx=4, pady=1)

            if already:
                fg = P['ov0']
                label_text = f"{name}  (already in pool)"
            elif any(p in name.lower() for p in self._EXCLUDE_PATTERNS):
                fg = P['yellow']
                label_text = name
            else:
                fg = P['text']
                label_text = name

            cb = tk.Checkbutton(row, variable=bv,
                                 bg=P['s0'], fg=fg,
                                 activebackground=P['s1'], activeforeground=fg,
                                 selectcolor=P['s1'],
                                 bd=0, highlightthickness=0,
                                 cursor='hand2')
            cb.pack(side=tk.LEFT)
            lbl = tk.Label(row, text=label_text, fg=fg, bg=P['s0'],
                           font=('Consolas', 9), anchor='w', cursor='hand2')
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            lbl.bind('<Button-1>', lambda e, v=bv: v.set(not v.get()))
            visible += 1

        self._update_count()

    def _update_count(self):
        total    = len(self._rows)
        selected = sum(1 for _, bv, _ in self._rows if bv.get())
        self._sv_count.set(f"{selected} selected / {total} total")

    # ── Quick-select helpers ──────────────────────────────────────────────────

    def _sel_all(self):
        for _, bv, _ in self._rows:
            bv.set(True)

    def _sel_none(self):
        for _, bv, _ in self._rows:
            bv.set(False)

    def _sel_all_except_root(self):
        for name, bv, _ in self._rows:
            bv.set(name.lower() != 'root')

    def _sel_suggested(self):
        """Select all bones that aren't already in the pool and aren't suggested excludes."""
        for name, bv, already in self._rows:
            bv.set(not already and not any(p in name.lower() for p in self._EXCLUDE_PATTERNS))

    # ── OK ────────────────────────────────────────────────────────────────────

    def _ok(self):
        self.result = [
            name for name, bv, already in self._rows
            if bv.get() and not already
        ]
        self.destroy()


class XmlImportDialog(tk.Toplevel):
    """
    Preview and select hardpoints to import from an EaW XML file as templates.

    Displays a scrollable, filterable list of every <HardPoint> found in the
    file.  Each row shows a checkbox, the hardpoint name, its Type value, and
    the field count.  Quick-select buttons narrow the selection; the user then
    clicks "Import Selected" to append the chosen entries to the Template Editor.

    result : list[dict] | None
        None  → user cancelled.
        list  → (possibly empty) list of deep-copied template dicts to import.
    """

    def __init__(self, parent, templates: list, source_name: str = ""):
        super().__init__(parent)
        self.title("Import Hardpoints from XML as Templates")
        self.geometry("740x580")
        self.minsize(560, 420)
        self.configure(bg=P['bg'])
        self.result = None

        self._templates      = templates
        self._source         = source_name
        self._filter_var     = tk.StringVar()
        self._filter_after_id = None
        self._filter_var.trace_add('write', lambda *_: self._schedule_filter())

        # One BooleanVar per template — default all selected
        self._vars: list[tk.BooleanVar] = [
            tk.BooleanVar(value=True) for _ in templates
        ]
        for bv in self._vars:
            bv.trace_add('write', lambda *_: self._update_count())

        self._build()
        self.transient(parent)
        self.grab_set()
        self.wait_window()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        root_f = ttk.Frame(self, padding=10)
        root_f.pack(fill=tk.BOTH, expand=True)
        root_f.rowconfigure(2, weight=1)
        root_f.columnconfigure(0, weight=1)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = ttk.Frame(root_f)
        hdr.grid(row=0, column=0, sticky='ew', pady=(0, 6))

        ttk.Label(hdr,
                  text=f"Found {len(self._templates)} hardpoint(s)  ·  Source: {self._source}",
                  style='Header.TLabel').pack(anchor='w')
        ttk.Label(hdr, style='Small.TLabel', justify='left',
                  text=("Fire_Bone_A → {bone_a}     Fire_Bone_B → {bone_b}     "
                        "Attachment_Bone / Collision_Mesh → {bone_a} when matching Fire_Bone_A  "
                        "(original bone names preserved in a leading comment field)"),
                  wraplength=700).pack(anchor='w', pady=(2, 0))

        # ── Filter + quick-select row ─────────────────────────────────────────
        ctrl = ttk.Frame(root_f)
        ctrl.grid(row=1, column=0, sticky='ew', pady=(0, 4))
        ctrl.columnconfigure(1, weight=1)

        ttk.Label(ctrl, text="Filter:").grid(row=0, column=0, sticky='w', padx=(0, 4))
        ttk.Entry(ctrl, textvariable=self._filter_var
                  ).grid(row=0, column=1, sticky='ew', padx=(0, 6))
        ttk.Button(ctrl, text="✕", width=3,
                   command=lambda: self._filter_var.set('')
                   ).grid(row=0, column=2, padx=(0, 10))
        ttk.Button(ctrl, text="All",
                   command=self._sel_all).grid(row=0, column=3, padx=2)
        ttk.Button(ctrl, text="None",
                   command=self._sel_none).grid(row=0, column=4, padx=2)
        ttk.Button(ctrl, text="HP_ only",
                   command=self._sel_suggested).grid(row=0, column=5, padx=2)

        # ── Scrollable checkbox list ──────────────────────────────────────────
        lf = ttk.LabelFrame(root_f, text=" Hardpoints to Import ")
        lf.grid(row=2, column=0, sticky='nsew')
        lf.rowconfigure(0, weight=1)
        lf.columnconfigure(0, weight=1)

        cf = ttk.Frame(lf)
        cf.grid(row=0, column=0, sticky='nsew', padx=4, pady=4)
        cf.rowconfigure(0, weight=1); cf.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(cf, bg=P['s0'], highlightthickness=0)
        vsb = ttk.Scrollbar(cf, orient='vertical', command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        self._list_inner = ttk.Frame(self._canvas)
        self._cwin = self._canvas.create_window(
            (0, 0), window=self._list_inner, anchor='nw')
        self._list_inner.bind(
            '<Configure>',
            lambda e: self._canvas.configure(
                scrollregion=self._canvas.bbox('all')))
        self._canvas.bind(
            '<Configure>',
            lambda e: self._canvas.itemconfig(self._cwin, width=e.width))
        self._canvas.bind(
            '<MouseWheel>',
            lambda e: self._canvas.yview_scroll(int(-e.delta / 120), 'units'))

        # ── Count label + action buttons ──────────────────────────────────────
        bottom = ttk.Frame(root_f)
        bottom.grid(row=3, column=0, sticky='ew', pady=(8, 0))

        self._sv_count = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self._sv_count,
                  style='Small.TLabel').pack(side=tk.LEFT)
        ttk.Button(bottom, text="Cancel",
                   command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Import Selected as Templates",
                   style='Accent.TButton',
                   command=self._ok).pack(side=tk.RIGHT, padx=4)

        self.bind('<Return>', lambda _: self._ok())
        self.bind('<Escape>', lambda _: self.destroy())

        self._refresh_list()

    # ── Filter debounce ───────────────────────────────────────────────────────

    def _schedule_filter(self):
        """Cancel any pending filter refresh and schedule a fresh one after 350 ms.

        This prevents the canvas from being rebuilt on every keystroke while the
        user is still typing, which made large XML imports feel sluggish.
        """
        if self._filter_after_id:
            try:
                self.after_cancel(self._filter_after_id)
            except Exception:
                pass
        self._filter_after_id = self.after(350, self._do_filter_refresh)

    def _do_filter_refresh(self):
        self._filter_after_id = None
        self._refresh_list()

    # ── List rendering ────────────────────────────────────────────────────────

    def _type_for(self, tpl: dict) -> str:
        """Return the value of the first Type field in the template, or ''."""
        for f in tpl.get("fields", []):
            if f.get("tag") == "Type":
                return f.get("value", "")
        return ""

    def _refresh_list(self):
        for w in self._list_inner.winfo_children():
            w.destroy()

        filt = self._filter_var.get().lower()

        for i, (tpl, bv) in enumerate(zip(self._templates, self._vars)):
            name = tpl.get("name", f"(unnamed {i + 1})")
            if filt and filt not in name.lower():
                continue

            type_val = self._type_for(tpl)
            # Count real element fields (exclude comment/blank meta-entries)
            n_elem = sum(
                1 for f in tpl.get("fields", [])
                if f.get("_type", "element") == "element"
            )

            row = ttk.Frame(self._list_inner)
            row.pack(fill=tk.X, padx=4, pady=1)

            cb = tk.Checkbutton(
                row, variable=bv,
                bg=P['s0'], fg=P['text'],
                activebackground=P['s1'], activeforeground=P['text'],
                selectcolor=P['s1'], bd=0, highlightthickness=0,
                cursor='hand2')
            cb.pack(side=tk.LEFT)

            name_lbl = tk.Label(
                row, text=name, fg=P['blue'], bg=P['s0'],
                font=('Consolas', 9, 'bold'), anchor='w',
                cursor='hand2', width=42)
            name_lbl.pack(side=tk.LEFT)
            name_lbl.bind('<Button-1>', lambda e, v=bv: v.set(not v.get()))

            type_lbl = tk.Label(
                row, text=type_val, fg=P['teal'], bg=P['s0'],
                font=('Consolas', 9), anchor='w', cursor='hand2')
            type_lbl.pack(side=tk.LEFT, padx=(8, 0))
            type_lbl.bind('<Button-1>', lambda e, v=bv: v.set(not v.get()))

            tk.Label(
                row, text=f"  {n_elem} fields",
                fg=P['ov0'], bg=P['s0'],
                font=('Consolas', 8), anchor='w'
            ).pack(side=tk.LEFT)

        self._update_count()

    def _update_count(self):
        total    = len(self._templates)
        selected = sum(1 for bv in self._vars if bv.get())
        self._sv_count.set(f"{selected} selected / {total} total")

    # ── Quick-select helpers ──────────────────────────────────────────────────

    def _sel_all(self):
        for bv in self._vars:
            bv.set(True)

    def _sel_none(self):
        for bv in self._vars:
            bv.set(False)

    def _sel_suggested(self):
        for tpl, bv in zip(self._templates, self._vars):
            bv.set(tpl.get("name", "").upper().startswith("HP_"))

    # ── OK ────────────────────────────────────────────────────────────────────

    def _ok(self):
        self.result = [
            copy.deepcopy(tpl)
            for tpl, bv in zip(self._templates, self._vars)
            if bv.get()
        ]
        self.destroy()


class WrapFrame(tk.Frame):
    """
    A Frame that lays out its children in a left-to-right flow and wraps
    them into additional rows when there is not enough horizontal space —
    exactly like CSS flexbox with flex-wrap:wrap.

    Usage:
        bar = WrapFrame(parent, padx=2, pady=2)
        bar.pack(fill=tk.X)
        bar.add(ttk.Button(bar, text="Foo"))
        bar.add_sep()   # vertical separator between groups

    Children must be added via bar.add() so the WrapFrame knows about them.
    Do NOT use pack/grid/place directly on children — the WrapFrame manages
    their geometry via .place() internally.
    """

    def __init__(self, parent, padx=2, pady=2, row_pady=1, **kw):
        kw.setdefault('background', P['bg'])
        super().__init__(parent, **kw)
        self._children_info = []   # list of (widget, is_sep, padx, pady)
        self._padx     = padx
        self._pady     = pady
        self._row_pady = row_pady

        # Re-entrancy guard: prevents _layout from triggering itself via
        # self.configure(height=...) which fires another <Configure> event.
        self._laying_out = False

        # Pending after() id for debounced layout — avoids hammering _layout
        # on every pixel of a resize drag.
        self._layout_pending = None

        self.bind('<Configure>', self._on_configure)

    # ── Public API ─────────────────────────────────────────────────────────

    def add(self, widget, is_sep=False, padx=None, pady=None):
        """Register *widget* with this WrapFrame and schedule a layout pass."""
        self._children_info.append((
            widget,
            is_sep,
            padx if padx is not None else self._padx,
            pady if pady is not None else self._pady,
        ))
        # Schedule layout after the widget has been realised so that
        # winfo_reqwidth/height return correct values.
        self._schedule_layout()
        return widget

    def add_sep(self):
        """Add a vertical separator (suppressed at row starts after wrapping)."""
        sep = ttk.Separator(self, orient='vertical')
        self.add(sep, is_sep=True, padx=6, pady=2)
        return sep

    # ── Internal helpers ───────────────────────────────────────────────────

    def _on_configure(self, event):
        # event.width == 1 means the widget is not yet mapped; ignore.
        if event.width > 1:
            self._schedule_layout(event.width)

    def _schedule_layout(self, width=None):
        """Debounce layout: cancel any pending pass and schedule a fresh one."""
        if self._layout_pending is not None:
            try:
                self.after_cancel(self._layout_pending)
            except Exception:
                pass
        # after_idle fires once the event loop is idle — after all pending
        # <Configure> events have been processed — so _layout runs exactly
        # once per resize batch with no re-entrancy risk.
        self._layout_pending = self.after_idle(
            lambda w=width: self._layout(w))

    # ── Layout engine ──────────────────────────────────────────────────────

    def _layout(self, avail_width=None):
        """Place all registered children into wrapping rows."""
        # Clear the pending id since we are now running.
        self._layout_pending = None

        # Re-entrancy guard: self.configure(height=...) at the end triggers
        # another <Configure> which would call _layout again synchronously.
        if self._laying_out:
            return
        self._laying_out = True
        try:
            self._do_layout(avail_width)
        finally:
            self._laying_out = False

    def _do_layout(self, avail_width=None):
        if avail_width is None:
            avail_width = self.winfo_width()
        if avail_width <= 1:
            avail_width = 9999   # not yet mapped — lay out without wrapping

        # Forget all existing placements
        for widget, *_ in self._children_info:
            widget.place_forget()

        x = 0
        y = 0
        row_h = 0
        rows = [[]]  # list of rows; each row: list of (widget,is_sep,padx,pady,x,y,rw,rh)

        for widget, is_sep, padx, pady in self._children_info:
            # Read natural size directly — no update_idletasks() needed here
            # because winfo_reqwidth/height always reflect the latest requested
            # size even before the widget is mapped.
            req_w = widget.winfo_reqwidth() + padx * 2
            req_h = widget.winfo_reqheight()

            # Separators are suppressed at the very start of any row
            if is_sep and x == 0:
                continue

            if x > 0 and x + req_w > avail_width:
                # Wrap — drop any trailing separator in the current row
                while rows[-1] and rows[-1][-1][1]:
                    rows[-1].pop()
                rows.append([])
                x = 0
                y += row_h + self._row_pady * 2
                row_h = 0

            # Suppress separator again if we just wrapped to a new row
            if is_sep and x == 0:
                continue

            rows[-1].append((widget, is_sep, padx, pady, x, y, req_w, req_h))
            x += req_w
            row_h = max(row_h, req_h + pady * 2)

        # Place widgets at their computed positions
        for row in rows:
            for widget, is_sep, padx, pady, rx, ry, rw, rh in row:
                widget.place(x=rx + padx, y=ry + pady,
                             width=widget.winfo_reqwidth(),
                             height=widget.winfo_reqheight())

        # Compute total height and resize self so the parent allocates enough
        # space.  This fires a new <Configure> on self, but the re-entrancy
        # guard above absorbs it safely.
        all_y = 0
        for row in rows:
            if not row:
                continue
            rh = max(it[7] + it[3] * 2 for it in row)
            all_y += rh + self._row_pady * 2
        new_h = max(all_y, 4)
        if self.winfo_reqheight() != new_h:
            self.configure(height=new_h)


# ─────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────

class App:

    # ── Init ─────────────────────────────────────

    def __init__(self, root: tk.Tk, open_path: str | None = None):
        self.root = root
        self.root.title(APP_TITLE)
        #self.root.minsize(MIN_W, MIN_H)
        self.root.geometry(f"{MIN_W+60}x{MIN_H+40}")

        # State
        self.config_path: Path | None = None
        self.config: dict = {}
        self.dirty = False
        self._loading = False

        self.template_registry: dict = {}
        self.raw_registry:      dict = {}
        self.component_registry: dict = {}
        self.raw_comp_registry:  dict = {}
        self._editing_group_idx: int | None = None
        self._ge_saving: bool = False   # suppresses _ge_load during _ge_save's own selection restore

        # Browser sort state
        self._tpl_sort_col = 'name'
        self._tpl_sort_rev = False
        self._comp_sort_col = 'name'
        self._comp_sort_rev = False

        # Template editor state
        self._te_file_path: Path | None = None   # file currently open in editor
        self._te_templates: list = []            # list of template dicts being edited
        self._te_active_idx: int | None = None   # index into _te_templates
        self._te_dirty = False
        self._te_field_store: dict = {}          # maps treeview iid -> field dict
        self._te_loading = False                 # suppress auto-apply during load
        self._te_meta_refresh_id = None          # pending after() id for debounced list refresh
        self._te_inline_entry = None             # currently open inline cell editor widget

        # Config field StringVars
        self.sv = {k: tk.StringVar() for k in
                   ('ship_name', 'output_file', 'templates', 'components',
                    'tm_start', 'tm_format', 'dp_start', 'dp_format')}
        for sv in self.sv.values():
            sv.trace_add('write', self._on_cfg_changed)

        self._build_styles()
        self._build_ui()
        self._new_config(prompt=False)

        # Defer sash positioning until after the window is fully rendered
        self._set_initial_sashes()

        if open_path:
            self.root.after(100, lambda: self._open_config(Path(open_path)))

    # ── Sash Positioning ─────────────────────────

    def _set_initial_sashes(self):
        """
        Set all PanedWindow sash positions after the window is fully rendered.

        Panes that live inside non-active notebook tabs report winfo_width() == 1
        until their tab is first shown.  We handle this with two strategies:

          1. Multiple timed passes for panes that ARE visible at startup.
          2. A notebook <<NotebookTabChanged>> binding that positions sashes
             the first time each hidden tab is revealed.
        """
        # Track which tab-specific sashes have already been initialised so we
        # only force-set them once (after that the user may have moved them).
        self._sash_initialised = set()

        def _apply_global():
            """Position sashes that are visible from startup."""
            try:
                self.root.update_idletasks()
                h = self.root.winfo_height()
                w = self.root.winfo_width()

                # Outer vertical pane: upper content / log (~72% to content)
                self._outer.sashpos(0, max(200, int(h * 0.80)))

                # Horizontal pane: sidebar / main notebook
                self._h_pane.sashpos(0, 264)

                # Bones & Groups tab (tab index 0 — visible at startup)
                if hasattr(self, '_bones_groups_pane'):
                    bgp_w = self._bones_groups_pane.winfo_width()
                    target = max(200, int(bgp_w * 0.28) if bgp_w > 10 else int(w * 0.28))
                    self._bones_groups_pane.sashpos(0, target)

                if hasattr(self, '_groups_pane'):
                    groups_h = self._groups_pane.winfo_height()
                    target = max(180, int(groups_h * 0.32) if groups_h > 50 else 220)
                    self._groups_pane.sashpos(0, target)

                # Group Editor horizontal pane: Settings | Notebook(Bones/Comps/Overrides)
                if hasattr(self, '_group_editor_pane'):
                    ge_w = self._group_editor_pane.winfo_width()
                    if ge_w > 50:
                        self._group_editor_pane.sashpos(0, max(220, int(ge_w * 0.32)))

            except Exception:
                pass

        def _apply_tab(tab_index: int):
            """Position sashes for a specific tab once it is visible."""
            try:
                self.root.update_idletasks()
                w = self.root.winfo_width()

                if tab_index == 1 and hasattr(self, '_template_browser_pane'):
                    # Template Browser: list ~38% | detail ~62%
                    pane_w = self._template_browser_pane.winfo_width()
                    target = max(220, int(pane_w * 0.38) if pane_w > 50 else int(w * 0.28))
                    self._template_browser_pane.sashpos(0, target)

                if tab_index == 2 and hasattr(self, '_comp_browser_pane'):
                    # Component Browser: list ~38% | detail ~62%
                    pane_w = self._comp_browser_pane.winfo_width()
                    target = max(220, int(pane_w * 0.38) if pane_w > 50 else int(w * 0.28))
                    self._comp_browser_pane.sashpos(0, target)

                if tab_index == 3 and hasattr(self, '_te_pane_ref'):
                    # Template Editor: list ~22% | editor ~78%
                    pane_w = self._te_pane_ref.winfo_width()
                    target = max(200, int(pane_w * 0.22) if pane_w > 50 else int(w * 0.20))
                    self._te_pane_ref.sashpos(0, target)

            except Exception:
                pass

        def _on_tab_changed(event):
            """Apply sashes the first time a non-startup tab becomes visible."""
            try:
                idx = self.notebook.index(self.notebook.select())
            except Exception:
                return
            if idx not in self._sash_initialised:
                self._sash_initialised.add(idx)
                # Two quick passes so the pane has time to report real dimensions
                self.root.after(30,  lambda i=idx: _apply_tab(i))
                self.root.after(150, lambda i=idx: _apply_tab(i))

        # Bind the tab-change event so hidden tabs get positioned on first reveal
        if hasattr(self, 'notebook'):
            self.notebook.bind('<<NotebookTabChanged>>', _on_tab_changed)
        else:
            # notebook not built yet — bind after build completes
            self.root.after(100, lambda: self.notebook.bind(
                '<<NotebookTabChanged>>', _on_tab_changed))

        # Three passes for the startup-visible panes
        self.root.after(50,  _apply_global)
        self.root.after(200, _apply_global)
        self.root.after(500, _apply_global)

    # ── Styles ───────────────────────────────────

    def _build_styles(self):
        s = ttk.Style(self.root)
        try:
            s.theme_use('clam')
        except Exception:
            pass

        bg, surf, surf1 = P['bg'], P['s0'], P['s1']
        text, sub, blue = P['text'], P['sub0'], P['blue']

        s.configure('.', background=bg, foreground=text, fieldbackground=surf,
                    selectbackground=blue, selectforeground=bg,
                    insertcolor=text, bordercolor=surf1,
                    troughcolor=surf, relief='flat')

        for name, cfg in [
            ('TFrame',      {'background': bg}),
            ('TLabel',      {'background': bg, 'foreground': text}),
            ('TEntry',      {'fieldbackground': surf, 'foreground': text, 'insertcolor': text}),
            ('TSpinbox',    {'fieldbackground': surf, 'foreground': text}),
            ('TCombobox',   {'fieldbackground': surf, 'foreground': text, 'background': surf, 'arrowcolor': text}),
            ('TButton',     {'background': surf, 'foreground': text, 'padding': (6, 3)}),
            ('TNotebook',   {'background': bg, 'tabmargins': [2, 2, 0, 0]}),
            ('TNotebook.Tab', {'background': surf, 'foreground': sub, 'padding': (10, 4)}),
            ('Treeview',    {'background': surf, 'fieldbackground': surf, 'foreground': text, 'rowheight': 24, 'borderwidth': 0}),
            ('Treeview.Heading', {'background': surf1, 'foreground': P['sub1'], 'relief': 'flat'}),
            ('TLabelframe',     {'background': bg}),
            ('TLabelframe.Label', {'background': bg, 'foreground': P['mauve']}),
            ('TPanedwindow', {'background': surf1}),
            ('TScrollbar',  {'background': surf1, 'troughcolor': surf, 'arrowcolor': sub, 'bordercolor': bg}),
            ('TCheckbutton',{'background': bg, 'foreground': text}),
            ('TSeparator',  {'background': surf1}),
        ]:
            s.configure(name, **cfg)

        s.map('TCombobox',
              fieldbackground=[('readonly', surf)],
              foreground=[('readonly', text), ('disabled', sub)],
              selectbackground=[('readonly', surf)],
              selectforeground=[('readonly', text)])
        s.map('TButton', background=[('active', surf1), ('pressed', P['s2'])])
        s.map('TNotebook.Tab', background=[('selected', surf1)], foreground=[('selected', text)])
        s.map('Treeview', background=[('selected', blue)], foreground=[('selected', bg)])

        for name, bg_c, hover in [
            ('Accent.TButton',  blue,          P['sapphire']),
            ('Success.TButton', P['green'],     P['teal']),
            ('Warn.TButton',    P['yellow'],    P['peach']),
            ('Danger.TButton',  P['red'],       P['maroon']),
            ('Mauve.TButton',   P['mauve'],     P['pink']),
        ]:
            s.configure(name, background=bg_c, foreground=bg)
            s.map(name, background=[('active', hover), ('pressed', surf1)])

        s.configure('Header.TLabel',  background=bg, foreground=blue,   font=('Segoe UI', 10, 'bold'))
        s.configure('Section.TLabel', background=P['mantle'], foreground=P['mauve'], font=('Segoe UI', 9, 'bold'))
        s.configure('Small.TLabel',   background=bg, foreground=sub,    font=('Segoe UI', 8))
        s.configure('Warn.TLabel',    background=bg, foreground=P['yellow'])
        s.configure('Good.TLabel',    background=bg, foreground=P['green'])
        s.configure('Err.TLabel',     background=bg, foreground=P['red'])
        s.configure('Sidebar.TFrame', background=P['mantle'])
        s.configure('Sidebar.TLabel', background=P['mantle'], foreground=text)
        s.configure('SidebarSmall.TLabel', background=P['mantle'], foreground=sub, font=('Segoe UI', 8))

        self.root.configure(background=bg)

    # ── UI Construction ───────────────────────────

    def _build_ui(self):
        self._build_menu()

        self._outer = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        self._outer.pack(fill=tk.BOTH, expand=True)

        upper = ttk.Frame(self._outer)
        self._outer.add(upper, weight=4)

        self._build_toolbar(upper)

        self._h_pane = ttk.PanedWindow(upper, orient=tk.HORIZONTAL)
        self._h_pane.pack(fill=tk.BOTH, expand=True)

        sidebar = self._build_sidebar(self._h_pane)
        self._h_pane.add(sidebar, weight=0)

        main_nb = self._build_main_notebook(self._h_pane)
        self._h_pane.add(main_nb, weight=1)

        log_frame = self._build_log(self._outer)
        self._outer.add(log_frame, weight=1)

        # Sash positions are set after the window is fully rendered — see _set_initial_sashes()

    # ── Menu ─────────────────────────────────────

    def _build_menu(self):
        def menu(**kw):
            return tk.Menu(self.root, tearoff=False,
                           background=P['s0'], foreground=P['text'],
                           activebackground=P['blue'], activeforeground=P['bg'], **kw)

        mb = menu()
        self.root.config(menu=mb)

        fm = menu()
        mb.add_cascade(label="File", menu=fm)
        fm.add_command(label="New Config",       command=self._file_new,      accelerator="Ctrl+N")
        fm.add_command(label="Open Config…",     command=self._file_open,     accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="Save",             command=self._file_save,     accelerator="Ctrl+S")
        fm.add_command(label="Save As…",         command=self._file_save_as,  accelerator="Ctrl+Shift+S")
        fm.add_separator()
        fm.add_command(label="Exit",             command=self._on_close)

        gm = menu()
        mb.add_cascade(label="Generate", menu=gm)
        gm.add_command(label="⚡ Generate XML",    command=self._do_generate,  accelerator="F5")
        gm.add_command(label="📋 List Hardpoints", command=self._do_list,      accelerator="F6")
        gm.add_command(label="🔍 Dump Template…",  command=self._do_dump,      accelerator="F7")
        gm.add_separator()
        gm.add_command(label="↺ Reload Templates", command=self._templates_reload)

        vm = menu()
        mb.add_cascade(label="View", menu=vm)
        vm.add_command(label="Template Browser",    command=lambda: self.notebook.select(1))
        vm.add_command(label="Bones & Groups",      command=lambda: self.notebook.select(0))
        vm.add_command(label="Component Browser",   command=lambda: self.notebook.select(2))
        vm.add_command(label="Template Editor",     command=lambda: self.notebook.select(3))
        vm.add_separator()
        vm.add_command(label="Clear Log",           command=self._log_clear)

        hm = menu()
        mb.add_cascade(label="Help", menu=hm)
        hm.add_command(label="About", command=self._show_about)
        hm.add_command(label="Field Format Reference", command=self._show_field_help)

        self.root.bind('<Control-n>', lambda _: self._file_new())
        self.root.bind('<Control-o>', lambda _: self._file_open())
        self.root.bind('<Control-s>', lambda _: self._file_save())
        self.root.bind('<Control-S>', lambda _: self._file_save_as())
        self.root.bind('<F5>',        lambda _: self._do_generate())
        self.root.bind('<F6>',        lambda _: self._do_list())
        self.root.bind('<F7>',        lambda _: self._do_dump())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Toolbar ───────────────────────────────────

    def _build_toolbar(self, parent):
        # Outer frame holds the WrapFrame on the left and status on the right
        outer = ttk.Frame(parent)
        outer.pack(fill=tk.X, padx=2, pady=2)

        self.sv_status = tk.StringVar(value="Ready")
        ttk.Label(outer, textvariable=self.sv_status, style='Small.TLabel').pack(side=tk.RIGHT, padx=12)

        if not _GEN_AVAILABLE:
            ttk.Label(outer, text="⚠ hp_generator.py not found — generation disabled",
                      foreground=P['yellow'], background=P['bg'],
                      font=('Segoe UI', 8)).pack(side=tk.RIGHT, padx=8)

        tb = WrapFrame(outer, padx=2, pady=2)
        tb.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def tbtn(text, cmd, style='TButton'):
            b = ttk.Button(tb, text=text, command=cmd, style=style)
            tb.add(b)
            return b

        tbtn("📄 New",    self._file_new)
        tbtn("📂 Open",   self._file_open)
        tbtn("💾 Save",   self._file_save)
        tbtn("Save As…",  self._file_save_as)
        tb.add_sep()
        tbtn("⚡ Generate XML",   self._do_generate,        'Success.TButton')
        tbtn("📋 List HPs",        self._do_list)
        tbtn("🔍 Dump Template",   self._do_dump)
        tb.add_sep()
        tbtn("↺ Reload Templates",  self._templates_reload,  'Mauve.TButton')
        #tbtn("✏ Template Editor",   lambda: self.notebook.select(2), 'Mauve.TButton')
        tbtn("↺ Reload Components",self._components_reload,  'Mauve.TButton')

    # ── Left Sidebar ─────────────────────────────

    def _build_sidebar(self, parent) -> ttk.Frame:
        outer = ttk.Frame(parent, style='Sidebar.TFrame', width=264)
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=P['mantle'], highlightthickness=0, width=252)
        vsb = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas, style='Sidebar.TFrame')
        wid = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_inner(e):  canvas.configure(scrollregion=canvas.bbox('all'))
        def _on_canvas(e): canvas.itemconfig(wid, width=e.width)
        inner.bind('<Configure>', _on_inner)
        canvas.bind('<Configure>', _on_canvas)

        # Scroll only when the pointer is over the sidebar canvas/inner frame
        def _sidebar_scroll(e):
            canvas.yview_scroll(int(-e.delta / 120), 'units')
        canvas.bind('<MouseWheel>', _sidebar_scroll)
        inner.bind('<MouseWheel>', _sidebar_scroll)
        # Keep references so we can propagate to sidebar child widgets after build
        self._sidebar_canvas = canvas
        self._sidebar_inner  = inner

        p_ = {'padx': 10, 'pady': 3}
        sp = {'fill': tk.X, 'padx': 10, 'pady': 2}

        def section(text):
            ttk.Label(inner, text=text, style='Section.TLabel').pack(anchor='w', padx=10, pady=(10, 2))
            ttk.Separator(inner, orient='h').pack(**sp)

        def row_entry(label, sv, browse_fn=None, double_browse=False):
            ttk.Label(inner, text=label, style='Sidebar.TLabel').pack(anchor='w', **p_)
            row = ttk.Frame(inner, style='Sidebar.TFrame')
            row.pack(fill=tk.X, **p_)
            ttk.Entry(row, textvariable=sv).pack(side=tk.LEFT, fill=tk.X, expand=True)
            if browse_fn:
                ttk.Button(row, text="…", width=3, command=browse_fn
                           ).pack(side=tk.LEFT, padx=(2, 0))
            return row

        # ── Ship Config ──────────────────────────
        section("SHIP CONFIG")
        row_entry("Ship Name:",   self.sv['ship_name'])
        row_entry("Output File:", self.sv['output_file'], self._browse_output)

        ttk.Label(inner, text="Templates Path:", style='Sidebar.TLabel').pack(anchor='w', **p_)
        trow = ttk.Frame(inner, style='Sidebar.TFrame')
        trow.pack(fill=tk.X, **p_)
        ttk.Entry(trow, textvariable=self.sv['templates']).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(trow, text="📁", width=3, command=self._browse_tpl_dir ).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Button(trow, text="📄", width=3, command=self._browse_tpl_file).pack(side=tk.LEFT, padx=(2, 0))

        self.sv_tpl_status = tk.StringVar(value="No templates loaded")
        self._tpl_status_lbl = ttk.Label(inner, textvariable=self.sv_tpl_status, style='Warn.TLabel',
                                          wraplength=230, justify='left')
        self._tpl_status_lbl.pack(anchor='w', **p_)

        # ── Template exclude / include filters ──
        self._build_sidebar_filter_section(inner, 'template', _sidebar_scroll)

        ttk.Label(inner, text="Components Path:", style='Sidebar.TLabel').pack(anchor='w', **p_)
        crow = ttk.Frame(inner, style='Sidebar.TFrame')
        crow.pack(fill=tk.X, **p_)
        ttk.Entry(crow, textvariable=self.sv['components']).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(crow, text="📁", width=3, command=self._browse_comp_dir ).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Button(crow, text="📄", width=3, command=self._browse_comp_file).pack(side=tk.LEFT, padx=(2, 0))

        self.sv_comp_status = tk.StringVar(value="No components loaded")
        self._comp_status_lbl = ttk.Label(inner, textvariable=self.sv_comp_status, style='Warn.TLabel',
                                           wraplength=230, justify='left')
        self._comp_status_lbl.pack(anchor='w', **p_)

        # ── Component exclude / include filters ──
        self._build_sidebar_filter_section(inner, 'component', _sidebar_scroll)

        # ── Turret Models ────────────────────────
        section("TURRET MODELS")
        for label, key, w, klass in [("Start:", 'tm_start', 6, 'Spinbox'),
                                      ("Format:", 'tm_format', 8, 'Entry')]:
            r = ttk.Frame(inner, style='Sidebar.TFrame')
            r.pack(fill=tk.X, **p_)
            ttk.Label(r, text=label, style='Sidebar.TLabel', width=9).pack(side=tk.LEFT)
            if klass == 'Spinbox':
                ttk.Spinbox(r, textvariable=self.sv[key], from_=1, to=9999, width=w).pack(side=tk.LEFT)
            else:
                ttk.Entry(r, textvariable=self.sv[key], width=w).pack(side=tk.LEFT)
                ttk.Label(r, text='(e.g. "02d")', style='SidebarSmall.TLabel').pack(side=tk.LEFT, padx=4)
        ttk.Label(inner, text="Counter for {model_idx} in template field values.",
                  style='SidebarSmall.TLabel', wraplength=220).pack(anchor='w', padx=10, pady=(0,3))

        # ── Damage Particles ─────────────────────
        #section("DAMAGE PARTICLES")
        #for label, key, w, klass in [("Start:", 'dp_start', 6, 'Spinbox'),
        #                              ("Format:", 'dp_format', 8, 'Entry')]:
        #    r = ttk.Frame(inner, style='Sidebar.TFrame')
        #    r.pack(fill=tk.X, **p_)
        #    ttk.Label(r, text=label, style='Sidebar.TLabel', width=9).pack(side=tk.LEFT)
        #    if klass == 'Spinbox':
        #        ttk.Spinbox(r, textvariable=self.sv[key], from_=1, to=9999, width=w).pack(side=tk.LEFT)
        #    else:
        #        ttk.Entry(r, textvariable=self.sv[key], width=w).pack(side=tk.LEFT)
        #        ttk.Label(r, text='(e.g. "02d")', style='SidebarSmall.TLabel').pack(side=tk.LEFT, padx=4)
        #ttk.Label(inner, text="Counter for {damage_idx} in template field values.",
        #          style='SidebarSmall.TLabel', wraplength=220).pack(anchor='w', padx=10, pady=(0,3))

        # ── Quick Actions ────────────────────────
        section("QUICK ACTIONS")
        for txt, cmd, style in [
            ("⚡ Generate XML",    self._do_generate,       'Success.TButton'),
            ("📋 List Hardpoints", self._do_list,            'TButton'),
            ("🔍 Dump Template",   self._do_dump,            'TButton'),
            ("↺ Reload Templates", self._templates_reload,   'Mauve.TButton'),
            ("↺ Reload Components",self._components_reload,  'Mauve.TButton'),
        ]:
            ttk.Button(inner, text=txt, command=cmd, style=style
                       ).pack(fill=tk.X, padx=10, pady=2)

        # ── File Info ────────────────────────────
        section("FILE INFO")
        self.sv_file_info = tk.StringVar(value="No file loaded")
        ttk.Label(inner, textvariable=self.sv_file_info, style='SidebarSmall.TLabel',
                  wraplength=230, justify='left').pack(anchor='w', **p_)

        # ── JSON Preview ─────────────────────────
        section("JSON PREVIEW")
        self.json_preview = tk.Text(
            inner, height=16, state='disabled',
            bg=P['s0'], fg=P['sub0'],
            font=('Consolas', 7), relief='flat', wrap='none'
        )
        self.json_preview.pack(fill=tk.X, padx=10, pady=4)

        return outer

    # ── Sidebar Filter Section (Excludes / Includes) ───────────────────────

    def _build_sidebar_filter_section(self, parent, kind: str, scroll_fn):
        """
        Build the collapsible Excludes / Includes filter panel for *kind*
        ('template' or 'component').  The panel lives inside the sidebar's
        scrollable canvas so every child widget receives the scroll binding.

        Excludes: paths beneath the main Templates/Components folder that
                  should be silently skipped during loading.
        Includes: extra files or folders that are always loaded regardless of
                  the main path (even if that field is blank).

        Both lists are stored in the ship config as relative paths when the
        config file has already been saved, and as absolute paths otherwise.
        """
        label_prefix = "Template" if kind == 'template' else "Component"
        cfg_excl_key = f"{kind}_excludes"
        cfg_incl_key = f"{kind}_includes"

        # ── Single outer container packed once into parent ────────────────
        # Both the header row and the collapsible body live inside this frame
        # so that when the body is shown it always appears directly below the
        # toggle button, not appended to the end of the whole sidebar.
        outer = ttk.Frame(parent, style='Sidebar.TFrame')
        outer.pack(fill=tk.X, padx=6, pady=(2, 4))
        outer.bind('<MouseWheel>', scroll_fn)

        hdr_row = ttk.Frame(outer, style='Sidebar.TFrame')
        hdr_row.pack(fill=tk.X)
        hdr_row.bind('<MouseWheel>', scroll_fn)

        body = ttk.Frame(outer, style='Sidebar.TFrame')
        # body starts hidden; toggled by the button below

        _collapsed = [True]   # mutable cell so inner functions can modify it

        def _toggle():
            if _collapsed[0]:
                body.pack(fill=tk.X, pady=(2, 0))
                toggle_btn.configure(text="▾ Filters")
            else:
                body.pack_forget()
                toggle_btn.configure(text="▸ Filters")
            _collapsed[0] = not _collapsed[0]
            # Force the sidebar canvas to recalculate its scroll region
            parent.event_generate('<Configure>')

        def _expand_only():
            """Open the panel only if it is currently collapsed."""
            if _collapsed[0]:
                _toggle()

        toggle_btn = ttk.Button(hdr_row, text="▸ Filters", width=10,
                                command=_toggle, style='TButton')
        toggle_btn.pack(side=tk.LEFT)
        toggle_btn.bind('<MouseWheel>', scroll_fn)
        ttk.Label(hdr_row, text="excludes / includes",
                  style='SidebarSmall.TLabel').pack(side=tk.LEFT, padx=4)

        # ── EXCLUDES section ──────────────────────────────────────────────
        excl_hdr = ttk.Frame(body, style='Sidebar.TFrame')
        excl_hdr.pack(fill=tk.X, pady=(6, 0))
        excl_hdr.bind('<MouseWheel>', scroll_fn)
        tk.Label(excl_hdr, text="Exclude  (skip these paths):",
                 bg=P['mantle'], fg=P['yellow'],
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=4)

        excl_lbf = ttk.Frame(body, style='Sidebar.TFrame')
        excl_lbf.pack(fill=tk.X, padx=4, pady=(2, 0))
        excl_lbf.columnconfigure(0, weight=1)

        excl_lb = tk.Listbox(
            excl_lbf, height=3, selectmode='extended',
            bg=P['s0'], fg=P['yellow'],
            selectbackground=P['s1'], selectforeground=P['yellow'],
            font=('Consolas', 7), relief='flat',
            activestyle='none', highlightthickness=0)
        excl_lb.grid(row=0, column=0, sticky='ew')
        excl_lb.bind('<MouseWheel>', scroll_fn)
        excl_lb.bind('<Delete>',     lambda e: self._filter_list_remove(cfg_excl_key, excl_lb, kind))
        excl_lb.bind('<Double-1>',   lambda e: self._filter_list_remove(cfg_excl_key, excl_lb, kind))

        excl_vsb = ttk.Scrollbar(excl_lbf, orient='vertical', command=excl_lb.yview)
        excl_lb.configure(yscrollcommand=excl_vsb.set)
        excl_vsb.grid(row=0, column=1, sticky='ns')

        excl_btns = ttk.Frame(body, style='Sidebar.TFrame')
        excl_btns.pack(fill=tk.X, padx=4, pady=(2, 4))
        excl_btns.bind('<MouseWheel>', scroll_fn)

        def _excl_add_dir():
            p = filedialog.askdirectory(
                title=f"Exclude {label_prefix} Folder",
                initialdir=self._filter_initial_dir(kind))
            if p:
                self._filter_list_add(cfg_excl_key, p, excl_lb, kind)

        def _excl_add_file():
            p = filedialog.askopenfilename(
                title=f"Exclude {label_prefix} File",
                initialdir=self._filter_initial_dir(kind),
                filetypes=[("JSON", "*.json"), ("All", "*.*")])
            if p:
                self._filter_list_add(cfg_excl_key, p, excl_lb, kind)

        def _excl_remove():
            self._filter_list_remove(cfg_excl_key, excl_lb, kind)

        ttk.Button(excl_btns, text="📁 Folder", width=8,
                   command=_excl_add_dir).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(excl_btns, text="📄 File", width=7,
                   command=_excl_add_file).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(excl_btns, text="✕", width=3,
                   command=_excl_remove,
                   style='Danger.TButton').pack(side=tk.LEFT)
        for w in excl_btns.winfo_children():
            w.bind('<MouseWheel>', scroll_fn)

        # ── INCLUDES section ──────────────────────────────────────────────
        incl_hdr = ttk.Frame(body, style='Sidebar.TFrame')
        incl_hdr.pack(fill=tk.X, pady=(6, 0))
        incl_hdr.bind('<MouseWheel>', scroll_fn)
        tk.Label(incl_hdr, text="Include  (always load these paths):",
                 bg=P['mantle'], fg=P['green'],
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=4)

        incl_lbf = ttk.Frame(body, style='Sidebar.TFrame')
        incl_lbf.pack(fill=tk.X, padx=4, pady=(2, 0))
        incl_lbf.columnconfigure(0, weight=1)

        incl_lb = tk.Listbox(
            incl_lbf, height=3, selectmode='extended',
            bg=P['s0'], fg=P['green'],
            selectbackground=P['s1'], selectforeground=P['green'],
            font=('Consolas', 7), relief='flat',
            activestyle='none', highlightthickness=0)
        incl_lb.grid(row=0, column=0, sticky='ew')
        incl_lb.bind('<MouseWheel>', scroll_fn)
        incl_lb.bind('<Delete>',     lambda e: self._filter_list_remove(cfg_incl_key, incl_lb, kind))
        incl_lb.bind('<Double-1>',   lambda e: self._filter_list_remove(cfg_incl_key, incl_lb, kind))

        incl_vsb = ttk.Scrollbar(incl_lbf, orient='vertical', command=incl_lb.yview)
        incl_lb.configure(yscrollcommand=incl_vsb.set)
        incl_vsb.grid(row=0, column=1, sticky='ns')

        incl_btns = ttk.Frame(body, style='Sidebar.TFrame')
        incl_btns.pack(fill=tk.X, padx=4, pady=(2, 4))
        incl_btns.bind('<MouseWheel>', scroll_fn)

        def _incl_add_dir():
            p = filedialog.askdirectory(
                title=f"Include {label_prefix} Folder",
                initialdir=self._filter_initial_dir(kind))
            if p:
                self._filter_list_add(cfg_incl_key, p, incl_lb, kind)

        def _incl_add_file():
            p = filedialog.askopenfilename(
                title=f"Include {label_prefix} File",
                initialdir=self._filter_initial_dir(kind),
                filetypes=[("JSON", "*.json"), ("All", "*.*")])
            if p:
                self._filter_list_add(cfg_incl_key, p, incl_lb, kind)

        def _incl_remove():
            self._filter_list_remove(cfg_incl_key, incl_lb, kind)

        ttk.Button(incl_btns, text="📁 Folder", width=8,
                   command=_incl_add_dir).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(incl_btns, text="📄 File", width=7,
                   command=_incl_add_file).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(incl_btns, text="✕", width=3,
                   command=_incl_remove,
                   style='Danger.TButton').pack(side=tk.LEFT)
        for w in incl_btns.winfo_children():
            w.bind('<MouseWheel>', scroll_fn)

        # Hint line
        tk.Label(body, text="Paths shown relative to config file when saved.",
                 bg=P['mantle'], fg=P['ov0'],
                 font=('Segoe UI', 7), justify='left').pack(
            anchor='w', padx=4, pady=(0, 4))

        # ── Store references for _load_cfg_to_ui / _sync_cfg_from_ui ─────
        # _filter_toggle = full toggle (collapse/expand); _filter_expand = expand-only
        if kind == 'template':
            self._tpl_excl_lb = excl_lb
            self._tpl_incl_lb = incl_lb
            self._tpl_filter_toggle = _expand_only   # used by _filter_list_add
        else:
            self._comp_excl_lb = excl_lb
            self._comp_incl_lb = incl_lb
            self._comp_filter_toggle = _expand_only   # used by _filter_list_add

    # ── Filter list helpers ────────────────────────────────────────────────

    def _filter_initial_dir(self, kind: str) -> str:
        """Return a sensible starting directory for filter browse dialogs."""
        sv_key = 'templates' if kind == 'template' else 'components'
        raw = self.sv[sv_key].get().strip()
        if raw:
            p = Path(resolve_path(self.config_path, raw))
            return str(p if p.is_dir() else p.parent)
        if self.config_path:
            return str(self.config_path.parent)
        return _script_dir()

    def _filter_list_add(self, cfg_key: str, path: str, lb: tk.Listbox, kind: str):
        """
        Add *path* to the config filter list and the sidebar listbox.
        Stores a path relative to the config file when possible.
        Triggers an immediate template/component reload.
        Silently ignores duplicates.
        Auto-expands the filter panel when the first item is added.
        """
        display = self._make_rel(path)
        lst = self.config.setdefault(cfg_key, [])
        # Reject duplicates (compare normalised absolute paths)
        abs_new = Path(resolve_path(self.config_path, display)).resolve()
        for existing in lst:
            try:
                if Path(resolve_path(self.config_path, existing)).resolve() == abs_new:
                    return
            except Exception:
                pass
        was_empty = len(lst) == 0
        lst.append(display)
        lb.insert(tk.END, display)
        # Auto-expand the collapsible filter panel so the user sees their entry
        if was_empty:
            toggle_attr = '_tpl_filter_toggle' if kind == 'template' else '_comp_filter_toggle'
            toggle_fn = getattr(self, toggle_attr, None)
            if toggle_fn is not None:
                try:
                    toggle_fn()   # expand if currently collapsed
                except Exception:
                    pass
        self._mark_dirty()
        self._update_json_preview()
        if kind == 'template':
            self._templates_reload()
        else:
            self._components_reload()

    def _filter_list_remove(self, cfg_key: str, lb: tk.Listbox, kind: str):
        """Remove the selected entries from the config filter list and listbox."""
        idxs = list(lb.curselection())
        if not idxs:
            return
        lst = self.config.get(cfg_key, [])
        for i in reversed(idxs):
            if i < len(lst):
                lst.pop(i)
            lb.delete(i)
        self._mark_dirty()
        self._update_json_preview()
        if kind == 'template':
            self._templates_reload()
        else:
            self._components_reload()

    def _filter_lb_load(self, lb: tk.Listbox, paths: list):
        """Populate a filter Listbox from a saved path list."""
        lb.delete(0, tk.END)
        for p in paths:
            lb.insert(tk.END, p)

    # ── Main Notebook ─────────────────────────────

    def _build_main_notebook(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        self.notebook = ttk.Notebook(frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        tab1 = ttk.Frame(self.notebook)
        self.notebook.add(tab1, text="  Bones & Groups  ")
        self._build_bones_groups_tab(tab1)

        tab2 = ttk.Frame(self.notebook)
        self.notebook.add(tab2, text="  Template Browser  ")
        self._build_template_browser(tab2)

        tab4 = ttk.Frame(self.notebook)
        self.notebook.add(tab4, text="  Component Browser  ")
        self._build_component_browser(tab4)

        tab3 = ttk.Frame(self.notebook)
        self.notebook.add(tab3, text="  Template Editor  ")
        self._build_template_editor(tab3)

        return frame

    # ── Bones & Groups Tab ────────────────────────

    def _build_bones_groups_tab(self, parent):
        hp = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        hp.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        hp.add(self._build_bones_panel(hp), weight=2)
        hp.add(self._build_groups_panel(hp), weight=3)

        self._bones_groups_pane = hp   # saved for deferred sash positioning

    # ── Bones Panel ───────────────────────────────

    def _build_bones_panel(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(3, weight=1)   # treeview row expands; button row always visible

        hdr = ttk.Frame(f)
        hdr.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))
        ttk.Label(hdr, text="BONE POOL", style='Header.TLabel').pack(side=tk.LEFT)
        self.sv_bone_count = tk.StringVar(value="0 bones")
        ttk.Label(hdr, textvariable=self.sv_bone_count, style='Small.TLabel').pack(side=tk.LEFT, padx=8)

        # Legend
        leg = ttk.Frame(f)
        leg.grid(row=1, column=0, sticky='ew', padx=4, pady=(0, 2))
        for color, lbl in [(P['sub0'], "unassigned"), (P['text'], "1 group"), (P['peach'], "multi-group")]:
            tk.Label(leg, text="●", fg=color, bg=P['bg'], font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(4,0))
            ttk.Label(leg, text=lbl, style='Small.TLabel').pack(side=tk.LEFT, padx=(0,6))

        sr = ttk.Frame(f)
        sr.grid(row=2, column=0, sticky='ew', padx=4, pady=(0, 2))
        ttk.Label(sr, text="Filter:").pack(side=tk.LEFT, padx=(0, 4))
        self.sv_bone_filter = tk.StringVar()
        self.sv_bone_filter.trace_add('write', lambda *_: self._bones_refresh())
        ttk.Entry(sr, textvariable=self.sv_bone_filter).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(sr, text="✕", width=3,
                   command=lambda: self.sv_bone_filter.set('')).pack(side=tk.LEFT, padx=2)

        tvf = ttk.Frame(f)
        tvf.grid(row=3, column=0, sticky='nsew', padx=4)
        tvf.rowconfigure(0, weight=1); tvf.columnconfigure(0, weight=1)

        self.bones_tv = ttk.Treeview(tvf, columns=('bone', 'custom', 'groups'),
                                      show='headings', selectmode='extended', height=16)
        for col, txt, w in [('bone','Bone Name',170), ('custom','Custom HP Name',135), ('groups','Group Assignments',180)]:
            self.bones_tv.heading(col, text=txt, command=lambda c=col: self._bones_sort(c))
            self.bones_tv.column(col, width=w, minwidth=60)

        self.bones_tv.tag_configure('unassigned', foreground=P['sub0'])
        self.bones_tv.tag_configure('assigned',   foreground=P['text'])
        self.bones_tv.tag_configure('multi',      foreground=P['peach'])

        vsb = ttk.Scrollbar(tvf, orient='vertical',   command=self.bones_tv.yview)
        hsb = ttk.Scrollbar(tvf, orient='horizontal', command=self.bones_tv.xview)
        self.bones_tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.bones_tv.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        self.bones_tv.bind('<Double-1>',  lambda _: self._bones_edit())
        self.bones_tv.bind('<Delete>',    lambda _: self._bones_delete())
        self.bones_tv.bind('<Button-3>',  self._bones_ctx_menu)
        _setup_tv_autofit(self.bones_tv, {'bone': 170, 'custom': 135, 'groups': 180})

        br = WrapFrame(f, padx=2, pady=2)
        br.grid(row=4, column=0, sticky='ew', padx=4, pady=2)
        br.add(ttk.Button(br, text="+ Bone",       command=self._bones_add     ))
        br.add(ttk.Button(br, text="+ Sequence",   command=self._bones_sequence))
        br.add(ttk.Button(br, text="📥 From ALO…", command=self._bones_from_alo,
                           style='Mauve.TButton'))
        br.add(ttk.Button(br, text="✎ Edit",       command=self._bones_edit    ))
        br.add(ttk.Button(br, text="✕ Delete",     command=self._bones_delete,
                           style='Danger.TButton'))
        br.add(ttk.Button(br, text="Select All",   command=lambda: self.bones_tv.selection_set(
                                                        self.bones_tv.get_children())))
        br.add_sep()
        br.add(ttk.Button(br, text="▶ Assign Selected to Group",
                   style='Accent.TButton',
                   command=self._bones_assign_to_group))
        #br.add(ttk.Button(br, text="🔀 Bulk Assign…",
        #           command=self._bones_bulk_assign))

        return f

    # ── Groups Panel ─────────────────────────────

    def _build_groups_panel(self, parent) -> ttk.Frame:
        vp = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        vp.pack(fill=tk.BOTH, expand=True)
        vp.add(self._build_groups_list(vp),  weight=1)
        vp.add(self._build_group_editor(vp), weight=2)
        self._groups_pane = vp   # saved for deferred sash positioning
        return vp

    def _build_groups_list(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)   # treeview row expands; button row always visible

        hdr = ttk.Frame(f)
        hdr.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))
        ttk.Label(hdr, text="GROUPS", style='Header.TLabel').pack(side=tk.LEFT)
        self.sv_group_count = tk.StringVar(value="0 groups")
        ttk.Label(hdr, textvariable=self.sv_group_count, style='Small.TLabel').pack(side=tk.LEFT, padx=8)

        tvf = ttk.Frame(f)
        tvf.grid(row=1, column=0, sticky='nsew', padx=4)
        tvf.rowconfigure(0, weight=1); tvf.columnconfigure(0, weight=1)

        cols = ('#', 'label', 'template', 'bones', 'components', 'overrides')
        self.groups_tv = ttk.Treeview(tvf, columns=cols, show='headings',
                                       selectmode='browse', height=8)
        spec = [('#', 28, '#', 28), ('label', 170, 'Comment / Prefix', 80),
                ('template', 150, 'Template', 70), ('bones', 42, 'Bones', 32),
                ('components', 155, 'Components', 55), ('overrides', 130, 'Field Overrides', 55)]
        for col, w, txt, mw in spec:
            self.groups_tv.heading(col, text=txt)
            self.groups_tv.column(col, width=w, minwidth=mw)

        vsb = ttk.Scrollbar(tvf, orient='vertical', command=self.groups_tv.yview)
        self.groups_tv.configure(yscrollcommand=vsb.set)
        self.groups_tv.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        self.groups_tv.bind('<<TreeviewSelect>>', self._on_group_select)
        self.groups_tv.bind('<Double-1>',         lambda _: self._on_group_select())
        self.groups_tv.bind('<Motion>',           self._groups_tv_tooltip)
        self.groups_tv.bind('<Leave>',            lambda e: self._groups_hide_tooltip())
        self._groups_tooltip_win  = None
        self._groups_tooltip_last = None
        _setup_tv_autofit(self.groups_tv,
                          {'#': 28, 'label': 170, 'template': 150,
                           'bones': 42, 'components': 155, 'overrides': 130})

        br = WrapFrame(f, padx=2, pady=2)
        br.grid(row=2, column=0, sticky='ew', padx=4, pady=4)
        br.add(ttk.Button(br, text="+ Group",     command=self._groups_add      ))
        br.add(ttk.Button(br, text="⧉ Duplicate", command=self._groups_duplicate))
        br.add(ttk.Button(br, text="✕ Delete",    command=self._groups_delete,   style='Danger.TButton'))
        br.add_sep()
        br.add(ttk.Button(br, text="↑ Up",        command=self._groups_move_up  ))
        br.add(ttk.Button(br, text="↓ Down",      command=self._groups_move_down))

        return f

    def _build_group_editor(self, parent) -> ttk.Frame:
        outer = ttk.Frame(parent)

        hdr = ttk.Frame(outer)
        hdr.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(hdr, text="GROUP EDITOR", style='Header.TLabel').pack(side=tk.LEFT)
        self.sv_ge_label = tk.StringVar(value="(no group selected)")
        ttk.Label(hdr, textvariable=self.sv_ge_label, style='Small.TLabel').pack(side=tk.LEFT, padx=8)
        # Auto-saved — no manual Save/Reload buttons needed
        ttk.Label(hdr, text="● auto-saved", style='Small.TLabel',
                  foreground=P['green']).pack(side=tk.RIGHT, padx=8)

        body = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._group_editor_pane = body   # saved for deferred sash positioning

        # ── Left: settings ───────────────────────
        lf = ttk.LabelFrame(body, text=" Group Settings ")
        lf.columnconfigure(1, weight=1)
        body.add(lf, weight=1)

        self.ge = {k: tk.StringVar() for k in
                   ('comment', 'prefix', 'template', 'start', 'fmt', 'health_override')}

        rows = [
            ("Group Comment:", 'comment',    None),
            ("Name Prefix:",   'prefix',     None),
            ("Template:",      'template',   'combo'),
            ("Start Index:",   'start',      'spin'),
            ("Index Format:",  'fmt',        None),
        ]

        # Build rows with hints placed BELOW each input (2 grid rows per field row).
        # Input widgets occupy even grid rows; hints occupy the odd rows beneath them.
        hints = [
            "e.g. MyShip, Turbolaser — appears as XML comment",
            "e.g. HP_MyShip_Turbolaser_L — prefix for auto-numbered HP names",
            "",  # template row — hint shown via model-warn label
            "First number in the sequence  (1 → HP_…_01)",
            'Python format spec — "02d" → 01, 02, 03 …',
        ]

        for field_idx, (label, key, kind) in enumerate(rows):
            input_row = field_idx * 2       # even rows hold labels + widgets
            hint_row  = field_idx * 2 + 1  # odd rows hold the hint text

            ttk.Label(lf, text=label).grid(row=input_row, column=0, sticky='w', padx=8, pady=(4, 0))

            if kind == 'combo':
                self._ge_tpl_combo = SearchableCombobox(lf, textvariable=self.ge['template'],
                                                         values=[], width=32)
                self._ge_tpl_combo.grid(row=input_row, column=1, sticky='ew', padx=8, pady=(4, 0))
                self._ge_tpl_combo.bind_selected(self._ge_on_template_changed)

                # Preview button next to combo
                self._ge_tpl_preview_btn = ttk.Button(lf, text="👁", width=3,
                                                       command=self._ge_preview_template)
                self._ge_tpl_preview_btn.grid(row=input_row, column=2, padx=(0, 4), pady=(4, 0))

            elif kind == 'spin':
                ttk.Spinbox(lf, textvariable=self.ge[key], from_=1, to=9999, width=8
                            ).grid(row=input_row, column=1, sticky='w', padx=8, pady=(4, 0))
            else:
                ttk.Entry(lf, textvariable=self.ge[key]
                          ).grid(row=input_row, column=1, sticky='ew', padx=8, pady=(4, 0))

            # Hint label sits in the row immediately below the input widget
            hint = hints[field_idx]
            if hint:
                ttk.Label(lf, text=hint, style='Small.TLabel'
                          ).grid(row=hint_row, column=1, columnspan=2,
                                 sticky='w', padx=(8, 4), pady=(0, 2))

        # Offset all subsequent rows past the doubled field rows
        _after_fields = len(rows) * 2

        # ── Health Override ──────────────────────────────────────────────
        ttk.Label(lf, text="Health Override:").grid(
            row=_after_fields, column=0, sticky='w', padx=8, pady=(6, 0))
        ttk.Entry(lf, textvariable=self.ge['health_override']).grid(
            row=_after_fields, column=1, columnspan=2, sticky='ew', padx=8, pady=(6, 0))
        ttk.Label(lf,
                  text="Overrides the <Health> field value.\nLeave blank to use template default.",
                  style='Small.TLabel').grid(
            row=_after_fields + 1, column=1, columnspan=2,
            sticky='w', padx=(8, 4), pady=(0, 2))
        _after_fields += 2

        self.sv_ge_model_warn = tk.StringVar(value="")
        ttk.Label(lf, textvariable=self.sv_ge_model_warn,
                  style='Warn.TLabel').grid(row=_after_fields, column=0, columnspan=3,
                                             sticky='w', padx=8, pady=4)

        # HP name preview
        ttk.Separator(lf, orient='h').grid(row=_after_fields+1, column=0, columnspan=3,
                                            sticky='ew', padx=8, pady=4)
        ttk.Label(lf, text="Name Preview:", font=('Segoe UI', 8, 'bold')
                  ).grid(row=_after_fields+2, column=0, sticky='w', padx=8)
        self.sv_ge_name_preview = tk.StringVar(value="—")
        ttk.Label(lf, textvariable=self.sv_ge_name_preview, foreground=P['teal'],
                  font=('Consolas', 8), wraplength=280, justify='left'
                  ).grid(row=_after_fields+2, column=1, columnspan=2, sticky='w', padx=8)

        for key in ('prefix', 'start', 'fmt'):
            self.ge[key].trace_add('write', lambda *_: self._ge_update_name_preview())

        # Auto-save: any change to group settings fields is immediately
        # written to config (guarded by self._loading to avoid feedback
        # during _ge_load).
        for _sv in self.ge.values():
            _sv.trace_add('write', lambda *_: self._ge_autosave())

        # ── Right side: Notebook with Bones / Components / Field Overrides tabs ──
        right_nb = ttk.Notebook(body)
        body.add(right_nb, weight=2)
        self._ge_right_nb = right_nb

        # ════════════════════════════════════════
        # TAB 1 — Assigned Bones
        # ════════════════════════════════════════
        rf = ttk.Frame(right_nb)
        right_nb.add(rf, text="  Bones  ")
        rf.rowconfigure(0, weight=1)
        rf.columnconfigure(0, weight=1)

        btvf = ttk.Frame(rf)
        btvf.grid(row=0, column=0, columnspan=2, sticky='nsew', padx=4, pady=(4, 0))
        btvf.rowconfigure(0, weight=1); btvf.columnconfigure(0, weight=1)

        self.ge_bones_tv = ttk.Treeview(btvf,
                                          columns=('idx','bone_a','bone_b','bone_c','bone_d','bone_e','bone_f','custom','hp_name'),
                                          show='headings', selectmode='extended', height=10)
        for col, txt, w in [('idx','#',28), ('bone_a','Bone A',110),
                              ('bone_b','Bone B',90), ('bone_c','Bone C (ATT)',90),
                              ('bone_d','Bone D (COL)',90), ('bone_e','Bone E (DMG)',90),
                              ('bone_f','Bone F (DCL)',90),
                              ('custom','Custom HP Name',100),
                              ('hp_name','Generated HP Name',150)]:
            self.ge_bones_tv.heading(col, text=txt)
            self.ge_bones_tv.column(col, width=w, minwidth=28)

        self.ge_bones_tv.tag_configure('dual',   foreground=P['teal'])
        self.ge_bones_tv.tag_configure('single', foreground=P['text'])

        gb_vsb = ttk.Scrollbar(btvf, orient='vertical',   command=self.ge_bones_tv.yview)
        gb_hsb = ttk.Scrollbar(btvf, orient='horizontal', command=self.ge_bones_tv.xview)
        self.ge_bones_tv.configure(yscrollcommand=gb_vsb.set, xscrollcommand=gb_hsb.set)
        self.ge_bones_tv.grid(row=0, column=0, sticky='nsew')
        gb_vsb.grid(row=0, column=1, sticky='ns')
        gb_hsb.grid(row=1, column=0, sticky='ew')

        gbr_outer = ttk.Frame(rf)
        gbr_outer.grid(row=2, column=0, columnspan=2, sticky='ew', padx=4, pady=(2, 4))
        self.sv_ge_bone_count = tk.StringVar(value="0 bones")
        ttk.Label(gbr_outer, textvariable=self.sv_ge_bone_count,
                  style='Small.TLabel').pack(side=tk.RIGHT, padx=8)
        gbr = WrapFrame(gbr_outer, padx=2, pady=2)
        gbr.pack(side=tk.LEFT, fill=tk.X, expand=True)
        gbr.add(ttk.Button(gbr, text="+ From Pool", command=self._ge_add_from_pool))
        gbr.add(ttk.Button(gbr, text="✕ Remove",    command=self._ge_remove_bone,  style='Danger.TButton'))
        gbr.add(ttk.Button(gbr, text="↑",           command=self._ge_bone_up,   width=3))
        gbr.add(ttk.Button(gbr, text="↓",           command=self._ge_bone_down, width=3))
        gbr.add(ttk.Button(gbr, text="✎ Edit",      command=self._ge_edit_bone))

        self.ge_bones_tv.bind('<Delete>',   lambda _: self._ge_remove_bone())
        self.ge_bones_tv.bind('<Double-1>', lambda _: self._ge_edit_bone())
        _setup_tv_autofit(self.ge_bones_tv,
                          {'idx': 28, 'bone_a': 110, 'bone_b': 90, 'bone_c': 90,
                           'bone_d': 90, 'bone_e': 90, 'bone_f': 90, 'custom': 100, 'hp_name': 150})

        # ════════════════════════════════════════
        # TAB 2 — Components
        # ════════════════════════════════════════
        cf = ttk.Frame(right_nb)
        right_nb.add(cf, text="  Components  ")
        cf.rowconfigure(1, weight=1)
        cf.columnconfigure(0, weight=1)

        cpick = ttk.Frame(cf)
        cpick.columnconfigure(0, weight=1)
        cpick.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))
        self._ge_comp_combo = SearchableCombobox(cpick,
                                                  values=sorted(self.component_registry.keys()),
                                                  width=24)
        self._ge_comp_combo.grid(row=0, column=0, sticky='ew')
        ttk.Button(cpick, text="＋ Add", style='Accent.TButton',
                   command=self._ge_add_component).grid(row=0, column=1, padx=(4, 0))

        ctvf = ttk.Frame(cf)
        ctvf.rowconfigure(0, weight=1); ctvf.columnconfigure(0, weight=1)
        ctvf.grid(row=1, column=0, sticky='nsew', padx=4, pady=(0, 2))

        self.ge_comp_tv = ttk.Treeview(ctvf, columns=('idx', 'name'),
                                        show='headings', selectmode='extended', height=10)
        self.ge_comp_tv.heading('idx',  text='#')
        self.ge_comp_tv.heading('name', text='Component Name')
        self.ge_comp_tv.column('idx',  width=30, minwidth=24)
        self.ge_comp_tv.column('name', width=200, minwidth=80)
        self.ge_comp_tv.tag_configure('comp', foreground=P['mauve'])

        cvsb = ttk.Scrollbar(ctvf, orient='vertical', command=self.ge_comp_tv.yview)
        self.ge_comp_tv.configure(yscrollcommand=cvsb.set)
        self.ge_comp_tv.grid(row=0, column=0, sticky='nsew')
        cvsb.grid(row=0, column=1, sticky='ns')

        self.ge_comp_tv.bind('<Delete>', lambda _: self._ge_remove_component())
        _setup_tv_autofit(self.ge_comp_tv, {'idx': 30, 'name': 200})

        warn_row = ttk.Frame(cf)
        warn_row.grid(row=2, column=0, sticky='ew', padx=4, pady=(0, 2))
        self.sv_ge_comp_warn = tk.StringVar(value="")
        ttk.Label(warn_row, textvariable=self.sv_ge_comp_warn, style='Warn.TLabel').pack(side=tk.LEFT)
        self._ge_comp_conflict_details: str = ""
        self._ge_comp_details_btn = ttk.Button(warn_row, text="Details...",
                                                command=self._ge_show_comp_conflicts,
                                                style='Warn.TButton')

        cbr_outer = ttk.Frame(cf)
        cbr_outer.grid(row=3, column=0, sticky='ew', padx=4, pady=(0, 4))
        self.sv_ge_comp_count = tk.StringVar(value="0 components")
        ttk.Label(cbr_outer, textvariable=self.sv_ge_comp_count,
                  style='Small.TLabel').pack(side=tk.RIGHT, padx=8)
        cbr = WrapFrame(cbr_outer, padx=2, pady=2)
        cbr.pack(side=tk.LEFT, fill=tk.X, expand=True)
        cbr.add(ttk.Button(cbr, text="✕ Remove", command=self._ge_remove_component, style='Danger.TButton'))
        cbr.add(ttk.Button(cbr, text="↑", command=self._ge_comp_up,   width=3))
        cbr.add(ttk.Button(cbr, text="↓", command=self._ge_comp_down, width=3))
        cbr.add(ttk.Button(cbr, text="👁", command=self._ge_preview_component, width=3))

        # ════════════════════════════════════════
        # TAB 3 — Field Overrides
        # ════════════════════════════════════════
        ovf = ttk.Frame(right_nb)
        right_nb.add(ovf, text="  Field Overrides  ")
        ovf.rowconfigure(1, weight=1)
        ovf.columnconfigure(0, weight=1)

        # Header with description and "Load from Template" button
        ov_hdr = ttk.Frame(ovf)
        ov_hdr.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))
        ttk.Label(ov_hdr,
                  text="Override or extend template fields for this group only. Highest priority — applied after template + components.",
                  style='Small.TLabel', wraplength=600, justify='left').pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.sv_ge_ov_count = tk.StringVar(value="0 overrides")
        ttk.Label(ov_hdr, textvariable=self.sv_ge_ov_count,
                  style='Small.TLabel', foreground=P['peach']).pack(side=tk.RIGHT, padx=6)

        # Fields treeview
        ov_tvf = ttk.Frame(ovf)
        ov_tvf.grid(row=1, column=0, sticky='nsew', padx=4, pady=(0, 2))
        ov_tvf.rowconfigure(0, weight=1); ov_tvf.columnconfigure(0, weight=1)

        self.ge_ov_tv = ttk.Treeview(ov_tvf,
                                      columns=('idx', 'type', 'tag', 'value', 'flags'),
                                      show='headings', selectmode='extended', height=8)
        for col, txt, w in [('idx', '#', 30), ('type', 'Type', 90),
                              ('tag', 'Tag / Text', 180), ('value', 'Value', 270),
                              ('flags', 'Flags', 70)]:
            self.ge_ov_tv.heading(col, text=txt)
            self.ge_ov_tv.column(col, width=w, minwidth=28)

        self.ge_ov_tv.tag_configure('element',         foreground=P['text'])
        self.ge_ov_tv.tag_configure('section_comment', foreground=P['ov0'])
        self.ge_ov_tv.tag_configure('inline_comment',  foreground=P['ov0'])
        self.ge_ov_tv.tag_configure('blank',           foreground=P['s2'])
        self.ge_ov_tv.tag_configure('bone_ref',        foreground=P['teal'])
        self.ge_ov_tv.tag_configure('model_ref',       foreground=P['peach'])

        ov_vsb = ttk.Scrollbar(ov_tvf, orient='vertical',   command=self.ge_ov_tv.yview)
        ov_hsb = ttk.Scrollbar(ov_tvf, orient='horizontal', command=self.ge_ov_tv.xview)
        self.ge_ov_tv.configure(yscrollcommand=ov_vsb.set, xscrollcommand=ov_hsb.set)
        self.ge_ov_tv.grid(row=0, column=0, sticky='nsew')
        ov_vsb.grid(row=0, column=1, sticky='ns')
        ov_hsb.grid(row=1, column=0, sticky='ew')

        self.ge_ov_tv.bind('<<TreeviewSelect>>', self._ge_ov_on_select)
        self.ge_ov_tv.bind('<Double-1>',         self._ge_ov_double_click)
        self.ge_ov_tv.bind('<Delete>',           lambda _: self._ge_ov_del())
        self.ge_ov_tv.bind('<Control-Up>',       lambda e: (self._ge_ov_up(), 'break')[1])
        self.ge_ov_tv.bind('<Control-Down>',     lambda e: (self._ge_ov_down(), 'break')[1])
        self.ge_ov_tv.bind('<Control-d>',        lambda e: (self._ge_ov_dup(), 'break')[1])
        self.ge_ov_tv.bind('<F2>',               lambda e: (self._ge_ov_inline_edit('#3'), 'break')[1])
        _setup_tv_autofit(self.ge_ov_tv,
                          {'idx': 30, 'type': 90, 'tag': 180, 'value': 270, 'flags': 70})

        # Toolbar row: Add buttons + Load from Template
        ov_tbr = WrapFrame(ovf, padx=2, pady=2)
        ov_tbr.grid(row=2, column=0, sticky='ew', padx=4, pady=(0, 2))
        ov_tbr.add(ttk.Label(ov_tbr, text="Add:", style='Small.TLabel', background=P['bg']))
        ov_tbr.add(ttk.Button(ov_tbr, text="Element",         command=self._ge_ov_add_element))
        ov_tbr.add(ttk.Button(ov_tbr, text="Section Comment", command=self._ge_ov_add_section_comment))
        ov_tbr.add(ttk.Button(ov_tbr, text="Inline Comment",  command=self._ge_ov_add_inline_comment))
        ov_tbr.add(ttk.Button(ov_tbr, text="Blank Line",      command=self._ge_ov_add_blank))
        ov_tbr.add_sep()
        ov_tbr.add(ttk.Button(ov_tbr, text="✎ Edit",    command=self._ge_ov_edit))
        ov_tbr.add(ttk.Button(ov_tbr, text="✕ Delete",  command=self._ge_ov_del, style='Danger.TButton'))
        ov_tbr.add(ttk.Button(ov_tbr, text="↑ Up",      command=self._ge_ov_up))
        ov_tbr.add(ttk.Button(ov_tbr, text="↓ Down",    command=self._ge_ov_down))
        ov_tbr.add(ttk.Button(ov_tbr, text="⧉ Dup",     command=self._ge_ov_dup))
        ov_tbr.add_sep()
        ov_tbr.add(ttk.Button(ov_tbr, text="📋 Load from Template",
                               command=self._ge_ov_load_from_template, style='Mauve.TButton'))
        ov_tbr.add(ttk.Button(ov_tbr, text="🗑 Clear All",
                               command=self._ge_ov_clear_all, style='Danger.TButton'))

        # Inline field editor
        ov_ed = ttk.LabelFrame(ovf, text=" Field Editor ")
        ov_ed.grid(row=3, column=0, sticky='ew', padx=4, pady=(0, 2))
        ov_ed.columnconfigure(1, weight=1, minsize=110)
        ov_ed.columnconfigure(3, weight=3)
        ov_ed.columnconfigure(5, weight=3)

        self.ge_ov_ed = {}
        _ov_ed_layout = [
            (0, 0, "Type:",       'ftype',     'combo', ['element','section_comment','inline_comment','blank']),
            (0, 2, "Tag:",        'tag',       'entry', None),
            (0, 4, "Value:",      'value',     'entry', None),
            (1, 2, "Empty tag:",  'empty_tag', 'check', None),
        ]
        for row, col, lbl, key, kind, opts in _ov_ed_layout:
            ttk.Label(ov_ed, text=lbl).grid(row=row, column=col,
                                             sticky='w', padx=(8 if col==0 else 4, 2), pady=3)
            if kind == 'combo':
                sv = tk.StringVar(value='element')
                cb = ttk.Combobox(ov_ed, textvariable=sv, values=opts, state='readonly', width=12)
                cb.grid(row=row, column=col+1, sticky='ew', padx=(2, 4), pady=3)
                cb.bind('<<ComboboxSelected>>', lambda _e: None)
                self.ge_ov_ed[key] = sv
                self._ge_ov_ftype_cb = cb
            elif kind == 'entry':
                sv = tk.StringVar()
                ttk.Entry(ov_ed, textvariable=sv).grid(
                    row=row, column=col+1, sticky='ew', padx=(2, 4), pady=3)
                self.ge_ov_ed[key] = sv
            elif kind == 'check':
                sv = tk.BooleanVar()
                ttk.Checkbutton(ov_ed, text="(produces <Tag/>)", variable=sv).grid(
                    row=row, column=col+1, columnspan=3, sticky='w', padx=(2, 4), pady=3)
                self.ge_ov_ed[key] = sv

        # Auto-apply field editor changes to selected row
        self._ge_ov_field_applying = False
        def _ov_auto_apply(*_):
            if self._loading or self._ge_ov_field_applying:
                return
            if not self.ge_ov_tv.selection():
                return
            self._ge_ov_field_applying = True
            try:
                self._ge_ov_apply_field(silent=True)
            finally:
                self._ge_ov_field_applying = False
        for sv in self.ge_ov_ed.values():
            if isinstance(sv, (tk.StringVar, tk.BooleanVar)):
                sv.trace_add('write', _ov_auto_apply)

        ov_ed_btn = ttk.Frame(ovf)
        ov_ed_btn.grid(row=4, column=0, sticky='ew', padx=4, pady=(0, 4))
        ttk.Button(ov_ed_btn, text="+ Insert Below", command=self._ge_ov_insert_below).pack(side=tk.LEFT, padx=2)
        ttk.Label(ov_ed_btn,
                  text="Double-click Tag/Value to edit inline · F2 tag · Ctrl+↑↓ move · Ctrl+D dup",
                  style='Small.TLabel').pack(side=tk.LEFT, padx=8)

        # Internal field store for override TV (iid -> field dict)
        self._ge_ov_field_store: dict = {}
        self._ge_ov_inline_entry = None

        return outer

    # ── Template Browser Tab ─────────────────────

    def _build_template_browser(self, parent):
        hp = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        hp.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        lf = ttk.Frame(hp)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(2, weight=1)   # treeview row expands; button row always visible
        hp.add(lf, weight=1)

        hdr = ttk.Frame(lf)
        hdr.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))
        ttk.Label(hdr, text="TEMPLATES", style='Header.TLabel').pack(side=tk.LEFT)
        self.sv_tpl_count = tk.StringVar(value="0 templates")
        ttk.Label(hdr, textvariable=self.sv_tpl_count, style='Small.TLabel').pack(side=tk.LEFT, padx=8)

        sr = ttk.Frame(lf)
        sr.grid(row=1, column=0, sticky='ew', padx=4, pady=(0, 2))
        ttk.Label(sr, text="Filter:").pack(side=tk.LEFT)
        self.sv_tpl_filter = tk.StringVar()
        self.sv_tpl_filter.trace_add('write', lambda *_: self._tpl_browser_refresh())
        ttk.Entry(sr, textvariable=self.sv_tpl_filter).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(sr, text="✕", width=3,
                   command=lambda: self.sv_tpl_filter.set('')).pack(side=tk.LEFT)

        tvf = ttk.Frame(lf)
        tvf.grid(row=2, column=0, sticky='nsew', padx=4)
        tvf.rowconfigure(0, weight=1); tvf.columnconfigure(0, weight=1)

        self.tpl_tv = ttk.Treeview(tvf, columns=('name', 'inherits', 'fields'),
                                    show='headings', selectmode='browse')
        for col, txt, w in [('name','Template Name',220), ('inherits','Inherits From',175), ('fields','Fields',55)]:
            self.tpl_tv.heading(col, text=txt, command=lambda c=col: self._tpl_sort(c))
            self.tpl_tv.column(col, width=w, minwidth=50)

        self.tpl_tv.tag_configure('base',  foreground=P['blue'])
        self.tpl_tv.tag_configure('child', foreground=P['text'])

        tvsb = ttk.Scrollbar(tvf, orient='vertical', command=self.tpl_tv.yview)
        self.tpl_tv.configure(yscrollcommand=tvsb.set)
        self.tpl_tv.grid(row=0, column=0, sticky='nsew')
        tvsb.grid(row=0, column=1, sticky='ns')
        self.tpl_tv.bind('<<TreeviewSelect>>', self._on_tpl_selected)
        _setup_tv_autofit(self.tpl_tv, {'name': 220, 'inherits': 175, 'fields': 55})

        tbr = WrapFrame(lf, padx=2, pady=2)
        tbr.grid(row=3, column=0, sticky='ew', padx=4, pady=4)
        tbr.add(ttk.Button(tbr, text="↺ Reload",  command=self._templates_reload))
        #tbr.add(ttk.Button(tbr, text="🔍 Dump",   command=self._do_dump         ))
        tbr.add(ttk.Button(tbr, text="✏ Edit Template File…",
                   command=self._browser_open_in_editor,
                   style='Mauve.TButton'))

        # Right detail pane
        rf = ttk.Frame(hp)
        hp.add(rf, weight=2)

        dhdr = ttk.Frame(rf)
        dhdr.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(dhdr, text="TEMPLATE DETAIL", style='Header.TLabel').pack(side=tk.LEFT)
        self.sv_tpl_resolved = tk.BooleanVar(value=True)
        ttk.Checkbutton(dhdr, text="Show resolved (with inherited) fields",
                        variable=self.sv_tpl_resolved,
                        command=self._on_tpl_selected).pack(side=tk.LEFT, padx=12)

        # Meta info grid
        info = ttk.Frame(rf)
        info.pack(fill=tk.X, padx=4, pady=(0, 4))
        info.columnconfigure(1, weight=1)

        self.sv_td = {k: tk.StringVar(value="—") for k in
                      ('name', 'inherits', 'pc', 'chain', 'fields_own', 'fields_total')}
        meta_rows = [
            ("Name:",               'name',         P['blue']),
            ("Inherits from:",      'inherits',      P['text']),
            ("Parent comment:",     'pc',            P['text']),
            ("Inheritance chain:",  'chain',         P['mauve']),
            ("Own fields / Total:", 'fields_own',    P['sub0']),
        ]
        for r, (lbl, key, fg) in enumerate(meta_rows):
            ttk.Label(info, text=lbl).grid(row=r, column=0, sticky='w', padx=8, pady=2)
            ttk.Label(info, textvariable=self.sv_td[key],
                      foreground=fg).grid(row=r, column=1, sticky='w', padx=8, pady=2)

        ttk.Separator(rf, orient='h').pack(fill=tk.X, padx=4, pady=4)

        # Fields table
        ff = ttk.Frame(rf)
        ff.pack(fill=tk.BOTH, expand=True, padx=4)
        ff.rowconfigure(0, weight=1); ff.columnconfigure(0, weight=1)

        fcols = ('source', 'type', 'tag', 'value', 'note')
        self.fields_tv = ttk.Treeview(ff, columns=fcols, show='headings')
        for col, txt, w in [('source','Source',70), ('type','Type',70), ('tag','Tag',200),
                              ('value','Value',220), ('note','Note',110)]:
            self.fields_tv.heading(col, text=txt)
            self.fields_tv.column(col, width=w, minwidth=50)

        self.fields_tv.tag_configure('comment',   foreground=P['ov0'])
        self.fields_tv.tag_configure('blank',     foreground=P['s2'])
        self.fields_tv.tag_configure('bone_ref',  foreground=P['teal'])
        self.fields_tv.tag_configure('model_ref', foreground=P['peach'])
        self.fields_tv.tag_configure('normal',    foreground=P['text'])
        self.fields_tv.tag_configure('inherited', foreground=P['sub0'])

        fvsb = ttk.Scrollbar(ff, orient='vertical',   command=self.fields_tv.yview)
        fhsb = ttk.Scrollbar(ff, orient='horizontal', command=self.fields_tv.xview)
        self.fields_tv.configure(yscrollcommand=fvsb.set, xscrollcommand=fhsb.set)
        self.fields_tv.grid(row=0, column=0, sticky='nsew')
        fvsb.grid(row=0, column=1, sticky='ns')
        fhsb.grid(row=1, column=0, sticky='ew')
        _setup_tv_autofit(self.fields_tv,
                          {'source': 70, 'type': 70, 'tag': 200, 'value': 220, 'note': 110})

        self._template_browser_pane = hp   # saved for deferred sash positioning

    # ── Component Browser Tab ────────────────────

    def _build_component_browser(self, parent):
        hp = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        hp.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        lf = ttk.Frame(hp)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(2, weight=1)   # treeview row expands; button row always visible
        hp.add(lf, weight=1)

        hdr = ttk.Frame(lf)
        hdr.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))
        ttk.Label(hdr, text="COMPONENTS", style='Header.TLabel').pack(side=tk.LEFT)
        self.sv_comp_browser_count = tk.StringVar(value="0 components")
        ttk.Label(hdr, textvariable=self.sv_comp_browser_count,
                  style='Small.TLabel').pack(side=tk.LEFT, padx=8)

        sr = ttk.Frame(lf)
        sr.grid(row=1, column=0, sticky='ew', padx=4, pady=(0, 2))
        ttk.Label(sr, text="Filter:").pack(side=tk.LEFT)
        self.sv_comp_filter = tk.StringVar()
        self.sv_comp_filter.trace_add('write', lambda *_: self._comp_browser_refresh())
        ttk.Entry(sr, textvariable=self.sv_comp_filter).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(sr, text="✕", width=3,
                   command=lambda: self.sv_comp_filter.set('')).pack(side=tk.LEFT)

        tvf = ttk.Frame(lf)
        tvf.grid(row=2, column=0, sticky='nsew', padx=4)
        tvf.rowconfigure(0, weight=1); tvf.columnconfigure(0, weight=1)

        self.comp_tv = ttk.Treeview(tvf, columns=('name', 'inherits', 'fields'),
                                     show='headings', selectmode='browse')
        for col, txt, w in [('name', 'Component Name', 220),
                              ('inherits', 'Inherits From', 175),
                              ('fields', 'Fields', 55)]:
            self.comp_tv.heading(col, text=txt, command=lambda c=col: self._comp_sort(c))
            self.comp_tv.column(col, width=w, minwidth=50)

        self.comp_tv.tag_configure('base',  foreground=P['blue'])
        self.comp_tv.tag_configure('child', foreground=P['text'])

        cvsb = ttk.Scrollbar(tvf, orient='vertical', command=self.comp_tv.yview)
        self.comp_tv.configure(yscrollcommand=cvsb.set)
        self.comp_tv.grid(row=0, column=0, sticky='nsew')
        cvsb.grid(row=0, column=1, sticky='ns')
        self.comp_tv.bind('<<TreeviewSelect>>', self._on_comp_selected)
        _setup_tv_autofit(self.comp_tv, {'name': 220, 'inherits': 175, 'fields': 55})

        cbr = WrapFrame(lf, padx=2, pady=2)
        cbr.grid(row=3, column=0, sticky='ew', padx=4, pady=4)
        cbr.add(ttk.Button(cbr, text="↺ Reload", command=self._components_reload))
        cbr.add(ttk.Button(cbr, text="✏ Edit Component File…",
                   command=self._comp_browser_open_in_editor,
                   style='Mauve.TButton'))

        # ── Right detail pane ─────────────────────────────────────────────
        rf = ttk.Frame(hp)
        hp.add(rf, weight=2)

        dhdr = ttk.Frame(rf)
        dhdr.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(dhdr, text="COMPONENT DETAIL", style='Header.TLabel').pack(side=tk.LEFT)
        self.sv_comp_resolved = tk.BooleanVar(value=True)
        ttk.Checkbutton(dhdr, text="Show resolved (with inherited) fields",
                        variable=self.sv_comp_resolved,
                        command=self._on_comp_selected).pack(side=tk.LEFT, padx=12)

        # Meta info grid
        info = ttk.Frame(rf)
        info.pack(fill=tk.X, padx=4, pady=(0, 4))
        info.columnconfigure(1, weight=1)

        self.sv_cd = {k: tk.StringVar(value="—") for k in
                      ('name', 'inherits', 'pc', 'chain', 'fields_own')}
        meta_rows = [
            ("Name:",               'name',        P['blue']),
            ("Inherits from:",      'inherits',    P['text']),
            ("Parent comment:",     'pc',          P['text']),
            ("Inheritance chain:",  'chain',       P['mauve']),
            ("Own fields / Total:", 'fields_own',  P['sub0']),
        ]
        for r, (lbl, key, fg) in enumerate(meta_rows):
            ttk.Label(info, text=lbl).grid(row=r, column=0, sticky='w', padx=8, pady=2)
            ttk.Label(info, textvariable=self.sv_cd[key],
                      foreground=fg).grid(row=r, column=1, sticky='w', padx=8, pady=2)

        ttk.Separator(rf, orient='h').pack(fill=tk.X, padx=4, pady=4)

        # Fields table
        ff = ttk.Frame(rf)
        ff.pack(fill=tk.BOTH, expand=True, padx=4)
        ff.rowconfigure(0, weight=1); ff.columnconfigure(0, weight=1)

        fcols = ('source', 'type', 'tag', 'value', 'note')
        self.comp_fields_tv = ttk.Treeview(ff, columns=fcols, show='headings')
        for col, txt, w in [('source', 'Source', 70), ('type', 'Type', 70),
                              ('tag', 'Tag', 200), ('value', 'Value', 220),
                              ('note', 'Note', 110)]:
            self.comp_fields_tv.heading(col, text=txt)
            self.comp_fields_tv.column(col, width=w, minwidth=50)

        self.comp_fields_tv.tag_configure('comment',   foreground=P['ov0'])
        self.comp_fields_tv.tag_configure('blank',     foreground=P['s2'])
        self.comp_fields_tv.tag_configure('bone_ref',  foreground=P['teal'])
        self.comp_fields_tv.tag_configure('model_ref', foreground=P['peach'])
        self.comp_fields_tv.tag_configure('normal',    foreground=P['text'])
        self.comp_fields_tv.tag_configure('inherited', foreground=P['sub0'])

        fvsb = ttk.Scrollbar(ff, orient='vertical',   command=self.comp_fields_tv.yview)
        fhsb = ttk.Scrollbar(ff, orient='horizontal', command=self.comp_fields_tv.xview)
        self.comp_fields_tv.configure(yscrollcommand=fvsb.set, xscrollcommand=fhsb.set)
        self.comp_fields_tv.grid(row=0, column=0, sticky='nsew')
        fvsb.grid(row=0, column=1, sticky='ns')
        fhsb.grid(row=1, column=0, sticky='ew')
        _setup_tv_autofit(self.comp_fields_tv,
                          {'source': 70, 'type': 70, 'tag': 200, 'value': 220, 'note': 110})

        self._comp_browser_pane = hp   # saved for deferred sash positioning

    # ── Log Area ──────────────────────────────────

    def _build_log(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent)

        hdr = ttk.Frame(f)
        hdr.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(hdr, text="OUTPUT LOG", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(hdr, text="Copy All", command=self._log_copy ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(hdr, text="Clear",    command=self._log_clear).pack(side=tk.RIGHT, padx=2)
        self.sv_log_count = tk.StringVar(value="")
        ttk.Label(hdr, textvariable=self.sv_log_count, style='Small.TLabel').pack(side=tk.RIGHT, padx=8)

        inner = ttk.Frame(f)
        inner.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        inner.rowconfigure(0, weight=1); inner.columnconfigure(0, weight=1)

        self.log = tk.Text(inner, height=8, state='disabled',
                           bg=P['crust'], fg=P['text'],
                           font=('Consolas', 9), relief='flat', wrap='word')
        lvsb = ttk.Scrollbar(inner, orient='vertical', command=self.log.yview)
        self.log.configure(yscrollcommand=lvsb.set)
        self.log.grid(row=0, column=0, sticky='nsew')
        lvsb.grid(row=0, column=1, sticky='ns')

        for tag, fg, font_extra in [
            ('info',    P['text'],     None),
            ('success', P['green'],    None),
            ('warn',    P['yellow'],   None),
            ('error',   P['red'],      None),
            ('header',  P['blue'],     ('Consolas', 9, 'bold')),
            ('dim',     P['ov0'],      None),
        ]:
            kw = {'foreground': fg}
            if font_extra:
                kw['font'] = font_extra
            self.log.tag_configure(tag, **kw)

        return f

    # ─────────────────────────────────────────────
    # File Operations
    # ─────────────────────────────────────────────

    def _file_new(self):
        if not self._check_dirty():
            return
        self._new_config()

    def _new_config(self, prompt=True):
        self.config = _make_blank_config()
        # Pre-create one default group so the Group Editor is ready to use immediately
        self.config["groups"] = [{
            "group_comment": "{shipname}, {templatename}",
            "template":      "",   # assigned to first available template after reload
            "name_prefix":   "HP_{shipname}_{templatename}",
            "start_index":   1,
            "index_format":  "02d",
            "bones":         []
        }]
        self.config_path = None
        self.dirty = False
        self._load_cfg_to_ui()
        # After templates load completes, assign first template and select the group
        self.root.after(300, self._init_default_group)
        self._update_title()
        if prompt:
            self._log("New config created.\n", 'info')

    def _init_default_group(self):
        """After startup template load, assign first template to the pre-created group."""
        groups = self.config.get("groups", [])
        if groups and not groups[0].get("template") and self.template_registry:
            first_tpl = sorted(self.template_registry.keys())[0]
            groups[0]["template"] = first_tpl
            self._groups_refresh()
            # Select the default group so the editor is open
        if groups:
            self.groups_tv.selection_set("0")
            self.groups_tv.see("0")
            self._ge_load(0)

    def _file_open(self):
        if not self._check_dirty():
            return
        path = filedialog.askopenfilename(
            title="Open Ship Config",
            initialdir=str(self.config_path.parent) if self.config_path else _script_dir(),
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if path:
            self._open_config(Path(path))

    def _open_config(self, path: Path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            self.config = data
            self.config_path = path
            self.dirty = False
            self._load_cfg_to_ui()
            self._update_title()
            self._log(f"Opened: {path}\n", 'success')
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON Error", f"Invalid JSON in file:\n{e}")
            self._log(f"ERROR opening {path}: JSON error: {e}\n", 'error')
        except Exception as e:
            messagebox.showerror("Open Error", f"Failed to open:\n{e}")
            self._log(f"ERROR opening {path}: {e}\n", 'error')

    def _file_save(self) -> bool:
        if self.config_path is None:
            return self._file_save_as()
        self._save_to(self.config_path)
        return True

    def _file_save_as(self) -> bool:
        initial = str(self.config_path.parent) if self.config_path else _script_dir()
        fname   = self.config_path.name if self.config_path else "ship_config.json"
        path = filedialog.asksaveasfilename(
            title="Save Ship Config",
            initialdir=initial, initialfile=fname,
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if not path:
            return False
        self._save_to(Path(path))
        return True

    def _save_to(self, path: Path):
        self._sync_cfg_from_ui()

        # ── Relativize all file/folder paths before writing ───────────────
        # Re-express every path stored in the config relative to the program
        # root (_script_dir()), NOT relative to where the config file was saved.
        # This is the key to portability: a config in "Ship Configs/" can use
        # simple names like "Templates" or "Hardpoints/Hardpoints_Ship.xml"
        # that work for every user regardless of their install location.
        # Paths outside the program root (e.g. a different drive) are kept
        # absolute but normalised to forward slashes for cross-platform
        # readability when configs are shared between users.
        save_cfg = copy.deepcopy(self.config)
        old_base = self.config_path  # None for a brand-new unsaved file

        def _to_abs(val: str) -> str:
            """Resolve val to an absolute path using _script_dir() as anchor."""
            return resolve_path(old_base, val) if val else val

        def _to_rel(abs_val: str) -> str:
            """Express abs_val relative to the program root (_script_dir()).

            Paths under the program root become short portable names like
            "Templates" or "Ship Configs/myship.json".
            Falls back to an absolute forward-slash path when the target is
            outside the program root (e.g. a different drive).
            """
            if not abs_val:
                return abs_val
            try:
                return Path(abs_val).relative_to(Path(_script_dir())).as_posix()
            except ValueError:
                return Path(abs_val).as_posix()

        for key in ('output_file', 'templates', 'components'):
            v = save_cfg.get(key, '')
            if v:
                save_cfg[key] = _to_rel(_to_abs(v))

        for key in ('template_excludes', 'template_includes',
                    'component_excludes', 'component_includes'):
            save_cfg[key] = [_to_rel(_to_abs(p))
                             for p in save_cfg.get(key, []) if p]

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(save_cfg, fh, indent=2)
            self.config_path = path
            self.dirty = False
            self._update_title()
            self._update_file_info()
            self._update_json_preview()
            self._log(f"Saved: {path}\n", 'success')
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save:\n{e}")
            self._log(f"ERROR saving: {e}\n", 'error')

    def _check_dirty(self) -> bool:
        if not self.dirty:
            return True
        r = messagebox.askyesnocancel("Unsaved Changes",
                                       "You have unsaved changes. Save before continuing?")
        if r is None:
            return False
        if r:
            return self._file_save()
        return True

    def _on_close(self):
        if self._check_dirty():
            self.root.destroy()

    # ── Browse helpers ────────────────────────────

    def _make_rel(self, filepath: str) -> str:
        """Express *filepath* relative to the program root (_script_dir()).

        Returns a forward-slash posix string so configs are readable on any OS.
        Falls back to an absolute path (forward slashes) if the target sits
        outside the program root (e.g. a completely different drive).
        """
        try:
            return Path(filepath).relative_to(Path(_script_dir())).as_posix()
        except ValueError:
            return Path(filepath).as_posix()

    def _browse_output(self):
        # Start in the directory of the current output file value when possible.
        cur = self.sv['output_file'].get().strip()
        if cur:
            abs_p = Path(resolve_path(self.config_path, cur))
            initial      = str(abs_p.parent)
            initial_file = abs_p.name
        elif self.config_path:
            initial      = str(self.config_path.parent)
            initial_file = "Hardpoints_NewShip.xml"
        else:
            initial      = str(Path(_script_dir()) / "Hardpoints")
            initial_file = "Hardpoints_NewShip.xml"

        p = filedialog.asksaveasfilename(
            title="Select Output XML",
            initialdir=initial,
            initialfile=initial_file,
            defaultextension=".xml",
            filetypes=[("XML", "*.xml"), ("All", "*.*")]
        )
        if p:
            self.sv['output_file'].set(self._make_rel(p))

    def _browse_tpl_dir(self):
        # Start inside the current templates path when possible.
        cur = self.sv['templates'].get().strip()
        if cur:
            abs_p = Path(resolve_path(self.config_path, cur))
            initial = str(abs_p) if abs_p.is_dir() else str(abs_p.parent)
        elif self.config_path:
            initial = str(self.config_path.parent)
        else:
            initial = _default_templates()

        p = filedialog.askdirectory(
            title="Select Templates Folder",
            initialdir=initial
        )
        if p:
            self.sv['templates'].set(self._make_rel(p))
            self._templates_reload()

    def _browse_tpl_file(self):
        # Start inside the current templates path when possible.
        cur = self.sv['templates'].get().strip()
        if cur:
            abs_p = Path(resolve_path(self.config_path, cur))
            initial = str(abs_p) if abs_p.is_dir() else str(abs_p.parent)
        elif self.config_path:
            initial = str(self.config_path.parent)
        else:
            initial = _default_templates()

        p = filedialog.askopenfilename(
            title="Select Templates JSON",
            initialdir=initial,
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if p:
            self.sv['templates'].set(self._make_rel(p))
            self._templates_reload()

    def _browse_comp_dir(self):
        cur = self.sv['components'].get().strip()
        if cur:
            abs_p = Path(resolve_path(self.config_path, cur))
            initial = str(abs_p) if abs_p.is_dir() else str(abs_p.parent)
        elif self.config_path:
            initial = str(self.config_path.parent)
        else:
            initial = _default_components()
        p = filedialog.askdirectory(title="Select Components Folder", initialdir=initial)
        if p:
            self.sv['components'].set(self._make_rel(p))
            self._components_reload()

    def _browse_comp_file(self):
        cur = self.sv['components'].get().strip()
        if cur:
            abs_p = Path(resolve_path(self.config_path, cur))
            initial = str(abs_p) if abs_p.is_dir() else str(abs_p.parent)
        elif self.config_path:
            initial = str(self.config_path.parent)
        else:
            initial = _default_components()
        p = filedialog.askopenfilename(
            title="Select Components JSON",
            initialdir=initial,
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if p:
            self.sv['components'].set(self._make_rel(p))
            self._components_reload()

    # ─────────────────────────────────────────────
    # Config Sync
    # ─────────────────────────────────────────────

    def _load_cfg_to_ui(self):
        self._loading = True
        try:
            self.sv['ship_name'  ].set(self.config.get("ship_name", ""))
            self.sv['output_file'].set(self.config.get("output_file", ""))
            self.sv['templates'  ].set(
                self.config.get("templates") or self.config.get("templates_file", ""))
            self.sv['components' ].set(self.config.get("components", ""))
            tm = self.config.get("turret_models", {})
            self.sv['tm_start' ].set(str(tm.get("start",  1)))
            self.sv['tm_format'].set(str(tm.get("format", "02d")))
            dp = self.config.get("damage_particles", {})
            self.sv['dp_start' ].set(str(dp.get("start",  1)))
            self.sv['dp_format'].set(str(dp.get("format", "02d")))
        finally:
            self._loading = False

        # ── Filter lists (excludes / includes) ───────────────────────────
        # These are populated here rather than inside _loading so that the
        # listboxes (which are not driven by StringVar traces) are always
        # refreshed whenever a new config is opened.
        if hasattr(self, '_tpl_excl_lb'):
            self._filter_lb_load(self._tpl_excl_lb,
                                 self.config.get("template_excludes", []))
        if hasattr(self, '_tpl_incl_lb'):
            self._filter_lb_load(self._tpl_incl_lb,
                                 self.config.get("template_includes", []))
        if hasattr(self, '_comp_excl_lb'):
            self._filter_lb_load(self._comp_excl_lb,
                                 self.config.get("component_excludes", []))
        if hasattr(self, '_comp_incl_lb'):
            self._filter_lb_load(self._comp_incl_lb,
                                 self.config.get("component_includes", []))
        # Auto-expand filter panels if the loaded config already has filter entries
        has_tpl_filters = (self.config.get("template_excludes") or
                           self.config.get("template_includes"))
        has_comp_filters = (self.config.get("component_excludes") or
                            self.config.get("component_includes"))
        if has_tpl_filters and hasattr(self, '_tpl_filter_toggle'):
            try:
                self._tpl_filter_toggle()   # _expand_only — safe to call multiple times
            except Exception:
                pass
        if has_comp_filters and hasattr(self, '_comp_filter_toggle'):
            try:
                self._comp_filter_toggle()
            except Exception:
                pass

        if "bone_pool" not in self.config:
            self.config["bone_pool"] = self._collect_bones_from_groups()

        self._bones_refresh()
        self._groups_refresh()
        self._templates_reload()
        self._components_reload()
        self._update_file_info()
        self._update_json_preview()

    def _sync_cfg_from_ui(self):
        self.config["ship_name"]   = self.sv['ship_name'  ].get().strip()
        self.config["output_file"] = self.sv['output_file'].get().strip()
        self.config["templates"]   = self.sv['templates'  ].get().strip()
        self.config.pop("templates_file", None)
        comp = self.sv['components'].get().strip()
        if comp:
            self.config["components"] = comp
        else:
            self.config.pop("components", None)
        try:
            tm_start = int(self.sv['tm_start'].get())
        except ValueError:
            tm_start = 1
        self.config["turret_models"] = {
            "start":  tm_start,
            "format": self.sv['tm_format'].get().strip() or "02d"
        }
        try:
            dp_start = int(self.sv['dp_start'].get())
        except ValueError:
            dp_start = 1
        self.config["damage_particles"] = {
            "start":  dp_start,
            "format": self.sv['dp_format'].get().strip() or "02d"
        }
        #self.config["bone_pool"] = self._pool_entries_from_tv()

    def _on_cfg_changed(self, *_):
        if self._loading:
            return
        self._mark_dirty()
        self._update_json_preview()

    def _mark_dirty(self):
        self.dirty = True
        self._update_title()

    def _update_title(self):
        fname = self.config_path.name if self.config_path else "Untitled"
        self.root.title(f"{'● ' if self.dirty else ''}{fname} — {APP_TITLE} v{APP_VERSION}")

    def _update_file_info(self):
        loc = str(self.config_path) if self.config_path else "Not saved"
        g   = len(self.config.get("groups", []))
        b   = len(self.config.get("bone_pool", []))
        t   = len(self.template_registry)
        c   = len(self.component_registry)
        self.sv_file_info.set(f"{loc}\n{g} groups  ·  {b} bones  ·  {t} templates  ·  {c} components")

    def _update_json_preview(self):
        self._sync_cfg_from_ui()
        try:
            lines = json.dumps(self.config, indent=2).split('\n')
            text  = '\n'.join(lines[:80])
            if len(lines) > 80:
                text += f"\n  … ({len(lines)-80} more lines)"
        except Exception:
            text = "(error)"
        self.json_preview.config(state='normal')
        self.json_preview.delete('1.0', tk.END)
        self.json_preview.insert('1.0', text)
        self.json_preview.config(state='disabled')

    # ─────────────────────────────────────────────
    # Templates
    # ─────────────────────────────────────────────

    def _templates_reload(self):
        self._sync_cfg_from_ui()
        raw_path = self.config.get("templates", "")
        has_includes = bool(self.config.get("template_includes"))

        if not raw_path and not has_includes:
            self.sv_tpl_status.set("⚠ No templates path set")
            self._tpl_status_lbl.configure(style='Warn.TLabel')
            return

        abs_path = resolve_path(self.config_path, raw_path) if raw_path else ""

        # Resolve filter paths relative to the config file (snapshot before thread)
        excl_abs = [resolve_path(self.config_path, e)
                    for e in self.config.get("template_excludes", []) if e]
        incl_abs = [resolve_path(self.config_path, i)
                    for i in self.config.get("template_includes", []) if i]

        if abs_path:
            self._log(f"Loading templates from: {abs_path}\n", 'dim')
        if excl_abs:
            self._log(f"  Excludes: {', '.join(Path(e).name for e in excl_abs)}\n", 'dim')
        if incl_abs:
            self._log(f"  Includes: {', '.join(Path(i).name for i in incl_abs)}\n", 'dim')
        self.sv_tpl_status.set("Loading…")

        def _load():
            return load_templates_safe(abs_path, excludes=excl_abs, includes=incl_abs)

        def _done(resolved, raw, errors):
            self.template_registry = resolved
            self.raw_registry      = raw

            if errors:
                for e in errors:
                    self._log(f"  ⚠ {e}\n", 'warn')

            n = len(resolved)
            n_excl = len(self.config.get("template_excludes", []))
            n_incl = len(self.config.get("template_includes", []))
            filter_note = ""
            if n_excl or n_incl:
                parts = []
                if n_excl: parts.append(f"{n_excl} excl")
                if n_incl: parts.append(f"{n_incl} incl")
                filter_note = f"  [{', '.join(parts)}]"
            if n == 0:
                self.sv_tpl_status.set(f"⚠ No templates loaded{filter_note}")
                self._tpl_status_lbl.configure(style='Warn.TLabel')
            else:
                self.sv_tpl_status.set(f"✓ {n} template{'s' if n != 1 else ''} loaded{filter_note}")
                self._tpl_status_lbl.configure(style='Good.TLabel')

            self.sv_tpl_count.set(f"{n} templates")
            self._tpl_browser_refresh()
            self._groups_refresh()
            self._update_file_info()
            self._log(f"Templates loaded: {n}{filter_note}\n", 'success' if n else 'warn')

        def _run():
            result = _load()
            self.root.after(0, lambda: _done(*result))

        threading.Thread(target=_run, daemon=True).start()

    def _components_reload(self):
        self._sync_cfg_from_ui()
        raw_path = self.config.get("components", "")
        has_includes = bool(self.config.get("component_includes"))

        if not raw_path and not has_includes:
            self.sv_comp_status.set("No components path set")
            self._comp_status_lbl.configure(style='Warn.TLabel')
            self.component_registry = {}
            self.raw_comp_registry  = {}
            self._ge_refresh_comp_combo()
            if hasattr(self, 'comp_tv'):
                self._comp_browser_refresh()
            return

        abs_path = resolve_path(self.config_path, raw_path) if raw_path else ""

        # Resolve filter paths relative to the config file (snapshot before thread)
        excl_abs = [resolve_path(self.config_path, e)
                    for e in self.config.get("component_excludes", []) if e]
        incl_abs = [resolve_path(self.config_path, i)
                    for i in self.config.get("component_includes", []) if i]

        if abs_path:
            self._log(f"Loading components from: {abs_path}\n", 'dim')
        if excl_abs:
            self._log(f"  Excludes: {', '.join(Path(e).name for e in excl_abs)}\n", 'dim')
        if incl_abs:
            self._log(f"  Includes: {', '.join(Path(i).name for i in incl_abs)}\n", 'dim')
        self.sv_comp_status.set("Loading…")

        def _load():
            return load_components_safe(abs_path, excludes=excl_abs, includes=incl_abs)

        def _done(resolved, raw, errors):
            self.component_registry = resolved
            self.raw_comp_registry  = raw

            if errors:
                for e in errors:
                    self._log(f"  ⚠ {e}\n", 'warn')

            n = len(resolved)
            n_excl = len(self.config.get("component_excludes", []))
            n_incl = len(self.config.get("component_includes", []))
            filter_note = ""
            if n_excl or n_incl:
                parts = []
                if n_excl: parts.append(f"{n_excl} excl")
                if n_incl: parts.append(f"{n_incl} incl")
                filter_note = f"  [{', '.join(parts)}]"
            if n == 0:
                self.sv_comp_status.set(f"⚠ No components loaded{filter_note}")
                self._comp_status_lbl.configure(style='Warn.TLabel')
            else:
                self.sv_comp_status.set(f"✓ {n} component{'s' if n != 1 else ''} loaded{filter_note}")
                self._comp_status_lbl.configure(style='Good.TLabel')

            self._ge_refresh_comp_combo()
            self._log(f"Components loaded: {n}{filter_note}\n", 'success' if n else 'warn')
            # Refresh the Component Browser tab if it has been built
            if hasattr(self, 'comp_tv'):
                self._comp_browser_refresh()

        def _run():
            result = _load()
            self.root.after(0, lambda: _done(*result))

        threading.Thread(target=_run, daemon=True).start()

    def _ge_refresh_comp_combo(self):
        """Update the component picker combo values after a registry reload."""
        if hasattr(self, '_ge_comp_combo'):
            self._ge_comp_combo.configure_values(sorted(self.component_registry.keys()))

    # ─────────────────────────────────────────────
    # Bone Pool
    # ─────────────────────────────────────────────

    def _collect_bones_from_groups(self) -> list:
        seen, pool = set(), []
        for g in self.config.get("groups", []):
            for e in g.get("bones", []):
                n = bone_name(e)
                if n and n not in seen:
                    seen.add(n)
                    pool.append(e)
        return pool

    def _pool_entries_from_tv(self) -> list:
        entries = []
        for iid in self.bones_tv.get_children():
            v = self.bones_tv.item(iid)['values']
            b = v[0] if v else ""; c = v[1] if len(v) > 1 else ""
            if b:
                entries.append(make_bone_entry(b, c))
        return entries

    def _group_assignments(self) -> dict[str, list[int]]:
        """Return {bone_name: [group_indices]} for every bone referenced in any slot."""
        asgn: dict[str, list[int]] = {}
        for gi, g in enumerate(self.config.get("groups", [])):
            for e in g.get("bones", []):
                # Collect every non-empty bone name referenced in this entry
                bone_refs: set[str] = set()
                a = bone_name(e)
                if a:
                    bone_refs.add(a)
                for fn in (bone_b_val, bone_c_val, bone_d_val, bone_e_val, bone_f_val):
                    v = fn(e)
                    if v:
                        bone_refs.add(v)
                for n in bone_refs:
                    asgn.setdefault(n, []).append(gi)
        return asgn

    _bones_sort_col = ""
    _bones_sort_rev = False

    def _bones_sort(self, col):
        if self._bones_sort_col == col:
            self._bones_sort_rev = not self._bones_sort_rev
        else:
            self._bones_sort_col = col
            self._bones_sort_rev = False
        self._bones_refresh()

    def _bones_refresh(self):
        filt  = self.sv_bone_filter.get().lower() if hasattr(self, 'sv_bone_filter') else ""
        asgn  = self._group_assignments()
        groups = self.config.get("groups", [])

        rows = []
        for e in self.config.get("bone_pool", []):
            bn = bone_name(e); bc = bone_custom(e)
            if filt and filt not in bn.lower() and filt not in bc.lower():
                continue
            indices = asgn.get(bn, [])
            if indices:
                labels = []
                for gi in indices:
                    gname = (groups[gi].get("group_comment") or
                             groups[gi].get("name_prefix", f"G{gi+1}"))
                    labels.append(f"[{gi+1}] {gname[:20]}")
                grp_str = ", ".join(labels)
                tag = 'multi' if len(indices) > 1 else 'assigned'
            else:
                grp_str = "—"; tag = 'unassigned'
            rows.append((bn, bc, grp_str, tag))

        # Sort
        col_idx = {'bone': 0, 'custom': 1, 'groups': 2}.get(self._bones_sort_col, 0)
        rows.sort(key=lambda r: r[col_idx].lower(), reverse=self._bones_sort_rev)

        self.bones_tv.delete(*self.bones_tv.get_children())
        for bn, bc, grp_str, tag in rows:
            self.bones_tv.insert('', 'end', iid=bn, values=(bn, bc, grp_str), tags=(tag,))

        self.sv_bone_count.set(f"{len(rows)} bones")
        self._update_file_info()

    def _bones_selected_names(self) -> list[str]:
        return [self.bones_tv.item(i)['values'][0]
                for i in self.bones_tv.selection()
                if self.bones_tv.item(i)['values']]

    def _bones_add(self):
        dlg = BoneDialog(self.root, "Add Bone")
        if not dlg.result:
            return
        b, c = dlg.result
        pool = self.config.setdefault("bone_pool", [])
        if b in {bone_name(e) for e in pool}:
            messagebox.showwarning("Duplicate", f"'{b}' is already in the pool."); return
        pool.append(make_bone_entry(b, c))
        self._bones_refresh(); self._mark_dirty(); self._update_json_preview()

    def _bones_sequence(self):
        pool = self.config.setdefault("bone_pool", [])
        dlg = BoneSequenceDialog(self.root, existing_pool=pool)
        if not dlg.result:
            return
        existing = {bone_name(e) for e in pool}
        added = 0
        for b in dlg.result:
            if b not in existing:
                pool.append(b)
                existing.add(b)
                added += 1
        skipped = len(dlg.result) - added
        self._bones_refresh(); self._mark_dirty(); self._update_json_preview()
        self._log(f"Added {added} bone(s)" + (f" ({skipped} duplicates skipped)" if skipped else "") + ".\n", 'info')

    def _bones_from_alo(self):
        """Open the ALO import dialog and add the user-selected bones to the pool."""
        if not _ALO_AVAILABLE:
            messagebox.showerror(
                "ALO Reader Unavailable",
                "alo_reader.py could not be imported.\n"
                "Make sure it is in the same directory as hp_generator_GUI.py.",
                parent=self.root)
            return

        pool = self.config.setdefault("bone_pool", [])
        dlg  = AloImportDialog(self.root, existing_pool=pool)

        if dlg.result is None:
            return   # user cancelled

        if not dlg.result:
            self._log("ALO import: no bones selected.\n", 'warn')
            return

        existing = {bone_name(e) for e in pool}
        added = 0
        for b in dlg.result:
            if b not in existing:
                pool.append(b)
                existing.add(b)
                added += 1

        self._bones_refresh(); self._mark_dirty(); self._update_json_preview()
        self._log(f"ALO import: added {added} bone(s) to pool.\n",
                  'success' if added else 'info')

    def _bones_edit(self):
        sel = self.bones_tv.selection()
        if not sel:
            return
        iid = sel[0]
        v   = self.bones_tv.item(iid)['values']
        dlg = BoneDialog(self.root, "Edit Bone", bone=v[0], custom=v[1] if len(v) > 1 else "")
        if not dlg.result:
            return
        nb, nc = dlg.result
        old_b  = v[0]
        pool = self.config.get("bone_pool", [])
        for i, e in enumerate(pool):
            if bone_name(e) == old_b:
                pool[i] = make_bone_entry(nb, nc); break
        # Rename in groups too
        if nb != old_b:
            for g in self.config.get("groups", []):
                for j, e in enumerate(g.get("bones", [])):
                    if bone_name(e) == old_b:
                        g["bones"][j] = make_bone_entry(nb, bone_custom(e) or nc)
        self._bones_refresh(); self._groups_refresh()
        if self._editing_group_idx is not None:
            self._ge_load(self._editing_group_idx)
        self._mark_dirty(); self._update_json_preview()

    def _bones_delete(self):
        names = self._bones_selected_names()
        if not names:
            return
        asgn = self._group_assignments()
        in_groups = [n for n in names if asgn.get(n)]
        msg = f"Delete {len(names)} bone(s) from the pool?"
        if in_groups:
            msg += f"\n\nThese are assigned to groups and will be removed from them too:\n  " + "\n  ".join(in_groups[:10])
            if len(in_groups) > 10:
                msg += f"\n  … and {len(in_groups)-10} more"
        if not messagebox.askyesno("Delete Bones", msg):
            return
        if in_groups:
            for g in self.config.get("groups", []):
                g["bones"] = [e for e in g.get("bones", []) if bone_name(e) not in names]
        self.config["bone_pool"] = [e for e in self.config.get("bone_pool", [])
                                     if bone_name(e) not in names]
        self._bones_refresh(); self._groups_refresh()
        if self._editing_group_idx is not None:
            self._ge_load(self._editing_group_idx)
        self._mark_dirty(); self._update_json_preview()
        self._log(f"Deleted {len(names)} bone(s).\n", 'info')

    def _bones_ctx_menu(self, event):
        item = self.bones_tv.identify_row(event.y)
        if item and item not in self.bones_tv.selection():
            self.bones_tv.selection_set(item)
        ctx = tk.Menu(self.root, tearoff=False,
                      background=P['s0'], foreground=P['text'],
                      activebackground=P['blue'], activeforeground=P['bg'])
        ctx.add_command(label="Edit Bone",   command=self._bones_edit)
        ctx.add_command(label="Delete",      command=self._bones_delete)
        ctx.add_separator()
        ctx.add_command(label="Select All",
                        command=lambda: self.bones_tv.selection_set(self.bones_tv.get_children()))
        ctx.add_separator()
        ctx.add_command(label="Assign to Selected Group", command=self._bones_assign_to_group)
        ctx.add_command(label="Bulk Assign…",             command=self._bones_bulk_assign)
        try:
            ctx.tk_popup(event.x_root, event.y_root)
        finally:
            ctx.grab_release()

    def _bones_assign_to_group(self):
        names = self._bones_selected_names()
        if not names:
            messagebox.showinfo("No Selection", "Select bones in the Bone Pool first.")
            return
        sel = self.groups_tv.selection()
        if not sel:
            messagebox.showinfo("No Group", "Select a group in the Groups list first.")
            return
        gi = self._gv_to_idx(sel[0])
        if gi is None:
            return
        dlg = BoneColumnAssignDialog(
            self.root,
            bone_pool=self.config.get("bone_pool", []),
            groups=self.config.get("groups", []),
            preselected_bones=names,
            current_group_idx=gi,
        )
        if not dlg.result:
            return
        target_gi, new_bones = dlg.result
        prev_group_sel = self.groups_tv.selection()
        self.config["groups"][target_gi]["bones"] = new_bones
        self._bones_refresh(); self._groups_refresh()
        # Restore whichever group was selected; fall back to the target group
        restored = False
        for iid in prev_group_sel:
            if iid in self.groups_tv.get_children():
                self.groups_tv.selection_set(iid)
                self.groups_tv.see(iid)
                restored = True
        if not restored:
            tgt_iid = str(target_gi)
            if tgt_iid in self.groups_tv.get_children():
                self.groups_tv.selection_set(tgt_iid)
                self.groups_tv.see(tgt_iid)
        if self._editing_group_idx == target_gi:
            self._ge_load(target_gi)
        self._mark_dirty(); self._update_json_preview()
        self._log(f"Assigned bones to group [{target_gi+1}].\n", 'success')

    def _bones_bulk_assign(self):
        groups = self.config.get("groups", [])
        pool   = self.config.get("bone_pool", [])
        if not pool:
            messagebox.showinfo("No Bones", "No bones in pool. Add bones first."); return
        if not groups:
            messagebox.showinfo("No Groups", "No groups yet. Create a group first."); return
        gi = self._gv_to_idx(self.groups_tv.selection()[0]) if self.groups_tv.selection() else None
        dlg = BoneColumnAssignDialog(
            self.root,
            bone_pool=pool,
            groups=groups,
            current_group_idx=gi,
        )
        if not dlg.result:
            return
        target_gi, new_bones = dlg.result
        prev_group_sel = self.groups_tv.selection()
        self.config["groups"][target_gi]["bones"] = new_bones
        self._bones_refresh(); self._groups_refresh()
        # Restore group selection
        restored = False
        for iid in prev_group_sel:
            if iid in self.groups_tv.get_children():
                self.groups_tv.selection_set(iid)
                self.groups_tv.see(iid)
                restored = True
        if not restored:
            tgt_iid = str(target_gi)
            if tgt_iid in self.groups_tv.get_children():
                self.groups_tv.selection_set(tgt_iid)
                self.groups_tv.see(tgt_iid)
        if self._editing_group_idx == target_gi:
            self._ge_load(target_gi)
        self._mark_dirty(); self._update_json_preview()
        self._log(f"Bulk assigned bones to group [{target_gi+1}].\n", 'success')
    # ─────────────────────────────────────────────
    # Groups List
    # ─────────────────────────────────────────────

    def _groups_refresh(self):
        self.groups_tv.delete(*self.groups_tv.get_children())
        for i, g in enumerate(self.config.get("groups", [])):
            label = g.get("group_comment") or g.get("name_prefix", "—")
            tpl   = g.get("template", "—")
            # Mark missing templates
            if tpl not in self.template_registry and tpl and self.template_registry:
                tpl = f"⚠ {tpl}"
            # --- Components column ---
            comp_names = g.get("components", [])
            if comp_names:
                comp_str = ", ".join(comp_names)
                if len(comp_str) > 38:
                    comp_str = comp_str[:35] + "…"
            else:
                comp_str = "—"
            # --- Field overrides column ---
            overrides = g.get("field_overrides", [])
            ov_tags = [
                f.get("tag") or f.get("text", "")
                for f in overrides
                if f.get("_type", "element") not in ("blank",)
                   and (f.get("tag") or f.get("text"))
            ]
            if ov_tags:
                ov_str = ", ".join(ov_tags)
                if len(ov_str) > 38:
                    ov_str = ov_str[:35] + "…"
            else:
                ov_str = "—"
            self.groups_tv.insert('', 'end', iid=str(i),
                                   values=(i+1, label, tpl,
                                           len(g.get("bones", [])),
                                           comp_str, ov_str))

        n = len(self.config.get("groups", []))
        self.sv_group_count.set(f"{n} group{'s' if n != 1 else ''}")

        tpl_names = sorted(self.template_registry.keys())
        if hasattr(self, '_ge_tpl_combo'):
            self._ge_tpl_combo.configure_values(tpl_names)

    def _gv_to_idx(self, iid: str) -> int | None:
        try: return int(iid)
        except Exception: return None

    def _on_group_select(self, _=None):
        # Ignore events fired by _ge_save restoring the selection programmatically
        if self._ge_saving:
            return
        sel = self.groups_tv.selection()
        if not sel:
            self._ge_set_enabled(False); return
        gi = self._gv_to_idx(sel[0])
        if gi is not None:
            self._ge_load(gi)

    def _groups_add(self):
        default_tpl = (sorted(self.template_registry.keys()) or [""])[0]
        ship = self.config.get('ship_name', 'Ship')
        g = {
            "group_comment": "{shipname}, {templatename}",
            "template":      default_tpl,
            "name_prefix":   "HP_{shipname}_{templatename}",
            "start_index":   1,
            "index_format":  "02d",
            "bones":         []
        }
        self.config.setdefault("groups", []).append(g)
        self._groups_refresh()
        ni = len(self.config["groups"]) - 1
        self.groups_tv.selection_set(str(ni)); self.groups_tv.see(str(ni))
        self._ge_load(ni); self._mark_dirty()

    def _groups_delete(self):
        sel = self.groups_tv.selection()
        if not sel: return
        gi = self._gv_to_idx(sel[0])
        if gi is None: return
        label = (self.config["groups"][gi].get("group_comment") or
                 self.config["groups"][gi].get("name_prefix", f"Group {gi+1}"))
        n_bones = len(self.config["groups"][gi].get("bones", []))
        msg = f"Delete group '{label}'?"
        if n_bones:
            msg += f"\n\n({n_bones} bone assignment{'s' if n_bones != 1 else ''} will be lost from this group — bones remain in the pool)"
        if not messagebox.askyesno("Delete Group", msg):
            return
        del self.config["groups"][gi]
        self._editing_group_idx = None
        self._ge_set_enabled(False)
        self._groups_refresh(); self._bones_refresh(); self._mark_dirty(); self._update_json_preview()

    def _groups_duplicate(self):
        sel = self.groups_tv.selection()
        if not sel: return
        gi = self._gv_to_idx(sel[0])
        if gi is None: return
        dup = copy.deepcopy(self.config["groups"][gi])
        dup["name_prefix"]   = dup.get("name_prefix", "") + "_Copy"
        dup["group_comment"] = (dup.get("group_comment", "") + " (Copy)").strip()
        self.config["groups"].insert(gi + 1, dup)
        self._groups_refresh()
        ni = str(gi + 1)
        self.groups_tv.selection_set(ni); self.groups_tv.see(ni)
        self._ge_load(gi + 1); self._mark_dirty()

    def _groups_move_up(self):
        sel = self.groups_tv.selection()
        if not sel: return
        gi = self._gv_to_idx(sel[0])
        if gi is None or gi == 0: return
        gs = self.config["groups"]
        gs[gi-1], gs[gi] = gs[gi], gs[gi-1]
        self._groups_refresh()
        self.groups_tv.selection_set(str(gi-1))
        if self._editing_group_idx == gi:
            self._editing_group_idx = gi - 1
        self._mark_dirty()

    def _groups_move_down(self):
        sel = self.groups_tv.selection()
        if not sel: return
        gi = self._gv_to_idx(sel[0])
        gs = self.config["groups"]
        if gi is None or gi >= len(gs) - 1: return
        gs[gi], gs[gi+1] = gs[gi+1], gs[gi]
        self._groups_refresh()
        self.groups_tv.selection_set(str(gi+1))
        if self._editing_group_idx == gi:
            self._editing_group_idx = gi + 1
        self._mark_dirty()

    def _groups_tv_tooltip(self, event):
        """Show a popup with the full components / field-overrides list on hover."""
        row = self.groups_tv.identify_row(event.y)
        col = self.groups_tv.identify_column(event.x)

        if col not in ('#5', '#6') or not row:
            self._groups_hide_tooltip()
            return

        gi = self._gv_to_idx(row)
        if gi is None or gi >= len(self.config.get("groups", [])):
            self._groups_hide_tooltip()
            return

        g = self.config["groups"][gi]

        if col == '#5':                          # Components
            items = g.get("components", [])
            if not items:
                self._groups_hide_tooltip()
                return
            header = f"Components ({len(items)}):"
            lines  = [f"  {c}" for c in items]
        else:                                    # Field Overrides
            overrides = g.get("field_overrides", [])
            items = [
                f.get("tag") or f.get("text", "")
                for f in overrides
                if f.get("_type", "element") not in ("blank",)
                   and (f.get("tag") or f.get("text"))
            ]
            if not items:
                self._groups_hide_tooltip()
                return
            header = f"Field Overrides ({len(items)}):"
            lines  = [f"  {t}" for t in items]

        key = (row, col)
        if key == self._groups_tooltip_last:
            return                               # already showing for this cell
        self._groups_tooltip_last = key
        self._groups_hide_tooltip()

        text = header + "\n" + "\n".join(lines)
        x, y = event.x_root + 14, event.y_root + 14

        tw = tk.Toplevel(self.root)
        tw.wm_overrideredirect(True)
        tw.configure(bg=P['s1'])
        tk.Label(tw, text=text, bg=P['s0'], fg=P['text'],
                 font=('Consolas', 8), justify='left',
                 padx=8, pady=5, relief='flat').pack()
        tw.geometry(f"+{x}+{y}")
        self._groups_tooltip_win = tw

    def _groups_hide_tooltip(self):
        """Destroy the groups-list tooltip if it is visible."""
        if getattr(self, '_groups_tooltip_win', None):
            try:
                self._groups_tooltip_win.destroy()
            except Exception:
                pass
            self._groups_tooltip_win  = None
        self._groups_tooltip_last = None

    # ─────────────────────────────────────────────
    # Group Editor
    # ─────────────────────────────────────────────

    def _ge_set_enabled(self, on: bool):
        if not on:
            self.sv_ge_label.set("(no group selected)")
            try:
                self.ge_comp_tv.delete(*self.ge_comp_tv.get_children())
                self.sv_ge_comp_count.set("0 components")
                self.ge_ov_tv.delete(*self.ge_ov_tv.get_children())
                self._ge_ov_field_store.clear()
                self.sv_ge_ov_count.set("0 overrides")
            except Exception:
                pass

    def _ge_load(self, gi: int):
        self._editing_group_idx = gi
        gs = self.config.get("groups", [])
        if gi >= len(gs): return
        g = gs[gi]

        self._loading = True
        self.ge['comment'        ].set(g.get("group_comment",  ""))
        self.ge['prefix'         ].set(g.get("name_prefix",    ""))
        self.ge['template'       ].set(g.get("template",       ""))
        self.ge['start'          ].set(str(g.get("start_index", 1)))
        self.ge['fmt'            ].set(g.get("index_format",  "02d"))
        self.ge['health_override'].set(g.get("health_override", ""))
        self._loading = False

        label = g.get("group_comment") or g.get("name_prefix", f"Group {gi+1}")
        self.sv_ge_label.set(f"Editing  [{gi+1}]  {label}")
        self._ge_set_enabled(True)
        self._ge_refresh_bones(g.get("bones", []))
        self._ge_refresh_components(g.get("components", []))
        self._ge_ov_refresh(g.get("field_overrides", []))
        self._ge_check_model_warn()
        self._ge_update_name_preview()

    def _ge_refresh_bones(self, bones):
        self.ge_bones_tv.delete(*self.ge_bones_tv.get_children())
        prefix = self.ge['prefix'].get()
        try:
            start = int(self.ge['start'].get())
        except ValueError:
            start = 1
        fmt = self.ge['fmt'].get() or "02d"
        for i, e in enumerate(bones):
            bn_a = bone_name(e)
            bn_b = bone_b_val(e)
            bn_c = bone_c_val(e)
            bn_d = bone_d_val(e)
            bn_e = bone_e_val(e)
            bn_f = bone_f_val(e)
            bc   = bone_custom(e)
            if bc:
                hp = bc
            else:
                try:
                    hp = f"{prefix}_{format(start + i, fmt)}"
                except Exception:
                    hp = f"{prefix}_{start + i}"
            has_extra = any([bn_b, bn_c, bn_d, bn_e, bn_f])
            tag = 'dual' if has_extra else 'single'
            self.ge_bones_tv.insert('', 'end',
                values=(i+1, bn_a, bn_b, bn_c, bn_d, bn_e, bn_f, bc, hp), tags=(tag,))
        n = len(bones)
        self.sv_ge_bone_count.set(f"{n} bone{'s' if n != 1 else ''}")

    def _ge_refresh_components(self, comp_names: list):
        """Populate the components treeview from a list of component name strings."""
        self.ge_comp_tv.delete(*self.ge_comp_tv.get_children())
        for i, name in enumerate(comp_names):
            tag = 'comp' if name in self.component_registry else 'unassigned'
            display = name if name in self.component_registry else f"⚠ {name}"
            self.ge_comp_tv.insert('', 'end', iid=str(i), values=(i+1, display), tags=(tag,))
        n = len(comp_names)
        self.sv_ge_comp_count.set(f"{n} component{'s' if n != 1 else ''}")
        self._ge_check_comp_conflicts(comp_names)

    def _ge_check_comp_conflicts(self, comp_names: list):
        """Warn when multiple components override the same field tag.

        The warning label is kept to a single short line; a "Details…" button
        opens a small popup with the full per-tag breakdown.  New conflicts are
        also written to the Output Log the first time they are detected so the
        user doesn't miss them.
        """
        tag_sources: dict[str, list[str]] = {}
        for cname in comp_names:
            comp = self.component_registry.get(cname)
            if not comp:
                continue
            for f in comp.get("fields", []):
                if f.get("_type", "element") == "element":
                    tag = f.get("tag", "")
                    if tag:
                        tag_sources.setdefault(tag, []).append(cname)
        conflicts = {tag: srcs for tag, srcs in tag_sources.items() if len(srcs) > 1}
        self._ge_comp_conflicts = conflicts

        if conflicts:
            n = len(conflicts)
            detail_lines = [f"  {tag}  →  last wins: {srcs[-1]}  (also set by: {', '.join(srcs[:-1])})"
                            for tag, srcs in conflicts.items()]
            self._ge_comp_conflict_details = "\n".join(detail_lines)
            self.sv_ge_comp_warn.set(
                f"⚠  {n} field conflict{'s' if n != 1 else ''} (last component wins)  ")
            self._ge_comp_details_btn.pack(side=tk.LEFT, padx=(4, 0))

            # Log only when the conflict set changes so we don't spam on every refresh
            curr_set = frozenset(conflicts.keys())
            prev_set = getattr(self, '_ge_comp_last_conflict_set', frozenset())
            if curr_set != prev_set:
                self._ge_comp_last_conflict_set = curr_set
                gi    = self._editing_group_idx
                label = f"Group [{gi + 1}]" if gi is not None else "Group"
                self._log(f"⚠ Component conflict in {label}: "
                          f"{n} field{'s' if n != 1 else ''} overridden\n", 'warn')
                for line in detail_lines:
                    self._log(f"    {line.strip()}\n", 'warn')
        else:
            self._ge_comp_conflict_details = ""
            self.sv_ge_comp_warn.set("")
            self._ge_comp_details_btn.pack_forget()
            self._ge_comp_last_conflict_set = frozenset()

   # def _ge_show_comp_conflicts(self):
    def _ge_show_comp_conflicts(self):
            """Open a small scrollable window listing all component conflicts."""
            conflicts = getattr(self, '_ge_comp_conflicts', {})
            if not conflicts:
                return
            dlg = tk.Toplevel(self.root)
            dlg.title("Component Conflicts")
            dlg.geometry("480x320")
            dlg.configure(bg=P['bg'])
            dlg.resizable(True, True)
            dlg.transient(self.root)
            ttk.Label(dlg, text="Conflicting fields — the last listed component wins:",
                    style='Header.TLabel').pack(anchor='w', padx=10, pady=(10, 4))
            ttk.Separator(dlg, orient='h').pack(fill=tk.X, padx=10, pady=2)
            inner = ttk.Frame(dlg)
            inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
            inner.rowconfigure(0, weight=1); inner.columnconfigure(0, weight=1)
            tv = ttk.Treeview(inner, columns=('tag', 'winner', 'losers'),
                            show='headings', selectmode='none')
            tv.heading('tag',    text='Field Tag')
            tv.heading('winner', text='Wins (last)')
            tv.heading('losers', text='Overridden')
            tv.column('tag',    width=160, minwidth=80)
            tv.column('winner', width=140, minwidth=80)
            tv.column('losers', width=160, minwidth=80)
            tv.tag_configure('conflict', foreground=P['yellow'])
            vsb = ttk.Scrollbar(inner, orient='vertical', command=tv.yview)
            tv.configure(yscrollcommand=vsb.set)
            tv.grid(row=0, column=0, sticky='nsew')
            vsb.grid(row=0, column=1, sticky='ns')
            for tag in sorted(conflicts.keys()):
                srcs = conflicts[tag]
                winner = srcs[-1]
                losers = ", ".join(srcs[:-1])
                tv.insert('', 'end', values=(tag, winner, losers), tags=('conflict',))
            ttk.Button(dlg, text="Close", command=dlg.destroy,
                    style='Accent.TButton').pack(pady=(4, 10))
            dlg.grab_set()
            dlg.bind('<Escape>', lambda e: dlg.destroy())

    def _ge_comp_names_from_tv(self) -> list:
        """Return ordered list of component names from the treeview."""
        result = []
        for iid in self.ge_comp_tv.get_children():
            v = self.ge_comp_tv.item(iid)['values']
            if v:
                name = str(v[1]).lstrip("⚠ ").strip()
                result.append(name)
        return result

    def _ge_add_component(self):
        name = self._ge_comp_combo.get().strip()
        if not name:
            return
        existing = self._ge_comp_names_from_tv()
        if name in existing:
            messagebox.showinfo("Already Added",
                                f"Component '{name}' is already in this group.", parent=self.root)
            return
        existing.append(name)
        gi = self._editing_group_idx
        if gi is not None:
            self.config["groups"][gi]["components"] = existing
        self._ge_refresh_components(existing)
        self._mark_dirty(); self._update_json_preview()

    def _ge_remove_component(self):
        sel = self.ge_comp_tv.selection()
        if not sel: return
        existing = self._ge_comp_names_from_tv()
        # Sort indices descending so pops don't shift the positions of later items
        indices = sorted([int(iid) for iid in sel], reverse=True)
        for idx in indices:
            if 0 <= idx < len(existing):
                existing.pop(idx)
        gi = self._editing_group_idx
        if gi is not None:
            self.config["groups"][gi]["components"] = existing
        self._ge_refresh_components(existing)
        self._mark_dirty(); self._update_json_preview()

    def _ge_comp_up(self):
        sel = self.ge_comp_tv.selection()
        if not sel: return
        idx = int(sel[0])
        existing = self._ge_comp_names_from_tv()
        if idx == 0: return
        existing[idx-1], existing[idx] = existing[idx], existing[idx-1]
        gi = self._editing_group_idx
        if gi is not None:
            self.config["groups"][gi]["components"] = existing
        self._ge_refresh_components(existing)
        new_iid = str(idx - 1)
        self.ge_comp_tv.selection_set(new_iid)
        self.ge_comp_tv.see(new_iid)
        self._mark_dirty(); self._update_json_preview()

    def _ge_comp_down(self):
        sel = self.ge_comp_tv.selection()
        if not sel: return
        idx = int(sel[0])
        existing = self._ge_comp_names_from_tv()
        if idx >= len(existing) - 1: return
        existing[idx], existing[idx+1] = existing[idx+1], existing[idx]
        gi = self._editing_group_idx
        if gi is not None:
            self.config["groups"][gi]["components"] = existing
        self._ge_refresh_components(existing)
        new_iid = str(idx + 1)
        self.ge_comp_tv.selection_set(new_iid)
        self.ge_comp_tv.see(new_iid)
        self._mark_dirty(); self._update_json_preview()

    def _ge_autosave(self):
        """Called by StringVar traces — silently saves if a group is loaded."""
        if self._loading or self._editing_group_idx is None:
            return
        self._ge_save(silent=True)

    def _ge_save(self, silent: bool = False):
        gi = self._editing_group_idx
        if gi is None: return
        gs = self.config.get("groups", [])
        if gi >= len(gs): return
        g = gs[gi]

        g["group_comment"] = self.ge['comment'].get().lstrip()
        g["name_prefix"]   = self.ge['prefix'].get().strip()
        g["template"]      = self.ge['template'].get().strip()
        try:
            g["start_index"] = int(self.ge['start'].get())
        except ValueError:
            g["start_index"] = 1
        g["index_format"] = self.ge['fmt'].get().strip() or "02d"

        # Health override — store only when non-empty, remove key when cleared
        health_ov = self.ge['health_override'].get().strip()
        if health_ov:
            g["health_override"] = health_ov
        else:
            g.pop("health_override", None)

        bones = []
        for iid in self.ge_bones_tv.get_children():
            v    = self.ge_bones_tv.item(iid)['values']
            bn_a = v[1] if len(v) > 1 else ""
            bn_b = v[2] if len(v) > 2 else ""
            bn_c = v[3] if len(v) > 3 else ""
            bn_d = v[4] if len(v) > 4 else ""
            bn_e = v[5] if len(v) > 5 else ""
            bn_f = v[6] if len(v) > 6 else ""
            bc   = v[7] if len(v) > 7 else ""
            if bn_a:
                bones.append(make_group_bone_entry(bn_a, bn_b, bn_c, bn_d, bn_e, bn_f, bc))
        g["bones"] = bones

        # Save components list
        comp_names = self._ge_comp_names_from_tv()
        if comp_names:
            g["components"] = comp_names
        else:
            g.pop("components", None)

        # Save field overrides
        overrides = self._ge_ov_fields_from_tv()
        if overrides:
            g["field_overrides"] = overrides
        else:
            g.pop("field_overrides", None)

        # Strip empty optional keys
        for k in ("group_comment",):
            if not g.get(k):
                g.pop(k, None)

        self._groups_refresh(); self._bones_refresh()
        self._mark_dirty(); self._update_json_preview()
        if not silent:
            self._log(f"Group [{gi+1}] saved.\n", 'success')
        # Restore selection so the user stays on the group they just saved.
        # Set _ge_saving so _on_group_select ignores this programmatic event
        # and does NOT call _ge_load (which would rebuild ge_bones_tv and
        # wipe any in-progress selection from bone move / delete operations).
        #
        # IMPORTANT: reset _ge_saving via after_idle, NOT in a finally block.
        # The <<TreeviewSelect>> event fired by selection_set (and the one
        # queued by _groups_refresh's prior delete) are dispatched
        # asynchronously by Tk.  A finally block resets _ge_saving=False
        # before those events arrive, so _on_group_select is no longer
        # blocked and calls _ge_load, which rebuilds ge_bones_tv with new
        # auto-generated iids — breaking any selection restore that callers
        # (e.g. _ge_bone_up/down) attempt after _ge_save returns.
        # Keeping _ge_saving=True until after_idle ensures the flag is still
        # set when the queued events fire.
        iid = str(gi)
        if iid in self.groups_tv.get_children():
            self._ge_saving = True
            self.groups_tv.selection_set(iid)
            self.groups_tv.see(iid)
            self.root.after_idle(lambda: setattr(self, '_ge_saving', False))
        else:
            self._ge_saving = False

    def _ge_reload(self):
        if self._editing_group_idx is not None:
            self._ge_load(self._editing_group_idx)

    def _ge_on_template_changed(self, _=None):
        self._ge_check_model_warn()

    def _ge_check_model_warn(self):
        tpl_name = self.ge['template'].get()
        tpl = self.template_registry.get(tpl_name, {})

        def _uses(ph):
            return any(ph in str(f.get("value", ""))
                       for f in tpl.get("fields", [])
                       if f.get("_type", "element") == "element")

        missing_tpl = tpl_name and tpl_name not in self.template_registry and self.template_registry
        needs_model  = _uses("{model_idx}")
        needs_damage = _uses("{damage_idx}")

        warns = []
        if missing_tpl:
            warns.append(f"Template '{tpl_name}' not found in loaded templates")
        if needs_model:
            warns.append("Template uses {model_idx} — counter from Turret Models (sidebar)")
        if needs_damage:
            warns.append("Template uses {damage_idx} — counter from Damage Particles (sidebar)")

        self.sv_ge_model_warn.set("  |  ".join(f"ℹ {w}" for w in warns))

    def _ge_update_name_preview(self):
        prefix = self.ge['prefix'].get().strip()
        try:
            start  = int(self.ge['start'].get())
        except ValueError:
            start = 1
        fmt = self.ge['fmt'].get().strip() or "02d"
        try:
            ex = f"{prefix}_{format(start, fmt)}, {prefix}_{format(start+1, fmt)}, …"
        except Exception:
            ex = "(invalid format)"
        self.sv_ge_name_preview.set(ex)

    def _ge_preview_template(self):
        name = self.ge['template'].get()
        if not name:
            return
        self.notebook.select(1)
        # Highlight in template browser
        for iid in self.tpl_tv.get_children():
            if self.tpl_tv.item(iid)['values'][0] == name:
                self.tpl_tv.selection_set(iid)
                self.tpl_tv.see(iid)
                self._on_tpl_selected()
                return

    def _ge_add_from_pool(self):
        pool = self.config.get("bone_pool", [])
        if not pool:
            messagebox.showinfo("Empty Pool", "No bones in pool. Add bones first."); return
        gi = self._editing_group_idx
        if gi is None:
            messagebox.showinfo("No Group", "No group is being edited."); return
        # Pass current group's bone list so the preview is accurate
        dlg = BoneColumnAssignDialog(
            self.root,
            bone_pool=pool,
            groups=self.config.get("groups", []),
            current_group_idx=gi,
        )
        if not dlg.result:
            return
        target_gi, new_bones = dlg.result
        self.config["groups"][target_gi]["bones"] = new_bones
        # Reload the group editor so ge_bones_tv reflects the new list
        self._ge_load(target_gi)
        self._ge_save(silent=True)
        self._bones_refresh()
        self._log(f"Added bones to group [{target_gi+1}] via From Pool.\n", 'info')
    def _update_ge_bone_count(self):
        n = len(self.ge_bones_tv.get_children())
        self.sv_ge_bone_count.set(f"{n} bone{'s' if n != 1 else ''}")

    def _ge_remove_bone(self):
        sel = self.ge_bones_tv.selection()
        if not sel: return
        children = list(self.ge_bones_tv.get_children())
        sel_set  = set(sel)
        # Find the best item to focus after deletion: first item below the
        # deleted block, or the last item above it if nothing remains below.
        last_del_idx = max(children.index(iid) for iid in sel)
        candidates_after  = [c for c in children[last_del_idx+1:] if c not in sel_set]
        candidates_before = [c for c in children[:last_del_idx]   if c not in sel_set]
        next_sel = (candidates_after or candidates_before or [None])[-1] \
                   if not candidates_after else candidates_after[0]
        for iid in sel:
            self.ge_bones_tv.delete(iid)
        self._renumber_ge_bones()
        self._update_ge_bone_count()
        if next_sel and next_sel in self.ge_bones_tv.get_children():
            self.ge_bones_tv.selection_set(next_sel)
            self.ge_bones_tv.see(next_sel)
        self._ge_save(silent=True)

    def _renumber_ge_bones(self):
        prefix = self.ge['prefix'].get()
        try:
            start = int(self.ge['start'].get())
        except ValueError:
            start = 1
        fmt = self.ge['fmt'].get() or "02d"
        for i, iid in enumerate(self.ge_bones_tv.get_children()):
            v    = self.ge_bones_tv.item(iid)['values']
            bn_a = v[1] if len(v) > 1 else ""
            bn_b = v[2] if len(v) > 2 else ""
            bn_c = v[3] if len(v) > 3 else ""
            bn_d = v[4] if len(v) > 4 else ""
            bn_e = v[5] if len(v) > 5 else ""
            bn_f = v[6] if len(v) > 6 else ""
            bc   = v[7] if len(v) > 7 else ""
            try:
                hp = bc if bc else f"{prefix}_{format(start + i, fmt)}"
            except Exception:
                hp = f"{prefix}_{start + i}"
            has_extra = any([bn_b, bn_c, bn_d, bn_e, bn_f])
            tag = 'dual' if has_extra else 'single'
            self.ge_bones_tv.item(iid, values=(i+1, bn_a, bn_b, bn_c, bn_d, bn_e, bn_f, bc, hp),
                                   tags=(tag,))

    def _ge_bone_up(self):
        sel = list(self.ge_bones_tv.selection())
        if not sel: return
        children = list(self.ge_bones_tv.get_children())
        # Sort by ascending position so we move the topmost item first
        ordered = sorted(sel, key=lambda iid: children.index(iid))
        if children.index(ordered[0]) == 0: return   # topmost already at position 0
        for iid in ordered:
            children = list(self.ge_bones_tv.get_children())
            cur = children.index(iid)
            if cur > 0:
                self.ge_bones_tv.move(iid, '', cur - 1)
        self._renumber_ge_bones()
        # _ge_save keeps _ge_saving=True until after_idle, which blocks any
        # deferred <<TreeviewSelect>> events from triggering _ge_load and
        # rebuilding ge_bones_tv with new iids.  Restore selection
        # synchronously while the iids are still valid.
        self._ge_save(silent=True)
        self.ge_bones_tv.selection_set(*sel)
        self.ge_bones_tv.see(ordered[0])

    def _ge_bone_down(self):
        sel = list(self.ge_bones_tv.selection())
        if not sel: return
        children = list(self.ge_bones_tv.get_children())
        # Sort by descending position so we move the bottommost item first
        ordered = sorted(sel, key=lambda iid: children.index(iid), reverse=True)
        if children.index(ordered[0]) >= len(children) - 1: return   # bottommost already last
        for iid in ordered:
            children = list(self.ge_bones_tv.get_children())
            cur = children.index(iid)
            if cur < len(children) - 1:
                self.ge_bones_tv.move(iid, '', cur + 1)
        self._renumber_ge_bones()
        # _ge_save keeps _ge_saving=True until after_idle (same as _ge_bone_up).
        # Restore selection synchronously while the iids are still valid.
        self._ge_save(silent=True)
        self.ge_bones_tv.selection_set(*sel)
        self.ge_bones_tv.see(ordered[0])

    def _ge_edit_bone(self):
        sel = self.ge_bones_tv.selection()
        if not sel: return
        iid = sel[0]
        v    = self.ge_bones_tv.item(iid)['values']
        bn_a = v[1] if len(v) > 1 else ""
        bn_b = v[2] if len(v) > 2 else ""
        bn_c = v[3] if len(v) > 3 else ""
        bn_d = v[4] if len(v) > 4 else ""
        bn_e = v[5] if len(v) > 5 else ""
        bn_f = v[6] if len(v) > 6 else ""
        bc   = v[7] if len(v) > 7 else ""
        pool = self.config.get("bone_pool", [])
        dlg  = GroupBoneEditDialog(self.root, bone_pool=pool,
                                    bone_a=bn_a, bone_b=bn_b,
                                    bone_c=bn_c, bone_d=bn_d, bone_e=bn_e,
                                    bone_f=bn_f, custom=bc)
        if not dlg.result: return
        nb_a, nb_b, nb_c, nb_d, nb_e, nb_f, nc = dlg.result
        idx = self.ge_bones_tv.index(iid)
        prefix = self.ge['prefix'].get()
        try:
            start = int(self.ge['start'].get())
        except ValueError:
            start = 1
        fmt = self.ge['fmt'].get() or "02d"
        try:
            hp = nc if nc else f"{prefix}_{format(start + idx, fmt)}"
        except Exception:
            hp = nc if nc else f"{prefix}_{start + idx}"
        has_extra = any([nb_b, nb_c, nb_d, nb_e, nb_f])
        tag = 'dual' if has_extra else 'single'
        self.ge_bones_tv.item(iid, values=(idx+1, nb_a, nb_b, nb_c, nb_d, nb_e, nb_f, nc, hp),
                               tags=(tag,))
        self._ge_save(silent=True)

    # ─────────────────────────────────────────────
    # Template Browser
    # ─────────────────────────────────────────────

    def _tpl_browser_refresh(self):
        filt = self.sv_tpl_filter.get().lower()
        rows = []
        for name, tpl in self.template_registry.items():
            inherits = self.raw_registry.get(name, {}).get("inherits_from", "") or "—"
            if filt and filt not in name.lower() and filt not in inherits.lower():
                continue
            n_fields_res = len(tpl.get("fields", []))
            tag = 'child' if inherits and inherits != "—" else 'base'
            rows.append((name, inherits, n_fields_res, tag))

        # Sort by active column
        col = self._tpl_sort_col
        rev = self._tpl_sort_rev
        if col == 'fields':
            rows.sort(key=lambda r: r[2], reverse=rev)
        elif col == 'inherits':
            rows.sort(key=lambda r: (r[1] == '—', r[1].lower()), reverse=rev)
        else:
            rows.sort(key=lambda r: r[0].lower(), reverse=rev)

        self.tpl_tv.delete(*self.tpl_tv.get_children())
        for name, inherits, n_fields_res, tag in rows:
            self.tpl_tv.insert('', 'end', iid=name,
                                values=(name, inherits, f"{n_fields_res}"),
                                tags=(tag,))
        # Update heading arrows to show active sort
        for c in ('name', 'inherits', 'fields'):
            label_map = {'name': 'Template Name', 'inherits': 'Inherits From', 'fields': 'Fields'}
            arrow = (' ▲' if not rev else ' ▼') if c == col else ''
            self.tpl_tv.heading(c, text=label_map[c] + arrow)
        n = len(self.tpl_tv.get_children())
        self.sv_tpl_count.set(f"{n} template{'s' if n != 1 else ''}")

    def _tpl_sort(self, col: str):
        """Toggle sort on the given column and refresh the template browser."""
        if self._tpl_sort_col == col:
            self._tpl_sort_rev = not self._tpl_sort_rev
        else:
            self._tpl_sort_col = col
            self._tpl_sort_rev = False
        self._tpl_browser_refresh()

    def _on_tpl_selected(self, _=None):
        sel = self.tpl_tv.selection()
        if not sel:
            return
        name = sel[0]
        show_resolved = self.sv_tpl_resolved.get()
        tpl  = self.template_registry.get(name, {})
        raw  = self.raw_registry.get(name, {})

        inherits = raw.get("inherits_from", "") or "—"
        pc       = tpl.get("parent_comment", "") or "—"

        # Build inheritance chain
        chain_parts = []
        current = name
        visited = set()
        while current and current not in visited:
            chain_parts.append(current)
            visited.add(current)
            current = self.raw_registry.get(current, {}).get("inherits_from", "")
        chain = " → ".join(reversed(chain_parts)) if len(chain_parts) > 1 else "—"

        n_own   = len(raw.get("fields", []))
        n_total = len(tpl.get("fields", []))

        self.sv_td['name'      ].set(name)
        self.sv_td['inherits'  ].set(inherits)
        self.sv_td['pc'        ].set(pc)
        self.sv_td['chain'     ].set(chain)
        self.sv_td['fields_own'].set(f"{n_own} own  /  {n_total} total (resolved)")

        # Fields table
        fields_to_show = tpl.get("fields", []) if show_resolved else raw.get("fields", [])
        raw_field_tags  = {(f.get("tag",""), str(f.get("value",""))) for f in raw.get("fields", [])}

        self.fields_tv.delete(*self.fields_tv.get_children())
        for field in fields_to_show:
            ftype = field.get("_type", "element")

            if ftype == "blank":
                self.fields_tv.insert('', 'end', values=("", "blank", "", "", "", ""), tags=('blank',))
                continue
            if ftype in ("section_comment", "inline_comment"):
                text = field.get("text", "")
                self.fields_tv.insert('', 'end',
                    values=("", ftype.replace("_"," "), "", text, "", ""),
                    tags=('comment',))
                continue

            tag   = field.get("tag", "")
            value = str(field.get("value", ""))
            empty = "empty_tag" if field.get("empty_tag") else ""

            is_bone   = "{bone}"  in value or "{bone_a}" in value
            is_bone_b = "{bone_b}" in value
            is_bone_c = "{bone_c}" in value
            is_bone_d = "{bone_d}" in value
            is_bone_e = "{bone_e}" in value
            is_bone_f = "{bone_f}" in value
            is_any_bone = is_bone or is_bone_b or is_bone_c or is_bone_d or is_bone_e or is_bone_f
            is_model  = "{model_idx}"  in value
            is_damage = "{damage_idx}" in value

            note_parts = []
            if is_bone:   note_parts.append("→ bone_a")
            if is_bone_b: note_parts.append("→ bone_b")
            if is_bone_c: note_parts.append("→ bone_c")
            if is_bone_d: note_parts.append("→ bone_d")
            if is_bone_e: note_parts.append("→ bone_e")
            if is_bone_f: note_parts.append("→ bone_f")
            if is_model:  note_parts.append("→ model_idx")
            if is_damage: note_parts.append("→ dmg_idx")
            note = "  ".join(p for p in note_parts if p)

            # Is this field inherited (not in raw)?
            key = (tag, value)
            is_inherited = show_resolved and key not in raw_field_tags and inherits != "—"
            source = "↑ parent" if is_inherited else "own"

            if   is_any_bone:  row_tag = 'bone_ref'
            elif is_model:     row_tag = 'model_ref'
            elif is_damage:    row_tag = 'model_ref'   # reuse peach colour
            elif is_inherited: row_tag = 'inherited'
            else:              row_tag = 'normal'

            self.fields_tv.insert('', 'end',
                values=(source, "element", tag, value, note or empty),
                tags=(row_tag,))

    def _browser_open_in_editor(self):
        """Open the selected template's source JSON file in the Template Editor.

        If a template is selected in the browser and its source file is known,
        that file is opened directly.  Otherwise a file-picker dialog is shown.
        """
        # Try to resolve the source file from the currently selected template
        sel = self.tpl_tv.selection() if hasattr(self, 'tpl_tv') else ()
        if sel:
            name = sel[0]
            src  = self.raw_registry.get(name, {}).get("_source_file", "")
            if src and Path(src).is_file():
                self._te_load_file(Path(src))
                self.notebook.select(3)
                # After the file loads, highlight the specific template in the editor list
                self.root.after(80, lambda n=name: self._te_highlight_template(n))
                return

        # Fallback: ask the user to pick a file
        initial = _default_templates()
        path = filedialog.askopenfilename(
            title="Open Template File in Editor",
            initialdir=initial,
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if path:
            self._te_load_file(Path(path))
            self.notebook.select(2)

    def _te_highlight_template(self, name: str):
        """Select *name* in the Template Editor's template list if it is present."""
        children = self.te_tpl_tv.get_children()
        for iid in children:
            if self.te_tpl_tv.item(iid)['values'][0] == name:
                self.te_tpl_tv.selection_set(iid)
                self.te_tpl_tv.see(iid)
                self._te_on_tpl_select()
                return

    def _comp_browser_open_in_editor(self):
        """Open the selected component's source JSON file in the Template Editor.

        If a component is selected in the browser and its source file is known,
        that file is opened directly.  Otherwise a file-picker dialog is shown.
        """
        sel = self.comp_tv.selection() if hasattr(self, 'comp_tv') else ()
        if sel:
            name = sel[0]
            src  = self.raw_comp_registry.get(name, {}).get("_source_file", "")
            if src and Path(src).is_file():
                self._te_load_file(Path(src))
                self.notebook.select(3)
                self.root.after(80, lambda n=name: self._te_highlight_template(n))
                return

        # Fallback: ask the user to pick a file
        initial = _default_components()
        path = filedialog.askopenfilename(
            title="Open Component File in Editor",
            initialdir=initial,
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if path:
            self._te_load_file(Path(path))
            self.notebook.select(2)

    # ─────────────────────────────────────────────
    # Component Browser
    # ─────────────────────────────────────────────

    def _comp_browser_refresh(self):
        """Populate the component list treeview from the loaded component registry."""
        if not hasattr(self, 'comp_tv'):
            return
        filt = self.sv_comp_filter.get().lower() if hasattr(self, 'sv_comp_filter') else ""
        rows = []
        for name, comp in self.component_registry.items():
            inherits = self.raw_comp_registry.get(name, {}).get("inherits_from", "") or "—"
            if filt and filt not in name.lower() and filt not in inherits.lower():
                continue
            n_fields_res = len(comp.get("fields", []))
            tag = 'child' if inherits and inherits != "—" else 'base'
            rows.append((name, inherits, n_fields_res, tag))

        col = self._comp_sort_col
        rev = self._comp_sort_rev
        if col == 'fields':
            rows.sort(key=lambda r: r[2], reverse=rev)
        elif col == 'inherits':
            rows.sort(key=lambda r: (r[1] == '—', r[1].lower()), reverse=rev)
        else:
            rows.sort(key=lambda r: r[0].lower(), reverse=rev)

        self.comp_tv.delete(*self.comp_tv.get_children())
        for name, inherits, n_fields_res, tag in rows:
            self.comp_tv.insert('', 'end', iid=name,
                                values=(name, inherits, f"{n_fields_res}"),
                                tags=(tag,))
        # Update heading arrows
        for c in ('name', 'inherits', 'fields'):
            label_map = {'name': 'Component Name', 'inherits': 'Inherits From', 'fields': 'Fields'}
            arrow = (' ▲' if not rev else ' ▼') if c == col else ''
            self.comp_tv.heading(c, text=label_map[c] + arrow)
        n = len(self.comp_tv.get_children())
        self.sv_comp_browser_count.set(f"{n} component{'s' if n != 1 else ''}")

    def _comp_sort(self, col: str):
        """Toggle sort on the given column and refresh the component browser."""
        if self._comp_sort_col == col:
            self._comp_sort_rev = not self._comp_sort_rev
        else:
            self._comp_sort_col = col
            self._comp_sort_rev = False
        self._comp_browser_refresh()

    def _on_comp_selected(self, _=None):
        """Populate the detail pane when a component is selected in the browser."""
        if not hasattr(self, 'comp_tv'):
            return
        sel = self.comp_tv.selection()
        if not sel:
            return
        name          = sel[0]
        show_resolved = self.sv_comp_resolved.get()
        comp          = self.component_registry.get(name, {})
        raw           = self.raw_comp_registry.get(name, {})

        inherits = raw.get("inherits_from", "") or "—"
        pc       = comp.get("parent_comment", "") or "—"

        # Build inheritance chain
        chain_parts = []
        current     = name
        visited     = set()
        while current and current not in visited:
            chain_parts.append(current)
            visited.add(current)
            current = self.raw_comp_registry.get(current, {}).get("inherits_from", "")
        chain = " → ".join(reversed(chain_parts)) if len(chain_parts) > 1 else "—"

        n_own   = len(raw.get("fields",  []))
        n_total = len(comp.get("fields", []))

        self.sv_cd['name'      ].set(name)
        self.sv_cd['inherits'  ].set(inherits)
        self.sv_cd['pc'        ].set(pc)
        self.sv_cd['chain'     ].set(chain)
        self.sv_cd['fields_own'].set(f"{n_own} own  /  {n_total} total (resolved)")

        fields_to_show = comp.get("fields", []) if show_resolved else raw.get("fields", [])
        raw_field_tags = {(f.get("tag", ""), str(f.get("value", "")))
                         for f in raw.get("fields", [])}

        self.comp_fields_tv.delete(*self.comp_fields_tv.get_children())
        for field in fields_to_show:
            ftype = field.get("_type", "element")

            if ftype == "blank":
                self.comp_fields_tv.insert('', 'end',
                    values=("", "blank", "", "", "", ""), tags=('blank',))
                continue
            if ftype in ("section_comment", "inline_comment"):
                text = field.get("text", "")
                self.comp_fields_tv.insert('', 'end',
                    values=("", ftype.replace("_", " "), "", text, "", ""),
                    tags=('comment',))
                continue

            tag   = field.get("tag", "")
            value = str(field.get("value", ""))
            empty = "empty_tag" if field.get("empty_tag") else ""

            is_bone   = "{bone}"  in value or "{bone_a}" in value
            is_bone_b = "{bone_b}" in value
            is_bone_c = "{bone_c}" in value
            is_bone_d = "{bone_d}" in value
            is_bone_e = "{bone_e}" in value
            is_bone_f = "{bone_f}" in value
            is_any_bone = is_bone or is_bone_b or is_bone_c or is_bone_d or is_bone_e or is_bone_f
            is_model  = "{model_idx}"  in value
            is_damage = "{damage_idx}" in value

            note_parts = []
            if is_bone:   note_parts.append("→ bone_a")
            if is_bone_b: note_parts.append("→ bone_b")
            if is_bone_c: note_parts.append("→ bone_c")
            if is_bone_d: note_parts.append("→ bone_d")
            if is_bone_e: note_parts.append("→ bone_e")
            if is_bone_f: note_parts.append("→ bone_f")
            if is_model:  note_parts.append("→ model_idx")
            if is_damage: note_parts.append("→ dmg_idx")
            note = "  ".join(note_parts)

            key          = (tag, value)
            is_inherited = show_resolved and key not in raw_field_tags and inherits != "—"
            source       = "↑ parent" if is_inherited else "own"

            if   is_any_bone:  row_tag = 'bone_ref'
            elif is_model:     row_tag = 'model_ref'
            elif is_damage:    row_tag = 'model_ref'
            elif is_inherited: row_tag = 'inherited'
            else:              row_tag = 'normal'

            self.comp_fields_tv.insert('', 'end',
                values=(source, "element", tag, value, note or empty),
                tags=(row_tag,))

    # ─────────────────────────────────────────────
    # Group Editor — Field Overrides panel
    # ─────────────────────────────────────────────

    # ── Helpers shared with Template Editor field logic ───────────────────

    def _ge_ov_field_to_row(self, field: dict) -> tuple:
        ftype = field.get("_type", "element")
        if ftype == "blank":
            return ("", "blank", "", "", "")
        if ftype in ("section_comment", "inline_comment"):
            label = "section cmt" if ftype == "section_comment" else "inline cmt"
            return ("", label, field.get("text", ""), "", "")
        tag   = field.get("tag", "")
        value = str(field.get("value", ""))
        flags = "empty_tag" if field.get("empty_tag") else ""
        return ("", "element", tag, value, flags)

    def _ge_ov_colour_tag(self, field: dict) -> str:
        ftype = field.get("_type", "element")
        if ftype != "element":
            return ftype
        val = str(field.get("value", ""))
        if "{bone" in val:
            return 'bone_ref'
        if "{model_idx}" in val or "{damage_idx}" in val:
            return 'model_ref'
        return 'element'

    def _ge_ov_next_iid(self) -> str:
        existing = set(self.ge_ov_tv.get_children())
        n = 0
        while f"ov{n}" in existing:
            n += 1
        return f"ov{n}"

    def _ge_ov_insert_row(self, iid: str, field: dict, position: str = 'end', after_iid: str = None):
        self._ge_ov_field_store[iid] = field
        row   = self._ge_ov_field_to_row(field)
        ctag  = self._ge_ov_colour_tag(field)
        if after_iid is not None:
            idx = self.ge_ov_tv.index(after_iid)
            self.ge_ov_tv.insert('', idx + 1, iid=iid, values=row, tags=(ctag,))
        else:
            self.ge_ov_tv.insert('', position, iid=iid, values=row, tags=(ctag,))

    def _ge_ov_renumber(self):
        for i, iid in enumerate(self.ge_ov_tv.get_children()):
            vals = list(self.ge_ov_tv.item(iid)['values'])
            if vals:
                vals[0] = i + 1
                self.ge_ov_tv.item(iid, values=vals)

    def _ge_ov_update_count(self):
        self._ge_ov_renumber()
        n = len(self.ge_ov_tv.get_children())
        self.sv_ge_ov_count.set(f"{n} override{'s' if n != 1 else ''}")

    def _ge_ov_fields_from_tv(self) -> list:
        return [self._ge_ov_field_store.get(iid, {"_type": "blank"})
                for iid in self.ge_ov_tv.get_children()]

    # ── Populate TV from saved data ───────────────────────────────────────

    def _ge_ov_refresh(self, fields: list):
        """Load a list of field dicts into the override treeview."""
        self.ge_ov_tv.delete(*self.ge_ov_tv.get_children())
        self._ge_ov_field_store.clear()
        for i, field in enumerate(fields):
            self._ge_ov_insert_row(f"ov{i}", field, position='end')
        self._ge_ov_update_count()
        self._ge_ov_clear_editor()

    # ── Load template fields into override TV ─────────────────────────────

    def _ge_ov_load_from_template(self):
        """Populate the override TV with the fully-resolved fields of the current template + components."""
        gi = self._editing_group_idx
        if gi is None:
            messagebox.showinfo("No Group", "No group selected.", parent=self.root)
            return
        g        = self.config.get("groups", [])[gi]
        tpl_name = g.get("template", "")
        tpl      = self.template_registry.get(tpl_name)
        if tpl is None:
            messagebox.showwarning("Template Not Found",
                                   f"Template '{tpl_name}' is not loaded.", parent=self.root)
            return

        # Apply components to get the fully resolved field list
        comp_names = g.get("components", [])
        if comp_names and self.component_registry:
            from hp_generator import apply_components, _merge_fields
            fields = apply_components(tpl.get("fields", []), comp_names, self.component_registry)
        else:
            fields = list(tpl.get("fields", []))

        existing = self._ge_ov_fields_from_tv()
        if existing:
            if not messagebox.askyesno("Replace Overrides",
                                       f"This will replace {len(existing)} existing override(s) "
                                       f"with {len(fields)} field(s) from '{tpl_name}'.\nContinue?",
                                       parent=self.root):
                return

        import copy as _copy
        self._ge_ov_refresh([_copy.deepcopy(f) for f in fields])
        self._ge_autosave()
        self._log(f"Overrides: loaded {len(fields)} field(s) from '{tpl_name}'.\n", 'info')
        # Switch to the Field Overrides tab so the user can see the result
        if hasattr(self, '_ge_right_nb'):
            self._ge_right_nb.select(2)

    # ── Clear all ─────────────────────────────────────────────────────────

    def _ge_ov_clear_all(self):
        if not self.ge_ov_tv.get_children():
            return
        if not messagebox.askyesno("Clear All Overrides",
                                   f"Remove all {len(self.ge_ov_tv.get_children())} override field(s)?",
                                   parent=self.root):
            return
        self.ge_ov_tv.delete(*self.ge_ov_tv.get_children())
        self._ge_ov_field_store.clear()
        self._ge_ov_update_count()
        self._ge_autosave()

    # ── Inline editor population / clearing ───────────────────────────────

    def _ge_ov_clear_editor(self):
        self._loading = True
        try:
            self.ge_ov_ed['ftype'].set('element')
            self.ge_ov_ed['tag'].set('')
            self.ge_ov_ed['value'].set('')
            self.ge_ov_ed['empty_tag'].set(False)
        finally:
            self._loading = False

    def _ge_ov_populate_editor(self, field: dict):
        self._loading = True
        try:
            ftype = field.get("_type", "element")
            self.ge_ov_ed['ftype'].set(ftype)
            if ftype == "element":
                self.ge_ov_ed['tag'].set(field.get("tag", ""))
                self.ge_ov_ed['value'].set(str(field.get("value", "")))
                self.ge_ov_ed['empty_tag'].set(bool(field.get("empty_tag", False)))
            else:
                self.ge_ov_ed['tag'].set(field.get("text", ""))
                self.ge_ov_ed['value'].set("")
                self.ge_ov_ed['empty_tag'].set(False)
        finally:
            self._loading = False

    # ── TV event handlers ─────────────────────────────────────────────────

    def _ge_ov_on_select(self, _=None):
        sel = self.ge_ov_tv.selection()
        if not sel or len(sel) > 1:
            return
        field = self._ge_ov_field_store.get(sel[0], {})
        self._ge_ov_populate_editor(field)

    _GE_OV_COL_MAP = {'#3': 'tag', '#4': 'value'}

    def _ge_ov_double_click(self, event):
        col = self.ge_ov_tv.identify_column(event.x)
        if col in self._GE_OV_COL_MAP:
            iid = self.ge_ov_tv.identify_row(event.y)
            if iid:
                self.ge_ov_tv.selection_set(iid)
            self.root.after_idle(lambda c=col: self._ge_ov_inline_edit(c))
        else:
            self._ge_ov_edit()

    def _ge_ov_inline_edit(self, col_id: str):
        sel = self.ge_ov_tv.selection()
        if not sel:
            return
        iid       = sel[0]
        field_key = self._GE_OV_COL_MAP.get(col_id)
        if not field_key:
            return
        field = self._ge_ov_field_store.get(iid, {})
        ftype = field.get("_type", "element")
        if ftype == "blank":
            return
        if ftype in ("section_comment", "inline_comment") and field_key != 'tag':
            return

        if field_key == 'tag':
            current = field.get("tag", "") if ftype == "element" else field.get("text", "")
        elif field_key == 'value':
            current = str(field.get("value", ""))
        else:
            current = "; ".join(f'{k}={v}' for k, v in field.get("attrs", {}).items())

        bbox = self.ge_ov_tv.bbox(iid, col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        var   = tk.StringVar(value=current)
        entry = ttk.Entry(self.ge_ov_tv, textvariable=var)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set(); entry.select_range(0, 'end')

        if hasattr(self, '_ge_ov_inline_entry') and self._ge_ov_inline_entry:
            try:
                self._ge_ov_inline_entry.destroy()
            except Exception:
                pass
        self._ge_ov_inline_entry = entry

        def _commit(event=None):
            if not entry.winfo_exists():
                return
            nv = var.get()
            entry.place_forget(); entry.destroy()
            self._ge_ov_inline_entry = None
            self._ge_ov_apply_inline_cell(iid, field_key, nv)
            return 'break'

        def _cancel(event=None):
            if not entry.winfo_exists():
                return
            entry.place_forget(); entry.destroy()
            self._ge_ov_inline_entry = None
            return 'break'

        def _tab(event=None):
            _commit()
            next_col = {'#3': '#4', '#4': '#5', '#5': '#3'}.get(col_id, '#3')
            self.root.after_idle(lambda c=next_col: self._ge_ov_inline_edit(c))
            return 'break'

        entry.bind('<Return>',   _commit)
        entry.bind('<KP_Enter>', _commit)
        entry.bind('<Escape>',   _cancel)
        entry.bind('<Tab>',      _tab)
        entry.bind('<FocusOut>', _commit)

    def _ge_ov_apply_inline_cell(self, iid: str, field_key: str, new_val: str):
        field = dict(self._ge_ov_field_store.get(iid, {}))
        ftype = field.get("_type", "element")
        if field_key == 'tag':
            if ftype == "element":
                field["tag"] = new_val.strip()
            else:
                field["text"] = new_val
        elif field_key == 'value':
            field["value"] = new_val

        self._ge_ov_field_store[iid] = field
        self.ge_ov_tv.item(iid, values=self._ge_ov_field_to_row(field),
                            tags=(self._ge_ov_colour_tag(field),))
        self._ge_ov_renumber()
        # Sync lower editor
        if self.ge_ov_tv.selection() and self.ge_ov_tv.selection()[0] == iid:
            self._loading = True
            try:
                if field_key == 'tag':
                    self.ge_ov_ed['tag'].set(
                        field.get("tag", "") if ftype == "element" else field.get("text", ""))
                elif field_key == 'value':
                    self.ge_ov_ed['value'].set(str(field.get("value", "")))
            finally:
                self._loading = False
        self._ge_autosave()
        self._ge_ov_update_count()

    # ── Field editor apply / insert ───────────────────────────────────────

    def _ge_ov_field_from_editor(self, silent=False) -> dict | None:
        ftype = self.ge_ov_ed['ftype'].get()
        if ftype == 'blank':
            return {"_type": "blank"}
        if ftype in ('section_comment', 'inline_comment'):
            return {"_type": ftype, "text": self.ge_ov_ed['tag'].get().strip()}
        tag = self.ge_ov_ed['tag'].get().strip()
        if not tag:
            if not silent:
                messagebox.showerror("Required", "Tag name cannot be empty.", parent=self.root)
            return None
        value     = self.ge_ov_ed['value'].get()
        empty_tag = bool(self.ge_ov_ed['empty_tag'].get())
        field: dict = {"tag": tag, "value": value}
        if empty_tag:
            field["empty_tag"] = True
        return field

    def _ge_ov_apply_field(self, silent=False):
        sel = self.ge_ov_tv.selection()
        if not sel:
            return
        field = self._ge_ov_field_from_editor(silent=silent)
        if field is None:
            return
        iid = sel[0]
        self._ge_ov_field_store[iid] = field
        self.ge_ov_tv.item(iid, values=self._ge_ov_field_to_row(field),
                            tags=(self._ge_ov_colour_tag(field),))
        self._ge_autosave()
        self._ge_ov_update_count()

    def _ge_ov_insert_below(self):
        field = self._ge_ov_field_from_editor()
        if field is None:
            return
        new_iid = self._ge_ov_next_iid()
        sel     = self.ge_ov_tv.selection()
        after   = sel[-1] if sel else None
        self._ge_ov_insert_row(new_iid, field, after_iid=after)
        self.ge_ov_tv.selection_set(new_iid)
        self.ge_ov_tv.see(new_iid)
        self._ge_ov_update_count()
        self._ge_autosave()

    # ── Add typed rows ────────────────────────────────────────────────────

    def _ge_ov_add_element(self):
        self._ge_ov_insert_blank('element')

    def _ge_ov_add_section_comment(self):
        self._ge_ov_insert_blank('section_comment')

    def _ge_ov_add_inline_comment(self):
        self._ge_ov_insert_blank('inline_comment')

    def _ge_ov_add_blank(self):
        self._ge_ov_insert_blank('blank')

    def _ge_ov_insert_blank(self, ftype: str):
        field = ({"_type": "blank"} if ftype == "blank"
                 else {"_type": ftype, "text": ""} if ftype in ("section_comment", "inline_comment")
                 else {"tag": "", "value": ""})
        new_iid = self._ge_ov_next_iid()
        sel     = self.ge_ov_tv.selection()
        after   = sel[-1] if sel else None
        self._ge_ov_insert_row(new_iid, field, after_iid=after)
        self.ge_ov_tv.selection_set(new_iid)
        self.ge_ov_tv.see(new_iid)
        self._ge_ov_populate_editor(field)
        self._ge_ov_update_count()
        self._ge_autosave()

    # ── CRUD operations ───────────────────────────────────────────────────

    def _ge_ov_edit(self):
        sel = self.ge_ov_tv.selection()
        if not sel:
            return
        field = self._ge_ov_field_store.get(sel[0], {})
        self._ge_ov_populate_editor(field)

    def _ge_ov_del(self):
        sels = self.ge_ov_tv.selection()
        if not sels:
            return
        for iid in sels:
            self.ge_ov_tv.delete(iid)
            self._ge_ov_field_store.pop(iid, None)
        self._ge_ov_update_count()
        self._ge_autosave()

    def _ge_ov_dup(self):
        import copy as _copy
        sels = self.ge_ov_tv.selection()
        if not sels:
            return
        children = list(self.ge_ov_tv.get_children())
        ordered  = sorted(sels, key=lambda iid: children.index(iid))
        last_iid = ordered[-1]
        insert_idx = children.index(last_iid)
        new_iids = []
        for j, iid in enumerate(ordered):
            field   = _copy.deepcopy(self._ge_ov_field_store.get(iid, {}))
            new_iid = self._ge_ov_next_iid()
            self._ge_ov_field_store[new_iid] = field
            row   = self._ge_ov_field_to_row(field)
            ctag  = self._ge_ov_colour_tag(field)
            self.ge_ov_tv.insert('', insert_idx + 1 + j, iid=new_iid, values=row, tags=(ctag,))
            new_iids.append(new_iid)
        self.ge_ov_tv.selection_set(*new_iids)
        if new_iids:
            self.ge_ov_tv.see(new_iids[-1])
        self._ge_ov_update_count()
        self._ge_autosave()

    def _ge_ov_up(self):
        sels = list(self.ge_ov_tv.selection())
        if not sels:
            return
        children = list(self.ge_ov_tv.get_children())
        ordered  = sorted(sels, key=lambda iid: children.index(iid))
        if children.index(ordered[0]) == 0:
            return
        for iid in ordered:
            children = list(self.ge_ov_tv.get_children())
            cur = children.index(iid)
            if cur > 0:
                self.ge_ov_tv.move(iid, '', cur - 1)
        self.ge_ov_tv.selection_set(*sels)
        self.ge_ov_tv.see(ordered[0])
        self._ge_ov_renumber()
        self._ge_autosave()

    def _ge_ov_down(self):
        sels = list(self.ge_ov_tv.selection())
        if not sels:
            return
        children = list(self.ge_ov_tv.get_children())
        ordered  = sorted(sels, key=lambda iid: children.index(iid), reverse=True)
        if children.index(ordered[0]) >= len(children) - 1:
            return
        for iid in ordered:
            children = list(self.ge_ov_tv.get_children())
            cur = children.index(iid)
            if cur < len(children) - 1:
                self.ge_ov_tv.move(iid, '', cur + 1)
        self.ge_ov_tv.selection_set(*sels)
        self.ge_ov_tv.see(ordered[-1])
        self._ge_ov_renumber()
        self._ge_autosave()

    def _ge_ov_preview_component(self):
        pass  # placeholder — kept for structural parity

    def _ge_preview_component(self):
        """Navigate to the Component Browser and highlight the selected component."""
        sel = self.ge_comp_tv.selection()
        if not sel:
            return
        v    = self.ge_comp_tv.item(sel[0])['values']
        name = str(v[1]).lstrip("⚠ ").strip() if v else ""
        if not name:
            return
        self.notebook.select(2)   # switch to Component Browser tab
        # Give the tab a moment to render before trying to select
        self.root.after(50, lambda n=name: self._comp_browser_highlight(n))

    def _comp_browser_highlight(self, name: str):
        """Select and scroll to *name* in the component browser list."""
        if not hasattr(self, 'comp_tv'):
            return
        children = self.comp_tv.get_children()
        if name in children:
            self.comp_tv.selection_set(name)
            self.comp_tv.see(name)
            self._on_comp_selected()
        else:
            # Component not visible — may be filtered out; clear filter and retry
            self.sv_comp_filter.set("")
            self.root.after(30, lambda n=name: (
                self.comp_tv.selection_set(n),
                self.comp_tv.see(n),
                self._on_comp_selected()
            ) if n in self.comp_tv.get_children() else None)

    # ─────────────────────────────────────────────
    # Generator Actions
    # ─────────────────────────────────────────────

    def _pre_generate_check(self) -> bool:
        """Validate config and templates before running generator. Returns True if OK."""
        if not _GEN_AVAILABLE:
            messagebox.showerror("Generator Not Found",
                                  "hp_generator.py could not be imported.\n"
                                  "Make sure it is in the same directory as this GUI.")
            return False
        if not self.config.get("groups"):
            messagebox.showwarning("No Groups", "The config has no groups — nothing to generate.")
            return False
        if not self.template_registry:
            messagebox.showwarning("No Templates",
                                    "No templates are loaded. Set the templates path and reload.")
            return False
        return True

    def _make_temp_config(self) -> str:
        """
        Write a temp JSON config with all paths fully resolved to absolute form.
        Returns the temp file path (caller must delete it).
        The generator always receives absolute paths so it works regardless of
        the current working directory or whether the config has been saved yet.
        """
        import tempfile
        cfg_copy = copy.deepcopy(self.config)
        # Use the saved config file's location as the resolution base so that
        # relative paths stored in the config (e.g. "Templates", "Components")
        # resolve correctly.  Never use os.getcwd() — it is unreliable inside
        # a frozen .exe.
        base = self.config_path if self.config_path else None

        # ── Templates path ───────────────────────────────────────────────
        tpl = cfg_copy.get("templates", "")
        cfg_copy["templates"] = (
            resolve_path(base, tpl) if tpl
            else str(Path(_script_dir()) / "Templates")
        )

        # ── Components path ──────────────────────────────────────────────
        # THIS was the missing piece: without this, the generator received
        # the raw relative string (e.g. "Components") and failed to find it.
        comp = cfg_copy.get("components", "")
        if comp:
            cfg_copy["components"] = resolve_path(base, comp)

        # ── Output file ──────────────────────────────────────────────────
        out = cfg_copy.get("output_file", "")
        cfg_copy["output_file"] = (
            resolve_path(base, out) if out
            else str(Path(_script_dir()) / "Hardpoints" / f"Hardpoints_{cfg_copy.get('ship_name','Ship')}.xml")
        )

        # ── Filter lists (excludes / includes) ───────────────────────────
        for key in ("template_excludes", "template_includes",
                    "component_excludes", "component_includes"):
            cfg_copy[key] = [resolve_path(base, p)
                            for p in cfg_copy.get(key, []) if p]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                        delete=False, encoding='utf-8') as tf:
            json.dump(cfg_copy, tf, indent=2)
            return tf.name

    def _do_generate(self):
        if not self._pre_generate_check():
            return
        self._sync_cfg_from_ui()

        # Validate groups
        warnings = []
        for i, g in enumerate(self.config.get("groups", [])):
            tpl = g.get("template", "")
            if tpl not in self.template_registry:
                warnings.append(f"Group [{i+1}]: template '{tpl}' not found")
            if not g.get("bones"):
                warnings.append(f"Group [{i+1}]: no bones assigned")

        if warnings:
            msg = "Warnings found:\n\n" + "\n".join(f"• {w}" for w in warnings)
            msg += "\n\nContinue anyway?"
            if not messagebox.askyesno("Generation Warnings", msg):
                return

        tmp_path = self._make_temp_config()

        self._log("─" * 60 + "\n", 'dim')
        self._log("⚡ Generating XML…\n", 'header')
        self.sv_status.set("Generating…")

        def run():
            success, out, err = run_generator(gen.generate, tmp_path)
            Path(tmp_path).unlink(missing_ok=True)
            self.root.after(0, lambda: self._on_generate_done(success, out, err))

        threading.Thread(target=run, daemon=True).start()

    def _on_generate_done(self, success, out, err):
        self.sv_status.set("Ready")
        if out.strip():
            self._log(out, 'success' if success else 'warn')
        if err.strip():
            self._log(err, 'error')
        if success:
            self._log("✓ Generation complete.\n", 'success')
        else:
            self._log("✗ Generation failed — see errors above.\n", 'error')
            messagebox.showerror("Generation Failed",
                                  "XML generation encountered errors.\nSee the Output Log for details.")

    def _do_list(self):
        if not self._pre_generate_check():
            return
        self._sync_cfg_from_ui()
        tmp_path = self._make_temp_config()

        self._log("─" * 60 + "\n", 'dim')
        self._log("📋 Listing hardpoints…\n", 'header')
        self.sv_status.set("Listing…")

        def run():
            success, out, err = run_generator(gen.generate, tmp_path, list_only=True)
            Path(tmp_path).unlink(missing_ok=True)
            self.root.after(0, lambda: _done(success, out, err))

        def _done(success, out, err):
            self.sv_status.set("Ready")
            if out.strip():
                self._log(out, 'info')
            if err.strip():
                self._log(err, 'error')

        threading.Thread(target=run, daemon=True).start()

    def _do_dump(self):
        if not self.template_registry:
            messagebox.showinfo("No Templates", "No templates loaded."); return
        dlg = DumpTemplateDialog(self.root, list(self.template_registry.keys()))
        if not dlg.result:
            return
        name = dlg.result

        self._log("─" * 60 + "\n", 'dim')
        self._log(f"🔍 Dumping template: {name}\n", 'header')

        tpl = self.template_registry.get(name, {})
        raw = self.raw_registry.get(name, {})

        self._log(f"  Name:           {name}\n", 'info')
        inherits = raw.get("inherits_from", "") or "(none)"
        self._log(f"  Inherits from:  {inherits}\n", 'info')
        self._log(f"  Parent comment: {tpl.get('parent_comment','')}\n", 'info')
        n_own   = len(raw.get("fields", []))
        n_total = len(tpl.get("fields", []))
        self._log(f"  Fields: {n_own} own / {n_total} total (resolved)\n\n", 'info')

        for field in tpl.get("fields", []):
            ftype = field.get("_type", "element")
            if ftype == "blank":
                self._log("\n", 'dim')
            elif ftype == "section_comment":
                self._log(f"  <!-- {field.get('text','')} -->\n", 'dim')
            elif ftype == "inline_comment":
                self._log(f"  <!--{field.get('text','')}-->\n", 'dim')
            else:
                tag   = field.get("tag", "?")
                value = field.get("value", "")
                attrs = field.get("attrs", {})
                empty = " [empty_tag]" if field.get("empty_tag") else ""
                attr_str = "".join(f' {k}="{v}"' for k, v in attrs.items())
                color = 'info'
                if "{bone}" in str(value):  color = 'warn'
                if "{model_idx}" in str(value): color = 'warn'
                self._log(f"  <{tag}{attr_str}>{value}</{tag}>{empty}\n", color)

        # Also show in template browser
        self.notebook.select(1)
        if name in [self.tpl_tv.item(i)['values'][0] for i in self.tpl_tv.get_children()]:
            self.tpl_tv.selection_set(name)
            self.tpl_tv.see(name)
            self._on_tpl_selected()

    # ─────────────────────────────────────────────
    # Log
    # ─────────────────────────────────────────────

    def _log(self, text: str, tag: str = 'info'):
        self.log.config(state='normal')
        self.log.insert(tk.END, text, tag)
        self.log.see(tk.END)
        self.log.config(state='disabled')
        # Count lines cheaply using the widget's line index rather than
        # reading the entire content string.
        last_line = int(self.log.index(tk.END).split('.')[0]) - 1
        self.sv_log_count.set(f"{last_line} lines")

    def _log_clear(self):
        self.log.config(state='normal')
        self.log.delete('1.0', tk.END)
        self.log.config(state='disabled')
        self.sv_log_count.set("0 lines")

    def _log_copy(self):
        content = self.log.get('1.0', tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.sv_status.set("Log copied to clipboard")
        self.root.after(2000, lambda: self.sv_status.set("Ready"))

    # ─────────────────────────────────────────────
    # Help / About
    # ─────────────────────────────────────────────

    def _show_about(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("About")
        dlg.resizable(False, False)
        dlg.configure(bg=P['bg'])
        dlg.transient(self.root)

        f = ttk.Frame(dlg, padding=24)
        f.pack()

        ttk.Label(f, text="EaW Hardpoint Generator", font=('Segoe UI', 14, 'bold'),
                  foreground=P['blue']).pack()
        ttk.Label(f, text=f"GUI Version {APP_VERSION}", font=('Segoe UI', 9),
                  foreground=P['sub0']).pack(pady=(2, 12))

        gen_status = f"hp_generator.py loaded ✓" if _GEN_AVAILABLE else "hp_generator.py NOT found ⚠"
        gen_color  = P['green'] if _GEN_AVAILABLE else P['red']
        ttk.Label(f, text=gen_status, foreground=gen_color).pack()

        alo_status = "alo_reader.py loaded ✓" if _ALO_AVAILABLE else "alo_reader.py NOT found  (ALO import disabled)"
        alo_color  = P['green'] if _ALO_AVAILABLE else P['yellow']
        ttk.Label(f, text=alo_status, foreground=alo_color).pack()

        xml_status = "hp_xml_importer.py loaded ✓" if _XML_IMPORTER_AVAILABLE else "hp_xml_importer.py NOT found  (XML import disabled)"
        xml_color  = P['green'] if _XML_IMPORTER_AVAILABLE else P['yellow']
        ttk.Label(f, text=xml_status, foreground=xml_color).pack()

        ttk.Separator(f, orient='h').pack(fill=tk.X, pady=12)

        info = (
            "Generates hardpoint XML for Star Wars: Empire at War\n"
            "from reusable JSON templates and ship config files.\n\n"
            "Keyboard shortcuts:\n"
            "  Ctrl+N  New config\n"
            "  Ctrl+O  Open config\n"
            "  Ctrl+S  Save\n"
            "  F5      Generate XML\n"
            "  F6      List hardpoints\n"
            "  F7      Dump template"
        )
        ttk.Label(f, text=info, justify='left', foreground=P['sub1']).pack(anchor='w')

        ttk.Button(f, text="Close", command=dlg.destroy, style='Accent.TButton').pack(pady=(16, 0))

    def _show_field_help(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Field Format Reference")
        dlg.geometry("680x540")
        dlg.configure(bg=P['bg'])
        dlg.transient(self.root)

        f = ttk.Frame(dlg, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        f.rowconfigure(1, weight=1)
        f.columnconfigure(0, weight=1)

        ttk.Label(f, text="Template Field Format Reference", style='Header.TLabel').grid(
            row=0, column=0, sticky='w', pady=(0, 8))

        t = tk.Text(f, bg=P['crust'], fg=P['text'], font=('Consolas', 9),
                    relief='flat', wrap='word', state='normal')
        t.grid(row=1, column=0, sticky='nsew')
        vsb = ttk.Scrollbar(f, orient='vertical', command=t.yview)
        vsb.grid(row=1, column=1, sticky='ns')
        t.configure(yscrollcommand=vsb.set)

        ref = """\
FIELD PLACEHOLDERS:
──────────────────────────────────────────────

{bone} / {bone_a}
  The primary bone for this hardpoint instance.
  Used in: Fire_Bone_A, Attachment_Bone, Collision_Mesh, etc.
  Example:  { "tag": "Fire_Bone_A", "value": "{bone_a}" }
            → <Fire_Bone_A>HP_TL_01_L</Fire_Bone_A>

{bone_b}
  The secondary fire bone. Defaults to bone_a if no explicit Bone B is set.
  Used in: Fire_Bone_B
  Example:  { "tag": "Fire_Bone_B", "value": "{bone_b}" }
            → <Fire_Bone_B>HP_TL_02_L</Fire_Bone_B>  (or same as bone_a)

{bone_c}
  Tertiary bone slot. Defaults to bone_a if Bone C is not set.
  Intended default use: Attachment_Bone override.
  Example:  { "tag": "Attachment_Bone", "value": "{bone_c}" }

{bone_d}
  Quaternary bone slot. Defaults to bone_a if Bone D is not set.
  Intended default use: Collision_Mesh override.
  Example:  { "tag": "Collision_Mesh", "value": "{bone_d}" }

{bone_e}
  Quinary bone slot. stays EMPTY in output if no Bone E is set.
                     Unlike Bone B/C/D, this does NOT fall back to bone_a.
  Intended default use: Damage_Particles bone reference.
  Example:  { "tag": "Damage_Particles", "value": "{bone_e}" }

{bone_f}
  Senary bone slot. stays EMPTY in output if no Bone F is set.
                     Unlike Bone B/C/D, this does NOT fall back to bone_a.
  Intended default use: Damage_Decal bone reference.
  Example:  { "tag": "Damage_Decal", "value": "{bone_f}" }

{model_idx}
  Auto-incrementing counter for turret model filenames. The template
  provides the full pattern; {model_idx} is replaced by a formatted number:
  Example:  { "tag": "Model_To_Attach", "value": "T_Turret_XX9_{model_idx}.ALO" }
            → <Model_To_Attach>T_Turret_XX9_01.ALO</Model_To_Attach>
            → <Model_To_Attach>T_Turret_XX9_02.ALO</Model_To_Attach>
  Counter configured via sidebar → TURRET MODELS (Start / Format).


FIELD ENTRY FORMATS:
──────────────────────────────────────────────

{ "tag": "TagName", "value": "some text" }
  → <TagName>some text</TagName>

{ "tag": "TagName", "value": "1", "attrs": {"Editor_Ignore": "Yes"} }
  → <TagName Editor_Ignore="Yes">1</TagName>

{ "tag": "TagName", "value": "", "empty_tag": true }
  → <TagName/>

{ "tag": "TagName", "value": "" }
  → <TagName></TagName>

{ "_type": "blank" }
  → (blank line in output XML)

{ "_type": "section_comment", "text": "FIRE SETTINGS:" }
  → <!-- FIRE SETTINGS:
     -->

{ "_type": "inline_comment", "text": "  <MyTag>value</MyTag>" }
  → <!--  <MyTag>value</MyTag>-->


INHERITANCE:
──────────────────────────────────────────────

A template can declare "inherits_from": "ParentName".
The child inherits all parent fields, then applies its own as overrides.

  • Child fields with the same tag REPLACE all parent entries for that tag.
  • Child fields with new tags are APPENDED after inherited fields.
  • Structural entries (_type: blank/comment) in a child are always appended.
  • parent_comment is inherited unless the child sets its own.
  • Inheritance chains (A → B → C) are supported.
  • Circular references are detected and reported as errors.


BONE ENTRY FORMATS (in a group's "bones" list):
──────────────────────────────────────────────

Plain string — all bone slots default to this bone:
  "HP_TL_01_L"

Object — with custom hardpoint name:
  { "bone": "HP_TL_01_L", "name": "HP_Custom_Name" }

Object — explicit separate fire bones (bone_b ≠ bone_a):
  { "bone_a": "HP_TL_01_L", "bone_b": "HP_TL_02_L" }

Object — all five bone slots + custom name:
  { "bone_a": "HP_TL_01_L", "bone_b": "HP_TL_02_L",
    "bone_c": "HP_DMG_01",  "bone_d": "HP_ATT_01",
    "bone_e": "HP_COL_01",  "name": "HP_Custom_Name" }

Bone slot defaults (when a slot is left blank or absent):
  bone_b → bone_a    bone_c → bone_a    bone_d → bone_a    bone_e → bone_a

Intended default uses (can be reassigned freely in any template):
  bone_a → {bone_a}  Fire_Bone_A / primary reference
  bone_b → {bone_b}  Fire_Bone_B (secondary fire position)
  bone_c → {bone_c}  Attachment_Bone override
  bone_d → {bone_d}  Collision_Mesh override
  bone_e → {bone_e}  Damage_Particles bone
  bone_f → {bone_f}  Damage_Decal bone


SHIP CONFIG KEYS:
──────────────────────────────────────────────

  ship_name         — used in trailing hardpoint-list comment in XML
  output_file       — path to write the generated XML file
  templates         — path to a .json file OR a folder (scanned recursively)
  turret_models      — { "start": 1, "format": "02d" }  (optional)
  damage_particles   — { "start": 1, "format": "02d" }  (optional)
  template_excludes  — list of paths to skip (relative to config or absolute)
  template_includes  — list of extra paths to always load (file or folder)
  component_excludes — list of component paths to skip
  component_includes — list of extra component paths to always load
  bone_pool          — list of bones (GUI-managed; not required by generator)
  groups             — list of group objects (see below)


TEMPLATE / COMPONENT FILTERS:
──────────────────────────────────────────────

The sidebar "▸ Filters" panel beneath each path field lets you fine-tune
which files are loaded from the main Templates / Components folder:

Excludes — paths to silently skip during loading.
  • Can be a sub-folder (skips every file inside it) or a single .json file.
  • Useful for disabling a whole category of templates without moving files.
  • Example: exclude "Templates/Legacy" to hide all legacy templates.

Includes — extra files or folders that are ALWAYS loaded.
  • Loaded in addition to the main path, regardless of what the main path is.
  • The main path can even be blank if you only use Includes.
  • Example: include a shared "Common_Templates.json" from another mod.
  • Deduplication: if an included file is also found under the main path it
    is only loaded once.

Interaction rules:
  • Files from Includes are loaded AFTER files from the main path.
  • An Exclude overrides an Include: if a file matches an exclude rule it is
    always skipped, even if it was explicitly included.
  • Paths are stored relative to the config file when possible, so configs
    can be moved/shared without breaking filter entries.

GUI controls:
  📁 Folder  — browse for a directory to exclude/include
  📄 File    — browse for a single .json file to exclude/include
  ✕          — remove selected entries (also: Delete key or double-click)
  ▸ Filters  — click to expand/collapse the filter panel


GROUP KEYS:
──────────────────────────────────────────────

  template       — template name (required)
  name_prefix    — prefix for auto-numbered HP names  (required)
  bones          — list of bone entries (required — see BONE ENTRY FORMATS)
  group_comment  — <!-- COMMENT --> block before this group in XML
  start_index    — starting number (default 1)
  index_format   — Python format spec (default "02d" → 01, 02, …)


IMPORTING BONES FROM .ALO MODEL FILES:
──────────────────────────────────────────────

The Bone Pool supports direct import from ALAMO engine .ALO model files.
Click  📥 From ALO…  in the Bone Pool panel.

What it does:
  • Parses the binary skeleton chunk of the .ALO file.
  • Extracts every bone name, de-duplicating repeated names.
  • Shows a filterable checklist so you can select exactly which bones
    to add (e.g. only hardpoint bones like HP_TL_01_L).

Quick-select buttons:
  HP_ only        — selects only bones whose name starts with HP_
  All excl. Root  — everything except the skeleton root node
  All             — every bone in the file
  None            — clears all selections

Colour coding in the import dialog:
  White   — new bone (will be added)
  Grey    — already in the pool (cannot be added again)
  Yellow  — suggested exclude (shadow meshes, particle emitters, etc.)

Multiple .ALO files can be selected in one import pass.  Bones that appear
in more than one file are de-duplicated automatically.

Requires: alo_reader.py in the same directory as hp_generator_GUI.py.


COMPONENTS:
──────────────────────────────────────────────

Components are optional sub-templates that override or extend the fields of
a base Template for a specific group — without requiring a separate Template.

They use the exact same JSON file format as Templates:
  Components/Component_Targetable.json
  { "templates": [ { "name": "Is_Targetable_True", "fields": [ ... ] } ] }

Components are loaded from the Components Path set in the Ship Config panel
(sidebar).  A Components folder is scanned recursively, just like Templates.

Assigning components to a group
────────────────────────────────
In the Group Editor, the "Assigned Components" panel lists components applied
to this group.  Use the combo to pick a component by name and click
"+ Add Component" to append it.  Use ↑ / ↓ to reorder and ✕ Remove to
delete.  Click "💾 Save Group" to persist the list.

How fields are merged
──────────────────────
Components are applied to the base Template's resolved fields in list order
(top → bottom), using the same tag-replacement logic as Template inheritance:

  • A component field with the same tag REPLACES the base value for that tag.
  • A component field with a new tag is APPENDED after the base fields.
  • Structural entries (blank, comment) in a component are always appended.

Conflict handling (two components change the same tag):
  The component that appears LATER in the list wins.
  Reorder components in the Group Editor to control priority.

In the generated XML the components are listed in the hardpoint comment block:
  <!-- PARENT: Turbolaser_Light_Green
  -->
  <!-- COMPONENTS:
  Is_Targetable_True
  Turret_Imperial_XX9
  -->

Ship config storage:
  "groups": [
    {
      "template":   "Turbolaser_Light_Green",
      "components": ["Is_Targetable_True", "Turret_Imperial_XX9"],
      "bones":      [...]
    }
  ]

Components also support inherits_from within their own file, so you can build
component hierarchies (e.g. Turret_Imperial_XX9_360 inherits Turret_Imperial_XX9).
"""
        t.insert('1.0', ref)
        t.config(state='disabled')
        ttk.Button(f, text="Close", command=dlg.destroy).grid(row=2, column=0, pady=8)



    # ─────────────────────────────────────────────
    # Template Editor Tab
    # ─────────────────────────────────────────────

    def _build_template_editor(self, parent):
        """Full template editor: create, edit, and save hardpoint template JSON files."""

        # ── Top toolbar ──────────────────────────────────────────────────
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, padx=6, pady=(6, 0))

        ttk.Label(top, text="TEMPLATE EDITOR", style='Header.TLabel').pack(side=tk.LEFT)

        # File path display
        self.sv_te_file = tk.StringVar(value="(no file — unsaved)")
        ttk.Label(top, textvariable=self.sv_te_file,
                  style='Small.TLabel').pack(side=tk.LEFT, padx=12)

        # Container row so right-side packing works correctly
        btn_row = ttk.Frame(top)
        btn_row.pack(fill=tk.X, padx=6, pady=2)
        
        # Action buttons — use a WrapFrame so they reflow on narrow windows
        te_btns = WrapFrame(btn_row, padx=2, pady=1)
        te_btns.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        for txt, cmd, style in [
            ("↺ Reload into Browser", self._templates_reload, 'Mauve.TButton'),
            ("💾 Save As…",   self._te_save_as,     'TButton'),
            ("💾 Save",       self._te_save,        'Accent.TButton'),
            ("📄 New File",   self._te_new_file,   'TButton'),
            ("📂 Open JSON",  self._te_open_file,  'TButton'),
            ("📥 From XML…",  self._te_import_xml, 'Warn.TButton'),
        ]:
            te_btns.add(ttk.Button(te_btns, text=txt, command=cmd, style=style))

        # Separator (use same parent for consistency)
        ttk.Separator(top, orient='horizontal').pack(fill=tk.X, padx=6, pady=4)

        # ── Main horizontal split: template list | editor ─────────────────
        hp = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        hp.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self._te_pane = hp

        # ── Left: template list ───────────────────────────────────────────
        lf = ttk.Frame(hp)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(1, weight=1)   # treeview row expands; button row always visible
        hp.add(lf, weight=1)

        lhdr = ttk.Frame(lf)
        lhdr.grid(row=0, column=0, sticky='ew', pady=(0, 2))
        ttk.Label(lhdr, text="Templates in file:", style='Small.TLabel').pack(side=tk.LEFT)
        self.sv_te_tpl_count = tk.StringVar(value="0 templates")
        ttk.Label(lhdr, textvariable=self.sv_te_tpl_count,
                  style='Small.TLabel', foreground=P['sub0']).pack(side=tk.LEFT, padx=6)

        tvf = ttk.Frame(lf)
        tvf.grid(row=1, column=0, sticky='nsew')
        tvf.rowconfigure(0, weight=1); tvf.columnconfigure(0, weight=1)

        self.te_tpl_tv = ttk.Treeview(tvf, columns=('name', 'inherits', 'nf'),
                                       show='headings', selectmode='extended')
        for col, txt, w in [('name', 'Template Name', 200),
                              ('inherits', 'Inherits From', 150),
                              ('nf', 'Fields', 50)]:
            self.te_tpl_tv.heading(col, text=txt)
            self.te_tpl_tv.column(col, width=w, minwidth=40)
        self.te_tpl_tv.tag_configure('base',  foreground=P['blue'])
        self.te_tpl_tv.tag_configure('child', foreground=P['text'])

        te_vsb = ttk.Scrollbar(tvf, orient='vertical', command=self.te_tpl_tv.yview)
        self.te_tpl_tv.configure(yscrollcommand=te_vsb.set)
        self.te_tpl_tv.grid(row=0, column=0, sticky='nsew')
        te_vsb.grid(row=0, column=1, sticky='ns')
        self.te_tpl_tv.bind('<<TreeviewSelect>>', self._te_on_tpl_select)
        self.te_tpl_tv.bind('<Delete>', lambda _: self._te_del_template())
        _setup_tv_autofit(self.te_tpl_tv, {'name': 200, 'inherits': 150, 'nf': 50})

        lbr = WrapFrame(lf, padx=2, pady=2)
        lbr.grid(row=2, column=0, sticky='ew', pady=(4, 0))
        lbr.add(ttk.Button(lbr, text="+ New Template",  command=self._te_new_template ))
        lbr.add(ttk.Button(lbr, text="⧉ Duplicate",     command=self._te_dup_template ))
        lbr.add(ttk.Button(lbr, text="✕ Delete",         command=self._te_del_template,
                   style='Danger.TButton'))
        lbr.add(ttk.Button(lbr, text="↑", command=self._te_tpl_up,   width=3))
        lbr.add(ttk.Button(lbr, text="↓", command=self._te_tpl_down, width=3))

        # ── Right: template editor detail ─────────────────────────────────
        rf = ttk.Frame(hp)
        hp.add(rf, weight=3)
        rf.rowconfigure(1, weight=1)
        rf.columnconfigure(0, weight=1)

        # Meta panel
        meta = ttk.LabelFrame(rf, text=" Template Metadata ")
        meta.grid(row=0, column=0, sticky='ew', padx=0, pady=(0, 4))
        meta.columnconfigure(1, weight=1)
        meta.columnconfigure(3, weight=1)

        self.te_sv = {}
        for i, (lbl, key, col) in enumerate([
            ("Name:",           'name',           0),
            ("Inherits from:",  'inherits_from',  2),
            ("Parent comment:", 'parent_comment', 0),
            ("File comment:",   'file_comment',   2),
        ]):
            row = i // 2
            col_lbl = col
            col_val = col + 1
            ttk.Label(meta, text=lbl).grid(row=row, column=col_lbl,
                                            sticky='w', padx=(8 if col==0 else 4, 2), pady=3)
            sv = tk.StringVar()
            self.te_sv[key] = sv
            if key == 'inherits_from':
                self._te_inherits_cb = SearchableCombobox(meta, textvariable=sv,
                                                           values=[], width=28)
                self._te_inherits_cb.grid(row=row, column=col_val, sticky='ew',
                                           padx=(2, 8), pady=3)
                self._te_inherits_cb.bind_selected(self._te_apply_meta)
            else:
                ttk.Entry(meta, textvariable=sv, width=30).grid(
                    row=row, column=col_val, sticky='ew',
                    padx=(2, 8 if col_val==3 else 2), pady=3)

        # Auto-apply metadata whenever any field changes
        self._te_meta_applying = False
        def _auto_apply_meta(*_):
            if self._te_loading or self._te_meta_applying:
                return
            if self._te_active_idx is None:
                return
            self._te_meta_applying = True
            try:
                self._te_apply_meta()
            finally:
                self._te_meta_applying = False
        for key, sv in self.te_sv.items():
            if key != 'inherits_from':   # inherits uses bind_selected above
                sv.trace_add('write', _auto_apply_meta)

        meta_btn_row = ttk.Frame(meta)
        meta_btn_row.grid(row=2, column=0, columnspan=4, sticky='w', padx=8, pady=(0, 4))
        ttk.Label(meta_btn_row,
                  text="Metadata is saved automatically as you type.",
                  style='Small.TLabel').pack(side=tk.LEFT, padx=2)

        # Fields panel
        ff = ttk.LabelFrame(rf, text=" Fields ")
        ff.grid(row=1, column=0, sticky='nsew')
        ff.rowconfigure(0, weight=1)
        ff.columnconfigure(0, weight=1)

        ftvf = ttk.Frame(ff)
        ftvf.grid(row=0, column=0, sticky='nsew', padx=4, pady=(4, 0))
        ftvf.rowconfigure(0, weight=1); ftvf.columnconfigure(0, weight=1)

        self.te_fields_tv = ttk.Treeview(ftvf,
            columns=('idx', 'type', 'tag', 'value', 'flags'),
            show='headings', selectmode='extended')
        col_specs = [
            ('idx',   '#',           30),
            ('type',  'Type',        90),
            ('tag',   'Tag / Text', 200),
            ('value', 'Value',      280),
            ('flags', 'Flags',        70),
        ]
        for col, txt, w in col_specs:
            self.te_fields_tv.heading(col, text=txt)
            self.te_fields_tv.column(col, width=w, minwidth=30)

        self.te_fields_tv.tag_configure('element',        foreground=P['text'])
        self.te_fields_tv.tag_configure('section_comment',foreground=P['ov0'])
        self.te_fields_tv.tag_configure('inline_comment', foreground=P['ov0'])
        self.te_fields_tv.tag_configure('blank',          foreground=P['s2'])
        self.te_fields_tv.tag_configure('bone_ref',       foreground=P['teal'])
        self.te_fields_tv.tag_configure('model_ref',      foreground=P['peach'])
        self.te_fields_tv.tag_configure('selected_row',   foreground=P['blue'])

        fvsb = ttk.Scrollbar(ftvf, orient='vertical',   command=self.te_fields_tv.yview)
        fhsb = ttk.Scrollbar(ftvf, orient='horizontal', command=self.te_fields_tv.xview)
        self.te_fields_tv.configure(yscrollcommand=fvsb.set, xscrollcommand=fhsb.set)
        self.te_fields_tv.grid(row=0, column=0, sticky='nsew')
        fvsb.grid(row=0, column=1, sticky='ns')
        fhsb.grid(row=1, column=0, sticky='ew')
        _setup_tv_autofit(self.te_fields_tv,
                          {'idx': 30, 'type': 90, 'tag': 200, 'value': 280, 'flags': 70})
        self.te_fields_tv.bind('<<TreeviewSelect>>', self._te_on_field_select)
        self.te_fields_tv.bind('<Double-1>',         self._te_on_fields_double_click)
        self.te_fields_tv.bind('<Delete>',           lambda _: self._te_del_field())
        # Keyboard shortcuts for the fields table.
        # IMPORTANT: Return 'break' from Ctrl+Up/Down to suppress the Treeview's
        # built-in class binding, which would otherwise reset the selection after
        # our handler has already moved the row and set it correctly.
        self.te_fields_tv.bind('<F2>',           lambda e: (self._te_inline_edit_col('tag'), 'break')[1])
        self.te_fields_tv.bind('<Control-Up>',   lambda e: (self._te_field_up(),   'break')[1])
        self.te_fields_tv.bind('<Control-Down>', lambda e: (self._te_field_down(), 'break')[1])
        self.te_fields_tv.bind('<Control-d>',    lambda e: (self._te_dup_field(),  'break')[1])

        # Field CRUD buttons — WrapFrame so they reflow on small layouts
        fbr = WrapFrame(ff, padx=2, pady=2)
        fbr.grid(row=1, column=0, sticky='ew', padx=4, pady=(2, 0))

        fbr.add(ttk.Label(fbr, text="Add:", style='Small.TLabel',
                           background=P['bg']))
        fbr.add(ttk.Button(fbr, text="Element",         command=self._te_add_element))
        fbr.add(ttk.Button(fbr, text="Section Comment", command=self._te_add_section_comment))
        fbr.add(ttk.Button(fbr, text="Inline Comment",  command=self._te_add_inline_comment))
        fbr.add(ttk.Button(fbr, text="Blank Line",      command=self._te_add_blank))
        fbr.add_sep()
        fbr.add(ttk.Button(fbr, text="✎ Edit",    command=self._te_edit_field))
        fbr.add(ttk.Button(fbr, text="✕ Delete",  command=self._te_del_field,
                   style='Danger.TButton'))
        fbr.add(ttk.Button(fbr, text="↑ Up",      command=self._te_field_up))
        fbr.add(ttk.Button(fbr, text="↓ Down",    command=self._te_field_down))
        fbr.add(ttk.Button(fbr, text="⧉ Duplicate", command=self._te_dup_field))

        # Inline field editor (row 2)
        ed = ttk.LabelFrame(ff, text=" Field Editor ")
        ed.grid(row=2, column=0, sticky='ew', padx=4, pady=4)
        # Type/Attrs col gets less space; Tag and Value cols get more
        ed.columnconfigure(1, weight=1, minsize=110)  # Type combo / Attrs entry
        ed.columnconfigure(3, weight=3)               # Tag entry
        ed.columnconfigure(5, weight=3)               # Value entry

        self.te_ed = {}
        fields_layout = [
            (0, 0, "Type:",       'ftype',      'combo', ['element','section_comment','inline_comment','blank']),
            (0, 2, "Tag:",        'tag',        'entry', None),
            (0, 4, "Value:",      'value',      'entry', None),
            (1, 2, "Empty tag:",  'empty_tag',  'check', None),
        ]
        for row, col, lbl, key, kind, opts in fields_layout:
            ttk.Label(ed, text=lbl).grid(row=row, column=col,
                                          sticky='w', padx=(8 if col==0 else 4, 2), pady=3)
            if kind == 'combo':
                sv = tk.StringVar(value='element')
                cb = ttk.Combobox(ed, textvariable=sv, values=opts,
                                   state='readonly', width=12)  # narrower than before
                cb.grid(row=row, column=col+1, sticky='ew', padx=(2,4), pady=3)
                cb.bind('<<ComboboxSelected>>', self._te_on_ftype_change)
                self.te_ed[key] = sv
                self._te_ftype_cb = cb
            elif kind == 'entry':
                sv = tk.StringVar()
                ttk.Entry(ed, textvariable=sv).grid(
                    row=row, column=col+1, sticky='ew', padx=(2,4), pady=3)
                self.te_ed[key] = sv
            elif kind == 'check':
                sv = tk.BooleanVar()
                ttk.Checkbutton(ed, text="(produces <Tag/>)",
                                variable=sv).grid(
                    row=row, column=col+1, columnspan=3,
                    sticky='w', padx=(2,4), pady=3)
                self.te_ed[key] = sv

        # Auto-apply field changes whenever any editor widget changes
        self._te_field_applying = False
        def _auto_apply_field(*_):
            if self._te_loading or self._te_field_applying:
                return
            if not self.te_fields_tv.selection():
                return
            self._te_field_applying = True
            try:
                self._te_apply_field(silent=True)
            finally:
                self._te_field_applying = False

        for key, sv in self.te_ed.items():
            if isinstance(sv, (tk.StringVar, tk.BooleanVar)):
                sv.trace_add('write', _auto_apply_field)

        # Attrs hint
        ed_btn = ttk.Frame(ff)
        ed_btn.grid(row=3, column=0, sticky='ew', padx=4, pady=(0, 4))
        ttk.Button(ed_btn, text="+ Insert Below",
                   command=self._te_insert_below).pack(side=tk.LEFT, padx=2)
        ttk.Label(ed_btn,
                  text="Ctrl/Shift-click for multi-select · Double-click Tag/Value to edit inline · F2 edit tag · Ctrl+↑↓ move · Ctrl+D duplicate",
                  style='Small.TLabel').pack(side=tk.LEFT, padx=8)

        # Deferred sash for editor pane
        self._te_pane_ref = hp
        # Sash positioning for this pane is handled by _set_initial_sashes() / _on_tab_changed

    # ─── Template Editor: file operations ─────────────────────────────────

    def _te_new_file(self):
        if not self._te_confirm_discard():
            return
        self._te_file_path = None
        self._te_templates = []
        self._te_active_idx = None
        self._te_dirty = False
        self._te_refresh_list()
        self._te_clear_editor()
        self.sv_te_file.set("(new file — unsaved)")
        # Start with one blank template
        self._te_new_template()

    def _te_open_file(self):
        if not self._te_confirm_discard():
            return
        initial = str(self._te_file_path.parent) if self._te_file_path else _default_templates()
        path = filedialog.askopenfilename(
            title="Open Template JSON File",
            initialdir=initial,
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if not path:
            return
        self._te_load_file(Path(path))

    def _te_load_file(self, path: Path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Open Error", f"Could not load:\n{e}")
            return
        self._te_file_path = path
        self._te_templates  = data.get("templates", [])
        # Deep-copy so edits don't affect the raw dict
        self._te_templates  = copy.deepcopy(self._te_templates)
        self._te_active_idx = None
        self._te_dirty      = False
        self._te_refresh_list()
        self._te_clear_editor()
        self.sv_te_file.set(str(path))
        self._te_update_inherits_combo()
        self._log(f"Template editor: opened {path.name} ({len(self._te_templates)} templates)\n", 'info')
        # Auto-select first template
        if self._te_templates:
            self.te_tpl_tv.selection_set("0")
            self.te_tpl_tv.see("0")
            self._te_on_tpl_select()

    def _te_save(self):
        if self._te_file_path is None:
            return self._te_save_as()
        self._te_write_file(self._te_file_path)

    def _te_save_as(self):
        initial = str(self._te_file_path.parent) if self._te_file_path else _default_templates()
        fname   = self._te_file_path.name if self._te_file_path else "Templates_New.json"
        path = filedialog.asksaveasfilename(
            title="Save Template File",
            initialdir=initial,
            initialfile=fname,
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if not path:
            return
        self._te_write_file(Path(path))

    def _te_write_file(self, path: Path):
        # Make sure any in-progress edits to the active template are committed
        self._te_commit_active()
        file_comment = self.te_sv.get('file_comment', tk.StringVar()).get().strip()
        data = {}
        if file_comment:
            data["_comment"] = file_comment
        data["templates"] = self._te_templates
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._te_file_path = path
            self._te_dirty     = False
            self.sv_te_file.set(str(path))
            self._log(f"Template editor: saved {path.name}\n", 'success')
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save:\n{e}")

    def _te_confirm_discard(self) -> bool:
        if not self._te_dirty:
            return True
        r = messagebox.askyesnocancel("Unsaved Changes",
            "The template editor has unsaved changes.\nDiscard them?")
        return r is True  # None (cancel) or False → don't discard

    def _te_import_xml(self):
        """
        Import hardpoints from an EaW .XML file as templates into the Template Editor.

        Each <HardPoint> entry becomes one template dict.  The user picks which
        hardpoints to include via the XmlImportDialog selection screen.
        Selected templates are *appended* to whatever is already in the editor
        (no discard prompt — nothing is replaced).
        After import the first newly added template is selected and the editor
        is marked dirty.  The user saves the result via "Save" / "Save As…".
        """
        if not _XML_IMPORTER_AVAILABLE:
            messagebox.showerror(
                "Importer Unavailable",
                "hp_xml_importer.py could not be imported.\n"
                "Make sure it is in the same directory as hp_generator_GUI.py.",
                parent=self.root)
            return

        initial = (str(self._te_file_path.parent)
                   if self._te_file_path else _script_dir())
        path = filedialog.askopenfilename(
            title="Import Hardpoints from XML File",
            initialdir=initial,
            filetypes=[("XML", "*.xml *.XML"), ("All files", "*.*")]
        )
        if not path:
            return

        # Parse the XML file
        self._log(f"XML import: parsing {Path(path).name}…\n", 'dim')
        try:
            templates, warnings = hp_xml_importer.parse_hardpoints_from_xml(path)
        except hp_xml_importer.XmlImportError as exc:
            messagebox.showerror("Import Error",
                                 f"Could not parse XML file:\n{exc}",
                                 parent=self.root)
            self._log(f"XML import error: {exc}\n", 'error')
            return
        except Exception as exc:
            messagebox.showerror("Import Error",
                                 f"Unexpected error reading file:\n{exc}",
                                 parent=self.root)
            self._log(f"XML import unexpected error: {exc}\n", 'error')
            return

        for w in warnings:
            self._log(f"  ⚠ {w}\n", 'warn')

        if not templates:
            messagebox.showinfo(
                "Nothing Found",
                "No <HardPoint> entries were found in the selected file.",
                parent=self.root)
            return

        # Show selection dialog
        dlg = XmlImportDialog(self.root, templates,
                              source_name=Path(path).name)
        if dlg.result is None:
            return   # user cancelled
        if not dlg.result:
            self._log("XML import: no templates selected.\n", 'warn')
            return

        # Warn about name collisions with existing templates
        existing_names = {t.get("name", "") for t in self._te_templates}
        collisions = [t.get("name", "") for t in dlg.result
                      if t.get("name", "") in existing_names]
        if collisions:
            preview = "\n".join(f"  • {n}" for n in collisions[:10])
            if len(collisions) > 10:
                preview += f"\n  … and {len(collisions) - 10} more"
            if not messagebox.askyesno(
                    "Name Collisions",
                    f"{len(collisions)} template name(s) already exist in the "
                    f"editor and will be duplicated:\n\n{preview}\n\n"
                    "Continue anyway?",
                    parent=self.root):
                return

        # Commit any in-progress field edits before appending
        self._te_commit_active()

        first_new_idx = len(self._te_templates)
        self._te_templates.extend(dlg.result)
        self._te_dirty = True

        self._te_refresh_list()
        self._te_update_inherits_combo()

        # Select the first newly imported template
        new_iid = str(first_new_idx)
        try:
            self.te_tpl_tv.selection_set(new_iid)
            self.te_tpl_tv.see(new_iid)
            self._te_on_tpl_select()
        except Exception:
            pass

        # If no file was associated yet, update the status label
        if self._te_file_path is None:
            self.sv_te_file.set(
                f"(imported from {Path(path).name} — not yet saved as JSON)")

        n = len(dlg.result)
        self._log(
            f"XML import: appended {n} template{'s' if n != 1 else ''} "
            f"from {Path(path).name}.  Use 💾 Save / Save As… to write as JSON.\n",
            'success')



    # ─── Template list CRUD ────────────────────────────────────────────────

    def _te_refresh_list(self):
        self.te_tpl_tv.delete(*self.te_tpl_tv.get_children())
        for i, tpl in enumerate(self._te_templates):
            name     = tpl.get("name", f"(unnamed {i+1})")
            inherits = tpl.get("inherits_from", "") or "—"
            nf       = len(tpl.get("fields", []))
            tag      = 'child' if tpl.get("inherits_from", "").strip() else 'base'
            self.te_tpl_tv.insert('', 'end', iid=str(i),
                                   values=(name, inherits, nf), tags=(tag,))
        n = len(self._te_templates)
        self.sv_te_tpl_count.set(f"{n} template{'s' if n!=1 else ''}")
        self._te_update_inherits_combo()

    def _te_new_template(self):
        self._te_commit_active()
        tpl = {
            "name":           "New_Template",
            "parent_comment": "New_Template",
            "inherits_from":  "",
            "fields":         []
        }
        self._te_templates.append(tpl)
        self._te_dirty = True
        self._te_refresh_list()
        new_idx = len(self._te_templates) - 1
        self.te_tpl_tv.selection_set(str(new_idx))
        self.te_tpl_tv.see(str(new_idx))
        self._te_on_tpl_select()

    def _te_dup_template(self):
        sels = self.te_tpl_tv.selection()
        if not sels: return
        indices = sorted([int(s) for s in sels])
        self._te_commit_active()
        # Collect deep copies before any insertions shift indices
        dups = [copy.deepcopy(self._te_templates[i]) for i in indices]
        for dup in dups:
            dup["name"] = dup.get("name", "") + "_Copy"
        insert_at = indices[-1] + 1
        for j, dup in enumerate(dups):
            self._te_templates.insert(insert_at + j, dup)
        self._te_dirty = True
        self._te_refresh_list()
        new_iids = [str(insert_at + j) for j in range(len(dups))]
        self.te_tpl_tv.selection_set(*new_iids)
        if new_iids:
            self.te_tpl_tv.see(new_iids[-1])
            self._te_active_idx = insert_at
            self._te_on_tpl_select()

    def _te_del_template(self):
        sels = self.te_tpl_tv.selection()
        if not sels: return
        indices = sorted([int(s) for s in sels])
        names = [self._te_templates[i].get("name", f"template {i+1}") for i in indices]
        if len(names) == 1:
            msg = f"Delete '{names[0]}'?"
        else:
            preview = "\n".join(f"  • {n}" for n in names[:8])
            if len(names) > 8:
                preview += f"\n  … and {len(names) - 8} more"
            msg = f"Delete {len(names)} templates?\n\n{preview}"
        if not messagebox.askyesno("Delete Templates", msg):
            return
        for i in reversed(indices):
            del self._te_templates[i]
        self._te_active_idx = None
        self._te_dirty = True
        self._te_refresh_list()
        self._te_clear_editor()

    def _te_tpl_up(self):
        sels = self.te_tpl_tv.selection()
        if not sels: return
        indices = sorted([int(s) for s in sels])
        if indices[0] == 0: return
        self._te_commit_active()
        # Process ascending: each selected item swaps with the item above it
        for i in indices:
            self._te_templates[i-1], self._te_templates[i] = \
                self._te_templates[i], self._te_templates[i-1]
        self._te_dirty = True
        self._te_refresh_list()
        new_iids = [str(i - 1) for i in indices]
        self.te_tpl_tv.selection_set(*new_iids)
        if new_iids:
            self.te_tpl_tv.see(new_iids[0])
        if self._te_active_idx is not None and str(self._te_active_idx) in sels:
            self._te_active_idx -= 1

    def _te_tpl_down(self):
        sels = self.te_tpl_tv.selection()
        if not sels: return
        indices = sorted([int(s) for s in sels], reverse=True)
        if indices[0] >= len(self._te_templates) - 1: return
        self._te_commit_active()
        # Process descending: each selected item swaps with the item below it
        for i in indices:
            self._te_templates[i], self._te_templates[i+1] = \
                self._te_templates[i+1], self._te_templates[i]
        self._te_dirty = True
        self._te_refresh_list()
        new_iids = [str(i + 1) for i in indices]
        self.te_tpl_tv.selection_set(*new_iids)
        if new_iids:
            self.te_tpl_tv.see(new_iids[-1])
        if self._te_active_idx is not None and str(self._te_active_idx) in sels:
            self._te_active_idx += 1

    def _te_on_tpl_select(self, _=None):
        sels = self.te_tpl_tv.selection()
        if not sels:
            self._te_clear_editor()
            return
        # If multiple selected, commit active but only load editor for the last clicked one
        if len(sels) > 1:
            # Commit current without switching — keep editor showing last single selection
            return
        self._te_commit_active()
        i   = int(sels[0])
        self._te_active_idx = i
        tpl = self._te_templates[i]

        # Load metadata — suppress auto-apply during load
        self._te_loading = True
        try:
            self.te_sv['name'          ].set(tpl.get("name",           ""))
            self.te_sv['inherits_from' ].set(tpl.get("inherits_from",  ""))
            self.te_sv['parent_comment'].set(tpl.get("parent_comment", ""))
            self.te_sv['file_comment'  ].set("")     # file-level, not per template
        finally:
            self._te_loading = False

        # Populate fields table
        self._te_refresh_fields(tpl.get("fields", []))
        self._te_clear_field_editor()

    def _te_clear_editor(self):
        self._te_loading = True
        try:
            for sv in self.te_sv.values():
                sv.set("")
        finally:
            self._te_loading = False
        self.te_fields_tv.delete(*self.te_fields_tv.get_children())
        self._te_clear_field_editor()
        self._te_active_idx = None

    def _te_update_inherits_combo(self):
        """Populate the inherits_from combobox with all known template names."""
        names = sorted({tpl.get("name", "") for tpl in self._te_templates
                        if tpl.get("name", "")})
        # Also include names from the loaded registry
        names = sorted(set(names) | set(self.template_registry.keys()))
        names = [""] + names   # blank = no parent
        if hasattr(self, '_te_inherits_cb'):
            self._te_inherits_cb.configure_values(names)

    # ─── Metadata apply ────────────────────────────────────────────────────

    def _te_apply_meta(self):
        i = self._te_active_idx
        if i is None: return
        tpl = self._te_templates[i]

        # ── Capture old name before overwriting ───────────────────────────
        old_name = tpl.get("name", "").strip()
        new_name = self.te_sv['name'].get().strip()

        tpl["name"]           = new_name
        tpl["parent_comment"] = self.te_sv['parent_comment'].get().strip()
        tpl["inherits_from"]  = self.te_sv['inherits_from'].get().strip()
        self._te_dirty = True

        # ── Cascade rename through inheritance chains ─────────────────────
        # If the template's name changed, update every other template in this
        # file that inherits from the old name so the chain stays intact.
        if old_name and new_name and old_name != new_name:
            renamed_count = 0
            for j, other in enumerate(self._te_templates):
                if j == i:
                    continue   # skip the template being renamed
                if other.get("inherits_from", "").strip() == old_name:
                    other["inherits_from"] = new_name
                    renamed_count += 1
            if renamed_count:
                self._log(
                    f"Template Editor: renamed '{old_name}' -> '{new_name}';"
                    f" updated {renamed_count} child template(s).\n",
                    'info'
                )

        # ── Debounced list refresh ────────────────────────────────────────
        # Cancel any pending refresh and schedule a new one 250 ms out so we
        # don't hammer the treeview on every keypress while typing a name.
        if hasattr(self, '_te_meta_refresh_id') and self._te_meta_refresh_id:
            try:
                self.root.after_cancel(self._te_meta_refresh_id)
            except Exception:
                pass
        def _do_refresh(idx=i):
            self._te_meta_refresh_id = None
            self._te_refresh_list()
            # Re-select the row that was being edited
            try:
                self.te_tpl_tv.selection_set(str(idx))
            except Exception:
                pass
        self._te_meta_refresh_id = self.root.after(250, _do_refresh)

    # ─── Template commit (save in-memory before switching) ────────────────

    def _te_commit_active(self):
        """Write the fields table back to _te_templates for the active template.

        Also cascades any name change to child templates, matching the same
        logic as _te_apply_meta so that switching templates via the list never
        silently breaks inheritance.
        """
        i = self._te_active_idx
        if i is None or i >= len(self._te_templates):
            return
        tpl = self._te_templates[i]

        old_name = tpl.get("name", "").strip()
        new_name = self.te_sv['name'].get().strip() or old_name
        tpl["name"]           = new_name
        tpl["parent_comment"] = self.te_sv['parent_comment'].get().strip()
        tpl["inherits_from"]  = self.te_sv['inherits_from'].get().strip()

        # Cascade rename to children (same logic as _te_apply_meta)
        if old_name and new_name and old_name != new_name:
            for j, other in enumerate(self._te_templates):
                if j != i and other.get("inherits_from", "").strip() == old_name:
                    other["inherits_from"] = new_name

        # Rebuild fields from treeview
        fields = []
        for iid in self.te_fields_tv.get_children():
            fields.append(self._te_row_to_field(iid))
        tpl["fields"] = fields

    # ─── Fields table ─────────────────────────────────────────────────────

    def _te_refresh_fields(self, fields: list):
        self.te_fields_tv.delete(*self.te_fields_tv.get_children())
        for i, field in enumerate(fields):
            iid = str(i)
            self._te_insert_field_row(iid, field, at_end=True)
        self._te_renumber_fields()

    def _te_field_to_row(self, field: dict) -> tuple:
        """Convert a field dict to a treeview row tuple."""
        ftype = field.get("_type", "element")
        if ftype == "blank":
            return ("", "blank", "", "", "")
        if ftype in ("section_comment", "inline_comment"):
            label = "section cmt" if ftype == "section_comment" else "inline cmt"
            return ("", label, field.get("text", ""), "", "")
        tag   = field.get("tag", "")
        value = str(field.get("value", ""))
        flags = "empty_tag" if field.get("empty_tag") else ""
        return ("", "element", tag, value, flags)

    def _te_row_to_field(self, iid: str) -> dict:
        """Reconstruct a field dict from the stored tag on the treeview item."""
        # We store the original field dict as a tag string — but it's easier
        # to store it in a parallel dict keyed by iid.
        return self._te_field_store.get(iid, {"_type": "blank"})

    def _te_insert_field_row(self, iid: str, field: dict, at_end=False, after_iid=None):
        """Insert a field into the treeview and store it in the parallel dict."""
        if not hasattr(self, '_te_field_store'):
            self._te_field_store = {}
        self._te_field_store[iid] = field

        ftype = field.get("_type", "element")
        row   = self._te_field_to_row(field)
        # Determine colour tag
        val   = str(field.get("value",""))
        if ftype == "element":
            if "{bone" in val or "{bone_a}" in val or "{bone_b}" in val:
                tag = 'bone_ref'
            elif "{model_idx}" in val or "{damage_idx}" in val:
                tag = 'model_ref'
            else:
                tag = 'element'
        else:
            tag = ftype  # blank / section_comment / inline_comment

        kw = dict(values=row, tags=(tag,))
        if at_end:
            self.te_fields_tv.insert('', 'end', iid=iid, **kw)
        elif after_iid:
            idx = self.te_fields_tv.index(after_iid)
            self.te_fields_tv.insert('', idx+1, iid=iid, **kw)
        else:
            self.te_fields_tv.insert('', 'end', iid=iid, **kw)

    def _te_next_field_iid(self) -> str:
        """Generate a unique iid for a new field row."""
        existing = set(self.te_fields_tv.get_children())
        n = 0
        while f"f{n}" in existing:
            n += 1
        return f"f{n}"

    def _te_on_field_select(self, _=None):
        sel = self.te_fields_tv.selection()
        if not sel: return
        # Only populate the inline editor when exactly one row is selected;
        # with multiple selected we leave the editor showing the previous value
        # so the user can still apply a bulk edit if they wish.
        if len(sel) > 1:
            return
        iid   = sel[0]
        field = self._te_field_store.get(iid, {})
        self._te_populate_field_editor(field)

    def _te_clear_field_editor(self):
        self._te_loading = True
        try:
            self.te_ed['ftype'].set('element')
            self.te_ed['tag'].set('')
            self.te_ed['value'].set('')
            self.te_ed['empty_tag'].set(False)
        finally:
            self._te_loading = False
        self._te_on_ftype_change()

    def _te_populate_field_editor(self, field: dict):
        self._te_loading = True
        try:
            ftype = field.get("_type", "element")
            self.te_ed['ftype'].set(ftype)
            if ftype == "element":
                self.te_ed['tag'].set(field.get("tag", ""))
                self.te_ed['value'].set(str(field.get("value", "")))
                self.te_ed['empty_tag'].set(bool(field.get("empty_tag", False)))
            else:
                self.te_ed['tag'].set(field.get("text", ""))
                self.te_ed['value'].set("")
                self.te_ed['empty_tag'].set(False)
        finally:
            self._te_loading = False
        self._te_on_ftype_change()

    def _te_on_ftype_change(self, _=None):
        ftype = self.te_ed['ftype'].get()
        is_elem = ftype == 'element'
        # Show/hide irrelevant fields
        # (we just disable rather than hide to preserve layout)

    # ─── Inline cell editing ───────────────────────────────────────────────

    # Maps treeview column identifiers to human-readable field keys
    _INLINE_COL_MAP = {'#3': 'tag', '#4': 'value'}

    def _te_on_fields_double_click(self, event):
        """Route double-click: inline-edit editable columns, open dialog for others."""
        col = self.te_fields_tv.identify_column(event.x)
        if col in self._INLINE_COL_MAP:
            # Inline edit the clicked column — but first make sure the row is
            # selected (the click may not have fired <<TreeviewSelect>> yet).
            iid = self.te_fields_tv.identify_row(event.y)
            if iid:
                self.te_fields_tv.selection_set(iid)
            self.root.after_idle(lambda c=col: self._te_inline_edit_col_id(c))
        else:
            self._te_edit_field()

    def _te_inline_edit_col(self, field_key: str):
        """Start inline editing the given field key ('tag', 'value')
        for the currently selected row.  Called by keyboard shortcuts."""
        key_to_col = {'tag': '#3', 'value': '#4'}
        col = key_to_col.get(field_key)
        if col:
            self._te_inline_edit_col_id(col)

    def _te_inline_edit_col_id(self, col_id: str):
        """Open a floating Entry widget over treeview cell (col_id e.g. '#3')."""
        sel = self.te_fields_tv.selection()
        if not sel:
            return
        iid = sel[0]
        field_key = self._INLINE_COL_MAP.get(col_id)
        if not field_key:
            return

        field = self._te_field_store.get(iid, {})
        ftype = field.get("_type", "element")

        # Blank rows have no editable cells
        if ftype == "blank":
            return
        # Comment rows: only the 'tag' column (which shows the text) is editable
        if ftype in ("section_comment", "inline_comment") and field_key != 'tag':
            return

        # Get the current text for this cell
        if field_key == 'tag':
            current = field.get("tag", "") if ftype == "element" else field.get("text", "")
        elif field_key == 'value':
            current = str(field.get("value", ""))
        else:  # attrs
            current = "; ".join(f'{k}={v}' for k, v in field.get("attrs", {}).items())

        # Get cell bounding box relative to the treeview widget
        bbox = self.te_fields_tv.bbox(iid, col_id)
        if not bbox:
            return  # row may be scrolled out of view
        x, y, w, h = bbox

        # Create a themed entry widget placed directly over the cell
        var = tk.StringVar(value=current)
        entry = ttk.Entry(self.te_fields_tv, textvariable=var)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.select_range(0, 'end')

        # Destroy any previously open inline editor
        if hasattr(self, '_te_inline_entry') and self._te_inline_entry:
            try:
                self._te_inline_entry.destroy()
            except Exception:
                pass
        self._te_inline_entry = entry

        def _commit(event=None):
            if not entry.winfo_exists():
                return
            new_val = var.get()
            entry.place_forget()
            entry.destroy()
            self._te_inline_entry = None
            self._apply_inline_cell(iid, field_key, new_val)
            # Return 'break' when called from a key binding so the event isn't
            # forwarded to the treeview (prevents spurious selection changes).
            return 'break'

        def _cancel(event=None):
            if not entry.winfo_exists():
                return
            entry.place_forget()
            entry.destroy()
            self._te_inline_entry = None
            return 'break'

        def _tab(event=None):
            """Commit and move to the next editable column."""
            _commit()
            # Cycle tag → value → tag
            next_col = {'#3': '#4', '#4': '#3'}.get(col_id, '#3')
            self.root.after_idle(lambda c=next_col: self._te_inline_edit_col_id(c))
            return 'break'

        entry.bind('<Return>',   _commit)
        entry.bind('<KP_Enter>', _commit)
        entry.bind('<Escape>',   _cancel)
        entry.bind('<Tab>',      _tab)
        entry.bind('<FocusOut>', _commit)
        # Scroll events should commit the edit so it doesn't float out of sync
        self.te_fields_tv.bind('<MouseWheel>', lambda e: _commit(), add='+')

    def _apply_inline_cell(self, iid: str, field_key: str, new_val: str):
        """Persist an inline-edited cell value back to the field store and treeview."""
        field = dict(self._te_field_store.get(iid, {}))
        ftype = field.get("_type", "element")

        if field_key == 'tag':
            if ftype == "element":
                field["tag"] = new_val.strip()
            else:
                field["text"] = new_val
        elif field_key == 'value':
            field["value"] = new_val

        self._te_field_store[iid] = field

        # Recompute the colour tag
        val = str(field.get("value", ""))
        if ftype == "element":
            if "{bone" in val or "{bone_a}" in val or "{bone_b}" in val:
                colour_tag = 'bone_ref'
            elif "{model_idx}" in val or "{damage_idx}" in val:
                colour_tag = 'model_ref'
            else:
                colour_tag = 'element'
        else:
            colour_tag = ftype

        self.te_fields_tv.item(iid, values=self._te_field_to_row(field),
                               tags=(colour_tag,))
        self._te_renumber_fields()

        # Keep the lower Field Editor in sync if this row is still selected
        if self.te_fields_tv.selection() and self.te_fields_tv.selection()[0] == iid:
            self._te_loading = True
            try:
                if field_key == 'tag':
                    self.te_ed['tag'].set(
                        field.get("tag", "") if ftype == "element" else field.get("text", ""))
                elif field_key == 'value':
                    self.te_ed['value'].set(field.get("value", ""))
            finally:
                self._te_loading = False

        self._te_dirty = True
        self._te_update_field_count()

    def _te_field_from_editor(self, silent=False) -> dict | None:
        """Build a field dict from the current editor values. Returns None on error.

        When silent=True the messagebox is suppressed (used by auto-apply traces).
        """
        ftype = self.te_ed['ftype'].get()
        if ftype == 'blank':
            return {"_type": "blank"}
        if ftype in ('section_comment', 'inline_comment'):
            text = self.te_ed['tag'].get().strip()
            return {"_type": ftype, "text": text}
        # element
        tag = self.te_ed['tag'].get().strip()
        if not tag:
            if not silent:
                messagebox.showerror("Required", "Tag name cannot be empty.", parent=self.root)
            return None
        value     = self.te_ed['value'].get()
        empty_tag = bool(self.te_ed['empty_tag'].get())

        field: dict = {"tag": tag, "value": value}
        if empty_tag:
            field["empty_tag"] = True
        return field

    def _te_apply_field(self, silent=False):
        """Apply the editor values to the currently selected row.

        When silent=True (called from auto-apply traces) no messageboxes are
        shown — errors are simply ignored so the trace never blocks the UI.
        """
        sel = self.te_fields_tv.selection()
        if not sel:
            if not silent:
                messagebox.showinfo("No Row Selected",
                                    "Select a field row in the table, then click Apply.")
            return
        field = self._te_field_from_editor(silent=silent)
        if field is None:
            return
        iid = sel[0]
        self._te_field_store[iid] = field
        row = self._te_field_to_row(field)
        ftype = field.get("_type", "element")
        val   = str(field.get("value", ""))
        if ftype == "element":
            if "{bone" in val:
                tag = 'bone_ref'
            elif "{model_idx}" in val or "{damage_idx}" in val:
                tag = 'model_ref'
            else:
                tag = 'element'
        else:
            tag = ftype
        self.te_fields_tv.item(iid, values=row, tags=(tag,))
        self._te_dirty = True
        self._te_update_field_count()

    def _te_insert_below(self):
        """Insert a new field row below the selected row(s) using editor values."""
        field = self._te_field_from_editor()
        if field is None:
            return
        new_iid = self._te_next_field_iid()
        sel = self.te_fields_tv.selection()
        # Use the last selected row as the insertion anchor
        after = sel[-1] if sel else None
        self._te_field_store[new_iid] = field
        row = self._te_field_to_row(field)
        ftype = field.get("_type", "element")
        val   = str(field.get("value", ""))
        if ftype == "element":
            if "{bone" in val:
                tag = 'bone_ref'
            elif "{model_idx}" in val or "{damage_idx}" in val:
                tag = 'model_ref'
            else:
                tag = 'element'
        else:
            tag = ftype
        if after:
            idx = self.te_fields_tv.index(after)
            self.te_fields_tv.insert('', idx + 1, iid=new_iid, values=row, tags=(tag,))
        else:
            self.te_fields_tv.insert('', 'end', iid=new_iid, values=row, tags=(tag,))
        self.te_fields_tv.selection_set(new_iid)
        self.te_fields_tv.see(new_iid)
        self._te_dirty = True
        self._te_update_field_count()

    def _te_add_element(self):
        self.te_ed['ftype'].set('element')
        self._te_clear_field_editor()
        self.te_ed['ftype'].set('element')
        self._te_insert_blank_row("element")

    def _te_add_section_comment(self):
        self._te_insert_blank_row("section_comment")

    def _te_add_inline_comment(self):
        self._te_insert_blank_row("inline_comment")

    def _te_add_blank(self):
        self._te_insert_blank_row("blank")

    def _te_insert_blank_row(self, ftype: str):
        if ftype == 'blank':
            field = {"_type": "blank"}
        elif ftype in ('section_comment', 'inline_comment'):
            field = {"_type": ftype, "text": ""}
        else:
            field = {"tag": "", "value": ""}
        new_iid = self._te_next_field_iid()
        sel = self.te_fields_tv.selection()
        # When multiple rows are selected use the last one as anchor
        after = sel[-1] if sel else None
        self._te_field_store[new_iid] = field
        row = self._te_field_to_row(field)
        tag = ftype if ftype != 'element' else 'element'
        if after:
            idx = self.te_fields_tv.index(after)
            self.te_fields_tv.insert('', idx+1, iid=new_iid, values=row, tags=(tag,))
        else:
            self.te_fields_tv.insert('', 'end', iid=new_iid, values=row, tags=(tag,))
        self.te_fields_tv.selection_set(new_iid)
        self.te_fields_tv.see(new_iid)
        self._te_populate_field_editor(field)
        self._te_dirty = True
        self._te_update_field_count()

    def _te_edit_field(self):
        sel = self.te_fields_tv.selection()
        if not sel: return
        iid   = sel[0]
        field = self._te_field_store.get(iid, {})
        self._te_populate_field_editor(field)

    def _te_del_field(self):
        sels = self.te_fields_tv.selection()
        if not sels: return
        for iid in sels:
            self.te_fields_tv.delete(iid)
            self._te_field_store.pop(iid, None)
        self._te_dirty = True
        self._te_renumber_fields()
        self._te_update_field_count()

    def _te_dup_field(self):
        sels = self.te_fields_tv.selection()
        if not sels: return
        children = list(self.te_fields_tv.get_children())
        # Sort selected by current position so we insert in order
        ordered = sorted(sels, key=lambda iid: children.index(iid))
        last_iid = ordered[-1]
        insert_idx = children.index(last_iid)
        new_iids = []
        for j, iid in enumerate(ordered):
            field   = copy.deepcopy(self._te_field_store.get(iid, {}))
            new_iid = self._te_next_field_iid()
            self._te_field_store[new_iid] = field
            row   = self._te_field_to_row(field)
            ftype = field.get("_type", "element")
            val   = str(field.get("value", ""))
            if ftype == "element":
                tag = ('bone_ref' if "{bone" in val
                       else 'model_ref' if ("{model_idx}" in val or "{damage_idx}" in val)
                       else 'element')
            else:
                tag = ftype
            self.te_fields_tv.insert('', insert_idx + 1 + j, iid=new_iid,
                                      values=row, tags=(tag,))
            new_iids.append(new_iid)
        self.te_fields_tv.selection_set(*new_iids)
        if new_iids:
            self.te_fields_tv.see(new_iids[-1])
        self._te_dirty = True
        self._te_renumber_fields()
        self._te_update_field_count()

    def _te_field_up(self):
        sels = list(self.te_fields_tv.selection())
        if not sels: return
        children = list(self.te_fields_tv.get_children())
        # Sort selected by ascending position
        sel_pos = sorted([(children.index(iid), iid) for iid in sels])
        if sel_pos[0][0] == 0: return   # topmost selected is already first
        # Move each item up by 1 (ascending order so we don't displace each other)
        for _orig_idx, iid in sel_pos:
            children = list(self.te_fields_tv.get_children())
            cur = children.index(iid)
            self.te_fields_tv.move(iid, '', cur - 1)
        # Re-assert selection after all moves
        self.te_fields_tv.selection_set(*sels)
        if sels:
            self.te_fields_tv.see(sels[0])
        self._te_renumber_fields()
        self.te_fields_tv.selection_set(*sels)
        self._te_dirty = True

    def _te_field_down(self):
        sels = list(self.te_fields_tv.selection())
        if not sels: return
        children = list(self.te_fields_tv.get_children())
        # Sort selected by descending position
        sel_pos = sorted([(children.index(iid), iid) for iid in sels], reverse=True)
        if sel_pos[0][0] >= len(children) - 1: return   # bottom-most is already last
        # Move each item down by 1 (descending order so we don't displace each other)
        for _orig_idx, iid in sel_pos:
            children = list(self.te_fields_tv.get_children())
            cur = children.index(iid)
            self.te_fields_tv.move(iid, '', cur + 1)
        self.te_fields_tv.selection_set(*sels)
        if sels:
            self.te_fields_tv.see(sels[-1])
        self._te_renumber_fields()
        self.te_fields_tv.selection_set(*sels)
        self._te_dirty = True

    def _te_renumber_fields(self):
        """Patch the # column of every row to reflect its current 1-based position."""
        for i, iid in enumerate(self.te_fields_tv.get_children()):
            vals = list(self.te_fields_tv.item(iid)['values'])
            if vals:
                vals[0] = i + 1
                self.te_fields_tv.item(iid, values=vals)

    def _te_update_field_count(self):
        self._te_renumber_fields()
        n = len(self.te_fields_tv.get_children())
        # Update the template list row
        i = self._te_active_idx
        if i is not None:
            sel = self.te_tpl_tv.selection()
            cur = self.te_tpl_tv.item(str(i))['values']
            if cur:
                self.te_tpl_tv.item(str(i), values=(cur[0], cur[1], n))


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="EaW Hardpoint Generator GUI")
    parser.add_argument("config", nargs="?", help="Ship config JSON to open on launch")
    args = parser.parse_args()

    def resource_path(relative_path):
        """Get absolute path to resource, works for dev and PyInstaller"""
        try:
            # PyInstaller temporary folder
            base_path = sys._MEIPASS
        except AttributeError:
            # normal Python execution
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)


    root = tk.Tk()
    root.iconbitmap(default=resource_path("icon.ico"))

    app  = App(root, open_path=args.config)
    root.mainloop()


if __name__ == "__main__":
    main()
