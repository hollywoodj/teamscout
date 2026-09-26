"""scout_bot.py cache formatters — no live Discord token required."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scout_bot

FEED = {
    "league": "LD2L SEASON XXII",
    "week": 6,
    "results_week": 5,
    "generated": "2026-09-17T06:02:00",
    "standings": [
        {"name": "The Great Leap Forward", "nameShort": "The Great Leap Forward",
         "value": "7 - 3", "captain": "Hollywood"},
        {"name": "posh goldfinch", "nameShort": "posh goldfinch",
         "value": "6 - 4", "captain": "champ0044"},
    ],
    "upcoming": [
        {
            "a": "The Great Leap Forward",
            "aShort": "The Great Leap Forward",
            "ac": "Hollywood",
            "b": "posh goldfinch",
            "bShort": "posh goldfinch",
            "bc": "champ0044",
            "label": "WEEK 6",
            "rosters": {
                "a": [
                    {"name": "Hollywood", "captain": True},
                    {"name": "Teammate"},
                ],
                "b": [
                    {"name": "champ0044", "captain": True},
                ],
            },
        }
    ],
}

MATCHES = {
    "1": {
        "match_id": 111,
        "start_time": 100,
        "radiant_name": "The Great Leap Forward",
        "dire_name": "posh goldfinch",
        "radiant_win": True,
    },
    "2": {
        "match_id": 222,
        "start_time": 200,
        "radiant_name": "Lane Tyrants",
        "dire_name": "The Great Leap Forward",
        "radiant_win": False,
    },
}


class TeamKeyTests(unittest.TestCase):
    def test_strips_the_and_punctuation(self):
        self.assertEqual(
            scout_bot.team_key("The Mad King's Gambit"),
            scout_bot.team_key("mad kings gambit"),
        )


class FormatTests(unittest.TestCase):
    def test_week(self):
        text = scout_bot.format_week(FEED)
        self.assertIn("LD2L SEASON XXII", text)
        self.assertIn("week 6", text)
        self.assertIn("week 5", text)

    def test_standings(self):
        text = scout_bot.format_standings(FEED)
        self.assertIn("The Great Leap Forward", text)
        self.assertIn("7 - 3", text)
        self.assertIn("Hollywood", text)

    def test_matchups(self):
        text = scout_bot.format_matchups(FEED)
        self.assertIn("WEEK 6", text)
        self.assertIn("posh goldfinch", text)

    def test_roster_resolves_short_name(self):
        text = scout_bot.format_roster("great leap forward", FEED)
        self.assertIn("Hollywood (C)", text)
        self.assertIn("Teammate", text)

    def test_roster_unknown(self):
        text = scout_bot.format_roster("not a team", FEED)
        self.assertIn("No team matching", text)

    def test_recent_newest_first(self):
        text = scout_bot.format_recent("Great Leap Forward", FEED, MATCHES)
        self.assertLess(text.index("222"), text.index("111"))
        self.assertIn("W vs Lane Tyrants", text)
        self.assertIn("W vs posh goldfinch", text)

    def test_recent_empty_cache(self):
        text = scout_bot.format_recent("posh goldfinch", FEED, {})
        self.assertIn("No official match cache", text)


class ChannelGateTests(unittest.TestCase):
    def test_wrong_channel_points_at_scout_channel(self):
        self.assertEqual(
            scout_bot.wrong_channel_message("1", "1550204926427267262"),
            "Please use this command in <#1550204926427267262>.",
        )

    def test_matching_channel_is_allowed(self):
        self.assertIsNone(scout_bot.wrong_channel_message(
            "1550204926427267262", "1550204926427267262"
        ))

    def test_no_restriction_when_unset(self):
        self.assertIsNone(scout_bot.wrong_channel_message("1", ""))

    def test_guild_prefers_configured_id(self):
        self.assertEqual(
            scout_bot.effective_guild_id("111", "222"),
            "111",
        )

    def test_guild_derives_from_channel_when_empty(self):
        self.assertEqual(
            scout_bot.effective_guild_id("", "222"),
            "222",
        )

    def test_mismatch_when_both_set_and_differ(self):
        self.assertTrue(scout_bot.guild_channel_mismatch("111", "222"))
        self.assertFalse(scout_bot.guild_channel_mismatch("111", "111"))
        self.assertFalse(scout_bot.guild_channel_mismatch("", "222"))

    def test_snowflake_rejects_junk(self):
        with self.assertRaises(ValueError):
            scout_bot.require_snowflake("not-an-id", "SCOUT_BOT_CHANNEL_ID")
        self.assertEqual(
            scout_bot.require_snowflake("1550204926427267262", "SCOUT_BOT_CHANNEL_ID"),
            "1550204926427267262",
        )


class RegistrationTests(unittest.TestCase):
    def test_five_commands_register(self):
        import discord
        from discord import app_commands

        client = discord.Client(intents=discord.Intents.default())
        tree = app_commands.CommandTree(client)
        guild = discord.Object(id=1)
        scout_bot.register_commands(tree, guild, channel_id="1550204926427267262")
        names = sorted(c.name for c in tree.get_commands(guild=guild))
        self.assertEqual(names, ["briefing", "matchups", "recent", "roster", "standings", "week"])

    def test_gate_rejects_other_channel(self):
        import asyncio
        from unittest import mock

        class FakeInteraction:
            def __init__(self):
                self.channel_id = 1
                self.response = mock.AsyncMock()

        async def _run():
            fi = FakeInteraction()
            wrapped = scout_bot.require_scout_channel("1550204926427267262")(
                mock.AsyncMock()
            )
            await wrapped(fi)
            fi.response.send_message.assert_awaited_once_with(
                "Please use this command in <#1550204926427267262>.",
                ephemeral=True,
            )
            wrapped.__wrapped__.assert_not_awaited()

        asyncio.run(_run())


class PostBriefingCLITests(unittest.TestCase):
    def test_arg_parser_wires_post_briefing_vs_and_dry_run(self):
        parser = scout_bot.build_arg_parser()
        args = parser.parse_args(
            ["--post-briefing", "Team Anony", "--vs", "Great Leap", "--dry-run"]
        )
        self.assertEqual(args.post_briefing, "Team Anony")
        self.assertEqual(args.vs, "Great Leap")
        self.assertTrue(args.dry_run)

    def test_default_args_have_no_post_briefing(self):
        parser = scout_bot.build_arg_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.post_briefing)
        self.assertIsNone(args.vs)
        self.assertFalse(args.dry_run)

    def test_normal_import_path_never_loads_team_scout_payload_modules(self):
        # The bot module itself must not import Team Scout's payload-building
        # modules at module scope - only post_briefing() does, and even then
        # only via a subprocess (scout.briefing_cli), never an in-process
        # import. sys.modules is process-global and sibling test files (e.g.
        # test_briefing.py, test_team_scout.py) import those modules directly,
        # so checking sys.modules in this same process would just prove one of
        # them ran first - not that scout_bot.py itself imports them. Import
        # scout_bot fresh in a subprocess instead.
        code = (
            "import sys; sys.path.insert(0, r'" + str(ROOT) + "'); "
            "import scout_bot; "
            "assert 'scout.team_scout' not in sys.modules, 'scout.team_scout imported'; "
            "assert 'scout.briefing' not in sys.modules, 'scout.briefing imported'; "
            "print('OK')"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)

    def test_team_scout_root_defaults_to_own_root(self):
        original = os.environ.pop("TEAM_SCOUT_ROOT", None)
        try:
            root = scout_bot._team_scout_root()
            self.assertEqual(root, scout_bot.project_root())
        finally:
            if original is not None:
                os.environ["TEAM_SCOUT_ROOT"] = original

    def test_team_scout_root_honors_env_override(self):
        original = os.environ.get("TEAM_SCOUT_ROOT")
        custom = str(Path("custom-scout-root").resolve())
        os.environ["TEAM_SCOUT_ROOT"] = custom
        try:
            self.assertEqual(str(scout_bot._team_scout_root()), custom)
        finally:
            if original is None:
                del os.environ["TEAM_SCOUT_ROOT"]
            else:
                os.environ["TEAM_SCOUT_ROOT"] = original

    def test_count_components_counts_nested_sections_and_accessories(self):
        components = [
            {"type": 10, "content": "a"},
            {"type": 9, "components": [{"type": 10, "content": "b"}],
             "accessory": {"type": 11, "media": {"url": "x"}}},
        ]
        # top text(1) + section(1) + its text(1) + its accessory(1) = 4
        self.assertEqual(scout_bot._count_components(components), 4)

    def test_text_chars_sums_nested_text_displays_only(self):
        components = [
            {"type": 10, "content": "abcde"},
            {"type": 9, "components": [{"type": 10, "content": "xyz"}]},
            {"type": 14, "divider": True, "spacing": 1},
        ]
        self.assertEqual(scout_bot._text_chars(components), 8)

    def test_render_components_text_walks_sections_galleries_and_buttons(self):
        components = [
            {"type": 10, "content": "hello"},
            {"type": 14},
            {"type": 9, "components": [{"type": 10, "content": "sec"}],
             "accessory": {"type": 11, "media": {"url": "http://x/thumb.png"}}},
            {"type": 12, "items": [{"media": {"url": "attachment://wards.png"}}]},
            {"type": 1, "components": [{"type": 2, "label": "Briefing"}]},
        ]
        text = scout_bot.render_components_text(components)
        self.assertIn("hello", text)
        self.assertIn("---", text)
        self.assertIn("[thumbnail: http://x/thumb.png]", text)
        self.assertIn("[image: attachment://wards.png]", text)
        self.assertIn("[button: Briefing]", text)


class CustomIdAndTabRowTests(unittest.TestCase):
    def test_custom_id_regex_round_trip(self):
        for tab in ("briefing", "wards"):
            custom_id = f"sb:tab:{tab}:05e833d7364f"
            match = scout_bot.CUSTOM_ID_RE.match(custom_id)
            self.assertIsNotNone(match)
            self.assertEqual(match.group(1), tab)
            self.assertEqual(match.group(2), "05e833d7364f")

    def test_custom_id_regex_rejects_junk(self):
        self.assertIsNone(scout_bot.CUSTOM_ID_RE.match("sb:tab:briefing:nothex"))
        self.assertIsNone(scout_bot.CUSTOM_ID_RE.match("sb:tab:other:05e833d7364f"))
        self.assertIsNone(scout_bot.CUSTOM_ID_RE.match("not-a-custom-id"))

    def test_tab_row_flips_styles_by_active_tab(self):
        row = scout_bot.tab_row("05e833d7364f", "briefing")
        by_tab = {c["custom_id"].split(":")[2]: c for c in row["components"]}
        self.assertEqual(by_tab["briefing"]["style"], 1)  # primary/active
        self.assertEqual(by_tab["wards"]["style"], 2)  # secondary

        row2 = scout_bot.tab_row("05e833d7364f", "wards")
        by_tab2 = {c["custom_id"].split(":")[2]: c for c in row2["components"]}
        self.assertEqual(by_tab2["wards"]["style"], 1)
        self.assertEqual(by_tab2["briefing"]["style"], 2)


class MultipartBodyTests(unittest.TestCase):
    def test_build_message_body_lists_attachments_and_reads_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap_dir = Path(tmp)
            (snap_dir / "wards.png").write_bytes(b"fakepng")
            page_doc = {"components": [{"type": 10, "content": "hi"}], "attachments": ["wards.png"]}
            body, files = scout_bot.build_message_body(page_doc, snap_dir, "05e833d7364f", "wards")
            self.assertEqual(body["flags"], 1 << 15)
            self.assertEqual(body["attachments"], [{"id": 0, "filename": "wards.png"}])
            # container components + the appended tab row
            self.assertEqual(len(body["components"]), 2)
            self.assertEqual(files, [("wards.png", b"fakepng")])

    def test_build_multipart_contains_payload_json_and_files(self):
        payload = {"flags": 1 << 15, "components": []}
        data, content_type = scout_bot._build_multipart(payload, [("wards.png", b"fakepng")])
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="payload_json"', data)
        self.assertIn(json.dumps(payload).encode("utf-8"), data)
        self.assertIn(b'name="files[0]"; filename="wards.png"', data)
        self.assertIn(b"fakepng", data)


class SnapshotTests(unittest.TestCase):
    def test_load_snapshot_reads_meta_and_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_root = scout_bot.SNAPSHOT_ROOT
            scout_bot.SNAPSHOT_ROOT = Path(tmp)
            try:
                snap_dir = Path(tmp) / "05e833d7364f"
                snap_dir.mkdir()
                (snap_dir / "meta.json").write_text(json.dumps({"id": "05e833d7364f"}))
                (snap_dir / "briefing.json").write_text(json.dumps({"components": [], "attachments": []}))
                (snap_dir / "wards.json").write_text(json.dumps({"components": [], "attachments": []}))
                snap = scout_bot.load_snapshot("05e833d7364f")
                self.assertIsNotNone(snap)
                self.assertEqual(snap["meta"]["id"], "05e833d7364f")
            finally:
                scout_bot.SNAPSHOT_ROOT = original_root

    def test_load_snapshot_missing_returns_none(self):
        original_root = scout_bot.SNAPSHOT_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            scout_bot.SNAPSHOT_ROOT = Path(tmp)
            try:
                self.assertIsNone(scout_bot.load_snapshot("05e833d7364f"))
            finally:
                scout_bot.SNAPSHOT_ROOT = original_root

    def test_load_snapshot_rejects_non_hex_id(self):
        self.assertIsNone(scout_bot.load_snapshot("../../etc/passwd"))


class SnapshotSubprocessTests(unittest.TestCase):
    def test_render_snapshot_invokes_briefing_cli_with_cwd_and_flags(self):
        from unittest import mock

        fake_meta = {"id": "05e833d7364f", "team": "Team Anony"}

        class FakeCompleted:
            returncode = 0
            stdout = (json.dumps(fake_meta) + "\n").encode("utf-8")
            stderr = b""

        captured = {}

        def fake_run(argv, cwd=None, stdout=None, stderr=None, **kwargs):
            captured["argv"] = argv
            captured["cwd"] = cwd
            captured["kwargs"] = kwargs
            return FakeCompleted()

        original_root = scout_bot.SNAPSHOT_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            scout_bot.SNAPSHOT_ROOT = Path(tmp) / "snapshots"
            try:
                with mock.patch.object(scout_bot.subprocess, "run", side_effect=fake_run):
                    meta = scout_bot.render_snapshot("Team Anony", vs="Great Leap")
            finally:
                scout_bot.SNAPSHOT_ROOT = original_root

        self.assertEqual(meta["id"], "05e833d7364f")
        argv = captured["argv"]
        self.assertEqual(argv[0], sys.executable)
        self.assertIn("scout.briefing_cli", argv)
        self.assertIn("--team", argv)
        self.assertIn("Team Anony", argv)
        self.assertIn("--vs", argv)
        self.assertIn("Great Leap", argv)
        self.assertEqual(captured["cwd"], str(scout_bot._team_scout_root()))
        if os.name == "nt":
            self.assertEqual(captured["kwargs"].get("creationflags"), subprocess.CREATE_NO_WINDOW)
        self.assertNotIn("shell", captured["kwargs"])


class EmojiSyncTests(unittest.TestCase):
    def test_sanitize_emoji_name_strips_prefix_and_bad_chars(self):
        self.assertEqual(scout_bot.sanitize_emoji_name("npc_dota_hero_antimage"), "h_antimage")
        self.assertEqual(
            scout_bot.sanitize_emoji_name("npc_dota_hero_nature's_prophet!!"),
            "h_natures_prophet",
        )

    def test_sanitize_emoji_name_caps_at_32_chars(self):
        long_name = "npc_dota_hero_" + ("x" * 40)
        name = scout_bot.sanitize_emoji_name(long_name)
        self.assertLessEqual(len(name), 32)
        self.assertTrue(name.startswith("h_"))

    def test_sync_skips_existing_emoji_names(self):
        from unittest import mock

        heroes = {
            "1": {"id": 1, "name": "npc_dota_hero_antimage", "img": "/apps/dota2/images/dota_react/heroes/antimage.png?"},
            "2": {"id": 2, "name": "npc_dota_hero_axe", "img": "/apps/dota2/images/dota_react/heroes/axe.png?"},
        }
        # A minimal 4x4 red PNG stands in for a downloaded portrait.
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGBA", (256, 144), (200, 40, 40, 255)).save(buf, format="PNG")
        fake_portrait = buf.getvalue()

        created_calls = []

        def fake_create(app_id, token, name, image_bytes):
            created_calls.append(name)
            return {"id": "999", "name": name}

        with tempfile.TemporaryDirectory() as tmp:
            original_dir = scout_bot.HERO_EMOJI_CACHE_DIR
            scout_bot.HERO_EMOJI_CACHE_DIR = Path(tmp)
            try:
                with mock.patch.object(scout_bot, "load_scout_env",
                                        return_value={"token": "faketoken", "application_id": "123",
                                                      "guild_id": "", "channel_id": ""}), \
                     mock.patch.object(scout_bot, "fetch_opendota_heroes_constants",
                                        return_value=(heroes, "live")), \
                     mock.patch.object(scout_bot, "list_application_emojis",
                                        return_value=[{"name": "h_antimage", "id": "111"}]), \
                     mock.patch.object(scout_bot, "_http_get_bytes", return_value=fake_portrait), \
                     mock.patch.object(scout_bot, "create_application_emoji", side_effect=fake_create):
                    created, skipped, emoji_map = scout_bot.sync_hero_emojis()
            finally:
                scout_bot.HERO_EMOJI_CACHE_DIR = original_dir

        self.assertEqual(created, 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(created_calls, ["h_axe"])
        self.assertEqual(emoji_map["1"], "<:h_antimage:111>")
        self.assertEqual(emoji_map["2"], "<:h_axe:999>")

if __name__ == "__main__":
    unittest.main()
