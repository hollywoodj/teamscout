"""Read landmark entities straight out of the installed Dota 2 map.

The map's entity lumps (``maps/dota/entities/*.vents_c``, Source 2 resources
carrying a binary KeyValues3 payload) hold the exact world-unit origins of
the two ``dota_minimap_boundary`` corners, every tower, and every rune
spawner. Reading them from ``game/dota/maps/dota.vpk`` means the Discord
ward maps project wards, towers and rune spots with the same numbers the
game itself uses for its minimap, for whichever map version is installed.

The KeyValues3 reader follows ValveResourceFormat's ``BinaryKV3`` (legacy
``VKV\\x03`` through ``KV3\\x05``, LZ4 or Zstandard compressed) and its
``EntityLump`` decoding of both the hashed-key binary entity records and the
newer ``keyValues3Data`` records. Only what the ward maps need is exposed.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

VPK_SIGNATURE = 0x55AA1234
VPK_ARCHIVE_INLINE = 0x7FFF

KV3_MAGIC_LEGACY = 0x03564B56  # "VKV\x03"
KV3_MAGIC_PREFIX = 0x4B563300  # "KV3\x0N"
KV3_TRAILER = 0xFFEEDD00

KV3_ENCODING_BINARY = bytes((0x00, 0x05, 0x86, 0x1B, 0xD8, 0xF7, 0xC1, 0x40,
                             0xAD, 0x82, 0x75, 0xA4, 0x82, 0x67, 0xE7, 0x14))
KV3_ENCODING_BINARY_BC = bytes((0x46, 0x1A, 0x79, 0x95, 0xBC, 0x95, 0x6C, 0x4F,
                                0xA7, 0x0B, 0x05, 0xBC, 0xA1, 0xB7, 0xDF, 0xD2))
KV3_ENCODING_BINARY_LZ4 = bytes((0x8A, 0x34, 0x47, 0x68, 0xA1, 0x63, 0x5C, 0x4F,
                                 0xA1, 0x97, 0x53, 0x80, 0x6F, 0xD9, 0xB1, 0x19))

COMPRESSION_NONE, COMPRESSION_LZ4, COMPRESSION_ZSTD = 0, 1, 2

# KV3 binary node types (BinaryKV3.NodeType.cs).
T_NULL, T_BOOL, T_INT64, T_UINT64, T_DOUBLE, T_STRING, T_BLOB, T_ARRAY = range(1, 9)
T_OBJECT, T_ARRAY_TYPED, T_INT32, T_UINT32, T_TRUE, T_FALSE = range(9, 15)
T_INT64_ZERO, T_INT64_ONE, T_DOUBLE_ZERO, T_DOUBLE_ONE, T_FLOAT = range(15, 20)
T_INT16, T_UINT16, T_UNKNOWN_22, T_INT32_AS_BYTE = range(20, 24)
T_ARRAY_BYTE_LENGTH, T_ARRAY_AUX_BUFFER = 24, 25

# Entity field types used by the hashed-key entity records (EntityFieldType.cs).
F_FLOAT, F_VECTOR, F_INTEGER, F_BOOLEAN, F_COLOR32 = 0x1, 0x3, 0x5, 0x6, 0x9
F_INTEGER64, F_CSTRING, F_UINT64, F_FLOAT64, F_UINT, F_QANGLE = 0x1A, 0x1E, 0x21, 0x22, 0x25, 0x27

MURMUR2_SEED = 0x31415926
ENTITY_KEYS = ("classname", "origin", "angles", "targetname", "mapunitname",
               "hammeruniqueid", "model", "scales", "teamnumber", "unitname",
               "spawnflags", "rune_type", "runetype", "team")

LANDMARK_CLASS_PREFIXES = (
    "dota_minimap_boundary",
    "npc_dota_tower",
    "npc_dota_fort",
    "dota_item_rune_spawner",
    "ent_dota_fountain",
    "npc_dota_roshan_spawner",
    "ent_dota_shop",
    "ent_dota_tree",
)
# Bumped whenever landmarks_from_entities() starts returning something new,
# so a cache written by an older version is re-read from the map.
LANDMARKS_VERSION = 2

MAP_VPK_NAME = "dota.vpk"
ENTITY_LUMP_PREFIX = "maps/dota/entities/"
ENTITY_LUMP_EXTENSION = "vents_c"


class MapEntityError(ValueError):
    """The map data could not be decoded."""


# ---------------------------------------------------------------------------
# Small binary helpers
# ---------------------------------------------------------------------------

class _Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def read(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise MapEntityError("Truncated map data")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        values = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return values

    def u8(self):
        return self.unpack("<B")[0]

    def u16(self):
        return self.unpack("<H")[0]

    def i32(self):
        return self.unpack("<i")[0]

    def u32(self):
        return self.unpack("<I")[0]

    def cstring(self):
        end = self.data.index(b"\0", self.pos)
        text = bytes(self.data[self.pos:end]).decode("utf-8", "replace")
        self.pos = end + 1
        return text


class _Cursor:
    """A memoryview with a moving read position (one KV3 typed buffer)."""

    __slots__ = ("view", "pos")

    def __init__(self, view=b""):
        self.view = memoryview(view)
        self.pos = 0

    def take(self, n):
        if self.pos + n > len(self.view):
            raise MapEntityError("KV3 buffer underrun")
        chunk = self.view[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        value = struct.unpack_from(fmt, self.view, self.pos)[0]
        self.pos += size
        return value

    def cstring(self):
        raw = bytes(self.view[self.pos:])
        end = raw.index(b"\0")
        self.pos += end + 1
        return raw[:end].decode("utf-8", "replace")

    @property
    def remaining(self):
        return len(self.view) - self.pos


def _align(offset, alignment):
    return (offset + alignment - 1) & ~(alignment - 1)


def _lz4_block_decode(src, out, out_pos, out_end):
    """Decode one LZ4 block into ``out`` (a preallocated bytearray) at
    ``out_pos``. Matches may reference bytes before ``out_pos``, which is
    what lets the caller chain frames the way LZ4ChainDecoder does."""
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        literal = token >> 4
        if literal == 15:
            while True:
                extra = src[i]
                i += 1
                literal += extra
                if extra != 255:
                    break
        if literal:
            if out_pos + literal > out_end:
                raise MapEntityError("LZ4 literal overruns output")
            out[out_pos:out_pos + literal] = src[i:i + literal]
            i += literal
            out_pos += literal
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        length = (token & 15) + 4
        if (token & 15) == 15:
            while True:
                extra = src[i]
                i += 1
                length += extra
                if extra != 255:
                    break
        start = out_pos - offset
        if offset == 0 or start < 0 or out_pos + length > out_end:
            raise MapEntityError("LZ4 match out of range")
        if offset >= length:
            out[out_pos:out_pos + length] = out[start:start + length]
        else:
            for k in range(length):
                out[out_pos + k] = out[start + k]
        out_pos += length
    return out_pos


def _lz4_decompress(src, size):
    out = bytearray(size)
    written = _lz4_block_decode(bytes(src), out, 0, size)
    if written != size:
        raise MapEntityError(f"LZ4 produced {written} bytes, expected {size}")
    return out


def _zstd_decompress(src, size):
    try:
        from compression import zstd as _zstd  # Python 3.14+
        out = _zstd.decompress(bytes(src))
    except ImportError:
        try:
            import zstandard
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise MapEntityError(
                "Zstandard support is needed to read this map (pip install zstandard)") from exc
        out = zstandard.ZstdDecompressor().decompressobj().decompress(bytes(src))
    if len(out) != size:
        raise MapEntityError(f"Zstandard produced {len(out)} bytes, expected {size}")
    return bytearray(out)


def _block_decompress(reader, size):
    """Valve's legacy CBlockCompress::FastDecompress."""
    out = bytearray(size)
    position = 0
    mask = 0
    remaining_bits = 0
    while position < size:
        if remaining_bits == 0:
            mask = reader.u16()
            remaining_bits = 16
        if mask & 1:
            offset_size = reader.u16()
            offset = (offset_size >> 4) + 1
            length = (offset_size & 0xF) + 3
            source = position - offset
            for _ in range(length):
                out[position] = out[source]
                position += 1
                source += 1
        else:
            out[position] = reader.u8()
            position += 1
        mask >>= 1
        remaining_bits -= 1
    return out


def murmur2(text, seed=MURMUR2_SEED):
    """Case-insensitive MurmurHash2 used for entity key tokens."""
    data = text.lower().encode("utf-8")
    m = 0x5BD1E995
    length = len(data)
    if length == 0:
        return 0
    h = (seed ^ length) & 0xFFFFFFFF
    i = 0
    while length >= 4:
        k = struct.unpack_from("<I", data, i)[0]
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> 24
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
        i += 4
        length -= 4
    if length == 3:
        h ^= data[i] | (data[i + 1] << 8)
        h ^= data[i + 2] << 16
        h = (h * m) & 0xFFFFFFFF
    elif length == 2:
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * m) & 0xFFFFFFFF
    elif length == 1:
        h ^= data[i]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h


_KNOWN_KEY_HASHES = {murmur2(key): key for key in ENTITY_KEYS}


# ---------------------------------------------------------------------------
# Source 2 resource container
# ---------------------------------------------------------------------------

def resource_blocks(data):
    """Return {block type: (offset, size)} for a Source 2 resource file."""
    if len(data) < 16:
        raise MapEntityError("Truncated resource header")
    _file_size, _header_version, _version, block_offset, block_count = struct.unpack_from("<IHHII", data, 0)
    blocks = {}
    pos = 8 + block_offset
    for _ in range(block_count):
        if pos + 12 > len(data):
            raise MapEntityError("Truncated resource block table")
        kind, relative, size = struct.unpack_from("<4sII", data, pos)
        blocks[kind.decode("ascii", "replace")] = (pos + 4 + relative, size)
        pos += 12
    return blocks


# ---------------------------------------------------------------------------
# Binary KeyValues3
# ---------------------------------------------------------------------------

class _Buffers:
    __slots__ = ("b1", "b2", "b4", "b8")

    def __init__(self):
        self.b1 = _Cursor()
        self.b2 = _Cursor()
        self.b4 = _Cursor()
        self.b8 = _Cursor()


class _Context:
    __slots__ = ("version", "types", "object_lengths", "blobs", "blob_lengths",
                 "strings", "buf", "aux")

    def __init__(self, version):
        self.version = version
        self.types = _Cursor()
        self.object_lengths = _Cursor()
        self.blobs = _Cursor()
        self.blob_lengths = _Cursor()
        self.strings = []
        self.buf = _Buffers()
        self.aux = _Buffers()


def parse_kv3(data, offset, size):
    """Decode a binary KV3 block into plain Python values."""
    reader = _Reader(data, offset)
    magic = reader.u32()
    if magic == KV3_MAGIC_LEGACY:
        return _parse_legacy(reader, offset, size)
    version = magic & 0xFF
    if (magic & 0xFFFFFF00) != KV3_MAGIC_PREFIX:
        raise MapEntityError(f"Not a binary KV3 block (magic {magic:#x})")
    if not 1 <= version <= 5:
        raise MapEntityError(f"Unsupported KV3 version {version}")
    return _parse_versioned(reader, offset, size, version)


def _parse_versioned(reader, offset, size, version):
    ctx = _Context(version)
    reader.read(16)  # format GUID
    compression = reader.u32()
    if compression not in (COMPRESSION_NONE, COMPRESSION_LZ4, COMPRESSION_ZSTD):
        raise MapEntityError(f"Unknown KV3 compression {compression}")

    count_types = count_objects_b2 = count_blocks = size_blobs = 0
    count_bytes2 = 0
    if version == 1:
        count_bytes1, count_bytes4, count_bytes8, size_uncompressed_total = reader.unpack("<iiii")
        size_compressed_total = size - (reader.pos - offset)
        frame_size = 0
    else:
        (_dict_id, frame_size, count_bytes1, count_bytes4, count_bytes8, count_types,
         _count_objects, _count_arrays, size_uncompressed_total, size_compressed_total,
         count_blocks, size_blobs) = reader.unpack("<HHiiiiHHiiii")
    if version >= 4:
        count_bytes2, _size_block_sizes = reader.unpack("<ii")

    if version >= 5:
        (size_unc_b1, size_cmp_b1, size_unc_b2, size_cmp_b2, count_bytes1_b2, count_bytes2_b2,
         count_bytes4_b2, count_bytes8_b2, _unk13, count_objects_b2, _count_arrays_b2,
         _unk16) = reader.unpack("<iiiiiiiiiiii")
    else:
        size_unc_b1, size_cmp_b1 = size_uncompressed_total, size_compressed_total
        size_unc_b2 = size_cmp_b2 = 0
        count_bytes1_b2 = count_bytes2_b2 = count_bytes4_b2 = count_bytes8_b2 = 0

    # Buffer 1 -----------------------------------------------------------
    blob_tail = None  # zstd < v5 packs the blobs behind buffer 1
    if compression == COMPRESSION_NONE:
        buffer1 = bytearray(reader.read(size_unc_b1))
    elif compression == COMPRESSION_LZ4:
        buffer1 = _lz4_decompress(reader.read(size_cmp_b1), size_unc_b1)
    else:
        total = size_unc_b1 + (size_blobs if version < 5 else 0)
        raw = _zstd_decompress(reader.read(size_cmp_b1), total)
        buffer1 = raw[:size_unc_b1]
        blob_tail = raw[size_unc_b1:]

    bufs1 = _Buffers()
    pos = 0
    if count_bytes1 > 0:
        bufs1.b1 = _Cursor(buffer1[pos:pos + count_bytes1])
        pos += count_bytes1
    if count_bytes2 > 0:
        pos = _align(pos, 2)
        bufs1.b2 = _Cursor(buffer1[pos:pos + count_bytes2 * 2])
        pos += count_bytes2 * 2
    if count_bytes4 > 0:
        pos = _align(pos, 4)
        bufs1.b4 = _Cursor(buffer1[pos:pos + count_bytes4 * 4])
        pos += count_bytes4 * 4
    if count_bytes8 > 0:
        pos = _align(pos, 8)
        bufs1.b8 = _Cursor(buffer1[pos:pos + count_bytes8 * 8])
        pos += count_bytes8 * 8
    elif version < 5:
        pos = _align(pos, 8)

    count_strings = bufs1.b4.unpack("<i")
    blob_sizes = None
    if version >= 5:
        ctx.aux = bufs1
        ctx.strings = [bufs1.b1.cstring() for _ in range(count_strings)]
    else:
        ctx.buf = bufs1
        strings_start = pos
        cursor = _Cursor(buffer1[pos:])
        ctx.strings = [cursor.cstring() for _ in range(count_strings)]
        pos += cursor.pos
        if version == 1:
            types_length = size_uncompressed_total - pos - 4
        else:
            types_length = count_types - (pos - strings_start)
        ctx.types = _Cursor(buffer1[pos:pos + types_length])
        pos += types_length
        if count_blocks == 0:
            trailer = struct.unpack_from("<I", buffer1, pos)[0]
            if trailer != KV3_TRAILER:
                raise MapEntityError("Bad KV3 trailer")
        else:
            blob_sizes = _Cursor(buffer1[pos:])

    # Buffer 2 (v5) --------------------------------------------------------
    if version >= 5:
        if compression == COMPRESSION_NONE:
            buffer2 = bytearray(reader.read(size_unc_b2))
        elif compression == COMPRESSION_LZ4:
            buffer2 = _lz4_decompress(reader.read(size_cmp_b2), size_unc_b2)
        else:
            buffer2 = _zstd_decompress(reader.read(size_cmp_b2), size_unc_b2)
        bufs2 = _Buffers()
        ctx.buf = bufs2
        end = count_objects_b2 * 4
        ctx.object_lengths = _Cursor(buffer2[:end])
        pos = end
        if count_bytes1_b2 > 0:
            bufs2.b1 = _Cursor(buffer2[pos:pos + count_bytes1_b2])
            pos += count_bytes1_b2
        if count_bytes2_b2 > 0:
            pos = _align(pos, 2)
            bufs2.b2 = _Cursor(buffer2[pos:pos + count_bytes2_b2 * 2])
            pos += count_bytes2_b2 * 2
        if count_bytes4_b2 > 0:
            pos = _align(pos, 4)
            bufs2.b4 = _Cursor(buffer2[pos:pos + count_bytes4_b2 * 4])
            pos += count_bytes4_b2 * 4
        if count_bytes8_b2 > 0:
            pos = _align(pos, 8)
            bufs2.b8 = _Cursor(buffer2[pos:pos + count_bytes8_b2 * 8])
            pos += count_bytes8_b2 * 8
        ctx.types = _Cursor(buffer2[pos:pos + count_types])
        pos += count_types
        if count_blocks == 0:
            trailer = struct.unpack_from("<I", buffer2, pos)[0]
            if trailer != KV3_TRAILER:
                raise MapEntityError("Bad KV3 trailer")
        else:
            blob_sizes = _Cursor(buffer2[pos:])

    # Binary blobs ---------------------------------------------------------
    if count_blocks > 0:
        if blob_sizes is None:
            raise MapEntityError("KV3 blob table missing")
        ctx.blob_lengths = _Cursor(bytes(blob_sizes.take(count_blocks * 4)))
        if blob_sizes.unpack("<I") != KV3_TRAILER:
            raise MapEntityError("Bad KV3 blob trailer")
        if compression == COMPRESSION_NONE:
            blobs = bytearray(reader.read(size_blobs))
        elif compression == COMPRESSION_LZ4:
            blobs = bytearray(size_blobs)
            decoded = 0
            while blob_sizes.remaining >= 2:
                block_length = blob_sizes.unpack("<H")
                frame = min(frame_size, size_blobs - decoded)
                decoded = _lz4_block_decode(bytes(reader.read(block_length)), blobs,
                                            decoded, decoded + frame)
            if decoded != size_blobs:
                raise MapEntityError("KV3 blob frames did not fill the blob buffer")
        elif version >= 5:
            compressed = size_compressed_total - size_cmp_b1 - size_cmp_b2
            blobs = _zstd_decompress(reader.read(compressed), size_blobs)
        else:
            blobs = blob_tail if blob_tail is not None else bytearray()
        ctx.blobs = _Cursor(blobs)
        if reader.u32() != KV3_TRAILER:
            raise MapEntityError("Bad KV3 end trailer")

    node_type = _read_type(ctx)
    return _read_value(ctx, node_type)


def _read_type(ctx):
    byte = ctx.types.unpack("<B")
    if byte & 0x80:
        byte &= 0x3F if ctx.version >= 3 else 0x7F
        ctx.types.unpack("<B")  # flag byte (resource, soundevent, ...)
    return byte


def _read_child(ctx, parent):
    node_type = _read_type(ctx)
    if isinstance(parent, list):
        parent.append(_read_value(ctx, node_type))
        return
    string_id = ctx.buf.b4.unpack("<i")
    name = "" if string_id == -1 else ctx.strings[string_id]
    parent[name] = _read_value(ctx, node_type)


def _read_value(ctx, node_type):
    buf = ctx.buf
    if node_type == T_NULL:
        return None
    if node_type == T_TRUE:
        return True
    if node_type == T_FALSE:
        return False
    if node_type == T_INT64_ZERO:
        return 0
    if node_type == T_INT64_ONE:
        return 1
    if node_type == T_DOUBLE_ZERO:
        return 0.0
    if node_type == T_DOUBLE_ONE:
        return 1.0
    if node_type == T_BOOL:
        return buf.b1.unpack("<B") == 1
    if node_type == T_INT32_AS_BYTE:
        return buf.b1.unpack("<B")
    if node_type == T_INT16:
        return buf.b2.unpack("<h")
    if node_type == T_UINT16:
        return buf.b2.unpack("<H")
    if node_type == T_INT32:
        return buf.b4.unpack("<i")
    if node_type == T_UINT32:
        return buf.b4.unpack("<I")
    if node_type == T_FLOAT:
        return buf.b4.unpack("<f")
    if node_type == T_INT64:
        return buf.b8.unpack("<q")
    if node_type == T_UINT64:
        return buf.b8.unpack("<Q")
    if node_type == T_DOUBLE:
        return buf.b8.unpack("<d")
    if node_type == T_STRING:
        string_id = buf.b4.unpack("<i")
        return "" if string_id == -1 else ctx.strings[string_id]
    if node_type == T_BLOB:
        if ctx.version < 2:
            length = buf.b4.unpack("<i")
            return bytes(buf.b1.take(length)) if length > 0 else b""
        length = ctx.blob_lengths.unpack("<i")
        return bytes(ctx.blobs.take(length)) if length > 0 else b""
    if node_type == T_ARRAY:
        out = []
        for _ in range(buf.b4.unpack("<i")):
            _read_child(ctx, out)
        return out
    if node_type in (T_ARRAY_TYPED, T_ARRAY_BYTE_LENGTH):
        length = buf.b1.unpack("<B") if node_type == T_ARRAY_BYTE_LENGTH else buf.b4.unpack("<i")
        sub_type = _read_type(ctx)
        return [_read_value(ctx, sub_type) for _ in range(length)]
    if node_type == T_ARRAY_AUX_BUFFER:
        length = buf.b1.unpack("<B")
        sub_type = _read_type(ctx)
        ctx.buf, ctx.aux = ctx.aux, ctx.buf
        try:
            return [_read_value(ctx, sub_type) for _ in range(length)]
        finally:
            ctx.buf, ctx.aux = ctx.aux, ctx.buf
    if node_type == T_OBJECT:
        length = ctx.object_lengths.unpack("<i") if ctx.version >= 5 else buf.b4.unpack("<i")
        out = {}
        for _ in range(length):
            _read_child(ctx, out)
        return out
    raise MapEntityError(f"Unknown KV3 node type {node_type}")


def _parse_legacy(reader, offset, size):
    encoding = bytes(reader.read(16))
    reader.read(16)  # format GUID
    if encoding == KV3_ENCODING_BINARY_BC:
        declared = reader.u32()
        if declared > 0x7FFFFFFF:
            payload = bytearray(reader.read(declared & 0x7FFFFFFF))
        else:
            payload = _block_decompress(reader, declared)
    elif encoding == KV3_ENCODING_BINARY_LZ4:
        uncompressed = reader.i32()
        compressed = size - (reader.pos - offset)
        payload = _lz4_decompress(reader.read(compressed), uncompressed)
    elif encoding == KV3_ENCODING_BINARY:
        payload = bytearray(reader.read(size - (reader.pos - offset)))
    else:
        raise MapEntityError("Unrecognised legacy KV3 encoding")

    body = _Reader(payload)
    strings = [body.cstring() for _ in range(body.u32())]
    node_type = _legacy_type(body)
    return _legacy_value(body, strings, node_type)


def _legacy_type(body):
    byte = body.u8()
    if byte & 0x80:
        byte &= 0x7F
        body.u8()  # flag byte
    return byte


def _legacy_child(body, strings, parent):
    name = None
    if not isinstance(parent, list):
        string_id = body.i32()
        name = "" if string_id == -1 else strings[string_id]
    value = _legacy_value(body, strings, _legacy_type(body))
    if name is None:
        parent.append(value)
    else:
        parent[name] = value


def _legacy_value(body, strings, node_type):
    if node_type == T_NULL:
        return None
    if node_type == T_BOOL:
        return body.u8() == 1
    if node_type == T_TRUE:
        return True
    if node_type == T_FALSE:
        return False
    if node_type == T_INT64_ZERO:
        return 0
    if node_type == T_INT64_ONE:
        return 1
    if node_type == T_INT64:
        return body.unpack("<q")[0]
    if node_type == T_UINT64:
        return body.unpack("<Q")[0]
    if node_type == T_INT32:
        return body.i32()
    if node_type == T_UINT32:
        return body.u32()
    if node_type == T_DOUBLE:
        return body.unpack("<d")[0]
    if node_type == T_DOUBLE_ZERO:
        return 0.0
    if node_type == T_DOUBLE_ONE:
        return 1.0
    if node_type == T_STRING:
        string_id = body.i32()
        return "" if string_id == -1 else strings[string_id]
    if node_type == T_BLOB:
        return bytes(body.read(body.i32()))
    if node_type == T_ARRAY:
        out = []
        for _ in range(body.i32()):
            _legacy_child(body, strings, out)
        return out
    if node_type == T_ARRAY_TYPED:
        length = body.i32()
        sub_type = _legacy_type(body)
        return [_legacy_value(body, strings, sub_type) for _ in range(length)]
    if node_type == T_OBJECT:
        out = {}
        for _ in range(body.i32()):
            _legacy_child(body, strings, out)
        return out
    raise MapEntityError(f"Unknown legacy KV3 node type {node_type}")


# ---------------------------------------------------------------------------
# Entity lump
# ---------------------------------------------------------------------------

def _entity_from_binary(blob):
    """Decode a hashed-key entity record (EntityLump.ParseEntityProperties)."""
    body = _Reader(blob)
    if body.u32() != 1:
        raise MapEntityError("Unsupported entity record version")
    hashed_count = body.u32()
    string_count = body.u32()
    entity = {}

    def read_typed(key_hash, key_name):
        field_type = body.u32()
        if field_type == F_BOOLEAN:
            value = body.u8() == 1
        elif field_type == F_FLOAT:
            value = body.unpack("<f")[0]
        elif field_type == F_FLOAT64:
            value = body.unpack("<d")[0]
        elif field_type == F_COLOR32:
            value = list(body.read(4))
        elif field_type == F_INTEGER:
            value = body.i32()
        elif field_type == F_UINT:
            value = body.u32()
        elif field_type == F_INTEGER64:
            value = body.unpack("<q")[0]
        elif field_type == F_UINT64:
            value = body.unpack("<Q")[0]
        elif field_type in (F_VECTOR, F_QANGLE):
            value = list(body.unpack("<fff"))
        elif field_type == F_CSTRING:
            value = body.cstring()
        else:
            raise MapEntityError(f"Unknown entity field type {field_type:#x}")
        if key_name is None:
            key_name = _KNOWN_KEY_HASHES.get(key_hash, f"key_{key_hash}")
        entity[key_name.lower()] = value

    for _ in range(hashed_count):
        read_typed(body.u32(), None)
    for _ in range(string_count):
        key_hash = body.u32()
        read_typed(key_hash, body.cstring())
    return entity


def _entity_from_kv3(record):
    if record.get("version", 1) != 1:
        raise MapEntityError("Unsupported entity data version")
    entity = {}
    for section in ("values", "attributes"):
        values = record.get(section)
        if isinstance(values, dict):
            for key, value in values.items():
                entity[str(key).lower()] = value
    return entity


def entities_from_lump(root):
    """Yield {key: value} dicts for every entity in a decoded entity lump."""
    if not isinstance(root, dict):
        raise MapEntityError("Entity lump root is not an object")
    for record in root.get("m_entityKeyValues") or []:
        if not isinstance(record, dict):
            continue
        try:
            if isinstance(record.get("keyValues3Data"), dict):
                entity = _entity_from_kv3(record["keyValues3Data"])
            elif isinstance(record.get("m_keyValuesData"), (bytes, bytearray)):
                entity = _entity_from_binary(record["m_keyValuesData"])
            else:
                continue
        except (MapEntityError, struct.error, ValueError, IndexError):
            continue
        if entity.get("classname"):
            yield entity


def entities_from_resource(data):
    """Decode a ``.vents_c`` file's bytes into entity dicts."""
    blocks = resource_blocks(data)
    if "DATA" not in blocks:
        raise MapEntityError("Entity lump has no DATA block")
    offset, size = blocks["DATA"]
    if "NTRO" in blocks:
        raise MapEntityError("NTRO entity lumps are not supported")
    root = parse_kv3(data, offset, size)
    return list(entities_from_lump(root))


_VECTOR_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


def vector3(value):
    """Coerce an entity ``origin``/``angles`` value to (x, y, z) floats."""
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return tuple(float(v) for v in value[:3])
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        parts = _VECTOR_RE.findall(value)
        if len(parts) >= 3:
            return tuple(float(p) for p in parts[:3])
    return None


def _clean_name(value):
    text = str(value or "")
    return text[5:] if text.startswith("[PR#]") else text


_TOWER_RE = re.compile(r"(?:npc_)?dota_(goodguys|badguys)_tower(\d)(?:_(top|mid|bot|bottom))?")


def landmarks_from_entities(entities):
    """Pick out the minimap boundary, towers, ancients, rune spawners and trees.

    Returns {"bounds": [minx, miny, maxx, maxy] | None, "towers": [...],
    "runes": [...], "ancients": [...], "trees": [[x, y], ...],
    "landmarks": [...]} with every origin in game world units."""
    corners = []
    towers = []
    runes = []
    ancients = []
    trees = []
    others = []
    for entity in entities:
        classname = str(entity.get("classname") or "").lower()
        if not classname.startswith(LANDMARK_CLASS_PREFIXES):
            continue
        origin = vector3(entity.get("origin"))
        if origin is None:
            continue
        x, y, _z = origin
        unit = _clean_name(entity.get("mapunitname") or entity.get("unitname") or "")
        target = _clean_name(entity.get("targetname") or "")
        if classname == "dota_minimap_boundary":
            corners.append((x, y))
        elif classname == "ent_dota_tree":
            trees.append([round(x), round(y)])
        elif classname == "npc_dota_tower":
            match = _TOWER_RE.search(unit.lower()) or _TOWER_RE.search(target.lower())
            if not match:
                continue
            side, tier, lane = match.group(1), int(match.group(2)), match.group(3) or ""
            towers.append({
                "side": "radiant" if side == "goodguys" else "dire",
                "tier": tier,
                "lane": "bottom" if lane == "bot" else lane,
                "name": unit or target,
                "x": x, "y": y,
            })
        elif classname == "npc_dota_fort":
            ancients.append({"side": "radiant" if "goodguys" in (unit + target).lower() else "dire",
                             "name": unit or target, "x": x, "y": y})
        elif classname.startswith("dota_item_rune_spawner"):
            kind = classname[len("dota_item_rune_spawner"):].lstrip("_") or "rune"
            runes.append({"kind": kind, "name": target, "x": x, "y": y})
        else:
            others.append({"classname": classname, "name": unit or target, "x": x, "y": y})

    bounds = None
    if len(corners) >= 2:
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        bounds = [min(xs), min(ys), max(xs), max(ys)]
    towers.sort(key=lambda t: (t["side"], t["tier"], t["lane"]))
    runes.sort(key=lambda r: (r["kind"], r["x"], r["y"]))
    trees.sort()
    return {"version": LANDMARKS_VERSION, "bounds": bounds, "towers": towers,
            "runes": runes, "ancients": ancients, "trees": trees, "landmarks": others}


# ---------------------------------------------------------------------------
# VPK access
# ---------------------------------------------------------------------------

def vpk_entries(directory):
    """Yield (path, archive, offset, length, preload) for a VPK v2 directory."""
    with Path(directory).open("rb") as file:
        signature, version, tree_size = struct.unpack("<III", file.read(12))
        if (signature, version) != (VPK_SIGNATURE, 2):
            raise MapEntityError("Unsupported VPK directory")
        file.seek(28)
        tree = file.read(tree_size)
    if len(tree) != tree_size:
        raise MapEntityError("Truncated VPK directory")
    data_start = 28 + tree_size

    cursor = 0

    def name():
        nonlocal cursor
        end = tree.index(0, cursor)
        text = tree[cursor:end].decode("utf-8", "replace")
        cursor = end + 1
        return text

    while extension := name():
        while folder := name():
            while basename := name():
                _crc, preload_size, archive, offset, length, terminator = struct.unpack_from(
                    "<IHHIIH", tree, cursor)
                cursor += 18
                if terminator != 0xFFFF:
                    raise MapEntityError("Invalid VPK entry")
                preload = tree[cursor:cursor + preload_size]
                cursor += preload_size
                path = f"{folder}/{basename}.{extension}" if folder != " " else f"{basename}.{extension}"
                yield path, archive, (data_start + offset if archive == VPK_ARCHIVE_INLINE else offset), length, preload


def vpk_read(directory, entry):
    """Return the bytes of one ``vpk_entries`` result."""
    _path, archive, offset, length, preload = entry
    directory = Path(directory)
    if archive == VPK_ARCHIVE_INLINE:
        source = directory
    else:
        stem = directory.name[:-len("_dir.vpk")] if directory.name.endswith("_dir.vpk") else directory.stem
        source = directory.with_name(f"{stem}_{archive:03d}.vpk")
    with source.open("rb") as file:
        file.seek(offset)
        body = file.read(length)
    if len(body) != length:
        raise MapEntityError("Truncated VPK file data")
    return bytes(preload) + body


def _entity_lump_entries(directory):
    for entry in vpk_entries(directory):
        path = entry[0]
        if path.startswith(ENTITY_LUMP_PREFIX) and path.endswith("." + ENTITY_LUMP_EXTENSION):
            yield entry


def map_vpk_candidates(game_dir):
    """Where the default map's VPK may live inside a Dota install."""
    game_dir = Path(game_dir)
    yield game_dir / "maps" / MAP_VPK_NAME
    yield game_dir / "pak01_dir.vpk"


def read_map_landmarks(game_dir):
    """Read landmarks from the first map VPK under ``game_dir`` that has
    entity lumps. Returns (landmarks dict, source path) or (None, None)."""
    for vpk in map_vpk_candidates(game_dir):
        if not vpk.is_file():
            continue
        entities = []
        lumps = 0
        for entry in _entity_lump_entries(vpk):
            lumps += 1
            entities.extend(entities_from_resource(vpk_read(vpk, entry)))
        if lumps:
            found = landmarks_from_entities(entities)
            found["source"] = str(vpk)
            found["lumps"] = lumps
            return found, vpk
    return None, None


def ensure_map_landmarks(cache_path, game_dirs):
    """Refresh ``cache_path`` (JSON) from the installed map when the map VPK
    changes; return the landmarks dict, or None when no install is found."""
    cache_path = Path(cache_path)
    for game_dir in game_dirs:
        vpk = next((c for c in map_vpk_candidates(game_dir) if c.is_file()), None)
        if vpk is None:
            continue
        stamp = f"{vpk.stat().st_mtime_ns}:{vpk.stat().st_size}:{vpk}"
        if cache_path.is_file():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = None
            if (isinstance(cached, dict) and cached.get("stamp") == stamp
                    and cached.get("version") == LANDMARKS_VERSION):
                return cached
        landmarks, _source = read_map_landmarks(game_dir)
        if landmarks is None:
            continue
        landmarks["stamp"] = stamp
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(landmarks, indent=1), encoding="utf-8")
        return landmarks
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return cached
        except (OSError, ValueError):
            pass
    return None


def _main(argv=None):
    """Print what the ward maps will use from the installed Dota map."""
    import argparse
    import sys

    from .dota_map_asset import _steam_game_dirs

    parser = argparse.ArgumentParser(description="Dump Dota map landmarks (minimap boundary, towers, runes)")
    parser.add_argument("--game-dir", default=None, help="Path to .../dota 2 beta/game/dota")
    args = parser.parse_args(argv)
    game_dirs = [Path(args.game_dir)] if args.game_dir else list(_steam_game_dirs())
    for game_dir in game_dirs:
        try:
            landmarks, source = read_map_landmarks(game_dir)
        except MapEntityError as exc:
            print(f"{game_dir}: {exc}", file=sys.stderr)
            continue
        if landmarks is None:
            continue
        summary = {k: v for k, v in landmarks.items() if k not in ("landmarks", "trees")}
        summary["trees"] = len(landmarks.get("trees") or [])
        print(json.dumps(summary, indent=1))
        return 0
    print("No readable Dota map found (looked for maps/dota.vpk under: "
          + ", ".join(str(g) for g in game_dirs) + ")", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover - manual diagnostic
    raise SystemExit(_main())
