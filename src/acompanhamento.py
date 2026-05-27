from __future__ import annotations

"""
Registro de auditorias em Google Sheets e rascunhos de e-mail de correção para veículos.
"""
import base64
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

SHEET_ID = "1BN5lKhcA_eVstgTW17JuRL3_F7OOpkepqEYl9ADYmnU"
ABA_ACOMPANHAMENTO = "Acompanhamento de Auditorias"

PARECERES_COM_EMAIL = {"Reprovado", "Aprovado com Ressalvas"}

_CABECALHO = [
    "Data Auditoria", "# PI", "Veículo", "Cliente", "Campanha",
    "Período", "Parecer", "Não Conformidades", "Status",
    "E-mail Enviado", "Data E-mail", "Draft ID", "Arquivo Processo", "Observações",
]


def garantir_aba_acompanhamento(sheets) -> None:
    meta = sheets.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    abas = [s["properties"]["title"] for s in meta["sheets"]]
    if ABA_ACOMPANHAMENTO in abas:
        return
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": ABA_ACOMPANHAMENTO}}}]},
    ).execute()
    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=f"'{ABA_ACOMPANHAMENTO}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [_CABECALHO]},
    ).execute()


def _extrair_nao_conformidades(auditoria: dict) -> list[str]:
    result = []

    for dim_key, dim_label in [
        ("validacao_dados", "Validação de Dados"),
        ("formalizacao", "Formalização"),
        ("financeiro", "Financeiro"),
    ]:
        dim = auditoria.get(dim_key, {})
        for item_key, item_val in dim.get("itens", {}).items():
            if not isinstance(item_val, dict):
                continue
            if item_val.get("status") in ("Não Conforme", "Ausente"):
                label = item_key.replace("_", " ").title()
                detail = item_val.get("divergencia") or item_val.get("observacao") or ""
                entry = f"{dim_label} — {label}"
                if detail:
                    entry += f": {detail}"
                result.append(entry)

    # Veiculação — campos com estrutura especial
    veic_itens = auditoria.get("veiculacao", {}).get("itens", {})

    qtd = veic_itens.get("quantidade", {})
    if qtd.get("status") in ("Não Conforme", "Ausente"):
        result.append(
            f"Veiculação — Quantidade: {qtd.get('comprovada')} comprovadas"
            f" de {qtd.get('contratada')} contratadas"
        )

    faixa = veic_itens.get("faixa_horaria", {})
    if faixa.get("status") in ("Não Conforme", "Ausente"):
        fora = faixa.get("veiculacoes_fora_da_faixa", [])
        faixa_c = faixa.get("faixa_contratada") or ""
        entry = f"Veiculação — Faixa Horária ({faixa_c}): {len(fora)} veiculação(ões) fora da faixa"
        if fora:
            exemplos = ", ".join(
                f"{v.get('data', '')} às {v.get('horario', '')}".strip()
                for v in fora[:3]
            )
            entry += f" ({exemplos}{'...' if len(fora) > 3 else ''})"
        result.append(entry)

    periodo = veic_itens.get("periodo", {})
    if periodo.get("status") in ("Não Conforme", "Ausente"):
        entry = "Veiculação — Período"
        if periodo.get("divergencia"):
            entry += f": {periodo['divergencia']}"
        result.append(entry)

    return result


def _periodo_str(periodo: Any) -> str:
    if not isinstance(periodo, dict):
        return ""
    ini = periodo.get("inicio") or ""
    fim = periodo.get("fim") or ""
    if ini and fim:
        return f"{ini} a {fim}"
    return periodo.get("descricao") or ""


def montar_email_correcao_agrupado(
    pi_data: dict,
    processos_com_nc: list[dict],
    contato: dict,
) -> dict:
    """
    Monta UM único e-mail de correção agrupando as pendências de todos os processos
    com não-conformidades.

    processos_com_nc: lista de dicts com keys:
        - nome            (str)  nome do arquivo/processo
        - parecer         (str)
        - nao_conformidades (list[str])
        - recomendacoes   (list[str])
    """
    pi_extr = pi_data.get("extracao", {})
    num_pi = pi_extr.get("numero_pi") or pi_data.get("nome", "")
    cliente = pi_extr.get("cliente") or ""
    campanha = pi_extr.get("campanha") or ""
    veiculo = pi_extr.get("veiculo") or contato.get("nome", "")
    periodo = _periodo_str(pi_extr.get("periodo"))

    nome_contato = contato.get("contato") or contato.get("email", "").split("@")[0]

    # Urgência pelo parecer mais grave entre todos os processos
    pareceres = [p["parecer"] for p in processos_com_nc]
    if "Reprovado" in pareceres:
        urgencia = "⚠️ [PENDÊNCIA] "
        intro = (
            "A auditoria deste processo resultou em REPROVADO. "
            "Os itens abaixo precisam ser corrigidos ou justificados para liberação do pagamento."
        )
    else:
        urgencia = "[RESSALVA] "
        intro = (
            "A auditoria deste processo resultou em APROVADO COM RESSALVAS. "
            "Solicitamos a regularização dos itens abaixo."
        )

    assunto = f"{urgencia}PI {num_pi} — {veiculo} — {cliente} — Solicitação de Correção"

    # Pendências agrupadas por processo
    multiplos = len(processos_com_nc) > 1
    secoes: list[str] = []
    todas_recomendacoes: list[str] = []

    for item in processos_com_nc:
        ncs = item.get("nao_conformidades", [])
        recs = item.get("recomendacoes", [])
        todas_recomendacoes.extend(recs)

        if multiplos:
            cabecalho_proc = f"  [ {item.get('nome') or 'Processo'} ]\n"
        else:
            cabecalho_proc = ""

        if ncs:
            linhas = "\n".join(f"  • {nc}" for nc in ncs)
        else:
            linhas = "  • Consulte o relatório de auditoria para detalhes."

        secoes.append(cabecalho_proc + linhas)

    nc_str = "\n\n".join(secoes)

    # Recomendações — deduplica mantendo ordem
    seen: set[str] = set()
    recs_unicas = [r for r in todas_recomendacoes if not (r in seen or seen.add(r))]
    rec_str = ""
    if recs_unicas:
        rec_str = "\nRECOMENDAÇÕES:\n\n" + "\n".join(f"  • {r}" for r in recs_unicas) + "\n"

    corpo = f"""\
Prezado(a) {nome_contato},

{intro}

────────────────────────────────────────────
  PI:        {num_pi}
  Cliente:   {cliente}
  Campanha:  {campanha}
  Período:   {periodo}
  Veículo:   {veiculo}
────────────────────────────────────────────

PENDÊNCIAS IDENTIFICADAS:

{nc_str}
{rec_str}
Por favor, providencie as correções ou documentos necessários e encaminhe para
faturamento@buenocomunicacaodf.com.br respondendo este e-mail.

Em caso de dúvidas, estamos à disposição.

Atenciosamente,

Bueno Comunicação DF
Auditoria / Faturamento
faturamento@buenocomunicacaodf.com.br
"""

    return {
        "to": contato["email"],
        "cc": contato.get("cc", []),
        "assunto": assunto,
        "corpo": corpo,
        "pi": num_pi,
        "veiculo": veiculo,
    }


def _criar_rascunho(gmail, email_dict: dict) -> str:
    msg = MIMEMultipart("alternative")
    msg["to"] = email_dict["to"]
    msg["subject"] = email_dict["assunto"]
    if email_dict.get("cc"):
        msg["cc"] = ", ".join(email_dict["cc"])
    msg.attach(MIMEText(email_dict["corpo"], "plain", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = gmail.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return draft["id"]


def registrar_e_solicitar_correcoes(resultado: dict, username: str | None = None, token_json: str | None = None) -> dict:
    """
    Registra todos os processos na aba de acompanhamento do Sheets (uma linha por processo).
    Cria UM ÚNICO rascunho de e-mail por PI, agrupando as pendências de todos os processos
    com não-conformidades.

    Retorna:
      {
        "registrados":  [{"pi", "processo", "parecer"}],
        "rascunhos":    [{"pi", "veiculo", "parecer", "draft_id", "to"}],
        "sem_contato":  [{"pi", "veiculo"}],
        "erros":        [{"pi", "erro"}],
      }
    """
    from cobranca_pis import autenticar, carregar_contatos, buscar_contato, ler_aba, ABA_CONTATOS

    sheets, gmail = autenticar(username=username, token_json=token_json)
    garantir_aba_acompanhamento(sheets)

    rows_contatos = ler_aba(sheets, f"'{ABA_CONTATOS}'")
    contatos = carregar_contatos(rows_contatos)

    pi_data = resultado.get("pi", {})
    pi_extr = pi_data.get("extracao", {})
    num_pi = pi_extr.get("numero_pi") or pi_data.get("nome", "")

    registrados: list[dict] = []
    rascunhos: list[dict] = []
    sem_contato: list[dict] = []
    erros: list[dict] = []
    hoje = datetime.date.today().strftime("%d/%m/%Y")

    # CNPJ do veículo (extraído do PI; usado como fallback na busca de contato)
    cnpj_veiculo = pi_extr.get("dados_bancarios", {}).get("cnpj") or ""

    # ── Passo 1: coletar dados de cada processo ────────────────────────────────
    processos_dados: list[dict] = []   # todos os processos para registro no Sheets
    processos_com_nc: list[dict] = []  # apenas os que precisam de e-mail

    for proc in resultado.get("processos", []):
        auditoria = proc.get("auditoria", {})
        extracao  = proc.get("extracao", {})
        parecer   = auditoria.get("parecer_conclusivo", "Não determinado")
        nao_conformidades = _extrair_nao_conformidades(auditoria)
        recomendacoes     = auditoria.get("recomendacoes", [])

        # Nome canônico do veículo sempre vem do PI
        veiculo  = pi_extr.get("veiculo")  or extracao.get("veiculo")  or ""
        cliente  = pi_extr.get("cliente")  or extracao.get("cliente")  or ""
        campanha = pi_extr.get("campanha") or extracao.get("campanha") or ""
        periodo  = _periodo_str(pi_extr.get("periodo") or extracao.get("periodo"))

        # CNPJ fallback a partir do processo se não veio do PI
        if not cnpj_veiculo:
            cnpj_veiculo = extracao.get("dados_bancarios", {}).get("cnpj") or ""

        processos_dados.append({
            "proc":    proc,
            "parecer": parecer,
            "veiculo": veiculo,
            "cliente": cliente,
            "campanha": campanha,
            "periodo": periodo,
            "nc_str":  " | ".join(nao_conformidades),
        })

        if parecer in PARECERES_COM_EMAIL:
            processos_com_nc.append({
                "nome":               proc.get("nome", ""),
                "parecer":            parecer,
                "nao_conformidades":  nao_conformidades,
                "recomendacoes":      recomendacoes,
            })

    # ── Passo 2: criar UM único rascunho de e-mail para o PI ──────────────────
    draft_id_unico = ""
    email_enviado_str = "Não"
    data_email_str = ""

    if processos_com_nc:
        # Usar dados do primeiro processo com NC para encontrar o veículo
        veiculo_ref = processos_dados[0]["veiculo"] if processos_dados else ""
        contato = buscar_contato(contatos, veiculo_ref, cnpj=cnpj_veiculo)

        if not contato or not contato.get("email"):
            sem_contato.append({"pi": num_pi, "veiculo": veiculo_ref})
        else:
            email_dict = montar_email_correcao_agrupado(
                pi_data,
                processos_com_nc,
                {**contato, "nome": veiculo_ref},
            )
            try:
                draft_id_unico = _criar_rascunho(gmail, email_dict)
                email_enviado_str = "Rascunho criado"
                data_email_str = hoje
                rascunhos.append({
                    "pi":       num_pi,
                    "veiculo":  veiculo_ref,
                    "parecer":  " | ".join(p["parecer"] for p in processos_com_nc),
                    "draft_id": draft_id_unico,
                    "to":       email_dict["to"],
                })
            except Exception as e:
                erros.append({"pi": num_pi, "erro": f"Gmail: {e}"})

    # ── Passo 3: registrar cada processo no Sheets (uma linha por processo) ────
    for pd in processos_dados:
        # O draft_id fica na linha apenas se esse processo contribuiu para o e-mail
        proc_tem_email = pd["parecer"] in PARECERES_COM_EMAIL
        row = [
            hoje, num_pi, pd["veiculo"], pd["cliente"], pd["campanha"], pd["periodo"],
            pd["parecer"], pd["nc_str"], "Pendente",
            email_enviado_str if proc_tem_email else "Não",
            data_email_str if proc_tem_email else "",
            draft_id_unico if proc_tem_email else "",
            pd["proc"].get("nome", ""), "",
        ]
        try:
            sheets.spreadsheets().values().append(
                spreadsheetId=SHEET_ID,
                range=f"'{ABA_ACOMPANHAMENTO}'!A1",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
            registrados.append({
                "pi":      num_pi,
                "processo": pd["proc"].get("nome", ""),
                "parecer":  pd["parecer"],
            })
        except Exception as e:
            erros.append({"pi": num_pi, "erro": f"Sheets: {e}"})

    return {
        "registrados": registrados,
        "rascunhos":   rascunhos,
        "sem_contato": sem_contato,
        "erros":       erros,
    }
