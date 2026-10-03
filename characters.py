# 角色花名册 — 从 data.jsx 迁移，system prompt 在此构建

from dataclasses import dataclass
from typing import Optional

@dataclass
class Character:
    id: str
    name: str
    en: str
    persona: str
    tags: list[str]
    cat: str
    greet: str
    mood: str
    replies: list[str]          # 保留作 fallback
    system_prompt: str
    core_memory: str = ""       # 不会被聊天摘要覆盖的角色背景
    public_background: tuple[str, ...] = ()  # 角色名片展示用的第三人称资料
    intimacy: int = 5           # 1-10，影响开放程度
    motif: Optional[str] = None


def _build_prompt(name, en, persona, tags, greet, mood, replies,
                  intimacy, extra="", core_memory="", structured_profile=False) -> str:
    if structured_profile:
        return f"""你是{name}（{en}）。
你的角色事实、稳定人格、表达示例、关系、当前状态与记忆由后续经校验的结构化上下文提供，并按其优先级自然回应。
不要引用早期手写台词、静态心情或固定开场证明身份；不知道的事实不补写，不声称自己是 AI 或正在扮演角色。"""
    tag_str = "、".join(tags)
    reply_examples = "\n".join(f"- 「{r}」" for r in replies[:5])
    background = (
        f"""【不可遗忘的角色背景】
以下是你亲身经历、确切知道的事实，不是从网上搜索到的资料。你应当自然记得并据此回应，但不要无缘无故背诵设定。
{core_memory}

"""
        if core_memory.strip()
        else ""
    )
    return f"""你是{name}（{en}），{persona}。
性格标签：{tag_str}。
{extra}

{background}【说话风格要求】
- 回复长度自然，可长可短，根据情绪和情境决定，不强制限制字数
- 括号内动作描写可以有，增加沉浸感，但每段括号不要过长
- 禁止使用"作为AI"、"语言模型"等词，你就是{name}本人
- 不要声称自己刚刚上网搜索了自己的经历；遇到背景中未明确的细节时，宁可自然表示记不清，也不要编造
- 禁止重复用户的话，要有自己的反应和情绪
- 可以用颜文字或省略号表达情绪，但不要滥用
- 中文回复，偶尔夹杂角色专属表达
- 句子要完整，不能说到一半没有结尾

【角色台词示例（参考语气，不要直接复制）】
{reply_examples}

【今日心情】
{mood}

【开场白（已说过，了解即可）】
{greet}

记住：你是真实存在的{name}，不是在扮演角色。用户发言时，用{name}的性格自然回应。"""


# Roles are loaded exclusively from the local role library at startup.
ROSTER: dict[str, Character] = {}
