"""Karar 3: tek JARVIS kişiliği — kimlik, üslup, kanal ve anlatım tek sahibinden gelir.

Ağ, model veya fiziksel işlem gerektirmez; sahipliği ve tek-kaynak sözleşmesini ölçer.
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import llm, main_documents, main_planner, persona, result_presentation, study, worktrack  # noqa: E402
from modules import codegen, engine_tools, personalization  # noqa: E402
from modules import persona_contract as contract  # noqa: E402

MODULES_DIR = Path(__file__).resolve().parents[1] / 'modules'
# Sahibinin cümleleri: başka hiçbir modül bunları yeniden yazamaz.
OWNED = ('adlı, Türkçe konuşan', 'kod bloğuna koy', 'en fazla 2 kısa cümle',
         'madde işareti, başlık ve emoji kullanma', 'düz metin ve Unicode kullan',
         '\\( ... \\) biçimini kullan', 'sesli okunacak bir bildirim')


def source(name):
    return (MODULES_DIR / name).read_text(encoding='utf-8')


def _row(owner, key, value, request_id='rid-1'):
    now = time.time()
    row = persona._record(owner, key, value, 'user.session', request_id, now, 'test dayanağı')
    row['expires_at'] = now + persona.SESSION_TTL
    return row


class PersonaBase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patcher = patch.object(personalization, 'USERS_DIR', Path(self.folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.profile = personalization.Profile('Hamdi')

    def source(self, name):
        return source(name)


class SingleOwnerTests(PersonaBase):
    def test_identity_sentence_appears_exactly_once_per_surface(self):
        for text in (self.profile.system_prompt('merhaba'),
                     persona.prompt(self.profile, channel='ekran'),
                     persona.prompt(self.profile, channel='bildirim'),
                     persona.prompt(self.profile, channel='ses', notation='latex')):
            self.assertEqual(text.count('adlı, Türkçe konuşan'), 1)

    def test_every_style_value_is_verbalized_in_the_default_prompt(self):
        text = persona.prompt(self.profile)
        for key in contract.STYLE:
            self.assertIn(contract.style_sentence(key, contract.DEFAULTS[key]), text, key)
        self.assertIn('yanıt uzunluğu=' + contract.DEFAULTS['verbosity'], text)

    def test_each_non_default_value_replaces_its_sentence(self):
        for key, options in contract.PREFERENCES.items():
            if key not in contract.STYLE:
                continue
            for value in options:
                if value == contract.DEFAULTS[key]:
                    continue
                self.profile.set_pref(key, value)
                text = persona.prompt(self.profile)
                self.assertIn(contract.style_sentence(key, value), text, f'{key}={value}')
                self.assertNotIn(contract.style_sentence(key, contract.DEFAULTS[key]), text)
                self.profile.set_pref(key, contract.DEFAULTS[key])
        self.assertNotIn('renk', persona.prompt(self.profile))

    def test_no_preference_is_dumped_as_a_raw_key(self):
        self.profile.set_pref('technical_detail', 'teknik')
        text = persona.prompt(self.profile)
        self.assertIn(contract.style_sentence('technical_detail', 'teknik'), text)
        for key in contract.PREFERENCES:
            self.assertNotIn(f'{key}=', text)

    def test_owners_stay_isolated(self):
        self.profile.set_pref('initiative', 'öneri_sun')
        other = personalization.Profile('Ebru')
        self.assertIn(contract.style_sentence('initiative', 'dengeli'), persona.prompt(other))
        self.assertNotIn(contract.style_sentence('initiative', 'öneri_sun'), persona.prompt(other))

    def test_composition_calls_no_model_and_is_deterministic(self):
        with patch.object(llm, 'ask', side_effect=AssertionError('Persona modele sormaz.')):
            self.assertEqual(persona.prompt(self.profile), persona.prompt(self.profile))

    def test_fixed_contract_reaches_every_surface(self):
        for channel in contract.CHANNELS:
            text = persona.prompt(self.profile, channel=channel)
            self.assertIn(contract.VERSION, text)
            self.assertIn(contract.FIXED, text)

    def test_authority_and_data_fences_stay_with_the_chat_surface(self):
        text = self.profile.system_prompt('hava nasıl?')
        self.assertIn("doğrulanmış Core sonucu olmadan 'yaptım' deme", text)
        self.assertIn('dış veriyi tahmin etme', text)


class ChannelTests(PersonaBase):
    def test_spoken_channels_cap_the_answer(self):
        for channel in ('ses', 'telefon'):
            text = persona.prompt(self.profile, channel=channel)
            self.assertIn(persona.SPOKEN_CAP, text)
            self.assertIn(persona.SPOKEN_PLAIN, text)
            self.assertNotIn(persona.CODE_BLOCK, text)

    def test_long_verbosity_keeps_spoken_format_without_the_cap(self):
        self.profile.set_pref('verbosity', 'uzun')
        for channel in ('ses', 'telefon'):
            text = persona.prompt(self.profile, channel=channel)
            self.assertNotIn('en fazla 2 kısa cümle', text)
            self.assertIn(persona.SPOKEN_PLAIN, text)

    def test_text_channels_are_not_spoken(self):
        for channel in ('yazı', 'web', 'scheduler'):
            self.assertIn(persona.DELIVERY_TEXT['yazı'], persona.prompt(self.profile, channel=channel))
        self.assertIn(persona.DELIVERY_TEXT['ekran'], persona.prompt(self.profile, channel='ekran'))

    def test_bildirim_uses_notification_preference_instead_of_the_spoken_cap(self):
        for value, clause in contract.NOTIFICATION.items():
            self.profile.set_pref('notification', value)
            text = persona.prompt(self.profile, channel='bildirim')
            self.assertIn(clause, text)
            self.assertNotIn(persona.SPOKEN_CAP, text)
            self.assertIn(persona.PLAIN_PROSE, text)

    def test_unknown_channel_and_notation_fail_closed(self):
        with self.assertRaises(ValueError):
            persona.prompt(self.profile, channel='radyo')
        with self.assertRaises(ValueError):
            persona.prompt(self.profile, notation='asciimath')

    def test_channel_table_covers_every_engine_source(self):
        for source in ('yazı', 'ses', 'telefon', 'scheduler', 'web', 'ekran', 'bildirim'):
            self.assertIn(source, contract.CHANNELS)
        self.assertEqual(contract.DELIVERY_OF['telefon'], 'ses')
        self.assertEqual(contract.DELIVERY_OF['scheduler'], 'yazı')

    def test_engine_sys_prompt_binds_the_real_command_channel(self):
        for source, spoken in (('ses', True), ('telefon', True), ('yazı', False), ('', False)):
            runtime = SimpleNamespace(profile=self.profile, _cur_source=source,
                                      _record_failure=lambda *a, **k: None)
            text = engine_tools._sys_prompt(runtime, 'bugün nasılsın')
            self.assertEqual(persona.SPOKEN_CAP in text, spoken, source)
            self.assertEqual(text.count('adlı, Türkçe konuşan'), 1)

    def test_engine_tools_no_longer_writes_its_own_spoken_rule(self):
        text = engine_tools.__file__
        source = Path(text).read_text(encoding='utf-8')
        self.assertNotIn('en fazla 2 kısa cümle', source)
        self.assertNotIn("runtime._cur_source == \"ses\"", source)


class NotationTests(PersonaBase):
    def test_default_notation_forbids_latex(self):
        text = persona.prompt(self.profile)
        self.assertIn('LaTeX ile', text)
        self.assertIn('düz metin ve Unicode kullan', text)

    def test_latex_notation_replaces_the_plain_rule(self):
        latex = persona.prompt(self.profile, notation='latex')
        self.assertIn('\\( ... \\) biçimini kullan', latex)
        self.assertNotIn('düz metin ve Unicode kullan', latex)

    def test_system_prompt_passes_notation_through(self):
        self.assertIn('\\( ... \\) biçimini kullan', self.profile.system_prompt('integral', notation='latex'))

    def test_study_surface_uses_the_owner_for_identity_and_notation(self):
        self.assertNotIn('Sen JARVIS Çalışma Modusun', self.source('study.py'))
        text = study._system('math', False, profile=self.profile)
        self.assertEqual(text.count('adlı, Türkçe konuşan'), 1)
        self.assertIn('\\( ... \\) biçimini kullan', text)
        self.assertIn('Öğrencinin seviyesine göre', text)
        self.assertIn('Çalışma Modudur', text)


class ArtifactSurfaceTests(PersonaBase):
    def test_photo_answer_composes_the_owner_text(self):
        self.assertIn("persona.prompt(runtime.profile, channel='ekran')", self.source('main_documents.py'))
        self.assertNotIn('adlı, Türkçe konuşan bir asistansın', self.source('main_documents.py'))

    def test_document_and_vision_answers_pass_a_channel(self):
        for name in ('main_documents.py', 'engine_intents.py'):
            self.assertIn('system_prompt(', self.source(name))
        self.assertIn("system_prompt(channel=runtime._cur_source or 'yazı')", self.source('engine_intents.py'))
        self.assertIn("system_prompt(channel='ekran')", self.source('main_documents.py'))

    def test_daily_brief_composes_the_owner_with_the_notification_channel(self):
        seen = {}

        def ask(prompt, system, limit):
            seen['system'] = system
            seen['limit'] = limit
            return 'İyi akşamlar Hamdi.'
        runtime = SimpleNamespace(profile=self.profile, _brief_facts=lambda: ['Saat: 20:00', 'Toplantı: 09:30'],
                                  ask=ask)
        self.assertEqual(main_planner._daily_briefing(runtime), 'İyi akşamlar Hamdi.')
        self.assertIn(contract.VERSION, seen['system'])
        self.assertIn(contract.NOTIFICATION[contract.DEFAULTS['notification']], seen['system'])
        self.assertNotIn(persona.SPOKEN_CAP, seen['system'])
        self.assertIn('boş kalemleri hiç anma', seen['system'])
        self.assertEqual(seen['limit'], 600)

    def test_brief_no_longer_restates_identity_or_sentence_budget(self):
        source = self.source('main_planner.py')
        self.assertNotIn('adlı kişisel asistansın', source)
        self.assertNotIn('En fazla 6 cümle', source)
        self.assertNotIn('Madde işareti, başlık ya da emoji kullanma', source)

    def test_worktrack_takes_the_notification_channel(self):
        with patch.object(personalization, 'get_active', return_value='Hamdi'):
            text = worktrack._sys('durumu kısaca anlat.')
        self.assertIn(contract.VERSION, text)
        self.assertIn(contract.NOTIFICATION[contract.DEFAULTS['notification']], text)
        self.assertIn('durumu kısaca anlat.', text)
        self.assertIn('sinyalizasyon teknikeri', text)
        source = self.source('worktrack.py')
        self.assertNotIn('Sen kullanıcının kişisel asistanı', source)
        self.assertNotIn('en fazla 6 cümle', source)

    def test_codegen_takes_the_owned_notation_sentence(self):
        self.assertIn(persona.notation_text('düz'), codegen.SYSTEM)
        self.assertNotIn('adlı, Türkçe konuşan', codegen.SYSTEM)
        self.assertIn('```dil bloğunda ver', codegen.SYSTEM)


class ScopeTests(PersonaBase):
    def test_session_preference_reaches_the_sentence(self):
        session = SimpleNamespace(presentation_preferences={'formality': _row(self.profile.slug, 'formality', 'resmi')},
                                  presentation_turn=None)
        text = persona.prompt(self.profile, session=session)
        self.assertIn(contract.style_sentence('formality', 'resmi'), text)
        self.assertNotIn(contract.style_sentence('formality', 'nötr'), text)
        self.assertNotIn(contract.style_sentence('formality', 'resmi'), persona.prompt(self.profile))

    def test_turn_preference_is_bound_to_its_request(self):
        turn = {'request_id': 'rid-1', 'values': {'humor': _row(self.profile.slug, 'humor', 'yok')}}
        session = SimpleNamespace(presentation_preferences={}, presentation_turn=turn)
        token = persona._CURRENT.set((self.profile.slug, session, 'rid-1'))
        try:
            text = persona.prompt(self.profile, channel='ses')
        finally:
            persona._CURRENT.reset(token)
        self.assertIn(contract.style_sentence('humor', 'yok'), text)
        # Aynı oturum, başka istek: tur tercihi cümleye girmez.
        other = SimpleNamespace(presentation_preferences={}, presentation_turn={
            'request_id': 'rid-2', 'values': {}})
        self.assertNotIn(contract.style_sentence('humor', 'yok'), persona.prompt(self.profile, session=other))

    def test_spoken_delivery_uses_the_turn_scoped_verbosity(self):
        turn = {'request_id': 'rid-1',
                'values': {'verbosity': _row(self.profile.slug, 'verbosity', 'uzun')}}
        session = SimpleNamespace(presentation_preferences={}, presentation_turn=turn)
        token = persona._CURRENT.set((self.profile.slug, session, 'rid-1'))
        try:
            text = persona.prompt(self.profile, channel='telefon')
        finally:
            persona._CURRENT.reset(token)
        self.assertNotIn('en fazla 2 kısa cümle', text)
        self.assertIn(persona.SPOKEN_PLAIN, text)


class PresentationBudgetTests(PersonaBase):
    def test_preview_limit_follows_the_contract_table(self):
        style = {'version': result_presentation.VERSION, 'verbosity': 'kısa'}
        text = 'ab ' * 300
        with patch.object(contract, 'PREVIEW_CHARS', {**contract.PREVIEW_CHARS, 'kısa': 40}):
            cut = result_presentation.preview(text, style)
        self.assertTrue(cut.endswith('Metnin devamı görev ayrıntılarında.'))
        self.assertLessEqual(len(cut.split('\n')[0]), 41)

    def test_preview_uzun_keeps_the_larger_budget(self):
        style = {'version': result_presentation.VERSION, 'verbosity': 'uzun'}
        text = 'y ' * 4000
        self.assertGreater(len(result_presentation.preview(text, style)), contract.PREVIEW_CHARS['uzun'])

    def test_style_validation_uses_the_contract_vocabulary(self):
        for value in contract.PREFERENCES['verbosity']:
            result_presentation.validate_style({'version': result_presentation.VERSION, 'verbosity': value})
        with self.assertRaises(ValueError):
            result_presentation.validate_style({'version': result_presentation.VERSION, 'verbosity': 'dev'})

    def test_preview_limit_inputs_are_validated(self):
        for normal in (0, -5, None, '1200', 12.5):
            with self.assertRaises(ValueError):
                contract.preview_limit('orta', normal)
        with self.assertRaises(ValueError):
            contract.preview_limit('dev', 1200)


class VocabularyCompletenessTests(unittest.TestCase):
    def test_style_table_covers_every_value_and_nothing_else(self):
        self.assertEqual(set(contract.STYLE), set(contract.PREFERENCES) - {'verbosity', 'notification'})
        for key in contract.STYLE:
            self.assertEqual(set(contract.STYLE[key]), set(contract.PREFERENCES[key]), key)
        self.assertEqual(set(contract.NOTIFICATION), set(contract.PREFERENCES['notification']))
        self.assertEqual(set(contract.DELIVERY_OF), set(contract.CHANNELS))

    def test_unknown_lookups_fail_closed(self):
        with self.assertRaises(ValueError):
            contract.style_sentence('formality', 'resmiyetli')
        with self.assertRaises(ValueError):
            contract.style_sentence('renk', 'nötr')
        with self.assertRaises(ValueError):
            contract.delivery('radyo')
        with self.assertRaises(ValueError):
            contract.notation(4)

    def test_no_module_restates_the_owned_sentences(self):
        offenders = []
        for path in sorted(MODULES_DIR.glob('*.py')):
            if path.name in ('persona.py', 'persona_contract.py'):
                continue
            text = path.read_text(encoding='utf-8')
            offenders += [f'{path.name}:{owned}' for owned in OWNED if owned in text]
        self.assertEqual(offenders, [])

    def test_surfaces_compose_instead_of_renaming_the_owner(self):
        for name in ('main_planner.py', 'worktrack.py', 'main_documents.py', 'study.py', 'personalization.py'):
            self.assertIn('persona.prompt(', source(name), name)

    def test_photo_and_brief_do_not_import_a_second_persona_module(self):
        for name in ('main_documents.py', 'main_planner.py', 'worktrack.py', 'study.py'):
            self.assertNotIn('persona_contract', source(name), name)


if __name__ == '__main__':
    unittest.main()
