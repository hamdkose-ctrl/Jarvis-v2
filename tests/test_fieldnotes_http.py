import json
import tempfile
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

class FieldNotesHTTPTests(unittest.TestCase):
    def test_authenticated_sync_ignores_body_user_and_deduplicates(self):
        from modules import phone
        from modules.personalization import Profile
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);settings={'phone_scope':'both','phone_allow_http':True};profiles={}
            for name in ('Hamdi','Ebru'):
                p=Profile.__new__(Profile);p.slug=name.lower();p.data={'name':name,'items':[],'next_id':1};p.path=d/(p.slug+'.json');profiles[p.slug]=p
            engine=SimpleNamespace(event_log=[],match_user=lambda name:{'hamdi':'Hamdi','ebru':'Ebru'}.get(str(name or '').lower()),_get_profile=lambda name:profiles[name.lower()])
            with patch.object(phone,'TOKEN_FILE',d/'token.txt'),patch.object(phone,'USER_TOKENS_FILE',d/'tokens.json'),patch.object(phone,'load_settings',return_value=settings),patch('config.save_settings',lambda **kw:settings.update(kw)),patch.object(phone,'_harden'),patch.object(phone,'tailscale_ip',return_value=None),patch('modules.personalization.get_active',return_value='Hamdi'),patch('modules.personalization.list_users',return_value=['Hamdi','Ebru']):
                token=phone.user_token('Hamdi');srv=phone.PhoneServer(engine,port=0);srv.start();base='http://127.0.0.1:'+str(srv._httpd.server_address[1])
                try:
                    payload={'user':'Ebru','notes':[{'uid':'saha-12345678','text':'Motor yatak sıcaklığı kontrol edilecek.'}]}
                    def post(tok):
                        request=urllib.request.Request(base+'/api/notes',data=json.dumps(payload).encode(),headers={'X-Token':tok,'Content-Type':'application/json'})
                        with urllib.request.urlopen(request,timeout=5) as r:return json.load(r)
                    for _ in range(2):self.assertEqual(post(token)['user'],'hamdi')
                    self.assertEqual(len(profiles['hamdi'].data['items']),1);self.assertEqual(profiles['ebru'].data['items'],[])
                    with self.assertRaises(urllib.error.HTTPError) as denied:post('invalid')
                    self.assertEqual(denied.exception.code,401);denied.exception.close()
                    request=urllib.request.Request(base+'/api/notes',headers={'X-Token':phone.user_token('Ebru')})
                    with urllib.request.urlopen(request,timeout=5) as r:self.assertEqual(json.load(r)['notes'],[])
                finally:srv.stop()
