import unittest

from turn_tactics import turn_tactics_answer


class TurnTacticsTest(unittest.TestCase):
    def test_term_explanation_has_conditions_and_uncertainty(self):
        answer = turn_tactics_answer("ツケマイって何？")
        self.assertIn("まくりの一種", answer)
        self.assertIn("起こる条件", answer)
        self.assertIn("舟券で見る所", answer)

    def test_sakimai_does_not_guarantee_win(self):
        answer = turn_tactics_answer("2号艇が先マイしたらどうなる？")
        self.assertIn("2号艇", answer)
        self.assertIn("先マイ＝1着確定ではない", answer)
        self.assertIn("3号艇", answer)

    def test_following_boat_after_tsukemai(self):
        answer = turn_tactics_answer("3がツケマイ行ったら4はどうなる？")
        self.assertIn("4号艇", answer)
        self.assertIn("艇間が開けば", answer)
        self.assertIn("着順は決め打ちしない", answer)

    def test_compound_development_question(self):
        answer = turn_tactics_answer("1がターン流れた時、2の差しと3のまくり差しどっちが入りやすい？")
        self.assertIn("艇間", answer)
        self.assertIn("断定できない", answer)

    def test_unrelated_live_statistics_remain_unhandled(self):
        self.assertIsNone(turn_tactics_answer("今の常滑の的中率は？"))

    def test_comparison(self):
        answer = turn_tactics_answer("先マイとツケマイの違いは？")
        self.assertIn("順番", answer)
        self.assertIn("攻め方", answer)


if __name__ == "__main__":
    unittest.main()
