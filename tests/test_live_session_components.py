"""Connection, retry and cleanup contracts using fake async Live sessions."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import test_engine_modular as fixtures
from modules import live,llm

class LiveSessionComponentTests(unittest.TestCase):
    def instance(self):
        with patch.object(live,'_Player',return_value=Mock()),patch.object(live.threading,'Thread'):
            obj=live.Live(Mock(),Mock(),Mock())
        self.addCleanup(obj.loop.close)
        obj._config=Mock(return_value='config')
        obj._save_sent=Mock()
        return obj

    def execute(self,obj,client):
        with patch.object(llm,'gemini_client',return_value=client),patch.object(live,'enabled',return_value=True),patch.object(live,'model_name',return_value='fake-model'),patch.object(live,'voice_name',return_value='Kore'),patch.object(live,'_cfg',side_effect=lambda key,default:default):
            asyncio.run(obj._converse())

    def test_voice_confirmation_is_queued_in_new_session_then_cleaned(self):
        obj=self.instance();obj._voice_confirmation='Kore';obj._voice_transition=True
        observed=[];session=object()
        @asynccontextmanager
        async def connect(**kwargs):yield session
        async def run(active):
            self.assertIs(active,session)
            observed.extend(obj._pending_text)
            self.assertFalse(obj._voice_transition)
            obj._closing=True
        obj._run_session=run
        client=SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=Mock(side_effect=connect))))
        self.execute(obj,client)
        self.assertIn('Kore',observed[0]);self.assertEqual(obj._pending_text,[])
        self.assertIsNone(obj._session);self.assertEqual(obj._state,'asleep')
        obj.player.clear.assert_called_once();obj._save_sent.assert_called_once()

    def test_internal_error_retries_in_safe_mode_without_resume(self):
        obj=self.instance();obj._resume='old';obj._resumable_until=float('inf')
        calls=[]
        @asynccontextmanager
        async def connect(**kwargs):
            calls.append((obj._safe,obj._resume))
            if len(calls)==1:raise RuntimeError('1011 internal error')
            yield object()
        async def run(session):obj._closing=True
        async def sleep(delay):pass
        obj._run_session=run
        client=SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=connect)))
        with patch.object(asyncio,'sleep',side_effect=sleep):self.execute(obj,client)
        self.assertEqual(calls,[(False,'old'),(True,None)])
        self.assertTrue(obj._force_safe)
        self.assertEqual(obj._state,'asleep')

    def test_no_key_never_opens_connection_and_cleans_state(self):
        obj=self.instance();obj._tools_running=2;obj._outbox.append(b'audio')
        self.execute(obj,None)
        self.assertEqual(obj._tools_running,0);self.assertEqual(len(obj._outbox),0)
        self.assertIsNone(obj._session);self.assertEqual(obj._state,'asleep')
        self.assertTrue(any('anahtarı yok' in str(c) for c in obj.emit.call_args_list))

    def test_privacy_gate_never_opens_connection(self):
        obj=self.instance();connect=Mock()
        client=SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=connect)))
        with patch.object(llm,'gemini_client',return_value=client),patch.object(live,'enabled',return_value=False),patch.object(live,'_cfg',side_effect=lambda key,default:default):asyncio.run(obj._converse())
        connect.assert_not_called();self.assertEqual(obj._state,'asleep')

    def test_session_failure_cancels_and_joins_other_workers(self):
        obj=self.instance();cancelled=[]
        async def send(session):
            try:await asyncio.Future()
            finally:cancelled.append('send')
        async def receive(session):
            try:await asyncio.Future()
            finally:cancelled.append('receive')
        async def watch(session):raise RuntimeError('session failed')
        obj._send=send;obj._receive=receive;obj._watch=watch
        with self.assertRaisesRegex(RuntimeError,'session failed'):asyncio.run(obj._run_session(object()))
        self.assertCountEqual(cancelled,['send','receive'])
