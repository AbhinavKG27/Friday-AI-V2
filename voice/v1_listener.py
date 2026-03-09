import speech_recognition as sr
import threading

from automation.v1_engine import execute_task, speak
from core.message_bus import dispatch_message


class V1VoiceListener:

    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.mic = sr.Microphone()
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _loop(self):

        speak("Friday is ready. How can I help you?")

        while self.running:

            with self.mic as source:
                print("Listening...")
                audio = self.recognizer.listen(source)

            try:
                command = self.recognizer.recognize_google(audio).lower()

                print("You said:", command)

                # send to GUI
                dispatch_message("USER", command)

                if "friday exit" in command:
                    speak("Okay, exiting. Say Hey Friday when you need me.")
                    self.stop()
                    break

                execute_task(command)

            except sr.UnknownValueError:
                print("Didn't understand")

            except Exception as e:
                print("Voice error:", e)
                speak("Sorry, I couldn't process that command.")