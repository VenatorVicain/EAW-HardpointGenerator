# Venator's EaW Hardpoint Generator

A powerful GUI tool for generating hardpoint XML files for **Star Wars: Empire at War** modding. Built to eliminate the tedious, error-prone process of hand-writing hundreds of nearly identical XML hardpoint entries — letting you define templates once and generate entire fleets of consistent hardpoints in seconds.

---

## Table of Contents

1. [What Is This?](#what-is-this)
2. [Requirements & Installation](#requirements--installation)
3. [File Structure](#file-structure)
4. [Quick Start (5 Minutes to Your First XML)](#quick-start-5-minutes-to-your-first-xml)
5. [Interface Overview](#interface-overview)
6. [The Sidebar](#the-sidebar)
7. [Bone Pool](#bone-pool)
8. [Groups](#groups)
9. [Group Editor — Settings](#group-editor--settings)
10. [Group Editor — Bones Tab](#group-editor--bones-tab)
11. [Group Editor — Components Tab](#group-editor--components-tab)
12. [Group Editor — Field Overrides Tab](#group-editor--field-overrides-tab)
13. [Template Browser](#template-browser)
14. [Component Browser](#component-browser)
15. [Template Editor](#template-editor)
16. [Generating XML](#generating-xml)
17. [Template File Format](#template-file-format)
18. [Field Types & Placeholders Reference](#field-types--placeholders-reference)
19. [Template Inheritance](#template-inheritance)
20. [Components System](#components-system)
21. [Ship Config Reference](#ship-config-reference)
22. [Exclude / Include Filters](#exclude--include-filters)
23. [ALO Bone Import](#alo-bone-import)
24. [XML Hardpoint Import](#xml-hardpoint-import)
25. [Keyboard Shortcuts](#keyboard-shortcuts)
26. [Tips, Tricks & Best Practices](#tips-tricks--best-practices)
27. [Troubleshooting](#troubleshooting)

---

## What Is This?

In Empire at War, every ship's weapons, shields, engines, and systems are defined as **hardpoints** — individual XML entries in files like `Hardpoints_Empire_Space.xml`. A large capital ship might have 30–80 of these entries, each nearly identical but with different bone names and numbering.

**The Hardpoint Generator** solves this by letting you:

- **Define templates** — reusable blueprints for each hardpoint type (e.g., light turbolaser, ion cannon, shield generator).
- **Build a bone pool** — all the hardpoint bone names from your model's skeleton.
- **Organize groups** — each group links a template to a set of bones, producing one XML entry per bone.
- **Generate the XML** — the tool assembles everything into a valid, game-ready XML file in one click.

Instead of writing 40 nearly identical `<HardPoint>` blocks by hand, you write one template and assign 40 bones. The generator does the rest.

---

## Requirements & Installation

### Requirements

- **Python 3.10 or newer** (uses `match`, `X | Y` type hints)
- **tkinter** — included with most Python distributions (on Linux, install `python3-tk`)
- No external Python packages required

### Files

The following files must all be in the **same directory**:

| File | Required | Purpose |
|---|---|---|
| `hp_generator_GUI.py` | ✅ Always | The graphical application |
| `hp_generator.py` | ✅ Always | XML generation engine |
| `alo_reader.py` | Optional | Enables bone import from `.ALO` model files |
| `hp_xml_importer.py` | Optional | Enables hardpoint import from existing `.XML` files |

Don't worry, these should be packaged with the HardpointGenerator.exe by default!

### Running the Application

Simply run HardpointGenerator.exe

### Recommended Folder Structure

```
HardpointGenerator/
├── HardpointGenerator.exe
├── Templates/
│   ├── Templates_Weapon_Generic.json
│   ├── Templates_Weapon_Ion.json
│   └── Templates_Shield.json
├── Components/
│   ├── Component_Targetable.json
│   └── Component_Turrets.json
├── Hardpoints/               ← Generated XML files go here
│   └── Hardpoints_MyShip.xml
└── Ship Configs/
    └── MyShip.json
```

---

## File Structure

### Ship Config (`*.json`)

The central file that ties everything together. It tells the generator which templates to use, where to write the output, and defines all the groups and bones for a specific ship.

### Templates (`Templates/*.json`)

JSON files defining reusable hardpoint blueprints. One file can contain multiple templates. Templates support inheritance — a "Light Turbolaser Turret" child template can inherit from a "Generic Weapon" parent.

### Components (`Components/*.json`)

Optional field overrides that can be layered on top of any template, per group. They use the same JSON format as templates. Useful for sharing settings (like `Is_Targetable Yes`) across many different groups without duplicating fields.

### Generated XML

The final output — a valid EaW hardpoint XML file ready to be referenced in ``Hardpointdatafiles.xml` and used in-game.

---

## Quick Start (5 Minutes to Your First XML)

### Step 1 — Launch the application

Launch HardpointGenerator.exe

A new, blank ship config is created automatically.

### Step 2 — Set the ship name and output path

In the left sidebar:
- **Ship Name:** `MyShip` (used in comments and arguments in the XML and program)
- **Output File:** `Hardpoints/Hardpoints_MyShip.xml` (where the XML will be written)
- **Templates Path:** `Templates` (the folder containing your template JSON files)
- **Components Path** `Components` (the folder containing your component JSON files)

Click the **📁** button to browse for folders, or **📄** to pick a single JSON file.

### Step 3 — Add bones to the pool

In the **Bones & Groups** tab, click **+ Bone** or **+ Sequence** to manually add bone names from your model, or **📥 From ALO…** to extract them automatically from a `.ALO` model file.

Example bones for a simple ship:
```
HP_Weapon_Turbolaser_L_01
HP_Weapon_Turbolaser_L_02
HP_Weapon_Turbolaser_R_01
HP_Weapon_Turbolaser_R_02
```

### Step 4 — Create a group

Click **+ Group** in the Groups panel. In the **Group Editor** that appears below:
- **Template:** Select `Hardpoint_Weapon_Generic` (or whichever template you have)
- **Name Prefix:** `HP_MyShip_Turbolaser_L`
- **Group Comment:** `MyShip, Turbolasers, Port`

### Step 5 — Assign bones to the group

Select the port turbolaser bones in the Bone Pool, then click **▶ Assign Selected to Group**. The assignment dialog lets you choose which bone column to fill (A–E) and from which row.

### Step 6 — Generate!

Press **F5** or click **⚡ Generate XML**. The output file is written and a summary is printed in the Output Log.

---

## Interface Overview

The application window has four main areas:

```
┌─────────────────────────────────────────────────────────────────┐
│  Toolbar (New, Open, Save, Generate, Reload…)                   │
├──────────────┬──────────────────────────────────────────────────┤
│              │  Notebook Tabs:                                  │
│   Sidebar    │  • Bones & Groups  (main workflow)               │
│   (Config,   │  • Template Browser (inspect loaded templates)   │
│    Paths,    │  • Component Browser (inspect loaded components) │
│    Preview)  │  • Template Editor  (create/edit                 │
│              │    template + component files)                   │
│              │                                                  │
├──────────────┴──────────────────────────────────────────────────┤
│  Output Log                                                     │
└─────────────────────────────────────────────────────────────────┘
```

All panes are resizable. Drag the dividers to customise your layout.

---

## The Sidebar

The sidebar on the left contains all the global ship configuration fields.

### Ship Name

The name of the ship. Used in the auto-generated comment at the bottom of the XML file and as the `{shipname}` placeholder in group name prefixes and comments.

**Example:** `MyShip` → Name prefix `HP_{shipname}_{templatename}_L` becomes `HP_MyShip_Turbolaser_L`

### Output File

Path to write the generated XML. Can be relative to the application folder (e.g., `Hardpoints/Hardpoints_MyShip.xml`) or absolute. Click **…** to browse.

### Templates Path

The folder containing your template JSON files, or a specific JSON file. Click **📁** for a folder or **📄** for a single file. After changing this, click **↺ Reload Templates** (or it reloads automatically when you browse).

### Components Path

Same as Templates Path but for component JSON files. Components are optional — leave blank if you don't want to use them.

### Turret Models

Controls the `{model_idx}` counter:
- **Start:** The first number (default `1`)
- **Format:** Python format string (default `02d` → `01`, `02`, `03`, …)

Use this when your template has a field like `<Model_To_Attach>T_Turret_Imperial_{model_idx}.ALO</Model_To_Attach>`. Each hardpoint gets a unique sequential number.

### JSON Preview

A live preview of the current ship config as JSON, showing the first 80 lines. Useful for sanity-checking before saving.

### File Info

Shows the save path, group count, bone count, template count, and component count at a glance.

---

## Bone Pool

The **Bone Pool** is the master list of all hardpoint bones for this ship. It is displayed in the left panel of the Bones & Groups tab.

Bones in the pool are colour-coded:
- **Grey** — Not yet assigned to any group
- **White** — Assigned to exactly one group
- **Peach/Orange** — Assigned to multiple groups

### Adding Bones Manually

Click **+ Bone**. Enter the bone name exactly as it appears in your `.ALO` model (case-sensitive). Optionally enter a **Custom HP Name** — this overrides the auto-generated hardpoint name for that specific bone (useful for a shield or engine hardpoint that needs a fixed name rather than `_01`, `_02`, etc.).

### Adding a Sequence

Click **+ Sequence** to bulk-add bones that follow a pattern.

| Field | Description | Example |
|---|---|---|
| Prefix | Common name start | `HP_MyShip_TL` |
| From # | Starting number | `1` |
| Count | How many to generate | `10` |
| Format | Number format | `02d` (→ `01`, `02`, …) |
| Suffix | Common name end | `_L` |

The **Preview** pane shows exactly which names will be added. Check **Skip bones already in pool** to avoid duplicates when extending an existing sequence.

The **↑ Find Next** button scans the existing pool and automatically sets "From #" to one past the highest existing number matching your prefix — perfect for extending a sequence without gaps or overlaps.

### Importing from ALO Files

Click **📥 From ALO…** to open the ALO Import dialog.

1. Click **📂 Browse .ALO File(s)…** and select one or more `.ALO` model files.
2. The tool extracts every bone name from the skeleton.
3. Use the filter and quick-select buttons to choose which bones to add.
   - **Suggested** — selects all bones except those suggested to be excluded
   - **All excl. Root** — everything except the root skeleton node
   - **All / None** — select or deselect everything
4. Click **Add Selected to Pool**.

Colour coding in the dialog:
- **White** — New bone, will be added
- **Grey** — Already in the pool
- **Yellow** — Suggested exclude (shadow meshes, particle emitters, collision objects)

> **Tip:** For most ships, The tool automatically suggests excluding bones like `ShadowMesh`, `PE_Fire`, `ObjObject`, etc.

### Editing and Deleting Bones

- **Double-click** a bone, or select it and click **✎ Edit**, to rename it or change its Custom HP Name.
- Press **Delete** or click **✕ Delete** to remove selected bones. If a bone is assigned to a group, you'll be warned before it's removed from those groups too.

### Filtering the Pool

Type in the Filter box to narrow the displayed list by bone name or custom name. The filter is case-insensitive.

---

## Groups

Each **Group** links one template to a set of bones, generating one hardpoint entry per bone. Groups are displayed in the upper-right panel of the Bones & Groups tab.

The Groups list shows:
- **#** — Group number (order in the XML)
- **Comment / Prefix** — The group comment or name prefix
- **Template** — The template assigned to this group (⚠ if not found)
- **Bones** — How many bones are assigned
- **Components** — Components applied to this group (hover for full list)
- **Field Overrides** — Field tags overridden for this group (hover for full list)

> **Tip:** Hover over the Components or Field Overrides cell in the list to see the complete list in a popup — handy when the full list is too long to display.

### Creating Groups

Click **+ Group** to add a new group. A default group with a placeholder template is created and selected immediately.

### Duplicating Groups

Select a group and click **⧉ Duplicate** to copy it with all settings and bone assignments. The duplicate is inserted directly below the original. Useful for quickly creating Port/Starboard or Top/Bottom variants.

### Reordering Groups

Use **↑ Up** and **↓ Down** to change a group's position in the list. Groups are output in order in the XML file.

### Deleting Groups

Select a group and click **✕ Delete**. Bone assignments within the group are lost, but the bones themselves remain in the pool.

---

## Group Editor — Settings

When a group is selected, the **Group Editor** panel appears below the Groups list. Changes are **auto-saved** as you type — there is no Save button needed.

### Group Comment

Appears as an XML comment before the group's hardpoints in the generated file:
```xml
<!-- Test Cruiser, Light Turbolasers, Port
-->
```

Supports placeholders:
- `{shipname}` → replaced with the Ship Name (spaces preserved)
- `{templatename}` → replaced with the template name (spaces preserved)

**Example:** `{shipname}, {templatename}` → `MyShip, Turbolaser`

### Name Prefix

The prefix for auto-generated hardpoint names. Combined with the start index and format:

```
Prefix:  HP_MyShip_Turbolaser_L
Start:   1
Format:  02d
→ HP_MyShip_Turbolaser_L_01, HP_MyShip_Turbolaser_L_02, …
```

Supports placeholders:
- `{shipname}` → Ship Name with spaces removed (e.g., `My Ship` → `MyShip`)
- `{templatename}` → Template name with spaces removed

**Example:** `HP_{shipname}_{templatename}` → `HP_MyShip_Hardpoint_Weapon_Generic`

### Template

The template to use for all hardpoints in this group. Click the dropdown or start typing to search. Click **👁** to jump to that template in the Template Browser.

A warning appears if the template uses `{model_idx}` (reminding you to check the counters in the sidebar).

### Start Index

The number to start from when auto-naming hardpoints. Normally `1`, but useful when you want multiple groups across different files to form a single continuous sequence (e.g., File A uses indices 1–10, File B uses 11–20).

> **Shared sequences:** If two groups share the same Name Prefix, template, and index format, the generator automatically continues the sequence from where the previous group ended — you don't need to calculate start indices manually.

### Index Format

A Python format specification controlling number formatting:
- `02d` → `01`, `02`, `03` (zero-padded to 2 digits — default)
- `03d` → `001`, `002`, `003`
- `d` → `1`, `2`, `3` (no padding)

### Health Override

Overrides the `<Health>` field value for this group specifically, without modifying the template. Leave blank to use the template's default. 
This is included purely for convenience, as you may manually override `<Health>` in the `Field Overrides` tab.

### Name Preview

A live preview showing what the first two hardpoint names in this group will be. Updates as you type.

---

## Group Editor — Bones Tab

This tab shows all bones assigned to this group, with their bone slot assignments and the generated hardpoint name for each.

### Columns

| Column | Description |
|---|---|
| # | Row number (determines the auto-index in the HP name) |
| Bone A | Primary bone — replaces `{bone_a}` / `{bone}` in template fields |
| Bone B | Secondary fire bone — replaces `{bone_b}` (defaults to Bone A if blank) |
| Bone C | Tertiary bone — replaces `{bone_c}` (defaults to Bone A if blank) |
| Bone D | Quaternary bone — replaces `{bone_d}` (defaults to Bone A if blank) |
| Bone E | Quinary bone — replaces `{bone_e}` (defaults to empty if blank) |
| Bone F | Senary bone — replaces `{bone_f}` (defaults to empty if blank) |
| Custom HP Name | Overrides the auto-generated name for this row only |
| Generated HP Name | Preview of the final hardpoint name |

Rows with extra bone slots filled (B–E) appear in **teal**; simple single-bone rows appear in white.

### Assigning Bones from the Pool

**From the Bone Pool panel:**
1. Select one or more bones in the Bone Pool.
2. Click **▶ Assign Selected to Group** (or right-click for the context menu).
3. The assignment dialog opens with your selected bones pre-selected.

**From the Group Editor:**
1. Click **+ From Pool** in the Bones tab.
2. The same assignment dialog opens.

### The Assignment Dialog

This dialog gives you full control over how bones are placed:

**Column selector (A–E):** Which bone slot to fill.
- **Column A** — Creates new rows, inserted at the chosen start row. Existing rows shift down.
- **Columns B–E** — Fills empty slots in existing rows from the start row onward. Overflow becomes new rows with Bone A left blank.

**Start from Row:** Where to begin filling. Click any row in the preview table to snap to it. Click a Bone A–E column header in the preview to also switch the bone column selector.

**Preview table:** Shows exactly what the group will look like after the assignment, colour-coded:
- **White** — Unchanged existing row
- **Grey** — Skipped (before start row)
- **Teal** — Slot filled in existing row
- **Blue** — New row with Bone A set
- **Yellow** — New row where Bone A is blank (overflow into B–E columns)

**Dynamic hint:** Text above the preview explains exactly what will happen in plain English.

### Editing a Bone Entry

Double-click a row, or select it and click **✎ Edit**, to open the bone entry editor. You can set all five bone slots and an optional custom name. Each slot has a searchable dropdown populated from the pool.

### Moving Bones

Use **↑** and **↓** buttons to reorder bone entries. The Generated HP Name column updates in real time as the numbering changes.

### Removing Bones

Select one or more rows and press **Delete** or click **✕ Remove**. The bones remain in the pool.

---

## Group Editor — Components Tab

Components are modular, optional field overrides that layer on top of the base template for this group only. They're defined in separate JSON files in the Components folder.

### Why Use Components?

Suppose you have 15 weapon groups, and 8 of them are targetable (`<Is_Targetable>Yes</Is_Targetable>`). Instead of creating 8 separate templates or using field overrides in every group, you create one **Component** called `Is_Targetable_True` and add it to those 8 groups. (This example component is already included in the files by default).

**Benefits:**
- Change one component → instantly affects all groups using it
- Mix and match: different groups can combine different components
- Cleaner templates: keep the base template minimal

### Adding a Component

1. In the Components tab, use the dropdown at the top to search for and select a component name.
2. Click **＋ Add**.

### Component Order

Components are applied left-to-right, top-to-bottom. When two components set the same field, **the later one wins**. Use **↑** and **↓** to control priority.

A warning appears if multiple assigned components override the same field. Click **Details…** to see exactly which fields conflict and which component wins.

### Viewing a Component

Select a component in the list and click **👁** to jump to the Component Browser and inspect its fields.

---

## Group Editor — Field Overrides Tab

Field Overrides allow you to override or extend the template's fields for this specific group, with the highest possible priority (applied after the template and all components). Perfect for one-off adjustments without needing a new template or component.

### Adding Overrides

Click the **Add:** buttons to insert fields:
- **Element** — A standard XML tag/value pair: `<Tag>Value</Tag>`
- **Section Comment** — A block comment: `<!-- LABEL: -->`
- **Inline Comment** — A single-line comment: `<!-- text -->`
- **Blank Line** — An empty line for visual separation in the XML

### Editing Fields

**Inline editing:** Double-click the **Tag** or **Value** cell to edit it directly in place. Press **Tab** to cycle to the next column, **Enter** or **Escape** to commit/cancel.

**Field Editor panel:** Select any row to populate the editor below the table. Changes apply automatically as you type.

**Field Editor fields:**
- **Type** — The field type (element, section_comment, inline_comment, blank)
- **Tag** — For elements: the XML tag name. For comments: the comment text.
- **Value** — The field value (supports all placeholders)
- **Empty tag** — When checked, outputs `<Tag/>` instead of `<Tag></Tag>`

### Load from Template

Click **📋 Load from Template** to populate the overrides list with the fully-resolved fields of the current template (including components). This is useful as a starting point for heavy customisation — you can then modify specific fields.

### Override Priority

The effective field order is:
1. Template base fields
2. Components (in list order)
3. **Field Overrides** (highest priority — always wins)

---

## Template Browser

The **Template Browser** tab lets you inspect all loaded templates in a searchable, sortable list.

### List Panel (Left)

- Click any column header to sort by that column. Click again to reverse.
- Type in the Filter box to search by template name or parent name.
- **Blue** entries are base templates (no parent). **White** entries inherit from a parent.
- Click **✏ Edit Template File…** to open the source JSON file in the Template Editor.

### Detail Panel (Right)

Selecting a template shows:
- **Name, Inherits from, Parent comment** — Basic metadata
- **Inheritance chain** — The full chain from root to this template (e.g., `Base → Child → GrandChild`)
- **Own fields / Total** — How many fields this template defines itself vs. the total after resolution
- **Fields table** — All fields with their source (own vs. inherited from parent), type, tag, value, and any attributes or bone/model references noted

Toggle **Show resolved** to switch between viewing only this template's own fields or the fully merged (inheritance-resolved) field list.

---

## Component Browser

Works identically to the Template Browser but for components. Useful for inspecting what fields a component will override before adding it to a group.

---

## Template Editor

The **Template Editor** tab allows you to create and edit template JSON files directly within the application — no external text editor required.

### Opening a File

Click **📂 Open JSON** to browse for an existing template file, or click **📄 New File** to start fresh.

> **Tip:** In the Template Browser, click **✏ Edit Template File…** to open the selected template's source file directly in the editor, with that template automatically selected.

### Importing from Existing XML

Click **📥 From XML…** to import hardpoints from an existing EaW `.XML` file as templates. This is useful for converting vanilla game hardpoints or community mods into the template format. Keep in mind some manual modification may be required.

The importer:
- Parses every `<HardPoint>` element
- Converts `Fire_Bone_A` → `{bone_a}`, `Fire_Bone_B` → `{bone_b}` automatically
- Converts `Attachment_Bone` and `Collision_Mesh` to `{bone_a}` when they match `Fire_Bone_A`
- Preserves original bone names in a leading comment field

After import, a selection dialog lets you choose which hardpoints to bring in. Imported templates are appended to the current file — save with **💾 Save As…**.

### Template List (Left Panel)

Shows all templates in the currently open file. Use **+ New Template**, **⧉ Duplicate**, and **✕ Delete** to manage the list. **↑** / **↓** reorders templates within the file.

### Template Metadata (Top)

- **Name** — The template's unique identifier. Referenced by `inherits_from` in child templates and by the `template` key in ship configs.
- **Inherits from** — Optional parent template name (searchable dropdown).
- **Parent comment** — Appears as `<!-- PARENT: ... -->` inside each generated `<HardPoint>` block. Usually the same as the template name.
- **File comment** — Stored as `_comment` in the JSON file (informational only, not in XML output).

Metadata changes are applied automatically as you type. Renaming a template automatically updates all child templates in the same file that inherit from it.

### Fields Table

Shows all fields for the selected template. Supports multi-select.

**Adding fields:** Use the Add buttons (Element, Section Comment, Inline Comment, Blank Line) to insert new rows below the selection.

**Inline editing:** Double-click the **Tag** or **Value** cell to edit in-place. Use **Tab** to cycle columns, **Enter** to commit.

**Field Editor panel:** The editor below the table shows the full details of the selected field and updates automatically.

**Keyboard shortcuts:**
- **F2** — Start editing the Tag of the selected row
- **Ctrl+↑ / Ctrl+↓** — Move selected row(s) up or down
- **Ctrl+D** — Duplicate selected row(s)
- **Delete** — Remove selected row(s)

### Saving

- **💾 Save** — Overwrites the current file.
- **💾 Save As…** — Saves to a new location.
- **↺ Reload into Browser** — After saving, reloads the Templates folder so the Template Browser reflects your changes immediately.

---

## Generating XML

### Generate XML (F5)

Validates the config, then writes the XML file. A summary is printed in the Output Log:

```
Generated: Hardpoints/Hardpoints_MyShip.xml
Total hardpoints: 42
  [Turbolaser] MyShip, Turbolaser, Port — 10 hardpoint(s)
  [Turbolaser] MyShip, Turbolaser, Starboard — 10 hardpoint(s)
  ...
```

If there are warnings (missing templates, empty groups), a dialog asks whether to continue.

### List Hardpoints (F6)

Prints all hardpoint names that would be generated, without writing any file. Use this to verify numbering and naming before committing.

```
Hardpoints for: MyShip
Total: 42

  HP_MyShip_Turbolaser_L_01
  HP_MyShip_Turbolaser_L_02
  ...
```

### Dump Template (F7)

Opens a dialog to select a template and prints its fully-resolved field list to the Output Log. Useful for debugging inheritance chains or verifying that a template looks correct before use.

---

## Template File Format

Template files are JSON files containing a list of template objects:

```json
{
  "_comment": "Optional file-level comment",
  "templates": [
    {
      "name":           "Hardpoint_Weapon_Generic",
      "parent_comment": "Hardpoint_Weapon_Generic",
      "inherits_from":  "",
      "fields": [
        { "_type": "section_comment", "text": "FIRE SETTINGS:" },
        { "tag": "Type",              "value": "HARD_POINT_WEAPON_LASER" },
        { "tag": "Fire_Bone_A",       "value": "{bone_a}" },
        { "tag": "Fire_Bone_B",       "value": "{bone_b}" },
        { "_type": "blank" },
        { "tag": "Fire_Projectile_Type", "value": "Proj_ExampleProjectile" },
        {
          "tag":   "Fire_Pulse_Count",
          "value": "1",
          "attrs": { "Editor_Ignore": "Yes" }
        },
        { "tag": "Empty_Tag_Example", "value": "", "empty_tag": true }
      ]
    },
    {
      "name":          "Hardpoint_Weapon_Generic_Fighter",
      "inherits_from": "Hardpoint_Weapon_Generic",
      "fields": [
        { "tag": "Fire_Cone_Width",  "value": "45.0" },
        { "tag": "Fire_Cone_Height", "value": "45.0" }
      ]
    }
  ]
}
```

---

## Field Types & Placeholders Reference

### Field Types

| Type | JSON | XML Output |
|---|---|---|
| Element | `{ "tag": "T", "value": "v" }` | `<T>v</T>` |
| Empty element | `{ "tag": "T", "value": "", "empty_tag": true }` | `<T/>` |
| Empty value | `{ "tag": "T", "value": "" }` | `<T></T>` |
| Attributed | `{ "tag": "T", "value": "1", "attrs": {"Editor_Ignore": "Yes"} }` | `<T Editor_Ignore="Yes">1</T>` |
| Section comment | `{ "_type": "section_comment", "text": "LABEL:" }` | `<!-- LABEL: -->` |
| Inline comment | `{ "_type": "inline_comment", "text": " note " }` | `<!-- note -->` |
| Blank line | `{ "_type": "blank" }` | _(empty line)_ |

### Placeholders

These are substituted at generation time for each individual hardpoint:

| Placeholder | Replaced With | Default When Missing |
|---|---|---|
| `{bone}` | Bone A (primary) — backward-compatible alias | — |
| `{bone_a}` | Bone A (primary) — the main hardpoint bone | — |
| `{bone_b}` | Bone B (secondary fire bone) | Falls back to Bone A |
| `{bone_c}` | Bone C (e.g., attachment bone override) | Falls back to Bone A |
| `{bone_d}` | Bone D (e.g., collision mesh override) | Falls back to Bone A |
| `{bone_e}` | Bone E (e.g., damage particles bone override) | No fallback |
| `{bone_f}` | Bone E (e.g., damage decal bone override) | No fallback |
| `{model_idx}` | Turret model counter (from sidebar settings) | — |
| `{shipname}` | Ship name (in name_prefix, spaces removed) | — |
| `{templatename}` | Template name (in name_prefix, spaces removed) | — |

### Bone Slot Usage Convention

The bone slots B–E have default intended uses, but you're free to use them for any purpose in your templates:

| Slot | Convention | Template field |
|---|---|---|
| A | Primary fire bone | `Fire_Bone_A`, `Attachment_Bone`, `Collision_Mesh` |
| B | Secondary fire bone | `Fire_Bone_B` |
| C | Attachment bone | `Attachment_Bone` |
| D | Collision mesh | `Collision_Mesh` |
| E | Damage Particles bone | `Damage_Particles` |

---

## Template Inheritance

Templates can inherit from a parent template using `"inherits_from": "ParentName"`.

### How Merging Works

1. **Same-tag override:** If the child defines a field with a tag that the parent also has, the child's version **replaces all parent entries** for that tag.
2. **New tags:** Child fields with tags not in the parent are **appended** after the inherited fields.
3. **Structural fields:** Blank lines and comments in the child are always appended (they have no tags, so they can't match parent fields).
4. **`parent_comment`:** Inherited from parent unless the child sets its own.

### Example

```json
{
  "templates": [
    {
      "name": "Weapon_Base",
      "fields": [
        { "tag": "Type",        "value": "HARD_POINT_WEAPON_LASER" },
        { "tag": "Fire_Cone_Width",  "value": "160.0" },
        { "tag": "Fire_Cone_Height", "value": "160.0" }
      ]
    },
    {
      "name": "Weapon_Fighter",
      "inherits_from": "Weapon_Base",
      "fields": [
        { "tag": "Fire_Cone_Width",  "value": "45.0" },
        { "tag": "Fire_Cone_Height", "value": "45.0" }
      ]
    }
  ]
}
```

`Weapon_Fighter` resolves to:
```xml
<Type>HARD_POINT_WEAPON_LASER</Type>
<Fire_Cone_Width>45.0</Fire_Cone_Width>
<Fire_Cone_Height>45.0</Fire_Cone_Height>
```

Chains are supported (`A → B → C`). Circular references are detected and reported as errors.

---

## Components System

Components are defined in exactly the same JSON format as templates and loaded from the Components folder. They are designed to be applied on top of a base template for specific groups.

### Creating a Component

```json
{
  "templates": [
    {
      "name":   "Is_Targetable_True",
      "fields": [
        { "tag": "Is_Targetable",   "value": "Yes" },
        { "tag": "Is_Destroyable",  "value": "Yes" },
      ]
    }
  ]
}
```

### Using a Component

Add the component name to a group in the Group Editor's **Components** tab. Multiple components can be stacked. The last component in the list wins any field conflicts.

### Components vs. Field Overrides

| | Components | Field Overrides |
|---|---|---|
| **Reusable** | ✅ Across any group, any ship | ❌ Per-group only |
| **Maintainable** | ✅ Change once, affects all users | ❌ Must update each group |
| **Granularity** | Predefined sets of fields | Any individual field |
| **Best for** | Shared configurations | One-off tweaks |

### Components in Generated XML

```xml
<HardPoint Name="HP_MyShip_Turbolaser_01">
  <!-- PARENT: Hardpoint_Weapon_Turbolaser
  -->
  <!-- COMPONENTS:
  Is_Targetable_True
  Turret_Heavy
  Has_DamageParticles
  -->
  <Type>HARD_POINT_WEAPON_LASER</Type>
  ...
</HardPoint>
```

---

## Ship Config Reference

A complete ship config example with all supported keys:

```json
{
  "_comment": "EaW Hardpoint Generator Ship Config",
  "ship_name":    "MyShip",
  "output_file":  "Hardpoints/Hardpoints_MyShip.xml",
  "templates":    "Templates",
  "components":   "Components",

  "template_excludes":  ["Templates/Legacy"],
  "template_includes":  ["../SharedTemplates/Templates_Common.json"],
  "component_excludes": [],
  "component_includes": [],

  "turret_models":    { "start": 1, "format": "02d" },
  "damage_particles": { "start": 1, "format": "02d" },

  "bone_pool": [
    "HP_Weapon_TL_L_01",
    "HP_Weapon_TL_L_02",
    { "bone_a": "HP_Ion_01", "bone_b": "HP_Ion_02", "name": "HP_Ion_Bank" }
  ],

  "groups": [
    {
      "group_comment":  "MyShip, Turbolasers, Port",
      "template":       "Hardpoint_Weapon_Turbolaser",
      "name_prefix":    "HP_MyShip_Turbolaser_L",
      "start_index":    1,
      "index_format":   "02d",
      "health_override": "",
      "components":     ["Is_Targetable_True"],
      "field_overrides": [],
      "bones": [
        "HP_Weapon_TL_L_01",
        "HP_Weapon_TL_L_02"
      ]
    }
  ]
}
```

### Bone Entry Formats

```json
"bones": [
  "HP_TL_01",
  { "bone": "HP_TL_02", "name": "HP_Custom_Name" },
  { "bone_a": "HP_TL_03", "bone_b": "HP_TL_04" },
  {
    "bone_a": "HP_TL_05",
    "bone_b": "HP_TL_06",
    "bone_c": "HP_TL_05_ATT_01",
    "bone_d": "HP_TL_05_COL_01",
    "bone_e": "HP_TL_05_DMG_01",
    "bone_f": "HP_TL_05_DMGDCL_01",
    "name":   "HP_Optional_Custom_Name"
  }
]
```

---

## Exclude / Include Filters

The **▸ Filters** panel beneath each path field in the sidebar lets you fine-tune which JSON files are loaded.

### Excludes

Paths to silently skip during loading. Can be a sub-folder or a single file.

**Use case:** You have a `Templates/Legacy/` folder with old templates you no longer want polluting the dropdown, but you don't want to delete them.

### Includes

Extra files or folders that are **always** loaded, in addition to the main path. The main path can even be blank if you only use includes.

**Use case:** A shared `Common_Templates.json` file sitting outside your main Templates folder that you want always available.

### Rules

- Excludes take priority over includes — an excluded file is never loaded even if explicitly included.
- Files from includes load after files from the main path; duplicate names are deduplicated (first occurrence wins).
- Paths are stored relative to the application folder in saved configs, so configs are portable.

### Controls

- **📁 Folder** — Browse for a directory to exclude/include
- **📄 File** — Browse for a single JSON file
- **✕** — Remove selected entries (also: Delete key or double-click)
- **▸ Filters** — Toggle the panel open/closed (auto-expands when the first item is added)

---

## ALO Bone Import

See the [Bone Pool section](#bone-pool) for full documentation. Quick summary:

1. Click **📥 From ALO…**
2. Browse for one or more `.ALO` model files
3. Review the extracted bones (yellow = suggested excludes, grey = already in pool)
4. Select the ones you want, click **Add Selected to Pool**

---

## XML Hardpoint Import

See the [Template Editor section](#template-editor) for full documentation. Quick summary:

1. In the Template Editor tab, click **📥 From XML…**
2. Browse for an EaW hardpoints XML file
3. Select which `<HardPoint>` entries to import
4. Click **Import Selected as Templates**
5. Review and save the resulting template JSON

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| **Ctrl+N** | New config |
| **Ctrl+O** | Open config |
| **Ctrl+S** | Save config |
| **Ctrl+Shift+S** | Save config as… |
| **F5** | Generate XML |
| **F6** | List hardpoints |
| **F7** | Dump template |
| **Delete** | Delete selected item (bones, fields, etc.) |
| **F2** | Inline-edit Tag of selected field row (Template Editor / Overrides) |
| **Ctrl+↑** | Move selected field row up |
| **Ctrl+↓** | Move selected field row down |
| **Ctrl+D** | Duplicate selected field row(s) |
| **Tab** | Cycle between inline-edit columns (Tag → Value → Attrs) |
| **Enter** | Commit inline edit |
| **Escape** | Cancel inline edit / close dialogs |

---

## Tips, Tricks & Best Practices

### Organising Templates

- **One file per weapon type** works well for large projects: `Templates_Weapon_Turbolaser.json`, `Templates_Weapon_Ion.json`, etc.
- Use inheritance liberally. A hierarchy like `Weapon_Base → Weapon_Turbolaser → Weapon_Turbolaser_Light_Green` keeps each template small and focused.
- Keep the base template lean — only put fields that are truly universal. Use inheritance for variants.

### Naming Conventions

Consistent naming makes configs easier to maintain:
- Templates: `Hardpoint_WeaponType_Variant` (e.g., `Hardpoint_Turbolaser_Light`)
- Components: `ComponentName_Value` (e.g., `Is_Targetable_True`, `Turret_Heavy_Imperial`)
- Name prefix: `HP_{shipname}_{type}_{side}` (e.g., `HP_MyShip_Turbolaser_L`)

### Port / Starboard Pairs

For symmetrical ships with port and starboard weapon groups:
1. Create the port group, assign its bones.
2. Select it and click **⧉ Duplicate**.
3. Edit the duplicate's comment (`Starboard`), prefix (`_R`), and reassign the starboard bones.

Because the prefixes differ, each group keeps its own counter.

You may also simply pair bot Port and Starboard weapon groups together in one group, of course.

### Shared Sequences

When hardpoints on the same ship form a single logical sequence regardless of which group they're in (e.g., all turbolasers numbered 01–24 across port and starboard groups), give both groups the **same Name Prefix**. The generator automatically continues the count from where the previous group left off.

### Dual Fire Bones

For weapons with two alternating firing positions, use a bone entry with both Bone A and Bone B set:

```json
{ "bone_a": "HP_TL_Fire_01_A", "bone_b": "HP_TL_Fire_01_B" }
```

In the template, `{bone_a}` → `Fire_Bone_A` and `{bone_b}` → `Fire_Bone_B`. Both get unique values in the generated XML.

### Using Health Override

Rather than creating separate templates just to change a health value, use the **Health Override** field in the Group Editor. Keep one template and tweak health per group.

### Testing Your Templates

Use **F7 (Dump Template)** while building templates. It shows the fully-resolved field list after inheritance, making it easy to spot mistakes before generating the XML.

### The JSON Preview

The sidebar's JSON Preview is a quick sanity check. If something looks wrong in the config, check here before saving.

### Relative Paths in Configs

The application always stores paths relative to its own folder. This makes configs fully portable — you can share a `.json` ship config and it will work on any machine with the same folder structure.

---

## Troubleshooting

### "hp_generator.py not found"

Ensure `hp_generator.py` is in the **same directory** as `hp_generator_GUI.py`. The generation features are disabled without it.

### "No templates loaded" / Templates path showing ⚠

1. Check the Templates Path in the sidebar is correct.
2. Make sure your JSON files have a `"templates"` array key at the top level.
3. Click **↺ Reload Templates** after changing the path.
4. Check the Output Log for specific error messages (invalid JSON, missing keys, etc.).

### Template shows ⚠ in the Groups list

The template name assigned to that group doesn't match any loaded template. This can happen after renaming a template or changing the templates path. Edit the group and reselect the correct template.

### Generated XML is empty / hardpoints are missing

- Check that every group has at least one bone assigned.
- Verify the template name in each group matches a loaded template exactly (case-sensitive).
- Run **F6 (List Hardpoints)** to see what would be generated without writing the file.

### Bone placeholders not substituting correctly

- Check that the template uses `{bone_a}`, `{bone_b}`, etc. (with curly braces) as the field value.
- In the bone entry, verify Bone A is set. Bone B–E default to Bone A if blank.
- Use **F7 (Dump Template)** to confirm the field values in the template.

### ALO import reads no bones

- The `.ALO` file may not contain a rigged skeleton (e.g., it's a particle effect or purely a render object).
- The file may use a format variant not yet supported by `alo_reader.py`.
- Check the Output Log for specific warnings from the reader.

### JSON save error

- Check that the output directory exists or that the application has write permission.
- If paths contain special characters, try using forward slashes or a simpler path.

---

*For questions, bug reports, or contributions, see the GitHub repository or contact Venator Vicain: venatorvicain on Discord, venatorvicain@gmail.com on Gmail.*

*GUI Style Attributions: [Catpuccin Mocha](https://github.com/catppuccin/catppuccin)
