# ◈ Friday — Offline AI Desktop Assistant

**Friday** is a fully modular, offline-capable AI desktop assistant for Windows,
built in Python with Tkinter. It runs entirely on your machine without any cloud
dependency (except optional Google Speech Recognition for voice input).

---

## Project Structure

```
Friday/
├── main.py                  ← Single entry point
├── friday_config.json       ← User configuration
├── requirements.txt
├── setup.bat                ← One-click dependency installer
├── run_friday.bat           ← One-click launcher
│
├── core/
│   └── assistant.py         ← Central command orchestrator / router
│
├── automation/
│   └── engine.py            ← OS automation (apps, power, volume, web)
│
├── filesystem/
│   └── engine.py            ← File search, listing, create, delete
│
├── scheduler/
│   └── reminder.py          ← Reminder storage + background polling
│
├── voice/
│   ├── listener.py          ← Microphone capture + speech-to-text
│   └── wake_word.py         ← Porcupine wake word detection
│
├── gui/
│   └── app.py               ← Tkinter dark-theme UI
│
├── models/
│   └── command.py           ← Command / CommandResult data classes
│
├── utils/
│   ├── config.py            ← JSON config management
│   ├── logger.py            ← Rotating file + console logging
│   └── text_utils.py        ← NLP helpers (normalize, extract, parse)
│
├── assets/                  ← Icons, images
├── data/                    ← reminders.json, history.json (auto-created)
└── logs/                    ← Rotating log files (auto-created)
```

---

## Installation

### Prerequisites
- Python 3.10 or higher
- Windows 10 / 11

### Quick Setup (Recommended)
```
Double-click setup.bat
```

### Manual Setup
```bash
pip install SpeechRecognition pyaudio psutil Pillow
```

### PyAudio Troubleshooting (Windows)
If `pip install pyaudio` fails:
```bash
pip install pipwin
pipwin install pyaudio
```
Or download the pre-built wheel from:
https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

---

## Running Friday

```bash
python main.py
```
Or double-click **run_friday.bat**.

---

## Configuration

Edit `friday_config.json` to customise Friday:

| Key | Default | Description |
|-----|---------|-------------|
| `porcupine_access_key` | `""` | Your Picovoice API key (free at console.picovoice.ai) |
| `porcupine_keyword_path` | `""` | Path to a custom .ppn wake word file |
| `speech_timeout` | `5` | Seconds to wait for speech |
| `enable_voice_input` | `true` | Enable microphone voice commands |
| `enable_wake_word` | `true` | Enable "Hey Friday" detection |
| `search_root_dirs` | Desktop, Documents, Downloads | Dirs to search for files |
| `gui_width` / `gui_height` | 960 / 680 | Window dimensions |

---

## Wake Word Setup (Optional)

1. Visit https://console.picovoice.ai/ and create a **free** account
2. Copy your **AccessKey**
3. Open `friday_config.json` and set `porcupine_access_key`
4. For a custom "Hey Friday" keyword:
   - Use the Picovoice Console to train a custom wake word
   - Download the `.ppn` file
   - Set `porcupine_keyword_path` to the file's absolute path
5. Install: `pip install pvporcupine pyaudio`

---

## Voice Commands

| Command | Action |
|---------|--------|
| `open chrome` | Launch Google Chrome |
| `open vscode` | Launch VS Code |
| `open downloads folder` | Open Downloads in Explorer |
| `open calculator` | Launch Windows Calculator |
| `open notepad` | Launch Notepad |
| `open cmd` | Open Command Prompt |
| `find my resume pdf` | Search for resume files |
| `list files in documents` | List Documents folder |
| `create folder MyProject` | Create folder on Desktop |
| `system info` | CPU, RAM, OS info |
| `battery level` | Battery status |
| `disk space` | Storage usage |
| `take screenshot` | Capture screen |
| `volume up` / `volume down` | Media volume |
| `mute` | Toggle mute |
| `lock screen` | Lock workstation |
| `shutdown system` | Schedule shutdown (30s) |
| `restart system` | Schedule restart (30s) |
| `remind me at 7 pm to call John` | Set a timed reminder |
| `show reminders` | List active reminders |
| `search google for Python tutorials` | Open browser search |
| `visit github.com` | Open website |
| `what can you do` | Show all capabilities |

---

## Architecture Notes

### Command Flow
```
User Input (text or voice)
      ↓
FridayAssistant._parse()       → Command object
      ↓
FridayAssistant._dispatch()    → route to engine
      ↓
AutomationEngine / FileSystemEngine / ReminderEngine
      ↓
CommandResult (status + message)
      ↓
GUI callback → display in chat window
```

### Thread Safety
- All assistant processing runs on background threads
- GUI updates are scheduled via `root.after(0, ...)` to the Tkinter main thread
- Reminder polling runs on its own daemon thread
- Voice capture runs on its own daemon thread

### Extending Friday
To add new commands:
1. Add a condition in `core/assistant.py → _dispatch()`
2. Implement the handler in the appropriate engine
3. Return a `CommandResult.ok()` or `CommandResult.err()`

---

## Logs

Logs are written to `logs/friday_YYYY-MM-DD.log` with rotation at 5MB.
Change verbosity in `friday_config.json`: `"log_level": "DEBUG"`.

---

## License

MIT License — free to use, modify, and distribute.
