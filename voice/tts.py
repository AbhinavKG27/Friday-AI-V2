"""
voice/tts.py  —  Friday v4
============================
Offline text-to-speech via pyttsx3.

ARCHITECTURE
------------
pyttsx3 requires that the engine is created and driven on a single
dedicated thread (Windows SAPI COM restriction). This class spawns one
background thread ("Friday-TTS") that owns the engine for its lifetime
and processes a queue of (text, done_event) tuples.

BLOCKING MODES
--------------
speak(text, block=True)
    The caller blocks until the audio has finished playing.
    Use this BEFORE opening the microphone — otherwise Friday's own
    voice bleeds back into the mic and gets misrecognised as a command.

speak(text, block=False)  [default]
    Returns immediately. Audio plays in the background.
    Use for responses after the mic has been closed.

AVAILABILITY CHECK
------------------
TextToSpeech.is_available is False when no TTS backend is available.
All speak() calls are silently no-ops in that case, so the rest of
codebase never needs to guard against missing TTS.
"""

import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import unicodedata
from typing import Callable, Optional


_CLEAN = [
    (re.compile(r"[●•◈▶►→↓↑◀▸\-\*#]"), " "),
    (re.compile(r"[\U0001F300-\U0001FAFF]"), " "),  # emoji
    (re.compile(r"─{2,}"), " "),
    (re.compile(r"\n+"), ". "),
    (re.compile(r"\s{2,}"), " "),
    (re.compile(r"\s+([,\.!?])\s*"), r"\1 "),
]

_PUNCT_TRANSLATE = str.maketrans(
    {
        "…": "...",
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
    }
)


def _clean(text: str) -> str:
    text = text.translate(_PUNCT_TRANSLATE)
    for pat, rep in _CLEAN:
        text = pat.sub(rep, text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" .")


class TextToSpeech:
    """Thread-safe TTS wrapper with pyttsx3 primary backend + OS fallback."""

    BLOCK_TIMEOUT = 60

    def __init__(
        self,
        rate: int = 170,
        volume: float = 0.95,
        voice_gender: str = "female",
        enabled: bool = True,
        on_start: Optional[Callable[[str], None]] = None,
        on_finish: Optional[Callable[[], None]] = None,
    ):
        self._log = logging.getLogger("Friday.TTS")
        self.rate = rate
        self.volume = volume
        self.voice_gender = voice_gender
        self.enabled = enabled
        self._on_start = on_start
        self._on_finish = on_finish

        self._available = False
        self._backend: Optional[str] = None
        self._fallback_cmd: Optional[str] = None
        self._reason: str = ""
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None

        self._init()

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def backend(self) -> Optional[str]:
        return self._backend

    @property
    def unavailable_reason(self) -> str:
        return self._reason

    def _init(self) -> None:
        if not self.enabled:
            self._reason = "disabled_by_config"
            self._log.info("Voice output disabled by config (enable_voice_output=false)")
            return

        try:
            import pyttsx3

            self._pyttsx3 = pyttsx3
            self._available = True
            self._backend = "pyttsx3"
            self._log.info("pyttsx3 available — starting TTS worker")
            self._worker = threading.Thread(target=self._run_pyttsx3, daemon=True, name="Friday-TTS")
            self._worker.start()
        except ImportError as exc:
            self._start_fallback_worker(f"pyttsx3 import failed: {exc}")

    def _configure_fallback_backend(self) -> bool:
        self._fallback_cmd = None

        if os.name == "nt":
            pwsh = shutil.which("pwsh")
            powershell = shutil.which("powershell")
            if pwsh:
                self._backend = "pwsh"
                self._fallback_cmd = pwsh
                return True
            if powershell:
                self._backend = "powershell"
                self._fallback_cmd = powershell
                return True
            self._reason = "windows_powershell_not_found"
            return False

        for cmd in ("say", "spd-say", "espeak"):
            found = shutil.which(cmd)
            if found:
                self._backend = cmd
                self._fallback_cmd = found
                return True

        self._reason = "no_fallback_backend_found"
        return False

    def _start_fallback_worker(self, reason: str, *, from_worker: bool = False) -> bool:
        if not self._configure_fallback_backend():
            self._available = False
            self._reason = reason if not self._reason else f"{self._reason}; {reason}"
            self._log.error("No TTS backend available: %s", self._reason)
            return False

        self._available = True
        self._reason = ""
        self._log.warning("Using fallback TTS backend '%s' (%s)", self._backend, reason)

        if from_worker:
            self._run_fallback()
            return True

        self._worker = threading.Thread(
            target=self._run_fallback,
            daemon=True,
            name="Friday-TTS-Fallback",
        )
        self._worker.start()
        return True

    def _run_pyttsx3(self) -> None:
        try:
            engine = self._pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", self.volume)
            self._select_voice(engine)
            self._log.info("TTS ready with pyttsx3")
        except Exception as exc:
            self._log.error("pyttsx3 init failed: %s", exc)
            self._start_fallback_worker(f"pyttsx3 init failed: {exc}", from_worker=True)
            return

        while not self._stop.is_set():
            try:
                text, done_evt = self._q.get(timeout=0.3)
            except queue.Empty:
                continue

            if text is None:
                break

            try:
                if self._on_start:
                    self._on_start(text)
                engine.say(text)
                engine.runAndWait()
                if self._on_finish:
                    self._on_finish()
            except Exception as exc:
                self._log.error("pyttsx3 speak error: %s", exc)
            finally:
                if done_evt:
                    done_evt.set()
                try:
                    self._q.task_done()
                except ValueError:
                    pass

        try:
            engine.stop()
        except Exception:
            pass

    def _run_fallback(self) -> None:
        while not self._stop.is_set():
            try:
                text, done_evt = self._q.get(timeout=0.3)
            except queue.Empty:
                continue

            if text is None:
                break

            try:
                if self._on_start:
                    self._on_start(text)
                self._speak_with_fallback(text)
                if self._on_finish:
                    self._on_finish()
            except Exception as exc:
                self._log.error("Fallback TTS speak error: %s", exc)
            finally:
                if done_evt:
                    done_evt.set()
                try:
                    self._q.task_done()
                except ValueError:
                    pass

    def _speak_with_fallback(self, text: str) -> None:
        if self._backend in {"pwsh", "powershell"} and self._fallback_cmd:
            escaped = text.replace("'", "''")
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$speak.Speak('{escaped}')"
            )
            cp = subprocess.run(
                [self._fallback_cmd, "-NoProfile", "-NonInteractive", "-Command", script],
                check=False,
                capture_output=True,
                text=True,
            )
            if cp.returncode != 0:
                raise RuntimeError(f"{self._backend} failed: {cp.stderr.strip() or cp.stdout.strip()}")
            return

        if self._backend in {"say", "spd-say", "espeak"} and self._fallback_cmd:
            cp = subprocess.run(
                [self._fallback_cmd, text],
                check=False,
                capture_output=True,
                text=True,
            )
            if cp.returncode != 0:
                raise RuntimeError(f"{self._backend} failed: {cp.stderr.strip() or cp.stdout.strip()}")
            return

        raise RuntimeError(f"Fallback backend not configured (backend={self._backend}, cmd={self._fallback_cmd})")

    def _select_voice(self, engine) -> None:
        voices = engine.getProperty("voices") or []
        female_kw = ["zira", "female", "woman", "helen", "eva", "susan", "hazel", "cortana"]
        male_kw = ["david", "male", "man", "mark", "george", "james", "richard"]
        keywords = female_kw if self.voice_gender == "female" else male_kw
        for voice in voices:
            if any(k in (voice.name or "").lower() for k in keywords):
                engine.setProperty("voice", voice.id)
                return
        if voices:
            engine.setProperty("voice", voices[0].id)

    def speak(self, text: str, block: bool = False) -> None:
        if not self._available:
            return

        cleaned = _clean(text)
        if not cleaned:
            return

        done_evt = threading.Event() if block else None
        self._q.put((cleaned, done_evt))

        if block and done_evt:
            done_evt.wait(timeout=self.BLOCK_TIMEOUT)

    def speak_async(self, text: str) -> None:
        self.speak(text, block=False)

    def clear_queue(self) -> None:
        while True:
            try:
                self._q.get_nowait()
                try:
                    self._q.task_done()
                except ValueError:
                    pass
            except queue.Empty:
                break

    def stop(self) -> None:
        self._stop.set()
        self._q.put((None, None))