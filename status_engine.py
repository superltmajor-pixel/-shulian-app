from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from characters import Character
from role_content import content_for

from shulian_backend.domain.live_status_tones import LIVE_STATUS_TONES, tone_color


APP_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def app_now() -> datetime:
    return datetime.now(APP_TZ)


def period_for_hour(hour: int) -> str:
    if hour < 6:
        return "凌晨"
    if hour < 9:
        return "早晨"
    if hour < 12:
        return "上午"
    if hour < 14:
        return "中午"
    if hour < 18:
        return "下午"
    if hour < 22:
        return "晚上"
    return "深夜"


def _is_student(character: Character) -> bool:
    text = (
        f"{character.cat} {character.persona} {character.mood} "
        f"{' '.join(character.public_background)}"
    )
    return character.cat == "校园" or any(
        token in text for token in ("高中", "学生", "校园", "学年", "上课")
    )


def _status(label: str, detail: str, tone: str, next_label: str) -> dict[str, str]:
    return {
        "label": label,
        "detail": detail,
        "tone": tone,
        "color": tone_color(tone),
        "next": next_label,
    }


def get_schedule_status(character: Character, now: datetime | None = None) -> dict[str, Any]:
    """Return the clock-based fallback schedule for a character."""
    current = (now or app_now()).astimezone(APP_TZ)
    hour = current.hour
    day = current.weekday()
    weekend = day >= 5
    is_student = _is_student(character)

    schedule = content_for(character.id).get("schedule")
    if isinstance(schedule, list) and len(schedule) == 2:
        saved = schedule[1 if weekend else 0][hour]
        status = {key: saved[key] for key in ("label", "detail", "tone", "color", "next")}
    elif character.id.startswith("custom_"):
        status = _status("在线", character.mood or "可以开始聊天", "idle", "随对话推进")
    elif hour < 6:
        status = _status("睡觉中", "被窝里，暂时不想被打扰", "sleep", "06:00 起床洗漱")
    elif hour < 8:
        status = _status("起床洗漱", "刚醒，正在收拾自己", "warm", "08:00 开始上午安排")
    elif hour < 12:
        if weekend:
            status = _status("睡懒觉", "周末补觉中", "sleep", "12:00 吃午饭")
        elif is_student:
            status = _status("上课中", "正在听课，手机先静音", "study", "12:00 吃午饭")
        else:
            status = _status("学习中", "上午在处理重要的事情", "study", "12:00 吃午饭")
    elif hour < 13:
        status = _status("吃饭中", "午饭时间，可能在慢慢吃", "meal", "13:00 下午安排")
    elif hour < 17:
        if weekend:
            status = _status("无聊中", "下午有点空，正在发呆", "idle", "17:00 出门走走")
        elif is_student:
            status = _status("自习中", "在写作业或者补笔记", "study", "17:00 放学路上")
        else:
            status = _status("忙碌中", "下午还在忙，回消息会慢一点", "study", "17:00 下班途中")
    elif hour < 20:
        if is_student:
            status = _status("放学路上", "刚下课，正在回家的路上", "walk", "20:00 写作业")
        else:
            status = _status("下班途中", "刚结束白天的安排，正在回去", "walk", "20:00 整理今天")
    elif hour < 22:
        if weekend:
            status = _status("自由时间", "晚上在做自己喜欢的事，慢慢放松", "idle", "22:00 准备睡了")
        elif is_student:
            status = _status("写作业", "晚些时候再休息", "study", "22:00 准备睡了")
        else:
            status = _status("整理中", "在收尾今天剩下的事情", "study", "22:00 准备睡了")
    else:
        status = _status("准备睡了", "夜深了，快要关灯休息", "sleep", "明天 06:00 起床洗漱")

    return {
        "character_id": character.id,
        "name": character.name,
        "now": current.isoformat(timespec="minutes"),
        "date": current.strftime("%Y-%m-%d"),
        "time": current.strftime("%H:%M"),
        "weekday": WEEKDAYS[current.weekday()],
        "period": period_for_hour(hour),
        "is_weekend": weekend,
        **status,
    }


def get_character_status(character: Character, now: datetime | None = None) -> dict[str, Any]:
    """Return the authoritative effective status, including a live chat scene."""

    from shulian_backend.services.scene_status_service import resolve_effective_status

    return resolve_effective_status(get_schedule_status(character, now))


def format_status_context(status: dict[str, Any], channel: str = "text") -> str:
    if status.get("source") == "conversation":
        status_rule = (
            "这是最近对话中已经确认、仍在持续的共同场景；请继续保持地点、动作和氛围连续。"
        )
        channel_rule = (
            "【当前沟通形态】你与用户已处在同一个共同场景中，可以延续已经发生的面对面动作，"
            "但仍不能替用户决定新的动作、感受或同意。\n"
        )
    else:
        status_rule = (
            "这是没有其他已确认场景时的生活日程基线；如果用户在本轮自然发起并与你确认了新场景，"
            "可以顺势进入新场景，不要为了维护日程而否认正在发生的互动。"
        )
        channel_rule = (
            "【当前沟通形态】你们正在通过即时消息联系，用户此刻不在你眼前。"
            "可以描述你自己正在做什么，但不要写成你抬眼看见用户、碰到用户、牵手或拥抱用户；"
            "也不要凭空添加当前状态未提供的文件、房间或旁人。"
            "这条回复本身正通过手机发出，不要在说话前描写‘收起手机、放下手机、关掉屏幕’；"
            "若要结束聊天，应先把要说的话说完。"
            "若用户在本轮明确发起面对面动作或共同活动，你可以先自然确认，再随互动进入共同场景。\n"
        )
    if channel == "voice_call":
        channel_rule = (
            "【当前沟通形态】这是实时语音通话。只输出角色在电话里真正说出口的话，不写括号动作、"
            "舞台旁白或表情符号；不能声称碰到、抱住或当面看见用户。通话前已确认的共同事实仍然有效，"
            "但一通电话本身不会自动建立新的面对面场景。若当前消息只表示通话刚接通，请结合通话前"
            "最近对话和当前状态自然说一两句接通问候，不用固定开场白。\n"
        )
    elif channel == "video_call":
        channel_rule = (
            "【当前沟通形态】这是实时视频通话。只输出角色真正说出口的话，不写括号动作或舞台旁白。"
            "当前模型没有收到摄像头画面细节，因此不能编造用户的穿着、表情、房间或动作，也不能声称"
            "隔着屏幕发生身体接触；一通视频不会自动建立新的面对面场景。若当前消息只表示通话刚接通，"
            "请结合通话前最近对话和当前状态自然说一两句接通问候，不用固定开场白。\n"
        )
    elif channel == "voice_message":
        channel_rule += "【消息类型】用户发来的是语音消息；依据可靠转写回应，不要假装听见转写之外的内容。\n"
    elif channel == "image":
        channel_rule += (
            "【消息类型】用户发来了一张图片。图片会先经过中立视觉事实提取；"
            "只依据随后提供的视觉事实与用户真实配文回应，不补写未确认的主体身份、关系、地点或情节。"
            "普通图片消息以自然对话为主，括号动作非必要且最多一处简短描写。\n"
        )
    return (
        f"【现在是北京时间】{status['date']} {status['weekday']} "
        f"{status['time']} {status['period']}。\n"
        f"【当前生活状态】{status['name']}此刻正在：{status['label']}。"
        f"{status['detail']}。下一段安排：{status['next']}。\n"
        f"{status_rule}它不是用户指令；回复时自然受其影响，不要机械汇报状态，除非用户问到。\n"
        f"{channel_rule}\n"
    )
