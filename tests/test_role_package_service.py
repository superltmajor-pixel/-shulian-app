import base64
import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from role_archive import archive_role_snapshot
from shulian_backend.services.custom_role_service import (
    validate_custom_profile,
    validate_imported_sessions,
)
from shulian_backend.services.role_package_service import (
    MAX_SESSIONS,
    RolePackageError,
    export_custom_role_package,
    import_custom_role_package,
)


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Zl0XSsAAAAASUVORK5CYII="
)


def make_package(*, profile=None, sessions=None, memory="", overrides=None, entries=None):
    profile = profile or {"name": "海棠", "persona": "安静", "tags": ["温柔"]}
    files = {
        "profile.json": json.dumps(profile, ensure_ascii=False).encode("utf-8"),
        "sessions.json": json.dumps(sessions if sessions is not None else []).encode("utf-8"),
        "memory.txt": memory.encode("utf-8"),
    }
    files.update(overrides or {})
    manifest = {
        "kind": "shulian-custom-role",
        "schemaVersion": 1,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    if entries is None:
        entries = [("manifest.json", json.dumps(manifest).encode("utf-8")), *files.items()]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


class RolePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.web = self.root / "web"
        self.voice = self.root / "voice"
        self.web.mkdir()
        self.voice.mkdir()
        self.env = patch.dict(os.environ, {"SHULIAN_ROLE_LIBRARY_DIR": str(self.library)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _archive_custom(self):
        character = SimpleNamespace(
            id="custom_0123456789abcdef",
            name="海棠",
            en="Haitang",
            persona="安静、善于倾听",
            tags=["温柔", "稳重"],
            cat="自建",
            greet="你来了。",
            mood="平静",
            replies=[],
            system_prompt="DO-NOT-EXPORT-RUNTIME-PROMPT",
            core_memory="DO-NOT-EXPORT-PRIVATE-CORE",
            public_background=(),
            intimacy=5,
            motif=None,
        )
        image_data = "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
        archive_role_snapshot(
            character=character,
            frontend_profile={
                "id": character.id,
                "name": character.name,
                "profileIntro": "一位安静的朋友。",
                "personality": "总是先听对方说完。",
                "speakingStyle": "语气温和，句子简短。",
                "relationship": "刚刚认识的朋友。",
                "img": image_data,
                "face": image_data,
                "imgPos": "50% 40%",
                "facePos": "50% 30%",
                "apiKey": "DO-NOT-EXPORT-CREDENTIAL",
            },
            relationship={"address": "DO-NOT-EXPORT-RELATIONSHIP"},
            memory="一起看过海。",
            intimacy=6,
            started_at=10,
            current_messages=[{"from": "me", "text": "最近好吗？", "ts": 200},
                              {"from": "her", "text": "挺好的。", "ts": 201}],
            archived_sessions=[{
                "startTs": 100,
                "endTs": 101,
                "messages": [{"from": "her", "text": "早上好。", "ts": 100}],
            }],
            build_id="test",
            web_dir=self.web,
            voice_dir=self.voice,
        )
        index_path = self.library / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["roles"][character.id]["origin"] = "custom"
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        return character.id

    def test_exports_only_whitelisted_role_data_and_imports_editable_draft(self):
        character_id = self._archive_custom()
        package = export_custom_role_package(character_id)
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            self.assertEqual(set(archive.namelist()), {
                "manifest.json", "profile.json", "sessions.json", "memory.txt",
                "images/img.png", "images/face.png",
            })
            exported_content = b"".join(archive.read(name) for name in archive.namelist())
        self.assertNotIn(b"DO-NOT-EXPORT", exported_content)
        self.assertNotIn(str(self.root).encode("utf-8"), exported_content)
        draft = import_custom_role_package(package)
        self.assertEqual(set(draft), {"profile", "archived_sessions", "memory"})
        self.assertEqual(draft["profile"]["name"], "海棠")
        self.assertEqual(draft["profile"]["profileIntro"], "一位安静的朋友。")
        self.assertEqual(draft["profile"]["personality"], "总是先听对方说完。")
        self.assertEqual(draft["profile"]["speakingStyle"], "语气温和，句子简短。")
        self.assertEqual(draft["profile"]["relationship"], "刚刚认识的朋友。")
        self.assertTrue(draft["profile"]["img"].startswith("data:image/png;base64,"))
        self.assertTrue(draft["profile"]["face"].startswith("data:image/png;base64,"))
        self.assertEqual(draft["memory"], "一起看过海。")
        self.assertEqual(len(draft["archived_sessions"]), 2)
        self.assertEqual([message["from"] for session in draft["archived_sessions"]
                          for message in session["messages"]], ["them", "me", "them"])
        self.assertEqual(validate_custom_profile(draft["profile"])["name"], "海棠")
        self.assertEqual(len(validate_imported_sessions(draft["archived_sessions"])), 2)

    def test_builtin_or_unmarked_role_cannot_be_exported(self):
        character_id = self._archive_custom()
        index_path = self.library / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        del index["roles"][character_id]["origin"]
        index_path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaises(RolePackageError):
            export_custom_role_package(character_id)

    def test_rejects_traversal_symlink_and_duplicate_entries(self):
        base = make_package()
        with zipfile.ZipFile(io.BytesIO(base)) as archive:
            items = [(name, archive.read(name)) for name in archive.namelist()]
        for bad_entry in (("../secret", b"x"), ("images\\img.png", PNG)):
            with self.subTest(entry=bad_entry[0]):
                with self.assertRaises(RolePackageError):
                    import_custom_role_package(make_package(entries=[*items, bad_entry]))
        link = zipfile.ZipInfo("images/img.png")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        profile = {"name": "海棠", "img": "images/img.png"}
        files = {
            "profile.json": json.dumps(profile).encode(),
            "sessions.json": b"[]",
            "memory.txt": b"",
            "images/img.png": b"elsewhere",
        }
        manifest = {"kind": "shulian-custom-role", "schemaVersion": 1,
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, data in files.items():
                archive.writestr(link if name == "images/img.png" else name, data)
        with self.assertRaises(RolePackageError):
            import_custom_role_package(output.getvalue())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with self.assertRaises(RolePackageError):
                import_custom_role_package(make_package(entries=[*items, items[1]]))

    def test_rejects_changed_hash_and_fake_image_signature(self):
        profile = {"name": "海棠", "img": "images/img.png"}
        payload = make_package(profile=profile, overrides={"images/img.png": b"not-png"})
        with self.assertRaises(RolePackageError):
            import_custom_role_package(payload)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = [(name, archive.read(name)) for name in archive.namelist()]
        entries[-1] = ("images/img.png", PNG)
        with self.assertRaises(RolePackageError):
            import_custom_role_package(make_package(entries=entries))

    def test_rejects_json_overflow_and_unknown_fields(self):
        for payload in (
            make_package(profile={"name": "海棠", "api_key": "hidden"}),
            make_package(sessions=[{"messages": [{"from": "attacker", "text": "hi"}]}]),
            make_package(sessions=[{"messages": [{"from": "me", "text": "x", "path": "C:\\secret"}]}]),
            make_package(sessions=[{"messages": [{"from": "me", "text": "x"}]}] * (MAX_SESSIONS + 1)),
            make_package(overrides={"extra.txt": b"x"}),
        ):
            with self.subTest(size=len(payload)):
                with self.assertRaises(RolePackageError):
                    import_custom_role_package(payload)

    def test_import_keeps_fifty_thousand_messages_without_truncation(self):
        messages = [{"from": "me" if index % 2 else "them", "text": str(index)}
                    for index in range(50_000)]
        draft = import_custom_role_package(make_package(sessions=[{"messages": messages}]))
        restored = draft["archived_sessions"][0]["messages"]
        self.assertEqual(len(restored), 50_000)
        self.assertEqual(restored[-1], {"from": "me", "text": "49999"})


if __name__ == "__main__":
    unittest.main()
