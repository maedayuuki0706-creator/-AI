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
        step = text.split('name: Notify 速報くん of confirmed ゆうき hits')[1].split('      - name:')[0]
        self.assertIn('GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}', step)


if __name__ == '__main__':
    unittest.main()
