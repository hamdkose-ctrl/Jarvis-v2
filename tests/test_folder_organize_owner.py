import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FolderOrganizeOwnerTests(unittest.TestCase):
    def test_bulk_organize_undo_is_owned_by_the_user_who_confirmed_it(self):
        from modules import files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'Masaüstü' / 'not.txt'
            target = root / 'Masaüstü' / 'Belgeler' / 'not.txt'
            source.parent.mkdir()
            source.write_text('önemli not', encoding='utf-8')
            with patch.object(files, 'DATA_DIR', root / 'state'):
                self.assertEqual(files.apply_organize([(source, target)], 'alice'), 1)
                self.assertTrue(target.is_file())
                self.assertIsNone(files.undo_organize('bob'))
                self.assertTrue(target.is_file())
                self.assertEqual(files.undo_organize('alice'), 1)
            self.assertTrue(source.is_file())

    def test_two_users_of_equal_length_never_share_one_undo_record(self):
        # Red: `_undo_file("hamdi")` ve `_undo_file("kubra")` aynı dosyaya düşüyordu, çünkü
        # regex sınıfı `\\w` yerine literal backslash + "w" harfini dışlıyordu (tüm adlar `_`).
        from modules import files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / 'Masaüstü' / 'a.txt'
            moved = root / 'Masaüstü' / 'Belgeler' / 'a.txt'
            first.parent.mkdir()
            first.write_text('a', encoding='utf-8')
            with patch.object(files, 'DATA_DIR', root / 'state'):
                self.assertNotEqual(files._undo_file('hamdi'), files._undo_file('kubra'))
                self.assertEqual(files.apply_organize([(first, moved)], 'hamdi'), 1)
                self.assertIsNone(files.undo_organize('kubra'))
                self.assertTrue(moved.is_file())
                self.assertEqual(files.undo_organize('hamdi'), 1)
            self.assertTrue(first.is_file())

    def test_a_partial_undo_keeps_the_records_it_could_not_restore(self):
        # Red: orijinal yol dolu olduğu için taşınamayan dosyanın kaydı da siliniyordu; kalan
        # dosya kategoride kalıyor ve ikinci "geri al" hiçbir şey yapmıyordu.
        from modules import files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / 'Masaüstü'
            folder.mkdir()
            first = folder / 'a.txt'
            second = folder / 'b.txt'
            first.write_text('a', encoding='utf-8')
            second.write_text('b', encoding='utf-8')
            plan = [(first, folder / 'Belgeler' / 'a.txt'), (second, folder / 'Belgeler' / 'b.txt')]
            with patch.object(files, 'DATA_DIR', root / 'state'):
                self.assertEqual(files.apply_organize(plan, 'alice'), 2)
                self.assertFalse(folder.joinpath('a.txt').exists())
                # a.txt'in özgün yeri artık dolu: geri alma yalnız b.txt'yi taşır.
                first.write_text('yeni içerik', encoding='utf-8')
                self.assertEqual(files.undo_organize('alice'), 1)
                self.assertTrue(second.is_file())
                undo_file = files._undo_file('alice')
                self.assertTrue(undo_file.is_file(), "kısmi geri almada kalan kayıt silindi")
                remaining = json.loads(undo_file.read_text(encoding='utf-8'))
                self.assertEqual(len(remaining), 1)
                self.assertEqual(Path(remaining[0][1]), first)
                # Kalan kayıt ikinci turda yeniden denenir; dolu hedef ezilmez.
                self.assertEqual(files.undo_organize('alice'), 0)
                self.assertEqual(first.read_text(encoding='utf-8'), 'yeni içerik')
                self.assertTrue(undo_file.is_file(), "kurtarılamayan kayıt ikinci turda düştü")
                # Çakışma kalkınca kayıt hâlâ kurtarılabilir.
                first.unlink()
                self.assertEqual(files.undo_organize('alice'), 1)
                self.assertEqual(first.read_text(encoding='utf-8'), 'a')
                self.assertFalse(undo_file.exists())

    def test_a_record_whose_moved_file_is_missing_is_not_silently_dropped(self):
        # Red: `undo_organize` yerinde bulamadığı kaydı `continue` ile düşürüyordu. Dosya sonra
        # geri gelirse (geri dönüş kutusu, OneDrive eşzitlemesi) geri alınacak kayıt kalmıyordu.
        from modules import files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / 'Masaüstü'
            folder.mkdir()
            first, second = folder / 'a.txt', folder / 'b.txt'
            first.write_text('a', encoding='utf-8')
            second.write_text('b', encoding='utf-8')
            moved_first = folder / 'Belgeler' / 'a.txt'
            plan = [(first, moved_first), (second, folder / 'Belgeler' / 'b.txt')]
            with patch.object(files, 'DATA_DIR', root / 'state'):
                self.assertEqual(files.apply_organize(plan, 'alice'), 2)
                moved_first.unlink()                        # kategorideki dosya şu anda yok
                second.write_text('çakışma', encoding='utf-8')  # öbür kaydın hedefi dolu
                self.assertEqual(files.undo_organize('alice'), 0)
                undo_file = files._undo_file('alice')
                remaining = json.loads(undo_file.read_text(encoding='utf-8'))
                self.assertEqual(len(remaining), 2, "geri alınamamış kayıtlar ledger'da kalmalı")
                # Hedefi açılan kayıt geri alınır; başarılan kayıt tekrar denenmez.
                second.unlink()
                self.assertEqual(files.undo_organize('alice'), 1)
                self.assertEqual(second.read_text(encoding='utf-8'), 'b')
                self.assertEqual(len(json.loads(undo_file.read_text(encoding='utf-8'))), 1)
                # Kayıp kayıt düşürülmedi: dosya kategoride yeniden belirince kayıt tekrar denenir.
                # (Boş kalan kategori klasörü geri alma sırasında temizlenmişti.)
                moved_first.parent.mkdir(exist_ok=True)
                moved_first.write_text('a', encoding='utf-8')
                self.assertEqual(files.undo_organize('alice'), 1)
                self.assertEqual(first.read_text(encoding='utf-8'), 'a')
                self.assertFalse(undo_file.exists())

    def test_the_previewed_plan_stamp_sees_a_different_file_in_the_same_path(self):
        # Red: plan tazeliği yalnız (kaynak, hedef) yollarını karşılaştırıyordu; aynı yolda farklı
        # bir dosya durduğunda (aynı ad, aynı boy) tazelik "değişmedi" diyordu.
        import os
        import shutil
        from modules import files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / 'Masaüstü'
            folder.mkdir()
            path = folder / 'belge.txt'
            path.write_text('orijinal içerik', encoding='utf-8')
            plan = [(path, folder / 'Belgeler' / 'belge.txt')]
            stamp = files.plan_stamp(plan)
            self.assertTrue(files.same_plan(plan, plan))
            # Aynı ad ve aynı boy, başka bir dosya: yol karşılaştırması bunu göremez.
            other = root / 'baska.txt'
            other.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
            os.utime(other, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns))
            os.replace(other, path)
            self.assertTrue(path.is_file())
            self.assertFalse(files.same_plan(plan, plan) and files.plan_stamp(plan) == stamp)
            # Gerçekten dokunulmamış plan ise mühür aynı kalır.
            untouched = folder / 'not.txt'
            untouched.write_text('not', encoding='utf-8')
            clean = [(untouched, folder / 'Belgeler' / 'not.txt')]
            self.assertEqual(files.plan_stamp(clean), files.plan_stamp(clean))
            self.assertTrue(files.same_plan(clean, clean))


class PendingOrganizeFreshnessTests(unittest.TestCase):
    def test_the_pending_job_carries_the_previewed_plan_stamp(self):
        # Red: önizleme job'ı yalnız planı taşıyordu; onay anında "aynı yollar" = "aynı dosyalar"
        # sayılıyordu. Bekleyen iş, önizlemede görülen dosya kimliğini de taşımalıdır.
        from modules import files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / 'Masaüstü'
            folder.mkdir()
            path = folder / 'a.txt'
            path.write_text('a', encoding='utf-8')
            plan = [(path, folder / 'Belgeler' / 'a.txt')]
            job = {"folder": folder, "key": "desktop", "label": "Masaüstü", "plan": plan,
                   "stamp": files.plan_stamp(plan)}
            self.assertIsInstance(job["stamp"], str, "mühür JSON turuna dayanmalı (salt metin)")
            self.assertEqual(json.loads(json.dumps({"stamp": job["stamp"]}))["stamp"], job["stamp"])
            path.write_text('değiştirilmiş uzun içerik', encoding='utf-8')
            self.assertNotEqual(files.plan_stamp(plan), job["stamp"])


if __name__ == '__main__':
    unittest.main()
