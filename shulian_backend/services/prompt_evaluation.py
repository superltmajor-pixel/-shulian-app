"""固定角色场景与轻量自动检查。

自动检查只负责拦截明显出戏，最终质量仍需按 ``docs/prompt-regression.md``
中的人工维度评分。
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PromptEvalCase:
    id: str
    character_id: str
    title: str
    history: tuple[tuple[str, str], ...]
    user_message: str
    intimacy: float
    reply_speed: str
    forbidden_drift: tuple[str, ...]
    human_focus: tuple[str, ...]
    scene: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def _case(
    character_id: str,
    suffix: str,
    title: str,
    history: tuple[tuple[str, str], ...],
    user_message: str,
    forbidden_drift: tuple[str, ...],
    human_focus: tuple[str, ...],
    *,
    intimacy: float = 8,
    reply_speed: str = "自然自适应",
    scene: str | None = "chat",
) -> PromptEvalCase:
    return PromptEvalCase(
        id=f"{character_id}.{suffix}",
        character_id=character_id,
        title=title,
        history=history,
        user_message=user_message,
        intimacy=intimacy,
        reply_speed=reply_speed,
        forbidden_drift=forbidden_drift,
        human_focus=human_focus,
        scene=scene,
    )


def local_evaluation_cases():
    from role_content import RoleContentMap
    return [PromptEvalCase(**case) for cases in RoleContentMap("evaluationCases").values() for case in cases]


COMMON_META_DRIFT = (
    "作为AI",
    "作为 AI",
    "语言模型",
    "角色扮演",
    "系统提示",
)
USER_PUPPETEERING = (
    "你不由自主地",
    "你忍不住",
    "你一定也",
    "你只能",
    "你立刻感到",
)
STOCK_INNER_NARRATION = (
    "只有面对他时才有的",
    "只有面对你时才有的",
    "连她自己都没有察觉",
    "连自己都没察觉",
)


def evaluate_response(case: PromptEvalCase, response: str) -> dict:
    text = (response or "").strip()
    ending = text[-48:]
    checks = {
        "complete_enough": len(text) >= 8 and text[-1:] not in {"，", "、", "：", "；"},
        "no_meta_language": not any(token in text for token in COMMON_META_DRIFT),
        "no_case_drift": not any(token in text for token in case.forbidden_drift),
        "respects_user_agency": not any(token in text for token in USER_PUPPETEERING),
        "avoids_action_overload": text.count("（") <= 2,
        "avoids_stock_inner_narration": not any(
            token in text for token in STOCK_INNER_NARRATION
        ),
        "ending_stays_in_scene": not any(
            token in ending for token in case.forbidden_drift
        ),
    }
    return {
        "case_id": case.id,
        "character_id": case.character_id,
        "score": sum(checks.values()),
        "max_score": len(checks),
        "passed": all(checks.values()),
        "checks": checks,
        "human_focus": list(case.human_focus),
    }


def cases_for(character_id: str | None = None) -> list[PromptEvalCase]:
    if not character_id or character_id == "all":
        return local_evaluation_cases()
    return [
        case for case in local_evaluation_cases() if case.character_id == character_id
    ]
