"""Provider Routing Policy v1, P0-3b: chains, route class and no cross-provider fallback inside llm."""
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import cloudflare_chat, llm, privacy_sources as ps, smart_router as router
from provider_fixture import fresh_bundle

PUB, PRIV = 'PUBLIC_RESEARCH', 'PRIVATE_GENERAL'


class RoutingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1_794_700_000.0
        for name, value in [('_STORE', Path(self.tmp.name)), ('_HEALTH', {}), ('_LAST', {})]:
            p = patch.object(router, name, value); p.start(); self.addCleanup(p.stop)
        for target, name, value in [
            (router.privacy, 'mode', 'normal'), (llm, 'user_key', 'gem-key'), (llm, 'user_groq_key', 'groq-key'),
            (llm, 'active_model', 'gem-model'), (llm, 'groq_model', 'groq-model'),
            (cloudflare_chat, 'configured', True), (llm, 'current_user', 'alice'), (llm, 'provider', 'auto'),
        ]:
            p = patch.object(target, name, return_value=value); p.start(); self.addCleanup(p.stop)
        for name, fn in [('protect', lambda s: 'enc:' + s), ('unprotect', lambda s: s.removeprefix('enc:'))]:
            p = patch.object(router.privacy, name, side_effect=fn); p.start(); self.addCleanup(p.stop)
        p = patch.object(router.time, 'time', return_value=self.now); p.start(); self.addCleanup(p.stop)
        fresh_bundle(self)
        router.configure('alice', True)
        for provider, model in (('gemini', 'gem-model'), ('groq', 'groq-model'), ('cloudflare', cloudflare_chat.MODEL)):
            router.set_free_tier_evidence('alice', provider=provider, model=model, free_tier_verified=True,
                source='official_provider_docs', evidence_ref='https://example.invalid/f', verified_at=self.now - 60,
                ttl_seconds=3600, eligibility='eligible', quota_state='available', quota_remaining=10,
                hard_stop_guaranteed=True, verification_status='verified', reason='ok')

    def order(self, route=None):
        return router.candidates('alice', 'chat', route=route)

    def test_chains(self):
        self.assertEqual(self.order(), ['groq', 'cloudflare', 'ollama'])
        self.assertEqual(self.order(PRIV), ['groq', 'cloudflare', 'ollama'])
        self.assertEqual(self.order(PUB), ['gemini', 'groq', 'cloudflare', 'ollama'])
        self.assertEqual(self.order('forged'), ['groq', 'cloudflare', 'ollama'])   # unknown route -> PRIVATE

    def test_task_type_does_not_reorder_providers(self):
        for task in ('chat', 'code', 'analysis'):
            self.assertEqual(router.candidates('alice', task), ['groq', 'cloudflare', 'ollama'])

    def test_private_chain_never_reaches_gemini_on_any_error(self):
        for error in (RuntimeError('429'), TimeoutError('t'), ConnectionError('c'), ValueError('5xx')):
            router._HEALTH.clear()
            call = Mock(side_effect=[error, error, error])
            with self.assertRaises(RuntimeError):
                router.run('alice', 'özel not', call)
            self.assertEqual([c.args[0] for c in call.call_args_list], ['groq', 'cloudflare', 'ollama'])

    def test_groq_429_falls_to_cloudflare_then_ollama_then_honest_unavailable(self):
        call = Mock(side_effect=[RuntimeError('429'), RuntimeError('429'), RuntimeError('down')])
        with self.assertRaises(RuntimeError) as caught:
            router.run('alice', 'x', call)
        self.assertNotIn('gemini:', str(caught.exception).split('Atlanan')[0])
        self.assertIn('Ücretli modele geçilmedi', str(caught.exception))

    def test_public_chain_gemini_error_goes_groq_cloudflare_ollama(self):
        call = Mock(side_effect=[RuntimeError('429'), RuntimeError('429'), RuntimeError('429'), 'yerel'])
        self.assertEqual(router.run('alice', 'x', call, route=PUB), 'yerel')
        self.assertEqual([c.args[0] for c in call.call_args_list], ['gemini', 'groq', 'cloudflare', 'ollama'])

    def test_gemini_only_user_gets_clear_user_action_guidance(self):
        from modules import failure_policy
        with patch.object(llm, 'user_groq_key', return_value=''), patch.object(cloudflare_chat, 'configured', return_value=False):
            call = Mock(side_effect=RuntimeError('ollama down'))
            with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
                router.run('alice', 'özel not', call)
        error = caught.exception
        self.assertEqual(error.recovery_class, 'user_action_required')
        self.assertIn('Groq veya Cloudflare anahtarı ekle ya da ücretsiz hesabı onayla', str(error))
        self.assertIn('Gemini', str(error))
        self.assertEqual([c.args[0] for c in call.call_args_list], ['ollama'])   # Gemini hiç denenmedi
        self.assertEqual(failure_policy.structured_outcome(error)['recovery_class'], 'user_action_required')

    def test_exhausted_after_real_private_cloud_attempts_is_not_a_user_action(self):
        from modules import failure_policy
        call = Mock(side_effect=RuntimeError('429'))
        with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
            router.run('alice', 'x', call)
        self.assertNotEqual(caught.exception.recovery_class, 'user_action_required')
        self.assertNotIn('anahtarı ekle', str(caught.exception))

    def test_missing_or_stale_evidence_skips_provider(self):
        router.set_free_tier_evidence('alice', provider='groq', model='groq-model', free_tier_verified=True,
            source='official_provider_docs', evidence_ref='https://example.invalid/f', verified_at=self.now - 7200,
            ttl_seconds=300, eligibility='eligible', quota_state='available', quota_remaining=10,
            hard_stop_guaranteed=True, verification_status='verified', reason='old')
        self.assertEqual(self.order(), ['cloudflare', 'ollama'])
        with patch.object(cloudflare_chat, 'configured', return_value=False):
            self.assertEqual(self.order(), ['ollama'])

    def test_local_privacy_mode_closes_the_cloud(self):
        with patch.object(router.privacy, 'mode', return_value='yerel'):
            self.assertEqual(self.order(PUB), ['ollama'])

    def test_paid_providers_not_in_pool(self):
        for route in (PUB, PRIV):
            self.assertFalse({'openai', 'anthropic', 'nvidia', 'openrouter'} & set(self.order(route)))

    # ---- llm.research / provenance -------------------------------------------------------------
    def capture(self):
        sent = []
        def fake(name, prompt, system, tokens, history):
            sent.append((name, prompt, system, history))
            return 'cevap'
        return sent, patch.object(llm, '_send_provider', side_effect=fake)

    def test_public_research_goes_to_gemini_without_history_or_memory(self):
        sent, fake = self.capture()
        evidence = [ps.mark_public('web_search', 'Haber metni')]
        with fake:
            self.assertEqual(llm.research('Haber nedir?', evidence, 'sistem'), 'cevap')
        name, prompt, _system, history = sent[0]
        self.assertEqual(name, 'gemini')
        self.assertIn('Haber metni', prompt)
        self.assertIsNone(history)

    def test_unlabeled_or_mixed_evidence_is_private_and_never_gemini(self):
        for evidence in ([], ['etiketsiz araç çıktısı'], [{'privacy': 'PUBLIC', 'source': 'web_search'}],
                         [ps.mark_public('web_search', 'a'), ps.mark_private('memory', 'özel')],
                         [ps.mark_public('foo_tool', 'a')]):
            sent, fake = self.capture()
            with fake:
                llm.research('soru', evidence)
            self.assertNotEqual(sent[0][0], 'gemini', repr(evidence))
            self.assertEqual(sent[0][0], 'groq')

    def test_plain_ask_is_private(self):
        sent, fake = self.capture()
        with fake:
            llm.ask('özel soru')
        self.assertEqual(sent[0][0], 'groq')

    def test_chat_with_history_never_reaches_gemini_even_when_everything_fails(self):
        seen = []
        def fail(name, *a):
            seen.append(name)
            raise llm.LocalModelError('x')
        with patch.object(llm, '_send_provider', side_effect=fail):
            with self.assertRaises(RuntimeError):
                llm.chat_draft('merhaba', user='alice')
        self.assertNotIn('gemini', seen)

    # ---- static -------------------------------------------------------------------------------
    def test_send_has_no_hard_coded_provider_and_no_cross_fallback(self):
        source = inspect.getsource(llm._send)
        for name in ('gemini', 'groq', 'ollama_task', 'cloudflare', 'Gemini', 'Groq'):
            self.assertNotIn(name, source)
        self.assertFalse(hasattr(llm, '_after_gemini'))
        transport = inspect.getsource(llm._send_provider)
        self.assertNotIn('_send(', transport)
        self.assertNotIn('smart_router', transport)

    def test_purge_runs_under_lock_on_a_fresh_read(self):
        path = router.owner_path('alice')
        path.write_text('{"cloud_free_confirmed": true, "legacy_key": "SECRET"}', encoding='utf-8')
        real = router._read_state
        calls = []
        def racing(owner):
            state = real(owner)
            calls.append(router._LOCK._is_owned())
            return state
        with patch.object(router, '_read_state', side_effect=racing):
            router._purge_legacy('alice', {'stale': 'copy'})   # the passed copy is ignored
        self.assertTrue(calls and all(calls))
        self.assertNotIn('SECRET', path.read_text(encoding='utf-8'))
        self.assertTrue(router.settings('alice')['cloud_free_confirmed'])

    def test_reset_leaves_a_file_that_became_valid_alone(self):
        router.configure('alice', True)
        router._reset_unreadable('alice')
        self.assertTrue(router.settings('alice')['cloud_free_confirmed'])

    def test_legacy_route_constant_is_gone(self):
        self.assertFalse(hasattr(router, '_LEGACY_ROUTE'))
        self.assertEqual(router._DEFAULT_ROUTE, PRIV)


class PrivateContentNeverReachesGeminiTests(unittest.TestCase):
    """P0-3c: documents (embed), voice (STT/Live) and screens (vision) are PRIVATE content."""

    def setUp(self):
        p = patch.object(llm, '_cli', side_effect=AssertionError('Gemini istemcisi özel içerik için açılamaz'))
        p.start(); self.addCleanup(p.stop)

    def test_aux_gemini_is_closed_in_every_state(self):
        for mode in ('normal', 'gizli', 'yerel'):
            with patch.object(llm.privacy, 'mode', return_value=mode):
                self.assertFalse(llm.gemini_aux_allowed())

    def test_embed_is_local_only(self):
        with patch.object(llm, '_backend', return_value='ollama'), patch.object(llm, 'load_settings', return_value={}), \
             patch('modules.ollama_embed.run', return_value=[[1.0]]) as local:
            self.assertEqual(llm.embed(['gizli belge']), [[1.0]])
        local.assert_called_once()
        with patch.object(llm, '_backend', return_value='lmstudio'):
            with self.assertRaises(ValueError):
                llm.embed(['x'])

    def test_transcribe_never_sends_audio_to_gemini(self):
        with self.assertRaises(RuntimeError):
            llm.transcribe(data=b'wav')

    def test_live_is_closed(self):
        from modules import live
        self.assertFalse(live.enabled())

    def test_vision_chain_is_local_only(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with patch.object(router, '_STORE', Path(tmp.name)), patch.object(router, '_HEALTH', {}), patch.object(router, '_LAST', {}), \
             patch.object(llm, 'user_key', return_value='k'), patch.object(llm, 'user_groq_key', return_value='k'), \
             patch.object(router.privacy, 'mode', return_value='normal'):
            router.configure('alice', True)
            sel = router.selection('alice', 'vision')
            self.assertEqual(sel['candidates'], ['ollama'])
            self.assertEqual({r['provider'] for r in sel['skipped']}, {'gemini', 'groq', 'cloudflare'})

    def test_no_gemini_content_call_remains_in_llm(self):
        source = inspect.getsource(llm)
        for needle in ('generate_content', 'embed_content', 'Part.from_bytes', 'gemini-embedding'):
            self.assertNotIn(needle, source)


if __name__ == '__main__':
    unittest.main()
