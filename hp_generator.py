#!/usr/bin/env python3
"""
=============================================================================
  EaW Hardpoint Generator
  For Star Wars: Empire at War
=============================================================================

  Generates complete hardpoint XML files from reusable templates.

  Usage:
    python hp_generator.py <ship_config.json> [options]

  Options:
    --templates, -t  PATH   Override the templates path (file or folder)
    --output,    -o  PATH   Override the output XML file path
    --list,      -l         Print all hardpoint names without writing the file
    --dump,      -d  NAME   Print the fully-resolved field list for a template

=============================================================================
  FIRE BONES — DUAL FIRING POSITION SUPPORT
=============================================================================

  Placeholders in template field values:
    {bone}    — primary bone (alias for {bone_a}, backward-compatible)
    {bone_a}  — primary bone (Fire_Bone_A)
    {bone_b}  — secondary bone (Fire_Bone_B). Defaults to bone_a when not set.
    {bone_c}  — tertiary bone (e.g. Attachment_Bone). Defaults to bone_a when not set.
    {bone_d}  — quaternary bone (e.g. Collision_Mesh). Defaults to bone_a when not set.
    {bone_e}  — quinary bone (e.g. Damage_Particles). Defaults to bone_a when not set.
    {bone_f}  — senary bone (e.g. Damage_Decal). Defaults to bone_a when not set.

  Bone entry formats in a group's "bones" list:
    "HP_TL_01_L"
    { "bone": "HP_TL_01_L", "name": "HP_Custom" }
    { "bone_a": "HP_TL_01_L", "bone_b": "HP_TL_02_L" }
    { "bone_a": "HP_TL_01_L", "bone_b": "HP_TL_02_L", "name": "HP_Custom" }
    { "bone_a": "HP_TL_01_L", "bone_b": "HP_TL_02_L", "bone_c": "HP_ATT_01",
      "bone_d": "HP_COL_01", "bone_e": "HP_DMG_01", "bone_f": "HP_DCL_01",
      "name": "HP_Custom" }

=============================================================================
  TURRET MODEL AUTO-NUMBERING  (updated behaviour)
=============================================================================

  The model filename base now lives in the template itself.
  Use {model_idx} anywhere in a field value — the generator replaces it with
  a formatted ship-wide counter number:

    Template:  { "tag": "Model_To_Attach", "value": "T_Turret_XX9_{model_idx}.ALO" }
    Output:    <Model_To_Attach>T_Turret_XX9_01.ALO</Model_To_Attach>

  Counter config (ship config root):
    "turret_models": { "start": 1, "format": "02d" }

  LEGACY: if a group has "model_base": "T_Turret_XX9_TurboLaser" AND the
  template has {model_idx}, the old behaviour applies:
    {model_idx} → T_Turret_XX9_TurboLaser_01.ALO  (full filename assembled)

=============================================================================
  DAMAGE PARTICLES AUTO-NUMBERING
=============================================================================

  Use {damage_idx} in Damage_Particles (or any field) for a separate
  ship-wide auto-incrementing counter:

    Template:  { "tag": "Damage_Particles", "value": "HP_turret_{damage_idx}_EMIT" }
    Output:    <Damage_Particles>HP_turret_01_EMIT</Damage_Particles>

  Counter config (ship config root):
    "damage_particles": { "start": 1, "format": "02d" }

  The damage_particles counter is INDEPENDENT of the turret_models counter.

=============================================================================
  TEMPLATES — FOLDER OR SINGLE FILE
=============================================================================

  "templates" in the ship config can be a .json file OR a folder.
  Folder mode scans recursively (sub-folders included).

=============================================================================
  INHERITANCE
=============================================================================

  Declare "inherits_from": "ParentName" to inherit all parent fields.
  Child fields replace parent fields of the same tag. Chains supported.
  Circular references are detected and aborted.

=============================================================================
  FIELD ENTRY FORMAT
=============================================================================

  { "tag": "T", "value": "text" }                 → <T>text</T>
  { "tag": "T", "value": "{bone_a}" }              → <T>HP_TL_01_L</T>
  { "tag": "T", "value": "{bone_b}" }              → <T>HP_TL_02_L</T>
  { "tag": "T", "value": "Base_{model_idx}.ALO" }      → <T>Base_01.ALO</T>
  { "tag": "T", "value": "PFX_{damage_idx}_S" }    → <T>PFX_01_S</T>
  { "tag": "T", "value": "", "empty_tag": true }   → <T/>
  { "_type": "blank" }
  { "_type": "section_comment", "text": "LABEL:" }
  { "_type": "inline_comment", "text": "  <Tag>v</Tag>" }

=============================================================================
  SHIP CONFIG — KEY REFERENCE
=============================================================================

  "ship_name"        : in trailing hardpoint-list comment
  "output_file"      : path to write generated XML
  "templates"        : file or folder (recursive)
  "turret_models"    : { "start": 1, "format": "02d" }
  "damage_particles" : { "start": 1, "format": "02d" }

  Group fields:
    template, name_prefix, bones  (required)
    group_comment, start_index, index_format  (optional)
    model_base  (LEGACY — see turret model notes above)

  Placeholders in name_prefix and group_comment:
    {shipname}     — replaced with the ship_name value from the config.
                     Spaces are removed when used in name_prefix so that
                     "Test Cruiser" → "TestCruiser" in the HP name.
                     Spaces are kept in group_comment.
    {templatename} — replaced with the group's template name (same space rules).

"""

import json
import argparse
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Template Loading
# ---------------------------------------------------------------------------

def load_templates(path: str) -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        print(f"ERROR: Templates path not found: {path}", file=sys.stderr)
        sys.exit(1)
    if p.is_file():
        files = [p]
    elif p.is_dir():
        files = sorted(p.rglob("*.json"))
        if not files:
            print(f"ERROR: No .json files found in: {path}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"ERROR: Templates path is neither file nor folder: {path}", file=sys.stderr)
        sys.exit(1)

    registry: dict[str, dict] = {}
    for fpath in files:
        data = _load_json(str(fpath))
        for tpl in data.get("templates", []):
            name = tpl.get("name", "")
            if not name:
                continue
            if name in registry:
                print(f"WARNING: Duplicate template '{name}' in {fpath.name} — overwriting.",
                      file=sys.stderr)
            registry[name] = tpl
    return registry


# ---------------------------------------------------------------------------
# Inheritance Resolution
# ---------------------------------------------------------------------------

def resolve_all_inheritance(registry: dict[str, dict]) -> dict[str, dict]:
    resolved: dict[str, dict] = {}

    def resolve(name: str, visiting: list[str]) -> dict:
        if name in resolved:
            return resolved[name]
        if name not in registry:
            raise ValueError(f"Template '{name}' not found in the registry.")
        if name in visiting:
            cycle = " -> ".join(visiting + [name])
            raise ValueError(f"Circular inheritance detected: {cycle}")

        tpl = dict(registry[name])
        parent_name = tpl.get("inherits_from", "").strip()

        if not parent_name:
            resolved[name] = tpl
            return tpl

        parent = resolve(parent_name, visiting + [name])
        merged = dict(tpl)
        merged["fields"] = _merge_fields(parent.get("fields", []), tpl.get("fields", []))
        if not tpl.get("parent_comment", "").strip():
            merged["parent_comment"] = parent.get("parent_comment", "")
        resolved[name] = merged
        return merged

    for name in registry:
        try:
            resolve(name, [])
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    return resolved


def _merge_fields(parent_fields: list, child_fields: list) -> list:
    child_overrides: dict[str, list] = {}
    child_structural: list = []

    for entry in child_fields:
        ftype = entry.get("_type", "element")
        if ftype != "element":
            child_structural.append(entry)
            continue
        tag = entry.get("tag", "")
        if tag:
            child_overrides.setdefault(tag, []).append(entry)

    merged: list = []
    emitted: set[str] = set()

    for entry in parent_fields:
        ftype = entry.get("_type", "element")
        if ftype != "element":
            merged.append(entry)
            continue
        tag = entry.get("tag", "")
        if tag in child_overrides:
            if tag not in emitted:
                merged.extend(child_overrides[tag])
                emitted.add(tag)
        else:
            merged.append(entry)

    for tag, entries in child_overrides.items():
        if tag not in emitted:
            merged.extend(entries)

    merged.extend(child_structural)
    return merged


# ---------------------------------------------------------------------------
# Field Rendering
# ---------------------------------------------------------------------------

def render_field(field: dict,
                 bone_a: str,
                 bone_b: str = "",
                 bone_c: str = "",
                 bone_d: str = "",
                 bone_e: str = "",
                 bone_f: str = "",
                 model: str = "",
                 damage_idx: str = "") -> str | None:
    """
    Render one field entry.  Substitutions:
      {bone}/{bone_a} → bone_a
      {bone_b}        → bone_b (fallback: bone_a)
      {bone_c}        → bone_c (fallback: bone_a) — typically Attachment_Bone
      {bone_d}        → bone_d (fallback: bone_a) — typically Collision_Mesh
      {bone_e}        → bone_e — stays EMPTY if not set (no fallback to bone_a) - typically Damage_Particles
      {bone_f}        → bone_f — stays EMPTY if not set (no fallback to bone_a) - typically Damage_Decal
      {model_idx}     → model string
      {damage_idx}    → damage_particles counter string
    """
    ftype = field.get("_type", "element")
    if ftype == "blank":
        return ""
    if ftype == "section_comment":
        return f"\t\t<!-- {field.get('text', '')}\n\t\t-->"
    if ftype == "inline_comment":
        return f"\t\t<!--{field.get('text', '')}-->"

    tag = field.get("tag", "")
    if not tag:
        return None

    value = str(field.get("value", ""))
    eff_b = bone_b if bone_b else bone_a
    eff_c = bone_c if bone_c else bone_a
    eff_d = bone_d if bone_d else bone_a
    eff_e = bone_e 
    eff_f = bone_f

    value = value.replace("{bone}",       bone_a)
    value = value.replace("{bone_a}",     bone_a)
    value = value.replace("{bone_b}",     eff_b)
    value = value.replace("{bone_c}",     eff_c)
    value = value.replace("{bone_d}",     eff_d)
    value = value.replace("{bone_e}",     eff_e)
    value = value.replace("{bone_f}",     eff_f)
    value = value.replace("{model_idx}",  model)
    value = value.replace("{damage_idx}", damage_idx)

    empty_tag = field.get("empty_tag", False)

    if empty_tag:
        return f"\t\t<{tag}/>"
    elif value == "":
        return f"\t\t<{tag}></{tag}>"
    else:
        return f"\t\t<{tag}>{value}</{tag}>"


# ---------------------------------------------------------------------------
# Component Loading  (same JSON format as templates)
# ---------------------------------------------------------------------------

def load_components(path: str) -> dict[str, dict]:
    """
    Load component definitions from *path* (file or folder).
    Components use exactly the same JSON format as templates.
    Returns a flat registry  {name: raw_dict}.
    """
    p = Path(path)
    if not p.exists():
        print(f"WARNING: Components path not found: {path}", file=sys.stderr)
        return {}
    if p.is_file():
        files = [p]
    elif p.is_dir():
        files = sorted(p.rglob("*.json"))
        if not files:
            print(f"WARNING: No .json component files found in: {path}", file=sys.stderr)
            return {}
    else:
        return {}

    registry: dict[str, dict] = {}
    for fpath in files:
        try:
            data = _load_json(str(fpath))
        except Exception as e:
            print(f"WARNING: Could not load component file {fpath.name}: {e}", file=sys.stderr)
            continue
        for tpl in data.get("templates", []):
            name = tpl.get("name", "")
            if not name:
                continue
            if name in registry:
                print(f"WARNING: Duplicate component '{name}' in {fpath.name} — overwriting.",
                      file=sys.stderr)
            registry[name] = tpl
    return registry


def resolve_component_inheritance(registry: dict[str, dict]) -> dict[str, dict]:
    """Resolve inheritance within the component registry (same logic as templates)."""
    resolved: dict[str, dict] = {}

    def resolve(name: str, visiting: list[str]) -> dict:
        if name in resolved:
            return resolved[name]
        if name not in registry:
            raise ValueError(f"Component '{name}' not found in the component registry.")
        if name in visiting:
            cycle = " -> ".join(visiting + [name])
            raise ValueError(f"Circular component inheritance: {cycle}")
        tpl = dict(registry[name])
        parent_name = tpl.get("inherits_from", "").strip()
        if not parent_name:
            resolved[name] = tpl
            return tpl
        parent = resolve(parent_name, visiting + [name])
        merged = dict(tpl)
        merged["fields"] = _merge_fields(parent.get("fields", []), tpl.get("fields", []))
        if not tpl.get("parent_comment", "").strip():
            merged["parent_comment"] = parent.get("parent_comment", "")
        resolved[name] = merged
        return merged

    for name in registry:
        try:
            resolve(name, [])
        except ValueError as e:
            print(f"WARNING: {e}", file=sys.stderr)
    return resolved


def apply_components(base_fields: list,
                     component_names: list[str],
                     resolved_component_registry: dict[str, dict]) -> list:
    """
    Apply an ordered list of components onto *base_fields*.

    Each component's fields are merged over the accumulated result using the
    same tag-replacement logic as template inheritance (_merge_fields).
    Components are applied left-to-right, so later components win conflicts.

    Returns the final merged field list.
    """
    result = list(base_fields)
    for comp_name in component_names:
        comp = resolved_component_registry.get(comp_name)
        if comp is None:
            print(f"WARNING: Component '{comp_name}' not found — skipping.", file=sys.stderr)
            continue
        result = _merge_fields(result, comp.get("fields", []))
    return result


def render_hardpoint(name: str,
                     template: dict,
                     bone_a: str,
                     bone_b: str = "",
                     bone_c: str = "",
                     bone_d: str = "",
                     bone_e: str = "",
                     bone_f: str = "",
                     model: str = "",
                     damage_idx: str = "",
                     component_names: list[str] | None = None) -> str:
    lines = [f'\t<HardPoint Name="{name}">']
    pc = template.get("parent_comment", "")
    if pc:
        lines.append(f"\t\t<!-- PARENT: {pc}\n\t\t-->")
    if component_names:
        comp_list = "\n\t\t".join(component_names)
        lines.append(f"\t\t<!-- COMPONENTS: \n\t\t{comp_list}\n\t\t-->")
    for field in template.get("fields", []):
        r = render_field(field, bone_a, bone_b, bone_c, bone_d, bone_e, bone_f, model, damage_idx)
        if r is not None:
            lines.append(r)
    lines.append("\t</HardPoint>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Name & Bone Resolution
# ---------------------------------------------------------------------------

def resolve_bone_entry(entry) -> tuple[str, str, str, str, str, str, str | None]:
    """
    Return (bone_a, bone_b, bone_c, bone_d, bone_e, bone_f, name_override).
    bone_b defaults to bone_a when not explicitly specified.
    bone_c, bone_d, bone_e, bone_f default to "" (render_field falls back to bone_a).
    """
    if isinstance(entry, str):
        return entry, entry, "", "", "", "", None
    if isinstance(entry, dict):
        bone_a = entry.get("bone_a") or entry.get("bone", "")
        bone_b = entry.get("bone_b") or bone_a
        bone_c = entry.get("bone_c", "")
        bone_d = entry.get("bone_d", "")
        bone_e = entry.get("bone_e", "")
        bone_f = entry.get("bone_f", "")
        return bone_a, bone_b, bone_c, bone_d, bone_e, bone_f, entry.get("name", None)
    return "", "", "", "", "", "", None


def build_hardpoint_name(prefix: str, index: int, fmt: str) -> str:
    return f"{prefix}_{format(index, fmt)}"


# ---------------------------------------------------------------------------
# Main Generation
# ---------------------------------------------------------------------------

def generate(ship_config_path: str,
             templates_path: str | None = None,
             output_path: str | None    = None,
             list_only: bool            = False,
             dump_template: str | None  = None) -> None:

    ship_config = _load_json(ship_config_path)
    ship_name   = ship_config.get("ship_name", "Ship")
    groups      = ship_config.get("groups", [])

    tpl_path = (templates_path
                or ship_config.get("templates")
                or ship_config.get("templates_file")
                or "Templates")

    raw_registry      = load_templates(tpl_path)
    resolved_registry = resolve_all_inheritance(raw_registry)

    # Load components (optional — no error if not configured)
    comp_path = ship_config.get("components", "")
    if comp_path:
        raw_comp_registry      = load_components(comp_path)
        resolved_comp_registry = resolve_component_inheritance(raw_comp_registry)
    else:
        resolved_comp_registry = {}

    if dump_template:
        _dump_template(dump_template, resolved_registry)
        return

    out_file = output_path or ship_config.get("output_file", f"Hardpoints_{ship_name}.xml")

    model_cfg    = ship_config.get("turret_models", {})
    model_start  = model_cfg.get("start", 1)
    model_format = model_cfg.get("format", "02d")

    dmg_cfg    = ship_config.get("damage_particles", {})
    dmg_start  = dmg_cfg.get("start", 1)
    dmg_format = dmg_cfg.get("format", "02d")

    model_counters: dict[str, int] = {}
    dmg_counters:   dict[str, int] = {}

    name_index_counters: dict[tuple, int] = {}

    def _pattern_for(template: dict, placeholder: str) -> str:
        """Return the first field-value string containing *placeholder*, or ''."""
        for f in template.get("fields", []):
            if f.get("_type", "element") == "element":
                v = str(f.get("value", ""))
                if placeholder in v:
                    return v
        return ""

    # Validate templates
    for g in groups:
        tpl_name = g.get("template", "")
        if tpl_name not in resolved_registry:
            print(f"ERROR: Template '{tpl_name}' not found.\n"
                  f"Available: {list(resolved_registry.keys())}", file=sys.stderr)
            sys.exit(1)

    def _uses(template, ph):
        return any(ph in str(f.get("value", ""))
                   for f in template.get("fields", [])
                   if f.get("_type", "element") == "element")

    all_blocks: list[str] = []
    all_names:  list[str] = []

    for group in groups:
        base_template = resolved_registry[group["template"]]
        tpl_name      = group["template"]
        name_prefix   = group.get("name_prefix", "HP_Unnamed")
        bones         = group.get("bones", [])
        start_index   = group.get("start_index", 1)
        index_format  = group.get("index_format", "02d")
        group_comment = group.get("group_comment", "")
        model_base    = group.get("model_base", "")  # legacy
        comp_names    = group.get("components", [])  # list of component names

        ship_name_nospace = ship_name.replace(" ", "")
        tpl_name_nospace  = tpl_name.replace(" ", "")
        name_prefix = (name_prefix
                       .replace("{shipname}",    ship_name_nospace)
                       .replace("{templatename}", tpl_name_nospace))
        group_comment = (group_comment
                         .replace("{shipname}",    ship_name)
                         .replace("{templatename}", tpl_name))

        ni_key = (name_prefix, tpl_name, index_format)
        if ni_key not in name_index_counters:
            name_index_counters[ni_key] = start_index
        effective_start = name_index_counters[ni_key]

        if comp_names and resolved_comp_registry:
            effective_fields = apply_components(
                base_template.get("fields", []),
                comp_names,
                resolved_comp_registry
            )
        else:
            effective_fields = list(base_template.get("fields", []))
            comp_names = []

        group_overrides = group.get("field_overrides", [])
        if group_overrides:
            effective_fields = _merge_fields(effective_fields, group_overrides)

        if effective_fields is not base_template.get("fields", []):
            template = dict(base_template)
            template["fields"] = effective_fields
        else:
            template = base_template

        uses_model  = _uses(template, "{model_idx}")
        uses_damage = _uses(template, "{damage_idx}")

        if group_comment:
            all_blocks.append(f"\n\t<!-- {group_comment}\n\t-->\n\t")

        for i, bone_entry in enumerate(bones):
            bone_a, bone_b, bone_c, bone_d, bone_e, bone_f, name_override = resolve_bone_entry(bone_entry)
            index   = effective_start + i
            hp_name = name_override or build_hardpoint_name(name_prefix, index, index_format)
            all_names.append(hp_name)

            if not list_only:
                # --- Model string ---
                if uses_model:
                    fmt = f"{{:{model_format}}}"
                    if model_base:
                        pat = f"{model_base}_{{model_idx}}.ALO"
                    else:
                        pat = _pattern_for(template, "{model_idx}")
                    if pat not in model_counters:
                        model_counters[pat] = model_start
                    if model_base:
                        model_str = f"{model_base}_{fmt.format(model_counters[pat])}.ALO"
                    else:
                        model_str = fmt.format(model_counters[pat])
                    model_counters[pat] += 1
                else:
                    model_str = ""

                # --- Damage_Particles string ---
                if uses_damage:
                    fmt = f"{{:{dmg_format}}}"
                    pat = _pattern_for(template, "{damage_idx}")
                    if pat not in dmg_counters:
                        dmg_counters[pat] = dmg_start
                    damage_str = fmt.format(dmg_counters[pat])
                    dmg_counters[pat] += 1
                else:
                    damage_str = ""

                all_blocks.append(render_hardpoint(
                    hp_name, template, bone_a, bone_b, bone_c, bone_d, bone_e, bone_f,
                    model_str, damage_str,
                    component_names=comp_names if comp_names else None
                ))
            else:
                if uses_model:
                    pat = (f"{model_base}_{{model_idx}}.ALO" if model_base
                           else _pattern_for(template, "{model_idx}"))
                    if pat not in model_counters:
                        model_counters[pat] = model_start
                    model_counters[pat] += 1
                if uses_damage:
                    pat = _pattern_for(template, "{damage_idx}")
                    if pat not in dmg_counters:
                        dmg_counters[pat] = dmg_start
                    dmg_counters[pat] += 1

        name_index_counters[ni_key] = effective_start + len(bones)

    if list_only:
        print(f"\nHardpoints for: {ship_name}")
        print(f"Total: {len(all_names)}\n")
        for name in all_names:
            print(f"  {name}")
        return

    xml_parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<!-- Generated with Venator's EaW Hardpoint Generator v1.0. -->",
        "",
        "<HardPoints>",
        *all_blocks,
        "",
        "</HardPoints>",
        _build_list_comment(ship_name, all_names),
    ]
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(xml_parts))

    print(f"Generated: {out_file}")
    print(f"Total hardpoints: {len(all_names)}")

    # Summary
    sum_model: dict[str, int] = {}
    sum_dmg:   dict[str, int] = {}
    for group in groups:
        bc    = len(group.get("bones", []))
        tplN  = group.get("template", "?")
        label = group.get("group_comment") or group.get("name_prefix", "?")
        tpl   = resolved_registry.get(tplN, {})

        comp_names_s = group.get("components", [])
        if comp_names_s and resolved_comp_registry:
            eff = dict(tpl)
            eff["fields"] = apply_components(tpl.get("fields", []),
                                              comp_names_s, resolved_comp_registry)
        else:
            eff = tpl

        extras = []
        if _uses(eff, "{model_idx}"):
            fmt  = f"{{:{model_format}}}"
            mb   = group.get("model_base", "")
            pat  = (f"{mb}_{{model_idx}}.ALO" if mb else _pattern_for(eff, "{model_idx}"))
            cur  = sum_model.get(pat, model_start)
            first = (f"{mb}_{fmt.format(cur)}.ALO" if mb else fmt.format(cur))
            last  = (f"{mb}_{fmt.format(cur+bc-1)}.ALO" if mb else fmt.format(cur+bc-1))
            extras.append(f"models:{first}…{last}")
            sum_model[pat] = cur + bc
        if _uses(eff, "{damage_idx}"):
            fmt = f"{{:{dmg_format}}}"
            pat = _pattern_for(eff, "{damage_idx}")
            cur = sum_dmg.get(pat, dmg_start)
            extras.append(f"damage:{fmt.format(cur)}…{fmt.format(cur+bc-1)}")
            sum_dmg[pat] = cur + bc

        ext = f"  [{', '.join(extras)}]" if extras else ""
        print(f"  [{tplN}] {label} — {bc} hardpoint(s){ext}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in '{path}':\n  {e}", file=sys.stderr)
        sys.exit(1)


def _build_header_comment(title: str, subtitle: str | None = None) -> str:
    lines = [f"<!-- {title}"]
    if subtitle:
        lines.append(f"\t{subtitle}")
    lines.append("\t-->")
    return "\n".join(lines)


def _build_list_comment(ship_name: str, names: list[str]) -> str:
    lines = [f"<!-- HARDPOINT LIST: {ship_name}"]
    for i, name in enumerate(names):
        lines.append(f"\t\t{name}{',' if i < len(names)-1 else ''}")
    lines.append("\t-->")
    return "\n".join(lines)


def _dump_template(name: str, registry: dict[str, dict]) -> None:
    if name not in registry:
        print(f"ERROR: Template '{name}' not found.", file=sys.stderr)
        print(f"Available: {list(registry.keys())}", file=sys.stderr)
        sys.exit(1)
    tpl = registry[name]
    print(f"\n=== Template: {name} ===")
    if tpl.get("inherits_from", ""):
        print(f"    Inherits from: {tpl['inherits_from']}  (fields shown are fully merged)")
    print(f"    parent_comment: {tpl.get('parent_comment','')}")
    print(f"    Fields ({len(tpl.get('fields',[]))}):")
    for field in tpl.get("fields", []):
        ftype = field.get("_type", "element")
        if ftype == "blank":         print()
        elif ftype == "section_comment": print(f"      <!-- {field.get('text','')} -->")
        elif ftype == "inline_comment":  print(f"      <!--{field.get('text','')}-->")
        else:
            tag      = field.get("tag","?")
            value    = field.get("value","")
            extra    = " [empty_tag]" if field.get("empty_tag") else ""
            print(f"      <{tag}>{value}</{tag}>{extra}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="EaW Hardpoint Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ship_config")
    p.add_argument("--templates", "-t", metavar="PATH")
    p.add_argument("--output",    "-o", metavar="PATH")
    p.add_argument("--list",      "-l", action="store_true")
    p.add_argument("--dump",      "-d", metavar="TEMPLATE_NAME")
    args = p.parse_args()
    generate(args.ship_config, args.templates, args.output, args.list, args.dump)


if __name__ == "__main__":
    main()
