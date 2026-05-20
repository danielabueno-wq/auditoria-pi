# Sistema de Auditoria de PIs

Ferramenta de auditoria automática que compara **Processos Administrativos** com **PIs (Pedidos de Inserção)** de publicidade, usando IA para detectar divergências e emitir parecer de conformidade.

---

## Modos de uso

A aplicação funciona de duas formas:

| Modo | Como rodar | Para quem |
|------|-----------|-----------|
| **Web (recomendado)** | Streamlit no navegador | Equipe, acesso remoto |
| **CLI** | Terminal / linha de comando | Uso local, automações |

---

## Deploy na Nuvem (Streamlit Cloud) — Recomendado

### Pré-requisitos
- Conta no [GitHub](https://github.com)
- Conta no [Streamlit Cloud](https://streamlit.io/cloud) (gratuito)
- Chave da [API da Anthropic](https://console.anthropic.com)

### Passo a passo

**1. Suba o código para o GitHub**
```bash
git init
git add .
git commit -m "primeiro commit"
git remote add origin https://github.com/seu-usuario/auditoria-pi.git
git push -u origin main
```

**2. Crie o app no Streamlit Cloud**
1. Acesse [share.streamlit.io](https://share.streamlit.io)
2. Clique em **New app**
3. Conecte ao repositório `auditoria-pi`
4. Defina o arquivo principal como `app.py`
5. Clique em **Advanced settings** → **Secrets**

**3. Configure os secrets no Streamlit Cloud**

Cole o conteúdo abaixo no campo de Secrets (substituindo pelos valores reais):
```toml
ANTHROPIC_API_KEY = "sk-ant-sua-chave-aqui"

[users]
admin = "senha-forte-aqui"
colaborador1 = "outra-senha-forte"
```

6. Clique em **Deploy** — em poucos minutos o app estará no ar com uma URL pública.

> **Segurança:** o arquivo `.streamlit/secrets.toml` está no `.gitignore` e nunca vai para o GitHub. Os secrets ficam apenas no Streamlit Cloud.

---

## Rodando Localmente (Interface Web)

```bash
# Instale dependências
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure secrets (edite o arquivo com sua chave e usuários)
# O arquivo .streamlit/secrets.toml já existe com exemplos

# Inicie o app
streamlit run app.py
```
Acesse `http://localhost:8501` no navegador.

---

## Uso via CLI (linha de comando)

### Requisitos
- Python 3.11+
- Chave de API da Anthropic (`ANTHROPIC_API_KEY`)
- Para OCR em imagens (opcional): [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) instalado no sistema

### Instalação
```bash
cd auditoria-pi
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sua-chave-aqui"
```

### Executando

```bash
# Coloque os arquivos em input/ e execute:
python main.py --processo processo_abc.pdf --pi pi_abc.pdf

# Com nome personalizado para os relatórios
python main.py --processo processo_abc.pdf --pi pi_abc.pdf --nome campanha_verão_2025
```

### Relatórios gerados em `output/`

```
auditoria-pi/
└── output/
    ├── campanha_verão_2025_20250518_143022.json
    └── campanha_verão_2025_20250518_143022.md
```

---

## Formatos Suportados

| Tipo        | Extensões                              |
|-------------|----------------------------------------|
| PDF         | `.pdf`                                 |
| Planilha    | `.xlsx`, `.xls`, `.csv`                |
| Imagem      | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.webp` |
| Texto       | `.txt`                                 |

Tamanho máximo por arquivo: **50 MB**

---

## O Que É Auditado

### Validação de Dados
Compara os seguintes campos entre o Processo e o PI:
- **Cliente**
- **Agência**
- **Campanha**
- **Veículo**
- **Período** (início e fim)
- **Inserções/Horários**

### Formalização
- Presença de **assinaturas** e **carimbos** em ambos os documentos
- Validação de **Cartas de Correção** (se existirem)

### Financeiro
- **Dados bancários** (banco, agência, conta, CNPJ, favorecido)
- **Número do PI**
- **Nome da campanha** na Nota Fiscal
- **Desconto padrão**

---

## Resultado da Auditoria

Cada item recebe um dos seguintes status:

| Status | Significado |
|--------|-------------|
| ✅ Conforme | Campo presente e igual nos dois documentos |
| ❌ Não Conforme | Divergência detectada |
| ⚠️ Ausente | Campo não encontrado em um ou ambos os documentos |
| ➖ Não Aplicável | Campo não se aplica a este documento |
| ❓ Não Verificável | Documento ilegível ou dados insuficientes |

### Pareceres Possíveis

| Parecer | Critério |
|---------|----------|
| ✅ **Aprovado** | Todos os itens obrigatórios conformes |
| ⚠️ **Aprovado com Ressalvas** | Divergências menores que não comprometem a operação |
| ❌ **Reprovado** | Divergências críticas ou ausência de dados essenciais |

---

## Estrutura do Projeto

```
auditoria-pi/
├── input/                  # Coloque os arquivos aqui
├── output/                 # Relatórios gerados
├── src/
│   ├── __init__.py
│   ├── audit_engine.py     # Integração com API do Claude
│   ├── document_processor.py  # Leitura de PDFs, planilhas e imagens
│   ├── report_generator.py    # Geração de JSON e Markdown
│   └── utils.py            # Logging e utilitários
├── config.py               # Configurações centrais
├── main.py                 # CLI
├── requirements.txt
└── README.md
```

---

## Dependências Opcionais

| Biblioteca | Função | Instalação |
|------------|--------|------------|
| `pdfplumber` | Extração de texto de PDFs | Incluída em `requirements.txt` |
| `pandas` + `openpyxl` | Leitura de planilhas | Incluída em `requirements.txt` |
| `pytesseract` + `Pillow` | OCR local em imagens | Requer Tesseract no sistema |

Se `pdfplumber` não estiver disponível, o PDF é enviado diretamente como imagem para análise visual pelo Claude. Se `pytesseract` não estiver disponível, o OCR é ignorado e o Claude analisa a imagem diretamente.

---

## Segurança e Privacidade

- Os arquivos **não são armazenados** nos servidores da Anthropic além do necessário para processar a requisição.
- A chave de API é lida exclusivamente via variável de ambiente `ANTHROPIC_API_KEY` — nunca hardcoded.
- Os relatórios gerados ficam apenas em `output/` na sua máquina.

---

## Solução de Problemas

**`ANTHROPIC_API_KEY não definida`**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

**`Arquivo não encontrado`**
Coloque o arquivo em `input/` ou forneça o caminho completo.

**`pandas não instalado`**
```bash
pip install pandas openpyxl
```

**OCR não funciona**
Instale o Tesseract: [instruções aqui](https://github.com/tesseract-ocr/tesseract#installing-tesseract).
O sistema funciona sem OCR — o Claude analisa as imagens diretamente.
