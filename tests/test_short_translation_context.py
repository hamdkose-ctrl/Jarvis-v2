import unittest
from datetime import datetime
from unittest.mock import patch
from modules import chat_translation as ct


class ShortTranslationContextTests(unittest.TestCase):
    def setUp(self):
        self.a=patch.object(ct,'_sources',{});self.a.start();self.addCleanup(self.a.stop)
        self.b=patch.object(ct,'_resets',{});self.b.start();self.addCleanup(self.b.stop)

    def rows(self,text):
        ts=datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
        return [{'role':'user','text':'Older long original paragraph.','ts':ts},
                {'role':'assistant','text':'Eski çeviri','ts':ts},
                {'role':'user','text':text,'ts':ts},
                {'role':'assistant','text':'Merhaba, nasıl yardımcı olayım?','ts':ts}]

    def test_hello_replaces_cached_paragraph(self):
        ct.remember('a','Older long original paragraph.')
        ct.remember('a','hello')
        self.assertEqual(ct.resolve('a','önceki metni Türkçeye çevir',self.rows('hello')),('hello','Türkçe'))

    def test_history_beats_stale_cache_after_restart(self):
        ct.remember('a','Older long original paragraph.')
        self.assertEqual(ct.resolve('a','cevir',self.rows('hello'))[0],'hello')

    def test_single_character_is_valid_source(self):
        ct.remember('a','a')
        self.assertEqual(ct.resolve('a','çevir',[])[0],'a')

    def test_acknowledgement_does_not_replace_source(self):
        ct.remember('a','hello');ct.remember('a','tamam')
        rows=self.rows('hello');rows.append({'role':'user','text':'tamam','ts':rows[-1]['ts']})
        self.assertEqual(ct.resolve('a','çevir',rows)[0],'hello')

    def test_explicit_last_answer_still_selects_assistant(self):
        self.assertEqual(ct.resolve('a','son cevabını Türkçeye çevir',self.rows('hello'))[0],'Merhaba, nasıl yardımcı olayım?')
