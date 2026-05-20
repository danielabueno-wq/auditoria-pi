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


def montar_email_correcao(pi_data: dict, processo: dict, contato: dict) -> dict:
    auditoria = processo.get("auditoria", {})
    extracao = processo.get("extracao", {})
    parecer = auditoria.get("parecer_conclusivo", "")
    nao_conformidades = _extrair_nao_conformidades(auditoria)
    recomendacoes = auditoria.get("recomendacoes", [])

    pi_extr = pi_data.get("extracao", {})
    num_pi = pi_extr.get("numero_pi") or pi_data.get("nome", "")
    cliente = extracao.get("cliente") or pi_extr.get("cliente") or ""
    campanha = extracao.get("campanha") or pi_extr.get("campanha") or ""
    veiculo = extracao.get("veiculo") or pi_extr.get("veiculo") or contato.get("nome", "")
    periodo = _periodo_str(extracao.get("periodo") or pi_extr.get("periodo"))

    nome_contato = contato.get("contato") or contato.get("email", "").split("@")[0]

    if parecer == "Reprovado":
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

    nc_str = (
        "\n".join(f"  • {nc}" for nc in nao_conformidades)
        if nao_conformidades
        else "  • Consulte o relatório de auditoria para detalhes."
    )

    rec_str = ""
    if recomendacoes:
        rec_str = "\nRECOMENDAÇÕES:\n\n" + "\n".join(f"  • {r}" for r in recomendacoes) + "\n"

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


def registrar_e_solicitar_correcoes(resultado: dict, username: str | None = None) -> dict:
    """
    Registra todos os processos na aba de acompanhamento do Sheets.
    Para pareceres não conformes, cria rascunhos de e-mail de correção no Gmail.

    Se `username` for informado, usa o token OAuth desse usuário — os rascunhos
    aparecem na conta Gmail do próprio usuário logado na plataforma.

    Retorna:
      {
        "registrados":  [{"pi", "processo", "parecer"}],
        "rascunhos":    [{"pi", "veiculo", "parecer", "draft_id", "to"}],
        "sem_contato":  [{"pi", "veiculo"}],
        "erros":        [{"pi", "erro"}],
      }
    """
    from cobranca_pis import autenticar, carregar_contatos, ler_aba, ABA_CONTATOS

    sheets, gmail = autenticar(username=username)
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

    for proc in resultado.get("processos", []):
        auditoria = proc.get("auditoria", {})
        extracao = proc.get("extracao", {})
        parecer = auditoria.get("parecer_conclusivo", "Não determinado")
        nao_conformidades = _extrair_nao_conformidades(auditoria)

        veiculo = extracao.get("veiculo") or pi_extr.get("veiculo") or ""
        cliente = extracao.get("cliente") or pi_extr.get("cliente") or ""
        campanha = extracao.get("campanha") or pi_extr.get("campanha") or ""
        periodo = _periodo_str(extracao.get("periodo") or pi_extr.get("periodo"))
        nc_str = " | ".join(nao_conformidades)

        draft_id = ""
        email_enviado = "Não"
        data_email = ""

        # Cria rascunho de correção para processos com pendências
        if parecer in PARECERES_COM_EMAIL:
            contato = contatos.get(veiculo)
            if not contato or not contato.get("email"):
                sem_contato.append({"pi": num_pi, "veiculo": veiculo})
            else:
                email_dict = montar_email_correcao(pi_data, proc, {**contato, "nome": veiculo})
                try:
                    draft_id = _criar_rascunho(gmail, email_dict)
                    email_enviado = "Rascunho criado"
                    data_email = hoje
                    rascunhos.append({
                        "pi": num_pi,
                        "veiculo": veiculo,
                        "parecer": parecer,
                        "draft_id": draft_id,
                        "to": email_dict["to"],
                    })
                except Exception as e:
                    erros.append({"pi": num_pi, "erro": f"Gmail: {e}"})

        row = [
            hoje, num_pi, veiculo, cliente, campanha, periodo,
            parecer, nc_str, "Pendente",
            email_enviado, data_email, draft_id,
            proc.get("nome", ""), "",
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
                "pi": num_pi,
                "processo": proc.get("nome", ""),
                "parecer": parecer,
            })
        except Exception as e:
            erros.append({"pi": num_pi, "erro": f"Sheets: {e}"})

    return {
        "registrados": registrados,
        "rascunhos": rascunhos,
        "sem_contato": sem_contato,
        "erros": erros,
    }
