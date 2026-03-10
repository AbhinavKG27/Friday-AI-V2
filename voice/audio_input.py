"""Audio capture utilities backed by sounddevice."""

from __future__ import annotations

import audioop
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - handled at runtime
    sd = None


@dataclass
class CapturedAudio:
    """Raw mono PCM capture payload."""

    pcm: bytes
    sample_rate: int
    sample_width: int = 2


class AudioStreamingQueue:
    """Thread-safe queue fed by a sounddevice InputStream callback."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        dtype: str = "int16",
        blocksize: int = 1600,
        max_chunks: int = 256,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.blocksize = blocksize
        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=max_chunks)
        self._stream = None
        self._lock = threading.Lock()

    @property
    def is_available(self) -> bool:
        return sd is not None

    def start(self) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is not installed")

        with self._lock:
            if self._stream is not None:
                return

            def _callback(indata, _frames, _time_info, _status):
                chunk = indata.copy().tobytes()
                try:
                    self._queue.put_nowait(chunk)
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(chunk)

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=self.blocksize,
                callback=_callback,
            )
            self._stream.start()

    def stop(self) -> None:
        with self._lock:
            if self._stream is None:
                return
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read_chunk(self, timeout: float) -> Optional[bytes]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break


class AudioPhraseCapturer:
    """Capture a single voice utterance using RMS based start/stop detection."""

    def __init__(
        self,
        stream: AudioStreamingQueue,
        energy_threshold: int = 220,
        silence_seconds: float = 0.8,
    ):
        self.stream = stream
        self.energy_threshold = energy_threshold
        self.silence_seconds = silence_seconds

    def capture_phrase(self, timeout: float, phrase_time_limit: float) -> CapturedAudio:
        self.stream.flush()
        start = time.monotonic()
        speech_started = False
        speech_started_at = 0.0
        silence_started_at = None
        chunks = []

        while True:
            elapsed = time.monotonic() - start
            if not speech_started and elapsed > timeout:
                raise TimeoutError("No speech detected before timeout")

            chunk = self.stream.read_chunk(timeout=0.2)
            if chunk is None:
                continue

            rms = audioop.rms(chunk, 2)
            now = time.monotonic()

            if rms >= self.energy_threshold:
                if not speech_started:
                    speech_started = True
                    speech_started_at = now
                silence_started_at = None
                chunks.append(chunk)
            elif speech_started:
                chunks.append(chunk)
                if silence_started_at is None:
                    silence_started_at = now
                if now - silence_started_at >= self.silence_seconds:
                    break

            if speech_started and (now - speech_started_at) >= phrase_time_limit:
                break

        return CapturedAudio(pcm=b"".join(chunks), sample_rate=self.stream.sample_rate)