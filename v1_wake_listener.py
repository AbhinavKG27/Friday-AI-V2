try:
    import pvporcupine
except ImportError:
    pvporcupine = None
try:
    import pyaudio
except ImportError:
    pyaudio = None
import struct
import sys
import os
import threading
import time


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


keyword_file = resource_path("assets/hey_friday_windows.ppn")


class V1WakeWordListener:

    def __init__(self, on_wake_callback):
        """
        on_wake_callback() is called when wake word detected.
        """
        self.on_wake = on_wake_callback
        self.running = False

    def start(self):
        if pvporcupine is None or pyaudio is None:
            print("Wake listener unavailable. Install pvporcupine and pyaudio.")
            return
        self.running = True
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _listen_loop(self):

        access_key = "NtoXZLPLnDTJ8a0CnjXZg9UpeOHI/V2I3hFQX+bsAvtqvRujBGAufg=="

        porcupine = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[keyword_file]
        )

        pa = pyaudio.PyAudio()

        audio_stream = pa.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length
        )

        print("Listening for 'Hey Friday'...")

        try:

            while self.running:

                pcm = audio_stream.read(
                    porcupine.frame_length,
                    exception_on_overflow=False
                )

                pcm = struct.unpack_from(
                    "h" * porcupine.frame_length,
                    pcm
                )

                keyword_index = porcupine.process(pcm)

                if keyword_index >= 0:

                    print("Wake word detected!")

                    if self.on_wake:
                        self.on_wake()

                    time.sleep(2)

        finally:

            audio_stream.stop_stream()
            audio_stream.close()
            pa.terminate()
            porcupine.delete()