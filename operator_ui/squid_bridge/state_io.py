"""Status-file I/O only: Windows replacement sharing and bounded write retries.

The Squid launcher installs this adapter in memory; shipped files are untouched.
No imaging, stage, robot, or controller command is retried here.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time

VERSION = 1
RETRY_DELAYS = (.02, .04, .08, .16, .20, .20)
READ_DELAYS = (.01, .02, .04, .08)


@contextmanager
def shared_reader(path):
    """Read an old or new complete file while allowing atomic rename/delete."""
    if os.name != 'nt':
        with open(path, 'rb') as stream:
            yield stream
        return
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # GENERIC_READ, FILE_SHARE_READ|WRITE|DELETE, OPEN_EXISTING, NORMAL.
    handle = create(str(Path(path).resolve()), 0x80000000, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        close(handle)
        raise
    try:
        stream = os.fdopen(fd, 'rb')  # stream now owns the native handle.
    except BaseException:
        os.close(fd)
        raise
    with stream:
        yield stream


def read_json(path):
    # ReplaceFile can briefly hide the pathname or deny new opens. Retry only
    # that narrow Windows transition, never malformed JSON or stale job data.
    for attempt in range(len(READ_DELAYS) + 1):
        try:
            with shared_reader(path) as stream:
                data = stream.read()
            return json.loads(data.decode('utf-8-sig'))
        except OSError as error:
            if getattr(error, 'winerror', None) not in (2, 5, 32, 33) or attempt == len(READ_DELAYS):
                raise
            time.sleep(READ_DELAYS[attempt])


def replace_file(source, target):
    if os.name != 'nt' or not Path(target).exists():
        os.replace(source, target)
        return
    # MoveFileEx (os.replace) still refuses an open destination on Windows.
    # ReplaceFile explicitly supports replacement-compatible readers and keeps
    # the original file's ACLs. Do not ignore ACL or attribute merge failures.
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    replace = kernel.ReplaceFileW
    replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                       wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    replace.restype = wintypes.BOOL
    if not replace(str(Path(target).resolve()), str(Path(source).resolve()), None, 0, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


def atomic_write_json(path, data):
    """Retry only replacement of these exact serialized bytes, for <=0.7s."""
    path = Path(path)
    payload = json.dumps(data, allow_nan=False).encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.run-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                replace_file(temporary, path)
                return
            except OSError as error:
                # Access denied can be transient on Windows rename; permanent
                # permission failures still propagate after this small bound.
                if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == len(RETRY_DELAYS):
                    raise
                time.sleep(RETRY_DELAYS[attempt])
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def install(module=None):
    """Patch only the native acquisition breadcrumb reader/writer in memory."""
    if module is None:
        from squid import acquisition_state as module
    if getattr(module, '_lacry_state_io_version', None) == VERSION:
        return
    lock = threading.RLock()

    def write(path, data):
        with lock:
            atomic_write_json(path, data)

    def read_run(state_dir=None):
        try:
            return read_json(module.run_file_path(state_dir))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    module._atomic_write_json = write
    module.read_run = read_run
    module._lacry_state_io_version = VERSION
