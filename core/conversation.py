"""
core/conversation.py
Conversation State Machine for Friday.

States:
  IDLE              — system is running, not actively doing anything
  WAKE_LISTENING    — continuously monitoring mic for "hey friday"
  GREETING          — wake word just detected, playing greeting
  COMMAND_LISTENING — listening for the user's command
  PROCESSING        — command received, being dispatched
  AWAITING_INPUT    — assistant asked a follow-up question, waiting for answer
  EXECUTING         — long-running task in progress
  CONVERSATION_END  — user said "friday exit", returning to WAKE_LISTENING

Fixes applied (v2.1):
  1. Double response eliminated — assistant.process_command() result is ONLY
     displayed via _on_assistant_speech; the legacy GUI callback is suppressed
     during active conversation so responses never appear twice.
  2. Wake-word phrases ("hey friday", "hi", etc.) are silently ignored when
     they arrive as voice input inside COMMAND_LISTENING — they are artefacts
     of the mic picking up residual audio after wake detection.
  3. After executing a command Friday stays in COMMAND_LISTENING so the user
     can immediately issue a follow-up without saying "Hey Friday" again.
     Only a timeout OR an explicit exit phrase returns to WAKE_LISTENING.
  4. Timeout while in COMMAND_LISTENING — after CONVERSATION_IDLE_TIMEOUT
     seconds of silence, Friday says a polite goodbye and returns to standby.
"""

import logging
import threading
import time
from enum import Enum, auto
from typing import Callable, Optional


class ConvState(Enum):
    IDLE              = auto()
    WAKE_LISTENING    = auto()
    GREETING          = auto()
    COMMAND_LISTENING = auto()
    PROCESSING        = auto()
    AWAITING_INPUT    = auto()
    EXECUTING         = auto()
    CONVERSATION_END  = auto()


# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

CONFIRMATION_TRIGGERS = [
    "delete", "remove", "shutdown", "shut down", "restart", "reboot",
    "format", "uninstall", "overwrite",
]

YES_PHRASES = [
    "yes", "yeah", "yep", "sure", "go ahead", "do it",
    "confirm", "proceed", "ok", "okay", "affirmative",
]
NO_PHRASES = [
    "no", "nope", "cancel", "abort", "don't", "negative", "back off",
]

EXIT_PHRASES = [
    "friday exit", "exit friday", "goodbye friday", "bye friday",
    "stop listening", "that's all", "that is all", "dismiss",
]

# Phrases to silently ignore — wake-word artefacts / pure noise
IGNORE_PHRASES = {
    "hey friday", "hi friday", "hello friday", "ok friday", "okay friday",
    "hey", "hi", "hello", "friday",
}

# After this many seconds of silence in COMMAND_LISTENING, go to standby
CONVERSATION_IDLE_TIMEOUT = 15   # seconds


# ------------------------------------------------------------------ #
# ConversationManager
# ------------------------------------------------------------------ #

class ConversationManager:
    """
    Drives the full voice interaction loop as a state machine.

    Key design:
    - Runs entirely on ONE background thread (Friday-ConvMgr).
    - Voice capture runs on a separate daemon thread (Friday-VoiceCapture).
    - GUI updates are fired via callbacks — callers must schedule them on
      the Tkinter main thread (e.g. root.after(0, cb, arg)).
    - assistant.process_command() is called synchronously on the ConvMgr
      thread so results are available immediately after execution.
    - The legacy assistant response callback is intentionally NOT used here
      to prevent duplicate messages in the GUI.
    """

    def __init__(
        self,
        assistant,
        tts,
        voice_listener,
        wake_detector,
        config,
        on_state_change:     Optional[Callable[[ConvState], None]] = None,
        on_user_speech:      Optional[Callable[[str], None]] = None,
        on_assistant_speech: Optional[Callable[[str], None]] = None,
        on_status:           Optional[Callable[[str], None]] = None,
    ):
        self.logger   = logging.getLogger("Friday.Conversation")
        self.assistant = assistant
        self.tts       = tts
        self.voice     = voice_listener
        self.wake      = wake_detector
        self.config    = config

        # Callbacks (must be thread-safe — schedule on main thread by caller)
        self._on_state_change     = on_state_change     or (lambda s: None)
        self._on_user_speech      = on_user_speech      or (lambda t: None)
        self._on_assistant_speech = on_assistant_speech or (lambda t: None)
        self._on_status           = on_status           or (lambda t: None)

        self._state      = ConvState.IDLE
        self._state_lock = threading.Lock()

        self._pending_command: Optional[str] = None
        self._pending_prompt:  Optional[str] = None

        # Single event used to pass speech results into the state machine
        self._speech_result: Optional[str] = None
        self._speech_error:  Optional[str] = None
        self._speech_ready   = threading.Event()

        self._running     = False
        self._main_thread: Optional[threading.Thread] = None

    # ================================================================== #
    # Lifecycle
    # ================================================================== #

    def start(self):
        self._running = True
        self._main_thread = threading.Thread(
            target=self._main_loop, daemon=True, name="Friday-ConvMgr"
        )
        self._main_thread.start()
        self.logger.info("ConversationManager started")

    def stop(self):
        self._running = False
        self._speech_ready.set()
        self.logger.info("ConversationManager stopped")

    # ================================================================== #
    # External triggers
    # ================================================================== #

    def trigger_wake(self):
        """
        Called by WakeWordDetector or the GUI 'Activate' button.
        Only transitions when we are truly idle (not mid-conversation).
        """
        with self._state_lock:
            if self._state in (ConvState.WAKE_LISTENING, ConvState.IDLE,
                               ConvState.CONVERSATION_END):
                self.logger.info("Wake triggered → GREETING")
                self._set_state(ConvState.GREETING)
                self._speech_ready.set()   # unblock _handle_wake_listening

    def submit_text_command(self, text: str):
        """
        Inject a text command from the GUI.
        Handles all current states gracefully.
        """
        text = text.strip()
        if not text:
            return
        with self._state_lock:
            curr = self._state

        if curr in (ConvState.WAKE_LISTENING, ConvState.IDLE, ConvState.CONVERSATION_END):
            # Jump straight to COMMAND_LISTENING — skip greeting for text input
            self._set_state(ConvState.COMMAND_LISTENING)
            self._inject_speech(text)
        elif curr in (ConvState.COMMAND_LISTENING, ConvState.AWAITING_INPUT,
                      ConvState.GREETING):
            self._inject_speech(text)
        else:
            # During PROCESSING / EXECUTING — queue for when we return
            self._inject_speech(text)

    # ------------------------------------------------------------------ #

    def _inject_speech(self, text: str):
        self._speech_result = text
        self._speech_error  = None
        self._speech_ready.set()

    # ================================================================== #
    # State helpers
    # ================================================================== #

    def _set_state(self, new_state: ConvState):
        old = self._state
        self._state = new_state
        if old != new_state:
            self.logger.info("State  %s → %s", old.name, new_state.name)
            self._on_state_change(new_state)

    @property
    def state(self) -> ConvState:
        return self._state

    # ================================================================== #
    # Main loop
    # ================================================================== #

    def _main_loop(self):
        self._set_state(ConvState.WAKE_LISTENING)
        self._on_status("👂 Listening for 'Hey Friday'…")

        while self._running:
            s = self._state

            if   s == ConvState.WAKE_LISTENING:    self._handle_wake_listening()
            elif s == ConvState.GREETING:           self._handle_greeting()
            elif s == ConvState.COMMAND_LISTENING:  self._handle_command_listening()
            elif s == ConvState.PROCESSING:         self._handle_processing()
            elif s == ConvState.AWAITING_INPUT:     self._handle_awaiting_input()
            elif s == ConvState.EXECUTING:          time.sleep(0.05)
            elif s == ConvState.CONVERSATION_END:   self._handle_conversation_end()
            else:                                   time.sleep(0.1)

    # ================================================================== #
    # State handlers
    # ================================================================== #

    def _handle_wake_listening(self):
        """
        Idle standby.  WakeWordDetector fires trigger_wake() on its own
        thread → sets state to GREETING and fires _speech_ready.
        We just park here until that happens (1-second poll keeps CPU near 0%).
        """
        self._speech_ready.clear()
        self._speech_ready.wait(timeout=1.0)

    def _handle_greeting(self):
        """Wake word detected — greet user and move to COMMAND_LISTENING."""
        greeting = "Hey there, how can I help you?"
        self._say(greeting)
        self._on_assistant_speech(greeting)
        self._on_status("🎙️ Listening for your command…")
        with self._state_lock:
            self._set_state(ConvState.COMMAND_LISTENING)

    def _handle_command_listening(self):
        """
        Listen for one command.
        - Stays here after execution (no auto-return to standby).
        - Returns to WAKE_LISTENING only on timeout or exit phrase.
        - Silently ignores wake-word artefacts.
        """
        self._speech_ready.clear()
        self._speech_result = None
        self._speech_error  = None
        self._on_status("🎙️ Listening… (say 'Friday exit' to stop)")

        # Start mic capture
        if self.voice and self.voice.is_available:
            self.voice.listen_once_with_callbacks(
                on_result=self._on_voice_result,
                on_error=self._on_voice_error,
            )

        # Wait for speech (or timeout → go to standby)
        listen_timeout = self.config.get("speech_timeout", 6) + CONVERSATION_IDLE_TIMEOUT
        got_input = self._speech_ready.wait(timeout=listen_timeout)

        if not got_input or self._speech_result is None:
            # True timeout — politely end conversation
            msg = "I haven't heard anything for a while. Going back to standby. Say 'Hey Friday' to wake me."
            self._say(msg)
            self._on_assistant_speech(msg)
            self._set_state(ConvState.CONVERSATION_END)
            return

        text = self._speech_result.strip()
        self.logger.info("Command received: '%s'", text)

        # ---- FIX 2: ignore wake-word artefacts ----
        if text.lower() in IGNORE_PHRASES:
            self.logger.debug("Ignoring wake-word artefact: '%s'", text)
            # Stay in COMMAND_LISTENING — loop round immediately
            return

        self._on_user_speech(text)

        # Check for exit
        if self._is_exit_command(text):
            self._handle_exit()
            return

        # Move to processing
        with self._state_lock:
            self._pending_command = text
            self._set_state(ConvState.PROCESSING)

    def _handle_processing(self):
        """Check if confirmation needed, then execute or ask."""
        cmd_text = self._pending_command
        if not cmd_text:
            self._set_state(ConvState.COMMAND_LISTENING)
            return

        self._on_status(f"⏳ Processing: {cmd_text[:50]}…")

        if self._needs_confirmation(cmd_text):
            prompt = "This action requires confirmation. Should I proceed?"
            self._say(prompt)
            self._on_assistant_speech(prompt)
            with self._state_lock:
                self._pending_prompt = "confirmation"
                self._set_state(ConvState.AWAITING_INPUT)
        else:
            self._execute_command(cmd_text)

    def _handle_awaiting_input(self):
        """Wait for yes/no or a follow-up answer."""
        self._speech_ready.clear()
        self._speech_result = None
        self._speech_error  = None
        self._on_status("🎙️ Awaiting your answer…")

        if self.voice and self.voice.is_available:
            self.voice.listen_once_with_callbacks(
                on_result=self._on_voice_result,
                on_error=self._on_voice_error,
            )

        got_input = self._speech_ready.wait(timeout=14)

        if not got_input or self._speech_result is None:
            self._say("I didn't hear a response. Cancelling.")
            self._on_assistant_speech("I didn't hear a response. Cancelling.")
            with self._state_lock:
                self._pending_command = None
                self._pending_prompt  = None
                self._set_state(ConvState.COMMAND_LISTENING)
            return

        answer = self._speech_result.strip()
        self._on_user_speech(answer)
        self.logger.info("Follow-up answer: '%s'", answer)

        if self._pending_prompt == "confirmation":
            if self._is_yes(answer):
                ack = "Got it, executing now."
                self._say(ack)
                self._on_assistant_speech(ack)
                self._execute_command(self._pending_command)
            elif self._is_no(answer):
                msg = "Understood, cancelling that action."
                self._say(msg)
                self._on_assistant_speech(msg)
                with self._state_lock:
                    self._pending_command = None
                    self._pending_prompt  = None
                    self._set_state(ConvState.COMMAND_LISTENING)
            else:
                msg = "I couldn't understand. Please say yes or no."
                self._say(msg)
                self._on_assistant_speech(msg)
                # Stay in AWAITING_INPUT — loop will re-enter here
        else:
            # Generic follow-up: append answer to original command
            combined = f"{self._pending_command} {answer}"
            self._pending_command = combined
            self._pending_prompt  = None
            self._execute_command(combined)

    def _handle_conversation_end(self):
        """Transition back to WAKE_LISTENING."""
        self._on_status("👂 Listening for 'Hey Friday'…")
        with self._state_lock:
            self._set_state(ConvState.WAKE_LISTENING)

    # ================================================================== #
    # Command execution
    # ================================================================== #

    def _execute_command(self, cmd_text: str):
        """
        Execute via FridayAssistant, speak + display the result.

        FIX 1 — double response:
        We call assistant.process_command() directly (synchronous).
        This fires the assistant's internal _response_callback which the GUI
        wired to _on_result_legacy.  To prevent the response appearing twice,
        the GUI's _on_result_legacy checks whether the ConvMgr is active and
        skips display when we are handling the response here ourselves.
        We signal this by setting assistant._conv_active = True before the
        call and False after.
        """
        with self._state_lock:
            self._set_state(ConvState.EXECUTING)
        self._on_status("⚙️ Executing…")

        try:
            # Signal to assistant that ConvMgr is handling display
            self.assistant._conv_active = True

            result = self.assistant.process_command(cmd_text)
            response = result.message

            # Display + speak the response (single source of truth)
            self._on_assistant_speech(response)
            self._say(response)

        except Exception as exc:
            err = f"Something went wrong: {exc}"
            self.logger.error("Execute error: %s", exc, exc_info=True)
            self._on_assistant_speech(err)
            self._say(err)

        finally:
            self.assistant._conv_active = False
            with self._state_lock:
                self._pending_command = None
                self._pending_prompt  = None
                # ---- FIX 3: stay in COMMAND_LISTENING after each command ----
                self._set_state(ConvState.COMMAND_LISTENING)
            self._on_status("🎙️ What else can I do for you? (say 'Friday exit' to stop)")

    # ================================================================== #
    # Exit
    # ================================================================== #

    def _handle_exit(self):
        bye = "Okay, going back to standby. Say 'Hey Friday' whenever you need me."
        self._say(bye)
        self._on_assistant_speech(bye)
        self._on_status("👂 Listening for 'Hey Friday'…")
        with self._state_lock:
            self._pending_command = None
            self._pending_prompt  = None
            self._set_state(ConvState.CONVERSATION_END)

    # ================================================================== #
    # Speech I/O
    # ================================================================== #

    def _say(self, text: str):
        self.logger.info("FRIDAY says: %s", text[:120])
        if self.tts and self.tts.is_available:
            self.tts.speak(text)

    def _on_voice_result(self, text: str):
        self._speech_result = text
        self._speech_error  = None
        self._speech_ready.set()

    def _on_voice_error(self, error: str):
        self._speech_error  = error
        self._speech_result = None
        self._speech_ready.set()

    # ================================================================== #
    # Decision helpers
    # ================================================================== #

    @staticmethod
    def _needs_confirmation(text: str) -> bool:
        t = text.lower()
        return any(kw in t for kw in CONFIRMATION_TRIGGERS)

    @staticmethod
    def _is_exit_command(text: str) -> bool:
        t = text.lower().strip()
        return any(phrase in t for phrase in EXIT_PHRASES)

    @staticmethod
    def _is_yes(text: str) -> bool:
        t = text.lower().strip()
        return any(t == p or t.startswith(p + " ") for p in YES_PHRASES)

    @staticmethod
    def _is_no(text: str) -> bool:
        t = text.lower().strip()
        return any(t == p or t.startswith(p + " ") for p in NO_PHRASES)