import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch
from test_phone_user_tokens import _FakeEngine
from modules import phone

class SecurePhoneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.settings={}
        d=Path(self.tmp.name)
        for item in (patch.object(phone,'TOKEN_FILE',d/'token.txt'),patch.object(phone,'USER_TOKENS_FILE',d/'tokens.json'),
                     patch.object(phone,'_harden'),patch.object(phone,'tailscale_ip',return_value=None),patch.object(phone,'load_settings',side_effect=lambda:self.settings),
                     patch('config.save_settings',side_effect=lambda **kw:self.settings.update(kw)),
                     patch('modules.personalization.get_active',return_value='Hamdi'),patch('modules.personalization.list_users',return_value=['Hamdi','Ebru'])):
            item.start();self.addCleanup(item.stop)
    def test_https_default_has_no_implicit_http_fallback(self):
        self.assertEqual(phone.PhoneServer.scope(),'secure')
        self.settings['phone_scope']='both'
        self.assertEqual(phone.PhoneServer.scope(),'secure')
        self.settings['phone_allow_http']=True
        self.assertEqual(phone.PhoneServer.scope(),'both')
    def test_missing_https_refuses_to_open_server(self):
        srv=phone.PhoneServer(_FakeEngine(),port=0)
        with patch.object(phone,'https_url',return_value=''):
            with self.assertRaisesRegex(OSError,'HTTPS'):srv.start()
        self.assertFalse(srv.running)
    def test_secure_listener_loopback_and_links_have_only_pair_codes(self):
        srv=phone.PhoneServer(_FakeEngine(),port=0)
        with patch.object(phone,'https_url',return_value='https://example.ts.net'),patch.object(phone,'tailscale_ip',return_value='100.100.1.2'):
            url=srv.start()
        self.addCleanup(srv.stop)
        self.assertEqual(srv._httpd.server_address[0],'127.0.0.1')
        self.assertTrue(url.startswith('https://'));self.assertIn('#p=',url);self.assertNotIn(srv.token,url)
        self.assertEqual(len(srv.urls()),1)
        self.assertFalse(phone.allowed_peer('100.100.1.2','secure'))
    def test_legacy_query_credentials_rejected_and_header_post_still_works(self):
        srv=phone.PhoneServer(_FakeEngine(),port=0)
        with patch.object(phone,'https_url',return_value='https://example.ts.net'):srv.start()
        self.addCleanup(srv.stop)
        base='http://127.0.0.1:'+str(srv._httpd.server_address[1]);token=phone.user_token('Ebru')
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base+'/api/ask?k='+token+'&q=test',timeout=5)
        self.assertEqual(error.exception.code,410);error.exception.close()
        request=urllib.request.Request(base+'/api/ask',data=json.dumps({'text':'birinci'}).encode(),headers={'X-Token':token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as result:self.assertIn('Ebru',json.load(result)['reply'])
    def test_siri_setup_has_no_credential_url(self):
        self.assertIn('X-Token',phone.SIRI_PAGE)
        self.assertIn("method:'POST'",phone.SIRI_PAGE)
        self.assertNotIn('/api/ask?k=',phone.SIRI_PAGE)
        self.assertNotIn('fragment.get("k")',phone.PAGE)
    def test_https_target_and_public_exposure_are_verified(self):
        host='example.ts.net:443'
        config={'TCP':{'443':{'HTTPS':True}},'Web':{host:{'Handlers':{'/':{'Proxy':'http://127.0.0.1:8765'}}}}}
        with patch.object(phone,'_ts_run',side_effect=lambda *args:(True,json.dumps(config))):
            self.assertEqual(phone.https_url(strict=True),'https://example.ts.net')
            config['AllowFunnel']={host:True}
            self.assertEqual(phone.https_url(strict=True),'')
            config['AllowFunnel']={host:False}
            config['Web'][host]['Handlers']['/']['Proxy']='http://127.0.0.1:9999'
            self.assertEqual(phone.https_url(strict=True),'')
    def test_unverified_https_status_does_not_pass_secure_mode(self):
        with patch.object(phone,'_ts_run',return_value=(False,'offline')) as status:
            self.assertEqual(phone.https_url(strict=True),'')
            self.assertEqual(status.call_count,1)
