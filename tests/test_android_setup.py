"""One-use provisioning, credential-free QR and actual local HTTP redemption."""
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
import unittest
import urllib.request
import urllib.error
from unittest.mock import Mock, patch
import test_engine_modular as fixtures
from modules.android_setup import SetupGrants
from web_phone import WebPhone

class AndroidSetupTests(unittest.TestCase):
    def test_unreadable_router_key_does_not_hide_local_provider(self):
        from modules import smart_router
        with patch.object(smart_router,'settings',return_value={'cloud_free_confirmed':False,'free_tier_evidence':{},'gemini_scopes':[],'account_scopes':{},'application_limits':smart_router._APPLICATION_DEFAULTS}), \
             patch.object(smart_router.privacy,'unprotect',side_effect=OSError('protected record unavailable')), \
             patch.object(smart_router.privacy,'mode',return_value='normal'), \
             patch.object(smart_router,'_record_failure'),patch.object(smart_router,'_HEALTH',{}):
            self.assertIn('ollama',smart_router.candidates('alice','chat'))

    def test_grant_single_use_concurrent_and_current_owner_key(self):
        grants=SetupGrants();code=grants.issue('alice',{'n':'Alice','k':'must-not-retain'})
        self.assertNotIn('k',grants._grants[code][1])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:grants.redeem(code,lambda owner:'current-'+owner),range(4)))
        self.assertEqual([r for r in results if r],[{'n':'Alice','k':'current-alice'}])

    def test_expiry_replacement_revocation_and_deleted_key(self):
        grants=SetupGrants()
        with patch('modules.android_setup.time.monotonic',return_value=10):old=grants.issue('alice',{})
        with patch('modules.android_setup.time.monotonic',return_value=101):self.assertIsNone(grants.redeem(old,Mock()))
        old=grants.issue('alice',{});new=grants.issue('alice',{})
        self.assertIsNone(grants.redeem(old,Mock()))
        self.assertIsNone(grants.redeem(new,lambda owner:''))
        code=grants.issue('alice',{});grants.clear('alice');self.assertIsNone(grants.redeem(code,Mock()))

    def bridge(self,url):
        grants=SetupGrants();captured=[]
        runtime=SimpleNamespace(_p=lambda:SimpleNamespace(name='Alice'),
            llm=SimpleNamespace(user_key=lambda owner:'private-api-key',model_names=lambda owner:['model']),
            _aname=lambda:'Jarvis',phonemod=SimpleNamespace(https_url=lambda **kw:url),
            phone=SimpleNamespace(running=True,port=9999,android_setup=grants),json=json,
            qr_matrix=lambda payload:captured.append(json.loads(payload)) or [[1]],privacy=SimpleNamespace(audit=Mock()))
        bridge=WebPhone();bridge._runtime=runtime
        return bridge,captured,grants

    def test_qr_contains_only_endpoint_and_grant(self):
        bridge,captured,grants=self.bridge('https://pc.tailnet.ts.net')
        with patch('modules.personalization.Profile',return_value=SimpleNamespace(data={'goals':['math']})):
            result=bridge.phone_app_qr()
        self.assertTrue(result['ok']);self.assertEqual(captured[0]['v'],2)
        self.assertNotIn('private-api-key',json.dumps(captured))
        self.assertEqual(set(captured[0]),{'j','v','u','c'})
        self.assertNotIn('k',next(iter(grants._grants.values()))[1])

    def test_no_https_never_falls_back_to_key_qr(self):
        for url in ('','http://pc.ts.net','https://evil.example'):
            bridge,captured,grants=self.bridge(url)
            with patch('modules.personalization.Profile',return_value=SimpleNamespace(data={})):
                self.assertFalse(bridge.phone_app_qr()['ok'])
            self.assertFalse(captured);self.assertFalse(grants._grants)

    def test_local_http_redemption_consumes_code_and_stop_revokes(self):
        from modules import phone
        runtime=fixtures.ModularEngineTests.context(self)
        runtime.llm=SimpleNamespace(user_key=lambda owner:'secret-'+owner)
        server=phone.PhoneServer(runtime,port=0)
        self.addCleanup(server.stop)
        with patch.object(phone,'load_settings',return_value={'phone_scope':'secure'}),patch.object(phone,'tailscale_ip',return_value=None),patch.object(phone,'https_url',return_value='https://pc.tailnet.ts.net'),patch.object(phone,'_harden'),patch.object(server,'user_of',return_value='Alice'):
            server.start()
            try:
                url=f'http://127.0.0.1:{server._httpd.server_address[1]}/api/android-setup'
                code=server.android_setup.issue('alice',{'j':'jarvis-android','v':1,'n':'Alice'})
                request=lambda:urllib.request.Request(url,data=json.dumps({'code':code}).encode())
                for headers in ({'Host':'evil.example'},{'Origin':'https://evil.example'}):
                    denied=urllib.request.Request(url,data=json.dumps({'code':code}).encode(),headers=headers)
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(denied,timeout=3)
                    self.assertEqual(error.exception.code,403);error.exception.close()
                with urllib.request.urlopen(request(),timeout=3) as response:
                    self.assertEqual(json.load(response)['k'],'secret-alice')
                    self.assertEqual(response.headers['Cache-Control'],'no-store')
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request(),timeout=3)
                self.assertEqual(error.exception.code,401);error.exception.close()
                server.android_setup.issue('alice',{})
            finally:server.stop()
            self.assertFalse(server.android_setup._grants)
