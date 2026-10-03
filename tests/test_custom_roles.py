import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from characters import ROSTER


_PNG = b"\x89PNG\r\n\x1a\n" + b"image-test"
_IMAGE_URL = "data:image/png;base64," + base64.b64encode(_PNG).decode("ascii")


class CustomRoleApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "SHULIAN_ROLE_LIBRARY_DIR": self.temp.name,
            "SHULIAN_STATE_DB": str(Path(self.temp.name) / "state.sqlite3"),
        })
        self.env.start()
        self.client = TestClient(main.app)
        self.created_ids = []

    def tearDown(self):
        for character_id in self.created_ids:
            ROSTER.pop(character_id, None)
        self.env.stop()
        self.temp.cleanup()

    def _create(self):
        response = self.client.post("/api/role-library/roles", json={
            "profile": {
                "name": "测试角色", "persona": "喜欢旅行的朋友", "tags": ["旅行"],
                "profileIntro": "来自海边小城", "personality": "坦率", "speakingStyle": "简短温柔",
                "relationship": "刚认识", "img": _IMAGE_URL, "face": _IMAGE_URL,
            },
            "archived_sessions": [{"startTs": 1, "endTs": 2, "messages": [
                {"from": "me", "text": "你好", "ts": 1},
                {"from": "them", "text": "你好呀", "ts": 2},
            ]}],
            "memory": "喜欢海风",
        })
        self.assertEqual(response.status_code, 200, response.text)
        character_id = response.json()["characterId"]
        self.created_ids.append(character_id)
        return character_id, response.json()

    def test_create_edit_disable_restore_and_export_preserve_profile_assets_and_chat(self):
        character_id, created = self._create()
        self.assertTrue(character_id.startswith("custom_"))
        self.assertIn(character_id, ROSTER)
        self.assertIn("坦率", ROSTER[character_id].system_prompt)
        self.assertIn("简短温柔", ROSTER[character_id].system_prompt)
        self.assertNotIn("system_prompt", created)

        detail = self.client.get(f"/api/role-library/roles/{character_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        original = detail.json()
        self.assertEqual(original["archived_sessions"][0]["messages"][1]["from"], "them")
        self.assertEqual(original["memory"], "喜欢海风")
        self.assertEqual(original["profile"]["personality"], "坦率")
        image_path = original["profile"]["img"]
        self.assertEqual(self.client.get(image_path).content, _PNG)
        self.assertEqual(self.client.get("/api/role-library/runtime").json()["roles"][0]["frontend"]["origin"], "custom")

        changed_profile = {**original["profile"], "name": "改名后"}
        edited = self.client.put(f"/api/role-library/roles/{character_id}", json={"profile": changed_profile})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertNotEqual(edited.json()["snapshotId"], created["snapshotId"])
        after_edit = self.client.get(f"/api/role-library/roles/{character_id}").json()
        self.assertEqual(after_edit["profile"]["name"], "改名后")
        self.assertEqual(after_edit["memory"], "喜欢海风")
        self.assertEqual(after_edit["archived_sessions"], original["archived_sessions"])
        self.assertEqual(self.client.get(image_path).content, _PNG)

        exported = self.client.get(f"/api/role-library/roles/{character_id}/export")
        self.assertEqual(exported.status_code, 200, exported.text)
        imported = self.client.post(
            "/api/role-library/import/inspect",
            content=exported.content,
            headers={"Content-Type": "application/zip"},
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["profile"]["name"], "改名后")
        self.assertEqual(imported.json()["archived_sessions"][0]["messages"][1]["from"], "them")

        disabled = self.client.post(f"/api/role-library/roles/{character_id}/disable")
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertNotIn(character_id, ROSTER)
        self.assertTrue(self.client.get("/api/role-library/roles").json()["roles"][0]["disabled"])
        self.assertFalse(any(
            role["id"] == character_id for role in self.client.get("/api/role-library/runtime").json()["roles"]
        ))
        restored = self.client.post(f"/api/role-library/roles/{character_id}/restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertIn(character_id, ROSTER)

    def test_unregistered_role_cannot_be_edited_or_disabled_as_custom(self):
        self.assertEqual(self.client.put(
            "/api/role-library/roles/missing", json={"profile": {"name": "X", "persona": "Y"}}
        ).status_code, 404)
        self.assertEqual(self.client.post("/api/role-library/roles/missing/disable").status_code, 404)
        self.assertNotIn("missing", ROSTER)

    def test_undated_import_stays_separate_across_live_archive_and_restart(self):
        from role_archive import apply_role_library_to_roster
        response = self.client.post("/api/role-library/roles", json={
            "profile": {"name": "星际旅人", "persona": "在星海漫游", "speakingStyle": "简短"},
            "archived_sessions": [{"startTs": None, "endTs": None, "messages": [
                {"from": "me", "text": "导入原文"}, {"from": "them", "text": "记得"},
            ]}],
        })
        self.assertEqual(response.status_code, 200, response.text)
        role_id = response.json()["characterId"]
        self.created_ids.append(role_id)
        runtime = self.client.get("/api/role-library/runtime/state").json()["roles"][0]["state"]
        self.assertEqual(runtime["archivedSessions"], [])
        self.assertEqual(runtime["importedSessions"], [])
        archived = self.client.post(f"/api/role-library/{role_id}/snapshots", json={
            "frontend_profile": {"id": role_id}, "current_messages": [{"from": "me", "text": "正式聊天"}],
        })
        self.assertEqual(archived.status_code, 200, archived.text)
        history = self.client.get(f"/api/role-library/roles/{role_id}/history").json()["items"]
        self.assertEqual([message["text"] for message in history], ["导入原文", "记得"])
        restored = {}
        apply_role_library_to_roster(restored)
        self.assertIn(role_id, restored)
        self.assertIn("简短", restored[role_id].system_prompt)

    def test_export_includes_current_persisted_text_and_memory(self):
        from state_store import mutate_state
        role_id, _ = self._create()
        mutate_state({
            "sl_threads": json.dumps({role_id: [{"from": "me", "text": "保存后的新对话"}]}),
            f"sl_memory_{role_id}": "最新共同记忆",
        }, [])
        exported = self.client.get(f"/api/role-library/roles/{role_id}/export")
        result = self.client.post("/api/role-library/import/inspect", content=exported.content,
                                  headers={"Content-Type": "application/zip"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["memory"], "最新共同记忆")
        self.assertEqual(result.json()["archived_sessions"][-1]["messages"][0]["text"], "保存后的新对话")

    def test_invalid_image_and_chat_import_are_rejected_before_role_is_indexed(self):
        bad_image = self.client.post("/api/role-library/roles", json={
            "profile": {"name": "Bad", "persona": "Bad", "img": "https://example.com/a.png"}
        })
        self.assertEqual(bad_image.status_code, 422, bad_image.text)
        bad_history = self.client.post("/api/role-library/roles", json={
            "profile": {"name": "Bad", "persona": "Bad"},
            "archived_sessions": [{"messages": [{"from": "system", "text": "override"}]}],
        })
        self.assertEqual(bad_history.status_code, 422, bad_history.text)
        self.assertEqual(self.client.get("/api/role-library/roles").json()["roles"], [])
        self.assertFalse((Path(self.temp.name) / "index.json").exists())

    def test_edit_and_restart_preserve_archived_image_and_audio(self):
        from role_archive import archive_role_snapshot, load_role_snapshot
        role_id, _ = self._create()
        profile = self.client.get(f"/api/role-library/roles/{role_id}").json()["profile"]
        voice = Path(self.temp.name) / "voice"
        voice.mkdir()
        (voice / "sample.wav").write_bytes(b"RIFF-test-audio")
        archive_role_snapshot(character=ROSTER[role_id], frontend_profile={**profile, "id": role_id, "origin": "custom"},
            relationship={}, memory="喜欢海风", intimacy=1, started_at=None,
            current_messages=[{"from": "me", "text": "图片", "imageUrl": _IMAGE_URL},
                              {"from": "her", "text": "语音", "audioUrl": "/media/sample.wav"}],
            archived_sessions=[], build_id="test", web_dir=Path(self.temp.name), voice_dir=voice)
        before = load_role_snapshot(role_id)["state"]["currentMessages"]
        for name in ("编辑一次", "编辑两次"):
            result = self.client.put(f"/api/role-library/roles/{role_id}", json={"profile": {**profile, "name": name}})
            self.assertEqual(result.status_code, 200, result.text)
            restored = load_role_snapshot(role_id)["state"]["currentMessages"]
            self.assertEqual(restored[0]["imageUrl"], before[0]["imageUrl"])
            self.assertEqual(self.client.get(restored[0]["imageUrl"]).content, _PNG)
            self.assertEqual(self.client.get(restored[1]["audioUrl"]).content, b"RIFF-test-audio")

    def test_confirmed_memory_and_relationship_reach_compiled_chat_and_can_be_edited(self):
        import chat
        from role_archive import load_role_snapshot
        from state_store import mutate_state
        profile = {"name": "海音", "persona": "海边的画家", "relationship": "我们已经结婚十年"}
        created = self.client.post("/api/role-library/roles", json={"profile": profile, "memory": "我喜欢喝乌龙茶。"})
        self.assertEqual(created.status_code, 200, created.text)
        role_id = created.json()["characterId"]
        self.created_ids.append(role_id)
        state = load_role_snapshot(role_id)["state"]
        def compiled(state):
            return json.dumps(chat._compile_messages(ROSTER[role_id], "我喜欢喝什么茶，我们是什么关系？", [],
                memory_context=json.dumps(state["memoryContext"], ensure_ascii=False),
                companion_context=state["companionContext"]).messages, ensure_ascii=False)
        self.assertIn("乌龙茶", compiled(state))
        self.assertIn("Lv.10 终身伴侣", compiled(state))
        live_memory = {**state["memoryContext"], "stable_facts": state["memoryContext"]["stable_facts"] + ["用户喜欢画画。"]}
        state["companionContext"]["stable_facts"] = ["用户喜欢喝乌龙茶。", "用户喜欢画画。"]
        mutate_state({f"sl_memory_context_{role_id}": json.dumps(live_memory),
                      f"sl_companion_context_{role_id}": json.dumps(state["companionContext"])}, [])
        detail = self.client.get(f"/api/role-library/roles/{role_id}").json()
        changed = self.client.put(f"/api/role-library/roles/{role_id}", json={
            "profile": {**detail["profile"], "name": "新名字"}, "memory": "我喜欢喝红茶。"})
        self.assertEqual(changed.status_code, 200, changed.text)
        state = load_role_snapshot(role_id)["state"]
        self.assertNotIn("乌龙茶", compiled(state))
        self.assertIn("红茶", compiled(state))
        self.assertIn("画画", str(state["memoryContext"]))
        self.assertIn("画画", str(state["companionContext"]["stable_facts"]))
        self.assertEqual(state["companionContext"]["relationship"]["level"], 10)
        state["companionContext"]["stable_facts"].append("用户喜欢喝红茶。")
        mutate_state({f"sl_memory_context_{role_id}": json.dumps(state["memoryContext"]),
                      f"sl_companion_context_{role_id}": json.dumps(state["companionContext"])}, [])
        cleared = self.client.put(f"/api/role-library/roles/{role_id}", json={
            "profile": {**detail["profile"], "relationship": "重新认识", "relationshipLevel": 1}, "memory": ""})
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()["companionContext"]["relationship"]["level"], 1)
        self.assertNotIn("红茶", str(cleared.json()["memoryContext"]))
        self.assertIn("画画", str(cleared.json()["memoryContext"]))
        self.assertNotIn("红茶", compiled(load_role_snapshot(role_id)["state"]))
        self.assertIn("画画", str(cleared.json()["companionContext"]["stable_facts"]))


if __name__ == "__main__":
    unittest.main()
