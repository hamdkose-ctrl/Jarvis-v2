"""Default :latest aliases must not select another installed model."""
import unittest
from unittest.mock import patch
from modules import llm

class OllamaModelAliasTests(unittest.TestCase):
    def resolve(self, preference, installed, requested=None):
        with patch.object(llm,'ollama_models',return_value=installed), \
             patch.object(llm,'_choice',return_value={'local_model':preference}), \
             patch.object(llm,'load_settings',return_value={}):
            return llm._ollama_effective_model({'backend':'ollama','provider':'ollama','model':preference},requested=requested)
    def test_untagged_preference_maps_to_installed_latest_before_sorted_fallback(self):
        self.assertEqual(self.resolve('llama3.2',['gemma3:4b','llama3.2:latest']),'llama3.2:latest')
    def test_untagged_explicit_request_keeps_its_installed_model(self):
        self.assertEqual(self.resolve('gemma3:4b',['gemma3:4b','llama3.2:latest'],requested='llama3.2'),'llama3.2:latest')
    def test_non_latest_tag_does_not_match_another_tag(self):
        self.assertEqual(self.resolve('llama3.2:3b',['gemma3:4b','llama3.2:latest']),'gemma3:4b')
