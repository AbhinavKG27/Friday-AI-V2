"""
gui/app.py
Main Tkinter application window for Friday.
Dark-themed, modular GUI with conversation log, status indicator,
command entry, and voice control.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import logging
import os
from datetime import datetime
from typing import Optional

from utils.config import Config
from models.command import CommandResult, CommandStatus


# ============================================================= #
#  Colour palette
# ============================================================= #
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
    "text":        "#e8e8e8",
    "text_dim":    "#888888",
    "text_muted":  "#444444",
    "user_msg":    "#1a2a3a",
    "bot_ok":      "#0a1f0a",
    "bot_err":     "#1f0a0a",
    "bot_unk":     "#1a1a00",
    "input_bg":    "#1a1a1a",
    "btn_primary": "#00d4ff",
    "btn_hover":   "#00b8d9",
}

FONT_FAMILY = "Consolas"


class FridayApp:
    """Root Tkinter window and UI controller."""

    def __init__(self, assistant, config: Config):
        from core.assistant import FridayAssistant
        self.assistant: FridayAssistant = assistant
        self.config = config
        self.logger = logging.getLogger("Friday.GUI")

        self.root = tk.Tk()
        self._history = []          # (role, text) tuples
        self._voice_active = False
        self._wake_detector = None
        self._voice_listener = None

        self._setup_window()
        self._build_ui()
        self._wire_assistant()
        self._start_voice_systems()
        self._show_welcome()

    # ============================================================= #
    # Window setup
    # ============================================================= #

    def _setup_window(self):
        w = self.config.get("gui_width", 900)
        h = self.config.get("gui_height", 650)
        self.root.title("Friday — AI Desktop Assistant")
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(700, 500)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Try to set icon
        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "friday_icon.png")
        if os.path.exists(icon_path):
            try:
                img = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, img)
            except Exception:
                pass

    # ============================================================= #
    # UI construction
    # ============================================================= #

    def _build_ui(self):
        self.root.columnconfigure(0, weight=0)   # sidebar
        self.root.columnconfigure(1, weight=1)   # main
        self.root.rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self):
        sidebar = tk.Frame(self.root, bg=COLORS["sidebar"], width=220)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        # Logo / title
        logo_frame = tk.Frame(sidebar, bg=COLORS["sidebar"], pady=20)
        logo_frame.pack(fill=tk.X)

        tk.Label(
            logo_frame, text="◈", font=(FONT_FAMILY, 32),
            fg=COLORS["accent"], bg=COLORS["sidebar"]
        ).pack()
        tk.Label(
            logo_frame, text="FRIDAY", font=(FONT_FAMILY, 16, "bold"),
            fg=COLORS["accent"], bg=COLORS["sidebar"]
        ).pack()
        tk.Label(
            logo_frame, text="AI Desktop Assistant", font=(FONT_FAMILY, 8),
            fg=COLORS["text_dim"], bg=COLORS["sidebar"]
        ).pack()

        # Separator
        tk.Frame(sidebar, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=10)

        # Status section
        status_frame = tk.Frame(sidebar, bg=COLORS["sidebar"], pady=15)
        status_frame.pack(fill=tk.X, padx=12)

        tk.Label(
            status_frame, text="STATUS", font=(FONT_FAMILY, 8, "bold"),
            fg=COLORS["text_muted"], bg=COLORS["sidebar"]
        ).pack(anchor=tk.W)

        self._status_dot = tk.Label(
            status_frame, text="●", font=(FONT_FAMILY, 14),
            fg=COLORS["green"], bg=COLORS["sidebar"]
        )
        self._status_dot.pack(anchor=tk.W)

        self._status_label = tk.Label(
            status_frame, text="Ready", font=(FONT_FAMILY, 10),
            fg=COLORS["text"], bg=COLORS["sidebar"], wraplength=180, justify=tk.LEFT
        )
        self._status_label.pack(anchor=tk.W)

        # Separator
        tk.Frame(sidebar, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=10, pady=5)

        # Quick commands
        tk.Label(
            sidebar, text="QUICK COMMANDS", font=(FONT_FAMILY, 8, "bold"),
            fg=COLORS["text_muted"], bg=COLORS["sidebar"]
        ).pack(anchor=tk.W, padx=12, pady=(8, 4))

        quick_cmds = [
            ("📁 Downloads", "open downloads folder"),
            ("🖥️ System Info", "system info"),
            ("📸 Screenshot", "take screenshot"),
            ("🔒 Lock Screen", "lock screen"),
            ("💾 Disk Space", "disk space"),
            ("🔋 Battery", "battery level"),
            ("📋 Reminders", "show reminders"),
            ("❓ Help", "what can you do"),
        ]
        for label, cmd in quick_cmds:
            btn = tk.Button(
                sidebar, text=label,
                font=(FONT_FAMILY, 9),
                fg=COLORS["text"], bg=COLORS["sidebar"],
                activeforeground=COLORS["accent"],
                activebackground=COLORS["panel"],
                relief=tk.FLAT, cursor="hand2",
                anchor=tk.W, padx=12, pady=3,
                command=lambda c=cmd: self._submit_command(c),
            )
            btn.pack(fill=tk.X)
            self._bind_hover(btn, COLORS["panel"], COLORS["sidebar"])

        # Spacer
        tk.Frame(sidebar, bg=COLORS["sidebar"]).pack(fill=tk.BOTH, expand=True)

        # Wake word status
        self._wake_label = tk.Label(
            sidebar, text="👂 Wake Word: OFF", font=(FONT_FAMILY, 8),
            fg=COLORS["text_muted"], bg=COLORS["sidebar"], pady=5
        )
        self._wake_label.pack()

        # Version
        tk.Label(
            sidebar, text="Friday v1.0.0", font=(FONT_FAMILY, 7),
            fg=COLORS["text_muted"], bg=COLORS["sidebar"], pady=8
        ).pack()

    def _build_main(self):
        main = tk.Frame(self.root, bg=COLORS["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        # --- Header bar ---
        header = tk.Frame(main, bg=COLORS["panel"], height=50)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)

        tk.Label(
            header, text="Conversation", font=(FONT_FAMILY, 12, "bold"),
            fg=COLORS["text"], bg=COLORS["panel"]
        ).pack(side=tk.LEFT, padx=16, pady=12)

        # Clear button
        clear_btn = tk.Button(
            header, text="⊘ Clear", font=(FONT_FAMILY, 9),
            fg=COLORS["text_dim"], bg=COLORS["panel"],
            activeforeground=COLORS["red"], activebackground=COLORS["panel"],
            relief=tk.FLAT, cursor="hand2", pady=6, padx=10,
            command=self._clear_conversation,
        )
        clear_btn.pack(side=tk.RIGHT, padx=8)

        # --- Conversation area ---
        conv_frame = tk.Frame(main, bg=COLORS["bg"])
        conv_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        conv_frame.columnconfigure(0, weight=1)
        conv_frame.rowconfigure(0, weight=1)

        self._chat = scrolledtext.ScrolledText(
            conv_frame,
            bg=COLORS["bg"], fg=COLORS["text"],
            font=(FONT_FAMILY, 10),
            relief=tk.FLAT, bd=0,
            wrap=tk.WORD,
            state=tk.DISABLED,
            padx=16, pady=12,
            selectbackground=COLORS["accent2"],
        )
        self._chat.grid(row=0, column=0, sticky="nsew")

        # Configure text tags
        self._chat.tag_configure("timestamp", foreground=COLORS["text_muted"], font=(FONT_FAMILY, 8))
        self._chat.tag_configure("user_label", foreground=COLORS["accent"], font=(FONT_FAMILY, 9, "bold"))
        self._chat.tag_configure("friday_label", foreground=COLORS["accent2"], font=(FONT_FAMILY, 9, "bold"))
        self._chat.tag_configure("user_text", foreground=COLORS["text"], font=(FONT_FAMILY, 10))
        self._chat.tag_configure("ok_text", foreground=COLORS["green"], font=(FONT_FAMILY, 10))
        self._chat.tag_configure("err_text", foreground=COLORS["red"], font=(FONT_FAMILY, 10))
        self._chat.tag_configure("unk_text", foreground=COLORS["yellow"], font=(FONT_FAMILY, 10))
        self._chat.tag_configure("separator", foreground=COLORS["border"])

        # --- Input area ---
        input_area = tk.Frame(main, bg=COLORS["panel"], pady=12)
        input_area.grid(row=2, column=0, sticky="ew")
        input_area.columnconfigure(1, weight=1)

        tk.Label(
            input_area, text=">_", font=(FONT_FAMILY, 12, "bold"),
            fg=COLORS["accent"], bg=COLORS["panel"]
        ).grid(row=0, column=0, padx=(16, 8))

        self._input_var = tk.StringVar()
        self._input_box = tk.Entry(
            input_area,
            textvariable=self._input_var,
            font=(FONT_FAMILY, 11),
            bg=COLORS["input_bg"], fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            relief=tk.FLAT, bd=6,
            selectbackground=COLORS["accent2"],
        )
        self._input_box.grid(row=0, column=1, sticky="ew", ipady=6)
        self._input_box.bind("<Return>", self._on_enter)
        self._input_box.bind("<Up>", self._history_up)
        self._input_box.bind("<Down>", self._history_down)
        self._input_box.focus()

        # Voice button
        self._voice_btn = tk.Button(
            input_area, text="🎙️",
            font=(FONT_FAMILY, 14),
            fg=COLORS["text"], bg=COLORS["panel"],
            activeforeground=COLORS["green"],
            activebackground=COLORS["panel"],
            relief=tk.FLAT, cursor="hand2", padx=8,
            command=self._on_voice_click,
        )
        self._voice_btn.grid(row=0, column=2, padx=4)

        # Send button
        send_btn = tk.Button(
            input_area, text="Send ▶",
            font=(FONT_FAMILY, 10, "bold"),
            fg=COLORS["bg"], bg=COLORS["accent"],
            activeforeground=COLORS["bg"],
            activebackground=COLORS["btn_hover"],
            relief=tk.FLAT, cursor="hand2",
            padx=14, pady=6,
            command=lambda: self._on_enter(None),
        )
        send_btn.grid(row=0, column=3, padx=(4, 16))

        # Hint label
        tk.Label(
            input_area,
            text="↵ Enter to send  |  🎙️ for voice  |  ↑↓ history",
            font=(FONT_FAMILY, 7), fg=COLORS["text_muted"], bg=COLORS["panel"]
        ).grid(row=1, column=1, columnspan=3, sticky=tk.W, pady=(2, 0))

        # History pointer
        self._cmd_history = []
        self._hist_idx = -1

    # ============================================================= #
    # Wiring
    # ============================================================= #

    def _wire_assistant(self):
        self.assistant.set_response_callback(self._on_result)
        self.assistant.reminders.set_fire_callback(self._on_reminder)

    def _start_voice_systems(self):
        # Voice listener
        if self.config.get("enable_voice_input", True):
            from voice.listener import VoiceListener
            self._voice_listener = VoiceListener(
                on_result=self._submit_command,
                on_error=lambda m: self._set_status(f"❌ {m}"),
                on_status=self._set_status,
                timeout=self.config.get("speech_timeout", 5),
                phrase_limit=self.config.get("speech_phrase_limit", 10),
                language=self.config.get("voice_language", "en-US"),
            )

        # Wake word detector
        if self.config.get("enable_wake_word", True):
            from voice.wake_word import WakeWordDetector
            access_key = self.config.get("porcupine_access_key", "")
            keyword_path = self.config.get("porcupine_keyword_path", "") or None
            if access_key:
                self._wake_detector = WakeWordDetector(
                    access_key=access_key,
                    on_wake=self._on_wake_detected,
                    on_status=self._set_status,
                    keyword_path=keyword_path,
                )
                if self._wake_detector.is_available:
                    self._wake_detector.start()
                    self.root.after(100, lambda: self._wake_label.config(
                        text="👂 Wake Word: ON", fg=COLORS["green"]
                    ))

    # ============================================================= #
    # Event handlers
    # ============================================================= #

    def _on_enter(self, event):
        text = self._input_var.get().strip()
        if not text:
            return
        self._input_var.set("")
        self._cmd_history.insert(0, text)
        self._hist_idx = -1
        self._submit_command(text)

    def _on_voice_click(self):
        if not self._voice_listener:
            self._append_message("FRIDAY", "Voice input not available. Install speech_recognition.", "err")
            return
        if not self._voice_listener.is_available:
            self._append_message("FRIDAY", "Voice module not ready. Run: pip install SpeechRecognition", "err")
            return
        self._voice_btn.config(fg=COLORS["red"], text="🔴")
        self._voice_listener.listen_once()
        self.root.after(8000, lambda: self._voice_btn.config(fg=COLORS["text"], text="🎙️"))

    def _on_wake_detected(self):
        self._set_status("🎙️ Wake word detected!")
        self._on_voice_click()

    def _history_up(self, event):
        if self._cmd_history:
            self._hist_idx = min(self._hist_idx + 1, len(self._cmd_history) - 1)
            self._input_var.set(self._cmd_history[self._hist_idx])
            self._input_box.icursor(tk.END)

    def _history_down(self, event):
        if self._hist_idx > 0:
            self._hist_idx -= 1
            self._input_var.set(self._cmd_history[self._hist_idx])
        else:
            self._hist_idx = -1
            self._input_var.set("")

    def _submit_command(self, text: str):
        """Display user message and dispatch to assistant."""
        self._append_message("YOU", text, "user")
        self._set_status("⏳ Processing…")
        self._status_dot.config(fg=COLORS["yellow"])
        self.assistant.process_command_async(text)

    def _on_result(self, result: CommandResult):
        """Called from assistant thread — schedule UI update on main thread."""
        self.root.after(0, self._display_result, result)

    def _display_result(self, result: CommandResult):
        tag = {
            CommandStatus.OK: "ok",
            CommandStatus.ERROR: "err",
            CommandStatus.UNKNOWN: "unk",
        }.get(result.status, "ok")

        self._append_message("FRIDAY", result.message, tag)
        self._set_status("Ready")
        self._status_dot.config(fg=COLORS["green"])

    def _on_reminder(self, time_str: str, message: str):
        """Called when a reminder fires."""
        self.root.after(0, self._show_reminder, time_str, message)

    def _show_reminder(self, time_str: str, message: str):
        self._append_message("⏰ REMINDER", f"[{time_str}] {message}", "ok")
        messagebox.showinfo(
            "Friday Reminder",
            f"⏰ Reminder!\n\n{message}\n\nTime: {time_str}"
        )

    # ============================================================= #
    # Chat display
    # ============================================================= #

    def _append_message(self, role: str, text: str, style: str):
        self._chat.config(state=tk.NORMAL)
        ts = datetime.now().strftime("%H:%M:%S")

        self._chat.insert(tk.END, f"\n")
        self._chat.insert(tk.END, f"[{ts}] ", "timestamp")

        if role == "YOU":
            self._chat.insert(tk.END, f"YOU  ›  ", "user_label")
            self._chat.insert(tk.END, f"{text}\n", "user_text")
        else:
            label_tag = "friday_label" if role == "FRIDAY" else "user_label"
            text_tag = {"ok": "ok_text", "err": "err_text", "unk": "unk_text"}.get(style, "ok_text")
            self._chat.insert(tk.END, f"{role}  ›  ", label_tag)
            self._chat.insert(tk.END, f"{text}\n", text_tag)

        self._chat.insert(tk.END, "─" * 60 + "\n", "separator")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _clear_conversation(self):
        self._chat.config(state=tk.NORMAL)
        self._chat.delete("1.0", tk.END)
        self._chat.config(state=tk.DISABLED)
        self._show_welcome()

    def _show_welcome(self):
        welcome = (
            "Welcome! I'm Friday, your offline AI desktop assistant.\n"
            "Type a command below or click 🎙️ to use your voice.\n"
            "Type 'what can you do' to see all capabilities."
        )
        self._append_message("FRIDAY", welcome, "ok")

    # ============================================================= #
    # Status helpers
    # ============================================================= #

    def _set_status(self, text: str):
        self.root.after(0, self._status_label.config, {"text": text})

    def _bind_hover(self, widget, hover_bg, normal_bg):
        widget.bind("<Enter>", lambda e: widget.config(bg=hover_bg))
        widget.bind("<Leave>", lambda e: widget.config(bg=normal_bg))

    # ============================================================= #
    # Lifecycle
    # ============================================================= #

    def _on_close(self):
        self.logger.info("Window close requested")
        if self._wake_detector:
            self._wake_detector.stop()
        self.assistant.shutdown()
        self.root.destroy()

    def run(self):
        """Start the Tkinter event loop (blocking)."""
        self.root.mainloop()
