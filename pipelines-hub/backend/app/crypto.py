"""Cifrado de credenciales en reposo."""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.secret_key
    if not key:
        key_file = settings.data_dir / "secret.key"
        if key_file.exists():
            key = key_file.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            key_file.write_text(key)
            key_file.chmod(0o600)
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError(
            "No se pudo descifrar la credencial: cambió HUB_SECRET_KEY o data/secret.key"
        ) from e
