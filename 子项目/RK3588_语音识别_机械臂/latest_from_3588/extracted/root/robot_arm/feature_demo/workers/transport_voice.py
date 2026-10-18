"""Keep this module's ASR models warm while its microphone remains explicit."""
import threading

from .voice import _legacy_engine_factory


class CachedEngineFactory:
    def __init__(self, factory=None):
        self._factory = factory or _legacy_engine_factory
        self._engine = None
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            if self._engine is None:
                self._engine = self._factory()
            return self._engine
