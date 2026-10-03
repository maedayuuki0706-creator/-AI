import unittest
from unittest.mock import patch
import sokuhou_runner as runner


class SokuhouRunnerTests(unittest.TestCase):
    def test_main_failure_does_not_skip_yuuki_persistence_or_audit(self):
        with patch.object(runner.sokuhou_delivery, 'paused', return_value=False), \
             patch.object(runner.sokuhou_character, 'install'), \
             patch.object(runner.hit_alerts_fast, 'check_and_send', side_effect=RuntimeError()), \
             patch.object(runner.yuuki_hit_alerts, 'run', return_value=1) as yuuki, \
             patch.object(runner.persist_runtime_data, 'persist') as persist, \
             patch.object(runner.sokuhou_health, 'audit', return_value=0) as audit, \
             patch.object(runner, 'print', create=True):
            self.assertEqual(runner.run(),1)
        yuuki.assert_called_once()
        persist.assert_called_once()
        audit.assert_called_once()

    def test_pause_does_not_send_or_change_receipts(self):
        with patch.object(runner.sokuhou_delivery, 'paused', return_value=True), \
             patch.object(runner.hit_alerts_fast, 'check_and_send') as main, \
             patch.object(runner.yuuki_hit_alerts, 'run') as yuuki, \
             patch.object(runner.persist_runtime_data, 'persist') as persist, \
             patch.object(runner, 'print', create=True):
            self.assertEqual(runner.run(),0)
        main.assert_not_called()
        yuuki.assert_not_called()
        persist.assert_not_called()
