from __future__ import annotations

import unittest

from local_searxng import LocalSearXNG


class LocalSearXNGTests(unittest.TestCase):
    def test_port_parser_accepts_docker_port_output(self) -> None:
        self.assertEqual(
            LocalSearXNG._port_from_output("127.0.0.1:32768"),
            32768,
        )

    def test_port_parser_rejects_missing_port(self) -> None:
        with self.assertRaises(RuntimeError):
            LocalSearXNG._port_from_output("")


if __name__ == "__main__":
    unittest.main()
