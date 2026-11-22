"""P0-2: sağlayıcı gizlilik kanıtının süresi (TTL).

Kanıt bir kez yazılıp sonsuza kadar güvenilir sayılamaz: 180 gün sonra
yenilenmesi gerekir. Süresi geçmiş veya tarihsiz kanıt fail-closed reddedilir;
bugünkü (taze) kanıtla davranış değişmez.
"""
import unittest

from modules import provider_privacy as pp

ROUTES = ("PUBLIC_RESEARCH", "PRIVATE_GENERAL")


def _fresh_facts(**changes):
    base = dict(pp.PROVIDER_BUNDLE["groq"])
    base.update(changes)
    return base


class EvidenceFresnessTests(unittest.TestCase):
    def test_live_bundle_is_current_and_unchanged_today(self):
        # Gemini ücretsiz katmanda veriyi eğitimde kullanabilir: genel rota için
        # açık kapsam izni gerekir. Diğer ikisi her iki rotada açık.
        for provider in ("gemini", "groq", "cloudflare"):
            gate = pp.privacy_gate(provider, pp.ROUTE_PUBLIC_RESEARCH)
            self.assertTrue(gate["ok"], (provider, gate))
        for provider in ("groq", "cloudflare"):
            gate = pp.privacy_gate(provider, pp.ROUTE_PRIVATE_GENERAL)
            self.assertTrue(gate["ok"], (provider, gate))
        self.assertTrue(pp.privacy_gate("gemini", pp.ROUTE_PRIVATE_GENERAL,
                                        consent_scopes=("conversation",))["ok"])
        self.assertEqual(pp.EVIDENCE_TTL_DAYS, 180)

    def test_expired_evidence_is_rejected(self):
        facts = _fresh_facts()
        later = facts["expires_at"] + 1
        for provider in ("gemini", "groq", "cloudflare"):
            gate = pp.privacy_gate(provider, pp.ROUTE_PUBLIC_RESEARCH, now=later)
            self.assertFalse(gate["ok"])
            self.assertEqual(gate["reason_code"], "PROVIDER_PRIVACY_EVIDENCE_STALE")

    def test_undated_or_misdated_evidence_is_rejected(self):
        now = pp.PROVIDER_BUNDLE["groq"]["verified_at"] + 10
        for broken in (
            {"verified_at": None},
            {"expires_at": None},
            {"verified_at": "2026-11-19"},
            {"verified_at": now + 3600},                       # gelecek tarihli kanıt
            {"verified_at": now - 10, "expires_at": now - 5},   # süresi geçmiş
            {"verified_at": now - 400 * 86400, "expires_at": now + 86400},  # TTL'den uzun
        ):
            bundle = {"groq": _fresh_facts(**broken)}
            gate = pp.privacy_gate("groq", pp.ROUTE_PUBLIC_RESEARCH, bundle=bundle, now=now)
            self.assertFalse(gate["ok"], broken)
            self.assertEqual(gate["reason_code"], "PROVIDER_PRIVACY_EVIDENCE_STALE", broken)

    def test_training_provider_still_needs_explicit_consent(self):
        """TTL eklendi, veri izni kuralı aynen korunuyor."""
        gate = pp.privacy_gate("gemini", pp.ROUTE_PRIVATE_GENERAL)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["reason_code"], "PROVIDER_ROUTE_NOT_ALLOWED")
        allowed = pp.privacy_gate("gemini", pp.ROUTE_PRIVATE_GENERAL,
                                  consent_scopes=("conversation",), data_scope="conversation")
        self.assertTrue(allowed["ok"])

    def test_unknown_provider_is_still_rejected(self):
        gate = pp.privacy_gate("openrouter", pp.ROUTE_PUBLIC_RESEARCH)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["reason_code"], "PROVIDER_PRIVACY_EVIDENCE_MISSING")


if __name__ == "__main__":
    unittest.main()
