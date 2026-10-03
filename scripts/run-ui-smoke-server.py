"""Run Shulian's real web app against isolated local-only smoke-test services.

This helper is intentionally separate from the normal launcher.  It creates a
temporary state database, credential path, role library, media directory and
log directory before importing the application, then replaces external AI and
TTS calls with deterministic local responses.  It never reads the installed
client's state and never sends a model request.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _configure_isolated_environment(root: Path) -> None:
    paths = {
        "SHULIAN_STATE_DB": root / "state.sqlite3",
        "SHULIAN_CREDENTIALS_FILE": root / "credentials.bin",
        "SHULIAN_AI_PREFERENCES_FILE": root / "ai-preferences.json",
        "SHULIAN_ROLE_LIBRARY_DIR": root / "role-library",
        "SHULIAN_LOG_DIR": root / "logs",
        "SHULIAN_VOICE_DIR": root / "media",
    }
    for key, value in paths.items():
        os.environ[key] = str(value)
    os.environ["TTS_PROVIDER"] = "edge"


def _install_local_fakes(initial_ai_state: str = "ready") -> Any:
    app_module = importlib.import_module("main")
    chat_router = importlib.import_module("shulian_backend.routers.chat")
    system_router = importlib.import_module("shulian_backend.routers.system")

    from characters import ROSTER
    from status_engine import get_character_status
    from shulian_backend.services import ai_config_service, tts_service
    from shulian_backend.services.scene_status_service import apply_scene_decision

    model_state = {
        "model": "deepseek-v4-flash",
        "provider": "deepseek",
        "configured": initial_ai_state == "ready",
        "remembered": initial_ai_state == "ready",
    }

    def ai_payload(*, ready: bool = True, configured: bool = True) -> dict[str, Any]:
        return {
            "configured": configured,
            "ready": ready,
            "remembered": model_state["remembered"],
            "provider": model_state["provider"],
            "provider_label": "豆包" if model_state["provider"] == "doubao" else "DeepSeek",
            "masked_key": "sk-****smoke",
            "model": model_state["model"],
            "model_options": ai_config_service._model_options_payload(),
            "base_url": "https://example.invalid",
            "error": None,
        }

    def update_model(model: str) -> dict[str, Any]:
        model_state["model"] = model
        return ai_payload(
            ready=model_state["configured"],
            configured=model_state["configured"],
        )

    def resolve_ai_config() -> dict[str, Any]:
        return ai_payload(
            ready=model_state["configured"],
            configured=model_state["configured"],
        )

    def update_ai_config(api_key: str, remember: bool) -> dict[str, Any]:
        model_state["provider"] = "doubao" if api_key.strip().lower().startswith("ark-") else "deepseek"
        model_state["configured"] = True
        model_state["remembered"] = remember
        return resolve_ai_config()

    def remove_ai_config() -> dict[str, Any]:
        model_state["configured"] = False
        model_state["remembered"] = False
        return resolve_ai_config()

    def logout_ai_config() -> dict[str, Any]:
        model_state["configured"] = False
        return resolve_ai_config()

    ai_config_service.resolve_ai_config = resolve_ai_config
    ai_config_service.update_ai_model = update_model
    ai_config_service.update_ai_config = update_ai_config
    ai_config_service.remove_ai_config = remove_ai_config
    ai_config_service.logout_ai_config = logout_ai_config
    system_router.model_adapter_status = lambda: {
        "adapter": "smoke",
        "ready": True,
        "provider": "local",
    }

    def fake_reply(
        character_id: str,
        user_message: str,
        history: list[dict[str, str]],
        reply_speed: str = "日常自然",
        memory: str = "",
        intimacy: float | None = None,
        live_status: dict[str, Any] | None = None,
        cancellation: Any = None,
        proactive: bool = False,
        memory_context: str = "",
        companion_context: object = None,
        channel: str = "text",
        image_url: str | None = None,
        image_caption: str = "",
    ) -> str:
        del history, reply_speed, memory, intimacy, live_status, cancellation
        del memory_context, companion_context, image_url, image_caption
        character = ROSTER[character_id]
        if "一起吃饭" in user_message or "陪我吃饭" in user_message:
            return f"好，我们现在一起吃饭。{character.name}会留在这个场景里陪着你。"
        if "在干什么" in user_message:
            status = get_character_status(character)
            return f"我现在正{status['label']}。你问得正好，我也想听听你在做什么。"
        if channel in {"voice_call", "video_call"}:
            status = get_character_status(character)
            return f"接通了。我们还在{status['label']}，你慢慢说，我在听。"
        if proactive:
            return "刚刚想起你了。等你有空时，再和我说说今天过得怎么样。"
        return "我听见了，也记得我们刚才说到这里。继续告诉我吧。"

    def fake_stream(*args: Any, **kwargs: Any) -> Iterator[str]:
        yield fake_reply(*args, **kwargs)

    def fake_reconcile(
        character: Any,
        user_message: str,
        reply: str,
        history: list[dict[str, str]],
        schedule_status: dict[str, Any],
        channel: str = "text",
    ) -> dict[str, Any]:
        del reply, history
        if channel == "text" and (
            "一起吃饭" in user_message or "陪我吃饭" in user_message
        ):
            return apply_scene_decision(
                schedule_status,
                {"action": "set", "scene": "meal", "confidence": 1.0},
            )
        return get_character_status(character)

    chat_router.chat_backend.get_reply = fake_reply
    chat_router.chat_backend.stream_reply = fake_stream
    chat_router.chat_backend.reconcile_scene_status = fake_reconcile
    chat_router.chat_backend.summarize_memory_context = (
        lambda character_id, old_context, old_memory, messages: old_context
        or json.dumps(
            {
                "version": 2,
                "stable_facts": [],
                "relationship_facts": [],
                "recent_events": [],
            },
            ensure_ascii=False,
        )
    )

    async def fake_tts(
        character_id: str,
        text: str,
        cancellation: Any = None,
    ) -> tuple[bytes, str, str]:
        del character_id, text, cancellation
        return b"ID3", "audio/mpeg", "smoke"

    tts_service.synthesize_tts = fake_tts
    return app_module.app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--initial-ai-state",
        choices=("ready", "missing"),
        default="ready",
        help="Start the isolated UI in the main app or API-key gate.",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="shulian-ui-smoke-") as temporary:
        isolated_root = Path(temporary)
        _configure_isolated_environment(isolated_root)
        app = _install_local_fakes(args.initial_ai_state)
        print(f"isolated_root={isolated_root}", flush=True)
        import uvicorn

        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="warning",
            access_log=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
