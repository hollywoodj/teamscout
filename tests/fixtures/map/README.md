# Map fixture files

Small Source 2 sample files used to test `scout/dota_map_entities.py`
(binary KeyValues3 + entity lump reading) and the VPK reader without a
Dota 2 install:

- `default_ents_kv3_v0.vents_c` — legacy `VKV\x03` KeyValues3 entity lump
- `default_ents_kv3_v1.vents_c` — `KV3\x01` entity lump
- `default_ents_kv3_v4_zstd.vents_c` — `KV3\x04`, Zstandard compressed, Dota
  custom-game lump with `dota_minimap_boundary`, `npc_dota_tower` and
  `dota_item_rune_spawner` entities in the newer `keyValues3Data` layout
- `entity_io_param_map_test.vpk` — single-file VPK v2 containing a map with
  `maps/wtf/entities/default_ents.vents_c`

They come from the ValveResourceFormat test suite
(https://github.com/ValveResourceFormat/ValveResourceFormat, MIT licence,
`Tests/Files/`).
