"""Distinct profile handles must not persist stale snapshots of one file."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from modules import personalization as profiles

class SharedProfileTests(unittest.TestCase):
    def test_old_handle_preserves_new_facts_and_preferences(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(profiles,'USERS_DIR',Path(folder)):
            screen=profiles.Profile('Hamdi');chat=profiles.Profile('Hamdi')
            chat.add_fact('new fact');screen.set_pref('voice','Emel')
            saved=json.loads(screen.path.read_text())
            self.assertEqual(saved['facts'],['new fact'])
            self.assertEqual(saved['prefs']['voice'],'Emel')
            self.assertIs(screen.data,chat.data)
            other=profiles.Profile('Ebru');self.assertIsNot(other.data,chat.data)

    def test_concurrent_fact_additions_from_separate_handles(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(profiles,'USERS_DIR',Path(folder)):
            handles=[profiles.Profile('Hamdi') for _ in range(4)]
            threads=[threading.Thread(target=lambda p=p,n=n:[p.add_fact(f'{n}:{i}') for i in range(20)]) for n,p in enumerate(handles)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(5);self.assertFalse(thread.is_alive())
            self.assertEqual(len(json.loads(handles[0].path.read_text())['facts']),80)

    def test_concurrent_command_counts_do_not_lose_increments(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(profiles,'USERS_DIR',Path(folder)):
            handles=[profiles.Profile('Hamdi') for _ in range(4)]
            threads=[threading.Thread(target=lambda p=p:[p.log_command('chat') for _ in range(30)]) for p in handles]
            for thread in threads:thread.start()
            for thread in threads:thread.join(5);self.assertFalse(thread.is_alive())
            self.assertEqual(json.loads(handles[0].path.read_text())['command_counts']['chat'],120)
