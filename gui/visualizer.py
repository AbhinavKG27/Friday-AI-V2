import tkinter as tk
import math
import random
import threading
try:
    import numpy as np
except ImportError:
    np = None
try:
    import pyaudio
except ImportError:
    pyaudio = None


class FridayVisualizer:

    def __init__(self, parent, color="#00d4ff"):
        self.parent = parent
        self.color = color

        self.canvas = tk.Canvas(
            parent,
            width=350,
            height=350,
            bg="#0d0d0d",
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)

        self.spikes = []
        self.pulse_radius = 60
        self.pulse_growing = True
        self.mic_level = 1.0
        self.running = True

        for i in range(80):
            self.spikes.append({
                "angle": i * (360 / 80),
                "length": 40
            })

        if np is not None and pyaudio is not None:
            threading.Thread(target=self._listen_mic, daemon=True).start()
        self._animate()

    def stop(self):
        self.running = False

    def boost_from_tts(self):
        """
        Called when Friday speaks so visualizer reacts
        """
        self.mic_level = max(self.mic_level, 2.5)

    def _listen_mic(self):
        if np is None or pyaudio is None:
            return

        CHUNK = 512
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000

        p = pyaudio.PyAudio()

        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

        while self.running:

            try:
                data = np.frombuffer(
                    stream.read(CHUNK, exception_on_overflow=False),
                    dtype=np.int16
                )

                volume = np.linalg.norm(data) / CHUNK
                level = min(max(volume / 10, 0.5), 3.0)

                self.mic_level = (self.mic_level * 0.6) + (level * 0.4)

            except:
                pass

        stream.stop_stream()
        stream.close()
        p.terminate()

    def _animate(self):

        if not self.running:
            return

        self.canvas.delete("all")

        center_x = 175
        center_y = 175

        if self.pulse_growing:
            self.pulse_radius += 0.6
            if self.pulse_radius > 70:
                self.pulse_growing = False
        else:
            self.pulse_radius -= 0.6
            if self.pulse_radius < 50:
                self.pulse_growing = True

        # glow rings
        for i in range(4, 0, -1):

            r = self.pulse_radius + (i * 3)

            self.canvas.create_oval(
                center_x - r,
                center_y - r,
                center_x + r,
                center_y + r,
                outline=self.color,
                width=1
            )

        # center orb
        self.canvas.create_oval(
            center_x - self.pulse_radius,
            center_y - self.pulse_radius,
            center_x + self.pulse_radius,
            center_y + self.pulse_radius,
            fill="#0d0d0d",
            outline=self.color,
            width=2
        )

        # spikes
        for spike in self.spikes:

            length = spike["length"] * self.mic_level * random.uniform(0.9, 1.1)

            angle = math.radians(spike["angle"])

            x_start = center_x + math.cos(angle) * self.pulse_radius
            y_start = center_y + math.sin(angle) * self.pulse_radius

            x_end = center_x + math.cos(angle) * (self.pulse_radius + length)
            y_end = center_y + math.sin(angle) * (self.pulse_radius + length)

            self.canvas.create_line(
                x_start,
                y_start,
                x_end,
                y_end,
                fill=self.color,
                width=1.5
            )

        self.canvas.after(40, self._animate)