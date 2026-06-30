"""
media_token.py — Tokens HMAC de corta vida para servir recursos de archivos.

Problema que resuelve:
    Los navegadores no pueden enviar el header Authorization en peticiones
    originadas por <img src="...">, window.open() o links directos.
    Exponer el JWT de sesión en la URL es un antipatrón de seguridad grave
    (queda en historial del navegador, logs de servidor, header Referer, etc.).

Solución:
    Se genera un token efímero firmado con HMAC-SHA256 que codifica el path
    exacto del recurso y su tiempo de expiración. Solo es válido para ese
    recurso específico y solo por MEDIA_TOKEN_TTL_SECONDS segundos.
    El JWT de sesión nunca aparece en ninguna URL.

Configuración (.env):
    MEDIA_TOKEN_SECRET      — Clave secreta para firmar (obligatoria en producción).
                              Genera una con: python3 -c "import secrets; print(secrets.token_hex(32))"
    MEDIA_TOKEN_TTL_SECONDS — Vida útil en segundos (default: 600 = 10 min).
"""
import hmac
import hashlib
import time
import json
import base64
import os
import logging

logger = logging.getLogger(__name__)

MEDIA_TOKEN_SECRET: str = os.getenv("MEDIA_TOKEN_SECRET", "")
MEDIA_TOKEN_TTL: int = int(os.getenv("MEDIA_TOKEN_TTL_SECONDS", "600"))

# Advertencia en arranque si no hay secret configurado
_FALLBACK_SECRET = b"dev_fallback_NOT_FOR_PRODUCTION_CONFIGURE_MEDIA_TOKEN_SECRET"
if not MEDIA_TOKEN_SECRET:
    logger.warning(
        "MEDIA_TOKEN_SECRET no configurado en .env. "
        "Se usa clave de desarrollo. NO usar en producción."
    )


def _get_secret() -> bytes:
    return MEDIA_TOKEN_SECRET.encode() if MEDIA_TOKEN_SECRET else _FALLBACK_SECRET


def generate_media_token(
    *,
    area: str,
    subpath: str,
    filename: str,
    user_id: int,
) -> str:
    """
    Genera un media token HMAC-SHA256 de vida corta para un recurso específico.

    El token codifica: área, subpath, filename, user_id y timestamp de expiración.
    Es seguro usarlo en query params de URLs — NO expone el JWT de sesión.

    Args:
        area:     Nombre del área (ej. "VENTAS")
        subpath:  Subpath dentro del área (ej. "/2026/")
        filename: Nombre del archivo (ej. "views.png")
        user_id:  ID del usuario autenticado que solicita el acceso

    Returns:
        Token en formato "<payload_base64>.<hmac_hex>"
    """
    expiry = int(time.time()) + MEDIA_TOKEN_TTL
    payload = {
        "a": area,
        "s": subpath,
        "f": filename,
        "u": user_id,
        "e": expiry,
    }
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    sig = hmac.new(_get_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_media_token(
    token: str,
    *,
    area: str,
    subpath: str,
    filename: str,
) -> int | None:
    """
    Verifica un media token. Retorna user_id si es válido, None si no lo es.

    Verificaciones realizadas (en orden):
    1. Firma HMAC (integridad — no puede ser forjado sin el secret)
    2. Expiración (el token tiene vida limitada)
    3. Coincidencia exacta del recurso (area + subpath + filename)
       — Un token para /imagen1.png no sirve para /imagen2.png

    Args:
        token:    Token a verificar
        area:     Área que está siendo accedida
        subpath:  Subpath del archivo
        filename: Nombre del archivo

    Returns:
        user_id (int) si el token es válido, None si es inválido o expirado.
    """
    try:
        payload_b64, sig = token.rsplit(".", 1)

        # 1. Verificar firma (timing-safe para prevenir timing attacks)
        expected_sig = hmac.new(
            _get_secret(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None

        # 2. Decodificar payload
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))

        # 3. Verificar expiración
        if payload.get("e", 0) < int(time.time()):
            return None

        # 4. Verificar que el token es para este recurso exacto
        if (
            payload.get("a") != area
            or payload.get("s") != subpath
            or payload.get("f") != filename
        ):
            return None

        return int(payload["u"])

    except Exception:
        # Nunca propagar detalles del error — siempre retornar None
        return None
