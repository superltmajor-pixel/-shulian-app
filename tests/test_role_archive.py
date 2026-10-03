import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from role_archive import (
    RoleArchiveError,
    apply_role_library_to_roster,
    archive_role_snapshot,
    list_role_library,
    load_role_library_runtime,
    load_role_snapshot,
    repair_current_snapshot_assets,
)


class RoleArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.web = self.root / "web"
        self.voice = self.root / "media"
        (self.web / "assets" / "sample").mkdir(parents=True)
        self.voice.mkdir(parents=True)
        (self.web / "assets" / "sample" / "avatar.png").write_bytes(b"avatar")
        (self.voice / "voice.webm").write_bytes(b"voice")
        self.character = SimpleNamespace(
            id="sample",
            name="Sample",
            en="Sample",
            persona="Companion",
            tags=["calm"],
            cat="custom",
            greet="hello",
            mood="steady",
            replies=["hello"],
            system_prompt="runtime prompt",
            core_memory="core memory",
            public_background=("background",),
            intimacy=5,
            motif=None,
        )
        self.env = patch.dict(os.environ, {"SHULIAN_ROLE_LIBRARY_DIR": str(self.library)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _archive(self):
        image = base64.b64encode(b"image-bytes").decode("ascii")
        return archive_role_snapshot(
            character=self.character,
            frontend_profile={"id": "sample", "img": "assets/sample/avatar.png"},
            relationship={"address": "friend"},
            memory="remember this",
            intimacy=7.5,
            started_at=123,
            current_messages=[
                {"from": "me", "text": "hi", "ts": 200},
                {"from": "her", "type": "voice", "audioUrl": "/media/voice.webm", "ts": 201},
                {"from": "me", "type": "image", "imageUrl": f"data:image/png;base64,{image}", "ts": 202},
            ],
            archived_sessions=[{
                "startTs": 100,
                "endTs": 110,
                "messages": [{"from": "her", "text": "old", "ts": 100}],
            }],
            build_id="test-build",
            web_dir=self.web,
            voice_dir=self.voice,
        )

    def test_snapshot_preserves_role_data_messages_assets_and_attachments(self):
        result = self._archive()
        snapshot = Path(result["path"])
        self.assertTrue(snapshot.is_dir())
        self.assertEqual(result["messageCount"], 4)
        self.assertEqual(result["conversationCount"], 2)
        self.assertEqual((snapshot / "core.md").read_text(encoding="utf-8").strip(), "core memory")
        self.assertEqual((snapshot / "memory.md").read_text(encoding="utf-8").strip(), "remember this")
        self.assertTrue((snapshot / "assets" / "sample" / "avatar.png").is_file())
        self.assertTrue((snapshot / "attachments" / "audio" / "voice.webm").is_file())
        self.assertEqual(len(list((snapshot / "attachments" / "images").glob("*.png"))), 1)

        messages = [json.loads(line) for line in (snapshot / "chat-history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(messages), 4)
        image_message = next(message for message in messages if message.get("type") == "image")
        self.assertNotIn("imageUrl", image_message)
        self.assertTrue(image_message["archiveImagePath"].startswith("attachments/images/"))
        voice_message = next(message for message in messages if message.get("type") == "voice")
        self.assertEqual(voice_message["archiveAudioPath"], "attachments/audio/voice.webm")

        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertIn("chat-history.jsonl", manifest["files"])
        self.assertNotIn("api_key", json.dumps(manifest).lower())

    def test_runtime_asset_urls_are_canonicalized_and_copied_into_new_snapshot(self):
        result = archive_role_snapshot(
            character=self.character,
            frontend_profile={
                "id": "sample",
                "img": "/api/role-library/sample/files/assets/sample/avatar.png",
                "gallery": [{
                    "title": "Avatar",
                    "img": "/api/role-library/sample/files/assets/sample/avatar.png",
                }],
            },
            relationship={},
            memory="",
            intimacy=5,
            started_at=123,
            current_messages=[],
            archived_sessions=[],
            build_id="repair-test",
            web_dir=self.web,
            voice_dir=self.voice,
        )
        snapshot = Path(result["path"])
        profile = json.loads((snapshot / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["frontend"]["img"], "assets/sample/avatar.png")
        self.assertEqual(
            profile["frontend"]["gallery"][0]["img"],
            "assets/sample/avatar.png",
        )
        self.assertTrue((snapshot / "assets" / "sample" / "avatar.png").is_file())
        self.assertEqual(result["assetCount"], 1)

    def test_asset_repair_clones_snapshot_and_preserves_old_snapshot_and_attachments(self):
        first = self._archive()
        old_snapshot = Path(first["path"])
        profile_path = old_snapshot / "profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["frontend"]["img"] = (
            "/api/role-library/sample/files/assets/sample/avatar.png"
        )
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        (old_snapshot / "assets" / "sample" / "avatar.png").unlink()

        result = repair_current_snapshot_assets(
            "sample",
            web_dir=self.web,
            build_id="repair-build",
        )
        repaired = Path(result["path"])
        self.assertNotEqual(result["snapshotId"], first["snapshotId"])
        self.assertTrue(old_snapshot.is_dir())
        self.assertFalse(
            (old_snapshot / "assets" / "sample" / "avatar.png").exists()
        )
        self.assertTrue(
            (repaired / "assets" / "sample" / "avatar.png").is_file()
        )
        self.assertTrue(
            (repaired / "attachments" / "audio" / "voice.webm").is_file()
        )
        repaired_profile = json.loads(
            (repaired / "profile.json").read_text(encoding="utf-8")
        )
        repaired_manifest = json.loads(
            (repaired / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            repaired_profile["frontend"]["img"],
            "assets/sample/avatar.png",
        )
        self.assertEqual(
            repaired_manifest["repairedFromSnapshotId"],
            first["snapshotId"],
        )
        current = json.loads(
            (self.library / "roles" / "sample" / "current.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(current["snapshotId"], result["snapshotId"])

    def test_new_snapshot_never_overwrites_previous_snapshot(self):
        first = self._archive()
        second = self._archive()
        self.assertNotEqual(first["snapshotId"], second["snapshotId"])
        self.assertTrue(Path(first["path"]).exists())
        self.assertTrue(Path(second["path"]).exists())
        current = json.loads((self.library / "roles" / "sample" / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(current["snapshotId"], second["snapshotId"])

    def test_library_index_lists_current_snapshot_without_chat_content(self):
        result = self._archive()
        index = list_role_library()
        self.assertEqual(index["roles"]["sample"]["currentSnapshotId"], result["snapshotId"])
        self.assertNotIn("remember this", json.dumps(index))

    def test_invalid_character_id_is_rejected(self):
        self.character.id = "../escape"
        with self.assertRaises(RoleArchiveError):
            self._archive()

    def test_runtime_loader_restores_profile_prompt_state_and_attachment_urls(self):
        result = self._archive()
        role = load_role_snapshot("sample")
        self.assertEqual(role["snapshotId"], result["snapshotId"])
        self.assertEqual(role["backend"]["system_prompt"], "runtime prompt")
        self.assertEqual(role["backend"]["core_memory"], "core memory")
        self.assertEqual(
            role["frontend"]["img"],
            "/api/role-library/sample/files/assets/sample/avatar.png",
        )
        self.assertEqual(role["state"]["memory"], "remember this")
        self.assertEqual(len(role["state"]["archivedSessions"]), 1)
        self.assertEqual(len(role["state"]["currentMessages"]), 3)
        voice = next(
            message for message in role["state"]["currentMessages"]
            if message.get("type") == "voice"
        )
        image = next(
            message for message in role["state"]["currentMessages"]
            if message.get("type") == "image"
        )
        self.assertEqual(
            voice["audioUrl"],
            "/api/role-library/sample/files/attachments/audio/voice.webm",
        )
        self.assertTrue(image["imageUrl"].startswith(
            "/api/role-library/sample/files/attachments/images/"
        ))
        self.assertNotIn("archiveConversationId", voice)

    def test_runtime_roster_prefers_archive_and_keeps_builtin_fallback(self):
        self._archive()
        fallback = SimpleNamespace(
            id="fallback",
            name="Fallback",
            en="Fallback",
            persona="Fallback",
            tags=[],
            cat="custom",
            greet="fallback",
            mood="fallback",
            replies=[],
            system_prompt="fallback",
            core_memory="",
            public_background=(),
            intimacy=5,
            motif=None,
        )
        roster = {"fallback": fallback}
        runtime = apply_role_library_to_roster(roster)
        self.assertIn("sample", roster)
        self.assertIs(roster["fallback"], fallback)
        self.assertEqual(roster["sample"].system_prompt, "runtime prompt")
        self.assertEqual(runtime["loadedCharacterIds"], ["sample"])

    def test_runtime_index_and_public_file_endpoint(self):
        self._archive()
        runtime = load_role_library_runtime()
        self.assertEqual([role["id"] for role in runtime["roles"]], ["sample"])
        client = TestClient(main.app)
        response = client.get("/api/role-library/runtime")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["roles"][0]["id"], "sample")
        self.assertNotIn("backend", response.json()["roles"][0])
        self.assertNotIn("state", response.json()["roles"][0])
        state = client.get("/api/role-library/runtime/state")
        self.assertEqual(state.status_code, 200, state.text)
        self.assertEqual(state.json()["roles"][0]["state"]["memory"], "remember this")
        asset = client.get("/api/role-library/sample/files/assets/sample/avatar.png")
        self.assertEqual(asset.status_code, 200, asset.text)
        self.assertEqual(asset.content, b"avatar")
        private = client.get("/api/role-library/sample/files/runtime-prompt.md")
        self.assertEqual(private.status_code, 404)


class RoleArchiveApiTests(unittest.TestCase):
    def test_existing_character_can_create_local_snapshot(self):
        from characters import Character, ROSTER
        character = Character(id="sample", name="Sample", en="Sample", persona="Friend",
                              tags=[], cat="自建", greet="Hello", mood="Calm",
                              replies=[], system_prompt="Be a friendly character")
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"SHULIAN_ROLE_LIBRARY_DIR": temp_dir}
        ), patch.dict(ROSTER, {"sample": character}):
            client = TestClient(main.app)
            response = client.post(
                "/api/role-library/sample/snapshots",
                json={
                    "frontend_profile": {"id": "sample", "name": "Sample"},
                    "relationship": {"address": "test"},
                    "memory": "memory" * 30_000,
                    "intimacy": 8,
                    "started_at": 100,
                    "current_messages": [{"from": "me", "text": "hello", "ts": 101}],
                    "archived_sessions": [],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["characterId"], "sample")
            self.assertTrue(Path(payload["path"]).is_dir())

    def test_unknown_character_cannot_create_snapshot(self):
        client = TestClient(main.app)
        response = client.post(
            "/api/role-library/not-a-role/snapshots",
            json={"frontend_profile": {}, "relationship": {}},
        )
        self.assertEqual(response.status_code, 404)


class FrontendRoleArchiveWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app = (root / "web" / "app.jsx").read_text(encoding="utf-8")
        cls.screens = (root / "web" / "screens.jsx").read_text(encoding="utf-8")

    def test_frontend_archives_only_role_scoped_state(self):
        block = self.app.split("const archiveRoleLibrary", 1)[1].split("\n  const base =", 1)[0]
        self.assertIn("/api/role-library/${encodeURIComponent(id)}/snapshots", block)
        for field in (
            "frontend_profile: character",
            "relationship:",
            "memory:",
            "intimacy:",
            "started_at:",
            "current_messages:",
            "archived_sessions:",
        ):
            self.assertIn(field, block)
        for forbidden in ("api_key", "credentials", "sl_user_profile", "notifications"):
            self.assertNotIn(forbidden, block.lower())

    def test_settings_exposes_non_destructive_role_archive_action(self):
        settings = self.screens.split("function SettingsScreen", 1)[1].split("function MePanel", 1)[0]
        self.assertIn("建立角色档案库", settings)
        self.assertIn("旧快照仍然保留", settings)
        self.assertIn("onArchiveRoleLibrary", settings)


    def test_frontend_loads_archive_before_render_without_overwriting_existing_state(self):
        bootstrap = self.app.split("function seedArchiveObjectState", 1)[1]
        self.assertIn("/api/role-library/runtime", bootstrap)
        self.assertIn("Object.prototype.hasOwnProperty.call(stored, characterId)", bootstrap)
        self.assertIn("localStorage.getItem(storageKey) !== null", bootstrap)
        self.assertIn("prepareRoleArchiveStateAfterGate()", self.app)
        self.assertIn("/api/role-library/runtime/state", bootstrap)
        self.assertIn("roles.forEach(seedRoleArchiveState)", bootstrap)
        self.assertIn("ROSTER.splice(0, ROSTER.length, ...merged)", bootstrap)
        self.assertIn("loadSqliteStateBeforeRender()\n  .then(loadRoleLibraryBeforeRender)\n  .finally(renderShulianApp)", bootstrap)


if __name__ == "__main__":
    unittest.main()
