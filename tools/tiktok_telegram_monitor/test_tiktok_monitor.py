import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tiktok_monitor


class FakeVideo:
    def __init__(self, identifier, timestamp=0, username="bruger", text="tekst"):
        self.id = identifier
        self.as_dict = {
            "id": identifier,
            "createTime": timestamp,
            "author": {"uniqueId": username},
            "desc": text,
        }


class FakeSearch:
    def __init__(self, videos):
        self.results = videos
        self.arguments = None

    async def search_type(self, search_term, object_type, count):
        self.arguments = (search_term, object_type, count)
        for video in self.results:
            yield video


class MonitorTests(unittest.TestCase):
    def settings(self, path):
        return tiktok_monitor.Settings("bot", "chat", "ms", state_file=path)

    def test_first_check_only_creates_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            search = FakeSearch([FakeVideo("2"), FakeVideo("1")])
            with patch.object(tiktok_monitor, "send_telegram_message") as send:
                sent = asyncio.run(tiktok_monitor.check_once(search, self.settings(state)))

            self.assertEqual(sent, 0)
            self.assertEqual(json.loads(state.read_text()), ["2", "1"])
            self.assertEqual(search.arguments, ("Vollsmose", "item", 30))
            send.assert_not_called()

    def test_new_videos_are_sent_oldest_first_and_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text('["old"]')
            search = FakeSearch(
                [FakeVideo("newer", 20), FakeVideo("old", 1), FakeVideo("new", 10)]
            )
            with patch.object(tiktok_monitor, "send_telegram_message") as send:
                sent = asyncio.run(tiktok_monitor.check_once(search, self.settings(state)))

            self.assertEqual(sent, 2)
            self.assertIn("/video/new", send.call_args_list[0].args[2])
            self.assertIn("/video/newer", send.call_args_list[1].args[2])
            self.assertEqual(json.loads(state.read_text()), ["old", "new", "newer"])

    def test_settings_reject_placeholder_credentials(self):
        settings = tiktok_monitor.Settings(
            "INDSAET_TELEGRAM_BOT_TOKEN", "chat", "ms"
        )
        with self.assertRaisesRegex(ValueError, "TELEGRAM_BOT_TOKEN"):
            settings.validate()

    def test_invalid_state_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text("{}")
            with self.assertRaisesRegex(RuntimeError, "ugyldigt format"):
                tiktok_monitor.load_seen_ids(state)

    def test_dependency_installer_uses_pinned_package_and_chromium(self):
        with patch.object(tiktok_monitor.subprocess, "run") as run:
            tiktok_monitor.install_dependencies()

        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[0].args[0],
            [
                tiktok_monitor.sys.executable,
                "-m",
                "pip",
                "install",
                "TikTokApi==7.1.0",
            ],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            [tiktok_monitor.sys.executable, "-m", "playwright", "install", "chromium"],
        )


if __name__ == "__main__":
    unittest.main()
