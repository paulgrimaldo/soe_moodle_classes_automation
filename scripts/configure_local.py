"""Create private local settings without printing secrets or overwriting existing settings."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists():
    print(".env ya existe; no se modifica.")
else:
    contents = (root / ".env.example").read_text()
    n8n_token = secrets.token_hex(32)
    for key, value in {
        "ACADEMIC_ADMIN_TOKEN": secrets.token_hex(32),
        "ACADEMIC_N8N_TOKEN": n8n_token,
        "N8N_BACKEND_TOKEN": n8n_token,
        "N8N_ENCRYPTION_KEY": secrets.token_hex(32),
    }.items():
        contents = contents.replace(f"{key}=\n", f"{key}={value}\n")
    with target.open("x") as output:
        target.chmod(0o600)
        output.write(contents)
    print("Configuración local creada en .env con permisos 0600. Publicación deshabilitada.")
