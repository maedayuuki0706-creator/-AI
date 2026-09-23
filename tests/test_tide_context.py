import unittest
from datetime import datetime

import tide_context as t


class TideContextTests(unittest.TestCase):
    def setUp(self):
        t.clear_cache()

    def test_controlled_and_no_tide_pools_are_excluded(self):
        called = []
        def fetcher(url):
            called.append(url)
            raise AssertionError("excluded venue must not fetch tide data")

        for jcd in ("07", "08", "09"):
            out = t.get_tide_context("20260924", jcd, "15:00", fetcher=fetcher)
            self.assertFalse(out["applicable"])
            self.assertEqual(out["status"], "excluded_no_tidal_difference")
        self.assertEqual(called, [])

    def test_brackish_and_seawater_tidal_venues_are_enabled(self):
        self.assertTrue(t.venue_profile("06")["tide_enabled"])  # Hamanako, brackish
        self.assertTrue(t.venue_profile("20")["tide_enabled"])  # Wakamatsu, seawater
        self.assertTrue(t.venue_profile("24")["tide_enabled"])  # Omura, seawater

    def test_jma_parser_and_tide_phase(self):
        raw = """
        <table><tbody>
        <tr>
          <td>2026/09/24(木)</td><td></td>
          <td>07:00</td><td>200</td><td>20:00</td><td>190</td>
          <td>*</td><td>*</td><td>*</td><td>*</td>
          <td>01:00</td><td>50</td><td>14:00</td><td>40</td>
          <td>*</td><td>*</td><td>*</td><td>*</td>
        </tr>
        </tbody></table>
        """
        events = t.parse_jma_events(raw)
        self.assertEqual(len(events), 4)
        falling = t.context_from_events("20260924", "10:00", events)
        self.assertTrue(falling["available"])
        self.assertEqual(falling["phase"], "falling")
        self.assertGreater(falling["normalized_level"], 0.0)
        self.assertLess(falling["normalized_level"], 1.0)
        self.assertEqual(falling["previous_turn"]["kind"], "high")
        self.assertEqual(falling["next_turn"]["kind"], "low")

        rising = t.context_from_events("20260924", "17:00", events)
        self.assertEqual(rising["phase"], "rising")
        self.assertEqual(rising["previous_turn"]["kind"], "low")
        self.assertEqual(rising["next_turn"]["kind"], "high")

    def test_wakamatsu_official_parser_uses_local_heights(self):
        raw = """
        <table>
          <tr><td>2026/09/24</td><td>15:04</td><td>0.4m</td><td>21:05</td><td>1.31m</td></tr>
          <tr><td>2026/09/25</td><td>15:29</td><td>0.36m</td><td>21:30</td><td>1.41m</td></tr>
        </table>
        """
        events = t.parse_wakamatsu_events(raw)
        self.assertEqual([(x["kind"], x["time"].strftime("%H:%M")) for x in events[:2]],
                         [("low", "15:04"), ("high", "21:05")])
        out = t.context_from_events("20260924", "18:00", events)
        self.assertEqual(out["phase"], "rising")
        self.assertIsNotNone(out["estimated_level_cm"])
        self.assertAlmostEqual(out["tidal_range_cm"], 91.0, places=1)

    def test_omura_parser_preserves_local_high_low_times(self):
        raw = """
        <table>
          <tr><td>9月28日</td><td>初日</td><td>18:26</td><td>12:39</td><td>中潮</td></tr>
          <tr><td>9月29日</td><td>2日目</td><td>18:54</td><td>13:18</td><td>中潮</td></tr>
        </table>
        """
        events = t.parse_omura_events(raw, 2026)
        day = [x for x in events if x["time"].date() == datetime(2026, 9, 28).date()]
        self.assertEqual([(x["kind"], x["time"].strftime("%H:%M")) for x in day],
                         [("high", "12:39"), ("low", "18:26")])
        out = t.context_from_events("20260928", "16:00", events)
        self.assertEqual(out["phase"], "falling")
        self.assertIsNone(out["estimated_level_cm"])


if __name__ == "__main__":
    unittest.main()
