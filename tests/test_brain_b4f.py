"""B4f: Core research başka sahibi olan/yanlış pozitif cümleleri almaz; çeviri non_text_target yalnız komut ifadesine bakar."""
import unittest
from unittest.mock import patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_understanding


def understand(text):
    return brain_understanding.understand(owner=fx.OWNER, request_id=fx.RID, text=text, active_context=fx.context(),
                                          candidates=(), references=())


OTHER_OWNER = ("altın fiyatını internette bul", "bitcoin kurunu google'da ara", "hava durumunu google'da bul",
               "euro dolar kurunu internette ara", "dünkü maç skorunu internette bul", "bugünkü namaz vakitlerini google'da ara")
FALSE_POSITIVES = ("internet hızımı bul", "internet kafe bul", "Chrome'da internet geçmişimde ara",
                   "Excel'de haber sütununu ara", "Google Drive'da bütçe tablosunu bul")
REAL_RESEARCH = ("son yapay zeka haberlerini araştır", "internette deprem haberlerini ara", "bu hafta yapay zeka haberlerini araştır",
                 "google'da python öğrenme kaynaklarını bul")


class ResearchBoundaryTests(unittest.TestCase):
    def test_other_owner_and_false_positive_sentences_get_no_core_research_args(self):
        for text in OTHER_OWNER + FALSE_POSITIVES:
            self.assertNotIn("research", understand(text).arguments, text)

    def test_real_public_research_still_gets_args(self):
        for text in REAL_RESEARCH:
            self.assertIn("research", understand(text).arguments, text)

    def test_mutation_without_the_exclusion_they_all_become_research(self):
        with patch.object(brain_understanding, "_RESEARCH_OTHER_OWNER", brain_understanding.re.compile(r"(?!x)x")):
            hits = [t for t in OTHER_OWNER + FALSE_POSITIVES if "research" in understand(t).arguments]
        self.assertGreaterEqual(len(hits), 8, hits)


class TranslationTargetScopeTests(unittest.TestCase):
    def hint(self, text):
        return brain_understanding.understand(owner=fx.OWNER, request_id=fx.RID, text=text, active_context=fx.context(),
                                              candidates=(), references=()).capability_hint

    def test_inline_text_may_contain_target_words(self):
        for text in ("ingilizceye çevir: sessiz kal", "ingilizceye çevir: ses çıkarma", "almancaya çevir: bu resim çok güzel",
                     "çevir: ekran çok parlak"):
            self.assertEqual(self.hint(text), "text.translate", text)

    def test_object_targets_still_belong_to_other_capabilities(self):
        for text in ("bunu tabloya çevir", "kodu pythona çevir", "bu fotoğrafı çevir", "ekrandaki yazıyı çevir"):
            self.assertNotEqual(self.hint(text), "text.translate", text)


if __name__ == "__main__":
    unittest.main()
