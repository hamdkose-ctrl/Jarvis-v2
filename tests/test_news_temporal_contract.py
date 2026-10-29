"""User examples are contract boundaries, not publisher-specific exceptions."""
import unittest
from datetime import datetime,timezone,timedelta
from modules import news_temporal

TR=timezone(timedelta(hours=3))
NOW=datetime(2026,10,29,9,30,tzinfo=TR)

class TemporalRequestContract(unittest.TestCase):
    def test_breaking_is_one_hour(self):
        scope=news_temporal.request_scope('son dakika haberleri neler',now=NOW)
        self.assertEqual(scope['intent'],'publication_window')
        self.assertEqual(scope['start'],NOW-timedelta(hours=1))
        self.assertEqual(scope['end'],NOW)
    def test_explicit_hours_override_breaking_default(self):
        scope=news_temporal.request_scope('son 3 saatteki son dakika gelişmeleri',now=NOW)
        self.assertEqual(scope['start'],NOW-timedelta(hours=3))
    def test_today_uses_istanbul_midnight(self):
        scope=news_temporal.request_scope('bugünkü gelişmeleri araştır',now=NOW.astimezone(timezone.utc))
        self.assertEqual(scope['start'],NOW.replace(hour=0,minute=0))
        self.assertEqual(scope['end'],NOW)
    def test_morning_never_includes_future_hours(self):
        scope=news_temporal.request_scope('bu sabah neler oldu',now=NOW)
        self.assertLessEqual(scope['end'],NOW)
    def test_tomorrow_is_event_date_not_publication_filter(self):
        scope=news_temporal.request_scope('yarın okullar tatil olmuş doğru mu',now=NOW)
        self.assertEqual(scope['intent'],'event_verification')
        self.assertEqual(scope['event_date'],(NOW+timedelta(days=1)).date())
        self.assertIsNone(scope['start'])
    def test_hour_precision_requires_aware_publication_time(self):
        scope=news_temporal.request_scope('son dakika',now=NOW)
        with self.assertRaises(ValueError):news_temporal.check_publication({'published':'2026-10-29'},scope)
    def test_offset_comparison_and_boundary(self):
        scope=news_temporal.request_scope('son dakika',now=NOW)
        news_temporal.check_publication({'published':'2026-10-29','published_at':'2026-10-29T05:30:00+00:00'},scope)
        with self.assertRaises(ValueError):news_temporal.check_publication({'published':'2026-10-29','published_at':'2026-10-29T05:29:59+00:00'},scope)
    def test_future_publication_rejected(self):
        scope=news_temporal.request_scope('son dakika',now=NOW)
        with self.assertRaises(ValueError):news_temporal.check_publication({'published':'2026-10-29','published_at':'2026-10-29T09:31:00+03:00'},scope)

    def test_receipt_boundary_rechecks_precision(self):
        from modules import research_evidence
        with self.assertRaises(ValueError):
            research_evidence.news_date({'published':'2026-10-29'},'son dakika haberleri',now=NOW)
        research_evidence.news_date({'published':'2026-10-29','published_at':'2026-10-29T09:15:00+03:00'},'son dakika haberleri',now=NOW)
    def test_event_question_cannot_complete_from_publication_date(self):
        from modules import research_evidence
        with self.assertRaisesRegex(ValueError,'geçerlilik'):
            research_evidence.news_date({'published':'2026-10-28'},'yarın karar geçerli mi',now=NOW)

    def test_expired_receipt_rejected_on_resume(self):
        from modules import research_evidence
        article={'published':'2026-10-29','published_at':'2026-10-29T09:15:00+03:00'}
        research_evidence.news_date(article,'son dakika',now=NOW)
        with self.assertRaises(ValueError):
            research_evidence.news_date(article,'son dakika',now=NOW+timedelta(hours=1))
    def test_morning_after_noon_excludes_afternoon(self):
        scope=news_temporal.request_scope('bu sabah neler oldu',now=NOW.replace(hour=16))
        self.assertEqual(scope['end'],NOW.replace(hour=12,minute=0))
        with self.assertRaises(ValueError):
            news_temporal.check_publication({'published':'2026-10-29','published_at':'2026-10-29T13:00:00+03:00'},scope)
    def test_today_rejects_yesterday_even_with_seven_day_default(self):
        from modules import research_evidence
        with self.assertRaises(ValueError):
            research_evidence.news_date({'published':'2026-10-28'},'bugünkü haberler',now=NOW)
    def test_hour_without_zone_rejected(self):
        scope=news_temporal.request_scope('son dakika',now=NOW)
        with self.assertRaises(ValueError):
            news_temporal.check_publication({'published':'2026-10-29','published_at':'2026-10-29T09:15:00'},scope)

    def test_publication_offset_does_not_turn_today_into_yesterday(self):
        from modules import research_evidence
        reference=NOW.replace(hour=0,minute=30)
        article={'published':'2026-10-28','published_at':'2026-10-28T21:15:00+00:00'}
        research_evidence.news_date(article,'bugünkü haberler',now=reference)
    def test_midnight_breaking_window_accepts_previous_calendar_day(self):
        from modules import research_evidence
        reference=NOW.replace(hour=0,minute=15)
        article={'published':'2026-10-28','published_at':'2026-10-28T23:45:00+03:00'}
        research_evidence.news_date(article,'son dakika haberleri',now=reference)

    def test_tomorrow_stays_bound_to_original_request_after_midnight(self):
        scope=news_temporal.request_scope('yarın karar geçerli mi',now=NOW+timedelta(days=1),reference=NOW)
        self.assertEqual(scope['event_date'],(NOW+timedelta(days=1)).date())
    def test_publication_freshness_uses_resume_clock_not_original_clock(self):
        scope=news_temporal.request_scope('son dakika',now=NOW+timedelta(hours=2),reference=NOW)
        self.assertEqual(scope['start'],NOW+timedelta(hours=1))

    def test_event_with_news_word_not_publication_route(self):
        from modules import research_evidence
        self.assertTrue(research_evidence.news_requested('Yarın tatil haberi doğru mu?'))
        self.assertFalse(research_evidence.publication_news_requested('Yarın tatil haberi doğru mu?'))
        self.assertTrue(research_evidence.publication_news_requested('Son dakika haberleri'))
