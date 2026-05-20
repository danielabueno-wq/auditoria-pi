"""
gerar_token.py — Gera o token de autenticação Google para um usuário.

Execute este script uma única vez na sua máquina para autorizar o acesso
ao Gmail e Google Sheets. O token gerado deve ser enviado ao administrador
para ser configurado no Streamlit Cloud.

Uso:
    python3 gerar_token.py rodrigo
"""
import json
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 gerar_token.py SEU_NOME")
        print("Exemplo: python3 gerar_token.py rodrigo")
        sys.exit(1)

    username = sys.argv[1].lower().strip()
    creds_path = Path(__file__).parent / "credentials.json"
    token_path = Path(__file__).parent / f"token_{username}.json"

    if not creds_path.exists():
        print("❌ Arquivo credentials.json não encontrado nesta pasta.")
        print("   Peça o arquivo credentials.json ao administrador e coloque")
        print("   na mesma pasta deste script.")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("❌ Dependências não instaladas. Execute:")
        print("   pip install google-auth google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    print(f"\n🔑 Gerando token para o usuário: {username}")
    print("   O navegador vai abrir para você autorizar o acesso ao Google.")
    print("   Faça login com seu e-mail corporativo.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json())

    print(f"\n✅ Token gerado com sucesso: {token_path.name}")
    print("\n" + "="*60)
    print("PRÓXIMO PASSO: envie o conteúdo abaixo ao administrador")
    print("="*60)
    print(token_path.read_text())
    print("="*60)
    print(f"\nOu envie o arquivo: {token_path.absolute()}")

if __name__ == "__main__":
    main()
