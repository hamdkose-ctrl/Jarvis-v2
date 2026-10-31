import copy
import dataclasses
import pathlib
import pickle
import unittest

from modules import privacy_sources as ps
from modules.privacy_sources import Labeled, RouteClass, RouteContext, classify, mark_private, mark_public

ROOT = pathlib.Path(__file__).resolve().parent.parent


class PublicProvenanceTests(unittest.TestCase):
    def test_allowlisted_sources_produce_public(self):
        for source in ("web_search", "news_pipeline", "public_page_reader"):
            self.assertIs(classify([mark_public(source, {"x": 1})]), RouteClass.PUBLIC, source)

    def test_unlisted_tool_cannot_make_itself_public(self):
        label = mark_public("foo_tool", "sonuç")
        self.assertIs(label.route, RouteClass.PRIVATE)
        self.assertIs(classify([label]), RouteClass.PRIVATE)

    def test_malformed_source_ids_are_private(self):
        for source in ("", "WEB_SEARCH", " web_search", None, 7, ("web_search",), "web_search\n"):
            self.assertIs(classify([mark_public(source, "x")]), RouteClass.PRIVATE, repr(source))

    def test_forged_dict_labels_are_private(self):
        forged = [
            {"privacy": "PUBLIC", "source": "web_search", "payload": "x"},
            {"privacy": RouteClass.PUBLIC, "source_id": "web_search"},
            "PUBLIC", RouteClass.PUBLIC, object(), None, 1,
        ]
        for item in forged:
            self.assertIs(classify([item]), RouteClass.PRIVATE, repr(item))

    def test_hand_built_public_label_is_rejected(self):
        with self.assertRaises(ValueError):
            Labeled("x", "web_search", RouteClass.PUBLIC)
        with self.assertRaises(ValueError):
            Labeled("x", "web_search", RouteClass.PUBLIC, object())

    def test_subclass_and_copies_cannot_smuggle_public(self):
        class Fake(Labeled):
            pass
        genuine = mark_public("web_search", "x")
        fake = Fake("x", "web_search", RouteClass.PRIVATE)
        object.__setattr__(fake, "route", RouteClass.PUBLIC)
        self.assertIs(classify([fake]), RouteClass.PRIVATE)
        self.assertIs(classify([copy.copy(genuine)]), RouteClass.PUBLIC)  # same issuer, still genuine
        with self.assertRaises(ValueError):
            dataclasses.replace(genuine, _issuer=None)
        try:
            restored = pickle.loads(pickle.dumps(genuine))
        except Exception:
            restored = None
        if restored is not None:
            self.assertIs(classify([restored]), RouteClass.PRIVATE)  # issuer identity does not survive

    def test_label_removed_from_allowlist_after_marking_is_private(self):
        label = mark_public("web_search", "x")
        original = ps.PUBLIC_SOURCE_ALLOWLIST
        try:
            ps.PUBLIC_SOURCE_ALLOWLIST = frozenset({"news_pipeline"})
            self.assertIs(classify([label]), RouteClass.PRIVATE)
        finally:
            ps.PUBLIC_SOURCE_ALLOWLIST = original

    def test_allowlist_is_immutable(self):
        self.assertIsInstance(ps.PUBLIC_SOURCE_ALLOWLIST, frozenset)


class RouteClassTests(unittest.TestCase):
    def test_empty_and_unlabeled_context_is_private(self):
        self.assertIs(classify([]), RouteClass.PRIVATE)
        self.assertIs(classify(["etiketsiz araç çıktısı"]), RouteClass.PRIVATE)
        self.assertIs(classify(iter(())), RouteClass.PRIVATE)

    def test_non_iterable_is_private(self):
        self.assertIs(classify(None), RouteClass.PRIVATE)
        self.assertIs(classify(5), RouteClass.PRIVATE)

    def test_public_plus_private_is_private_in_any_order(self):
        public = mark_public("web_search", "haber")
        for private in (mark_private("history", "özel"), "etiketsiz", {"privacy": "PUBLIC"}):
            self.assertIs(classify([public, private]), RouteClass.PRIVATE)
            self.assertIs(classify([private, public]), RouteClass.PRIVATE)

    def test_private_taint_is_sticky(self):
        context = RouteContext([mark_public("web_search", "a")])
        self.assertIs(context.route, RouteClass.PUBLIC)
        context.add(mark_private("memory", "özel"))
        self.assertIs(context.route, RouteClass.PRIVATE)
        context.add(mark_public("news_pipeline", "b"))
        context.add(mark_public("public_page_reader", "c"))
        self.assertIs(context.route, RouteClass.PRIVATE)

    def test_there_is_no_downgrade_api(self):
        public_names = {name for name in dir(RouteContext) if not name.startswith("_")}
        self.assertEqual(public_names, {"add", "route"})


class AuthorityIsCentralizedTests(unittest.TestCase):
    def test_no_other_module_declares_public_privacy(self):
        needles = ('"privacy": "PUBLIC"', "'privacy': 'PUBLIC'", 'privacy="PUBLIC"', '"privacy":"PUBLIC"')
        offenders = []
        for path in ROOT.rglob("*.py"):
            rel = path.relative_to(ROOT)
            if rel.parts[0] in {"tests", ".git"} or path.name == "privacy_sources.py":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(needle in text for needle in needles):
                offenders.append(str(rel))
        self.assertEqual(offenders, [])

    def test_allowlist_defined_only_in_privacy_sources(self):
        offenders = []
        for path in ROOT.rglob("*.py"):
            rel = path.relative_to(ROOT)
            if rel.parts[0] in {"tests", ".git"} or path.name == "privacy_sources.py":
                continue
            if "PUBLIC_SOURCE_ALLOWLIST =" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(rel))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
