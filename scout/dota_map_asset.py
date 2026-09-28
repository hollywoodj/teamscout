"""Read the current Dota minimap from a local Steam installation.

The OpenDota detailed map still depicts 7.40 terrain. Dota's own minimap
texture lets the Discord ward overlays follow the installed 7.41 map without
shipping a copy of Valve's image in this repository.
"""

from __future__ import annotations

import io
import re
import struct
from pathlib import Path

from PIL import Image


MINIMAP_ENTRY = "panorama/images/textures/minimap_game_png.vtex_c"


def _steam_game_dirs():
    steam = Path(r"C:\Program Files (x86)\Steam")
    roots = [steam]
    config = steam / "steamapps" / "libraryfolders.vdf"
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        text = ""
    for path in re.findall(r'"path"\s+"([^"]+)"', text):
        roots.append(Path(path.replace("\\\\", "\\")))
    for root in dict.fromkeys(roots):
        yield root / "steamapps" / "common" / "dota 2 beta" / "game" / "dota"


def _vpk_entry(directory, target):
    """Return (archive, offset, length) for one file in a Valve VPK v2."""
    with directory.open("rb") as file:
        signature, version, tree_size = struct.unpack("<III", file.read(12))
        if (signature, version) != (0x55AA1234, 2):
            raise ValueError("Unsupported Dota VPK directory")
        file.seek(28)
        tree = file.read(tree_size)
    if len(tree) != tree_size:
        raise ValueError("Truncated Dota VPK directory")

    cursor = 0

    def name():
        nonlocal cursor
        end = tree.index(0, cursor)
        result = tree[cursor:end].decode("utf-8")
        cursor = end + 1
        return result

    while extension := name():
        while folder := name():
            while basename := name():
                _crc, preload, archive, offset, length, terminator = struct.unpack_from(
                    "<IHHIIH", tree, cursor)
                cursor += 18
                if terminator != 0xFFFF:
                    raise ValueError("Invalid Dota VPK entry")
                embedded = tree[cursor:cursor + preload]
                cursor += preload
                path = f"{folder}/{basename}.{extension}"
                if path == target:
                    if preload:
                        raise ValueError("Unexpected inline minimap data")
                    return archive, offset, length
    raise FileNotFoundError(target)


def _decode_minimap(resource):
    """Decode the minimap's single BC3/DXT5 mip into a PIL image."""
    if len(resource) < 32:
        raise ValueError("Truncated Dota minimap texture")
    block_count = struct.unpack_from("<I", resource, 12)[0]
    for entry in range(block_count):
        position = 16 + entry * 12
        kind, relative, size = struct.unpack_from("<4sII", resource, position)
        if kind == b"DATA":
            data_offset = position + 4 + relative
            break
    else:
        raise ValueError("Dota minimap has no DATA block")
    if size < 32 or data_offset + size > len(resource):
        raise ValueError("Invalid Dota minimap DATA block")
    version, _flags = struct.unpack_from("<HH", resource, data_offset)
    width, height, depth, format_id, mip_count = struct.unpack_from(
        "<HHHBB", resource, data_offset + 20)
    if version != 1 or depth != 1 or format_id != 2 or mip_count != 1:
        raise ValueError("Unsupported Dota minimap texture format")
    pixel_data = resource[data_offset + size:]
    expected = ((width + 3) // 4) * ((height + 3) // 4) * 16
    if len(pixel_data) != expected:
        raise ValueError("Invalid Dota minimap pixel data")

    pixel_format = struct.pack("<II4sIIIII", 32, 4, b"DXT5", 0, 0, 0, 0, 0)
    header = (struct.pack("<IIIIIII", 124, 0x81007, height, width, expected, 0, 1)
              + bytes(44) + pixel_format + struct.pack("<IIIII", 0x1000, 0, 0, 0, 0))
    return Image.open(io.BytesIO(b"DDS " + header + pixel_data)).convert("RGB")


def ensure_current_minimap(cache_path):
    """Refresh a cached map when the installed Dota VPK changes."""
    cache_path = Path(cache_path)
    for game_dir in _steam_game_dirs():
        directory = game_dir / "pak01_dir.vpk"
        if not directory.is_file():
            continue
        if cache_path.is_file() and cache_path.stat().st_mtime >= directory.stat().st_mtime:
            return cache_path
        archive, offset, length = _vpk_entry(directory, MINIMAP_ENTRY)
        with (game_dir / f"pak01_{archive:03d}.vpk").open("rb") as file:
            file.seek(offset)
            resource = file.read(length)
        image = _decode_minimap(resource)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(cache_path, format="PNG")
        return cache_path
    return cache_path if cache_path.is_file() else None
