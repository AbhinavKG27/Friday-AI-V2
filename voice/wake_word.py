"""
voice/wake_word.py
Porcupine-based wake word detection ("Hey Friday").
Runs continuously in a background thread.
Fires on_wake() when the keyword is detected.
"""

import logging
import threading
import struct
from typing import Callable, Optional


class WakeWordDetector:
    """
    Uses Picovoice Porcupine for offline wake word detection.
    Falls back to a simple manual mode if Porcupine is not configured.
    """

    def __init__(
        self,
        access_key: str,
        on_wake: Callable[[], None],
        on_status: Optional[Callable[[str], None]] = None,
        keyword_path: Optional[str] = None,
        sensitivity: float = 0.5,
    ):
        self.logger = logging.getLogger("Friday.WakeWord")
        self.access_key = access_key
        self.keyword_path = keyword_path
        self.sensitivity = sensitivity
        self.on_wake = on_wake
        self.on_status = on_status or (lambda m: None)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._available = False

        self._init()

    def _init(self):
        if not self.access_key:
            self.logger.warning(
                "Porcupine access key not set. Wake word detection disabled. "
                "Set 'porcupine_access_key' in friday_config.json."
            )
            return
        try:
            import pvporcupine
            self._pvporcupine = pvporcupine
            self._available = True
            self.logger.info("Porcupine wake word engine available")
        except ImportError:
            self.logger.warning(
                "pvporcupine not installed. Wake word disabled. "
                "Run: pip install pvporcupine"
            )

    # ------------------------------------------------------------------ #

    @property
    def is_available(self) -> bool:
        return self._available

    def start(self):
        if not self._available:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="Friday-WakeWord"
        )
        self._thread.start()
        self.logger.info("Wake word detector started")
        self.on_status("👂 Listening for 'Hey Friday'…")

    def stop(self):
        self._running = False
        self.logger.info("Wake word detector stopped")

    # ------------------------------------------------------------------ #

    def _run(self):
        pv = self._pvporcupine
        try:
            import pyaudio
        except ImportError:
            self.logger.error("pyaudio not installed. Run: pip install pyaudio")
            return

        porcupine = None
        pa = None
        audio_stream = None

        try:
            # Build porcupine instance
            if self.keyword_path:
                porcupine = pv.create(
                    access_key=self.access_key,
                    keyword_paths=[self.keyword_path],
                    sensitivities=[self.sensitivity],
                )
            else:
                # Use built-in 'hey google' as placeholder if no custom keyword
                # The user should provide a .ppn file for "Hey Friday"
                porcupine = pv.create(
                    access_key=self.access_key,
                    keywords=["hey siri"],   # placeholder; replace with custom ppn
                    sensitivities=[self.sensitivity],
                )

            pa = pyaudio.PyAudio()
            audio_stream = pa.open(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length,
            )

            self.logger.info("Wake word listening loop started")
            while self._running:
                pcm = audio_stream.read(porcupine.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)
                result = porcupine.process(pcm)
                if result >= 0:
                    self.logger.info("Wake word detected!")
                    self.on_wake()

        except Exception as e:
            self.logger.error("Wake word error: %s", e)
        finally:
            if audio_stream:
                audio_stream.stop_stream()
                audio_stream.close()
            if pa:
                pa.terminate()
            if porcupine:
                porcupine.delete()
