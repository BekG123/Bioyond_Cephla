"""Per-user Haiku credentials, outside the repository; never stored as plaintext."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile


class CredentialError(ValueError):
    pass


def _protect(data, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    # UI forbidden, current Windows user scope (never LOCAL_MACHINE).
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise CredentialError('Windows could not unlock or save the Haiku key. Re-enter it in Developer view.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


class CredentialStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Cephla' / 'haiku-key.dpapi'

    @staticmethod
    def _keyring():
        try:
            import keyring
            # Require the OS secret service; no plaintext or third-party fallback.
            if not type(keyring.get_keyring()).__module__.startswith('keyring.backends.SecretService'):
                raise RuntimeError()
            return keyring
        except Exception:
            raise CredentialError('Secure key storage needs Python keyring and an unlocked Linux Secret Service, or set ANTHROPIC_API_KEY.') from None

    def load(self):
        try:
            if os.name == 'nt':
                if not self.path.exists():
                    return ''
                return _protect(self.path.read_bytes(), decrypt=True).decode('utf-8')
            return self._keyring().get_password('Cephla', 'anthropic-api-key') or ''
        except CredentialError:
            raise
        except Exception:
            raise CredentialError('Cannot read the saved Haiku key. Re-enter it in Developer view.') from None

    def save(self, key):
        temporary = None
        try:
            if os.name != 'nt':
                self._keyring().set_password('Cephla', 'anthropic-api-key', key)
                return
            encrypted = _protect(key.encode('utf-8'))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError('Cannot securely save the Haiku key. Check access to your user settings folder.') from None
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
