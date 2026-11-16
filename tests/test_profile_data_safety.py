"""Profil karantinası ve öğrenme tamponu yaşam döngüsü (veri güvenliği PR-1).

Kapsam: bozuk profil dosyasının baytları sonraki kayıttan önce zaman damgalı
kopyaya alınır; sohbeti silme/yeni sohbet learning_buffer'ı sıfırlar; onaylı
bilgiler ve onay bekleyen adaylar korunur.
"""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from modules import conversation_reset, learning
from modules import personalization as profiles
from web_chat import WebChat

STABLE_OLD = "Eski sohbette kalıcı bir bilgi cümlesi kullanıyorum."
STABLE_NEW = "Yeni sohbette başka bir aracı kullanıyoruz."


def _shared_key(path):
    return str(Path(path).resolve())


class ProfilKarantinaTestleri(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        p = patch.object(profiles, 'USERS_DIR', self.folder)
        p.start()
        self.addCleanup(p.stop)

    def _forget(self, slug):
        profiles._SHARED.pop(_shared_key(self.folder / f"{slug}.json"), None)

    def test_gecerli_profil_yedek_uretmez(self):
        (self.folder / 'hamdi.json').write_text(
            json.dumps({"name": "Hamdi", "facts": ["a"]}, ensure_ascii=False), encoding="utf-8")
        profil = profiles.Profile('Hamdi')
        self.assertEqual(profil.data["facts"], ["a"])
        self.assertNotIn("profile_corrupt_backup", profil.data)
        self.assertEqual(list(self.folder.glob("*.bozuk*.json")), [])

    def test_bozuk_metin_karantinaya_alinir_ve_kayit_yedige_dokunmaz(self):
        raw = b"{not json at all"
        (self.folder / 'hamdi.json').write_bytes(raw)
        profil = profiles.Profile('Hamdi')
        backups = list(self.folder.glob("hamdi.bozuk-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), raw)
        self.assertEqual(profil.data["profile_corrupt_backup"], backups[0].name)
        self.assertEqual(profil.data["facts"], [])           # taze varsayılanlarla devam
        profil.log_command("chat")                          # sıradan kayıt üzerine yazar
        self.assertEqual(backups[0].read_bytes(), raw)      # karantina baytı değişmedi
        self.assertEqual(json.loads((self.folder / 'hamdi.json').read_text(encoding="utf-8"))
                         ["command_counts"]["chat"], 1)

    def test_bos_dosya_karantinaya_alinir(self):
        (self.folder / 'hamdi.json').write_bytes(b"")
        profil = profiles.Profile('Hamdi')
        self.assertEqual(profil.data["facts"], [])
        self.assertIn("profile_corrupt_backup", profil.data)
        self.assertEqual(list(self.folder.glob("hamdi.bozuk-*.json"))[0].read_bytes(), b"")

    def test_kirik_json_karantinaya_alinir(self):
        (self.folder / 'hamdi.json').write_text('{"facts": ["a", "b"', encoding="utf-8")  # kesik
        profil = profiles.Profile('Hamdi')
        self.assertIn("profile_corrupt_backup", profil.data)
        self.assertEqual(profil.data["facts"], [])

    def test_sozluk_olmayan_kok_karantinaya_alinir(self):
        for i, body in enumerate(['[1, 2, 3]', '"merhaba dünya"', 'null', '1234']):
            with self.subTest(i=i):
                (self.folder / f'user{i}.json').write_text(body, encoding="utf-8")
                profil = profiles.Profile(f'User {i}')
                self.assertIn("profile_corrupt_backup", profil.data)
                self.assertEqual(list(self.folder.glob(f'user{i}.bozuk-*.json'))[0]
                                 .read_text(encoding="utf-8"), body)

    def test_gecersiz_utf8_karantinaya_alinir(self):
        raw = b'\xff\xfe{"facts": []'
        (self.folder / 'hamdi.json').write_bytes(raw)
        profil = profiles.Profile('Hamdi')
        self.assertIn("profile_corrupt_backup", profil.data)
        self.assertEqual(list(self.folder.glob("hamdi.bozuk-*.json"))[0].read_bytes(), raw)

    def test_turkce_icerikli_baytlar_birebir_korunur(self):
        raw = '{"name": "Şeyma", "facts": ["İstiklal Marşığü Şırnak"]'.encode("utf-8")  # kesik JSON
        (self.folder / 'seyma.json').write_bytes(raw)
        profiles.Profile('Şeyma')
        backup = list(self.folder.glob("seyma.bozuk-*.json"))[0]
        self.assertEqual(backup.read_bytes(), raw)

    def test_cakisan_karantina_adi_artirilir_ve_eski_yedek_bozulmaz(self):
        from datetime import datetime
        class SabitDatetime:
            @staticmethod
            def now(*a, **k):
                return datetime(2026, 11, 16, 12, 0, 0)
        (self.folder / 'hamdi.json').write_bytes(b"bozuk-v1")
        with patch.object(profiles, 'datetime', SabitDatetime):
            profiles.Profile('Hamdi')
        self._forget('hamdi')
        first = list(self.folder.glob("hamdi.bozuk-*.json"))[0]
        old_bytes = first.read_bytes()
        (self.folder / 'hamdi.json').write_bytes(b"bozuk-v2")
        with patch.object(profiles, 'datetime', SabitDatetime):
            profiles.Profile('Hamdi')
        backups = sorted(self.folder.glob("hamdi.bozuk-*.json"))
        self.assertEqual(len(backups), 2)
        self.assertEqual(first.read_bytes(), old_bytes)
        self.assertIn(b"bozuk-v2", [b.read_bytes() for b in backups])

    def test_okunamayan_dosya_cokmeden_varsayilanlarla_acilir(self):
        (self.folder / 'hamdi.json').mkdir()      # dosya yerine klasör: read OSError
        profil = profiles.Profile('Hamdi')
        self.assertEqual(profil.data["facts"], [])
        self.assertNotIn("profile_corrupt_backup", profil.data)

    def test_rename_user_bozuk_kaynakta_baytlar_karantinaya_alinir(self):
        raw = b"{corrupt"
        (self.folder / 'ali.json').write_bytes(raw)
        self.assertIsNone(profiles.rename_user('Ali', 'Ayşe'))
        backup = list(self.folder.glob("ali.bozuk-*.json"))[0]
        self.assertEqual(backup.read_bytes(), raw)
        self.assertTrue((self.folder / 'ayse.json').exists())

    def test_list_users_bozuk_dosyayi_atlayip_patlamaz(self):
        (self.folder / 'hamdi.json').write_text(json.dumps({"name": "Hamdi"}), encoding="utf-8")
        (self.folder / 'merve.json').write_bytes(b"{bozuk")
        self.assertEqual(profiles.list_users(), ["Hamdi", "Merve"])
        self.assertEqual(list(self.folder.glob("merve.bozuk-*.json")), [])  # listeleme yedeklemez


class OgrenmeTamponuTestleri(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        p = patch.object(profiles, 'USERS_DIR', self.folder)
        p.start()
        self.addCleanup(p.stop)
        self.profil = profiles.Profile('Hamdi')
        self.profil.data['prefs']['learn_from_chat'] = True
        self.profil.save()

    def _disk(self):
        return json.loads((self.folder / 'hamdi.json').read_text(encoding="utf-8"))

    def test_clear_buffer_ham_metni_siler_onayli_ve_aday_korunur(self):
        self.profil.data['learning_buffer'] = [f'mesaj {i}' for i in range(12)]
        self.profil.data['facts'] = ['kalici bilgi']
        self.profil.data['pending_facts'] = ['aday bilgi']
        self.profil.save()
        learning.clear_buffer(self.profil)
        self.assertNotIn('learning_buffer', self._disk())
        self.assertEqual(self._disk()['facts'], ['kalici bilgi'])
        self.assertEqual(self._disk()['pending_facts'], ['aday bilgi'])
        self.assertEqual(self._disk()['learning_status'], {'state': 'pending', 'pending': 1})

    def test_clear_buffer_bos_ve_statuzsuz_profilde_kaydetmez(self):
        before = (self.folder / 'hamdi.json').read_bytes()
        with patch.object(self.profil, 'save', side_effect=AssertionError('save çağrılmamalı')):
            learning.clear_buffer(self.profil)
        self.assertEqual((self.folder / 'hamdi.json').read_bytes(), before)

    def test_clear_buffer_aday_yokken_collecting_der(self):
        self.profil.data['learning_buffer'] = ['bir şeyler']
        self.profil.data['learning_status'] = {'state': 'extracting', 'pending': 0}
        self.profil.save()
        learning.clear_buffer(self.profil)
        self.assertEqual(self._disk()['learning_status'], {'state': 'collecting', 'pending': 0})

    def test_observe_silinen_metni_yeni_cekim_turuna_tasimaz(self):
        submitted = []
        with patch.object(learning, 'propose', return_value=[]), \
             patch.object(learning, '_pool') as pool, \
             patch.object(learning, 'extract_from_session') as extract:
            pool.submit.side_effect = lambda fn: submitted.append(fn)
            learning.observe(self.profil, STABLE_OLD)
            learning.clear_buffer(self.profil)
            for t in (STABLE_NEW, "Projemde yeni bir sensörü kontrolü için ayarladım.",
                      "Yeni panosu makinesi bugün çalışıyor."):
                learning.observe(self.profil, t)
            self.assertEqual(len(submitted), 1)
            submitted[0]()
        batch = [text for _, text in extract.call_args[0][1]]
        self.assertNotIn(STABLE_OLD, batch)
        self.assertIn(STABLE_NEW, batch)

    def _bridge(self):
        engine = SimpleNamespaceBridge(self.profil)
        bridge = WebChat()
        bridge._runtime = engine
        return bridge

    def test_yeni_sohbet_tamponu_temizler(self):
        self.profil.data['learning_buffer'] = [STABLE_OLD]
        self.profil.save()
        with patch.object(conversation_reset, 'mark'):
            self.assertTrue(self._bridge().chat_reset())
        self.assertNotIn('learning_buffer', self._disk())

    def test_gecmisi_silmek_tamponu_temizler(self):
        self.profil.data['learning_buffer'] = [STABLE_OLD]
        self.profil.save()
        with patch.object(conversation_reset, 'mark'):
            self.assertTrue(self._bridge().history_clear())
        self.assertNotIn('learning_buffer', self._disk())

    def test_tek_konusma_silme_tamponu_temizler(self):
        self.profil.data['learning_buffer'] = [STABLE_OLD]
        self.profil.save()
        sonuc = self._bridge().history_delete_conversation('2026-11-15')
        self.assertTrue(sonuc['ok'])
        self.assertNotIn('learning_buffer', self._disk())

    def test_yeni_sohbet_onayli_bilgiyi_silmez(self):
        self.profil.data['facts'] = ['kalici bilgi']
        self.profil.data['learning_buffer'] = [STABLE_OLD]
        self.profil.save()
        with patch.object(conversation_reset, 'mark'):
            self._bridge().chat_reset()
        self.assertEqual(self._disk()['facts'], ['kalici bilgi'])

    def test_baska_kullanicinin_tamponu_karismaz(self):
        diger = profiles.Profile('Ebru')
        self.profil.data['learning_buffer'] = [STABLE_OLD]
        self.profil.save()
        with patch.object(conversation_reset, 'mark'):
            self._bridge().chat_reset()
        self.assertNotIn('learning_buffer', self._disk())
        self.assertEqual(diger.data.get('learning_buffer', []), [])


class SimpleNamespaceBridge:
    """WebChat'ın üretime giden tek sıfırlama noktasını taklit eder (cihaz/sunucu yok)."""
    def __init__(self, profil):
        self.engine = SimpleEngine()
        self._profil = profil
        self.history = Mock()
        self.llm = Mock()

    def _p(self):
        return self._profil


class SimpleEngine:
    def __init__(self):
        self._event_lock = threading.Lock()
        self.requests_state = Mock()
        self._sessions = Mock()
        self._pending_photo = {}
        self.event_log = []

    @property
    def profile(self):
        return None


if __name__ == '__main__':
    unittest.main()
