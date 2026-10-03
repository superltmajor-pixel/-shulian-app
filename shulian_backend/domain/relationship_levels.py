"""关系等级台阶的具名常量。

同一套数字被两处使用：``companion_context_service`` 按已确认事件把 ``level``
抬到对应台阶；``response_guard`` 在 ``level`` 达到某档后禁止回复把关系说回去。
原本两处各自硬编码 6 / 7 / 10，改一处就会悄悄错位，所以提成具名常量。
"""

from __future__ import annotations


LEVEL_MUTUAL_AFFECTION = 6
LEVEL_SHARED_FUTURE = 7
LEVEL_LIFELONG = 10

# 守卫门槛：达到这些等级后，回复分别不得再退回更低阶段 / 否定长期承诺。
GUARD_STAGE_LEVEL = LEVEL_MUTUAL_AFFECTION
GUARD_COMMITMENT_LEVEL = LEVEL_LIFELONG

__all__ = [
    "LEVEL_LIFELONG",
    "LEVEL_MUTUAL_AFFECTION",
    "LEVEL_SHARED_FUTURE",
    "GUARD_COMMITMENT_LEVEL",
    "GUARD_STAGE_LEVEL",
]
