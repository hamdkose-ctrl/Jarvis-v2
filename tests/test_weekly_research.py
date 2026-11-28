from __future__ import annotations

import unittest
from unittest.mock import patch

from modules import task_plan_contracts, weekly_research


class HaftalikArastirmaTestleri(unittest.TestCase):
    """Haftalık tur gerçek sözleşmeden geçmeli ve kuyruğa cron ile yazılmalı."""

    def test_plan_gercek_sozlesmeden_gecer(self):
        gorevler = weekly_research.plan('yapay zeka mevzuatı')
        self.assertEqual(task_plan_contracts.validate(gorevler), gorevler)
        self.assertEqual([t['agent'] for t in gorevler], ['research', 'writer'])
        self.assertTrue(gorevler[0]['input']['query'])
        self.assertEqual(gorevler[1]['depends'], ['arastir'])

    def test_schedule_cron_ile_kuyruga_yazar(self):
        with patch.object(weekly_research.task_queue, 'enqueue',
                          return_value='a1b2c3d4e5f60718') as kuyruk:
            kayit = weekly_research.schedule('alice', 'yapay zeka mevzuatı')
        self.assertEqual(kayit['cron'], '0 9 * * 1')
        self.assertEqual(kayit['window_days'], 7)
        gorevler = kuyruk.call_args.args[1]
        self.assertEqual(task_plan_contracts.validate(gorevler), gorevler)
        self.assertEqual(kuyruk.call_args.kwargs['cron'], '0 9 * * 1')

    def test_bos_konu_reddedilir(self):
        for konu in ('', '   ', None):
            with self.assertRaises((ValueError, TypeError)):
                weekly_research.plan(konu)
    def test_komut_turu_kuyruga_yaziyor(self):
        from modules import task_agents

        kayit = {'id': 'a1b2c3d4e5f60718', 'cron': '0 9 * * 1',
                 'label': 'Her pazartesi 09:00', 'window_days': 7,
                 'topic': 'yapay zeka mevzuatı'}
        with patch.object(weekly_research, 'schedule', return_value=kayit) as zamanla:
            yanit = task_agents.handle('alice', 'haftalık araştırma turu kur: yapay zeka mevzuatı')
        self.assertEqual(zamanla.call_args.args, ('alice', 'yapay zeka mevzuatı'))
        self.assertIn('0 9 * * 1', yanit)
        self.assertIn('a1b2c3d4e5f60718', yanit)


if __name__ == '__main__':
    unittest.main()
