"""
samba_crypto.py — Cifrado/descifrado de contraseñas Samba
==========================================================
Usa Fernet (AES-128-CBC + HMAC-SHA256) de la librería `cryptography`.

La clave de cifrado vive en la variable de entorno SAMBA_FERNET_KEY.
Nunca se guarda en código, en la BD ni en logs.

Generar la clave (una sola vez, guardar en .env):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    """Obtiene la instancia Fernet a partir de la variable de entorno."""
    key = os.getenv("SAMBA_FERNET_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "Variable de entorno SAMBA_FERNET_KEY no configurada. "
            "Genera una con: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def encrypt_password(plain: str) -> str:
    """
    Cifra una contraseña en texto plano.
    Retorna un token base64 para guardar en la base de datos.
    """
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """
    Descifra una contraseña desde la base de datos.
    Lanza ValueError si el token fue alterado o la clave es incorrecta.
    """
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken:
        raise ValueError(
            "No se pudo descifrar la contraseña Samba. "
            "Verifica que SAMBA_FERNET_KEY sea la misma clave con la que se cifró."
        )


def is_encrypted(value: str) -> bool:
    """
    Heurístico: los tokens Fernet siempre empiezan con 'gAAAAA'.
    Útil para detectar si un valor ya fue cifrado (ej. en la migración).
    """
    return value.startswith("gAAAAA")
