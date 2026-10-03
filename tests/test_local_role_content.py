import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from characters import Character, ROSTER
from role_archive import archive_role_snapshot, load_role_snapshot, apply_role_library_to_roster
from role_content import content_for
from public_source import private_path, public_web_file


class LocalRoleContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'SHULIAN_ROLE_LIBRARY_DIR': self.temp.name,
            'SHULIAN_STATE_DB': str(Path(self.temp.name) / 'state.sqlite3'),
        })
        self.env.start()
        self.roster = patch.dict(ROSTER, {}, clear=True)
        self.roster.start()

    def tearDown(self):
        self.roster.stop()
        self.env.stop()
        self.temp.cleanup()

    def archive(self):
        char = Character(id='existing_id', name='林舟', en='Lin', persona='安静的旅行者',
                         tags=['旅行'], cat='自建', greet='你好', mood='平静', replies=['好呀'],
                         system_prompt='完整的原始提示词', core_memory='角色背景',
                         public_background=('在海边长大',), intimacy=6)
        frontend = dict(id=char.id, name=char.name, en=char.en, persona=char.persona,
                        tags=char.tags, cat=char.cat, greet=char.greet, mood=char.mood,
                        relationshipLevel=6, profileIntro='', personality='', speakingStyle='',
                        relationship='', origin='custom', hue=160,
                        forms=[{'name':'常服'}], gallery=[{'title':'相遇'}], quiz=[{'q':'喜欢哪里？'}])
        extensions={'aliases':['林舟','阿舟'], 'tts':{'voice':'example','pitch':'+1Hz'},
                    'initialRelationship':{'level':6,'title':'心意相通','dimensions':[3,3,3,1],
                                           'events':['mutual_affection'],'commitments':[]}}
        archive_role_snapshot(character=char, frontend_profile=frontend, relationship={},
                              memory='', intimacy=6, started_at=100,
                              current_messages=[{'from':'me','text':'已有的聊天','ts':101}],
                              archived_sessions=[], build_id='test', web_dir=self.temp.name,
                              voice_dir=self.temp.name, extensions=extensions,
                              index_metadata={'origin':'custom'})
        return char, frontend, extensions

    def test_empty_install_and_private_content_after_restart(self):
        self.assertEqual(apply_role_library_to_roster({})['loadedCharacterIds'], [])
        char, _, extensions = self.archive()
        restored={}
        self.assertEqual(apply_role_library_to_roster(restored)['loadedCharacterIds'], [char.id])
        self.assertEqual(restored[char.id].system_prompt, char.system_prompt)
        self.assertEqual(content_for(char.id), extensions)

    def test_empty_library_does_not_fail_character_health_checks(self):
        from fastapi.testclient import TestClient
        import main
        check = TestClient(main.app).get('/api/self-check').json()
        self.assertTrue(check['character_bibles']['ok'])
        self.assertTrue(check['personality_profiles']['ok'])
        self.assertEqual(check['character_bibles']['count'], 0)
        self.assertEqual(check['personality_profiles']['count'], 0)

    def test_edit_and_disable_restore_keep_advanced_content_and_existing_id(self):
        from fastapi.testclient import TestClient
        import main
        char, frontend, extensions = self.archive()
        apply_role_library_to_roster(ROSTER)
        client=TestClient(main.app)
        before=load_role_snapshot(char.id)
        detail=client.get(f'/api/role-library/roles/{char.id}').json()
        response=client.put(f'/api/role-library/roles/{char.id}',json={'profile':detail['profile']})
        self.assertEqual(response.status_code,200,response.text)
        after=load_role_snapshot(char.id)
        self.assertEqual(after['extensions'],extensions)
        for key in ('forms','gallery','quiz','hue'):
            self.assertEqual(after['frontend'][key],frontend[key])
        self.assertEqual(after['backend'],before['backend'])
        self.assertEqual(after['state']['currentMessages'],before['state']['currentMessages'])
        self.assertEqual(client.post(f'/api/role-library/roles/{char.id}/disable').status_code,200)
        self.assertNotIn(char.id,ROSTER)
        self.assertEqual(client.post(f'/api/role-library/roles/{char.id}/restore').status_code,200)
        self.assertEqual(ROSTER[char.id].system_prompt,char.system_prompt)
        self.assertEqual(ROSTER[char.id].replies,char.replies)

    def test_edited_advanced_fields_survive_reload_and_restore(self):
        from fastapi.testclient import TestClient
        import main
        char, frontend, extensions = self.archive()
        apply_role_library_to_roster(ROSTER)
        client = TestClient(main.app)
        endpoint = f'/api/role-library/roles/{char.id}'
        before = load_role_snapshot(char.id)
        profile = client.get(endpoint).json()['profile']
        edits = (
            ({'profileIntro': '在山中长大'}, {'core_memory': '在山中长大'}),
            ({'personality': '健谈外向', 'relationship': '同学'},
             {'public_background': ['健谈外向', '同学']}),
            ({'relationshipLevel': 3}, {'intimacy': 3}),
            ({'profileIntro': '', 'personality': '', 'relationship': ''},
             {'core_memory': '', 'public_background': []}),
        )
        expected = dict(before['backend'])
        for values, derived in edits:
            with self.subTest(fields=list(values)):
                profile.update(values)
                response = client.put(endpoint, json={'profile': profile})
                self.assertEqual(response.status_code, 200, response.text)
                expected.update(derived)
                saved = load_role_snapshot(char.id)
                for key in ('core_memory', 'public_background', 'intimacy'):
                    self.assertEqual(saved['backend'][key], expected[key])
                self.assertEqual(saved['extensions'], extensions)
                self.assertEqual(saved['backend']['replies'], before['backend']['replies'])
                for key in ('forms', 'gallery', 'quiz', 'hue'):
                    self.assertEqual(saved['frontend'][key], frontend[key])
                self.assertEqual(saved['state']['currentMessages'], before['state']['currentMessages'])
                restored = {}
                apply_role_library_to_roster(restored)
                self.assertEqual(restored[char.id].core_memory, expected['core_memory'])
                self.assertEqual(list(restored[char.id].public_background), expected['public_background'])
                self.assertEqual(restored[char.id].intimacy, expected['intimacy'])
                self.assertEqual(client.post(endpoint + '/disable').status_code, 200)
                self.assertEqual(client.post(endpoint + '/restore').status_code, 200)
                detail = client.get(f'/api/characters/{char.id}').json()
                self.assertEqual(detail['background'], expected['public_background'])
                self.assertEqual(detail['intimacy'], expected['intimacy'])

    def test_private_data_and_art_excluded_from_public_web_payload(self):
        for path in ('web/assets/private.png','role-library/index.json','web/media/audio.wav',
                     '.env','local-data/state.sqlite3','web/app.jsx.bak','character_bibles/private.json'):
            self.assertTrue(private_path(path),path)
            self.assertFalse(public_web_file(path),path)
        self.assertTrue(public_web_file('web/bundle/app.bundle.js'))
        self.assertTrue(public_web_file('web/shulian-brand-icon.png'))
        self.assertFalse(public_web_file('web/private-photo.png'))
