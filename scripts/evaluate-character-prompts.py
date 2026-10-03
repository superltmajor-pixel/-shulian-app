"""导出固定场景，或在明确传入 --live 时调用当前 AI 做回归评测。"""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chat import get_reply
from characters import ROSTER
from role_archive import apply_role_library_to_roster
from status_engine import get_schedule_status
from shulian_backend.services.ai_config_service import resolve_ai_config
from shulian_backend.services.prompt_evaluation import cases_for, evaluate_response


def main() -> int:
    apply_role_library_to_roster(ROSTER)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--character",
        default="all",
        choices=("all", *ROSTER),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="显式调用当前配置的 AI；默认只导出用例，不产生 API 请求。",
    )
    parser.add_argument(
        "--one-per-character",
        action="store_true",
        help="从每个本地角色选择第一个固定场景。",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--channel",
        choices=("all", "shared", "remote"),
        default="all",
        help="筛选共同场景或远程消息自然度用例。",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    selected = cases_for(args.character)
    if args.channel == "shared":
        selected = [case for case in selected if case.scene is not None]
    elif args.channel == "remote":
        selected = [case for case in selected if case.scene is None]
    if args.one_per_character:
        seen = set()
        representatives = []
        for case in selected:
            if case.character_id in seen:
                continue
            seen.add(case.character_id)
            representatives.append(case)
        selected = representatives
    if args.limit > 0:
        selected = selected[: args.limit]

    results = []
    if args.live:
        status = resolve_ai_config()
        if not status.get("ready"):
            raise SystemExit("AI service is not ready")
        for case in selected:
            history = [
                {"role": role, "content": content}
                for role, content in case.history
            ]
            live_status = get_schedule_status(ROSTER[case.character_id])
            if case.scene is not None:
                live_status.update(
                    {
                        "label": "与你相处中",
                        "detail": "最近对话已经确认双方处在同一个共同场景",
                        "source": "conversation",
                        "scene": case.scene,
                    }
                )
            response = get_reply(
                case.character_id,
                case.user_message,
                history,
                case.reply_speed,
                "",
                case.intimacy,
                live_status=live_status,
            )
            results.append(
                {
                    **case.as_dict(),
                    "response": response,
                    "automatic": evaluate_response(case, response),
                }
            )
    else:
        results = [case.as_dict() for case in selected]

    payload = {
        "live": args.live,
        "count": len(results),
        "results": results,
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
