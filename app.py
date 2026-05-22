"""
Interface web para o sistema de auditoria de PIs.
Execute com: streamlit run app.py
"""
import base64
import os
import tempfile
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Sistema de Auditoria Bueno",
    page_icon="🔴",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Identidade visual Bueno
# ---------------------------------------------------------------------------

def _load_logo_b64() -> str:
    logo_path = Path(__file__).parent / "assets" / "logo_bueno.png"
    if logo_path.exists():
        return base64.b64encode(logo_path.read_bytes()).decode()
    return ""

def _inject_css() -> None:
    logo_b64 = _load_logo_b64()
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="height:64px;">' if logo_b64 else ""

    st.markdown(f"""
    <style>
        /* Fonte global */
        html, body, [class*="css"] {{ font-family: 'Helvetica Neue', Arial, sans-serif; }}

        /* Cabeçalho vermelho Bueno */
        .bueno-header {{
            background-color: #C8102E;
            padding: 20px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-radius: 8px;
            margin-bottom: 24px;
        }}
        .bueno-header-title {{
            color: white;
            font-size: 1.4rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            line-height: 1.2;
        }}
        .bueno-header-sub {{
            color: rgba(255,255,255,0.8);
            font-size: 0.8rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-top: 2px;
        }}

        /* Botão primário vermelho */
        .stButton > button[kind="primary"] {{
            background-color: #C8102E !important;
            border: none !important;
            color: white !important;
            font-weight: 600 !important;
            border-radius: 6px !important;
            padding: 10px 24px !important;
            font-size: 1rem !important;
            transition: background-color 0.2s;
        }}
        .stButton > button[kind="primary"]:hover {{
            background-color: #A00C24 !important;
        }}

        /* Divisor vermelho */
        hr {{ border-color: #C8102E22 !important; }}

        /* Badge de status */
        .status-badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.78rem;
            font-weight: 600;
        }}

        /* Rodapé */
        .bueno-footer {{
            margin-top: 48px;
            padding-top: 16px;
            border-top: 2px solid #C8102E;
            text-align: center;
            color: #888;
            font-size: 0.75rem;
        }}
        .bueno-footer strong {{ color: #C8102E; }}

        /* Remove o menu padrão do Streamlit no topo */
        #MainMenu {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}
    </style>

    <div class="bueno-header">
        <div>
            <div class="bueno-header-title">Sistema de Auditoria Bueno</div>
            <div class="bueno-header-sub">Verificação de PIs e Processos Administrativos</div>
        </div>
        {logo_html}
    </div>
    """, unsafe_allow_html=True)

TIPOS_ACEITOS = ["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg", "tiff", "bmp", "webp", "txt"]

_inject_css()

# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

def _check_password() -> bool:
    users: dict = st.secrets.get("users", {})
    if not users:
        st.error("Nenhum usuário configurado em secrets.toml.")
        return False

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = ""

    if st.session_state.authenticated:
        return True

    st.markdown("### Acesso restrito")
    st.markdown("Entre com suas credenciais para acessar o sistema.")
    st.markdown("")

    with st.form("login"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar", type="primary", use_container_width=True)

    if submitted:
        if username in users and users[username] == password:
            st.session_state.authenticated = True
            st.session_state.username = username
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")

    return False


if not _check_password():
    st.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_google_token(username: str | None) -> str | None:
    """Lê o token Google do usuário a partir dos Secrets do Streamlit (produção)."""
    if not username:
        return None
    tokens = st.secrets.get("google_tokens", {})
    return tokens.get(username) or None


def _save_upload(uploaded_file) -> Path:
    suffix = Path(uploaded_file.name).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded_file.getbuffer())
    tmp.close()
    # Renomeia para preservar o nome original (usado nos relatórios)
    named = Path(tmp.name).parent / uploaded_file.name
    Path(tmp.name).rename(named)
    return named


def _status_badge(status: str) -> str:
    icons = {
        "Conforme": "🟢",
        "Não Conforme": "🔴",
        "Ausente": "🟡",
        "Não Verificável": "⚪",
        "Não Aplicável": "➖",
        "Consistente": "🟢",
        "Inconsistente": "🔴",
        "Parcialmente Consistente": "🟡",
        "Ausente em alguns": "🟡",
    }
    return f"{icons.get(status, '•')} {status}"


def _render_veiculacao(section: dict) -> None:
    status = section.get("status", "—")
    itens = section.get("itens", {})
    with st.expander(f"Veiculação / Comprovante — {_status_badge(status)}", expanded=(status == "Não Conforme")):
        # Quantidade
        qtd = itens.get("quantidade", {})
        if qtd:
            contratada = qtd.get("contratada")
            comprovada = qtd.get("comprovada")
            s = qtd.get("status", "—")
            col1, col2, col3 = st.columns(3)
            col1.metric("Contratadas", contratada or "—")
            col2.metric("Comprovadas", comprovada or "—", delta=None if not contratada else (comprovada or 0) - contratada)
            col3.markdown(f"**Status:** {_status_badge(s)}")
            if qtd.get("observacao"):
                st.warning(qtd["observacao"])

        # Faixa horária
        faixa = itens.get("faixa_horaria", {})
        if faixa:
            s = faixa.get("status", "—")
            st.markdown(f"**Faixa horária contratada:** {faixa.get('faixa_contratada') or '—'} — {_status_badge(s)}")
            if faixa.get("abatimento_indicado"):
                st.error("⚠️ Abatimento de pagamento indicado por veiculações fora da faixa horária.")
            fora = faixa.get("veiculacoes_fora_da_faixa", [])
            if fora:
                st.markdown(f"**{len(fora)} veiculação(ões) fora da faixa:**")
                for v in fora:
                    st.markdown(f"- {v.get('data','')} às {v.get('horario','')} — {v.get('programa') or 'programa não identificado'}")
            if faixa.get("observacao"):
                st.info(faixa["observacao"])

        # Período
        periodo = itens.get("periodo", {})
        if periodo and periodo.get("status") != "Conforme":
            st.warning(f"**Período:** {_status_badge(periodo.get('status','—'))} — {periodo.get('divergencia') or ''}")


def _render_financeiro(section: dict) -> None:
    status = section.get("status", "—")
    itens = section.get("itens", {})
    with st.expander(f"Financeiro — {_status_badge(status)}", expanded=(status == "Não Conforme")):
        rows = []
        skip = {"nf_dados_ausentes", "acao_corretiva_nf"}
        for key, val in itens.items():
            if key in skip or not isinstance(val, dict):
                continue
            label = key.replace("_", " ").title()
            item_status = val.get("status", "—")
            details_parts = []
            if val.get("processo") and val.get("pi"):
                details_parts.append(f"Processo: **{val['processo']}** · PI: **{val['pi']}**")
            if val.get("divergencia"):
                details_parts.append(f"_{val['divergencia']}_")
            if val.get("valor"):
                details_parts.append(f"Valor: {val['valor']}")
            rows.append({"Item": label, "Status": _status_badge(item_status), "Detalhes": " · ".join(details_parts) or "—"})
        if rows:
            st.table(rows)

        dados_ausentes = itens.get("nf_dados_ausentes", [])
        if dados_ausentes:
            st.warning(f"**Dados ausentes na NF:** {', '.join(dados_ausentes)}")

        acao = itens.get("acao_corretiva_nf")
        if acao:
            st.info(f"📋 **Ação corretiva recomendada:** {acao}")


def _render_dimension(title: str, section: dict) -> None:
    status = section.get("status", "—")
    with st.expander(f"{title} — {_status_badge(status)}", expanded=(status == "Não Conforme")):
        rows = []
        for key, val in section.get("itens", {}).items():
            if not isinstance(val, dict):
                continue
            label = key.replace("_", " ").title()
            item_status = val.get("status", "—")
            details_parts = []
            if val.get("processo") and val.get("pi"):
                details_parts.append(f"Processo: **{val['processo']}** · PI: **{val['pi']}**")
            if val.get("divergencia"):
                details_parts.append(f"_{val['divergencia']}_")
            if val.get("observacao"):
                details_parts.append(val["observacao"])
            if val.get("divergencias"):
                details_parts.extend(val["divergencias"])
            rows.append({
                "Item": label,
                "Status": _status_badge(item_status),
                "Detalhes": " · ".join(details_parts) if details_parts else "—",
            })
        if rows:
            st.table(rows)


def _render_consistency(consistency: dict) -> None:
    status_geral = consistency.get("status_geral", "—")
    st.subheader(f"Consistência entre Processos: {_status_badge(status_geral)}")

    inconsistencias = consistency.get("inconsistencias", [])
    if inconsistencias:
        st.warning("**Inconsistências encontradas:**\n" + "\n".join(f"- {i}" for i in inconsistencias))

    campos = consistency.get("campos_analisados", {})
    if campos:
        rows = []
        for campo, val in campos.items():
            if isinstance(val, dict):
                s = val.get("status", "—")
                div = val.get("divergencia") or "—"
                valores = val.get("valores", {})
                valores_str = " · ".join(f"{k}: *{v}*" for k, v in valores.items()) if valores else "—"
                rows.append({"Campo": campo.replace("_", " ").title(), "Status": _status_badge(s), "Valores por arquivo": valores_str, "Divergência": div})
        st.table(rows)

    obs = consistency.get("observacoes")
    if obs:
        st.info(obs)


def _render_processo_result(proc: dict, index: int) -> None:
    auditoria = proc.get("auditoria", {})
    parecer = auditoria.get("parecer_conclusivo", "Não determinado")
    justificativa = auditoria.get("justificativa_parecer", "")
    recomendacoes = auditoria.get("recomendacoes", [])

    parecer_fn = {
        "Aprovado": st.success,
        "Aprovado com Ressalvas": st.warning,
        "Reprovado": st.error,
    }.get(parecer, st.info)

    parecer_fn(f"**Parecer: {parecer}**")

    if justificativa:
        st.write(justificativa)

    if recomendacoes:
        st.write("**Recomendações:**")
        for r in recomendacoes:
            st.write(f"- {r}")

    _render_dimension("Validação de Dados", auditoria.get("validacao_dados", {}))
    _render_veiculacao(auditoria.get("veiculacao", {}))
    _render_dimension("Formalização", auditoria.get("formalizacao", {}))
    _render_financeiro(auditoria.get("financeiro", {}))


# ---------------------------------------------------------------------------
# Interface principal
# ---------------------------------------------------------------------------

col_user, col_sair = st.columns([5, 1])
with col_user:
    st.markdown(f"<span style='color:#888;font-size:0.85rem;'>Logado como <strong>{st.session_state.username}</strong></span>", unsafe_allow_html=True)
with col_sair:
    if st.button("Sair"):
        st.session_state.authenticated = False
        st.rerun()

st.divider()

# ── Navegação por abas ────────────────────────────────────────────────────────
tab_auditoria, tab_cobranca = st.tabs(["📄 Auditoria de PIs", "📋 Cobranças de NF"])


# ═════════════════════════════════════════════════════════════════════════════
# ABA 1 — AUDITORIA DE PIs (funcionalidade original)
# ═════════════════════════════════════════════════════════════════════════════
with tab_auditoria:
    st.markdown("### Upload dos documentos")

    pi_file = st.file_uploader(
        "PI — Pedido de Inserção",
        type=TIPOS_ACEITOS,
        key="pi",
    )

    processo_files = st.file_uploader(
        "Processos Administrativos (selecione um ou mais)",
        type=TIPOS_ACEITOS,
        accept_multiple_files=True,
        key="processos",
    )

    nome = st.text_input(
        "Nome da auditoria (opcional)",
        placeholder="ex: Campanha Verão 2026",
    )

    st.divider()

    pronto = pi_file is not None and len(processo_files) > 0
    run_button = st.button(
        "Auditar",
        type="primary",
        disabled=not pronto,
        use_container_width=True,
    )

    if not pronto:
        st.info("Faça upload do PI e de pelo menos um Processo Administrativo para habilitar a auditoria.")

    if run_button and pronto:
        api_key = st.secrets.get("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
        if not api_key:
            st.error("ANTHROPIC_API_KEY não configurada em secrets.toml.")
            st.stop()

        os.environ["ANTHROPIC_API_KEY"] = api_key

        tmp_files: list[Path] = []
        try:
            n = len(processo_files)
            msg = f"Processando {n} processo(s) + PI e consultando a IA… (pode levar {n * 1}–{n * 2} minutos)"
            with st.spinner(msg):
                from src.audit_engine import audit_multiple_documents
                from src.report_generator import save_reports

                pi_tmp = _save_upload(pi_file)
                tmp_files.append(pi_tmp)

                processo_tmps: list[Path] = []
                for pf in processo_files:
                    p = _save_upload(pf)
                    tmp_files.append(p)
                    processo_tmps.append(p)

                result = audit_multiple_documents(processo_tmps, pi_tmp)

            base_name = nome.strip() or f"auditoria_pi_{pi_file.name}"
            json_path, md_path = save_reports(result, base_name)

            # Persiste resultado para sobreviver a re-renders causados por outros botões
            st.session_state["ultimo_resultado"] = result
            st.session_state["ultimo_json_bytes"] = json_path.read_bytes()
            st.session_state["ultimo_json_nome"] = json_path.name
            st.session_state["ultimo_md_bytes"] = md_path.read_bytes()
            st.session_state["ultimo_md_nome"] = md_path.name
            st.session_state.pop("acomp_resultado", None)

        except Exception as exc:
            st.error(f"Erro durante a auditoria: {exc}")
            raise
        finally:
            for tmp in tmp_files:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    # ── Exibe resultado da última auditoria (persiste via session_state) ────────
    if "ultimo_resultado" in st.session_state:
        _result = st.session_state["ultimo_resultado"]
        _processos = _result.get("processos", [])
        _n = len(_processos)

        st.success("Auditoria concluída!")
        st.divider()

        consistency = _result.get("consistencia_entre_processos")
        if consistency and _n > 1:
            _render_consistency(consistency)
            st.divider()

        st.subheader("Resultado por Processo")
        if _n == 1:
            _render_processo_result(_processos[0], 1)
        else:
            inner_tabs = st.tabs([p.get("nome", f"Processo {i+1}") for i, p in enumerate(_processos)])
            for inner_tab, proc in zip(inner_tabs, _processos):
                with inner_tab:
                    _render_processo_result(proc, 0)

        st.divider()
        st.subheader("Baixar relatório")
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="Baixar JSON",
                data=st.session_state["ultimo_json_bytes"],
                file_name=st.session_state["ultimo_json_nome"],
                mime="application/json",
                use_container_width=True,
            )
        with col2:
            st.download_button(
                label="Baixar Markdown",
                data=st.session_state["ultimo_md_bytes"],
                file_name=st.session_state["ultimo_md_nome"],
                mime="text/markdown",
                use_container_width=True,
            )

        # ── Registro e solicitação de correções ──────────────────────────────
        st.divider()
        st.subheader("📋 Registrar e Acompanhar")

        _username = st.session_state.get("username")
        _token_json = _get_google_token(_username)
        _creds_acomp = (Path(__file__).parent / "credentials.json").exists() or bool(_token_json)
        if not _creds_acomp:
            st.info(
                "Configure o `credentials.json` para registrar na planilha "
                "e enviar e-mails de correção ao veículo (veja a aba Cobranças de NF)."
            )
        else:
            try:
                from cobranca_pis import token_existe, autenticar
                _token_ok = token_existe(_username, token_json=_token_json)
            except ImportError:
                _token_ok = False

            if not _token_ok:
                st.warning(
                    "Sua conta Gmail não está configurada nos Secrets do Streamlit. "
                    "Peça ao administrador para adicionar seu token Google nos Secrets."
                )
            else:
                _pareceres = [
                    p.get("auditoria", {}).get("parecer_conclusivo", "")
                    for p in _processos
                ]
                _n_problemas = sum(
                    1 for p in _pareceres if p in {"Reprovado", "Aprovado com Ressalvas"}
                )

                _col_btn, _col_info = st.columns([2, 3])
                with _col_btn:
                    _reg_btn = st.button(
                        "📋 Registrar e solicitar correções",
                        type="primary",
                        use_container_width=True,
                        key="btn_registrar",
                    )
                with _col_info:
                    if _n_problemas > 0:
                        st.warning(
                            f"⚠️ {_n_problemas} processo(s) com pendências — "
                            "rascunhos de correção serão criados no seu Gmail."
                        )
                    else:
                        st.info("Todos aprovados — apenas o registro será criado na planilha.")

                if _reg_btn:
                    with st.spinner("Registrando na planilha e criando rascunhos de correção…"):
                        try:
                            from src.acompanhamento import registrar_e_solicitar_correcoes
                            _ar = registrar_e_solicitar_correcoes(_result, username=_username, token_json=_token_json)
                            st.session_state["acomp_resultado"] = _ar
                        except Exception as _exc:
                            st.error(f"Erro ao registrar: {_exc}")
                            raise

                if "acomp_resultado" in st.session_state:
                    _ar = st.session_state["acomp_resultado"]
                    _c1, _c2, _c3, _c4 = st.columns(4)
                    _c1.metric("Registrados", len(_ar.get("registrados", [])))
                    _c2.metric("Rascunhos criados", len(_ar.get("rascunhos", [])))
                    _c3.metric("Sem contato", len(_ar.get("sem_contato", [])))
                    _c4.metric("Erros", len(_ar.get("erros", [])))

                    if _ar.get("rascunhos"):
                        st.success(
                            f"✅ {len(_ar['rascunhos'])} rascunho(s) criados no seu Gmail. "
                            "Confira em Rascunhos antes de enviar."
                        )
                    if _ar.get("sem_contato"):
                        with st.expander(f"⚠️ {len(_ar['sem_contato'])} veículo(s) sem e-mail cadastrado"):
                            for _item in _ar["sem_contato"]:
                                st.write(f"• **{_item['veiculo']}** — PI {_item['pi']}")
                    if _ar.get("erros"):
                        with st.expander(f"❌ {len(_ar['erros'])} erro(s)"):
                            for _item in _ar["erros"]:
                                st.write(f"• PI {_item['pi']}: {_item['erro']}")


# ═════════════════════════════════════════════════════════════════════════════
# ABA 2 — COBRANÇAS DE NF
# ═════════════════════════════════════════════════════════════════════════════
with tab_cobranca:
    import datetime as _dt

    # Verificar se cobranca_pis está disponível e configurado
    try:
        import cobranca_pis as _cob
        _modulo_ok = True
    except ImportError:
        _modulo_ok = False

    _cob_username  = st.session_state.get("username")
    _cob_token_json = _get_google_token(_cob_username)
    _creds_ok = (Path(__file__).parent / "credentials.json").exists() or bool(_cob_token_json)

    if not _modulo_ok or not _creds_ok:
        st.markdown("### ⚙️ Configuração necessária")
        st.warning(
            "O módulo de cobranças ainda não está configurado. "
            "Siga os passos abaixo para ativar:"
        )
        with st.expander("📋 Passo a passo de configuração", expanded=True):
            st.markdown("""
**1. Instalar dependências**
```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

**2. Criar credenciais no Google Cloud**
- Acesse [console.cloud.google.com](https://console.cloud.google.com)
- Crie (ou selecione) um projeto
- Ative as APIs: **Gmail API** e **Google Sheets API**
- Vá em **Credenciais → Criar credenciais → ID do cliente OAuth 2.0**
- Tipo: **App para computador (Desktop)**
- Baixe o arquivo e salve como **`credentials.json`** na pasta `~/auditoria-pi/`

**3. Autorizar na primeira execução**
```bash
cd ~/auditoria-pi
python cobranca_pis.py --dry-run
```
Um browser vai abrir para você autorizar o acesso. Depois, o `token.json` é salvo automaticamente.

**4. Recarregar esta página** — a aba de cobranças estará pronta.
            """)
        if not _modulo_ok:
            st.error("`cobranca_pis.py` não encontrado na pasta do projeto.")
        st.stop()

    # ── Verificar token do usuário logado ────────────────────────────────────
    # (_cob_username e _cob_token_json já definidos acima, antes do bloco if/else)
    _cob_token_ok = _cob.token_existe(_cob_username, token_json=_cob_token_json)

    if not _cob_token_ok:
        st.warning(
            "Sua conta Gmail não está configurada nos Secrets do Streamlit. "
            "Peça ao administrador para adicionar seu token Google nos Secrets."
        )
        st.divider()

    # ── Cobranças ─────────────────────────────────────────────────────────────
    st.markdown("### 📋 PIs Pendentes de Nota Fiscal")
    st.caption(
        "Campanhas encerradas com NF ainda não recebida e sem cobrança registrada. "
        "Fonte: planilha **Controle_PIs_Bueno** no Google Sheets."
    )

    col_ref, col_data = st.columns([1, 4])
    with col_ref:
        if st.button("🔄 Atualizar"):
            st.session_state.pop("pendentes_cache", None)
    with col_data:
        st.caption(f"Referência: {_dt.date.today().strftime('%d/%m/%Y')}")

    # Carregar pendentes
    if "pendentes_cache" not in st.session_state:
        with st.spinner("Consultando planilha..."):
            try:
                st.session_state["pendentes_cache"] = _cob.listar_pendentes_para_streamlit(
                    username=_cob_username, token_json=_cob_token_json
                )
            except Exception as _e:
                st.error(f"Erro ao ler planilha: {_e}")
                st.session_state["pendentes_cache"] = []

    _pendentes = st.session_state.get("pendentes_cache", [])

    # Métricas
    if _pendentes:
        _m1, _m2, _m3 = st.columns(3)
        _m1.metric("PIs pendentes", len(_pendentes))
        _m2.metric("Mais antigo", f"{max(p['dias_atraso'] for p in _pendentes)} dias")
        _total_vl = 0.0
        for _p in _pendentes:
            try:
                _total_vl += float(
                    str(_p.get("vl_liquido", "0"))
                    .replace(".", "").replace(",", ".")
                )
            except Exception:
                pass
        _m3.metric(
            "Volume total",
            f"R$ {_total_vl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )

    # Tabela
    if _pendentes:
        import pandas as _pd

        _df = _pd.DataFrame(_pendentes)[[
            "pi", "veiculo", "cliente", "titulo", "fim_pub", "dias_atraso", "vl_liquido", "responsavel"
        ]].rename(columns={
            "pi": "# PI", "veiculo": "Veículo", "cliente": "Cliente",
            "titulo": "Campanha", "fim_pub": "Fim Publicação",
            "dias_atraso": "Dias Atraso", "vl_liquido": "Valor Líq.",
            "responsavel": "Responsável",
        })

        def _cor_urgencia(row):
            if row["Dias Atraso"] >= 30:
                return ["background-color:#ffe0e0"] * len(row)
            if row["Dias Atraso"] >= 14:
                return ["background-color:#fff3cd"] * len(row)
            return [""] * len(row)

        st.dataframe(
            _df.style.apply(_cor_urgencia, axis=1),
            use_container_width=True,
            height=min(420, 60 + len(_df) * 38),
        )
        st.caption("🔴 ≥ 30 dias de atraso  |  🟡 ≥ 14 dias")
    else:
        st.success("✅ Nenhum PI pendente de NF no momento!")

    st.divider()

    # ── Cobrar PI específico ──────────────────────────────────────────────────
    st.markdown("#### 📨 Cobrar PI específico")
    with st.form("form_cobrar_pi"):
        _col_pi, _col_btn = st.columns([3, 1])
        with _col_pi:
            _pi_input = st.text_input(
                "Número do PI",
                placeholder="Ex: RJ 0003/2026  ou apenas  0003",
            )
        with _col_btn:
            st.write(""); st.write("")
            _cobrar_btn = st.form_submit_button("Cobrar", type="primary")

    if _cobrar_btn and _pi_input:
        with st.spinner(f"Criando rascunho para PI {_pi_input}..."):
            try:
                _res = _cob.cobrar_pi_especifico(_pi_input, username=_cob_username, token_json=_cob_token_json)
                if _res["cobrados"]:
                    st.success(f"✅ Rascunho criado no seu Gmail para o PI **{_pi_input}**! Confira em Rascunhos antes de enviar.")
                elif _res["pulados"]:
                    st.warning(f"⏭️ PI {_pi_input} já foi cobrado recentemente (e-mail encontrado no Gmail).")
                elif _res["sem_contato"]:
                    st.error("⚠️ Nenhum e-mail cadastrado para o veículo deste PI. Atualize a aba 'Contatos dos Veículos' no Google Sheets.")
                else:
                    st.info(f"ℹ️ PI '{_pi_input}' não encontrado ou campanha ainda não encerrada.")
            except Exception as _e:
                st.error(f"Erro: {_e}")

    st.divider()

    # ── Cobrar todos os pendentes ─────────────────────────────────────────────
    st.markdown("#### 🚀 Cobrar todos os pendentes")

    _col_opt1, _col_opt2 = st.columns(2)
    with _col_opt1:
        _dry_run = st.checkbox("Modo simulação (não cria rascunhos)", value=True)
    with _col_opt2:
        _force = st.checkbox("Ignorar verificação de duplicata", value=False)

    if _pendentes:
        _n = len(_pendentes)
        _label = f"🔍 Simular {_n} cobranças" if _dry_run else f"📨 Disparar {_n} cobranças"
        if st.button(_label, type="secondary" if _dry_run else "primary", use_container_width=True):
            with st.spinner("Processando..."):
                try:
                    _resultado = _cob.executar_cobranca(dry_run=_dry_run, force=_force, username=_cob_username, token_json=_cob_token_json)
                    _r1, _r2, _r3, _r4 = st.columns(4)
                    _r1.metric("Rascunhos criados", len(_resultado["cobrados"]))
                    _r2.metric("Já cobrados (pulados)", len(_resultado["pulados"]))
                    _r3.metric("Sem contato", len(_resultado["sem_contato"]))
                    _r4.metric("Erros", len(_resultado["erros"]))

                    if _resultado["cobrados"] and not _dry_run:
                        st.success(f"✅ {len(_resultado['cobrados'])} rascunho(s) criado(s) no Gmail!")
                    if _dry_run and _resultado["cobrados"]:
                        st.info(f"🔍 Simulação: {len(_resultado['cobrados'])} rascunho(s) seriam criados. Desmarque 'Modo simulação' para disparar.")
                    if _resultado["sem_contato"]:
                        with st.expander(f"⚠️ {len(_resultado['sem_contato'])} veículo(s) sem e-mail"):
                            for _item in _resultado["sem_contato"]:
                                st.write(f"• **{_item['veiculo']}** — PI {_item['pi']}")
                    if _resultado["erros"]:
                        with st.expander(f"❌ {len(_resultado['erros'])} erro(s)"):
                            for _item in _resultado["erros"]:
                                st.write(f"• PI {_item['pi']}: {_item['erro']}")
                except Exception as _e:
                    st.error(f"Erro ao processar cobranças: {_e}")
    else:
        st.info("Nenhum PI pendente para cobrar no momento.")

    st.divider()

    # ── Recobrança automática ─────────────────────────────────────────────────
    st.markdown("#### 🔁 Recobrança Automática")
    st.caption(
        "Verifica cobranças enviadas há 3+ dias úteis sem resposta do veículo "
        "e sem NF recebida — e cria rascunhos de follow-up no Gmail."
    )

    _col_rec1, _col_rec2 = st.columns([1, 3])
    with _col_rec1:
        _prazo_du = st.number_input(
            "Dias úteis sem resposta", min_value=1, max_value=30, value=3, step=1
        )
    with _col_rec2:
        _dry_rec = st.checkbox("Modo simulação (não cria rascunhos)", value=True, key="dry_rec")

    if st.button("🔁 Verificar e Recobrar", type="secondary" if _dry_rec else "primary", use_container_width=True):
        with st.spinner("Verificando histórico e Gmail..."):
            try:
                _res_rec = _cob.executar_recobranca(
                    dry_run=_dry_rec,
                    dias_uteis_prazo=int(_prazo_du),
                    username=_cob_username,
                    token_json=_cob_token_json,
                )
                _rr1, _rr2, _rr3, _rr4 = st.columns(4)
                _rr1.metric("Recobrança criada", len(_res_rec["recobrados"]))
                _rr2.metric("Pulados", len(_res_rec["pulados"]))
                _rr3.metric("Sem contato", len(_res_rec["sem_contato"]))
                _rr4.metric("Erros", len(_res_rec["erros"]))

                if _res_rec["recobrados"] and not _dry_rec:
                    st.success(
                        f"✅ {len(_res_rec['recobrados'])} rascunho(s) de recobrança criados no Gmail!"
                    )
                if _dry_rec and _res_rec["recobrados"]:
                    st.info(
                        f"🔍 Simulação: {len(_res_rec['recobrados'])} PI(s) precisariam de recobrança. "
                        "Desmarque 'Modo simulação' para criar os rascunhos."
                    )
                    with st.expander("Ver detalhes"):
                        for _item in _res_rec["recobrados"]:
                            st.write(
                                f"• PI **{_item['pi']}** — {_item['veiculo']} "
                                f"({_item['tentativa']}ª cobrança)"
                            )
                if _res_rec["pulados"]:
                    with st.expander(f"ℹ️ {len(_res_rec['pulados'])} PI(s) não precisam de recobrança"):
                        for _item in _res_rec["pulados"]:
                            st.write(f"• PI **{_item['pi']}** — {_item['motivo']}")
                if _res_rec["erros"]:
                    with st.expander(f"❌ {len(_res_rec['erros'])} erro(s)"):
                        for _item in _res_rec["erros"]:
                            st.write(f"• PI {_item['pi']}: {_item['erro']}")
            except Exception as _e:
                st.error(f"Erro ao processar recobrança: {_e}")

    st.divider()

    # ── Histórico ─────────────────────────────────────────────────────────────
    st.markdown("#### 📜 Histórico de Cobranças")
    st.caption("Registrado automaticamente na aba 'Histórico de Cobranças' do Google Sheets.")

    if st.button("🔎 Ver histórico recente"):
        with st.spinner("Carregando histórico..."):
            try:
                _sheets, _ = _cob.autenticar(username=_cob_username, token_json=_cob_token_json)
                _rows = _cob.ler_aba(_sheets, f"'{_cob.ABA_HISTORICO}'")
                if len(_rows) > 1:
                    import pandas as _pd2
                    _df_hist = _pd2.DataFrame(_rows[1:], columns=_rows[0])
                    st.dataframe(_df_hist.iloc[::-1].head(50), use_container_width=True)
                else:
                    st.info("Nenhum registro de cobrança ainda.")
            except Exception as _e:
                st.error(f"Erro ao carregar histórico: {_e}")


st.markdown("""
<div class="bueno-footer">
    <strong>Bueno Comunicação</strong> · Sistema de Auditoria de PIs · Uso interno restrito
</div>
""", unsafe_allow_html=True)
