from datetime import datetime
from unittest.mock import Mock
import unittest
from zoneinfo import ZoneInfo

import fusion_shadow_wakeup as wake

NOW=datetime(2026,10,13,12,tzinfo=ZoneInfo('Asia/Tokyo'))


class IndependentWakeTests(unittest.TestCase):
    def test_only_research_workflow_and_branch_are_addressed(self):
        api=Mock(side_effect=[{'id':123,'state':'active'},{'workflow_runs':[]},{}])
        self.assertEqual(wake.wake(api=api,now=NOW)['status'],'requested')
        self.assertEqual(api.call_args.args,('/actions/workflows/123/dispatches',{'ref':wake.CODE_BRANCH}))
        self.assertTrue(all('discord' not in str(c) and 'x-delivery' not in str(c) for c in api.call_args_list))

    def test_active_run_is_never_restarted_or_cancelled(self):
        api=Mock(side_effect=[{'id':123,'state':'active'}, {'workflow_runs':[{'id':2,'status':'in_progress'}]}])
        self.assertEqual(wake.wake(api=api,now=NOW,current_run_id='1')['status'],'already_active')
        self.assertEqual(api.call_count,2)

    def test_disabled_workflow_and_non_research_branches_never_dispatch(self):
        api=Mock(return_value={'state':'disabled_manually'})
        self.assertEqual(wake.wake(api=api,now=NOW)['status'],'disabled_by_owner')
        self.assertEqual(api.call_count,1)
        with self.assertRaises(ValueError):wake.wake(api=api,now=NOW,branch='main')

    def test_ambiguous_dispatch_is_never_retried(self):
        api=Mock(side_effect=[{'id':123,'state':'active'},{'workflow_runs':[]},TimeoutError()])
        with self.assertRaises(TimeoutError):wake.wake(api=api,now=NOW)
        self.assertEqual(api.call_count,3)

    def test_overnight_relay_preserves_next_morning_bootstrap_without_forecast_calls(self):
        api=Mock(side_effect=[{'id':123,'state':'active'},{'workflow_runs':[]},{}])
        report=wake.wake(api=api,now=NOW.replace(hour=2))
        self.assertEqual(report['phase'],'overnight_relay_no_forecast')
        self.assertEqual(api.call_args.args[1],{'ref':wake.CODE_BRANCH})


if __name__ == '__main__':
    unittest.main()
