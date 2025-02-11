import threading

from tinydb import JSONStorage, TinyDB

class ThreadSafeStorage(JSONStorage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()

    def read(self):
        with self._lock:
            return super().read()

    def write(self, data):
        with self._lock:
            return super().write(data)

def open_store(path: str):
    return TinyDB(path, storage=ThreadSafeStorage)