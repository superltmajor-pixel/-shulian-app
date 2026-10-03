from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HistorySessionManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web" / "app.jsx").read_text(encoding="utf-8")
        cls.chat = (ROOT / "web" / "chat.jsx").read_text(encoding="utf-8")

    def test_only_archived_sessions_open_the_delete_context_menu(self):
        self.assertIn("if (session.isCurrent) return;", self.chat)
        self.assertIn("onContextMenu={(event) => openSessionMenu(event, s)}", self.chat)
        self.assertIn("删除历史会话", self.chat)
        self.assertIn("删除后无法恢复", self.chat)

    def test_delete_callback_removes_the_original_archived_session_index(self):
        self.assertIn("onDeleteSession={(idx) => deleteArchivedSession(historyCharId, idx)}", self.app)
        self.assertIn("sessions.filter((_, sessionIdx) => sessionIdx !== idx)", self.app)

    def test_archived_sessions_are_persisted_through_the_debounced_writer(self):
        # 归档会话仍是全量聚合对象，但落盘改为防抖写入器：不再在每次 state 变化时
        # 同步 JSON.stringify + 写盘（流式回复期间会造成输入/滚动发黏）。
        self.assertIn("createDebouncedStorageWriter('sl_sessions')", self.app)
        self.assertIn("sessionsWriter.schedule(() => JSON.stringify(archivedSessions))", self.app)
        # 关窗/切后台与导出备份前必须补写，否则安静期内的改动会丢。
        self.assertIn("window.shulianStorageFlush = () => flushAllPersistentState()", self.app)
        self.assertIn("const pending = flushAllPersistentState()", self.app)


if __name__ == "__main__":
    unittest.main()
