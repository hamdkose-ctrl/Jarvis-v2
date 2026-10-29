"""Faz 1-B: planlayıcı model yokken genel hedeflerin modelsiz teslimi ve LM Studio/llama.cpp yerel uç noktası.

Gerçek model, ağ veya hesap çağrısı yok; HTTP ve model taklit edilir.
"""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import requests

from modules import goal_executor as goals, llm, model_free_delivery
import test_goal_executor as fixture


class ModelFreeDeliveryTests(unittest.TestCase):
    def case(self):
        case = fixture.GoalTests(); case.setUp(); self.addCleanup(case.doCleanups); return case

    def test_verified_step_is_delivered_when_local_model_missing(self):
        case = self.case()
        case.responses(case.plan('Hesap durumunu oku', 'Rapor dosyası'), case.tool('diagnose', {'kind': 'accounts'}),
                       llm.LocalModelError('Ollama kurulu değil; secret-path=C:/PRIVATE'))
        with patch('modules.service_health.report', return_value='Hesap durumu: iki bağlantı hazır'), \
                patch.object(llm, 'local_hint', return_value='Yerel model için Ollama yüklemelisin.'):
            result = goals.run(case.runtime, 'Hesabı kontrol et ve rapor oluştur')
        job = goals.latest('alice')
        self.assertEqual(job['state'], 'paused')
        self.assertTrue(all(g['state'] == 'pending' for g in job['goals']))
        self.assertEqual(job['model_free']['evidence'], ['s1'])
        self.assertIn('Modelsiz yol: doğrulanmış 1 sonuç', result)
        self.assertIn('Hesap durumu: iki bağlantı hazır', result)
        self.assertIn('Ollama yüklemelisin', result)
        self.assertNotIn('PRIVATE', result)

    def test_no_result_yet_says_why_and_keeps_goal(self):
        case = self.case()
        case.responses(llm.LocalModelError('bağlanamadı'))
        with patch.object(llm, 'provider', return_value='ollama'), \
                patch.object(llm, 'local_hint', return_value='Yerel model için LM Studio sunucusu çalışmıyor.'):
            result = goals.run(case.runtime, 'Masaüstündeki dosyaları düzenle')
        job = goals.latest('alice')
        self.assertEqual(job['state'], 'paused')
        self.assertEqual(job['model_free']['evidence'], [])
        self.assertIn('henüz doğrulanmış bir sonuç yok', result)
        self.assertIn('LM Studio', result)

    def test_rate_limit_uses_classified_text(self):
        case = self.case()
        case.responses(RuntimeError('HTTP 429 quota exceeded'))
        result = goals.run(case.runtime, 'Belgeyi özetle')
        self.assertEqual(goals.latest('alice')['model_free']['category'], 'rate_limit')
        self.assertIn('kullanım sınırına takıldı', result)

    def test_unclassified_planner_error_keeps_old_behaviour(self):
        case = self.case()
        case.responses(case.plan('İş bir'), RuntimeError('offline'))
        result = goals.run(case.runtime, 'İşi yap')
        job = goals.latest('alice')
        self.assertNotIn('model_free', job)
        self.assertIn('tamamlanmadı', result)

    def test_changed_file_is_not_delivered(self):
        case = self.case()
        path = case.root / 'document.txt'; path.write_text('Merhaba dünya', encoding='utf-8')
        case.responses(case.plan('Belgeyi oku', 'Özet'), case.tool('document', {'operation': 'read', 'path': str(path)}),
                       llm.LocalModelError('Ollama kurulu değil'))
        from modules import nxapi
        with patch.object(nxapi, 'allowed', return_value=path):
            goals.run(case.runtime, 'Dosyayı oku ve özetle')
        job = goals.latest('alice')
        self.assertEqual(job['model_free']['evidence'], ['s1'])
        path.write_text('değişti', encoding='utf-8')
        self.assertEqual(model_free_delivery.verified_outputs(job), [])
        self.assertEqual(model_free_delivery.render_lines(job), [])

    def test_resume_after_model_returns_clears_delivery_and_completes(self):
        case = self.case()
        case.responses(case.plan('Durumu oku'), case.tool('diagnose', {'kind': 'accounts'}), llm.LocalModelError('Ollama kurulu değil'))
        with patch('modules.service_health.report', return_value='Hesap durumu'):
            goals.run(case.runtime, 'Hesap durumunu oku')
            self.assertIn('model_free', goals.latest('alice'))
            case.responses(case.done('s1'), case.finish())
            goals.handle(case.runtime, 'devam et')
        job = goals.latest('alice')
        self.assertEqual(job['state'], 'done')
        self.assertNotIn('model_free', job)

    def test_news_goal_keeps_its_own_recovery(self):
        case = self.case()
        case.responses(case.plan('Haberleri araştır'), llm.LocalModelError('Ollama kurulu değil'))
        goals.run(case.runtime, 'Bugünkü ekonomi haberlerini araştır ve rapor dosyasına kaydet')
        self.assertNotIn('model_free', goals.latest('alice'))


class LocalBackendTests(unittest.TestCase):
    def settings(self, **values):
        p = patch.object(llm, 'load_settings', return_value=dict(values)); p.start(); self.addCleanup(p.stop)
        llm._ollama_tags_cache.clear(); self.addCleanup(llm._ollama_tags_cache.clear)

    def test_default_is_ollama(self):
        self.settings()
        c = llm._cfg()
        self.assertEqual((c['backend'], c['url'], c['model']), ('ollama', 'http://127.0.0.1:11434', 'llama3.2'))

    def test_lmstudio_and_llamacpp_defaults(self):
        self.settings(local_backend='lmstudio')
        self.assertEqual(llm._cfg()['url'], 'http://127.0.0.1:1234/v1')
        self.settings(local_backend='llamacpp', local_url='http://10.0.0.5:9000/v1/', local_model='qwen')
        c = llm._cfg()
        self.assertEqual((c['backend'], c['url'], c['model']), ('llamacpp', 'http://10.0.0.5:9000/v1', 'qwen'))
        self.settings(local_backend='bilinmeyen')
        self.assertEqual(llm._cfg()['backend'], 'ollama')

    def test_set_local_backend_validates_and_saves(self):
        save = Mock()
        with patch.object(llm, 'save_settings', save):
            with self.assertRaises(ValueError): llm.set_local_backend('vllm')
            with self.assertRaises(ValueError): llm.set_local_backend('lmstudio', 'ftp://x')
            llm.set_local_backend('lmstudio', '', '')
            save.assert_called_with(local_backend='lmstudio', local_url='http://127.0.0.1:1234/v1', local_model=None)
            llm.set_local_backend('ollama', 'http://127.0.0.1:11434/', 'qwen2.5:7b')
            save.assert_called_with(local_backend='ollama', ollama_url='http://127.0.0.1:11434', ollama_model='qwen2.5:7b')

    def test_models_listed_from_openai_endpoint(self):
        self.settings(local_backend='lmstudio')
        response = Mock(status_code=200); response.json.return_value = {'data': [{'id': 'b-model'}, {'id': 'a-model'}]}
        with patch.object(llm.requests, 'get', return_value=response) as get:
            self.assertEqual(llm.ollama_models(force=True), ['a-model', 'b-model'])
        self.assertEqual(get.call_args[0][0], 'http://127.0.0.1:1234/v1/models')

    def test_chat_uses_chat_completions_and_first_model(self):
        self.settings(local_backend='llamacpp')
        listing = Mock(status_code=200); listing.json.return_value = {'data': [{'id': 'gguf-model'}]}
        reply = Mock(status_code=200, content=b'x'); reply.json.return_value = {'choices': [{'message': {'content': 'Merhaba'}}]}
        with patch.object(llm.requests, 'get', return_value=listing), \
                patch.object(llm.requests, 'post', return_value=reply) as post, \
                patch.object(llm.usage_meter, 'record') as record:
            text = llm._ollama([{'role': 'user', 'content': 'selam'}], 'sistem', 50)
        self.assertEqual(text, 'Merhaba')
        url, body = post.call_args[0][0], post.call_args[1]['json']
        self.assertEqual(url, 'http://127.0.0.1:8080/v1/chat/completions')
        self.assertEqual(body['model'], 'gguf-model'); self.assertEqual(body['max_tokens'], 50)
        self.assertEqual(body['messages'][0], {'role': 'system', 'content': 'sistem'})
        self.assertEqual(record.call_args[0][0], 'llamacpp')

    def test_image_uses_openai_content_parts(self):
        self.settings(local_backend='lmstudio', local_model='vision')
        reply = Mock(status_code=200, content=b'x'); reply.json.return_value = {'choices': [{'message': {'content': 'kedi'}}]}
        with patch.object(llm.requests, 'post', return_value=reply) as post, patch.object(llm.usage_meter, 'record'):
            llm._ollama([{'role': 'user', 'content': 'ne var'}], '', 20, images=['QUJD'])
        content = post.call_args[1]['json']['messages'][-1]['content']
        self.assertEqual(content[0], {'type': 'text', 'text': 'ne var'})
        self.assertEqual(content[1]['image_url']['url'], 'data:image/png;base64,QUJD')

    def test_unreachable_server_gives_backend_hint(self):
        self.settings(local_backend='lmstudio', local_model='m')
        with patch.object(llm.requests, 'post', side_effect=requests.ConnectionError('refused')), \
                patch.object(llm.usage_meter, 'record'):
            with self.assertRaises(llm.LocalModelError) as caught:
                llm._ollama([{'role': 'user', 'content': 'x'}], '', 10)
        self.assertIn('LM Studio sunucusu çalışmıyor', str(caught.exception))
        self.assertIn('http://127.0.0.1:1234/v1', str(caught.exception))

    def test_missing_model_and_no_models(self):
        self.settings(local_backend='lmstudio', local_model='yok')
        missing = Mock(status_code=404, content=b'')
        with patch.object(llm.requests, 'post', return_value=missing), patch.object(llm.usage_meter, 'record'):
            with self.assertRaises(llm.LocalModelError) as caught:
                llm._ollama([{'role': 'user', 'content': 'x'}], '', 10)
        self.assertIn('“yok” modeli yok', str(caught.exception))
        self.settings(local_backend='lmstudio')
        with patch.object(llm.requests, 'get', side_effect=requests.ConnectionError('refused')):
            with self.assertRaises(llm.LocalModelError):
                llm._ollama([{'role': 'user', 'content': 'x'}], '', 10)

    def test_ollama_path_unchanged(self):
        self.settings()
        reply = Mock(status_code=200); reply.json.return_value = {'message': {'content': 'tamam'}}
        with patch.object(llm, 'ollama_models', return_value=['local-fixture']), \
             patch.object(llm.requests, 'post', return_value=reply) as post, patch.object(llm.usage_meter, 'record'):
            self.assertEqual(llm._ollama([{'role': 'user', 'content': 'x'}], '', 10), 'tamam')
        self.assertEqual(post.call_args[0][0], 'http://127.0.0.1:11434/api/chat')

    def test_embed_is_ollama_only(self):
        self.settings(local_backend='lmstudio')
        with patch.object(llm, 'provider', return_value='ollama'):
            with self.assertRaises(ValueError) as caught:
                llm.embed(['x'])
        self.assertIn('yalnız Ollama', str(caught.exception))

    def test_status_and_labels(self):
        self.settings(local_backend='llamacpp')
        info = llm.local_info()
        self.assertEqual(info['local_label'], 'llama.cpp')
        self.assertEqual(llm.provider_label('ollama'), 'llama.cpp (yerel)')
        self.settings()
        self.assertEqual(llm.provider_label('ollama'), 'Ollama (yerel)')


if __name__ == '__main__':
    unittest.main()
