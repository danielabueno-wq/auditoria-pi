"""
cobranca_pis.py — Automação de Cobrança de NFs para Veículos
=============================================================
Lê o Google Sheets "Controle_PIs_Bueno", identifica PIs com campanha
finalizada e Nota Fiscal não recebida, verifica duplicatas no Gmail,
e cria rascunhos de cobrança automaticamente.

COMO RODAR:
  python cobranca_pis.py              # execução normal
  python cobranca_pis.py --dry-run    # simula sem criar rascunhos
  python cobranca_pis.py --force      # ignora check de duplicata Gmail
  python cobranca_pis.py --pi RJ0003  # processa apenas um PI específico

INTEGRAÇÃO COM O STREAMLIT (auditoria-pi/app.py):
  from cobranca_pis import executar_cobranca
  resultado = executar_cobranca(dry_run=False)
  # resultado é um dict com chaves: cobrados, pulados, sem_contato, erros, detalhes

REQUISITOS:
  pip install google-auth google-auth-oauthlib google-api-python-client gspread

AUTENTICAÇÃO (primeira vez):
  1. console.cloud.google.com → projeto → Ativar: Gmail API + Google Sheets API
  2. Credenciais → OAuth2 Desktop → baixar como credentials.json
  3. Colocar credentials.json na mesma pasta deste script
  4. Na primeira execução um browser abre para autorizar — token.json é salvo.
=============================================================
"""

import os
import re
import json
import base64
import argparse
import datetime
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# ─── Configuração ──────────────────────────────────────────────────────────────

SHEET_ID        = "1BN5lKhcA_eVstgTW17JuRL3_F7OOpkepqEYl9ADYmnU"
ABA_PIS         = "Controle de PIs"
ABA_CONTATOS    = "Contatos dos Veículos"
ABA_HISTORICO   = "Histórico de Cobranças"   # criada automaticamente se não existir

# Remetente (conta Gmail autenticada)
REMETENTE_NOME  = "Bueno Comunicação DF"
REMETENTE_EMAIL = "daniela.bueno@buenocomunicacaodf.com.br"

ASSINATURA = """\
Atenciosamente,

Bueno Comunicação DF
Financeiro / Faturamento
faturamento@buenocomunicacaodf.com.br
"""

# Scopes OAuth — leitura+escrita no Sheets + rascunhos no Gmail
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# ─── Mapeamento de colunas — aba "Controle de PIs" (0-indexado) ───────────────
C_PI       = 1   # B  # PI
C_FONTE    = 2   # C  FONTE
C_AGENCIA  = 3   # D  AGÊNCIA
C_CLIENTE  = 4   # E  CLIENTE
C_TITULO   = 7   # H  TÍTULO
C_INI_PUB  = 8   # I  INI PUBLICAÇÃO
C_FIM_PUB  = 9   # J  FIM PUBLICAÇÃO
C_VEICULO  = 10  # K  VEÍCULO
C_VL_LIQ   = 14  # O  VALOR LÍQUIDO
C_NF       = 17  # R  # NF
C_DT_EMI   = 18  # S  DT EMISSÃO
C_DT_REC   = 19  # T  DT RECEBIMENTO
C_DT_VEN   = 20  # U  DT VENCIMENTO
C_DT_COB   = 21  # V  DT COBRANÇA
C_RESP     = 23  # X  RESPONSÁVEL

# ─── Mapeamento de colunas — aba "Contatos dos Veículos" (0-indexado) ─────────
CV_NOME    = 0   # A  Nome do Veículo (exato do sistema)
CV_CNPJ    = 1   # B  CNPJ do Veículo (ex: 11.692.592/0001-76)
CV_TIPO    = 2   # C  Tipo: radio / jornal / digital
CV_EMAIL   = 5   # F  E-mail Principal (Cobrança)
CV_CC      = 6   # G  E-mails em Cópia
CV_CONTATO = 7   # H  Pessoa de Contato
CV_TEL     = 8   # I  Telefone

# ─── Documentos cobrados por tipo de veículo ──────────────────────────────────
DOCS_POR_TIPO = {
    "radio": [
        "✅ Nota Fiscal / Fatura",
        "✅ Comprovante de Veiculação (Irradiação)",
        "✅ Artigo 299 (declaração de veiculação)",
    ],
    "jornal": [
        "✅ Nota Fiscal / Fatura",
        "✅ Comprovante de veiculação (print / recorte da página publicada)",
    ],
    "digital": [
        "✅ Nota Fiscal / Fatura",
        "✅ Comprovante de Veiculação (relatório de impressões / print da publicação)",
        "✅ Artigo 299 (declaração de veiculação)",
    ],
}
DOCS_PADRAO = [
    "✅ Nota Fiscal / Fatura",
    "✅ Comprovante de Veiculação",
]


# ══════════════════════════════════════════════════════════════════════════════
#  AUTENTICAÇÃO
# ══════════════════════════════════════════════════════════════════════════════
def autenticar(username: str | None = None, token_json: str | None = None):
    """
    Retorna (sheets_service, gmail_service) com OAuth2.

    Prioridade:
    1. token_json (string JSON passada pelo Streamlit Secrets) — para uso na nuvem
    2. token_<username>.json no disco — para uso local/desenvolvimento
    3. token.json padrão — comportamento original sem username
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None

    # 1. Token vindo dos Secrets do Streamlit (produção na nuvem)
    if token_json:
        creds = Credentials.from_authorized_user_info(
            json.loads(token_json), SCOPES
        )
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

    # 2. Token em arquivo local (desenvolvimento)
    if not creds or not creds.valid:
        token_filename = f"token_{username}.json" if username else "token.json"
        token_path = Path(__file__).parent / token_filename
        creds_path = Path(__file__).parent / "credentials.json"

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not creds_path.exists():
                    raise FileNotFoundError(
                        "credentials.json não encontrado.\n"
                        "Baixe em: console.cloud.google.com → Credenciais → OAuth2 Desktop"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

    sheets = build("sheets", "v4", credentials=creds)
    gmail  = build("gmail",  "v1",  credentials=creds)
    return sheets, gmail


def token_existe(username: str | None = None, token_json: str | None = None) -> bool:
    """Verifica se o token OAuth do usuário está disponível (secrets ou arquivo local)."""
    if token_json:
        return True
    filename = f"token_{username}.json" if username else "token.json"
    return (Path(__file__).parent / filename).exists()


# ══════════════════════════════════════════════════════════════════════════════
#  LEITURA DO GOOGLE SHEETS
# ══════════════════════════════════════════════════════════════════════════════
def ler_aba(sheets, aba: str) -> list[list]:
    """Lê todas as linhas de uma aba do Sheets."""
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=aba,
    ).execute()
    return resp.get("values", [])


def get_cell(row: list, idx: int, default="") -> str:
    """Acessa célula com segurança; retorna string limpa."""
    try:
        return str(row[idx]).strip()
    except IndexError:
        return default


def parse_data(s: str) -> datetime.date | None:
    """Converte DD/MM/YYYY ou YYYY-MM-DD para date."""
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def formatar_valor(v: str) -> str:
    """Tenta formatar como R$ X.XXX,XX ou retorna o valor bruto."""
    v = v.replace(".", "").replace(",", ".")
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return v


# ══════════════════════════════════════════════════════════════════════════════
#  IDENTIFICAÇÃO DE PIs PENDENTES
# ══════════════════════════════════════════════════════════════════════════════
def identificar_pendentes(
    rows: list[list],
    hoje: datetime.date,
    pi_filtro: str | None = None,
) -> list[dict]:
    """
    Retorna lista de dicts com PIs que atendem às 3 regras:
      1. # NF vazia (não recebida)
      2. FIM PUBLICAÇÃO <= hoje (campanha terminada)
      3. DT COBRANÇA vazia (ainda não foi cobrado)
    """
    pendentes = []

    for i, row in enumerate(rows[1:], start=2):  # pula cabeçalho
        num_pi    = get_cell(row, C_PI)
        if not num_pi:
            continue

        # Filtro por PI específico
        if pi_filtro and pi_filtro.lower() not in num_pi.lower():
            continue

        nf        = get_cell(row, C_NF)
        dt_cob    = get_cell(row, C_DT_COB)
        fim_pub_s = get_cell(row, C_FIM_PUB)

        # Regra 1: NF não recebida
        if nf:
            continue

        # Regra 3: DT COBRANÇA vazia
        if dt_cob:
            continue

        # Regra 2: campanha já terminou
        fim_pub = parse_data(fim_pub_s)
        if fim_pub is None or fim_pub > hoje:
            continue

        pendentes.append({
            "linha_sheet": i,
            "pi":          num_pi,
            "fonte":       get_cell(row, C_FONTE),
            "agencia":     get_cell(row, C_AGENCIA),
            "cliente":     get_cell(row, C_CLIENTE),
            "titulo":      get_cell(row, C_TITULO),
            "ini_pub":     get_cell(row, C_INI_PUB),
            "fim_pub":     fim_pub_s,
            "veiculo":     get_cell(row, C_VEICULO),
            "vl_liquido":  get_cell(row, C_VL_LIQ),
            "responsavel": get_cell(row, C_RESP),
            "dias_atraso": (hoje - fim_pub).days,
        })

    return pendentes


# ══════════════════════════════════════════════════════════════════════════════
#  CONTATOS DOS VEÍCULOS
# ══════════════════════════════════════════════════════════════════════════════
def _normalizar_cnpj(cnpj: str) -> str:
    """Remove formatação do CNPJ, deixando só dígitos."""
    return re.sub(r"\D", "", cnpj)


def carregar_contatos(rows: list[list]) -> dict[str, dict]:
    """
    Retorna dict indexado por nome do veículo.
    Cada entrada inclui o CNPJ normalizado para busca alternativa.
    Use buscar_contato() para localizar pelo nome OU pelo CNPJ.
    """
    contatos = {}
    for row in rows[1:]:  # pula cabeçalho
        nome = get_cell(row, CV_NOME)
        if not nome:
            continue
        email = get_cell(row, CV_EMAIL).replace("\n", "").strip()
        cc_raw = get_cell(row, CV_CC)
        cc_list = [e.strip() for e in re.split(r"[;,]", cc_raw) if e.strip() and "@" in e]
        cnpj_raw = get_cell(row, CV_CNPJ)
        contatos[nome] = {
            "email":   email,
            "cc":      cc_list,
            "tipo":    get_cell(row, CV_TIPO).lower(),
            "contato": get_cell(row, CV_CONTATO),
            "tel":     get_cell(row, CV_TEL),
            "cnpj":    cnpj_raw,
            "cnpj_digits": _normalizar_cnpj(cnpj_raw),
        }
    return contatos


def buscar_contato(contatos: dict[str, dict], nome: str, cnpj: str = "") -> dict | None:
    """
    Busca o contato pelo nome do veículo (exato) ou, se não encontrar,
    pelo CNPJ (apenas dígitos). Retorna None se não achar nenhum.
    """
    # 1. Tentativa exata pelo nome
    if nome in contatos:
        return contatos[nome]

    # 2. Fallback: busca pelo CNPJ normalizado
    if cnpj:
        cnpj_norm = _normalizar_cnpj(cnpj)
        if cnpj_norm:
            for dados in contatos.values():
                if dados["cnpj_digits"] == cnpj_norm:
                    return dados

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  VERIFICAÇÃO DE DUPLICATA NO GMAIL
# ══════════════════════════════════════════════════════════════════════════════
def ja_cobrado_no_gmail(gmail, num_pi: str, dias_busca: int = 60) -> bool:
    """
    Retorna True se já existe e-mail recente enviado pela conta que menciona
    o número do PI. Evita cobrar duas vezes o mesmo PI.
    """
    # Escapar caracteres especiais do número do PI
    pi_escaped = num_pi.replace("/", " ").replace("-", " ")
    query = (
        f'from:me subject:"{pi_escaped}" newer_than:{dias_busca}d'
    )
    try:
        result = gmail.users().messages().list(
            userId="me", q=query, maxResults=5
        ).execute()
        if result.get("messages"):
            return True
        # Tenta busca mais ampla só com o número
        query2 = f'from:me "{num_pi}" newer_than:{dias_busca}d'
        result2 = gmail.users().messages().list(
            userId="me", q=query2, maxResults=5
        ).execute()
        return bool(result2.get("messages"))
    except Exception as e:
        logging.warning(f"Erro ao verificar Gmail para PI {num_pi}: {e}")
        return False  # em caso de erro, não bloqueia


# ══════════════════════════════════════════════════════════════════════════════
#  MONTAGEM DO E-MAIL
# ══════════════════════════════════════════════════════════════════════════════
def montar_email(pi: dict, contato: dict) -> dict:
    """Monta o e-mail de cobrança adaptado ao tipo do veículo."""
    tipo    = contato.get("tipo", "")
    docs    = DOCS_POR_TIPO.get(tipo, DOCS_PADRAO)
    docs_str = "\n".join(docs)

    nome_contato = contato.get("contato") or contato.get("email", "").split("@")[0]
    vl = formatar_valor(pi["vl_liquido"]) if pi["vl_liquido"] else "conforme PI"

    # Determinar urgência pelo atraso
    dias = pi["dias_atraso"]
    if dias >= 30:
        urgencia = "⚠️ URGENTE — "
    elif dias >= 14:
        urgencia = "Atenção — "
    else:
        urgencia = ""

    assunto = (
        f"{urgencia}[COBRANÇA NF] PI {pi['pi']} — "
        f"{pi['veiculo']} — {pi['cliente']}"
    )

    corpo = f"""\
Prezado(a) {nome_contato},

Estamos entrando em contato referente ao PI abaixo, cuja campanha já foi encerrada e ainda \
não recebemos a documentação necessária para o faturamento.

────────────────────────────────────────────
  PI:          {pi['pi']}
  Cliente:     {pi['cliente']}
  Campanha:    {pi['titulo']}
  Veiculação:  {pi['ini_pub']} a {pi['fim_pub']}
  Veículo:     {pi['veiculo']}
  Valor Líq.:  {vl}
  Dias em aberto: {dias} dia(s)
────────────────────────────────────────────

Para regularizarmos o pagamento, precisamos dos seguintes documentos:

{docs_str}

Por favor, envie os documentos para faturamento@buenocomunicacaodf.com.br \
respondendo este e-mail ou pelo e-mail acima.

Em caso de dúvidas, estamos à disposição.

{ASSINATURA}"""

    return {
        "to":      contato["email"],
        "cc":      contato.get("cc", []),
        "assunto": assunto,
        "corpo":   corpo,
        "pi":      pi["pi"],
        "veiculo": pi["veiculo"],
    }


def criar_rascunho_gmail(gmail, email_dict: dict) -> str:
    """Cria rascunho no Gmail e retorna o draft ID."""
    msg = MIMEMultipart("alternative")
    msg["to"]      = email_dict["to"]
    msg["subject"] = email_dict["assunto"]
    if email_dict["cc"]:
        msg["cc"] = ", ".join(email_dict["cc"])
    msg.attach(MIMEText(email_dict["corpo"], "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = gmail.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}},
    ).execute()
    return draft["id"]


# ══════════════════════════════════════════════════════════════════════════════
#  REGISTRO NO HISTÓRICO (aba do Sheets)
# ══════════════════════════════════════════════════════════════════════════════
def garantir_aba_historico(sheets):
    """Cria a aba 'Histórico de Cobranças' se não existir."""
    meta = sheets.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    abas = [s["properties"]["title"] for s in meta["sheets"]]
    if ABA_HISTORICO in abas:
        return

    # Criar aba nova
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": ABA_HISTORICO}}}]},
    ).execute()

    # Cabeçalho
    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=f"'{ABA_HISTORICO}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [[
            "# PI", "Veículo", "Cliente", "Campanha",
            "Fim Publicação", "Valor Líq.", "Dias Atraso",
            "E-mail Destino", "Data Cobrança", "Status", "Draft ID",
        ]]},
    ).execute()


def registrar_historico(sheets, pi: dict, email_dict: dict, draft_id: str, status: str):
    """Appenda uma linha no Histórico de Cobranças."""
    garantir_aba_historico(sheets)
    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=f"'{ABA_HISTORICO}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [[
            pi["pi"],
            pi["veiculo"],
            pi["cliente"],
            pi["titulo"],
            pi["fim_pub"],
            formatar_valor(pi["vl_liquido"]) if pi["vl_liquido"] else "",
            pi["dias_atraso"],
            email_dict.get("to", ""),
            datetime.date.today().strftime("%d/%m/%Y"),
            status,
            draft_id,
        ]]},
    ).execute()


# ══════════════════════════════════════════════════════════════════════════════
#  FUNÇÃO PRINCIPAL — exportada para o Streamlit
# ══════════════════════════════════════════════════════════════════════════════
def executar_cobranca(
    dry_run: bool = False,
    force: bool = False,
    pi_filtro: str | None = None,
    hoje: datetime.date | None = None,
    username: str | None = None,
    token_json: str | None = None,
) -> dict:
    """
    Executa o fluxo completo de cobrança.

    Parâmetros:
      dry_run   — se True, identifica mas NÃO cria rascunhos
      force     — se True, ignora a verificação de duplicata no Gmail
      pi_filtro — processa apenas o PI cujo número contém essa string
      hoje      — data de referência (padrão: hoje)

    Retorna:
      {
        "cobrados":    [{"pi": ..., "veiculo": ..., "draft_id": ...}],
        "pulados":     [{"pi": ..., "veiculo": ..., "motivo": ...}],
        "sem_contato": [{"pi": ..., "veiculo": ...}],
        "erros":       [{"pi": ..., "erro": ...}],
        "total_pendentes": int,
      }
    """
    hoje = hoje or datetime.date.today()
    resultado = {"cobrados": [], "pulados": [], "sem_contato": [], "erros": [], "total_pendentes": 0}

    print(f"\n{'='*62}")
    print(f"  COBRANÇA DE NFs — CONTROLE DE PIs — {hoje.strftime('%d/%m/%Y')}")
    print(f"{'='*62}\n")

    # 1. Autenticar
    print("🔑 Autenticando no Google...")
    sheets, gmail = autenticar(username=username, token_json=token_json)
    print("   ✅ Autenticado.\n")

    # 2. Ler planilha
    print("📊 Lendo planilha Controle_PIs_Bueno...")
    rows_pis      = ler_aba(sheets, f"'{ABA_PIS}'")
    rows_contatos = ler_aba(sheets, f"'{ABA_CONTATOS}'")
    contatos      = carregar_contatos(rows_contatos)
    print(f"   {len(rows_pis)-1} PIs carregados | {len(contatos)} veículos cadastrados\n")

    # 3. Identificar pendentes
    pendentes = identificar_pendentes(rows_pis, hoje, pi_filtro)
    resultado["total_pendentes"] = len(pendentes)
    print(f"📋 PIs pendentes de NF (campanha encerrada, ainda não cobrados): {len(pendentes)}")

    if not pendentes:
        print("   Nada a fazer hoje. 🎉\n")
        return resultado

    print()

    # 4. Processar cada PI
    for pi in pendentes:
        num = pi["pi"]
        veiculo = pi["veiculo"]
        print(f"  ▶ PI {num} | {veiculo}")
        print(f"    Cliente: {pi['cliente']} | Atraso: {pi['dias_atraso']} dias")

        # Verificar contato (por nome ou CNPJ se disponível)
        contato = buscar_contato(contatos, veiculo)
        if not contato or not contato.get("email"):
            print(f"    ⚠️  Sem e-mail cadastrado para este veículo. Pulando.\n")
            resultado["sem_contato"].append({"pi": num, "veiculo": veiculo})
            if not dry_run:
                registrar_historico(sheets, pi, {}, "", "SEM_CONTATO")
            continue

        # Verificar duplicata no Gmail
        if not force and not dry_run:
            if ja_cobrado_no_gmail(gmail, num):
                print(f"    ⏭️  Já existe e-mail enviado para este PI. Pulando.\n")
                resultado["pulados"].append({"pi": num, "veiculo": veiculo, "motivo": "já cobrado no Gmail"})
                continue

        # Montar e-mail
        email_dict = montar_email(pi, contato)
        print(f"    📨 Para: {email_dict['to']}")
        if email_dict["cc"]:
            print(f"       CC: {', '.join(email_dict['cc'])}")
        print(f"    📌 Assunto: {email_dict['assunto']}")

        if dry_run:
            print(f"    🔍 [DRY-RUN] Rascunho NÃO criado.\n")
            resultado["cobrados"].append({"pi": num, "veiculo": veiculo, "draft_id": "dry-run"})
            continue

        # Criar rascunho
        try:
            draft_id = criar_rascunho_gmail(gmail, email_dict)
            registrar_historico(sheets, pi, email_dict, draft_id, "RASCUNHO_CRIADO")
            print(f"    ✅ Rascunho criado (ID: {draft_id})\n")
            resultado["cobrados"].append({"pi": num, "veiculo": veiculo, "draft_id": draft_id})
        except Exception as e:
            logging.error(f"Erro ao criar rascunho para PI {num}: {e}")
            resultado["erros"].append({"pi": num, "erro": str(e)})
            print(f"    ❌ Erro: {e}\n")

    # 5. Resumo
    print(f"\n{'='*62}")
    print(f"  RESUMO")
    print(f"  Pendentes encontrados : {resultado['total_pendentes']}")
    print(f"  Rascunhos criados     : {len(resultado['cobrados'])}")
    print(f"  Pulados (já cobrados) : {len(resultado['pulados'])}")
    print(f"  Sem contato cadastrado: {len(resultado['sem_contato'])}")
    print(f"  Erros                 : {len(resultado['erros'])}")
    print(f"{'='*62}\n")

    if resultado["sem_contato"]:
        print("⚠️  Veículos sem e-mail cadastrado (atualize a aba 'Contatos dos Veículos'):")
        for item in resultado["sem_contato"]:
            print(f"   • {item['veiculo']} (PI {item['pi']})")
        print()

    return resultado


# ══════════════════════════════════════════════════════════════════════════════
#  INTEGRAÇÃO STREAMLIT — funções auxiliares
# ══════════════════════════════════════════════════════════════════════════════
def listar_pendentes_para_streamlit(username: str | None = None, token_json: str | None = None) -> list[dict]:
    """
    Retorna lista de PIs pendentes sem criar rascunhos.
    Use no Streamlit para exibir a tabela de pendentes antes de disparar.
    """
    sheets, _ = autenticar(username=username, token_json=token_json)
    rows_pis = ler_aba(sheets, f"'{ABA_PIS}'")
    return identificar_pendentes(rows_pis, datetime.date.today())


def cobrar_pi_especifico(num_pi: str, username: str | None = None, token_json: str | None = None) -> dict:
    """
    Cobra um PI específico pelo número exato.
    Use no Streamlit para cobrar individualmente pelo botão.
    """
    return executar_cobranca(pi_filtro=num_pi, force=True, username=username, token_json=token_json)


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(
        description="Cobrança automática de NFs para veículos — Bueno Comunicação DF"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Identifica PIs pendentes mas NÃO cria rascunhos no Gmail"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Ignora verificação de duplicata no Gmail"
    )
    parser.add_argument(
        "--pi", metavar="NUMERO_PI",
        help="Processa apenas o PI cujo número contém esta string (ex: --pi 'RJ 0003')"
    )
    args = parser.parse_args()

    executar_cobranca(
        dry_run=args.dry_run,
        force=args.force,
        pi_filtro=args.pi,
    )
