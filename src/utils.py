"""Utilitários: logging, detecção de tipo de arquivo e helpers."""
import logging
import sys
from pathlib import Path
from typing import Optional

from config import LOG_LEVEL, MAX_FILE_SIZE_MB, SUPPORTED_EXTENSIONS


def setup_logger(name: str) -> logging.Logger:
    """Configura e retorna um logger formatado."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    return logger


logger = setup_logger(__name__)


def detect_file_type(path: Path) -> Optional[str]:
    """Retorna o tipo do arquivo com base na extensão."""
    suffix = path.suffix.lower()
    for file_type, extensions in SUPPORTED_EXTENSIONS.items():
        if suffix in extensions:
            return file_type
    return None


def validate_file(path: Path) -> None:
    """
    Valida que o arquivo existe, é suportado e está dentro do limite de tamanho.
    Lança exceções descritivas em caso de problema.
    """
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    if not path.is_file():
        raise ValueError(f"O caminho não é um arquivo: {path}")

    file_type = detect_file_type(path)
    if file_type is None:
        supported = [ext for exts in SUPPORTED_EXTENSIONS.values() for ext in exts]
        raise ValueError(
            f"Formato não suportado: '{path.suffix}'. "
            f"Formatos aceitos: {', '.join(sorted(supported))}"
        )

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(
            f"Arquivo muito grande: {size_mb:.1f} MB "
            f"(limite: {MAX_FILE_SIZE_MB} MB): {path.name}"
        )


def truncate_text(text: str, max_chars: int = 8000) -> str:
    """Trunca texto longo preservando início e fim para contexto."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return (
        text[:half]
        + f"\n\n[... {len(text) - max_chars} caracteres omitidos ...]\n\n"
        + text[-half:]
    )
