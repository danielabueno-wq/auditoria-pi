"""
Motor de auditoria: integração com a API do Claude para análise e comparação de documentos.

Otimizações de custo aplicadas:
- Haiku para extração de dados (5x mais barato, suficiente para tarefa mecânica)
- Opus apenas para comparação e raciocínio complexo
- Cache de prompts: system prompts idênticos são cacheados (~90% desconto nas reutilizações)
- Extração + comparação unificadas em uma única chamada por processo (reduz 2N+2 → N+2 calls)
"""
import json
from pathlib import Path
from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY
from src.document_processor import DocumentContent, process_document
from src.utils import setup_logger

logger = setup_logger(__name__)

MODEL_EXTRACTION = "claude-haiku-4-5-20251001"   # extração de dados estruturados
MODEL_ANALYSIS   = "claude-opus-4-7"              # comparação, raciocínio e parecer

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY não definida. "
                "Execute: export ANTHROPIC_API_KEY='sua-chave'"
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _build_visual_blocks(doc: DocumentContent) -> list[dict[str, Any]]:
    """Monta blocos de conteúdo visual (PDF/imagem) para envio à API."""
    blocks: list[dict[str, Any]] = []
    if doc.extraction_error:
        blocks.append({"type": "text", "text": f"[ERRO AO LER '{doc.path.name}': {doc.extraction_error}]"})
        return blocks
    for visual in doc.visual_content:
        if visual["media_type"] == "application/pdf":
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": visual["data"]},
            })
        else:
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": visual["media_type"], "data": visual["data"]},
            })
    if doc.text_content.strip():
        blocks.append({"type": "text", "text": f"Texto extraído de '{doc.path.name}':\n\n{doc.text_content}"})
    if not blocks:
        blocks.append({"type": "text", "text": f"[Arquivo '{doc.path.name}' sem conteúdo legível]"})
    return blocks


def _parse_json(raw: str) -> dict[str, Any] | None:
    try:
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except json.JSONDecodeError:
        pass
    return None


# ---------------------------------------------------------------------------
# Prompts (com cache_control aplicado via system list)
# ---------------------------------------------------------------------------

_PI_EXTRACTION_PROMPT = """\
Você é um especialista em auditoria de PIs (Pedidos de Inserção) de publicidade brasileira.
Extraia os campos do PI fornecido. Use null para campos ausentes.
Observação: o documento "Comerciais Exibidos" emitido pela emissora é o comprovante de
veiculação — não é o PI. Se receber esse documento aqui, extraia os campos que se aplicam.
Retorne SOMENTE um objeto JSON válido com esta estrutura:
{
  "cliente": string|null,
  "agencia": string|null,
  "campanha": string|null,
  "veiculo": string|null,
  "meio": "rádio"|"TV"|"jornal"|"revista"|"internet"|"outro"|null,
  "rede_gazeta": boolean|null,
  "periodo": {"inicio": string|null, "fim": string|null, "descricao": string|null},
  "insercoes_contratadas": {
    "quantidade_total": number|null,
    "faixa_horaria": string|null,
    "programas": [{"nome": string|null, "horario": string|null, "quantidade": number|null, "dias_semana": string|null}]
  },
  "numero_pi": string|null,
  "dados_bancarios": {"banco": string|null, "agencia_bancaria": string|null, "conta": string|null, "cnpj": string|null, "favorecido": string|null},
  "desconto_padrao": string|null,
  "valor_total": string|null,
  "possui_assinatura": boolean|null,
  "possui_carimbo": boolean|null,
  "observacoes": string|null
}"""

_EXTRACT_AND_COMPARE_PROMPT = """\
Você é um auditor especialista em conformidade de processos administrativos e PIs de publicidade brasileira.

Você receberá:
1. O documento do PROCESSO ADMINISTRATIVO (que inclui o comprovante/relatório de veiculação)
2. Os dados já extraídos do PI em JSON

Sua tarefa é dupla — faça as duas coisas em uma única resposta:

PARTE A — Extraia os campos do processo:
- Extraia todos os campos estruturados do processo (incluindo o comprovante de veiculação).
- O "comprovante de veiculação", o "relatório de checagem" e o documento chamado
  "Comerciais Exibidos" (emitido pela emissora) são todos a MESMA coisa. Sempre que
  encontrar qualquer um desses documentos, trate-o como o comprovante de veiculação.
- O documento "Comerciais Exibidos" tem a seguinte estrutura:
    - Cabeçalho: nome da emissora, CNPJ
    - Campos de identificação: Anunciante, Agência, Cidade, Nº PI, Praça de Exibição,
      Autorização, Produto/Campanha, Período (data início à data fim)
    - Tabela de inserções com colunas: Dia | Hora | Título | Tipo | Programa | Dur.
      onde "Dia" é o dia do mês, "Hora" é o horário exato no formato HH:MM:SS,
      "Programa" é o nome do programa, "Dur." é a duração em segundos.
    - Rodapé: "Total Inserções" ou "Total de Inserções" com o número total.
    - Página final: assinatura do responsável da emissora.
- Para cada linha da tabela, extraia: data completa (Dia + mês/ano do cabeçalho),
  horário exato (coluna Hora, ex: "07:58:33"), programa (coluna Programa) e quantidade (1 por linha).
- O total de inserções está no campo "Total Inserções" ou "Total de Inserções" no rodapé.
- Identifique se o veículo é da Rede Gazeta (Rádio Litoral FM, Rádio Gazeta AM/FM,
  ou se o e-mail/domínio do signatário contém "redegazeta.com.br").
- Para a NF: verifique se constam número do PI, nome do cliente, nome da campanha e desconto padrão.
- Para assinatura/carimbo: analise visualmente — a assinatura costuma aparecer na última página.

PARTE B — Compare com o PI e gere o laudo. Aplique as regras:

REGRA 1 — COMPROVANTE DE VEICULAÇÃO:
- Quantidade comprovada deve ser IGUAL OU SUPERIOR à contratada no PI.
  Se inferior: Não Conforme + calcule diferença + indique abatimento de pagamento.
- Cada veiculação deve ocorrer DENTRO da faixa horária exata do PI.
  Se fora da faixa: Não Conforme + liste os casos + indique abatimento por veiculação incorreta.
- Veiculações devem estar dentro do período contratado.

REGRA 2 — NF INCOMPLETA / REDE GAZETA (somente para rádio Rede Gazeta):
Se número do PI, nome do cliente, nome da campanha ou desconto padrão não constarem na NF:
  - Agência PROPEG → sugira Carta de Correção.
  - Outras agências de órgão do Governo Federal → sugira correção direta na NF.

Retorne SOMENTE um objeto JSON válido com esta estrutura:
{
  "extracao": {
    "cliente": string|null, "agencia": string|null, "campanha": string|null,
    "veiculo": string|null, "meio": string|null, "rede_gazeta": boolean|null,
    "periodo": {"inicio": string|null, "fim": string|null, "descricao": string|null},
    "insercoes_contratadas": {
      "quantidade_total": number|null, "faixa_horaria": string|null,
      "programas": [{"nome": string|null, "horario": string|null, "quantidade": number|null, "dias_semana": string|null}]
    },
    "comprovante_veiculacao": {
      "quantidade_total_veiculada": number|null,
      "veiculacoes": [{"data": string|null, "horario_exato": string|null, "programa": string|null, "quantidade": number|null, "dentro_da_faixa_horaria": boolean|null}]
    },
    "numero_pi": string|null,
    "nota_fiscal": {
      "numero": string|null, "contem_numero_pi": boolean|null, "contem_nome_cliente": boolean|null,
      "contem_nome_campanha": boolean|null, "contem_desconto_padrao": boolean|null,
      "valor": string|null, "dados_ausentes": [string]
    },
    "dados_bancarios": {"banco": string|null, "agencia_bancaria": string|null, "conta": string|null, "cnpj": string|null, "favorecido": string|null},
    "desconto_padrao": string|null, "valor_total": string|null,
    "possui_assinatura": boolean|null, "possui_carimbo": boolean|null,
    "cartas_correcao": [{"numero": string|null, "descricao": string|null, "data": string|null}],
    "observacoes": string|null
  },
  "auditoria": {
    "validacao_dados": {
      "status": "Conforme"|"Não Conforme"|"Não Verificável",
      "itens": {
        "cliente": {"status": "Conforme"|"Não Conforme"|"Ausente", "processo": string|null, "pi": string|null, "divergencia": string|null},
        "agencia": {"status": "Conforme"|"Não Conforme"|"Ausente", "processo": string|null, "pi": string|null, "divergencia": string|null},
        "campanha": {"status": "Conforme"|"Não Conforme"|"Ausente", "processo": string|null, "pi": string|null, "divergencia": string|null},
        "veiculo": {"status": "Conforme"|"Não Conforme"|"Ausente", "processo": string|null, "pi": string|null, "divergencia": string|null},
        "periodo": {"status": "Conforme"|"Não Conforme"|"Ausente", "processo": string|null, "pi": string|null, "divergencia": string|null},
        "insercoes": {"status": "Conforme"|"Não Conforme"|"Ausente", "divergencias": [string]}
      }
    },
    "veiculacao": {
      "status": "Conforme"|"Não Conforme"|"Não Verificável",
      "itens": {
        "quantidade": {"status": "Conforme"|"Não Conforme"|"Ausente", "contratada": number|null, "comprovada": number|null, "diferenca": number|null, "observacao": string|null},
        "faixa_horaria": {"status": "Conforme"|"Não Conforme"|"Ausente", "faixa_contratada": string|null, "veiculacoes_fora_da_faixa": [{"data": string, "horario": string, "programa": string|null}], "observacao": string|null, "abatimento_indicado": boolean},
        "periodo": {"status": "Conforme"|"Não Conforme"|"Ausente", "divergencia": string|null}
      }
    },
    "formalizacao": {
      "status": "Conforme"|"Não Conforme"|"Não Verificável",
      "itens": {
        "assinatura_processo": {"status": "Conforme"|"Não Conforme"|"Ausente", "observacao": string|null},
        "carimbo_processo": {"status": "Conforme"|"Não Conforme"|"Ausente", "observacao": string|null},
        "assinatura_pi": {"status": "Conforme"|"Não Conforme"|"Ausente", "observacao": string|null},
        "carimbo_pi": {"status": "Conforme"|"Não Conforme"|"Ausente", "observacao": string|null},
        "cartas_correcao": {"status": "Conforme"|"Não Conforme"|"Não Aplicável", "observacao": string|null}
      }
    },
    "financeiro": {
      "status": "Conforme"|"Não Conforme"|"Não Verificável",
      "itens": {
        "dados_bancarios": {"status": "Conforme"|"Não Conforme"|"Ausente", "divergencia": string|null},
        "numero_pi": {"status": "Conforme"|"Não Conforme"|"Ausente", "processo": string|null, "pi": string|null},
        "nome_campanha_nf": {"status": "Conforme"|"Não Conforme"|"Ausente", "divergencia": string|null},
        "desconto_padrao": {"status": "Conforme"|"Não Conforme"|"Ausente", "valor": string|null, "divergencia": string|null},
        "nf_dados_ausentes": [string],
        "acao_corretiva_nf": string|null
      }
    },
    "parecer_conclusivo": "Aprovado"|"Reprovado"|"Aprovado com Ressalvas",
    "justificativa_parecer": string,
    "recomendacoes": [string]
  }
}"""

_CONSISTENCY_PROMPT = """\
Você é um auditor especialista em conformidade de processos administrativos de publicidade brasileira.
Foram fornecidos dados extraídos de múltiplos processos do mesmo PI.
Verifique a consistência entre eles: todos devem conter as mesmas informações nos campos principais.
Retorne SOMENTE um objeto JSON válido com esta estrutura:
{
  "status_geral": "Consistente"|"Inconsistente"|"Parcialmente Consistente",
  "campos_analisados": {
    "cliente": {"status": "Consistente"|"Inconsistente"|"Ausente em alguns", "valores": {}, "divergencia": string|null},
    "agencia": {"status": "Consistente"|"Inconsistente"|"Ausente em alguns", "valores": {}, "divergencia": string|null},
    "campanha": {"status": "Consistente"|"Inconsistente"|"Ausente em alguns", "valores": {}, "divergencia": string|null},
    "veiculo": {"status": "Consistente"|"Inconsistente"|"Ausente em alguns", "valores": {}, "divergencia": string|null},
    "periodo": {"status": "Consistente"|"Inconsistente"|"Ausente em alguns", "valores": {}, "divergencia": string|null},
    "numero_pi": {"status": "Consistente"|"Inconsistente"|"Ausente em alguns", "valores": {}, "divergencia": string|null},
    "dados_bancarios": {"status": "Consistente"|"Inconsistente"|"Ausente em alguns", "divergencia": string|null},
    "desconto_padrao": {"status": "Consistente"|"Inconsistente"|"Ausente em alguns", "valores": {}, "divergencia": string|null}
  },
  "inconsistencias": [string],
  "observacoes": string|null
}
No campo "valores", use o nome do arquivo como chave e o valor encontrado como valor."""


def _cached_system(prompt: str) -> list[dict[str, Any]]:
    """Retorna system prompt no formato de lista com cache_control."""
    return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]


def _call_stream(model: str, system: list, messages: list, max_tokens: int) -> str:
    """Faz chamada com streaming e retorna o texto da resposta."""
    client = _get_client()
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if model == MODEL_ANALYSIS:
        kwargs["thinking"] = {"type": "adaptive"}

    with client.messages.stream(**kwargs) as stream:
        response = stream.get_final_message()

    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


# ---------------------------------------------------------------------------
# Funções públicas
# ---------------------------------------------------------------------------

def extract_pi_data(pi_doc: DocumentContent) -> dict[str, Any]:
    """Extrai campos estruturados do PI usando Haiku (barato e rápido)."""
    logger.info("Extraindo dados do PI '%s' [Haiku]…", pi_doc.path.name)

    blocks = _build_visual_blocks(pi_doc)
    blocks.append({"type": "text", "text": f"\nEste é o PI ({pi_doc.path.name}). Extraia os campos."})

    raw = _call_stream(
        model=MODEL_EXTRACTION,
        system=_cached_system(_PI_EXTRACTION_PROMPT),
        messages=[{"role": "user", "content": blocks}],
        max_tokens=2048,
    )
    return _parse_json(raw) or {"_raw": raw, "_parse_error": True}


def extract_and_compare(
    processo_doc: DocumentContent,
    pi_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Extrai os dados do processo E gera o laudo comparativo numa única chamada (Opus).
    Recebe os dados do PI já extraídos — sem reenviar o documento do PI.
    """
    logger.info("Analisando processo '%s' [Opus]…", processo_doc.path.name)

    blocks = _build_visual_blocks(processo_doc)
    blocks.append({
        "type": "text",
        "text": (
            f"\nEste é o PROCESSO ADMINISTRATIVO ({processo_doc.path.name}).\n\n"
            f"DADOS DO PI (já extraídos):\n{json.dumps(pi_data, ensure_ascii=False, indent=2)}\n\n"
            "Execute as PARTES A e B conforme instruído."
        ),
    })

    raw = _call_stream(
        model=MODEL_ANALYSIS,
        system=_cached_system(_EXTRACT_AND_COMPARE_PROMPT),
        messages=[{"role": "user", "content": blocks}],
        max_tokens=8192,
    )
    return _parse_json(raw) or {"_raw": raw, "_parse_error": True}


def check_consistency(processos_data: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Verifica consistência entre múltiplos processos (Opus, apenas dados JSON — sem documentos)."""
    logger.info("Verificando consistência entre %d processos [Opus]…", len(processos_data))

    summary = "\n\n".join(
        f"PROCESSO '{nome}':\n{json.dumps(dados, ensure_ascii=False, indent=2)}"
        for nome, dados in processos_data
    )

    raw = _call_stream(
        model=MODEL_ANALYSIS,
        system=_cached_system(_CONSISTENCY_PROMPT),
        messages=[{"role": "user", "content": summary}],
        max_tokens=3000,
    )
    return _parse_json(raw) or {"_raw": raw, "_parse_error": True}


def audit_multiple_documents(processo_paths: list[Path], pi_path: Path) -> dict[str, Any]:
    """
    Orquestra a auditoria completa:
    - 1 chamada Haiku  → extrai dados do PI
    - N chamadas Opus  → extrai + compara cada processo com o PI
    - 1 chamada Opus   → consistência entre processos (só se N > 1)
    Total: N + 2 chamadas (vs. 2N + 2 antes).
    """
    logger.info("=== Auditoria: %d processo(s) ===", len(processo_paths))

    pi_doc = process_document(pi_path)
    extraction_errors: list[str] = []
    if pi_doc.extraction_error:
        extraction_errors.append(f"PI: {pi_doc.extraction_error}")

    pi_data = extract_pi_data(pi_doc)

    processos: list[dict[str, Any]] = []
    processos_extracao: list[tuple[str, dict[str, Any]]] = []

    for processo_path in processo_paths:
        processo_doc = process_document(processo_path)
        if processo_doc.extraction_error:
            extraction_errors.append(f"{processo_path.name}: {processo_doc.extraction_error}")

        combined = extract_and_compare(processo_doc, pi_data)

        extracao = combined.get("extracao", {})
        auditoria = combined.get("auditoria", {})

        processos.append({
            "arquivo": str(processo_path),
            "nome": processo_path.name,
            "extracao": extracao,
            "auditoria": auditoria,
        })
        processos_extracao.append((processo_path.name, extracao))

    consistency = None
    if len(processo_paths) > 1:
        consistency = check_consistency(processos_extracao)

    return {
        "pi": {
            "arquivo": str(pi_path),
            "nome": pi_path.name,
            "extracao": pi_data,
        },
        "processos": processos,
        "consistencia_entre_processos": consistency,
        "erros_extracao": extraction_errors,
    }


def audit_documents(processo_path: Path, pi_path: Path) -> dict[str, Any]:
    """Atalho para auditoria de processo único."""
    return audit_multiple_documents([processo_path], pi_path)
