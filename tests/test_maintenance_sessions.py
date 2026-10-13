import concurrent.futures
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from modules.session_state import SessionStore
from modules import model_health, phone

class MaintenanceTests(unittest.TestCase):
    def test_parallel_user_approvals_are_independent(self):
        store=SessionStore();barrier=threading.Barrier(2)
        def request(owner,action):
            with store.use(owner):
                state=store.get('ignored');state.pending_confirm=action
                barrier.wait(timeout=3)
                return store.get('ignored').pending_confirm
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(request,'hamdi','shutdown');b=pool.submit(request,'ebru','message')
            self.assertEqual(a.result(),'shutdown');self.assertEqual(b.result(),'message')
        self.assertIsNone(store.get('third').pending_confirm)
    def test_nested_context_restores_owner_after_exception(self):
        store=SessionStore()
        with store.use('hamdi'):
            state=store.get('none');state.pending_msg={'text':'a'}
            with self.assertRaises(ValueError):
                with store.use('ebru'):
                    store.get('none').pending_msg={'text':'b'}
                    raise ValueError()
            self.assertIs(store.get('none'),state)
        store.reset('hamdi');self.assertIsNone(store.for_owner('hamdi').pending_msg)
    def test_public_and_reserved_peers_are_rejected(self):
        for address in ('8.8.8.8','203.0.113.1','0.0.0.0','169.254.1.1','::','2001:4860:4860::8888','invalid'):
            self.assertFalse(phone.allowed_peer(address),address)
        for address in ('127.0.0.1','192.168.1.5','10.1.2.3','172.16.1.4','100.100.2.3'):
            self.assertTrue(phone.allowed_peer(address),address)
        self.assertFalse(phone.allowed_peer('192.168.1.5','tailscale'))
        self.assertTrue(phone.allowed_peer('100.100.2.3','tailscale'))
    def test_history_filter_failure_denies_all_rows(self):
        server=phone.PhoneServer.__new__(phone.PhoneServer)
        with patch('modules.personalization.get_active',side_effect=OSError('test')):
            self.assertFalse(server.user_filter('hamdi')('ebru'))
    def test_models_cached_and_missing_models_reported(self):
        factory=Mock();factory.return_value.models.list.return_value=[SimpleNamespace(name='models/known')]
        result=model_health.check('a','test-key',['known','missing'],factory,True)
        self.assertEqual(result['state'],'missing_models');self.assertEqual(result['missing'],['missing'])
        self.assertNotIn('test-key',str(result))
        model_health.check('a','test-key',['known','missing'],factory)
        self.assertEqual(factory.call_count,1)
        model_health.check('b','test-key',['known','missing'],factory)
        self.assertEqual(factory.call_count,2)
    def test_models_access_quota_and_network_errors_are_distinct(self):
        factory=Mock()
        for code,state in [(403,'access_error'),(429,'quota_error'),(None,'connection_error')]:
            exc=RuntimeError('do not expose provider text');exc.code=code
            factory.side_effect=exc
            result=model_health.check('x','key',['known'],factory,True)
            self.assertEqual(result['state'],state);self.assertNotIn(str(exc),str(result))
    def test_missing_key_does_not_make_network_call(self):
        factory=Mock()
        self.assertEqual(model_health.check('empty','',['known'],factory,True)['state'],'missing_key')
        factory.assert_not_called()
