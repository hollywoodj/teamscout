import struct

import pytest
from PIL import Image

from scout import dota_map_asset
from scout.dota_map_asset import MINIMAP_ENTRY, _decode_minimap, ensure_current_minimap


def _lz4_run(first, count):
    """LZ4 block for `first` (4 bytes) repeated `count` times: 4 literals
    then one overlapping match at offset 4."""
    match = count * 4 - 4 - 4
    assert 15 <= match
    extra = match - 15
    block = bytes([0x4F]) + first + struct.pack("<H", 4)
    while extra >= 255:
        block += b"\xff"
        extra -= 255
    return block + bytes([extra])


def _vtex_resource(width, height, fmt, mips, extra=None):
    """Build a Source 2 vtex resource: header, one DATA block, then the
    mip payloads (smallest first). `mips` is [(payload_bytes, stored_size)]
    from mip 0 upwards; `extra` is a list of (type, payload) extra-data."""
    extra = extra or []
    table = b"".join(struct.pack("<III", kind, 0, len(payload)) for kind, payload in extra)
    # Fix up each entry's offset: payload sits at entry_pos + 4 + offset.
    payloads = b""
    entries = b""
    table_start = 40
    payload_pos = table_start + len(table)
    for index, (kind, payload) in enumerate(extra):
        entry_pos = table_start + index * 12
        entries += struct.pack("<III", kind, payload_pos - (entry_pos + 4), len(payload))
        payloads += payload
        payload_pos += len(payload)
    header = struct.pack("<HH", 1, 0) + struct.pack("<ffff", 0, 0, 0, 0)
    header += struct.pack("<HHHBB", width, height, 1, fmt, len(mips))
    header += struct.pack("<I", 0)
    header += struct.pack("<II", 8 if extra else 0, len(extra))
    data_block = header + entries + payloads
    file_header = struct.pack("<IHHII", 0, 12, 1, 8, 1)
    block_table = struct.pack("<4sII", b"DATA", 12 - 4, len(data_block))
    body = file_header + block_table + data_block
    for payload, _stored in reversed(mips):
        body += payload
    return body[:0] + struct.pack("<I", len(body)) + body[4:]


def test_decode_single_mip_rgba_texture():
    pixels = bytes([10, 200, 30, 255]) * 16
    resource = _vtex_resource(4, 4, dota_map_asset.VTEX_RGBA8888, [(pixels, len(pixels))])
    image = _decode_minimap(resource)
    assert image.size == (4, 4)
    assert image.getpixel((3, 3)) == (10, 200, 30)


def test_decode_skips_smaller_mips_and_inflates_lz4_compressed_mip():
    color = bytes([10, 200, 30, 255])
    mip0 = _lz4_run(color, 16)            # 4x4, stored LZ4 compressed
    mip1 = bytes([1, 2, 3, 255]) * 4      # 2x2, stored raw
    sizes = struct.pack("<III", 1, 8, 2) + struct.pack("<ii", len(mip0), len(mip1))
    resource = _vtex_resource(4, 4, dota_map_asset.VTEX_RGBA8888,
                              [(mip0, len(mip0)), (mip1, len(mip1))],
                              extra=[(dota_map_asset.EXTRA_COMPRESSED_MIP_SIZE, sizes)])
    image = _decode_minimap(resource)
    assert image.size == (4, 4)
    assert image.getpixel((0, 0)) == (10, 200, 30)
    assert image.getpixel((3, 3)) == (10, 200, 30)


def test_decode_dxt5_and_display_rect_crop():
    block = bytes(16) * 4  # 8x8 DXT5: four zeroed blocks -> black
    metadata = struct.pack("<HHH", 0, 6, 5) + bytes(122)
    resource = _vtex_resource(8, 8, dota_map_asset.VTEX_DXT5, [(block, len(block))],
                              extra=[(dota_map_asset.EXTRA_METADATA, metadata)])
    image = _decode_minimap(resource)
    assert image.size == (6, 5)
    assert image.getpixel((0, 0)) == (0, 0, 0)


def test_decode_rejects_unknown_formats_and_short_data():
    resource = _vtex_resource(4, 4, 19, [(bytes(16), 16)])  # BC6H is not handled
    with pytest.raises(ValueError):
        _decode_minimap(resource)
    truncated = _vtex_resource(4, 4, dota_map_asset.VTEX_RGBA8888, [(bytes(64), 64)])[:-10]
    with pytest.raises(ValueError):
        _decode_minimap(truncated)


def _single_file_vpk(files):
    """Build a VPK v2 directory with inline (archive 0x7FFF) data."""
    by_ext = {}
    for path, data in files.items():
        folder, _, name = path.rpartition("/")
        base, _, ext = name.rpartition(".")
        by_ext.setdefault(ext, {}).setdefault(folder or " ", []).append((base, data))
    blobs = b""
    tree = b""
    for ext, folders in by_ext.items():
        tree += ext.encode() + b"\0"
        for folder, entries in folders.items():
            tree += folder.encode() + b"\0"
            for base, data in entries:
                tree += base.encode() + b"\0"
                tree += struct.pack("<IHHIIH", 0, 0, 0x7FFF, len(blobs), len(data), 0xFFFF)
                blobs += data
            tree += b"\0"
        tree += b"\0"
    tree += b"\0"
    header = struct.pack("<IIIIIII", 0x55AA1234, 2, len(tree), len(blobs), 0, 0, 0)
    return header + tree + blobs


def test_ensure_current_minimap_extracts_from_a_dota_install(tmp_path):
    pixels = bytes([10, 200, 30, 255]) * 16
    vtex = _vtex_resource(4, 4, dota_map_asset.VTEX_RGBA8888, [(pixels, len(pixels))])
    game_dir = tmp_path / "game" / "dota"
    game_dir.mkdir(parents=True)
    (game_dir / "pak01_dir.vpk").write_bytes(_single_file_vpk({MINIMAP_ENTRY: vtex, "scripts/x.txt": b"hi"}))
    cache = tmp_path / "cache" / "dota_current_minimap.png"
    assert ensure_current_minimap(cache, [game_dir]) == cache
    image = Image.open(cache)
    assert image.size == (4, 4)
    assert image.convert("RGB").getpixel((1, 1)) == (10, 200, 30)
    # A fresh cache is reused while the VPK is unchanged.
    stamp = cache.stat().st_mtime
    assert ensure_current_minimap(cache, [game_dir]) == cache
    assert cache.stat().st_mtime == stamp
    # No install and no cache -> None; no install but a cache -> the cache.
    assert ensure_current_minimap(tmp_path / "none.png", [tmp_path / "missing"]) is None
    assert ensure_current_minimap(cache, [tmp_path / "missing"]) == cache


def test_ensure_current_minimap_reports_missing_texture(tmp_path):
    game_dir = tmp_path / "game" / "dota"
    game_dir.mkdir(parents=True)
    (game_dir / "pak01_dir.vpk").write_bytes(_single_file_vpk({"scripts/x.txt": b"hi"}))
    with pytest.raises(FileNotFoundError):
        ensure_current_minimap(tmp_path / "cache" / "map.png", [game_dir])
