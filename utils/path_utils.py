import os
import sys


def resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource.

    Works for:
    - Development mode
    - PyInstaller packaged executable
    """

    try:
        base_path = sys._MEIPASS  # PyInstaller temp folder
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def asset_path(file_name: str) -> str:
    """
    Shortcut for assets folder
    """
    return resource_path(os.path.join("assets", file_name))