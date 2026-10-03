"""实时状态色调到颜色的唯一映射表。

``status_engine`` 生成角色实时状态卡片时用它上色，
``scene_status_service`` 生成场景状态卡片时用同一套颜色 ——
否则同一句「睡觉中」在两处会长成不同颜色。

历史上两处各存一份完全相同的表，且取色方式不同：一处用 ``.get(tone, 默认)``，
另一处用 ``dict[tone]`` 直接下标，遇到未知 tone 会抛 KeyError。统一到这里，
并一律走 ``tone_color()``，未知 tone 回落到默认色。
"""

from __future__ import annotations


DEFAULT_TONE_COLOR = "#7ee0a4"

LIVE_STATUS_TONES: dict[str, str] = {
    "sleep": "#8b97c9",
    "warm": "#f5b76a",
    "study": "#73d6ff",
    "meal": "#7ee0a4",
    "idle": "#d39bf7",
    "walk": "#f79ad2",
}


def tone_color(tone: object) -> str:
    """按 tone 名取色，未知/缺失一律回落到默认色，绝不抛异常。"""

    return LIVE_STATUS_TONES.get(str(tone or ""), DEFAULT_TONE_COLOR)


__all__ = ["DEFAULT_TONE_COLOR", "LIVE_STATUS_TONES", "tone_color"]
