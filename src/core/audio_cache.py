"""In-process audio cache — keys large numpy arrays out of Gradio gr.State.

Gradio deep-copies State values, so passing raw audio arrays between callbacks
would double ~1GB+ memory per transition. Callers store the array once and pass
the returned key through State instead.

Count-bounded LRU. The bound (``config.AUDIO_CACHE_MAX_ENTRIES``, default 32)
sits well above the app's request concurrency (queue limit 20) so an in-flight
request's audio is never evicted mid-pipeline. Tradeoff: a browser tab left
idle past 32 newer uploads loses its entry — follow-up actions then raise a
cache miss ("run Extract Segments first"); saved sessions rehydrate from disk
via ``register_audio``. Every load refreshes recency.
"""
import logging
import threading
import uuid as _uuid
from collections import OrderedDict

import numpy as np

from config import AUDIO_CACHE_MAX_ENTRIES

log = logging.getLogger(__name__)

_AUDIO_STORE: "OrderedDict[str, tuple]" = OrderedDict()   # key → (audio_array, sample_rate)
_LOCK = threading.Lock()


def _get_entry(key: str):
    """Fetch an entry and refresh its recency. Returns None on miss."""
    with _LOCK:
        entry = _AUDIO_STORE.get(key)
        if entry is not None:
            _AUDIO_STORE.move_to_end(key)
        return entry


def _store_audio(audio: np.ndarray, sample_rate: int) -> str:
    """Cache audio in-process, return a lightweight reference key."""
    key = _uuid.uuid4().hex
    with _LOCK:
        _AUDIO_STORE[key] = (audio, sample_rate)
        while len(_AUDIO_STORE) > AUDIO_CACHE_MAX_ENTRIES:
            evicted_key, (evicted_audio, _) = _AUDIO_STORE.popitem(last=False)
            log.debug("audio cache evicted %s (%.0fs of audio, bound=%d)",
                      evicted_key, len(evicted_audio) / 16000,
                      AUDIO_CACHE_MAX_ENTRIES)
    return key


def _load_audio(ref) -> tuple:
    """Retrieve (audio, sample_rate) from a cache key or pass-through arrays."""
    if isinstance(ref, str):
        entry = _get_entry(ref)
        if entry is not None:
            return entry
        raise ValueError(f"Audio cache miss: {ref}")
    # Backward compat: raw numpy array (shouldn't happen in normal flow)
    return (ref, None)


def _audio_duration_from_ref(ref, fallback_sr=16000) -> float | None:
    """Get audio duration in seconds from a cache key."""
    if isinstance(ref, str):
        entry = _get_entry(ref)
        if entry:
            audio, sr = entry
            return len(audio) / (sr or fallback_sr)
    elif ref is not None and hasattr(ref, '__len__'):
        return len(ref) / fallback_sr
    return None


def register_audio(audio_path: str, *, target_sr: int = 16000) -> tuple[str, int]:
    """Load a WAV/MP3 from disk into the cache and return ``(key, sr)``.

    Used by the saved-sessions Load handler to re-stage audio without rerunning
    the pipeline so ``c.cached_audio`` (a State carrying a UUID key) resolves
    successfully when downstream actions look it up via ``_load_audio``.

    Mirrors the in-memory caching done by the live extract path; we intentionally
    avoid persisting the float32 audio array to the bucket because ``audio.<ext>``
    on disk is enough to rehydrate it cheaply.
    """
    import librosa
    audio, sr = librosa.load(audio_path, sr=target_sr, mono=True)
    return _store_audio(audio, sr), sr
