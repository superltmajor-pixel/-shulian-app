"""Custom-role imported history is read in bounded pages."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class RoleHistoryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_custom_history_is_paged_without_state_seeding(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            with (snapshot / "imported-history.jsonl").open("w", encoding="utf-8") as handle:
                for index in range(3):
                    handle.write(json.dumps({
                        "from": "me" if index % 2 == 0 else "them",
                        "text": f"消息 {index}",
                        "ts": index,
                        "archiveConversationId": "archived-0001",
                        "archiveConversationKind": "archived",
                    }, ensure_ascii=False) + "\n")
            with patch(
                "shulian_backend.routers.role_history.list_role_library",
                return_value={"roles": {"custom_abc": {"origin": "custom"}}},
            ), patch(
                "shulian_backend.routers.role_history._current_snapshot_dir",
                return_value=snapshot,
            ):
                first = self.client.get("/api/role-library/roles/custom_abc/history?limit=2")
                second = self.client.get("/api/role-library/roles/custom_abc/history?cursor=2&limit=2")
        self.assertEqual(first.status_code, 200)
        self.assertEqual([item["text"] for item in first.json()["items"]], ["消息 0", "消息 1"])
        self.assertEqual(first.json()["nextCursor"], 2)
        self.assertEqual(second.status_code, 200)
        self.assertEqual([item["text"] for item in second.json()["items"]], ["消息 2"])
        self.assertIsNone(second.json()["nextCursor"])

    def test_built_in_role_and_cross_origin_request_are_denied(self):
        with patch(
            "shulian_backend.routers.role_history.list_role_library",
            return_value={"roles": {"sample_a": {"origin": "built_in"}, "custom_abc": {"origin": "custom"}}},
        ):
            self.assertEqual(
                self.client.get("/api/role-library/roles/sample_a/history").status_code,
                404,
            )
            self.assertEqual(
                self.client.get(
                    "/api/role-library/roles/custom_abc/history",
                    headers={"origin": "https://example.invalid"},
                ).status_code,
                403,
            )


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
