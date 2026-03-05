"""
voice/listener.py
Handles microphone capture and speech-to-text conversion.
Uses SpeechRecognition (Google offline / Sphinx fallback).
"""

import logging
import threading
from typing import Callable, Optional


class VoiceListener:
    """
    Captures audio from the microphone and converts it to text.
    Runs in a background thread.
    Calls on_result(text) with the recognised phrase.
    Calls on_error(msg) on failure.
    Calls on_status(msg) for UI state changes.
    """

    def __init__(
        self,
        on_result: Callable[[str], None],
        on_error: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        timeout: int = 5,
        phrase_limit: int = 10,
        language: str = "en-US",
    ):
        self.logger = logging.getLogger("Friday.Voice")
        self.on_result = on_result
        self.on_error = on_error or (lambda m: None)
        self.on_status = on_status or (lambda m: None)
        self.timeout = timeout
        self.phrase_limit = phrase_limit
        self.language = language

        self._recognizer = None
        self._microphone = None
        self._available = False
        self._init_recognizer()

    # ------------------------------------------------------------------ #

    def _init_recognizer(self):
        try:
            import speech_recognition as sr
            self._sr = sr
            self._recognizer = sr.Recognizer()
            self._recognizer.energy_threshold = 300
            self._recognizer.dynamic_energy_threshold = True
            self._recognizer.pause_threshold = 0.8
            self._available = True
            self.logger.info("SpeechRecognition initialised")
        except ImportError:
            self.logger.warning(
                "speech_recognition not installed. Voice input disabled. "
                "Run: pip install SpeechRecognition"
            )
            self._available = False

    # ------------------------------------------------------------------ #

    @property
    def is_available(self) -> bool:
        return self._available

    def listen_once(self):
        """Listen for one utterance in a background thread."""
        if not self._available:
            self.on_error("Voice input not available. Install: pip install SpeechRecognition")
            return
        t = threading.Thread(target=self._capture, daemon=True, name="Friday-Voice")
        t.start()

    def _capture(self):
        sr = self._sr
        self.on_status("🎙️ Listening…")
        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.4)
                self.on_status("🎙️ Speak now…")
                audio = self._recognizer.listen(
                    source,
                    timeout=self.timeout,
                    phrase_time_limit=self.phrase_limit,
                )
            self.on_status("⏳ Processing speech…")
            # Try Google (requires internet) first, fall back to offline Sphinx
            text = self._recognise(audio)
            if text:
                self.logger.info("Recognised: %s", text)
                self.on_status("✅ Got it")
                self.on_result(text)
            else:
                self.on_error("Couldn't understand. Please try again.")
                self.on_status("Ready")
        except sr.WaitTimeoutError:
            self.on_error("No speech detected within timeout.")
            self.on_status("Ready")
        except sr.RequestError as e:
            self.on_error(f"Speech service error: {e}")
            self.on_status("Ready")
        except Exception as e:
            self.on_error(f"Voice error: {e}")
            self.on_status("Ready")

    def _recognise(self, audio) -> Optional[str]:
        """Try multiple recognition backends."""
        sr = self._sr
        # 1. Google Web Speech (needs internet, best accuracy)
        try:
            return self._recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            pass
        except sr.RequestError:
            self.logger.debug("Google Speech unavailable, trying Sphinx")

        # 2. CMU Sphinx (fully offline, lower accuracy)
        try:
            return self._recognizer.recognize_sphinx(audio)
        except Exception:
            pass

        return None
