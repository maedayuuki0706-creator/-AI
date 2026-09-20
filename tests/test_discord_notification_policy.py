import json
import os
import unittest
from unittest.mock import patch

import detailed_discord_notify as selected
import direct_discord_notify as main
import hit_alerts
import opportunity_alerts as opportunities
import send_opportunity_daily_discord as mid_reports
from discord_notification_policy import message_payload


class DiscordNotificationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.webhooks = {
            name: "https://example.test/api/webhooks/" + name
            for name in (
                "DISCORD_WEBHOOK_URL", "DISCORD_SELECTED_WEBHOOK_URL",
                "DISCORD_HIT_WEBHOOK_URL", "DISCORD_WEBHOOK_MID_ODDS",
                "DISCORD_WEBHOOK_MID_ODDS_SELECTED", "DISCORD_WEBHOOK_LONGSHOT",
            )
        }
        env = patch.dict(os.environ, self.webhooks, clear=True)
        env.start()
        self.addCleanup(env.stop)
        http = patch("urllib.request.urlopen")
        self.http = http.start()
        self.addCleanup(http.stop)
        self.http.return_value.__enter__.return_value.status = 204

    def check_delivery(self, env_name, content, *, notify):
        self.http.assert_called_once()
        request = self.http.call_args.args[0]
        self.assertEqual(request.full_url, self.webhooks[env_name])
        payload = json.loads(request.data)
        self.assertEqual(payload["content"], "@everyone\n" + content if notify else content)
        self.assertEqual(payload["allowed_mentions"], {"parse": ["everyone"] if notify else []})
        self.assertEqual(payload["flags"], 0 if notify else 4096)
        self.http.reset_mock()

    def test_main_prediction_is_silent_even_if_content_contains_mentions(self):
        content = "メイン予想 @everyone @here <@123> <@&456>"
        main.send_discord(content)
        self.check_delivery("DISCORD_WEBHOOK_URL", content, notify=False)

    def test_mid_and_longshot_predictions_are_silent(self):
        for name in ("DISCORD_WEBHOOK_MID_ODDS", "DISCORD_WEBHOOK_LONGSHOT"):
            with self.subTest(channel=name):
                opportunities._send(name, "予想の買い目")
                self.check_delivery(name, "予想の買い目", notify=False)

    def test_selected_predictions_ping_everyone_and_next_main_stays_silent(self):
        selected._send_selected_discord("厳選予想")
        self.check_delivery("DISCORD_SELECTED_WEBHOOK_URL", "厳選予想", notify=True)
        self.assertEqual(os.environ["DISCORD_WEBHOOK_URL"], self.webhooks["DISCORD_WEBHOOK_URL"])
        main.send_discord("次のメイン予想")
        self.check_delivery("DISCORD_WEBHOOK_URL", "次のメイン予想", notify=False)

    def test_selected_mid_predictions_ping_everyone(self):
        opportunities._send("DISCORD_WEBHOOK_MID_ODDS_SELECTED", "厳選中穴予想")
        self.check_delivery("DISCORD_WEBHOOK_MID_ODDS_SELECTED", "厳選中穴予想", notify=True)

    def test_hit_alerts_ping_everyone_and_next_main_stays_silent(self):
        hit_alerts._send_hit_channel("速報くん 的中速報")
        self.check_delivery("DISCORD_HIT_WEBHOOK_URL", "速報くん 的中速報", notify=True)
        self.assertEqual(os.environ["DISCORD_WEBHOOK_URL"], self.webhooks["DISCORD_WEBHOOK_URL"])
        main.send_discord("次のメイン予想")
        self.check_delivery("DISCORD_WEBHOOK_URL", "次のメイン予想", notify=False)

    def test_mid_channel_daily_report_is_also_silent(self):
        with patch.object(mid_reports.time, "sleep"):
            mid_reports.post_discord("中穴の日報")
        self.check_delivery("DISCORD_WEBHOOK_MID_ODDS", "中穴の日報", notify=False)

    def test_failed_alert_restores_main_destination(self):
        for sender in (selected._send_selected_discord, hit_alerts._send_hit_channel):
            with self.subTest(sender=sender.__name__):
                self.http.side_effect = TimeoutError()
                with self.assertRaises(TimeoutError):
                    sender("速報")
                self.assertEqual(os.environ["DISCORD_WEBHOOK_URL"], self.webhooks["DISCORD_WEBHOOK_URL"])
        self.http.side_effect = None

    def test_existing_prefix_is_not_duplicated(self):
        content = "@everyone\n厳選予想"
        self.assertEqual(message_payload(content, notify_everyone=True)["content"], content)


if __name__ == "__main__":
    unittest.main()
