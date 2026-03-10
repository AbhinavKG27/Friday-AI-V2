"""Asynchronous voice listener powered by sounddevice input streaming."""

import logging
import threading
import time
from typing import Callable, Optional

try:
    import speech_recognition as sr
except ImportError:  # pragma: no cover - runtime dependency
    sr = None

from voice.audio_input import AudioPhraseCapturer, AudioStreamingQueue


class VoiceListener:
    """One-shot asynchronous microphone capture + transcription."""

    def __init__(
        self,
        on_result: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        timeout: int = 6,
        phrase_limit: int = 12,
        language: str = "en-US",
        sample_rate: int = 16000,
    ):
        self._log = logging.getLogger("Friday.Voice")
        self._def_result = on_result or (lambda t: None)
        self._def_error = on_error or (lambda m: None)
        self._def_status = on_status or (lambda m: None)
        self.timeout = timeout
        self.phrase_limit = phrase_limit
        self.language = language

        self._recognizer = sr.Recognizer() if sr else None
        self._stream = AudioStreamingQueue(sample_rate=sample_rate)
        self._capturer = AudioPhraseCapturer(self._stream)

        self._available = False
        self._thread: Optional[threading.Thread] = None
        self._t_lock = threading.Lock()

        self._init()

    def _init(self):
        if sr is None:
            self._log.warning(
                "speech_recognition not installed — voice input disabled. "
                "Run: pip install SpeechRecognition sounddevice"
            )
            return
        if not self._stream.is_available:
            self._log.warning(
                "sounddevice not installed — voice input disabled. "
                "Run: pip install sounddevice"
            )
            return

        self._available = True
        self._log.info(
            "Voice listener ready (sounddevice stream) timeout=%ss phrase_limit=%ss",
            self.timeout,
            self.phrase_limit,
        )

    @property
    def is_available(self) -> bool:
        return self._available

    def listen_once(self) -> None:
        self.listen_once_with_callbacks(
            on_result=self._def_result,
            on_error=self._def_error,
            on_status=self._def_status,
        )

    def listen_once_with_callbacks(
        self,
        on_result: Callable[[str], None],
        on_error: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        if not self._available:
            if on_error:
                on_error("Voice input unavailable — run: pip install SpeechRecognition sounddevice")
            return

        _err = on_error or (lambda m: None)
        _status = on_status or (lambda m: None)

        with self._t_lock:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
                if self._thread.is_alive():
                    _err("Microphone busy — please wait a moment.")
                    return

            self._thread = threading.Thread(
                target=self._capture,
                args=(on_result, _err, _status),
                daemon=True,
                name="Friday-Voice",
            )
            self._thread.start()

    def _capture(
        self,
        on_result: Callable[[str], None],
        on_error: Callable[[str], None],
        on_status: Callable[[str], None],
    ) -> None:
        on_status("🎙️ Listening…")

        try:
            self._stream.start()
            on_status("🎙️ Speak now…")
            captured = self._capturer.capture_phrase(self.timeout, self.phrase_limit)

            on_status("⏳ Recognising…")
            text = self._recognise(captured.pcm, captured.sample_rate)

            if text:
                on_status("✅ Got it")
                on_result(text)
            else:
                on_error("Could not understand the audio. Please try again.")
                on_status("❓ Unclear")

        except TimeoutError:
            on_error("No speech detected.")
            on_status("⏱️ Timeout")
        except OSError as exc:
            on_error(f"Microphone error: {exc}")
            on_status("❌ Mic error")
        except Exception as exc:
            on_error(f"Voice capture error: {exc}")
            on_status("❌ Error")
            self._log.exception("Unexpected voice capture error")
        finally:
            self._stream.stop()

    def _recognise(self, pcm_data: bytes, sample_rate: int) -> Optional[str]:
        if not pcm_data or self._recognizer is None:
            return None

        audio = sr.AudioData(pcm_data, sample_rate, sample_width=2)
        try:
            return self._recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            return None
        except sr.RequestError as exc:
            self._log.debug("Google STT unavailable: %s", exc)
            return None


def listen_and_execute(assistant) -> None:
    listener = VoiceListener()
    if not listener.is_available:
        return

    done = threading.Event()

    def _on_result(text: str):
        try:
            assistant.process_command(text)
        finally:
            done.set()

    def _on_error(_msg: str):
        done.set()

    while True:
        done.clear()
        listener.listen_once_with_callbacks(on_result=_on_result, on_error=_on_error)
        done.wait(timeout=max(listener.timeout + listener.phrase_limit + 2, 5))
        time.sleep(0.1)