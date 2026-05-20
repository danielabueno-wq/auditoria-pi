# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the Streamlit web app (primary interface)
streamlit run app.py

# Run a single CLI audit
python main.py --processo input/processo.pdf --pi input/pi.pdf
python main.py --processo input/processo.pdf --pi input/pi.pdf --nome campanha_verao_2026

# Run the NF billing automation (dry-run — no Gmail drafts created)
python cobranca_pis.py --dry-run

# Run billing for a specific PI
python cobranca_pis.py --pi "RJ 0003/2026"

# First-time Google auth (opens browser)
python cobranca_pis.py --dry-run   # token.json is saved after authorization

# Install dependencies
pip install -r requirements.txt
```

No test suite or linter is configured yet.

## Architecture

This project has two independent systems that share the same Streamlit interface (`app.py`).

### System 1 — PI Audit Engine

Compares *Processos Administrativos* against *Pedidos de Inserção* (PIs) using the Claude API to detect compliance divergences and issue a formal `parecer`.

**Call flow (per audit):**
1. `document_processor.py` — reads and encodes files (PDF text + base64, spreadsheet → markdown table, image → base64 + optional OCR)
2. `audit_engine.py:extract_pi_data()` — **1 Haiku call** extracts structured JSON from the PI document
3. `audit_engine.py:extract_and_compare()` — **1 Opus call per processo** — extracts the processo data AND runs the full comparison against the PI JSON in a single call (avoids re-sending the PI document)
4. `audit_engine.py:check_consistency()` — **1 Opus call** (only when N > 1 processos) — checks consistency across all processos using only their JSON extractions (no documents re-sent)
5. `report_generator.py` — writes `output/<name>_<timestamp>.json` and `.md`

**Model assignment rationale:** Haiku for mechanical JSON extraction (5× cheaper), Opus with `thinking: adaptive` for reasoning-heavy comparison and parecer. System prompts use `cache_control: ephemeral` to reduce cost on repeated calls.

**Audit dimensions** (defined in `_EXTRACT_AND_COMPARE_PROMPT`):
- `validacao_dados` — cliente, agência, campanha, veículo, período, inserções
- `veiculacao` — quantidade comprovada vs contratada, faixa horária, período
- `formalizacao` — assinaturas e carimbos
- `financeiro` — dados bancários, número PI na NF, nome campanha na NF, desconto padrão

**Rede Gazeta rule:** When `rede_gazeta=true` and the NF is missing PI number/client/campaign/discount: PROPEG → suggest *Carta de Correção*; other government agencies → suggest direct NF correction.

### System 2 — NF Billing Automation (`cobranca_pis.py`)

Reads the **Controle_PIs_Bueno** Google Sheet (ID: `1BN5lKhcA_eVstgTW17JuRL3_F7OOpkepqEYl9ADYmnU`), identifies PIs needing billing, and creates Gmail draft emails.

**Billing rule** — a PI is billable when all three conditions are true:
- Column R (`# NF`) is empty — invoice not yet received
- Column J (`FIM PUBLICAÇÃO`) ≤ today — campaign has ended
- Column V (`DT COBRANÇA`) is empty — not yet billed

**Anti-duplicate check:** before creating a draft, searches Gmail for recent emails (`from:me`) mentioning the PI number. If found, skips.

**Email template** varies by vehicle type (from Sheet 2 `Contatos dos Veículos`, column B):
- `radio` → NF + Comprovante de Veiculação (Irradiação) + Artigo 299
- `jornal` → NF + print da página publicada
- `digital` → NF + Comprovante de Veiculação + Artigo 299

**After each run**, results are appended to a `Histórico de Cobranças` sheet (auto-created if missing).

**Streamlit integration:** `cobranca_pis.py` exports `listar_pendentes_para_streamlit()`, `executar_cobranca()`, and `cobrar_pi_especifico()`. The "📋 Cobranças de NF" tab in `app.py` calls these directly. If `credentials.json` is missing, the tab renders setup instructions instead.

### `app.py` — Streamlit Interface

Two tabs:
- **📄 Auditoria de PIs** — file upload → `audit_multiple_documents()` → renders results per processo with expandable sections for each dimension
- **📋 Cobranças de NF** — pending PI table, cobrar individual PI form, bulk dispatch with dry-run mode, histórico viewer

Authentication is handled via `st.secrets["users"]` (username → password dict). `ANTHROPIC_API_KEY` is also read from secrets.

### Configuration

- `config.py` — `INPUT_DIR`, `OUTPUT_DIR`, `SUPPORTED_EXTENSIONS`, `MAX_FILE_SIZE_MB` (50)
- `.streamlit/secrets.toml` (gitignored) — `ANTHROPIC_API_KEY`, `[users]` dict
- `credentials.json` (gitignored) — Google OAuth2 Desktop credentials for `cobranca_pis.py`
- `token.json` (gitignored, auto-generated) — saved Google OAuth token

### Google API Scopes (`cobranca_pis.py`)

```python
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]
```

Both `credentials.json` and `token.json` must be in the project root (`~/auditoria-pi/`).
