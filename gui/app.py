"""
gui/app.py
Main Tkinter application window for Friday.
Integrates ConversationManager for full Siri/Alexa-style voice workflow.
"""

import tkinter as tk
from tkinter import scrolledtext, messagebox
import logging
import os
from datetime import datetime

from utils.config import Config
from models.command import CommandResult
from core.conversation import ConvState


# ================================================================= #
#  Colour palette
# ================================================================= #
COLORS = {
    "bg":          "#0d0d0d",
    "panel":       "#141414",
    "sidebar":     "#0a0a0a",
    "border":      "#222222",
    "accent":      "#00d4ff",
    "accent2":     "#7b2fff",
    "green":       "#00ff88",
    "red":         "#ff4444",
    "yellow":      "#ffcc00",
    "orange":      "#ff8800",
    "text":        "#e8e8e8",
    "text_dim":    "#888888",
    "text_muted":  "#444444",
    "input_bg":    "#1a1a1a",
    "btn_hover":   "#00b8d9",
}
FONT = "Consolas"

STATE_DOT = {
    ConvState.IDLE:              "#444444",
    ConvState.WAKE_LISTENING:    "#00d4ff",
    ConvState.GREETING:          "#00ff88",
    ConvState.COMMAND_LISTENING: "#ff8800",
    ConvState.PROCESSING:        "#ffcc00",
    ConvState.AWAITING_INPUT:    "#ff8800",
    ConvState.EXECUTING:         "#7b2fff",
    ConvState.CONVERSATION_END:  "#00d4ff",
}
STATE_NAME = {
    ConvState.IDLE:              "Idle",
    ConvState.WAKE_LISTENING:    "Wake Listening",
    ConvState.GREETING:          "Greeting",
    ConvState.COMMAND_LISTENING: "Listening…",
    ConvState.PROCESSING:        "Processing",
    ConvState.AWAITING_INPUT:    "Awaiting Answer",
    ConvState.EXECUTING:         "Executing",
    ConvState.CONVERSATION_END:  "Standby",
}


class FridayApp:
    """Root Tkinter window and primary UI controller."""

    def __init__(self, assistant, config: Config):
        self.assistant = assistant
        self.config = config
        self.logger = logging.getLogger("Friday.GUI")

        self.root = tk.Tk()
        self._conv_manager = None
        self._tts = None
        self._voice_listener = None
        self._cmd_history = []
        self._hist_idx = -1

        self._setup_window()
        self._build_ui()
        self._wire_assistant()
        self._init_voice_systems()
        self._show_welcome()

    # ================================================================= #
    # Window
    # ================================================================= #

    def _setup_window(self):
        w = self.config.get("gui_width", 960)
        h = self.config.get("gui_height", 680)
        self.root.title("Friday — AI Voice Assistant")
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(700, 500)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================================================================= #
    # UI construction
    # ================================================================= #

    def _build_ui(self):
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self):
        sb = tk.Frame(self.root, bg=COLORS["sidebar"], width=230)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)

        # Logo block
        tk.Label(sb, text="◈", font=(FONT, 34), fg=COLORS["accent"],
                 bg=COLORS["sidebar"]).pack(pady=(20, 2))
        tk.Label(sb, text="FRIDAY", font=(FONT, 15, "bold"),
                 fg=COLORS["accent"], bg=COLORS["sidebar"]).pack()
        tk.Label(sb, text="Voice AI Assistant", font=(FONT, 8),
                 fg=COLORS["text_dim"], bg=COLORS["sidebar"]).pack(pady=(0, 10))

        tk.Frame(sb, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=10)

        # Status block
        sf = tk.Frame(sb, bg=COLORS["sidebar"], pady=14)
        sf.pack(fill=tk.X, padx=14)
        tk.Label(sf, text="STATUS", font=(FONT, 8, "bold"),
                 fg=COLORS["text_muted"], bg=COLORS["sidebar"]).pack(anchor=tk.W)

        dr = tk.Frame(sf, bg=COLORS["sidebar"])
        dr.pack(anchor=tk.W)
        self._dot = tk.Label(dr, text="●", font=(FONT, 16),
                             fg=COLORS["accent"], bg=COLORS["sidebar"])
        self._dot.pack(side=tk.LEFT)
        self._state_lbl = tk.Label(dr, text="Initialising…", font=(FONT, 9),
                                   fg=COLORS["text"], bg=COLORS["sidebar"])
        self._state_lbl.pack(side=tk.LEFT, padx=6)

        self._status_lbl = tk.Label(sf, text="Starting up…", font=(FONT, 9),
                                    fg=COLORS["text_dim"], bg=COLORS["sidebar"],
                                    wraplength=196, justify=tk.LEFT)
        self._status_lbl.pack(anchor=tk.W, pady=(4, 0))

        tk.Frame(sb, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=10)

        self._wake_lbl = tk.Label(sb, text="👂 Wake Word: Checking…",
                                  font=(FONT, 8), fg=COLORS["text_muted"],
                                  bg=COLORS["sidebar"], pady=8)
        self._wake_lbl.pack()

        tk.Frame(sb, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=10)

        # Quick commands
        tk.Label(sb, text="QUICK COMMANDS", font=(FONT, 8, "bold"),
                 fg=COLORS["text_muted"], bg=COLORS["sidebar"]).pack(
            anchor=tk.W, padx=14, pady=(10, 4))

        for label, cmd in [
            ("📁 Downloads",   "open downloads folder"),
            ("🖥️ System Info",  "system info"),
            ("📸 Screenshot",   "take screenshot"),
            ("🔒 Lock Screen",  "lock screen"),
            ("💾 Disk Space",   "disk space"),
            ("🔋 Battery",      "battery level"),
            ("📋 Reminders",    "show reminders"),
            ("❓ Help",         "what can you do"),
        ]:
            b = tk.Button(sb, text=label, font=(FONT, 9),
                          fg=COLORS["text"], bg=COLORS["sidebar"],
                          activeforeground=COLORS["accent"],
                          activebackground=COLORS["panel"],
                          relief=tk.FLAT, cursor="hand2",
                          anchor=tk.W, padx=14, pady=3,
                          command=lambda c=cmd: self._submit(c))
            b.pack(fill=tk.X)
            self._hover(b, COLORS["panel"], COLORS["sidebar"])

        tk.Frame(sb, bg=COLORS["sidebar"]).pack(fill=tk.BOTH, expand=True)
        tk.Label(sb, text="Friday v2.0.0", font=(FONT, 7),
                 fg=COLORS["text_muted"], bg=COLORS["sidebar"], pady=8).pack()

    def _build_main(self):
        main = tk.Frame(self.root, bg=COLORS["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        # Header
        hdr = tk.Frame(main, bg=COLORS["panel"], height=50)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)

        tk.Label(hdr, text="Conversation", font=(FONT, 12, "bold"),
                 fg=COLORS["text"], bg=COLORS["panel"]).pack(
            side=tk.LEFT, padx=16, pady=12)

        self._voice_btn = tk.Button(
            hdr, text="🎙️ Activate", font=(FONT, 9, "bold"),
            fg=COLORS["bg"], bg=COLORS["accent"],
            activeforeground=COLORS["bg"], activebackground=COLORS["btn_hover"],
            relief=tk.FLAT, cursor="hand2", padx=10, pady=4,
            command=self._manual_wake,
        )
        self._voice_btn.pack(side=tk.RIGHT, padx=8, pady=8)

        tk.Button(hdr, text="⊘ Clear", font=(FONT, 9),
                  fg=COLORS["text_dim"], bg=COLORS["panel"],
                  activeforeground=COLORS["red"], activebackground=COLORS["panel"],
                  relief=tk.FLAT, cursor="hand2", pady=6, padx=10,
                  command=self._clear).pack(side=tk.RIGHT)

        # Chat
        cf = tk.Frame(main, bg=COLORS["bg"])
        cf.grid(row=1, column=0, sticky="nsew")
        cf.columnconfigure(0, weight=1)
        cf.rowconfigure(0, weight=1)

        self._chat = scrolledtext.ScrolledText(
            cf, bg=COLORS["bg"], fg=COLORS["text"],
            font=(FONT, 10), relief=tk.FLAT, bd=0,
            wrap=tk.WORD, state=tk.DISABLED,
            padx=16, pady=12,
            selectbackground=COLORS["accent2"],
        )
        self._chat.grid(row=0, column=0, sticky="nsew")

        self._chat.tag_configure("ts",     foreground=COLORS["text_muted"], font=(FONT, 8))
        self._chat.tag_configure("you",    foreground=COLORS["accent"],     font=(FONT, 9, "bold"))
        self._chat.tag_configure("fri",    foreground=COLORS["accent2"],    font=(FONT, 9, "bold"))
        self._chat.tag_configure("rem",    foreground=COLORS["yellow"],     font=(FONT, 9, "bold"))
        self._chat.tag_configure("sys",    foreground=COLORS["text_muted"], font=(FONT, 8, "italic"))
        self._chat.tag_configure("ok",     foreground=COLORS["green"],      font=(FONT, 10))
        self._chat.tag_configure("err",    foreground=COLORS["red"],        font=(FONT, 10))
        self._chat.tag_configure("unk",    foreground=COLORS["yellow"],     font=(FONT, 10))
        self._chat.tag_configure("plain",  foreground=COLORS["text"],       font=(FONT, 10))
        self._chat.tag_configure("sep",    foreground=COLORS["border"])

        # Input
        inp = tk.Frame(main, bg=COLORS["panel"], pady=10)
        inp.grid(row=2, column=0, sticky="ew")
        inp.columnconfigure(1, weight=1)

        tk.Label(inp, text=">_", font=(FONT, 12, "bold"),
                 fg=COLORS["accent"], bg=COLORS["panel"]).grid(
            row=0, column=0, padx=(16, 8))

        self._ivar = tk.StringVar()
        self._ibox = tk.Entry(inp, textvariable=self._ivar,
                              font=(FONT, 11),
                              bg=COLORS["input_bg"], fg=COLORS["text"],
                              insertbackground=COLORS["accent"],
                              relief=tk.FLAT, bd=6,
                              selectbackground=COLORS["accent2"])
        self._ibox.grid(row=0, column=1, sticky="ew", ipady=6)
        self._ibox.bind("<Return>", self._on_enter)
        self._ibox.bind("<Up>",     self._hist_up)
        self._ibox.bind("<Down>",   self._hist_down)
        self._ibox.focus()

        tk.Button(inp, text="Send ▶", font=(FONT, 10, "bold"),
                  fg=COLORS["bg"], bg=COLORS["accent"],
                  activeforeground=COLORS["bg"], activebackground=COLORS["btn_hover"],
                  relief=tk.FLAT, cursor="hand2", padx=14, pady=6,
                  command=lambda: self._on_enter(None)).grid(
            row=0, column=2, padx=(4, 16))

        tk.Label(inp,
                 text="↵ Enter to send  |  🎙️ Activate for voice  |  ↑↓ history",
                 font=(FONT, 7), fg=COLORS["text_muted"],
                 bg=COLORS["panel"]).grid(row=1, column=1, columnspan=2,
                                          sticky=tk.W, pady=(2, 0))

    # ================================================================= #
    # Wiring
    # ================================================================= #

    def _wire_assistant(self):
        self.assistant.set_response_callback(self._on_result_legacy)
        self.assistant.reminders.set_fire_callback(self._on_reminder)

    def _init_voice_systems(self):
        """Construct TTS, VoiceListener, WakeWord, and ConversationManager."""
        from voice.tts import TextToSpeech
        from voice.listener import VoiceListener
        from core.conversation import ConversationManager

        # TTS
        self._tts = TextToSpeech(
            rate=self.config.get("tts_rate", 175),
            volume=self.config.get("tts_volume", 0.95),
            voice_gender=self.config.get("tts_voice_gender", "female"),
        )

        # Voice input
        self._voice_listener = VoiceListener(
            timeout=self.config.get("speech_timeout", 6),
            phrase_limit=self.config.get("speech_phrase_limit", 10),
            language=self.config.get("voice_language", "en-US"),
        )

        # Wake word
        wake_detector = None
        if self.config.get("enable_wake_word", True):
            from voice.wake_word import WakeWordDetector
            key = self.config.get("porcupine_access_key", "")
            kw_path = self.config.get("porcupine_keyword_path", "") or None
            if key:
                wake_detector = WakeWordDetector(
                    access_key=key,
                    on_wake=self._on_wake_word,
                    on_status=lambda m: self.root.after(0, self._set_status, m),
                    keyword_path=kw_path,
                )
                if wake_detector.is_available:
                    wake_detector.start()
                    self.root.after(0, self._wake_lbl.config, {
                        "text": "👂 Wake Word: ACTIVE", "fg": COLORS["green"]})
                else:
                    self.root.after(0, self._wake_lbl.config, {
                        "text": "👂 Wake Word: Unavailable", "fg": COLORS["red"]})
            else:
                self.root.after(0, self._wake_lbl.config, {
                    "text": "👂 Wake Word: Key Not Set", "fg": COLORS["yellow"]})
        else:
            self.root.after(0, self._wake_lbl.config, {
                "text": "👂 Wake Word: Disabled", "fg": COLORS["text_muted"]})

        # Conversation Manager — the central state machine
        self._conv_manager = ConversationManager(
            assistant=self.assistant,
            tts=self._tts,
            voice_listener=self._voice_listener,
            wake_detector=wake_detector,
            config=self.config,
            on_state_change=self._on_state_change,
            on_user_speech=self._on_user_speech,
            on_assistant_speech=self._on_assistant_speech,
            on_status=lambda m: self.root.after(0, self._set_status, m),
        )
        self._conv_manager.start()

    # ================================================================= #
    # Event handlers
    # ================================================================= #

    def _on_enter(self, event):
        text = self._ivar.get().strip()
        if not text:
            return
        self._ivar.set("")
        self._cmd_history.insert(0, text)
        self._hist_idx = -1
        self._submit(text)

    def _submit(self, text: str):
        self._append("YOU", text, "plain", "you")
        if self._conv_manager:
            self._conv_manager.submit_text_command(text)

    def _manual_wake(self):
        """Manually trigger conversation mode (no wake word needed)."""
        if self._conv_manager:
            self._conv_manager.trigger_wake()
        self._voice_btn.config(text="🔴 Listening…", bg=COLORS["red"],
                               fg=COLORS["text"])
        self.root.after(3500, lambda: self._voice_btn.config(
            text="🎙️ Activate", bg=COLORS["accent"], fg=COLORS["bg"]))

    def _on_wake_word(self):
        """WakeWordDetector fires this on its own thread."""
        if self._conv_manager:
            self._conv_manager.trigger_wake()

    # ---- ConversationManager callbacks (called on worker threads) ----

    def _on_state_change(self, state: ConvState):
        self.root.after(0, self._apply_state_ui, state)

    def _on_user_speech(self, text: str):
        self.root.after(0, self._append, "YOU (voice)", text, "plain", "you")

    def _on_assistant_speech(self, text: str):
        self.root.after(0, self._append, "FRIDAY", text, "ok", "fri")

    def _on_result_legacy(self, result: CommandResult):
        """Fallback for reminders or direct calls."""
        tag = {"ok": "ok", "error": "err", "unknown": "unk"}.get(result.status, "ok")
        self.root.after(0, self._append, "FRIDAY", result.message, tag, "fri")

    def _on_reminder(self, time_str: str, message: str):
        self.root.after(0, self._fire_reminder, time_str, message)

    def _fire_reminder(self, time_str: str, message: str):
        self._append("⏰ REMINDER", f"[{time_str}] {message}", "ok", "rem")
        if self._tts:
            self._tts.speak(f"Reminder! {message}")
        messagebox.showinfo("Friday Reminder", f"⏰ {message}\nTime: {time_str}")

    def _hist_up(self, event):
        if self._cmd_history:
            self._hist_idx = min(self._hist_idx + 1, len(self._cmd_history) - 1)
            self._ivar.set(self._cmd_history[self._hist_idx])
            self._ibox.icursor(tk.END)

    def _hist_down(self, event):
        if self._hist_idx > 0:
            self._hist_idx -= 1
            self._ivar.set(self._cmd_history[self._hist_idx])
        else:
            self._hist_idx = -1
            self._ivar.set("")

    # ================================================================= #
    # UI helpers
    # ================================================================= #

    def _apply_state_ui(self, state: ConvState):
        self._dot.config(fg=STATE_DOT.get(state, COLORS["text_dim"]))
        self._state_lbl.config(text=STATE_NAME.get(state, state.name))
        # Show subtle system line for key transitions
        if state == ConvState.WAKE_LISTENING:
            self._append_sys("👂 Standby — waiting for 'Hey Friday'…")
        elif state == ConvState.COMMAND_LISTENING:
            self._append_sys("🎙️ Listening for your command…")
        elif state == ConvState.AWAITING_INPUT:
            self._append_sys("💬 Waiting for your response…")

    def _append(self, role: str, text: str, text_tag: str, label_tag: str = "fri"):
        self._chat.config(state=tk.NORMAL)
        ts = datetime.now().strftime("%H:%M:%S")
        self._chat.insert(tk.END, "\n")
        self._chat.insert(tk.END, f"[{ts}] ", "ts")
        self._chat.insert(tk.END, f"{role}  ›  ", label_tag)
        self._chat.insert(tk.END, f"{text}\n", text_tag)
        self._chat.insert(tk.END, "─" * 60 + "\n", "sep")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _append_sys(self, text: str):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, f"  {text}\n", "sys")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _set_status(self, text: str):
        self._status_lbl.config(text=text)

    def _clear(self):
        self._chat.config(state=tk.NORMAL)
        self._chat.delete("1.0", tk.END)
        self._chat.config(state=tk.DISABLED)
        self._show_welcome()

    def _show_welcome(self):
        self._append("FRIDAY", (
            "Friday is running and listening for 'Hey Friday'.\n"
            "You can also type commands below, or click 🎙️ Activate.\n"
            "Say 'Friday exit' to return to standby."
        ), "ok", "fri")

    def _hover(self, widget, hover_bg, normal_bg):
        widget.bind("<Enter>", lambda e: widget.config(bg=hover_bg))
        widget.bind("<Leave>", lambda e: widget.config(bg=normal_bg))

    # ================================================================= #
    # Lifecycle
    # ================================================================= #

    def _on_close(self):
        self.logger.info("Closing Friday")
        if self._conv_manager:
            self._conv_manager.stop()
        if self._tts:
            self._tts.stop()
        self.assistant.shutdown()
        self.root.destroy()

    def run(self):
        self.root.mainloop()