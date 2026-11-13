"""Offline TCP protocol checks; never contact the lab scanner."""
import contextlib
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from barcode_scanner_cli import main, scan_once


class FakeScanner:
    def __init__(self, replies):
        self.replies = replies
        self.commands = []
        self.errors = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen()
        self.listener.settimeout(3)
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def serve(self):
        try:
            for reply in self.replies:
                connection, _ = self.listener.accept()
                with connection:
                    connection.settimeout(3)
                    self.commands.append(self.read_exact(connection, 5))
                    for chunk in reply:
                        connection.sendall(chunk)
                        time.sleep(0.01)
                    self.commands.append(self.read_exact(connection, 4))
        except Exception as error:
            self.errors.append(error)
        finally:
            self.listener.close()

    @staticmethod
    def read_exact(connection, length):
        data = b""
        while len(data) < length:
            chunk = connection.recv(length - len(data))
            if not chunk:
                break
            data += chunk
        return data

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.thread.join(4)
        if self.thread.is_alive():
            raise AssertionError("Fake scanner did not finish")
        if self.errors:
            raise self.errors[0]


class ScannerCliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict('os.environ', BIOYOND_PLATE_DB=str(Path(directory.name)/'plates.sqlite3'))
        env.start()
        self.addCleanup(env.stop)

    def test_fragmented_utf8_frame_and_receipt(self):
        with tempfile.TemporaryDirectory() as directory, FakeScanner(
                [[b" QR-\xc3", b"\xa9 ", b"\x04"]]) as scanner:
            result, path = scan_once("127.0.0.1", scanner.port, None, 1, directory)
            self.assertEqual(result["result"], "decoded")
            self.assertEqual(result["barcode"], " QR-\u00e9 ")
            self.assertEqual(json.loads(path.read_text())["barcode"], " QR-\u00e9 ")
            self.assertTrue(result['plate_registry']['saved'])
            from plate_registry import PlateRegistry
            self.assertEqual(PlateRegistry().get(' QR-\u00e9 ')['scan_count'], 1)
            PlateRegistry().record_scan(json.loads(path.read_text()), str(path))
            self.assertEqual(PlateRegistry().get(' QR-\u00e9 ')['scan_count'], 1)
        self.assertEqual(scanner.commands, [b"start", b"stop"])

    def test_no_read_then_decode_in_count_mode(self):
        with tempfile.TemporaryDirectory() as directory, FakeScanner(
                [[b"NG\x04"], [b"plate-123\x04"]]) as scanner:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = main(["--host", "127.0.0.1", "--port", str(scanner.port),
                             "--source-ip", "auto", "--count", "2", "--interval", ".01",
                             "--log-dir", directory])
            self.assertEqual(code, 0)
            self.assertIn("NO_READ", output.getvalue())
            self.assertIn('"plate-123"', output.getvalue())
            self.assertEqual(len(list(Path(directory).glob("*.json"))), 2)
        self.assertEqual(scanner.commands, [b"start", b"stop"] * 2)

    def test_partial_frame_times_out_without_next_scan(self):
        with tempfile.TemporaryDirectory() as directory, FakeScanner([[b"partial"]]) as scanner:
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--host", "127.0.0.1", "--port", str(scanner.port),
                             "--source-ip", "auto", "--count", "3", "--timeout", ".1",
                             "--log-dir", directory])
            receipts = list(Path(directory).glob("*.json"))
            self.assertEqual(code, 2)
            self.assertEqual(len(receipts), 1)
            record = json.loads(receipts[0].read_text())
            self.assertEqual(record["result"], "timeout")
            self.assertIsNone(record["barcode"])
            self.assertEqual(record["response_hex"], b"partial".hex())
        self.assertEqual(scanner.commands, [b"start", b"stop"])

    def test_invalid_arguments_fail_before_scanning(self):
        for arguments in (["--timeout", "nan"], ["--count", "0"],
                          ["--port", "65536"], ["--continuous", "--interactive"]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(arguments)
                self.assertEqual(error.exception.code, 2)

    def test_invalid_utf8_is_not_a_plate_id(self):
        with tempfile.TemporaryDirectory() as directory, FakeScanner([[b'\xff\x04']]) as scanner:
            result, _ = scan_once('127.0.0.1', scanner.port, None, 1, directory)
            self.assertEqual(result['result'], 'error')
            self.assertIsNone(result['barcode'])
            self.assertNotIn('plate_registry', result)

    def test_database_failure_is_visible_without_losing_receipt(self):
        with tempfile.TemporaryDirectory() as directory, FakeScanner([[b'001\x04']]) as scanner:
            with patch('plate_registry.PlateRegistry.record_scan', side_effect=OSError('disk unavailable')):
                result, path = scan_once('127.0.0.1', scanner.port, None, 1, directory)
            self.assertEqual(result['barcode'], '001')
            self.assertFalse(result['plate_registry']['saved'])
            self.assertEqual(json.loads(path.read_text())['barcode'], '001')


if __name__ == "__main__":
    unittest.main()
