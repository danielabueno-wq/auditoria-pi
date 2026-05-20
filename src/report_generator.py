"""
Geração de relatórios de auditoria em JSON e Markdown.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR
from src.utils import setup_logger

logger = setup_logger(__name__)


def _status_icon(status: str) -> str:
    icons = {
        "Conforme": "✅",
        "Não Conforme": "❌",
        "Ausente": "⚠️",
        "Não Verificável": "❓",
        "Não Aplicável": "➖",
        "Aprovado": "✅",
        "Reprovado": "❌",
        "Aprovado com Ressalvas": "⚠️",
        "Consistente": "✅",
        "Inconsistente": "❌",
        "Parcialmente Consistente": "⚠️",
        "Ausente em alguns": "⚠️",
    }
    return icons.get(status, "•")


def _format_item_row(label: str, item: dict[str, Any]) -> str:
    status = item.get("status", "—")
    icon = _status_icon(status)

    details: list[str] = []
    if item.get("processo") and item.get("pi"):
        details.append(f"Processo: *{item['processo']}* · PI: *{item['pi']}*")
    if item.get("divergencia"):
        details.append(f"Divergência: {item['divergencia']}")
    if item.get("observacao"):
        details.append(item["observacao"])
    if item.get("valor"):
        details.append(f"Valor: {item['valor']}")
    if item.get("divergencias"):
        details.extend(item["divergencias"])

    detail_str = " · ".join(details) if details else "—"
    return f"| {label} | {icon} {status} | {detail_str} |"


def _render_audit_section(auditoria: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    sections = [
        ("validacao_dados", "Validação de Dados"),
        ("veiculacao", "Veiculação / Comprovante"),
        ("formalizacao", "Formalização"),
        ("financeiro", "Financeiro"),
    ]
    for key, title in sections:
        section = auditoria.get(key, {})
        status = section.get("status", "—")
        icon = _status_icon(status)
        lines += [
            f"#### {title}: {icon} {status}",
            "",
            "| Item | Status | Detalhes |",
            "|------|--------|----------|",
        ]
        for item_key, item_val in section.get("itens", {}).items():
            if not isinstance(item_val, dict):
                continue
            label = item_key.replace("_", " ").title()

            # Campo especial: faixa horária com lista de veiculações fora da faixa
            if item_key == "faixa_horaria":
                status = item_val.get("status", "—")
                icon = _status_icon(status)
                faixa = item_val.get("faixa_contratada") or "—"
                obs = item_val.get("observacao") or ""
                abatimento = " ⚠️ **Abatimento indicado**" if item_val.get("abatimento_indicado") else ""
                lines.append(f"| {label} | {icon} {status} | Faixa contratada: {faixa}{abatimento} · {obs} |")
                fora = item_val.get("veiculacoes_fora_da_faixa", [])
                if fora:
                    lines.append(f"| ↳ Fora da faixa ({len(fora)}) | | " +
                                 " · ".join(f"{v.get('data','')} {v.get('horario','')} ({v.get('programa','')})" for v in fora) + " |")

            # Campo especial: quantidade com contratada vs comprovada
            elif item_key == "quantidade":
                status = item_val.get("status", "—")
                icon = _status_icon(status)
                contratada = item_val.get("contratada")
                comprovada = item_val.get("comprovada")
                diferenca = item_val.get("diferenca")
                obs = item_val.get("observacao") or ""
                detail = f"Contratada: {contratada} · Comprovada: {comprovada}"
                if diferenca is not None and diferenca < 0:
                    detail += f" · **Diferença: {diferenca}**"
                if obs:
                    detail += f" · {obs}"
                lines.append(f"| {label} | {icon} {status} | {detail} |")

            else:
                lines.append(_format_item_row(label, item_val))

        # Ação corretiva NF (financeiro)
        if key == "financeiro":
            acao = section.get("itens", {}).get("acao_corretiva_nf")
            if acao:
                lines.append(f"| Ação Corretiva NF | 📋 Orientação | {acao} |")
            dados_ausentes = section.get("itens", {}).get("nf_dados_ausentes", [])
            if dados_ausentes:
                lines.append(f"| Dados Ausentes NF | ⚠️ | {', '.join(dados_ausentes)} |")

        lines.append("")
    return lines


def generate_markdown(result: dict[str, Any]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    erros = result.get("erros_extracao", [])
    pi_info = result.get("pi", {})
    processos = result.get("processos", [])
    consistency = result.get("consistencia_entre_processos")

    lines: list[str] = [
        "# Relatório de Auditoria — PI",
        "",
        f"**Data/Hora:** {now}  ",
        f"**PI:** `{pi_info.get('nome', '—')}`  ",
        f"**Processos analisados:** {len(processos)}  ",
        "",
    ]

    if erros:
        lines += ["## ⚠️ Alertas de Extração", ""]
        lines += [f"- {e}" for e in erros]
        lines += [""]

    # Consistência entre processos
    if consistency and len(processos) > 1:
        status_geral = consistency.get("status_geral", "—")
        icon = _status_icon(status_geral)
        lines += [
            "---",
            f"## Consistência entre Processos: {icon} {status_geral}",
            "",
        ]
        inconsistencias = consistency.get("inconsistencias", [])
        if inconsistencias:
            lines += ["**Inconsistências encontradas:**", ""]
            lines += [f"- {i}" for i in inconsistencias]
            lines += [""]

        campos = consistency.get("campos_analisados", {})
        if campos:
            lines += ["| Campo | Status | Divergência |", "|-------|--------|-------------|"]
            for campo, val in campos.items():
                if isinstance(val, dict):
                    s = val.get("status", "—")
                    div = val.get("divergencia") or "—"
                    lines.append(f"| {campo.replace('_', ' ').title()} | {_status_icon(s)} {s} | {div} |")
            lines += [""]

        obs = consistency.get("observacoes")
        if obs:
            lines += [obs, ""]

    # Resultado por processo
    lines += ["---", "## Resultado por Processo", ""]

    for i, proc in enumerate(processos, start=1):
        auditoria = proc.get("auditoria", {})
        parecer = auditoria.get("parecer_conclusivo", "Não determinado")
        justificativa = auditoria.get("justificativa_parecer", "")
        recomendacoes = auditoria.get("recomendacoes", [])
        icon = _status_icon(parecer)

        lines += [
            f"### {i}. {proc.get('nome', f'Processo {i}')}",
            "",
            f"**Parecer:** {icon} {parecer}",
            "",
        ]
        if justificativa:
            lines += [justificativa, ""]
        if recomendacoes:
            lines += ["**Recomendações:**", ""]
            lines += [f"- {r}" for r in recomendacoes]
            lines += [""]

        lines += _render_audit_section(auditoria)
        lines += ["---", ""]

    # Dados extraídos
    lines += ["## Dados Extraídos", "", "### PI", "```json"]
    lines += [json.dumps(pi_info.get("extracao", {}), ensure_ascii=False, indent=2)]
    lines += ["```", ""]

    for proc in processos:
        lines += [f"### {proc.get('nome', 'Processo')}", "```json"]
        lines += [json.dumps(proc.get("extracao", {}), ensure_ascii=False, indent=2)]
        lines += ["```", ""]

    lines += ["---", "*Relatório gerado automaticamente pelo sistema de auditoria de PIs.*"]
    return "\n".join(lines)


def save_reports(result: dict[str, Any], base_name: str | None = None) -> tuple[Path, Path]:
    """Salva relatório em JSON e Markdown no diretório output/. Retorna (json_path, md_path)."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = base_name or "auditoria"
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)

    json_path = OUTPUT_DIR / f"{stem}_{timestamp}.json"
    md_path = OUTPUT_DIR / f"{stem}_{timestamp}.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Relatório JSON salvo: %s", json_path)

    md_path.write_text(generate_markdown(result), encoding="utf-8")
    logger.info("Relatório Markdown salvo: %s", md_path)

    return json_path, md_path
