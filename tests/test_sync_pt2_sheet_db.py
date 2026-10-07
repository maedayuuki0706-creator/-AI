import unittest

import sync_pt2_sheet_db as sync


class PT2SheetDbSyncTests(unittest.TestCase):
    def test_player_parser_keeps_course_and_method_percentages(self):
        headers = [
            "登録番号","選手名","級別","支部","勝率","1コース1着率","逃げ率","差し率",
            "まくり率","まくり差し率","2コース1着率","3コース1着率","4コース1着率",
            "5コース1着率","6コース1着率","平均ST","元A級","得意決まり手","総合評価",
            "モーター整備力","ペラ調整力","弱機立て直し力","弱機立て直しサンプル数",
            "整備改善値","ペラ改善値","整備サンプル数","ペラサンプル数","最新調整コメント","メモ",
        ]
        row = [
            "4238","毒島 誠","A1","群馬","8.24","86.5%","60.0%","14.3%","5.7%",
            "14.3%","41.2%","52.4%","14.3%","23.1%","0.0%","0.15","","","A",
            "4.0","4.5","3.5","2","0.12","0.08","3","4","伸び寄り","test",
        ]
        players = sync._parse_players([headers, row])
        p = players["4238"]
        self.assertEqual(p["course_win"], [86.5, 41.2, 52.4, 14.3, 23.1, 0.0])
        self.assertEqual(p["escape"], 60.0)
        self.assertEqual(p["maintenance_grade"], 4.0)

    def test_motor_parser_keys_by_venue_and_motor(self):
        headers = list(sync.MOTOR_HEADERS.keys())
        row = [
            "24","大村","11","2026/05/24","2026/10/07","3.71","13.8%","28.8%",
            "5","6","12","80","0","0","1'51\"1","D","C","B","A","B","B",
            "選手A","リング","memo",
        ]
        motors = sync._parse_motors([headers, row])
        self.assertIn("24:11", motors)
        self.assertEqual(motors["24:11"]["top2"], 13.8)
        self.assertEqual(motors["24:11"]["stretch"], "A")

    def test_venue_parser_keeps_first_canonical_duplicate(self):
        headers = list(sync.VENUE_HEADERS.keys())
        canonical = [
            "24","大村","海水","あり","58.0%","13.7%","11.4%","9.9%","6.1%","1.5%",
            "55.1%","12.8%","14.1%","12.2%","42.0%","中","1C優勢","canonical",
        ]
        auxiliary = [
            "24","大村","下げ潮","0","","","","","","",
            "","","","","","","","auxiliary",
        ]
        venues = sync._parse_venues([headers, canonical, auxiliary])
        self.assertEqual(venues["24"]["water"], "海水")
        self.assertEqual(venues["24"]["course_win"][0], 58.0)
        self.assertEqual(venues["24"]["escape"], 55.1)
        self.assertEqual(venues["24"]["volatility"], 42.0)

    def test_venue_parser_uses_two_digit_codes(self):
        headers = list(sync.VENUE_HEADERS.keys())
        row = [
            "3","江戸川","汽水","あり","48.8%","17.0%","12.7%","12.0%","8.2%","2.8%",
            "43.5%","18.7%","13.9%","12.1%","51.2%","最強","河川水面","memo",
        ]
        venues = sync._parse_venues([headers, row])
        self.assertIn("03", venues)
        self.assertEqual(venues["03"]["course_win"][0], 48.8)
        self.assertEqual(venues["03"]["volatility"], 51.2)


if __name__ == "__main__":
    unittest.main()
