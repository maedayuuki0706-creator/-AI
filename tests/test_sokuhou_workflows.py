"""Guard the exact production concurrency/persistence failure from this incident."""
from pathlib import Path
import unittest


class SokuhouWorkflowTests(unittest.TestCase):
    def test_notifier_concurrency_is_active_yaml_not_an_escaped_comment(self):
        text = Path('.github/workflows/discord_notify.yml').read_text()
        start = text.index('\nconcurrency:\n')
        end = text.index('\njobs:', start)
        block = text[start:end]
        self.assertNotIn('\\n', block)
        self.assertIn('\n  group: boat-ai-discord-notify-main\n', block)
        self.assertIn('\n  cancel-in-progress: false\n', block)
        self.assertNotIn('git pull --rebase', text)
        self.assertIn('python persist_runtime_data.py data/ --exclude data/x_post_delivery/', text)

    def test_yuuki_durable_writer_has_repository_token(self):
        text = Path('.github/workflows/prototype3-delivery.yml').read_text()
        step = text.split('name: Verify Sokuhou independent delivery is enabled')[1].split('      - name:')[0]
        self.assertIn('GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}', step)

    def test_independent_sender_is_serialized_and_main_defers_hit_delivery(self):
        text = Path('.github/workflows/sokuhou-delivery.yml').read_text()
        self.assertIn('group: sokuhou-confirmed-hit-delivery', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertIn('DISCORD_HIT_WEBHOOK_URL: ${{ secrets.DISCORD_HIT_WEBHOOK_URL }}', text)
        self.assertIn('python -u sokuhou_runner.py', text)
        self.assertIn("SOKUHOU_EXTERNAL_RUNNER: '1'", Path('.github/workflows/discord_notify.yml').read_text())


if __name__ == '__main__':
    unittest.main()
