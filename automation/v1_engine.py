import sys
sys.path.append(".")  # so import works
def send_command_to_frontend(text):
    """
    Legacy compatibility function.
    V2 GUI already handles output via MessageBus.
    """
    pass

import os
import datetime
import random
import pyttsx3
import psutil
import time
import shutil
import glob
import subprocess
import socket
import speech_recognition as sr
import nltk
from nltk.corpus import wordnet
from rapidfuzz import fuzz
import tkinter as tk   # ✅ added for GUI
import pyautogui

# Initialize TTS
engine = pyttsx3.init()
voices = engine.getProperty('voices')

# Pick female voice
for voice in voices:
    if "female" in voice.name.lower() or "zira" in voice.name.lower():
        engine.setProperty('voice', voice.id)
        break

engine.setProperty('rate', 150)  # Optional: speech speed

# List of greetings to detect
greetings = [
    "hello", "hi", "good morning", "good afternoon",
    "good evening", "good night", "greetings", "yo", "sup", "what's up"
]
# Possible friendly replies
greeting_replies = [
    "Hello there!", "Hi! How can I help you?", "Hey! Nice to see you.",
    "Good to see you!", "Greetings!", "Hello! What can I do for you?"
]

def press_keys(key_string):
    import pyautogui
    keys = [k.strip() for k in key_string.lower().split('+')]
    speak(f"Pressing: {' + '.join(keys)}")
    pyautogui.hotkey(*keys)


def define_word(word):
    synsets = wordnet.synsets(word)
    if synsets:
        definition = synsets[0].definition()
        speak(f"{word} means: {definition}")
    else:
        speak(f"Sorry, I don’t have the meaning of {word} in my offline dictionary.")

def build_uwp_app_index():
    uwp_index = {}
    try:
        print("Indexing installed UWP apps (may take a moment)...")
        result = subprocess.run(
            ['powershell', '-Command', 'Get-StartApps | ConvertTo-Json'],
            capture_output=True, text=True, shell=True
        )
        import json
        apps = json.loads(result.stdout)
        if isinstance(apps, list):
            for app in apps:
                name = app.get("Name", "").lower()
                appid = app.get("AppID", "")
                if name and appid:
                    uwp_index[name] = appid
    except Exception as e:
        print(f"Failed to build UWP app index: {e}")
    print(f"Indexed {len(uwp_index)} apps.")
    return uwp_index

uwp_apps = build_uwp_app_index()

# ---------------------- Universal launcher ----------------------
def launch_app(app_name):
    name_lower = app_name.lower()

    # 1️⃣ Try direct exe in PATH
    if shutil.which(app_name):
        speak(f"Opening {app_name}")
        os.system(f'start "" "{app_name}"')
        return True

    # 2️⃣ Search Start Menu .lnk shortcuts
    start_menu_dirs = [
        os.path.join(os.environ['APPDATA'], r'Microsoft\Windows\Start Menu\Programs'),
        r'C:\ProgramData\Microsoft\Windows\Start Menu\Programs'
    ]
    for dir in start_menu_dirs:
        for root, dirs, files in os.walk(dir):
            for file in files:
                if file.lower().endswith(".lnk") and name_lower in file.lower():
                    os.startfile(os.path.join(root, file))
                    speak(f"Opening {app_name}")
                    return True

    # 3️⃣ Search UWP apps
    for uwp_name, app_id in uwp_apps.items():
        if name_lower in uwp_name:
            speak(f"Opening {uwp_name}")
            os.system(f'explorer shell:AppsFolder\\{app_id}')
            return True

    # 4️⃣ Not found
    speak(f"Sorry, I couldn't find or open {app_name} on your system.")
    return False


def speak(text):
    print("Friday:", text)

    try:
        # Send to V2 GUI through MessageBus
        from core.message_bus import dispatch_message
        dispatch_message("FRIDAY", text)
    except:
        pass

    try:
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print("TTS error:", e)

def get_note_online():
    recognizer = sr.Recognizer()
    mic = sr.Microphone()
    for attempt in range(2):  # try twice
        try:
            with mic as source:
                speak("What should I write?")
                audio = recognizer.listen(source)
            note = recognizer.recognize_google(audio)
            return note
        except Exception:
            speak("Sorry, I couldn't get that. Please say it again.")
    return None

# ✅ Offline dictionary
offline_dict = {
    "python": "a powerful programming language",
    "algorithm": "a set of rules to solve a problem"
}

# ✅ Main execute function
def execute_task(command):
    command = command.lower()
    # --- 1️⃣ Greetings check ---
    for greet in greetings:
        if fuzz.ratio(command, greet) > 70:
            speak(random.choice(greeting_replies))
            return

    # ---------------------- Apps ----------------------
    if command.startswith("open"):
        app_name = command.replace("open", "", 1).strip()
        launch_app(app_name)


    # ---------------------- Time & Date ----------------------
    elif "time" in command:
        now = datetime.datetime.now().strftime("%I:%M %p")
        speak(f"The time is {now}")

    elif "date" in command:
        today = datetime.datetime.now().strftime("%A, %d %B %Y")
        speak(f"Today is {today}")

    # ---------------------- Battery ----------------------
    elif "battery" in command:
        battery = psutil.sensors_battery()
        if battery:
            speak(f"Battery is at {battery.percent} percent")
        else:
            speak("I couldn't get battery status")

    # ---------------------- Shutdown / Restart ----------------------
    elif "shutdown" in command:
        speak("Shutting down your computer.")
        os.system("shutdown /s /t 1")

    elif "restart" in command:
        speak("Restarting your computer.")
        os.system("shutdown /r /t 1")

        # ---------------------- Optimize ----------------------
    elif "optimise" in command or "optimize" in command:
        try:
            bat_path = os.path.abspath("C:\\Users\\Abhinav KG\\Downloads\\friday_ai\\backend\\optimize.bat")
            subprocess.run(['powershell', '-Command', f'Start-Process "{bat_path}" -Verb runAs'], check=True)
            speak("Optimization started successfully.")
        except Exception as e:
            speak(f"Failed to run optimize.bat: {e}")

    # ---------------------- Jokes & Motivation ----------------------
    elif "joke" in command:
        jokes = [
            "Why do programmers prefer dark mode? Because light attracts bugs.",
            "Why do Java developers wear glasses? Because they can't C sharp.",
            "I told my computer I needed a break, and it said no problem — it’ll go to sleep!"
        ]
        speak(random.choice(jokes))

    elif "motivate" in command:
        quotes = [
            "Believe in yourself, you can do it!",
            "Stay positive and keep moving forward!",
            "Don’t watch the clock; do what it does. Keep going!"
        ]
        speak(random.choice(quotes))

    # ---------------------- Notes ----------------------
    elif "take a note" in command:
        note = get_note_online()
        if note:
            with open("notes.txt", "a") as f:
                f.write(note + "\n")
            speak("Note added.")
        else:
            speak("Failed to get the note after trying twice.")


    elif "show my notes" in command or "read my notes" in command:
        if os.path.exists("notes.txt"):
            with open("notes.txt", "r") as f:
                notes = f.read()
                if notes.strip():
                    speak("Here are your notes:")
                    speak(notes)
                else:
                    speak("Your notes file is empty.")
        else:
            speak("No notes found.")

    # ---------------------- Calculator ----------------------
    elif "calculate" in command:
        try:
            expr = command.replace("calculate", "").strip()
            result = eval(expr)
            speak(f"The result is {result}")
        except Exception:
            speak("Sorry, I couldn't calculate that.")

    # ---------------------- Dictionary ----------------------
    elif "define" in command:
        word = command.replace("define", "").strip()
        speak(define_word(word))

    # ---------------------- Disk usage ----------------------
    elif "disk usage" in command:
        total, used, free = shutil.disk_usage("/")
        speak(f"Total: {total//2**30} GB, Used: {used//2**30} GB, Free: {free//2**30} GB")

    # ---------------------- File search ----------------------
    elif "search file" in command:
        query = command.replace("search file", "").strip()
        files = glob.glob(f"*{query}*.*")
        if files:
            speak(f"Found: {', '.join(files)}")
        else:
            speak("No files found.")

    # ---------------------- Play music ----------------------
    elif "play music" in command:
        folder = "music"  # folder with mp3
        files = glob.glob(f"{folder}/*.mp3")
        if files:
            song = random.choice(files)
            os.startfile(song)
            speak("Playing music.")
        else:
            speak("No music files found.")

    # ---------------------- Tell a story ----------------------
    elif "tell me a story" in command or "story" in command:
        stories = [
            "Once upon a time there was a brave coder who built Friday...",
            "In a galaxy far away, an AI learned to help humans..."
        ]
        speak(random.choice(stories))

    # ---------------------- WiFi status ----------------------
    elif "wifi status" in command:
        try:
            socket.create_connection(("8.8.8.8", 53))
            speak("You are connected to the internet.")
        except:
            speak("No internet connection detected.")

    # ---------------------- Timer ----------------------
    elif "timer" in command:
        seconds = 10  # default
        speak(f"Timer set for {seconds} seconds.")
        time.sleep(seconds)
        speak("Time's up!")

    # ---------------------- Automations ----------------------

    # Right click
    elif "right click" in command:
        speak("Right clicking")
        pyautogui.click(button='right')

    # Left click (redundant, but explicit)
    elif "left click" in command:
        speak("Left clicking")
        pyautogui.click(button='left')

    # Press back (browser etc.)

    # ---------------------- Press any keys ----------------------
    elif command.startswith("press "):
        # Example: "press alt+left", "press shift+1", "press q", "press enter"
        key_string = command.replace("press ", "").strip()
        press_keys(key_string)

    
    elif command.startswith("type "):
        text = command.replace("type ", "").strip()
        speak(f"Typing: {text}")
        pyautogui.typewrite(text)
    # Move mouse to X Y and click
    elif command.startswith("move mouse to "):
        try:
            parts = command.replace("move mouse to ", "").split()
            x = int(parts[0])
            y = int(parts[1])
            speak(f"Moving mouse to ({x},{y}) and clicking")
            pyautogui.moveTo(x, y, duration=0.5)
            pyautogui.click()
        except Exception:
            speak("Sorry, I couldn't understand the coordinates.")

    # Scroll up or down
    elif command.startswith("scroll "):
        try:
            amount = int(command.replace("scroll ", ""))
            speak(f"Scrolling by {amount}")
            pyautogui.scroll(amount)
        except:
            speak("Sorry, couldn't scroll.")

    # ---------------------- Default fallback ----------------------
    else:
        speak("Sorry, I don't know how to do that yet.")

# ---------------------- MAIN LOOP ----------------------
