"""Read the current Dota minimap from a local Steam installation.

The OpenDota detailed map still depicts 7.40 terrain. Dota's own minimap
texture lets the Discord ward overlays follow the installed 7.41 map without
shipping a copy of Valve's image in this repository.

The texture (``panorama/images/textures/minimap_game_png.vtex_c``) is a
Source 2 ``vtex`` resource. Its decoding follows ValveResourceFormat's
``Texture`` reader: the pixel data sits right after the DATA block, mip
levels are stored smallest first, individual mips may be LZ4 compressed, and
the largest mip is what the minimap shows.
"""

from __future__ import annotations

import io
import re
import struct
from pathlib import Path

from PIL import Image

from .dota_map_entities import MapEntityError, _lz4_decompress, resource_blocks, vpk_entries, vpk_read


MINIMAP_ENTRY = "panorama/images/textures/minimap_game_png.vtex_c"

VTEX_DXT1, VTEX_DXT5, VTEX_RGBA8888 = 1, 2, 4
VTEX_JPEG_RGBA8888, VTEX_PNG_RGBA8888, VTEX_JPEG_DXT5, VTEX_PNG_DXT5 = 15, 16, 17, 18
VTEX_BC7, VTEX_BGRA8888, VTEX_WEBP_RGBA8888, VTEX_WEBP_DXT5 = 20, 28, 29, 30
VTEX_IMAGE_FILE_FORMATS = {VTEX_JPEG_RGBA8888, VTEX_PNG_RGBA8888, VTEX_JPEG_DXT5,
                           VTEX_PNG_DXT5, VTEX_WEBP_RGBA8888, VTEX_WEBP_DXT5}
VTEX_BLOCK_SIZES = {VTEX_DXT1: 8, VTEX_DXT5: 16, VTEX_BC7: 16, VTEX_RGBA8888: 4, VTEX_BGRA8888: 4}
VTEX_BLOCK_COMPRESSED = {VTEX_DXT1, VTEX_DXT5, VTEX_BC7}
VTEX_FLAG_CUBE = 1 << 4
VTEX_FLAG_VOLUME = 1 << 5

EXTRA_METADATA = 3
EXTRA_COMPRESSED_MIP_SIZE = 4

DXGI_FORMAT_BC7_UNORM = 98


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
    for entry in vpk_entries(directory):
        if entry[0] == target:
            _path, archive, offset, length, preload = entry
            if preload:
                raise ValueError("Unexpected inline minimap data")
            return archive, offset, length
    raise FileNotFoundError(target)


def _mip_size(size, level):
    return max(1, size >> level)


def _mip_bytes(width, height, depth, fmt):
    block = VTEX_BLOCK_SIZES[fmt]
    if fmt in VTEX_BLOCK_COMPRESSED:
        width = max(4, (width + 3) // 4 * 4)
        height = max(4, (height + 3) // 4 * 4)
        return (width // 4) * (height // 4) * depth * block
    return width * height * depth * block


def _dds_container(fmt, width, height, payload):
    """Wrap block-compressed pixels in a DDS header Pillow can decode."""
    flags = 0x81007  # caps | height | width | pixelformat | linearsize
    if fmt == VTEX_BC7:
        pixel_format = struct.pack("<II4sIIIII", 32, 4, b"DX10", 0, 0, 0, 0, 0)
        dx10 = struct.pack("<IIIII", DXGI_FORMAT_BC7_UNORM, 3, 0, 1, 0)
    else:
        fourcc = b"DXT1" if fmt == VTEX_DXT1 else b"DXT5"
        pixel_format = struct.pack("<II4sIIIII", 32, 4, fourcc, 0, 0, 0, 0, 0)
        dx10 = b""
    header = (struct.pack("<IIIIIII", 124, flags, height, width, len(payload), 0, 1)
              + bytes(44) + pixel_format + struct.pack("<IIIII", 0x1000, 0, 0, 0, 0))
    return b"DDS " + header + dx10 + payload


def _decode_minimap(resource):
    """Decode the minimap texture's largest mip into a PIL image."""
    resource = bytes(resource)
    blocks = resource_blocks(resource)
    if "DATA" not in blocks:
        raise ValueError("Dota minimap has no DATA block")
    data_offset, size = blocks["DATA"]
    if size < 40 or data_offset + size > len(resource):
        raise ValueError("Invalid Dota minimap DATA block")

    version, flags = struct.unpack_from("<HH", resource, data_offset)
    if version != 1:
        raise ValueError("Unsupported Dota minimap texture version")
    width, height, depth, fmt, mip_count = struct.unpack_from("<HHHBB", resource, data_offset + 20)
    extra_offset, extra_count = struct.unpack_from("<II", resource, data_offset + 32)
    if flags & (VTEX_FLAG_CUBE | VTEX_FLAG_VOLUME) or depth != 1:
        raise ValueError("Unsupported Dota minimap texture layout")

    display = None
    compressed_mips = None
    if extra_count:
        pos = data_offset + 32 + extra_offset
        for _ in range(extra_count):
            kind, offset, extra_size = struct.unpack_from("<III", resource, pos)
            payload_at = pos + 4 + offset
            if kind == EXTRA_METADATA and extra_size >= 6:
                _zero, rect_w, rect_h = struct.unpack_from("<HHH", resource, payload_at)
                if 0 < rect_w <= width and 0 < rect_h <= height:
                    display = (rect_w, rect_h)
            elif kind == EXTRA_COMPRESSED_MIP_SIZE and extra_size >= 12:
                flag, mips_offset, mips = struct.unpack_from("<III", resource, payload_at)
                sizes_at = payload_at + 4 + mips_offset
                sizes = list(struct.unpack_from(f"<{mips}i", resource, sizes_at))
                compressed_mips = sizes if flag == 1 else None
            pos += 12

    pixels = data_offset + size
    if fmt in VTEX_IMAGE_FILE_FORMATS:
        image = Image.open(io.BytesIO(resource[pixels:])).convert("RGB")
    else:
        if fmt not in VTEX_BLOCK_SIZES:
            raise ValueError(f"Unsupported Dota minimap texture format {fmt}")
        # Mips are stored smallest first; skip every level above mip 0.
        for level in range(max(mip_count, 1) - 1, 0, -1):
            level_size = _mip_bytes(_mip_size(width, level), _mip_size(height, level), 1, fmt)
            if compressed_mips is not None and level < len(compressed_mips):
                level_size = min(level_size, compressed_mips[level])
            pixels += level_size
        expected = _mip_bytes(width, height, 1, fmt)
        if compressed_mips is not None and compressed_mips and compressed_mips[0] < expected:
            stored = compressed_mips[0]
            if pixels + stored > len(resource):
                raise ValueError("Invalid Dota minimap pixel data")
            try:
                payload = bytes(_lz4_decompress(resource[pixels:pixels + stored], expected))
            except MapEntityError as exc:
                raise ValueError(f"Dota minimap mip did not decompress: {exc}") from exc
        else:
            payload = resource[pixels:pixels + expected]
            if len(payload) != expected:
                raise ValueError("Invalid Dota minimap pixel data")

        if fmt in VTEX_BLOCK_COMPRESSED:
            image = Image.open(io.BytesIO(_dds_container(fmt, width, height, payload)))
            image.load()
            image = image.convert("RGB")
        elif fmt == VTEX_RGBA8888:
            image = Image.frombytes("RGBA", (width, height), payload).convert("RGB")
        else:  # BGRA8888
            image = Image.frombytes("RGBA", (width, height), payload, "raw", "BGRA").convert("RGB")

    if display and display != image.size:
        image = image.crop((0, 0, display[0], display[1]))
    return image


def find_dota_install(game_dirs=None):
    """Return the first installed ``game/dota`` directory that has pak01."""
    for game_dir in (game_dirs if game_dirs is not None else _steam_game_dirs()):
        if (Path(game_dir) / "pak01_dir.vpk").is_file():
            return Path(game_dir)
    return None


def ensure_current_minimap(cache_path, game_dirs=None):
    """Refresh a cached map when the installed Dota VPK changes."""
    cache_path = Path(cache_path)
    for game_dir in (game_dirs if game_dirs is not None else _steam_game_dirs()):
        directory = Path(game_dir) / "pak01_dir.vpk"
        if not directory.is_file():
            continue
        if cache_path.is_file() and cache_path.stat().st_mtime >= directory.stat().st_mtime:
            return cache_path
        entry = next((e for e in vpk_entries(directory) if e[0] == MINIMAP_ENTRY), None)
        if entry is None:
            raise FileNotFoundError(MINIMAP_ENTRY)
        image = _decode_minimap(vpk_read(directory, entry))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(cache_path, format="PNG")
        return cache_path
    return cache_path if cache_path.is_file() else None
