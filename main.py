"""
Interface CLI para o sistema de auditoria de PIs.
Uso: python main.py --processo <arquivo> --pi <arquivo>
"""
import argparse
import sys
from pathlib import Path

from config import INPUT_DIR, OUTPUT_DIR
from src.audit_engine import audit_documents
from src.report_generator import save_reports
from src.utils import setup_logger

logger = setup_logger("auditoria-pi")


def _resolve_path(raw: str) -> Path:
    """Aceita caminho absoluto ou nome de arquivo dentro de input/."""
    p = Path(raw)
    if p.exists():
        return p.resolve()
    candidate = INPUT_DIR / raw
    if candidate.exists():
        return candidate.resolve()
    raise FileNotFoundError(
        f"Arquivo não encontrado: '{raw}'\n"
        f"Coloque o arquivo em '{INPUT_DIR}/' ou forneça o caminho completo."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="auditoria-pi",
        description="Auditoria automática de Processos Administrativos vs. PIs de publicidade.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python main.py --processo processo.pdf --pi pi.pdf\n"
            "  python main.py --processo /caminho/processo.pdf --pi /caminho/pi.xlsx\n"
            "  python main.py --processo processo.pdf --pi pi.pdf --nome minha_auditoria\n"
        ),
    )
    parser.add_argument(
        "--processo", "-p",
        required=True,
        metavar="ARQUIVO",
        help="Caminho para o processo administrativo (PDF, planilha ou imagem).",
    )
    parser.add_argument(
        "--pi", "-i",
        required=True,
        metavar="ARQUIVO",
        help="Caminho para o PI — Pedido de Inserção (PDF, planilha ou imagem).",
    )
    parser.add_argument(
        "--nome", "-n",
        default=None,
        metavar="NOME",
        help="Nome base para os arquivos de saída (padrão: 'auditoria').",
    )
    parser.add_argument(
        "--apenas-json",
        action="store_true",
        help="Gera apenas o relatório JSON (sem Markdown).",
    )

    args = parser.parse_args()

    try:
        processo_path = _resolve_path(args.processo)
        pi_path = _resolve_path(args.pi)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1

    print(f"\n{'='*60}")
    print("  SISTEMA DE AUDITORIA DE PIs")
    print(f"{'='*60}")
    print(f"  Processo : {processo_path.name}")
    print(f"  PI       : {pi_path.name}")
    print(f"  Saída    : {OUTPUT_DIR}/")
    print(f"{'='*60}\n")

    try:
        result = audit_documents(processo_path, pi_path)
    except ValueError as exc:
        logger.error("Configuração inválida: %s", exc)
        print(f"\nERRO DE CONFIGURAÇÃO: {exc}", file=sys.stderr)
        print("Verifique se ANTHROPIC_API_KEY está definida.", file=sys.stderr)
        return 1
    except Exception as exc:
        logger.error("Falha na auditoria: %s", exc)
        print(f"\nERRO INESPERADO: {exc}", file=sys.stderr)
        return 1

    base_name = args.nome or f"{processo_path.stem}_vs_{pi_path.stem}"

    try:
        json_path, md_path = save_reports(result, base_name)
    except Exception as exc:
        logger.error("Falha ao salvar relatórios: %s", exc)
        print(f"\nERRO AO SALVAR RELATÓRIO: {exc}", file=sys.stderr)
        return 1

    auditoria = result.get("auditoria", {})
    parecer = auditoria.get("parecer_conclusivo", "Não determinado")
    justificativa = auditoria.get("justificativa_parecer", "")

    print(f"\n{'='*60}")
    print(f"  PARECER: {parecer}")
    print(f"{'='*60}")
    if justificativa:
        for line in justificativa.split("\n")[:5]:
            print(f"  {line}")
    print()

    for dim_key, dim_label in [
        ("validacao_dados", "Validação de Dados"),
        ("formalizacao", "Formalização"),
        ("financeiro", "Financeiro"),
    ]:
        dim = auditoria.get(dim_key, {})
        status = dim.get("status", "—")
        print(f"  {dim_label:25s}: {status}")

    print(f"\n  Relatório JSON : {json_path}")
    print(f"  Relatório MD   : {md_path}")
    print()

    return 0 if parecer in ("Aprovado", "Aprovado com Ressalvas") else 1


if __name__ == "__main__":
    sys.exit(main())
