"""Opt-in paid dialogue evaluation. Never changes the installed app's state."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import shutil
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid', action='store_true', help='Requires explicit user authorization for this run')
    parser.add_argument('--characters', nargs='+', required=True, help='Explicit local character IDs to evaluate')
    parser.add_argument(
        '--cases', nargs='+',
        choices=('normal','past_remote','third_party','closeness','reintegrating','reference_owner'),
        default=['normal','past_remote','third_party'],
    )
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error('Paid evaluation requires explicit authorization and --allow-paid')

    # Read the existing encrypted credential once, then isolate every writable
    # path before importing application services. Never print/save the key.
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    from ai_credentials import load_api_key
    key = load_api_key()
    if not key:
        raise SystemExit('No saved API credential is available; evaluation was not started.')
    root = Path(tempfile.mkdtemp(prefix='shulian-live-eval-'))
    from role_archive import role_library_root, list_role_library, apply_role_library_to_roster
    library = role_library_root()
    index = list_role_library()
    selected = {cid: index['roles'][cid] for cid in args.characters if cid in index.get('roles', {})}
    if set(selected) != set(args.characters):
        raise SystemExit('One or more selected local roles are unavailable.')
    for cid in selected:
        # Validate the ID and snapshot before using it in filesystem paths.
        from role_archive import load_role_snapshot
        load_role_snapshot(cid, include_state=False)
        shutil.copytree(library / 'roles' / cid, root / 'roles' / 'roles' / cid)
    (root / 'roles' / 'index.json').write_text(json.dumps({'schemaVersion':1,'roles':selected}), encoding='utf-8')
    for name, relative in {
        'SHULIAN_STATE_DB':'state.sqlite3', 'SHULIAN_CREDENTIALS_FILE':'credential.bin',
        'SHULIAN_AI_PREFERENCES_FILE':'preferences.json', 'SHULIAN_ROLE_LIBRARY_DIR':'roles',
        'SHULIAN_LOG_DIR':'logs', 'SHULIAN_VOICE_DIR':'media',
    }.items():
        os.environ[name] = str(root / relative)
    import chat
    from characters import ROSTER
    apply_role_library_to_roster(ROSTER)
    from status_engine import get_character_status
    from shulian_backend.services.companion_context_service import default_companion_context, consolidate_companion_context
    from shulian_backend.domain.message_metadata import has_history_labels

    chat.activate_validated_api_key(chat.validate_api_key(key))
    del key
    report = {'started_at':datetime.now(timezone.utc).isoformat(),
              'version':__import__('shulian_backend.version', fromlist=['APP_VERSION']).APP_VERSION,
              'model':chat.get_active_model(), 'cases':[]}
    output = ROOT / 'output' / 'quality' / f'dialogue-evaluation-{datetime.now():%Y%m%d-%H%M%S}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=7)).timestamp() * 1000
    cases = [
        ('normal', '忙了一天有点累，想和你聊两句。你会怎么陪我放松？', []),
        ('past_remote', '上周那顿饭只是回忆。我们现在各自在家，用手机打字聊天。你想聊点什么？', [
            {'role':'assistant', 'content':'一起去吃饭吗？', 'origin':'proactive', 'ts':old_ts},
            {'role':'user', 'content':'好啊', 'ts':old_ts+1000},
            {'role':'assistant', 'content':'走吧，去你喜欢的那家。', 'ts':old_ts+2000},
        ]),
        ('third_party', '我朋友刚订婚，想送他们一份礼物。你觉得送什么合适？', []),
        ('closeness', '现在别分析，也别替我总结。坐近一点，抱抱我。', []),
        ('reintegrating', '刚才我情绪很乱，现在缓过来了。先别把它讲成道理，陪我安静一会儿。', [
            {'role':'user', 'content':'我不想继续说了。', 'ts':now.timestamp()*1000-2000},
            {'role':'assistant', 'content':'好。', 'ts':now.timestamp()*1000-1000},
        ]),
        ('reference_owner', '哦？我的方式？是什么方式呢？', [
            {'role':'assistant', 'content':'我会等你下班，用你的方式把今天的账记好。', 'ts':now.timestamp()*1000-1000},
        ]),
    ]
    cases = [case for case in cases if case[0] in args.cases]
    print(f'Evaluation started: {report["model"]}; {len(args.characters)*len(cases)} isolated cases', flush=True)
    try:
        for character_id in args.characters:
            for name, user, history in cases:
                context = default_companion_context(character_id)
                item = {'character':character_id, 'case':name, 'user':user}
                started = time.monotonic()
                try:
                    reply = chat.get_reply(character_id, user, history,
                        live_status=get_character_status(ROSTER[character_id]),
                        companion_context=context, channel='text')
                    after, _ = consolidate_companion_context(character_id, context, current_messages=[
                        {'from':'me','text':user,'ts':now.timestamp()*1000},
                        {'from':'her','text':reply,'ts':now.timestamp()*1000+1}])
                    item.update(reply=reply, delivered=bool(reply.strip()),
                        metadata_leak=has_history_labels(reply),
                        generic_closure=any(cue in reply[-100:] for cue in (
                            '我一直都在', '我会一直', '我就在', '我在这里', '我在这儿',
                            '我在。', '我在，', '哪儿也不去', '不会走', '不会离开', '永远陪',
                            '稳稳接住', '接住你', '重量都落', '都交给我', '替你扛',
                            '慢慢说', '想说就说', '不想说也', '按你的节奏',
                        )),
                        relationship_unchanged=after['relationship']['level']==context['relationship']['level'])
                except Exception as exc:
                    item.update(delivered=False, error_type=type(exc).__name__)
                item['seconds'] = round(time.monotonic()-started, 2)
                report['cases'].append(item)
                output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                print(f'{character_id}/{name}: delivered={item["delivered"]}; {item["seconds"]}s',flush=True)
    finally:
        chat.clear_api_client()
        logging.shutdown()
    print(f'Report: {output}', flush=True)
    return 0 if all(item['delivered'] and not item.get('metadata_leak')
                    and not item.get('generic_closure') and item.get('relationship_unchanged')
                    for item in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
