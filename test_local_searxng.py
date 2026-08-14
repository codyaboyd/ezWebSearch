from __future__ import annotations

import unittest
import shutil
from unittest.mock import patch

import local_searxng
from local_searxng import LocalSearXNG


class LocalSearXNGTests(unittest.TestCase):
    def test_free_port_is_a_valid_local_tcp_port(self) -> None:
        port = LocalSearXNG._find_free_port()
        self.assertGreaterEqual(port, 1)
        self.assertLessEqual(port, 65535)

    def test_missing_searxng_has_a_useful_error(self) -> None:
        instance = LocalSearXNG()
        instance._thread_error = ModuleNotFoundError(
            "No module named 'searx'",
            name="searx",
        )

        error = instance._startup_error()

        self.assertIsNotNone(error)
        self.assertIn("install SearXNG", str(error))

    def test_auto_backend_uses_docker_when_python_searxng_is_missing(self) -> None:
        instance = LocalSearXNG()

        with patch.object(local_searxng.importlib.util, "find_spec", return_value=None):
            self.assertEqual(instance._selected_backend(), "docker")

    def test_docker_settings_bind_inside_container(self) -> None:
        instance = LocalSearXNG()
        settings_path = instance._write_settings(
            LocalSearXNG.DOCKER_PORT,
            host=LocalSearXNG.DOCKER_HOST,
        )

        try:
            settings = settings_path.read_text(encoding="utf-8")
        finally:
            # close() also removes the temporary config directory, without
            # needing an event loop for this synchronous setup assertion.
            if instance._config_dir is not None:
                shutil.rmtree(instance._config_dir, ignore_errors=True)

        self.assertIn("bind_address: \"0.0.0.0\"", settings)
        self.assertIn("port: 8080", settings)


if __name__ == "__main__":
    unittest.main()
