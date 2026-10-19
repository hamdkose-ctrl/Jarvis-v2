"""Unwired classifier: unknown labels never acquire read permission."""
import unittest
from modules.permission_classify import classify


class PermissionClassifyTests(unittest.TestCase):
    def test_documented_turkish_and_english_actions(self):
        rows = {'message_out': ['Gönder', 'Send', 'Mesaj gönder'],
                'publish': ['Yayınla', 'Publish', 'Paylaş', 'Post'],
                'local_destructive': ['Sil', 'Delete', 'Biçimlendir', 'Format', 'Üzerine yaz', 'Overwrite'],
                'money_credential': ['Öde', 'Pay', 'Satın al', 'Buy', 'Şifre', 'Password'],
                'system_config': ['Ayarlar', 'Settings', 'Kayıt defteri', 'Registry'],
                'read': ['Aç', 'Open', 'Oku', 'Read', 'Göster', 'Show']}
        for via in ('outbox', 'desktop', 'browser', 'file', 'system'):
            for expected, names in rows.items():
                for name in names:
                    with self.subTest(via=via, name=name):
                        self.assertEqual(classify(via, name), expected)

    def test_case_whitespace_ascii_and_turkish_i(self):
        for name in ('SİL', 'SIL', ' sil ', 'Si\u0307l'):
            with self.subTest(name=name):
                self.assertEqual(classify(' DESKTOP ', name), 'local_destructive')
        self.assertEqual(classify('browser', '  YAYINLA  '), 'publish')
        self.assertEqual(classify('file', 'GÖSTER'), 'read')
        self.assertEqual(classify('file', 'goster'), 'read')

    def test_unknown_empty_wrong_types_and_oversized_labels_fail_closed(self):
        for name in ('', ' ', 'xyz', 'silgi', 'silme', 'readonly', 'gösterişli', 'x' * 513, None, 1, [], {}):
            with self.subTest(name=name):
                self.assertEqual(classify('file', name), 'system_config')
        for via in ('shell', '', None, [], 5):
            self.assertEqual(classify(via, 'Read'), 'system_config')
        for target in (None, 1, [], 'x' * 2049):
            self.assertEqual(classify('file', 'Read', target), 'system_config')

    def test_risky_combined_label_cannot_hide_behind_read_word(self):
        for name, expected in [('Aç ve sil', 'local_destructive'), ('Read and send', 'message_out'),
                               ('Göster ve öde', 'money_credential'), ('Delete and pay', 'money_credential'),
                               ('Read settings', 'system_config'), ('Send and publish', 'publish')]:
            with self.subTest(name=name):
                self.assertEqual(classify('browser', name), expected)
        self.assertEqual(classify('browser', 'open mystery action'), 'system_config')

    def test_target_cannot_turn_credentials_or_registry_into_plain_read(self):
        self.assertEqual(classify('desktop', 'Aç', 'Şifre yöneticisi'), 'money_credential')
        self.assertEqual(classify('system', 'Open', 'Kayıt defteri'), 'system_config')
        self.assertEqual(classify('file', 'Oku', 'rapor.txt'), 'read')

    def test_reversible_file_actions_are_not_assumed_safe_on_other_routes(self):
        for via in ('file', 'desktop'):
            for name in ('Kopyala', 'Copy', 'Yeni klasör', 'Create folder'):
                self.assertEqual(classify(via, name), 'local_reversible')
        for via in ('system', 'browser', 'outbox'):
            self.assertEqual(classify(via, 'Copy'), 'system_config')

    def test_classification_does_not_grant_permission_or_execute(self):
        from modules.permission_gate import decide
        for name, decision in [('Gönder', 'ask'), ('Yayınla', 'ask'), ('Öde', 'deny'), ('Sil', 'ask')]:
            action = {'class': classify('desktop', name), 'via': 'desktop', 'target': 'example'}
            self.assertEqual(decide(action, now=100)['decision'], decision)


if __name__ == '__main__':
    unittest.main()
