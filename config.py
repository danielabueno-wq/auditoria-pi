"""Configurações centrais da aplicação de auditoria."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

SUPPORTED_EXTENSIONS = {
    "pdf": [".pdf"],
    "spreadsheet": [".xlsx", ".xls", ".csv"],
    "image": [".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"],
    "text": [".txt"],
}

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

MAX_FILE_SIZE_MB = 50
