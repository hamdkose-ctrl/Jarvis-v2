"""Roadmap drift CI kontrolu icin sozlesme testleri.

classify()'nin surecleri. Git ile bagimlilik yok; is_new_file,
symbol_delta ve body_delta cagirilebilir olarak enjekte edilir.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.roadmap_drift_check import classify

ROOT = Path("repo")


def _no_symbols(path: str) -> set[str]:
    return set()


def _body_changed(path: str) -> bool:
    return True


def _body_unchanged(path: str) -> bool:
    return False


def _new_symbol(name: str):
    def _delta(path: str) -> set[str]:
        return {name}
    return _delta


class RoadmapDriftClassifyTests(unittest.TestCase):
    """classify()'nin surecleri."""

    def test_roadmap_affecting_without_roadmap_update_fails(self):
        """Yeni yetenek + roadmap guncellenmemis -> FAIL."""
        result = classify(
            ["modules/new_capability.py"],
            ROOT,
            is_new_file=lambda p: True,
            symbol_delta=_new_symbol("NewCapability"),
            body_delta=_body_unchanged,
        )
        self.assertTrue(result["roadmap_required"])
        self.assertFalse(result["roadmap_updated"])
        self.assertFalse(result["pass"])
        self.assertIn("modules/new_capability.py", result["roadmap_affecting"])

    def test_roadmap_affecting_with_roadmap_update_passes(self):
        """Yeni yetenek + roadmap da guncellenmis -> PASS."""
        result = classify(
            ["modules/new_capability.py", "docs/Jarvis_Yol_Haritasi.md"],
            ROOT,
            is_new_file=lambda p: True,
            symbol_delta=_new_symbol("NewCapability"),
            body_delta=_body_unchanged,
        )
        self.assertTrue(result["roadmap_required"])
        self.assertTrue(result["roadmap_updated"])
        self.assertTrue(result["pass"])

    def test_only_test_changes_no_roadmap_required(self):
        """Sadece test dosyasi degisikligi -> roadmap zorunlu degil, PASS."""
        result = classify(
            ["tests/test_something.py"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_unchanged,
        )
        self.assertFalse(result["roadmap_required"])
        self.assertTrue(result["pass"])

    def test_only_ci_changes_no_roadmap_required(self):
        """Sadece CI altyapisi degisikligi -> roadmap zorunlu degil, PASS."""
        result = classify(
            [".github/workflows/testler-windows.yml"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_unchanged,
        )
        self.assertFalse(result["roadmap_required"])
        self.assertTrue(result["pass"])

    def test_only_script_changes_no_roadmap_required(self):
        """Sadece scripts/ degisikligi -> roadmap zorunlu degil, PASS."""
        result = classify(
            ["scripts/some_maintenance.py"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_unchanged,
        )
        self.assertFalse(result["roadmap_required"])
        self.assertTrue(result["pass"])

    def test_only_non_roadmap_docs_no_roadmap_required(self):
        """Sadece diger docs/ degisikligi -> gereksiz fail yok, PASS."""
        result = classify(
            ["docs/README.md", "docs/agents/gorev-cekirdegi.md"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_unchanged,
        )
        self.assertFalse(result["roadmap_required"])
        self.assertTrue(result["pass"])

    def test_modified_module_no_new_public_symbol_no_roadmap(self):
        """Var olan modulu sadece icten degistirdiginde (refactor) gerek yok."""
        result = classify(
            ["modules/existing_module.py"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_unchanged,
        )
        self.assertFalse(result["roadmap_required"])
        self.assertTrue(result["pass"])

    def test_modified_module_with_new_public_symbol_requires_roadmap(self):
        """Var olan modulune yeni public simge eklendiyse roadmap zorunlu."""
        result = classify(
            ["modules/existing_module.py"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_new_symbol("new_public_function"),
            body_delta=_body_unchanged,
        )
        self.assertTrue(result["roadmap_required"])
        self.assertFalse(result["pass"])

    def test_roadmap_script_own_changes_no_self_trigger(self):
        """Kendi dosyasinda degisiklik => sonsuz tetikleme yok, PASS."""
        result = classify(
            ["scripts/roadmap_drift_check.py"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_unchanged,
        )
        self.assertFalse(result["roadmap_required"])
        self.assertTrue(result["pass"])

    def test_empty_changes_pass(self):
        """Degisiklik yoksa PASS."""
        result = classify(
            [],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_unchanged,
        )
        self.assertFalse(result["roadmap_required"])
        self.assertTrue(result["pass"])

    def test_mixed_excluded_and_roadmap_affecting(self):
        """Test + yeni yetenek karisimi: roadmap guncellenmemiÅŸse FAIL."""
        result = classify(
            ["tests/test_foo.py", "modules/new_feat.py"],
            ROOT,
            is_new_file=lambda p: p.endswith("new_feat.py"),
            symbol_delta=_new_symbol("NewFeat"),
            body_delta=_body_unchanged,
        )
        self.assertTrue(result["roadmap_required"])
        self.assertFalse(result["pass"])

    def test_roadmap_file_alone_is_not_roadmap_affecting(self):
        """Sadece roadmap dosyasi degisikligi, PASS (zaten guncellenmis)."""
        result = classify(
            ["docs/Jarvis_Yol_Haritasi.md"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_unchanged,
        )
        self.assertFalse(result["roadmap_required"])
        self.assertTrue(result["pass"])

    # --- Yeni surecler (Faz durumunu degistiren mevcut fonksiyon govdesi degisiklikleri) ---

    def test_existing_module_body_change_without_roadmap_fails(self):
        """Senaryo 1: Mevcut modul govdesi degisti (Faz madde tamamlayici), roadmap yok -> FAIL."""
        result = classify(
            ["modules/existing_module.py"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_changed,
        )
        self.assertTrue(result["roadmap_required"])
        self.assertFalse(result["roadmap_updated"])
        self.assertFalse(result["pass"])
        self.assertIn("modules/existing_module.py", result["roadmap_affecting"])

    def test_existing_module_body_change_with_roadmap_passes(self):
        """Senaryo 2: Ayni govdesi degisikligi + roadmap guncellenmis -> PASS."""
        result = classify(
            ["modules/existing_module.py", "docs/Jarvis_Yol_Haritasi.md"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_changed,
        )
        self.assertTrue(result["roadmap_required"])
        self.assertTrue(result["roadmap_updated"])
        self.assertTrue(result["pass"])

    def test_legacy_removal_or_wiring_without_roadmap_fails(self):
        """Senaryo 3: Legacy kaldirma / canli wiring (yeni public simge yok) + roadmap yok -> FAIL."""
        result = classify(
            ["modules/existing_module.py"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_changed,
        )
        self.assertTrue(result["roadmap_required"])
        self.assertFalse(result["pass"])

    def test_safe_refactor_body_unchanged_passes(self):
        """Senaryo 4: Saf refactor (govde degismemis) -> PASS."""
        result = classify(
            ["modules/existing_module.py"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_unchanged,
        )
        self.assertFalse(result["roadmap_required"])
        self.assertTrue(result["pass"])

    def test_bugfix_test_ci_docs_only_passes(self):
        """Senaryo 5: Bugfix/test/CI/docs-only degisiklik -> PASS."""
        for path in [
            "tests/test_fix.py",
            ".github/workflows/ci.yml",
            "scripts/maint.py",
            "docs/notes.md",
        ]:
            result = classify(
                [path],
                ROOT,
                is_new_file=lambda p: False,
                symbol_delta=_no_symbols,
                body_delta=_body_unchanged,
            )
            self.assertFalse(result["roadmap_required"], f"{path} should not require roadmap")
            self.assertTrue(result["pass"], f"{path} should PASS")

    def test_new_public_capability_fails(self):
        """Senaryo 6: Yeni public capability -> FAIL."""
        result = classify(
            ["modules/new_feat.py"],
            ROOT,
            is_new_file=lambda p: True,
            symbol_delta=_new_symbol("NewFeat"),
            body_delta=_body_unchanged,
        )
        self.assertTrue(result["roadmap_required"])
        self.assertFalse(result["pass"])

    def test_uncertain_body_change_fails_closed(self):
        """Senaryo 8: Belirsiz durumda sessizce PASS yok; govde degisti ise exceptions yoksa FAIL."""
        result = classify(
            ["modules/existing_module.py"],
            ROOT,
            is_new_file=lambda p: False,
            symbol_delta=_no_symbols,
            body_delta=_body_changed,
        )
        self.assertTrue(result["roadmap_required"])
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()

