"""
voice/wake_word.py  —  Friday v4
==================================
Wake-word detection with automatic mode selection.

MODE A — Porcupine (preferred, fully offline, very low CPU)
    Requires a free Picovoice API key in friday_config.json:
        "porcupine_access_key": "YOUR_KEY_HERE"
    For the exact phrase "Hey Friday" supply a custom .ppn file via:
        "porcupine_keyword_path": "path/to/hey-friday.ppn"
    Without a .ppn file the built-in "hey google" keyword is used
    as the nearest available approximation.

MODE B — Software keyword spotter (fallback, no API key needed)
    Uses SpeechRecognition in a short-window loop.
    Higher latency (~3 s) but works with zero configuration.
    Triggers on: "hey friday", "hi friday", "okay friday"

Mode is selected automatically: Porcupine is tried first. If the key
is missing or pvporcupine is not installed, software mode is used.
"""

import logging
import threading
import struct
import time
from typing import Callable, Optional


SOFT_WAKE_PHRASES = {
    "hey friday",
    "hi friday",
    "okay friday",
    "ok friday",
    "hello friday",
}


class WakeWordDetector:
    """
    Continuously listens for the wake word in a background thread.
    Fires on_wake() on the detector thread when detected.

    Parameters
    ----------
    access_key   : str   Picovoice key (empty string → software mode)
    on_wake      : Callable[[], None]   — called when wake word heard
    on_status    : Callable[[str], None] — optional status updates
    keyword_path : str | None   — path to custom .ppn file
    sensitivity  : float        — 0.0–1.0 (Porcupine only, default 0.5)
    """

    def __init__(
        self,
        access_key:   str,
        on_wake:      Callable[[], None],
        on_status:    Optional[Callable[[str], None]] = None,
        keyword_path: Optional[str]  = None,
        sensitivity:  float          = 0.5,
    ):
        self._log         = logging.getLogger("Friday.WakeWord")
        self.access_key   = access_key
        self.on_wake      = on_wake
        self.on_status    = on_status or (lambda m: None)
        self.keyword_path = keyword_path
        self.sensitivity  = sensitivity

        self._running   = False
        self._thread: Optional[threading.Thread] = None
        self._available = False
        self._mode      = "none"   # "porcupine" | "software" | "none"

        self._probe()

    # ─────────────────────────────────────────────
    # Mode probing
    # ─────────────────────────────────────────────

    def _probe(self):
        """Determine which wake-word mode is available."""
        if self.access_key:
            try:
                import pvporcupine
                self._pv        = pvporcupine
                self._available = True
                self._mode      = "porcupine"
                self._log.info("Wake word mode: Porcupine")
                return
            except ImportError:
                self._log.warning(
                    "pvporcupine not installed — falling back to software mode. "
                    "Run:  pip install pvporcupine  for best performance."
                )

        # Software fallback
        try:
            import speech_recognition as sr
            self._sr_mod    = sr
            self._available = True
            self._mode      = "software"
            self._log.info("Wake word mode: software keyword spotter")
        except ImportError:
            self._log.error(
                "Neither pvporcupine nor speech_recognition available — "
                "wake word detection disabled."
            )

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def mode(self) -> str:
        return self._mode

    def start(self):
        if not self._available:
            self._log.warning("Wake word detector not available")
            return
        self._running = True
        target = (
            self._run_porcupine
            if self._mode == "porcupine"
            else self._run_software
        )
        self._thread = threading.Thread(
            target=target, daemon=True, name="Friday-WakeWord"
        )
        self._thread.start()
        self._log.info("Wake word detector started (mode=%s)", self._mode)
        self.on_status("👂 Listening for 'Hey Friday'…")

    def stop(self):
        self._running = False
        self._log.info("Wake word detector stopped")

    # ─────────────────────────────────────────────
    # Porcupine loop
    # ─────────────────────────────────────────────

    def _run_porcupine(self):
        pv = self._pv
        try:
            import pyaudio
        except ImportError:
            self._log.error("pyaudio not installed — cannot run Porcupine")
            return

        porcupine = pa = stream = None
        try:
            if self.keyword_path:
                porcupine = pv.create(
                    access_key=self.access_key,
                    keyword_paths=[self.keyword_path],
                    sensitivities=[self.sensitivity],
                )
            else:
                porcupine = pv.create(
                    access_key=self.access_key,
                    keywords=["hey google"],       # nearest built-in
                    sensitivities=[self.sensitivity],
                )

            pa     = pyaudio.PyAudio()
            stream = pa.open(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length,
            )

            self._log.info("Porcupine listening loop active")
            while self._running:
                pcm    = stream.read(
                    porcupine.frame_length, exception_on_overflow=False
                )
                pcm    = struct.unpack_from("h" * porcupine.frame_length, pcm)
                if porcupine.process(pcm) >= 0:
                    self._log.info("Wake word detected (Porcupine)")
                    self.on_wake()

        except Exception as exc:
            self._log.error("Porcupine error: %s", exc)
        finally:
            if stream:
                stream.stop_stream(); stream.close()
            if pa:
                pa.terminate()
            if porcupine:
                porcupine.delete()

    # ─────────────────────────────────────────────
    # Software keyword spotter loop
    # ─────────────────────────────────────────────

    def _run_software(self):
        """
        Short-window SpeechRecognition loop.
        Listens in 3-second windows and checks each utterance for
        a wake phrase. Higher latency than Porcupine but zero config.
        """
        sr  = self._sr_mod
        rec = sr.Recognizer()
        rec.energy_threshold          = 400
        rec.dynamic_energy_threshold  = True
        rec.pause_threshold           = 0.6

        self._log.info("Software keyword spotter active")

        while self._running:
            try:
                with sr.Microphone() as source:
                    try:
                        audio = rec.listen(source, timeout=3, phrase_time_limit=4)
                    except sr.WaitTimeoutError:
                        continue

                text = ""
                try:
                    text = rec.recognize_google(audio, language="en-US").lower()
                except sr.UnknownValueError:
                    pass
                except sr.RequestError:
                    try:
                        text = rec.recognize_sphinx(audio).lower()
                    except Exception:
                        pass

                if not text:
                    continue

                self._log.debug("Soft-wake heard: '%s'", text)
                if any(phrase in text for phrase in SOFT_WAKE_PHRASES):
                    self._log.info("Wake phrase detected (software): '%s'", text)
                    self.on_wake()
                    time.sleep(1.5)   # cooldown to prevent double-fire

            except OSError as exc:
                self._log.error("Mic error in software spotter: %s", exc)
                time.sleep(2)
            except Exception as exc:
                self._log.error("Software spotter error: %s", exc)
                time.sleep(1)