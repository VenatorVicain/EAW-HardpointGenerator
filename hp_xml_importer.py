#!/usr/bin/env python3
"""
hp_xml_importer.py — Convert EaW HardPoints XML files into hp_generator template dicts.
For Star Wars: Empire at War (Petroglyph / Lucasarts).

Public API
----------
    from hp_xml_importer import parse_hardpoints_from_xml, XmlImportError

    templates, warnings = parse_hardpoints_from_xml("Hardpoints_Republic_Space.xml")
    # templates : list[dict]  — template dicts ready for hp_generator / Template Editor
    # warnings  : list[str]   — non-fatal notes (duplicate names, skipped elements, etc.)

Template format produced
------------------------
Each <HardPoint Name="HP_..."> element becomes one template dict:

    {
        "name":           "HP_...",          # from Name attribute
        "parent_comment": "HP_...",          # same as name (used by generator)
        "inherits_from":  "",                # no inheritance — direct conversion
        "fields": [
            {"_type": "inline_comment", "text": " Imported from XML ... "},
            {"tag": "Type",  "value": "HARD_POINT_WEAPON_LASER"},
            ...
            {"tag": "Fire_Bone_A",      "value": "{bone_a}"},
            {"tag": "Fire_Bone_B",      "value": "{bone_b}"},
            {"tag": "Attachment_Bone",  "value": "{bone_c}"},
            {"tag": "Collision_Mesh",   "value": "{bone_d}"},
            {"tag": "Damage_Particles", "value": "{bone_e}"},
            {"tag": "Damage_Decal",     "value": "{bone_f}"},
            ...
        ]
    }

Bone placeholder substitution
------------------------------
  Fire_Bone_A      →  {bone_a}  (always)
  Fire_Bone_B      →  {bone_b}  (always)
  Attachment_Bone  →  {bone_c}  (always)
  Collision_Mesh   →  {bone_d}  (always)
  Damage_Particles →  {bone_e}  (always)
  Damage_Decal     →  {bone_f}  (always)

  Original bone names are preserved in a leading inline comment field.

XML comment handling
--------------------
  <!-- ... --> nodes inside a <HardPoint> are converted to inline_comment fields
  so they are preserved in the template and regenerated XML.

Empty elements
--------------
  <Tag></Tag> and <Tag/> both produce {"tag": "Tag", "value": ""}
  (self-closing output is left to the generator's empty_tag flag, which the
  user can toggle in the Template Editor if desired).
"""

import xml.etree.ElementTree as ET
from pathlib import Path

# ── Tag sets for bone substitution ───────────────────────────────────────────

# Always replaced with the corresponding placeholder regardless of value
_ALWAYS_BONE_A = frozenset({'Fire_Bone_A'})
_ALWAYS_BONE_B = frozenset({'Fire_Bone_B'})
_ALWAYS_BONE_C = frozenset({'Attachment_Bone'})
_ALWAYS_BONE_D = frozenset({'Collision_Mesh'})
_ALWAYS_BONE_E = frozenset({'Damage_Particles'})
_ALWAYS_BONE_F = frozenset({'Damage_Decal'})


# ── Public exception ─────────────────────────────────────────────────────────

class XmlImportError(Exception):
    """Raised when the XML file cannot be parsed as a valid EaW HardPoints file."""


# ── Public function ───────────────────────────────────────────────────────────

def parse_hardpoints_from_xml(
        path: "str | Path") -> "tuple[list[dict], list[str]]":
    """
    Parse an EaW HardPoints XML file and return (templates, warnings).

    Parameters
    ----------
    path : str or Path
        Path to the .xml file (UTF-8, optionally BOM-prefixed).

    Returns
    -------
    templates : list[dict]
        List of template dicts, one per <HardPoint> element found.
    warnings  : list[str]
        Non-fatal notes: duplicate names, skipped elements, empty file, etc.

    Raises
    ------
    XmlImportError
        On unrecoverable errors: file unreadable, not valid XML, wrong root tag.
    """
    path = Path(path)

    # ── Read & strip BOM ────────────────────────────────────────────────────
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise XmlImportError(f"Cannot read file: {exc}") from exc

    if raw.startswith(b'\xef\xbb\xbf'):   # UTF-8 BOM
        raw = raw[3:]
    elif raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        # UTF-16 BOM — decode to UTF-8 bytes for the parser
        enc = 'utf-16-le' if raw[0] == 0xff else 'utf-16-be'
        raw = raw[2:].decode(enc, errors='replace').encode('utf-8')

    # ── Parse XML with comment preservation (Python 3.8+) ──────────────────
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root   = ET.fromstring(raw.decode('utf-8', errors='replace'), parser=parser)
    except ET.ParseError as exc:
        raise XmlImportError(f"XML parse error: {exc}") from exc

    if root.tag != 'HardPoints':
        raise XmlImportError(
            f"Root element is <{root.tag}>, expected <HardPoints>. "
            "This does not appear to be an EaW hardpoints file.")

    # ── Walk <HardPoint> elements ───────────────────────────────────────────
    templates: list[dict] = []
    warnings:  list[str]  = []
    seen_names: set[str]  = set()

    for child in root:
        # Root-level XML comment nodes — skip silently
        if callable(child.tag):
            continue

        if child.tag != 'HardPoint':
            warnings.append(
                f"Unexpected root-level <{child.tag}> element — skipped.")
            continue

        hp_name = child.get('Name', '').strip()
        if not hp_name:
            warnings.append(
                "A <HardPoint> element has no Name attribute — skipped.")
            continue

        if hp_name in seen_names:
            warnings.append(
                f"Duplicate HardPoint name '{hp_name}' — second occurrence skipped.")
            continue
        seen_names.add(hp_name)

        tpl = _convert_hardpoint(child, hp_name)
        templates.append(tpl)

    if not templates:
        warnings.append(
            "No <HardPoint> entries were found in the file.")

    return templates, warnings


# ── Conversion helpers ────────────────────────────────────────────────────────

def _convert_hardpoint(hp_elem: ET.Element, name: str) -> dict:
    """Convert a single <HardPoint> element into a template dict."""

    # ── First pass: collect original bone values for the leading comment ──
    bone_a_orig: str = _find_text(hp_elem, 'Fire_Bone_A')
    bone_b_orig: str = _find_text(hp_elem, 'Fire_Bone_B')
    bone_c_orig: str = _find_text(hp_elem, 'Attachment_Bone')
    bone_d_orig: str = _find_text(hp_elem, 'Collision_Mesh')
    bone_e_orig: str = _find_text(hp_elem, 'Damage_Particles')
    bone_f_orig: str = _find_text(hp_elem, 'Damage_Decal')

    # ── Build fields list ────────────────────────────────────────────────────
    fields: list[dict] = []

    # Leading comment recording original bone names (only if bones are present)
    if bone_a_orig:
        note_parts = [f"Imported from XML — original bones: Fire_Bone_A={bone_a_orig}"]
        if bone_b_orig and bone_b_orig != bone_a_orig:
            note_parts.append(f"Fire_Bone_B={bone_b_orig}")
        if bone_c_orig:
            note_parts.append(f"Attachment_Bone={bone_c_orig}")
        if bone_d_orig:
            note_parts.append(f"Collision_Mesh={bone_d_orig}")
        if bone_e_orig:
            note_parts.append(f"Damage_Particles={bone_e_orig}")
        if bone_f_orig:
            note_parts.append(f"Damage_Decal={bone_f_orig}")
        note = ", ".join(note_parts)
        fields.append({"_type": "inline_comment", "text": f" {note} "})

    # ── Second pass: convert each child node ────────────────────────────────
    for node in hp_elem:

        # XML comment node — callable(tag) is ElementTree's marker
        if callable(node.tag):
            comment_text = (node.text or "").strip()
            if comment_text:
                fields.append({
                    "_type": "inline_comment",
                    "text":  f" {comment_text} ",
                })
            else:
                fields.append({"_type": "blank"})
            continue

        tag = node.tag.strip()
        if not tag:
            continue

        # Raw text value — preserve intentional leading/trailing spaces
        # (e.g. " Gunship, 3.0 ") but collapse pure-whitespace to ""
        raw_text: str = node.text if node.text is not None else ""
        value: str    = raw_text if raw_text.strip() else ""

        # ── Bone placeholder substitution ─────────────────────────────────
        if tag in _ALWAYS_BONE_A:
            value = "{bone_a}"
        elif tag in _ALWAYS_BONE_B:
            value = "{bone_b}"
        elif tag in _ALWAYS_BONE_C:
            value = "{bone_c}"
        elif tag in _ALWAYS_BONE_D:
            value = "{bone_d}"
        elif tag in _ALWAYS_BONE_E:
            value = "{bone_e}"
        elif tag in _ALWAYS_BONE_F:
            value = "{bone_f}"

        # ── Build field dict ───────────────────────────────────────────────
        field: dict = {"tag": tag, "value": value}

        fields.append(field)

    return {
        "name":           name,
        "parent_comment": name,
        "inherits_from":  "",
        "fields":         fields,
    }


def _find_text(elem: ET.Element, tag: str) -> str:
    """Return the stripped text content of the first child with matching tag, or ''."""
    for child in elem:
        if not callable(child.tag) and child.tag == tag:
            return (child.text or "").strip()
    return ""
