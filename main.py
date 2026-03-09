"""
Friday - Offline AI Assistant
Entry point for the application.
"""

import sys
import os
import threading
import logging

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logger
from utils.config import Config
from core.assistant import FridayAssistant
from gui.app import FridayApp
from voice.v1_listener import V1VoiceListener
# NEW: import voice listener
from voice.listener import listen_and_execute


def main():
    """Main entry point."""

    # Setup logging first
    setup_logger()
    logger = logging.getLogger("Friday.Main")

    logger.info("=" * 60)
    logger.info("Friday AI Assistant - Starting Up")
    logger.info("=" * 60)

    # Load configuration
    config = Config()

    # Create the assistant core
    assistant = FridayAssistant(config)
    

    voice = V1VoiceListener()
    voice.start()


    # Start voice recognition in background thread
    voice_thread = threading.Thread(
        target=listen_and_execute,
        args=(assistant,),   # pass assistant so commands can execute
        daemon=True
    )
    voice_thread.start()

    logger.info("Voice listener started")

    # Create and launch the GUI
    app = FridayApp(assistant, config)
    app.run()

    logger.info("Friday AI Assistant - Shutting Down")


if __name__ == "__main__":
    main()