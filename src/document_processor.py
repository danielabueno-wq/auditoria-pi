"""
Processamento de documentos: leitura de PDFs, planilhas e imagens.
Extrai conteúdo para envio à API do Claude.
"""
import base64
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.utils import detect_file_type, setup_logger, truncate_text, validate_file

logger = setup_logger(__name__)


@dataclass
class DocumentContent:
    """Conteúdo extraído de um documento para análise."""

    path: Path
    file_type: str
    text_content: str = ""
    # Lista de dicts {"type": "base64", "media_type": "...", "data": "..."} para imagens/PDFs
    visual_content: list[dict[str, Any]] = field(default_factory=list)
    extraction_error: Optional[str] = None


def _encode_file_as_base64(path: Path) -> str:
    """Lê um arquivo e retorna seu conteúdo em base64."""
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _extract_pdf(path: Path) -> DocumentContent:
    """
    Extrai texto de PDF com pdfplumber.
    Também envia o arquivo como base64 para análise visual de assinaturas e carimbos.
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        logger.warning("pdfplumber não instalado — enviando PDF apenas como imagem.")
        return _fallback_as_image(path, "application/pdf")

    text_parts: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(f"--- Página {i} ---\n{page_text}")
    except Exception as exc:
        logger.warning("Erro ao extrair texto do PDF '%s': %s", path.name, exc)

    combined_text = "\n\n".join(text_parts)
    b64 = _encode_file_as_base64(path)
    visual = [{"type": "base64", "media_type": "application/pdf", "data": b64}]

    return DocumentContent(
        path=path,
        file_type="pdf",
        text_content=truncate_text(combined_text),
        visual_content=visual,
    )


def _extract_spreadsheet(path: Path) -> DocumentContent:
    """Converte planilha em texto tabular para análise."""
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        return DocumentContent(
            path=path,
            file_type="spreadsheet",
            extraction_error="pandas não instalado. Execute: pip install pandas openpyxl",
        )

    try:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(path, dtype=str, keep_default_na=False)

        text = df.to_markdown(index=False) if hasattr(df, "to_markdown") else df.to_string(index=False)
        return DocumentContent(
            path=path,
            file_type="spreadsheet",
            text_content=truncate_text(text),
        )
    except Exception as exc:
        return DocumentContent(
            path=path,
            file_type="spreadsheet",
            extraction_error=f"Erro ao ler planilha: {exc}",
        )


def _extract_image(path: Path) -> DocumentContent:
    """Prepara imagem em base64 para envio ao Claude (visão)."""
    ext_to_mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
    }
    media_type = ext_to_mime.get(path.suffix.lower(), "image/jpeg")

    # Tenta OCR local como texto auxiliar (não obrigatório)
    ocr_text = _try_ocr(path)

    b64 = _encode_file_as_base64(path)
    visual = [{"type": "base64", "media_type": media_type, "data": b64}]

    return DocumentContent(
        path=path,
        file_type="image",
        text_content=ocr_text,
        visual_content=visual,
    )


def _fallback_as_image(path: Path, media_type: str) -> DocumentContent:
    b64 = _encode_file_as_base64(path)
    return DocumentContent(
        path=path,
        file_type="pdf",
        visual_content=[{"type": "base64", "media_type": media_type, "data": b64}],
    )


def _try_ocr(path: Path) -> str:
    """OCR local via pytesseract (opcional). Retorna string vazia se indisponível."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        img = Image.open(path)
        return pytesseract.image_to_string(img, lang="por+eng")
    except Exception:
        return ""


def _extract_text_file(path: Path) -> DocumentContent:
    """Lê arquivo de texto simples."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return DocumentContent(
            path=path,
            file_type="text",
            text_content=truncate_text(text),
        )
    except Exception as exc:
        return DocumentContent(
            path=path,
            file_type="text",
            extraction_error=f"Erro ao ler arquivo de texto: {exc}",
        )


def process_document(path: Path) -> DocumentContent:
    """
    Ponto de entrada principal: valida e extrai conteúdo de qualquer tipo suportado.
    Nunca lança exceção — erros são capturados em DocumentContent.extraction_error.
    """
    try:
        validate_file(path)
    except Exception as exc:
        return DocumentContent(
            path=path,
            file_type="unknown",
            extraction_error=str(exc),
        )

    file_type = detect_file_type(path)
    logger.info("Processando '%s' (tipo: %s)…", path.name, file_type)

    dispatch = {
        "pdf": _extract_pdf,
        "spreadsheet": _extract_spreadsheet,
        "image": _extract_image,
        "text": _extract_text_file,
    }

    extractor = dispatch.get(file_type)  # type: ignore[arg-type]
    if extractor is None:
        return DocumentContent(
            path=path,
            file_type=file_type or "unknown",
            extraction_error=f"Tipo não suportado: {file_type}",
        )

    try:
        return extractor(path)
    except Exception as exc:
        logger.error("Falha inesperada ao processar '%s': %s", path.name, exc)
        return DocumentContent(
            path=path,
            file_type=file_type or "unknown",
            extraction_error=f"Erro inesperado: {exc}",
        )
