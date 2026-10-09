"""Bound the Yuuki exhibition refresh and keep strict no-send checks."""
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import prototype3_delivery as yuuki

JST = ZoneInfo('Asia/Tokyo')


class YuukiLateExhibitionRetryTests(unittest.TestCase):
    def test_late_transient_incomplete_preview_is_retried_once(self):
        early = {'preview': {'exhibition_count': 0}}
        ready = {'preview': {'exhibition_count': 6}}
        current = datetime(2026, 10, 9, 9, 45, tzinfo=JST)
        with patch.object(yuuki, 'now_jst', return_value=current), \
             patch.object(yuuki.base, 'analyze_official', side_effect=[early, ready]) as analyze, \
             patch.object(yuuki.base, 'fetch') as fetch:
            self.assertIs(yuuki._official_with_late_exhibition_retry('20261009', '23', 3, '09:48'), ready)
            self.assertEqual(analyze.call_count, 2)
            fetch.cache_clear.assert_called_once()

    def test_do_not_double_request_when_exhibition_not_due_soon(self):
        unready = {'preview': {'exhibition_count': 4}}
        current = datetime(2026, 10, 9, 9, 30, tzinfo=JST)
        with patch.object(yuuki, 'now_jst', return_value=current), \
             patch.object(yuuki.base, 'analyze_official', return_value=unready) as analyze, \
             patch.object(yuuki.base, 'fetch') as fetch:
            result = yuuki._official_with_late_exhibition_retry('20261009', '23', 3, '09:48')
            self.assertIs(result, unready)
            analyze.assert_called_once()
            fetch.cache_clear.assert_not_called()

    def test_still_waits_if_refreshed_preview_is_incomplete(self):
        incomplete = {'preview': {'exhibition_count': 3}}
        current = datetime(2026, 10, 9, 9, 45, tzinfo=JST)
        with patch.object(yuuki, 'now_jst', return_value=current), \
             patch.object(yuuki.base, 'analyze_official', return_value=incomplete) as analyze, \
             patch.object(yuuki.base, 'fetch') as fetch:
            record, state = yuuki.build_record('20261009', '23', 3, '09:48')
            self.assertIsNone(record)
            self.assertEqual(state, 'waiting_for_exhibition')
            self.assertEqual(analyze.call_count, 2)
            fetch.cache_clear.assert_called_once()

    def test_expired_race_does_not_retry(self):
        incomplete = {'preview': {'exhibition_count': 0}}
        current = datetime(2026, 10, 9, 9, 49, tzinfo=JST)
        with patch.object(yuuki, 'now_jst', return_value=current), \
             patch.object(yuuki.base, 'analyze_official', return_value=incomplete) as analyze, \
             patch.object(yuuki.base, 'fetch') as fetch:
            self.assertIs(yuuki._official_with_late_exhibition_retry('20261009', '23', 3, '09:48'), incomplete)
            analyze.assert_called_once()
            fetch.cache_clear.assert_not_called()


if __name__ == '__main__':
    unittest.main()
