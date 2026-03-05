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

    # Create and launch the GUI (this blocks until window is closed)
    app = FridayApp(assistant, config)
    app.run()

    logger.info("Friday AI Assistant - Shutting Down")


if __name__ == "__main__":
    main()
