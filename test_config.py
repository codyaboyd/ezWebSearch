from __future__ import annotations

import unittest

from config import DEFAULT_API_PORT, DEFAULT_SEARXNG_URL, Settings


class SettingsTests(unittest.TestCase):
    def test_defaults_match_the_two_service_ports(self) -> None:
        settings = Settings.from_env({})

        self.assertEqual(settings.searxng_url, DEFAULT_SEARXNG_URL)
        self.assertEqual(settings.port, DEFAULT_API_PORT)

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

    def test_blank_searxng_url_uses_the_compose_default(self) -> None:
        self.assertEqual(
            Settings.from_env({"SEARXNG_URL": ""}).searxng_url,
            DEFAULT_SEARXNG_URL,
        )
        self.assertEqual(
            Settings.from_env({"SEARXNG_URL": "   "}).searxng_url,
            DEFAULT_SEARXNG_URL,
        )

    def test_invalid_values_have_actionable_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTP_CONCURRENCY"):
            Settings.from_env({"HTTP_CONCURRENCY": "many"})

        with self.assertRaisesRegex(ValueError, "ALLOW_PRIVATE_URLS"):
            Settings.from_env({"ALLOW_PRIVATE_URLS": "maybe"})

        with self.assertRaisesRegex(ValueError, "SEARXNG_URL"):
            Settings.from_env({"SEARXNG_URL": "not-a-url"})


if __name__ == "__main__":
    unittest.main()
