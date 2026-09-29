import json
from collections import Counter
from pathlib import Path

import pytest

from scout import dota_map_asset
from scout.dota_map_entities import (
    LANDMARKS_VERSION, MapEntityError, _lz4_block_decode, ensure_map_landmarks, entities_from_resource,
    landmarks_from_entities, map_vpk_candidates, murmur2, parse_kv3, read_map_landmarks,
    resource_blocks, vector3, vpk_entries, vpk_read,
)

FIXTURES = Path(__file__).parent / "fixtures" / "map"


def _zstd_available():
    try:
        from compression import zstd  # noqa: F401
        return True
    except ImportError:
        try:
            import zstandard  # noqa: F401
            return True
        except ImportError:
            return False


needs_zstd = pytest.mark.skipif(not _zstd_available(), reason="no Zstandard decoder installed")


def test_murmur2_matches_valve_entity_key_tokens():
    # Known-answer values from ValveResourceFormat's EntityLumpKnownKeys table.
    assert murmur2("classname") == murmur2("ClassName")  # case-insensitive
    assert murmur2("") == 0
    # The v0/v1 fixtures resolve "classname"/"origin" only if the hash matches
    # Valve's; that is asserted by the entity tests below.


def test_resource_blocks_reads_the_block_table():
    data = (FIXTURES / "default_ents_kv3_v1.vents_c").read_bytes()
    blocks = resource_blocks(data)
    assert set(blocks) == {"REDI", "DATA"}
    assert blocks["DATA"] == (272, 1539)


def test_legacy_vkv3_lump_decodes_hashed_key_entities():
    data = (FIXTURES / "default_ents_kv3_v0.vents_c").read_bytes()
    entities = entities_from_resource(data)
    assert len(entities) == 22
    counts = Counter(e["classname"] for e in entities)
    assert counts["info_player_start_goodguys"] == 5
    assert counts["info_player_start_badguys"] == 5
    world = next(e for e in entities if e["classname"] == "worldspawn")
    assert "classname" in world


def test_kv3_v1_lump_decodes():
    data = (FIXTURES / "default_ents_kv3_v1.vents_c").read_bytes()
    offset, size = resource_blocks(data)["DATA"]
    root = parse_kv3(data, offset, size)
    assert root["m_name"]
    assert len(root["m_entityKeyValues"]) == 11
    entities = entities_from_resource(data)
    assert Counter(e["classname"] for e in entities)["point_commentary_node"] == 8
    origins = [vector3(e.get("origin")) for e in entities if e.get("origin") is not None]
    assert origins and all(len(o) == 3 for o in origins)


@needs_zstd
def test_kv3_v4_zstd_dota_lump_yields_boundary_towers_and_runes():
    data = (FIXTURES / "default_ents_kv3_v4_zstd.vents_c").read_bytes()
    entities = entities_from_resource(data)
    assert len(entities) == 2064
    counts = Counter(e["classname"] for e in entities)
    assert counts["ent_dota_tree"] == 1547
    assert counts["dota_minimap_boundary"] == 2
    assert counts["npc_dota_tower"] == 4
    landmarks = landmarks_from_entities(entities)
    # Every tree comes through, as whole world units.
    assert len(landmarks["trees"]) == 1547
    assert all(len(t) == 2 and all(isinstance(v, int) for v in t) for t in landmarks["trees"])
    # Corners are combined into (min_x, min_y, max_x, max_y); this custom
    # map's boundary is not centred on the world origin.
    assert landmarks["bounds"] == [-5120.0, -4608.0, 5120.0, 5120.0]
    assert [(r["kind"], r["x"]) for r in landmarks["runes"]] == [("rune", -768.0), ("rune", 768.0)]
    assert len(landmarks["towers"]) == 4
    assert all(t["side"] == "dire" and t["tier"] == 2 and t["lane"] == "mid" for t in landmarks["towers"])
    assert landmarks["ancients"][0]["side"] == "radiant"


def test_landmarks_from_entities_parses_real_map_names():
    entities = [
        {"classname": "dota_minimap_boundary", "origin": "-8192.000000 -8192.000000 0.000000"},
        {"classname": "dota_minimap_boundary", "origin": [8192.0, 8192.0, 0.0]},
        {"classname": "npc_dota_tower", "mapunitname": "npc_dota_goodguys_tower1_top",
         "targetname": "[PR#]dota_goodguys_tower1_top", "origin": "-6336 1856.002197 256"},
        {"classname": "npc_dota_tower", "mapunitname": "npc_dota_badguys_tower2_bot",
         "origin": [6269.34, -2240.0, 256.0]},
        {"classname": "npc_dota_tower", "targetname": "[PR#]dota_badguys_tower4",
         "origin": "5000 5200 128"},
        {"classname": "dota_item_rune_spawner_powerup", "targetname": "rune_top", "origin": "-1700 1100 128"},
        {"classname": "dota_item_rune_spawner_bounty", "origin": "-4000 3000 128"},
        {"classname": "dota_item_rune_spawner_xp", "origin": "-7000 1000 128"},
        {"classname": "npc_dota_fort", "mapunitname": "npc_dota_badguys_fort", "origin": "5500 5000 256"},
        {"classname": "ent_dota_tree", "origin": "1 2 3"},
        {"classname": "npc_dota_tower", "origin": "bogus"},
    ]
    landmarks = landmarks_from_entities(entities)
    assert landmarks["bounds"] == [-8192.0, -8192.0, 8192.0, 8192.0]
    assert landmarks["towers"] == [
        {"side": "dire", "tier": 2, "lane": "bottom", "name": "npc_dota_badguys_tower2_bot",
         "x": 6269.34, "y": -2240.0},
        {"side": "dire", "tier": 4, "lane": "", "name": "dota_badguys_tower4", "x": 5000.0, "y": 5200.0},
        {"side": "radiant", "tier": 1, "lane": "top", "name": "npc_dota_goodguys_tower1_top",
         "x": -6336.0, "y": 1856.002197},
    ]
    assert [(r["kind"], r["name"]) for r in landmarks["runes"]] == [
        ("bounty", ""), ("powerup", "rune_top"), ("xp", "")]
    assert landmarks["ancients"] == [{"side": "dire", "name": "npc_dota_badguys_fort", "x": 5500.0, "y": 5000.0}]
    assert landmarks["landmarks"] == []
    assert landmarks["trees"] == [[1, 2]]
    assert landmarks["version"] == LANDMARKS_VERSION


def test_vector3_accepts_strings_and_lists():
    assert vector3("1 2.5 -3") == (1.0, 2.5, -3.0)
    assert vector3([4, 5, 6, 7]) == (4.0, 5.0, 6.0)
    assert vector3("nope") is None
    assert vector3(None) is None


def test_lz4_block_decoder_handles_literals_and_overlapping_matches():
    # "abcabcabcabc": 3 literals then a 9-byte match at offset 3 (overlap).
    block = bytes([0x35, ord("a"), ord("b"), ord("c"), 0x03, 0x00])
    out = bytearray(12)
    assert _lz4_block_decode(block, out, 0, 12) == 12
    assert bytes(out) == b"abcabcabcabc"
    with pytest.raises(MapEntityError):
        _lz4_block_decode(bytes([0x10, ord("x"), 0x05, 0x00]), bytearray(4), 0, 4)


def test_single_file_vpk_lists_and_reads_entity_lumps():
    vpk = FIXTURES / "entity_io_param_map_test.vpk"
    entries = {entry[0]: entry for entry in vpk_entries(vpk)}
    assert "maps/wtf/entities/default_ents.vents_c" in entries
    lump = vpk_read(vpk, entries["maps/wtf/entities/default_ents.vents_c"])
    assert lump[:4] != b""
    entities = entities_from_resource(lump)
    assert Counter(e["classname"] for e in entities)["prop_dynamic"] == 2


def test_read_map_landmarks_scans_a_game_dir(tmp_path):
    # Lay the fixture VPK out as game/dota/maps/dota.vpk. Its lumps live
    # under maps/wtf/, so nothing is found for the default map's prefix,
    # which is reported as "no lumps" rather than an error.
    game_dir = tmp_path / "game" / "dota"
    (game_dir / "maps").mkdir(parents=True)
    (game_dir / "maps" / "dota.vpk").write_bytes((FIXTURES / "entity_io_param_map_test.vpk").read_bytes())
    assert list(map_vpk_candidates(game_dir))[0] == game_dir / "maps" / "dota.vpk"
    landmarks, source = read_map_landmarks(game_dir)
    assert landmarks is None and source is None


def test_ensure_map_landmarks_caches_per_vpk_version(tmp_path, monkeypatch):
    import scout.dota_map_entities as mod

    game_dir = tmp_path / "game" / "dota"
    (game_dir / "maps").mkdir(parents=True)
    vpk = game_dir / "maps" / "dota.vpk"
    vpk.write_bytes(b"not really a vpk")
    calls = []

    def fake_read(path):
        calls.append(path)
        return {"version": LANDMARKS_VERSION, "bounds": [-1.0, -2.0, 3.0, 4.0],
                "towers": [], "runes": [], "trees": [[5, 6]]}, vpk

    monkeypatch.setattr(mod, "read_map_landmarks", fake_read)
    cache = tmp_path / "cache" / "dota_map_landmarks.json"
    first = ensure_map_landmarks(cache, [game_dir])
    assert first["bounds"] == [-1.0, -2.0, 3.0, 4.0]
    assert cache.is_file()
    second = ensure_map_landmarks(cache, [game_dir])
    assert second["bounds"] == first["bounds"]
    assert len(calls) == 1  # unchanged VPK -> served from the cache
    vpk.write_bytes(b"a different vpk")
    ensure_map_landmarks(cache, [game_dir])
    assert len(calls) == 2  # changed VPK -> re-read
    # A cache written before trees were extracted (older version) is re-read
    # even though the VPK itself is unchanged.
    stale = json.loads(cache.read_text())
    stale.pop("version"); stale.pop("trees")
    cache.write_text(json.dumps(stale))
    assert ensure_map_landmarks(cache, [game_dir])["trees"] == [[5, 6]]
    assert len(calls) == 3
    # No install at all: the last cache still answers, and nothing otherwise.
    assert ensure_map_landmarks(cache, [tmp_path / "missing"])["bounds"] == [-1.0, -2.0, 3.0, 4.0]
    assert ensure_map_landmarks(tmp_path / "none.json", [tmp_path / "missing"]) is None
    assert json.loads(cache.read_text())["stamp"]


def test_find_dota_install_needs_pak01(tmp_path):
    assert dota_map_asset.find_dota_install([tmp_path]) is None
    (tmp_path / "pak01_dir.vpk").write_bytes(b"")
    assert dota_map_asset.find_dota_install([tmp_path]) == tmp_path
