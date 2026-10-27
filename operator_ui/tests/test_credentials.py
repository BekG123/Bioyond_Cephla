"""Credential persistence without real credentials, network, or robot access."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from credential_store import CredentialStore, CredentialError
from plate_agent import VisionClient, AgentError, PlateAgent


class CredentialsTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_encrypted_roundtrip_across_clients_and_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'key.dpapi'
            first = VisionClient(store=CredentialStore(path))
            first.set_key('test-only-haiku-secret')
            self.assertNotIn(b'test-only-haiku-secret', path.read_bytes())
            restored = VisionClient(store=CredentialStore(path))
            self.assertEqual(restored.key, 'test-only-haiku-secret')
            restored.set_key('replacement-test-secret')
            self.assertEqual(VisionClient(store=CredentialStore(path)).key, 'replacement-test-secret')
            self.assertEqual(list(Path(folder).iterdir()), [path])

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_corrupt_store_does_not_crash_startup_or_leak_contents(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            path = Path(folder) / 'key.dpapi'
            path.write_bytes(b'private-corrupt-data')
            client = VisionClient(store=CredentialStore(path))
            self.assertFalse(client.ready())
            self.assertTrue(client.credential_error)
            self.assertNotIn('private-corrupt-data', client.credential_error)

    def test_failed_save_preserves_existing_key(self):
        store = Mock()
        store.load.return_value = 'existing-test-key'
        store.save.side_effect = CredentialError('Cannot securely save the Haiku key.')
        client = VisionClient(store=store)
        with self.assertRaises(AgentError):
            client.set_key('replacement-test-key')
        self.assertEqual(client.key, 'existing-test-key')

    def test_invalid_key_never_persists_and_public_state_has_no_secret(self):
        store = Mock()
        store.load.return_value = 'private-test-key'
        client = VisionClient(store=store)
        with self.assertRaises(AgentError):
            client.set_key('short')
        store.save.assert_not_called()
        agent = PlateAgent(client=client, depth=Mock(public=lambda: {}))
        self.assertNotIn('private-test-key', str(agent.public()))

    def test_environment_fallback(self):
        store = Mock()
        store.load.return_value = ''
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'environment-test-key'}):
            self.assertTrue(VisionClient(store=store).ready())

    def test_plaintext_linux_backend_is_rejected(self):
        keyring = Mock()
        keyring.get_keyring.return_value = object()
        with patch.dict(sys.modules, {'keyring': keyring}):
            with self.assertRaises(CredentialError):
                CredentialStore._keyring()
        keyring.set_password.assert_not_called()


if __name__ == '__main__':
    unittest.main()
