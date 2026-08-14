from __future__ import annotations

import unittest

from config import Settings


class SettingsTests(unittest.TestCase):
    def test_from_env_normalizes_values_without_import_time_state(self) -> None:
        settings = Settings.from_env(
            {
                "SEARXNG_URL": " http://search.example/ ",
                "HTTP_CONCURRENCY": "4",
                "ALLOW_PRIVATE_URLS": "false",
                "PORT": "3100",
            }
        )

        self.assertEqual(settings.searxng_url, "http://search.example")
        self.assertEqual(settings.http_concurrency, 4)
        self.assertFalse(settings.allow_private_urls)
        self.assertEqual(settings.port, 3100)

    def test_blank_searxng_url_selects_automatic_provisioning(self) -> None:
        self.assertIsNone(Settings.from_env({"SEARXNG_URL": ""}).searxng_url)

    def test_invalid_values_have_actionable_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTP_CONCURRENCY"):
            Settings.from_env({"HTTP_CONCURRENCY": "many"})

        with self.assertRaisesRegex(ValueError, "ALLOW_PRIVATE_URLS"):
            Settings.from_env({"ALLOW_PRIVATE_URLS": "maybe"})


if __name__ == "__main__":
    unittest.main()
