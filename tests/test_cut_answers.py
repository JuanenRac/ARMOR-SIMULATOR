# ARMOR-SIMULATOR - tests/test_cut_answers.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.
"""A server answer cut in the middle, and token files with a byte-order mark."""
from __future__ import annotations

import argparse
import http.client
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from armor_simulator import cli, publisher  # noqa: E402


class CutAnswerTests(unittest.TestCase):
    def test_a_cut_or_garbled_answer_is_a_delivery_error_after_the_retries(self) -> None:
        kind = next(iter(publisher.ROUTES))
        for broken in (http.client.IncompleteRead(b"{", 100), http.client.BadStatusLine("x")):
            with mock.patch.object(publisher, "urlopen", side_effect=broken) as opened:
                with self.assertRaises(publisher.DeliveryError):
                    publisher.post("http://127.0.0.1:1", "t", kind, {"node_id": "n"}, attempts=3, pause_s=0)
                self.assertEqual(opened.call_count, 3)

    def test_token_files_with_a_byte_order_mark_are_read(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_bytes(b"\xef\xbb\xbfARMOR_INGEST_TOKEN=abc\r\n")
            self.assertEqual(cli._token(argparse.Namespace(ingest_token=None, ingest_token_file=str(path))), "abc")
            path.write_bytes(b"\xef\xbb\xbfsecret\n")
            self.assertEqual(cli._first_line(argparse.ArgumentParser(), path, "NONE"), "secret")


if __name__ == "__main__":
    unittest.main()
