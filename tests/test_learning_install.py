import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from modules import learning
from modules.personalization import Profile

class LearningInstallTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.p=Profile.__new__(Profile);self.p.slug='test';self.p.path=Path(self.tmp.name)/'profile.json'
  self.p.data={'name':'Test','prefs':{},'facts':[],'rules':[],'items':[],'goals':[]}
 def test_explicit_fact_persists_and_is_used(self):
  reply=learning.execute_typed(self.p,{'operation':'fact.add','text':'A17 panosunda X200 sensörü kullanıyoruz'})
  self.assertIn('kaydettim',reply)
  import json
  self.p.data=json.loads(self.p.path.read_text(encoding='utf-8'))
  self.assertIn('X200',self.p.system_prompt('A17 sensörü?'))
  self.assertEqual(self.p.data['rules'],[])
 def test_negative_approval(self):
  learning.propose(self.p,['A17 panosunda X200 sensörü var'])
  learning.execute_typed(self.p,{'operation':'pending.reject'})
  self.assertEqual(self.p.data['facts'],[]);self.assertEqual(learning.pending(self.p),[])
 def test_numbered_negative(self):
  learning.propose(self.p,['A17 panosunda X200 sensörü var'])
  learning.execute_typed(self.p,{'operation':'pending.reject','index':1})
  self.assertEqual(self.p.data['facts'],[]);self.assertEqual(learning.pending(self.p),[])
 def test_notes_and_user_isolation(self):
  self.p.data['items']=[{'text':'A17 arızasında sigorta kontrol edilir.'}]
  self.p.data['pending_facts']=['Gizli aday']
  prompt=learning.knowledge_prompt(self.p,'A17 arıza')
  self.assertIn('sigorta',prompt);self.assertNotIn('Gizli aday',prompt)
  other=Profile.__new__(Profile);other.data={'facts':[],'items':[]}
  self.assertEqual(learning.knowledge_prompt(other,'A17'),'')
 def test_memory_relevance_gate_excludes_unrelated_memory(self):
  self.p.data['facts']=['A17 panosunda X200 sensörü kullanılıyor','Kahvede şekersiz içmeyi tercih ediyor']
  prompt=learning.knowledge_prompt(self.p,'A17 sensörü hangisi?')
  self.assertIn('X200',prompt)
  self.assertNotIn('şekersiz',prompt)
 def test_observation_and_disable(self):
  with patch.object(learning,'load_settings',return_value={}):
   self.assertTrue(learning.observe(self.p,'A17 panosunda X200 sensörü kullanıyoruz.'))
   self.assertEqual(self.p.data['facts'],[])
   self.p.data['prefs']['learn_from_chat']=False
   self.assertEqual(learning.observe(self.p,'B18 panosunda başka sensör kullanıyoruz.'),[])
 def test_no_twenty_fact_limit_or_duplicates(self):
  for i in range(25):self.p.add_fact(f'Bilgi {i}')
  self.p.add_fact('Bilgi 0');self.assertEqual(len(self.p.data['facts']),25)
 def test_background_owner_and_error(self):
  jobs=[]
  with patch.object(learning._pool,'submit',side_effect=jobs.append),patch.object(learning,'load_settings',return_value={}):
   for text in ['Bugün iş yerinde konuştuğumuz ayrıntı bir.','Bugün iş yerinde konuştuğumuz ayrıntı iki.','Bugün iş yerinde konuştuğumuz ayrıntı üç.']:learning.observe(self.p,text)
  self.assertEqual(len(jobs),1)
  with patch.object(learning,'extract_from_session',side_effect=RuntimeError('offline')):jobs[0]()
  self.assertEqual(self.p.data['learning_status']['state'],'error')
  self.assertNotIn(self.p.slug,learning._busy)
