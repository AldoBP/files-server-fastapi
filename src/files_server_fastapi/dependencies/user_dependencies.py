"""
dependencies/user_dependencies.py
==================================
Dependencies de autenticación y autorización propias del proyecto.

Propósito:
    El paquete oauth2fast-fastapi maneja la autenticación base (token JWT),
    pero no conoce el concepto de "usuario dado de baja" ni el sistema de
    niveles de privilegio de este proyecto.

    Este módulo extiende esa lógica con:

    - get_active_user: verifica que el usuario NO esté dado de baja.
    - require_superadmin: verifica privilege_level >= 2.
    - require_area_admin_or_superadmin: verifica privilege_level >= 1.

Niveles de privilegio (tabla rol.privilege_level):
    0 → Usuario regular     (sin permisos de gestión)
    1 → Admin de Área       (gestión de su propia área)
    2 → Superadmin/Sistemas (acceso total)

¿Por qué privilege_level en vez de comparar nombres de rol?
    Los nombres de rol pueden cambiar ("admin" → "lider", "jefe", etc.).
    El privilege_level es un contrato estable: el código solo lee el número,
    no el texto. Renombrar un rol en la DB nunca rompe la autorización.
"""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oauth2fast_fastapi import User, get_current_verified_user
from pgsqlasync2fast_fastapi.dependencies import get_db_session

from files_server_fastapi.models.rol_model import Rol
from files_server_fastapi.models.users_extend_model import Users_extend

# ── Constantes de nivel de privilegio ────────────────────────────────────────
# Cambia estos valores SOLO si redefiniste la escala en tu tabla rol.
PRIVILEGE_USER       = 0  # Usuario regular
PRIVILEGE_AREA_ADMIN = 1  # Admin de Área
PRIVILEGE_SUPERADMIN = 2  # Sistemas / Superadmin


# ── Helper interno ────────────────────────────────────────────────────────────

async def _get_privilege_level(rol_id: int, db: AsyncSession) -> int:
    """
    Obtiene el privilege_level del rol desde la DB.
    Retorna PRIVILEGE_USER (0) si el rol no existe.
    """
    result = await db.execute(select(Rol).where(Rol.id == rol_id))
    rol = result.scalars().first()
    return rol.privilege_level if rol else PRIVILEGE_USER


# ── Dependency principal ──────────────────────────────────────────────────────

async def get_active_user(
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """
    Extiende get_current_verified_user con verificación de soft delete.

    Flujo:
        1. get_current_verified_user valida el token JWT y que is_verified=True.
        2. Esta dependency verifica que deleted_at IS NULL en users_extend.

    Lanza:
        HTTP 403 si el usuario tiene deleted_at con fecha/hora de baja.
    """
    result = await db.execute(
        select(Users_extend).where(Users_extend.user_id == current_user.id)
    )
    ext = result.scalars().first()

    if ext is not None and ext.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Tu cuenta ha sido dada de baja del sistema. "
                "Contacta a sistemas para más información."
            ),
        )
    return current_user


# ── Helper: extensión del usuario actual ──────────────────────────────────────

async def get_current_user_ext(
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> Users_extend:
    """
    Retorna el registro Users_extend del usuario autenticado y activo.
    Lanza 404 si el usuario no tiene extensión registrada.
    """
    result = await db.execute(
        select(Users_extend).where(Users_extend.user_id == current_user.id)
    )
    ext = result.scalars().first()
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario no tiene datos de extensión registrados.",
        )
    return ext


# ── Verificadores de nivel de privilegio ──────────────────────────────────────

async def require_superadmin(
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> tuple[User, Users_extend]:
    """
    Verifica que el usuario tenga privilege_level >= 2 (Superadmin/Sistemas).

    Retorna:
        (User, Users_extend) para uso en el endpoint.

    Lanza:
        HTTP 403 si el nivel de privilegio es insuficiente.
    """
    result = await db.execute(
        select(Users_extend).where(Users_extend.user_id == current_user.id)
    )
    ext = result.scalars().first()

    if not ext:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos suficientes para esta acción.",
        )

    level = await _get_privilege_level(ext.rol_id, db)
    if level < PRIVILEGE_SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo Sistemas/Superadmin puede ejecutar esta acción.",
        )

    return current_user, ext


async def require_area_admin_or_superadmin(
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> tuple[User, Users_extend, bool]:
    """
    Verifica que el usuario tenga privilege_level >= 1 (Admin de Área o superior).

    Retorna:
        (User, Users_extend, is_superadmin: bool)
        El booleano permite al endpoint saber si tiene permisos totales.

    Lanza:
        HTTP 403 si el nivel de privilegio es insuficiente.
    """
    result = await db.execute(
        select(Users_extend).where(Users_extend.user_id == current_user.id)
    )
    ext = result.scalars().first()

    if not ext:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos suficientes para esta acción.",
        )

    level = await _get_privilege_level(ext.rol_id, db)
    if level < PRIVILEGE_AREA_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere nivel de Admin de Área o superior.",
        )

    is_superadmin = level >= PRIVILEGE_SUPERADMIN
    return current_user, ext, is_superadmin

