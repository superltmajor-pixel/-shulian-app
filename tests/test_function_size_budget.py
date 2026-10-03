"""第 11 项的结构护栏：超长函数拆分后不许再长回去。

拆分本身由现有测试的文字锚点保护；这里补的是「尺寸预算」——
任何人往 MainApp / SettingsScreen / ChatThread 里再塞几百行，
或把已抽出的单元改成死代码，都会在这里先失败。
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

DECL_RE = re.compile(r"^(?:async function|function|class|const|let|var)\s")
NAME_RE = re.compile(r"^(?:async function|function|class|const|let|var)\s+([A-Za-z_$][\w$]*)")

# 拆分后的尺寸预算（行数）。当前实测：MainApp 846、SettingsScreen 124、ChatThread 361。
SIZE_BUDGETS = {
    "app.jsx": {"MainApp": 900},
    "screens.jsx": {"SettingsScreen": 200},
    "chat.jsx": {"ChatThread": 400},
}

# 抽出的单元必须仍被宿主组件引用，防止「抽走后没人调用」的死代码。
REQUIRED_WIRING = {
    "app.jsx": {
        "host": "MainApp",
        "units": ["useHomeGreeting({", "useMainAppPersistence({", "createContextConsolidator({",
                  "createAccountActions({", "createChatSenders({", "createCallController({"],
    },
    "screens.jsx": {
        "host": "SettingsScreen",
        "units": ["useDiagnosticsPanel()", "<SettingsGeneralSection", "<SettingsDataSection",
                  "<SettingsDiagnosticsSection", "<SettingsMaintenanceSection", "<SettingsPrivacySection"],
    },
    "chat.jsx": {
        "host": "ChatThread",
        "units": ["useVoiceRecorder({"],
    },
}


def top_level_blocks(text):
    """按列 0 声明切分，返回 [(名字, 行数)]。"""
    lines = text.split("\n")
    marks = [i for i, line in enumerate(lines) if DECL_RE.match(line)]
    marks.append(len(lines))
    blocks = []
    for index in range(len(marks) - 1):
        start, end = marks[index], marks[index + 1]
        match = NAME_RE.match(lines[start])
        if match:
            blocks.append((match.group(1), end - start))
    return blocks


def host_body(text, host):
    """截取宿主组件自身的函数体（到下一个列 0 声明为止），不含其后的拆分单元。"""
    lines = text.split("\n")
    marks = [i for i, line in enumerate(lines) if DECL_RE.match(line)]
    start = next(i for i, line in enumerate(lines) if line.startswith("function %s(" % host))
    following = [m for m in marks if m > start]
    end = following[0] if following else len(lines)
    return "\n".join(lines[start:end])


class FunctionSizeBudgetTests(unittest.TestCase):
    def test_no_frontend_function_regrows_past_its_budget(self):
        for filename, budgets in SIZE_BUDGETS.items():
            blocks = dict(top_level_blocks((WEB / filename).read_text(encoding="utf-8")))
            for name, budget in budgets.items():
                with self.subTest(file=filename, function=name):
                    self.assertIn(name, blocks, f"{filename} 里找不到 {name}")
                    self.assertLessEqual(
                        blocks[name], budget,
                        f"{filename} 的 {name} 长到 {blocks[name]} 行（预算 {budget}），该继续拆了",
                    )

    def test_split_units_are_still_wired_into_their_host(self):
        for filename, spec in REQUIRED_WIRING.items():
            text = (WEB / filename).read_text(encoding="utf-8")
            body = host_body(text, spec["host"])
            for unit in spec["units"]:
                with self.subTest(file=filename, unit=unit):
                    self.assertIn(unit, body,
                                  f"{spec['host']} 不再调用 {unit}，抽出的单元成了死代码")


if __name__ == "__main__":
    unittest.main()
