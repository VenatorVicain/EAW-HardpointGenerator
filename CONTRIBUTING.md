# Contributing to the EaW Hardpoint Generator

Thank you for your interest in contributing! This project is a tool for
Star Wars: Empire at War modding. **The application source code is closed
and not distributed for the time being**, but the community content that powers it — templates,
ship configs, and components — is entirely community-driven, and your
contributions are what make this tool useful.

---

## What You Can Contribute

| Type | Location | Description |
|---|---|---|
| **Templates** | `Templates/` | Reusable hardpoint field definitions (e.g. `Turbolaser_Light_Green`) |
| **Components** | `Components/` | Modular field overrides applied on top of templates (e.g. `Is_Targetable_True`) |
| **Ship Configs** | `Ship Configs/` | Ready-made `.json` configs for specific ships |
| **Bug Reports** | GitHub Issues | Something broken in the `.exe`? Let us know |
| **Feature Requests** | GitHub Issues | Ideas for new generator functionality |

> **Do not submit changes to `.py` source files, `.spec` files, or the
> `build.yml` workflow.** These are part of the closed-source application
> and pull requests modifying them will not be accepted.

---

## Before You Start

1. **Download the latest release** from the [Releases page](../../releases)
   and make sure your content works correctly in the application before
   submitting it.
2. **Check open issues and pull requests** to make sure someone isn't
   already working on the same thing.
3. For larger contributions (e.g. a full faction's worth of templates),
   **open an issue first** to discuss structure and naming conventions
   before putting in the work.

---

## File Format Reference

### Templates

Templates live in `Templates/` as `.json` files and follow this structure:

```json
{
  "templates": [
    {
      "name": "HP_Turbolaser_Light_Green",
      "parent_comment": "HP_Turbolaser_Light_Green",
      "inherits_from": "",
      "fields": [
        { "_type": "section_comment", "text": "TYPE" },
        { "tag": "Type", "value": "HARD_POINT_WEAPON_LASER" },
        { "_type": "blank" },
        { "_type": "section_comment", "text": "BONES" },
        { "tag": "Fire_Bone_A",     "value": "{bone_a}" },
        { "tag": "Fire_Bone_B",     "value": "{bone_b}" },
        { "tag": "Attachment_Bone", "value": "{bone_c}" },
        { "tag": "Collision_Mesh",  "value": "{bone_d}" }
      ]
    }
  ]
}
```

**Supported placeholders in field values:**

| Placeholder | Resolves to |
|---|---|
| `{bone_a}` / `{bone}` | Primary fire bone |
| `{bone_b}` | Secondary fire bone (falls back to `bone_a`) |
| `{bone_c}` | Attachment bone (falls back to `bone_a`) |
| `{bone_d}` | Collision mesh bone (falls back to `bone_a`) |
| `{bone_e}` | Damage particles bone (stays empty if unset) |
| `{bone_f}` | Damage decal bone (stays empty if unset) |
| `{model_idx}` | Auto-incrementing turret model counter |
| `{damage_idx}` | Auto-incrementing damage particles counter |

**Field entry types:**

```json
{ "tag": "Health", "value": "100" }
{ "tag": "Hull_Points", "value": "50", "attrs": { "Editor_Ignore": "Yes" } }
{ "tag": "EmptyTag", "value": "", "empty_tag": true }
{ "_type": "blank" }
{ "_type": "section_comment", "text": "SECTION LABEL:" }
{ "_type": "inline_comment", "text": "  <SomeTag>value</SomeTag>" }
```

**Inheritance** — a child template inherits all parent fields and can
override specific tags:

```json
{
  "name": "HP_Turbolaser_Heavy_Green",
  "parent_comment": "HP_Turbolaser_Heavy_Green",
  "inherits_from": "HP_Turbolaser_Light_Green",
  "fields": [
    { "tag": "Damage", "value": "200" }
  ]
}
```

### Components

Components live in `Components/` and use the **exact same file format** as
templates. They are designed to be applied on top of a base template to
override specific fields for a particular group, without requiring a
separate template per variant.

```json
{
  "templates": [
    {
      "name": "Is_Targetable_True",
      "parent_comment": "Is_Targetable_True",
      "fields": [
        { "tag": "Is_Targetable", "value": "Yes" }
      ]
    }
  ]
}
```

### Ship Configs

Ship configs live in `Ship Configs/` as `.json` files. They reference
template and component names by string — make sure the names match exactly.

```json
{
  "_comment": "EaW Hardpoint Generator Ship Config",
  "ship_name": "Venator",
  "output_file": "Hardpoints/Hardpoints_Venator.xml",
  "templates": "Templates",
  "components": "Components",
  "turret_models": { "start": 1, "format": "02d" },
  "bone_pool": [],
  "groups": [
    {
      "group_comment": "Venator, Turbolaser Light",
      "template": "HP_Turbolaser_Light_Green",
      "name_prefix": "HP_Venator_Turbolaser_L",
      "start_index": 1,
      "index_format": "02d",
      "components": ["Is_Targetable_True"],
      "bones": [
        { "bone_a": "HP_TL_01_L", "bone_b": "HP_TL_02_L" },
        { "bone_a": "HP_TL_03_L", "bone_b": "HP_TL_04_L" }
      ]
    }
  ]
}
```

---

## Naming Conventions

Please follow these conventions so contributions are consistent and
easy to browse in the GUI.

### Templates

- Use `PascalCase` or `Snake_Case` with underscores — avoid spaces in names.
- Name templates after the hardpoint type they represent, not the ship:
  `HP_Turbolaser_Light_Green`, not `HP_Venator_Turbolaser`.
- Prefix names with the hardpoint category where applicable:
  `HP_` for hardpoints, `Turret_` for turret-specific fields.
- If creating a child template, it should be obvious which parent it
  extends: `HP_Turbolaser_Heavy_Green` extends `HP_Turbolaser_Light_Green`.

### Components

- Name components after the field behaviour they provide:
  `Is_Targetable_True`, `Turret_Imperial_XX9`, `Shield_Generator_Large`.
- Keep them small and focused — one logical group of related fields per
  component.

### Ship Configs

- Name the file after the ship: `Venator.json`, `Acclamator.json`.
- The `ship_name` field should match the in-game object name exactly.
- Use relative paths (`Templates`, `Components`, `Hardpoints/`) — never
  absolute paths. This makes configs portable for all users.

### File Organisation

Place contributed content in the appropriate subfolder:

```
Templates/
Components/
Ship Configs/
```

If a logical subfolder doesn't exist yet, create it and mention it in
your pull request description.

---

## Submitting a Pull Request

1. **Fork** this repository and create a branch from `main`:
   ```
   git checkout -b templates/add-venator-turbolasers
   ```
   Branch name suggestions:
   - `templates/description`
   - `components/description`
   - `configs/ship-name`
   - `fix/description`

2. **Add your content** following the conventions above.

3. **Test your contribution** in the application — load your templates,
   generate XML for a ship config that uses them, and verify the output
   looks correct.

4. **Commit your changes** with a clear message:
   ```
   Add Venator turbolaser templates (light and heavy variants)
   ```

5. **Open a pull request** against `main` and fill in the PR template.
   Be specific about what you tested and what faction/ship the content
   is intended for.

---

## Reporting Bugs

Use the **Bug Report** issue template. Please include:

- The version of the `.exe` you are using (shown in the title bar and About dialog)
- Your operating system
- What you were doing when the bug occurred
- The exact error message or unexpected behaviour
- A minimal ship config and template that reproduces the issue, if applicable

---

## Code of Conduct

Be respectful. This is a modding community project. Contributions are
reviewed by the maintainer and may be declined if they don't fit the
project's scope or quality standards — that is not a personal judgement.
If your PR is declined, the review will explain why.
