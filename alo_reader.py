"""
alo_reader.py — Extract bone names from ALAMO engine .ALO model files.
For Star Wars: Empire at War (Petroglyph / Lucasarts).

Public API
----------
    from alo_reader import read_alo_bones, AloReadError

    bones, warnings = read_alo_bones("path/to/model.ALO")
    # bones    : list[str]  — bone names in file order (may contain duplicates)
    # warnings : list[str]  — non-fatal notes (e.g. duplicate names)

ALO Binary Format (chunk-based)
---------------------------------
Every datum is a chunk:
    [chunk_type : uint32 LE]  [size_raw : uint32 LE]  [payload : size bytes]

High bit of size_raw (0x80000000) marks the chunk as a *container* whose
payload is itself a sequence of child chunks.  The remaining 31 bits are the
payload byte-count.

Relevant chunk types for skeleton extraction:
    0x00000200  SKELETON    Container — holds all Bone chunks for this LOD.
    0x00000202  BONE        Container — one entry per bone in the skeleton.
    0x00000203  BONE_NAME   Leaf — null-terminated ASCII bone name string.

The file may have multiple top-level SKELETON blocks (one per LOD).  All
skeletons are checked; duplicates are de-duped while preserving the first
occurrence order.
"""

import struct
from pathlib import Path

# ── Chunk-type constants ──────────────────────────────────────────────────────

_T_SKELETON  = 0x00000200   # container: skeleton (one per LOD)
_T_BONE      = 0x00000202   # container: one bone
_T_BONE_NAME = 0x00000203   # leaf:      null-terminated bone name


# ── Public exception ──────────────────────────────────────────────────────────

class AloReadError(Exception):
    """Raised when a file cannot be parsed as a valid .ALO file."""


# ── Public function ───────────────────────────────────────────────────────────

def read_alo_bones(path: str | Path) -> tuple[list[str], list[str]]:
    """
    Parse an .ALO file and return (bones, warnings).

    bones    : list[str]  Bone names in file order.  Duplicates are removed
                          (keeping the first occurrence).  The 'Root' entry is
                          kept but usually excluded from a hardpoint bone pool.
    warnings : list[str]  Non-fatal messages (duplicates, zero-length names).

    Raises AloReadError on unrecoverable parse failures (truncated file, etc.).
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AloReadError(f"Cannot read file: {exc}") from exc

    if len(data) < 8:
        raise AloReadError("File is too small to be a valid .ALO file.")

    raw_bones: list[str] = []
    warnings:  list[str] = []

    _walk_chunks(data, 0, len(data), raw_bones, warnings)

    if not raw_bones:
        warnings.append(
            "No skeleton/bone chunks found.  The file may not contain a "
            "rigged mesh, or it uses a format variant not yet supported."
        )

    # De-duplicate while preserving insertion order
    seen:        set[str]  = set()
    unique_bones: list[str] = []
    dup_names:    list[str] = []

    for name in raw_bones:
        if name in seen:
            dup_names.append(name)
        else:
            seen.add(name)
            unique_bones.append(name)

    if dup_names:
        # Report duplicates but don't fail — they are common in EaW models
        # (e.g. multiple instances of PE_ or PTE_ particle emitter bones).
        counts: dict[str, int] = {}
        for n in dup_names:
            counts[n] = counts.get(n, 1) + 1
        summary = ", ".join(f"{n}×{c+1}" for n, c in sorted(counts.items()))
        warnings.append(f"Duplicate bone names removed: {summary}")

    return unique_bones, warnings


# ── Internal chunk walker ─────────────────────────────────────────────────────

def _walk_chunks(data: bytes, offset: int, end: int,
                 out: list[str], warnings: list[str]) -> None:
    """
    Recursively walk the chunk tree between *offset* and *end*, collecting
    bone names into *out*.
    """
    while offset + 8 <= end:
        if offset + 8 > len(data):
            break

        chunk_type = struct.unpack_from('<I', data, offset)[0]
        size_raw   = struct.unpack_from('<I', data, offset + 4)[0]
        is_container = bool(size_raw & 0x80000000)
        payload_size = size_raw & 0x7FFFFFFF

        payload_start = offset + 8
        payload_end   = payload_start + payload_size

        if payload_end > len(data):
            # Truncated chunk — abort this branch silently
            break

        if chunk_type == _T_SKELETON and is_container:
            # Skeleton container: recurse into its children to find Bone chunks
            _walk_chunks(data, payload_start, payload_end, out, warnings)

        elif chunk_type == _T_BONE and is_container:
            # Bone container: scan children for the name leaf
            name = _extract_bone_name(data, payload_start, payload_end, warnings)
            if name is not None:
                out.append(name)

        offset = payload_end


def _extract_bone_name(data: bytes, offset: int, end: int,
                       warnings: list[str]) -> str | None:
    """
    Walk inside a Bone container and return the null-terminated name string,
    or None if no BONE_NAME chunk is found.
    """
    while offset + 8 <= end:
        chunk_type = struct.unpack_from('<I', data, offset)[0]
        size_raw   = struct.unpack_from('<I', data, offset + 4)[0]
        payload_size = size_raw & 0x7FFFFFFF
        payload_start = offset + 8
        payload_end   = payload_start + payload_size

        if payload_end > len(data):
            break

        if chunk_type == _T_BONE_NAME:
            raw = data[payload_start:payload_end]
            # Strip null terminator(s)
            name = raw.rstrip(b'\x00').decode('ascii', errors='replace').strip()
            if not name:
                warnings.append("Bone with empty name skipped.")
                return None
            return name

        offset = payload_end

    return None
