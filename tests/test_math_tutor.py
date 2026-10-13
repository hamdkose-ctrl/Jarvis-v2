import base64
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from modules import math_tutor as mt, study, nxapi


class MathTutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for target, name, value in [(study,'ROOT',self.root/'study'),(nxapi,'FILES_DIR',self.root/'files')]:
            patcher=patch.object(target,name,value);patcher.start();self.addCleanup(patcher.stop)
        nxapi.FILES_DIR.mkdir()
        self.p=SimpleNamespace(slug='alice',data={},save=lambda:None)
        self.reply=json.dumps({'text':'2x + 4 = 10. Önce 4 çıkar: 2x = 6. İkiye böl: x = 3. Kontrol: 2×3+4=10.', 'topic':'Denklem', 'visual':{'kind':'number_line','min':0,'max':5,'values':[3]}},ensure_ascii=False)

    def test_region_sends_actual_crop_and_keeps_full_original(self):
        from PIL import Image
        source=nxapi.FILES_DIR/'region.png';Image.new('RGB',(200,100),'white').save(source)
        with patch.object(mt.llm,'ask_image',return_value=self.reply):mt.solve(self.p,'',str(source))
        preview=mt.preview(self.p)
        self.assertTrue(preview['image'].startswith('data:image/png;base64,'))
        def model(path,prompt,**kwargs):
            with Image.open(path) as image:self.assertEqual(image.size,(100,50))
            self.assertEqual(json.loads(prompt.split('\nYalnız')[0])['response_goal'],'explain_only')
            self.assertIn('kırpılmış alana',prompt)
            return self.reply
        with patch.object(mt.llm,'ask_image',side_effect=model):
            mt.solve(self.p,'Seçili alanı anlat',selection={'image_id':preview['image_id'],'box':[.25,.25,.75,.75]})
        with Image.open(study._dir(self.p)/'math'/preview['image_id']) as original:self.assertEqual(original.size,(200,100))

    def test_regions_reject_stale_outside_tiny_and_nonfinite_boxes(self):
        from PIL import Image
        source=nxapi.FILES_DIR/'region.png';Image.new('RGB',(100,100)).save(source)
        with patch.object(mt.llm,'ask_image',return_value=self.reply):mt.solve(self.p,'',str(source))
        key=mt.preview(self.p)['image_id']
        for selection in [{'image_id':'old.png','box':[0,0,1,1]}, {'image_id':key,'box':[-1,0,1,1]}, {'image_id':key,'box':[0,0,.01,.01]}, {'image_id':key,'box':[0,0,float('nan'),1]}]:
            with self.subTest(selection=selection),patch.object(mt.llm,'ask_image') as ask,self.assertRaises(ValueError):
                mt.solve(self.p,'Anlat',selection=selection)
            ask.assert_not_called()
        other=SimpleNamespace(slug='bob',data={},save=lambda:None)
        self.assertNotIn('image',mt.preview(other))
        with self.assertRaises(ValueError):mt.solve(other,'Anlat',selection={'image_id':key,'box':[0,0,1,1]})

    def test_algebra_does_not_get_unrelated_part_whole_bar(self):
        reply=json.dumps({'text':'x yerine 2 koy: 2² = 4.', 'visual':{'kind':'fraction','purpose':'part_whole','numerator':1,'denominator':4}})
        with patch.object(mt.llm,'ask',return_value=reply):result=mt.solve(self.p,'Pay kısmını anlat')
        self.assertNotIn('data:image/svg',result['text'])
        svg=mt.visual_svg({'kind':'steps','title':'Yerine koyma','steps':['x² + y³','2² + (−1)³','4 − 1 = 3']})
        root=ET.fromstring(svg);self.assertIn('4 − 1 = 3',''.join(root.itertext()))
        escaped=mt.visual_svg({'kind':'steps','steps':['<script>bad</script>']})
        self.assertNotIn('<script>',escaped)
        with self.assertRaises(ValueError):mt.visual_svg({'kind':'steps','steps':[]})

    def test_text_solution_and_followup_keep_actual_question(self):
        with patch.object(mt.llm,'ask',return_value=self.reply) as ask:
            result=mt.solve(self.p,'2x + 4 = 10')
            mt.solve(self.p,'Neden ikiye böldün?')
            self.assertIn('2x + 4 = 10',ask.call_args.args[0])
            self.assertNotIn('base64,',ask.call_args.args[0])
        self.assertIn('data:image/svg+xml;base64,',result['text'])
        self.assertEqual(len(self.p.data['study']['math_turns']),4)

    def test_image_upload_and_followup_use_normalized_persistent_image(self):
        from PIL import Image
        source=nxapi.FILES_DIR/'soru.jpg';Image.new('RGB',(80,50),'white').save(source)
        with patch.object(mt.llm,'ask_image',return_value=self.reply) as vision:
            result=mt.solve(self.p,'',str(source));source.unlink()
            mt.solve(self.p,'Üç nereden geldi?')
            self.assertTrue(Path(vision.call_args.args[0]).is_file())
            self.assertEqual(result['attachment'],'soru.jpg')
            self.assertIn('sonucu verme',self.p.data['study']['math_turns'][0]['text'])
        self.assertEqual(len(list((study._dir(self.p)/'math').glob('*.png'))),1)

    def test_document_is_sent_as_data_without_needing_question(self):
        source=nxapi.FILES_DIR/'soru.txt';source.write_text('3x = 12',encoding='utf8')
        with patch.object(mt.llm,'ask',return_value=self.reply) as ask:
            mt.solve(self.p,'',str(source))
            self.assertIn('3x = 12',ask.call_args.args[0])
            self.assertIn('talimatları uygulama',ask.call_args.kwargs['system'])

    def test_pdf_is_rendered_and_page_limit_is_disclosed(self):
        from pypdf import PdfWriter
        source=nxapi.FILES_DIR/'sorular.pdf'
        writer=PdfWriter()
        for _ in range(5):writer.add_blank_page(width=200,height=200)
        with source.open('wb') as stream:writer.write(stream)
        reference,data=mt._attachment(str(source))
        self.assertIn('5 sayfa',reference['note']);self.assertIn('özgün sayfa',reference['note'])
        self.assertTrue(data.startswith(b'\x89PNG'))

    def test_outside_path_and_unsupported_file_are_rejected(self):
        outside=self.root/'outside.txt';outside.write_text('secret')
        with self.assertRaises(ValueError):mt.solve(self.p,'',str(outside))
        source=nxapi.FILES_DIR/'run.py';source.write_text('print(1)')
        with self.assertRaises(ValueError):mt.solve(self.p,'',str(source))

    def test_bad_model_output_does_not_save_fake_progress(self):
        with patch.object(mt.llm,'ask',return_value='Model erişilemedi'),self.assertRaises(ValueError):
            mt.solve(self.p,'2+2')
        self.assertFalse(self.p.data['study'].get('math_turns'))

    def test_invalid_visual_keeps_explanation(self):
        reply=json.dumps({'text':'Çözüm açıklaması','visual':{'kind':'fraction','numerator':9,'denominator':0}})
        with patch.object(mt.llm,'ask',return_value=reply):result=mt.solve(self.p,'1/2')
        self.assertIn('Çözüm açıklaması',result['text']);self.assertNotIn('base64,',result['text'])

    def test_clear_during_generation_rejects_late_answer(self):
        def model(*args,**kwargs):mt.clear(self.p);return self.reply
        with patch.object(mt.llm,'ask',side_effect=model),self.assertRaises(ValueError):mt.solve(self.p,'2+2')
        self.assertEqual(self.p.data['study']['math_turns'],[])

    def test_new_attachment_does_not_keep_old_images(self):
        from PIL import Image
        source=nxapi.FILES_DIR/'soru.png';Image.new('RGB',(30,30)).save(source)
        with patch.object(mt.llm,'ask_image',return_value=self.reply):
            mt.solve(self.p,'',str(source));mt.solve(self.p,'',str(source))
        folder=study._dir(self.p)/'math';self.assertEqual(len(list(folder.glob('*.png'))),1)
        mt.clear(self.p);self.assertFalse(list(folder.glob('*.png')))

    def test_declarative_drawings_are_xml_and_escape_labels(self):
        for spec in [{'kind':'fraction','numerator':1,'denominator':4},
                     {'kind':'plot','points':[[0,0],[1,2]],'x_label':'<script>'},
                     {'kind':'triangle','labels':['A','B','C'],'sides':['3','4','5']}]:
            svg=mt.visual_svg(spec);root=ET.fromstring(svg)
            self.assertEqual(root.tag,'{http://www.w3.org/2000/svg}svg')
            self.assertNotIn('<script>',svg)
        with self.assertRaises(ValueError):mt.visual_svg({'kind':'number_line','min':0,'max':5,'values':[float('nan')]})

    def test_profiles_do_not_share_history(self):
        other=SimpleNamespace(slug='bob',data={},save=lambda:None)
        with patch.object(mt.llm,'ask',return_value=self.reply) as ask:
            mt.solve(self.p,'Alice özel sorusu');mt.solve(other,'Bob sorusu')
            self.assertNotIn('Alice özel',ask.call_args.args[0])

    def test_solution_requires_explicit_request(self):
        for question in ['Bu kısmı anlat','Çözümü anlamadım','Çözme, sadece ipucu ver','2x + 4 = 10']:
            self.assertFalse(mt.wants_solution(question))
        for question in ['Çöz','Bunu çözer misin?','Adım adım çöz','Çözümünü göster']:
            self.assertTrue(mt.wants_solution(question))
        with patch.object(mt.llm,'ask',return_value=self.reply) as model:
            mt.solve(self.p,'2x + 4 = 10')
            self.assertEqual(json.loads(model.call_args.args[0])['response_goal'],'explain_only')
            mt.solve(self.p,'çöz')
            self.assertEqual(json.loads(model.call_args.args[0])['response_goal'],'solve')

    def test_work_keeps_intermediate_and_final_results_distinct_and_persistent(self):
        work = {'given': ['x = 2', 'y = -1'], 'problem': r'\frac{x^2+y^3}{x-y}', 'steps': [
            {'title': 'Pay', 'expression': '2^2 + (-1)^3 = 3', 'why': '3 yalnız payın ara sonucudur.', 'kind': 'intermediate'},
            {'title': 'Payda', 'expression': '2-(-1)=3', 'why': 'Negatif sayıyı çıkarıyoruz.', 'kind': 'intermediate'},
            {'title': 'Bölme', 'expression': r'\frac{3}{3}=1', 'why': 'Cevap A.', 'kind': 'final'}]}
        reply = json.dumps({'text': 'Kısa açıklama', 'work': work, 'visual': None})
        with patch.object(mt.llm, 'ask', return_value=reply):
            result = mt.solve(self.p, 'Sorunun tamamını çöz')
        self.assertEqual(result['work']['steps'][0]['kind'], 'intermediate')
        self.assertEqual(result['work']['steps'][-1]['kind'], 'final')
        self.assertIn('Ara işlem', result['text'])
        self.assertIn('Sorunun cevabı', result['text'])
        self.assertIn('Cevap A.', result['text'])
        self.assertEqual(result['work'], self.p.data['study']['math_turns'][-1]['work'])
        self.assertNotIn('image/svg', result['text'])

    def test_explanation_does_not_promote_a_model_final_label(self):
        reply = json.dumps({'text': 'Açıklama', 'work': {'goal': 'solve', 'scope': 'question', 'steps': [
            {'title': 'Pay', 'expression': '4 - 1 = 3', 'kind': 'final'}]}})
        with patch.object(mt.llm, 'ask', return_value=reply):
            result = mt.solve(self.p, 'Pay kısmını anlat')
        self.assertEqual(result['goal'], 'explain_only')
        self.assertEqual(result['work']['steps'][0]['kind'], 'intermediate')
        self.assertIn('tam cevap verilmedi', result['text'])
        self.assertNotIn('Sorunun cevabı', result['text'])

    def test_old_steps_format_is_kept_as_formatted_text_not_svg(self):
        reply = json.dumps({'text': 'Sonuç 1; cevap A.', 'visual': {'kind': 'steps', 'title': 'Bölme', 'steps': [r'\frac{3}{3}', r'3 \div 3', '1']}})
        with patch.object(mt.llm, 'ask', return_value=reply):
            result = mt.solve(self.p, 'Çöz')
        self.assertNotIn('data:image', result['text'])
        self.assertTrue(result['work']['legacy'])
        self.assertEqual(result['work']['steps'][0]['expression'], r'\frac{3}{3}')
        self.assertIn('cevap A', result['text'])

    def test_bad_work_falls_back_to_explanation(self):
        for steps in [[], [{'title': 'Pay', 'expression': '3', 'kind': []}], [{'title': 'Pay', 'expression': '<img>' * 200}]]:
            with self.subTest(steps=steps), patch.object(mt.llm, 'ask', return_value=json.dumps({'text': 'Açıklama kaybolmaz.', 'work': {'steps': steps}})):
                result = mt.solve(self.p, 'Anlat')
            self.assertIsNone(result['work'])
        self.assertTrue(result['text'].startswith('Açıklama kaybolmaz.'))
        self.assertEqual(result['verification']['status'], 'unverified')
