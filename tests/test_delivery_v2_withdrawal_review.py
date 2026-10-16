import copy
import unittest

from delivery_v2.withdrawal_review import result_evidence, review_missed

KEY = 'yuuki:20261013:14:8:final'
URL = 'https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20261013&jcd=14&rno=8'


def table(withdrawal=True):
    head = '<table><thead><tr>' + ''.join('<th>'+x+'</th>' for x in
        ['着', '枠', 'ボートレーサー', 'レースタイム']) + '</tr></thead>'
    return head + ''.join('<tr><td>'+('欠' if i == 3 and withdrawal else str(i))+
        '</td><td>'+str(i)+'</td><td>fixture</td><td></td></tr>' for i in range(1,7))+'</table>'


class WithdrawalReviewTests(unittest.TestCase):
    def setUp(self):
        self.evidence = result_evidence(KEY, URL, table(), reviewed_at='2026-10-13T13:00:00+09:00')
        self.row = {'key': KEY, 'status': 'missed', 'message_id': None,
                    'attempt': 0, 'delivery_status': 'missing'}
        self.report = {'status': 'degraded', 'counts': {'sent':139,'missed':1},
                       'active_missed': [self.row], 'production_verification': [{'message_id':'123'}]}

    def test_review_keeps_failure_counts_and_confirmed_ids_and_input_unchanged(self):
        before = copy.deepcopy(self.report)
        result = review_missed(self.report, {KEY: self.evidence})
        self.assertEqual(self.report, before)
        for field in self.report:
            self.assertEqual(result[field], self.report[field])
        self.assertEqual(result['withdrawal_review']['reviewed'][0]['withdrawal_lanes'],[3])
        self.assertIsNone(result['withdrawal_review']['reviewed'][0]['known_before_deadline'])

    def test_ordinary_missing_stays_unresolved(self):
        self.assertEqual(review_missed(self.report,{})['withdrawal_review']['unresolved'],[KEY])

    def test_five_boats_or_historical_withdrawal_is_not_evidence(self):
        for raw in [table().replace('<tr><td>6</td><td>6</td><td>fixture</td><td></td></tr>',''),
                    table(False)+'<table><tr><td>欠</td><td>3</td></tr></table>']:
            with self.assertRaises(ValueError):
                result_evidence(KEY,URL,raw,reviewed_at='2026-10-13T13:00:00+09:00')

    def test_wrong_race_or_nonofficial_host_fails(self):
        for url in [URL.replace('rno=8','rno=9'),URL.replace('www.boatrace.jp','example.com')]:
            with self.assertRaises(ValueError):
                result_evidence(KEY,url,table(),reviewed_at='2026-10-13T13:00:00+09:00')

    def test_tampered_rows_fail_closed(self):
        self.evidence['result_rows'][0]['finish']='欠'
        with self.assertRaises(ValueError):
            review_missed(self.report,{KEY:self.evidence})

    def test_changed_source_is_revalidated_when_reading_saved_evidence(self):
        self.evidence['source_url']=URL.replace('rno=8','rno=9')
        with self.assertRaises(ValueError):
            review_missed(self.report,{KEY:self.evidence})

    def test_attempted_or_confirmed_delivery_is_never_excluded(self):
        for change in [{'message_id':'123'},{'attempt':1},{'status':'uncertain'}]:
            self.report['active_missed']=[{**self.row,**change}]
            result=review_missed(self.report,{KEY:self.evidence})
            self.assertEqual(result['withdrawal_review']['reviewed'],[])
            self.assertEqual(result['withdrawal_review']['unresolved'],[KEY])


if __name__ == '__main__':
    unittest.main()
