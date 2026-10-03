"""Synthetic, disposable role archives. No shipped or personal character data.

The five independent records exercise different relationship levels, aliases,
categories and grounded personality material through the real archive loader.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

IDS = ('sample_a', 'sample_b', 'sample_c', 'sample_d', 'sample_e')
NAMES = ('林舟', '许宁', '顾遥', '苏岚', '星禾')


def frontend_profiles():
    return [dict(id=cid, name=name,
                 accent=dict(accent='#ab1234', accent2='#cd5678', accent3='#ef9012', ink='#ffffff'),
                 forms=[dict(img=f'/api/role-library/{cid}/banner-{n}.png',
                             imgPos=f'{40+n*10}% 35%', imgFit='cover') for n in range(2)],
                 gallery=[f'/api/role-library/{cid}/portrait.png'],
                 quiz=[dict(id=f'{cid}_{n:02d}', question=f'合成问题 {n}',
                            options=['甲','乙','丙','丁'], answer=n%4) for n in range(1,11)])
            for cid,name in zip(IDS,NAMES)]


def load_frontend_roles(profiles):
    import json
    import subprocess
    result = subprocess.run(['node', str(Path(__file__).with_name('frontend_role_runtime.cjs'))],
                            input=json.dumps(profiles), text=True, encoding='utf-8',
                            capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout)


def personality_payload(cid, name):
    def item(suffix, **fields):
        return dict(id=f'{cid}.{suffix}', sourceEntryIds=[f'{cid}.identity'], **fields)
    statements = {key: [item(f'{key}.{n}', text=f'{name}重视真诚沟通，也会倾听第{n+1}种不同意见。', origin='interpretive_extension') for n in range(2)]
                  for key in ('coreTraits', 'values', 'voice', 'innerDynamics')}
    examples = []
    for scenario, triggers in [('daily', []), ('intimacy', ['爱', '抱', '吻', '喜欢']),
                               ('media', ['想到你', '像你']), ('support', ['难过']),
                               ('conflict', ['争执']), ('interest', ['阅读']),
                               ('decision', ['选择']), ('future', ['明天'])]:
        examples.append(item(f'example.{scenario}', scenario=scenario,
            origin='official_adaptation', user='今天过得怎么样？', assistant=f'{name}：可以慢慢告诉我。',
            rationale='合成夹具的审核说明，不应渲染进提示词',
            officialSourceIds=[f'{cid}.source'], sourceContext='原创测试设定',
            adaptationNote='用于离线行为验证', triggers=triggers, priority=80,
            channels=['text', 'image'] if scenario=='media' else ['text'],
            subjectRelations=['user_compares_character'] if scenario=='media' else [],
            requiresExplicitComparison=scenario=='media'))
    return dict(schemaVersion=4, characterId=cid, displayName=name, status='reviewed',
        **statements,
        closingStyles=[item(f'closing.{n}', text=text, origin='interpretive_extension') for n,text in enumerate(('越动情越少解释，用自然的简短话语收尾。','日常聊天以具体的关心收尾。','分歧时留下继续沟通的空间。'))],
        dynamicStates=[item(f'state.{mode}',mode=mode,instruction=f'{name}在{mode}状态下认真回应。',
                            origin='interpretive_extension',relationshipFloor=1,activationFloor=0,priority=80)
                       for mode in ('daily','relaxed','vulnerable','intimate','repair','reintegrating','boundary')],
        behaviorAnchors=[item('anchor.daily',instruction='先回应当前问题。',triggers=[],priority=50),
                         item('anchor.intimacy',instruction='尊重当前意愿。',triggers=['爱','抱','吻','喜欢'],priority=80)],
        dialogueExamples=examples,
        outputRails=[item('rail.identity',phrases=['我是其他测试角色'],severity='hard',repairInstruction='保持自己的身份。')])


def extensions(cid, name, index):
    level=(10,10,6,6,7)[index]
    bible=dict(schemaVersion=1,characterId=cid,displayName=name,work='原创测试设定',status='reviewed',
        companionOverlay='关系变化来自用户确认，背景事实不随对话改变。',
        sources=[dict(id=f'{cid}.source',sourceType='test_fixture',title='合成角色说明',publisher='Test author',
                      authority='official',locator='测试章节一')],
        entries=[dict(id=f'{cid}.identity',type='canon_fact',statement=f'{name}是一位喜欢阅读的旅行者。',
                      keywords=['身份','家人'],sourceIds=[f'{cid}.source'],evidenceLevel='direct',alwaysInclude=True)])
    result=dict(bible=bible,personality=personality_payload(cid,name),aliases=[name, f'阿{name[-1]}'],
                tts={'voice':'zh-CN-XiaoxiaoNeural','rate':'+0%','pitch':'+4Hz'},
                initialRelationship={'level':level,'title':'婚约伴侣' if index==1 else '心意相通',
                                     'dimensions':[4,4,4,4],'events':['marriage_commitment'] if index==1 else ['mutual_affection'],
                                     'commitments':['双方约定在用户生日当天结婚。'] if index==1 else []},
                evaluationCases=[dict(id=f'{cid}.case.{n}',character_id=cid,title='合成测试场景',history=[],
                                      user_message='今天过得怎么样？',intimacy=6,reply_speed='自然自适应',
                                      forbidden_drift=['我是其他测试角色'],human_focus=['保持身份'],scene='chat') for n in range(6)])
    if index==0:
        result['aliases'] += ['小舟','Voyager']
        bible['entries'][0]['statement'] += ' 又名小舟（Voyager）。'
        result['tts'] = {'voice':'zh-CN-XiaoyiNeural','rate':'-4%','pitch':'+8Hz'}
        result['initialRelationship'].update(title='永恒契约', events=['eternal_covenant'])
    if index==1:
        result['staleMarriage']={'cues':['见同事','理顺事务','公务处理完','忙完工作','事务结束'],
                                'key':'sample_b_marriage_after_work',
                                'instruction':'冲突事实裁决：结婚约定不再附加‘完成公务、见过同僚或理顺事务后’等旧前置条件。'}
    return result


def role_fixture_hooks():
    state={}
    def setup():
        from characters import Character, ROSTER, _build_prompt
        from role_archive import archive_role_snapshot, apply_role_library_to_roster
        state['temp']=tempfile.TemporaryDirectory(prefix='shulian-test-roles-')
        root=Path(state['temp'].name)
        state['env']=patch.dict(os.environ,{'SHULIAN_ROLE_LIBRARY_DIR':str(root)})
        state['roster']=patch.dict(ROSTER,{},clear=True)
        state['env'].start();state['roster'].start()
        for i,(cid,name) in enumerate(zip(IDS,NAMES)):
            background=f'{name}是一位喜欢阅读的旅行者。'
            if i==0: background += ' 又名小舟（Voyager）。'
            char=Character(id=cid,name=name,en='Voyager' if i==0 else cid,persona=background,tags=['阅读'],
                           cat='校园' if i==2 else '自建',greet='你好',mood='平静',replies=['欢迎回来'],
                           core_memory=background,public_background=(background,),intimacy=6,
                           system_prompt=_build_prompt(name,cid,background,['阅读'],'你好','平静',[],6,structured_profile=True))
            extra=extensions(cid,name,i)
            if i==0: char.core_memory += ' 又名小舟（Voyager）。'
            archive_role_snapshot(character=char,frontend_profile={'id':cid,'name':name,'origin':'custom'},
                                  relationship={},memory='',intimacy=6,started_at=None,current_messages=[],
                                  archived_sessions=[],build_id='test-fixture',web_dir=root,voice_dir=root,
                                  extensions=extra,index_metadata={'origin':'custom'})
        apply_role_library_to_roster(ROSTER)
    def teardown():
        state['roster'].stop();state['env'].stop();state['temp'].cleanup()
    return setup, teardown
