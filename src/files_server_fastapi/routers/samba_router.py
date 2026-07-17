"""
Samba Router
============
Gestiona la activación y desactivación del acceso Samba para usuarios individuales.

Reglas clave:
  - Samba NO se activa automáticamente al crear un usuario. Solo un administrador
    puede activarlo desde estos endpoints.
  - Los permisos Samba replican EXACTAMENTE los permisos web del usuario (ACLs granulares
    por carpeta incluidos). No hay configuración separada de permisos Samba.
  - Si el admin cambia un permiso web a un usuario con samba_enabled=True, Samba
    se re-sincroniza automáticamente en ese momento (vía _sync_samba_if_enabled
    en acls_router.py).
  - El endpoint /sync permite re-sincronizar manualmente si algo quedó desincronizado.

Mapeo web → Linux ACL:
  web_view   → r-- (solo lectura; editar = OnlyOffice, no desde el explorador)
  web_edit   → r-- (solo lectura en Samba; la edición es vía OnlyOffice en la web)
  web_upload → rw- (lectura + escritura/subida)
  web_full   → rwx (lectura + escritura + borrado + crear carpetas)
  deny_all   → --- (sin acceso)
"""
import os
import asyncio
import secrets
import string
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.dependencies.user_dependencies import (
    get_active_user,
    require_superadmin,
)
from files_server_fastapi.models.users_extend_model import Users_extend
from files_server_fastapi.models.permisos_model import User_Ruta_Access
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.rol_model import Rol

router = APIRouter(prefix="/samba", tags=["Gestión Samba"])

# ── Configuración Samba ───────────────────────────────────────────────────────
_SAMBA_SYNC_SCRIPT: str = os.getenv("SAMBA_SYNC_SCRIPT", "")

# Mapeo: access_type web → linux_acl para setfacl
_WEB_TO_LINUX_ACL: dict[str, str] = {
    "web_view":   "r--",
    "web_edit":   "r--",   # editar = OnlyOffice, no desde explorador de archivos
    "web_upload": "rw-",
    "web_full":   "rwx",
    "deny_all":   "---",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_samba_password(length: int = 16) -> str:
    """Genera una contraseña segura aleatoria para el usuario Samba."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _run_samba_sync(script_path: str) -> None:
    """Ejecuta el script de sincronización Samba en background."""
    if not script_path or not os.path.exists(script_path):
        return
    await asyncio.create_subprocess_exec(
        "python3", script_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def _set_samba_user_password(linux_username: str, password: str) -> tuple[bool, str]:
    """
    Crea o actualiza la contraseña del usuario en Samba usando smbpasswd.
    Retorna (success, error_message).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "smbpasswd", "-a", "-s", linux_username,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        # smbpasswd -s lee la contraseña dos veces de stdin (nueva + confirmación)
        password_input = f"{password}\n{password}\n".encode()
        _, stderr = await proc.communicate(input=password_input)
        if proc.returncode != 0:
            return False, stderr.decode().strip()
        return True, ""
    except FileNotFoundError:
        return False, "smbpasswd no encontrado. Asegúrate de que Samba está instalado."
    except Exception as e:
        return False, str(e)


async def _disable_samba_user(linux_username: str) -> tuple[bool, str]:
    """
    Deshabilita el usuario en Samba usando smbpasswd -d.
    Retorna (success, error_message).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "smbpasswd", "-d", linux_username,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return False, stderr.decode().strip()
        return True, ""
    except FileNotFoundError:
        return False, "smbpasswd no encontrado. Asegúrate de que Samba está instalado."
    except Exception as e:
        return False, str(e)


async def _get_user_ext_and_username(
    user_ext_id: int,
    db: AsyncSession,
) -> tuple["Users_extend", str]:
    """
    Resuelve el Users_extend por su ID y obtiene el username del usuario base.
    Lanza 404 si no existe.
    """
    from oauth2fast_fastapi import User as OAuthUser
    from sqlmodel import select as sql_select

    ext_result = await db.execute(
        select(Users_extend).where(Users_extend.id == user_ext_id)
    )
    user_ext = ext_result.scalars().first()
    if not user_ext:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró extensión de usuario con ID {user_ext_id}.",
        )

    # Obtener el username desde la tabla users (oauth2fast_fastapi)
    user_result = await db.execute(
        sql_select(OAuthUser).where(OAuthUser.id == user_ext.user_id)
    )
    user_obj = user_result.scalars().first()
    if not user_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el usuario base con ID {user_ext.user_id}.",
        )

    linux_username = user_obj.email.replace("@", "_").replace(".", "_").lower()
    return user_ext, linux_username


# ── Modelos de Request/Response ───────────────────────────────────────────────

class SambaActivateRequest(BaseModel):
    password: str | None = None
    """
    Contraseña Samba del usuario. Si se omite, se genera una contraseña aleatoria segura.
    El admin es responsable de comunicar las credenciales al usuario.
    """


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/users/{user_ext_id}/activate",
    summary="Activar acceso Samba para un usuario",
)
async def activate_samba(
    user_ext_id: int,
    req: SambaActivateRequest = SambaActivateRequest(),
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Activa el acceso Samba para el usuario indicado.

    - Si el usuario ya tiene Samba activo, actualiza la contraseña y re-sincroniza permisos.
    - Los permisos Samba se calculan automáticamente a partir de los permisos web actuales.
    - Si no se proporciona contraseña, se genera una aleatoria.
    - La contraseña se guarda en `users_extend.samba_password`.
    - El admin debe comunicar las credenciales al usuario manualmente.

    **Requiere rol SUPER_ADMIN o AREA_ADMIN.**
    """
    user_ext, linux_username = await _get_user_ext_and_username(user_ext_id, db)

    # Generar o usar la contraseña proporcionada
    password = req.password if req.password else _generate_samba_password()

    # Crear/actualizar el usuario en Samba
    success, error_msg = await _set_samba_user_password(linux_username, password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al configurar usuario en Samba: {error_msg}",
        )

    # Actualizar users_extend — ahora solo guarda el flag, no la contraseña
    user_ext.samba_enabled = True
    db.add(user_ext)
    await db.commit()

    # Sincronizar permisos (replicar ACLs web → Linux)
    asyncio.create_task(_run_samba_sync(_SAMBA_SYNC_SCRIPT))

    return {
        "user_ext_id": user_ext_id,
        "user_id": user_ext.user_id,
        "username": linux_username,
        "samba_enabled": True,
        "password": password,
        "warning": "Guarda esta contraseña ahora. No se volverá a mostrar nunca más."
    }


@router.post(
    "/users/{user_ext_id}/deactivate",
    summary="Desactivar acceso Samba para un usuario",
)
async def deactivate_samba(
    user_ext_id: int,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Desactiva el acceso Samba del usuario indicado.

    - Deshabilita el usuario en Samba (smbpasswd -d).
    - Actualiza `samba_enabled=False` en la base de datos.
    - Los ACLs web del usuario no se modifican.

    **Requiere rol SUPER_ADMIN o AREA_ADMIN.**
    """
    user_ext, linux_username = await _get_user_ext_and_username(user_ext_id, db)

    if not user_ext.samba_enabled:
        return {
            "user_ext_id": user_ext_id,
            "username": linux_username,
            "samba_enabled": False,
            "message": "El usuario ya tenía Samba desactivado.",
        }

    # Deshabilitar en Samba
    success, error_msg = await _disable_samba_user(linux_username)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al deshabilitar usuario en Samba: {error_msg}",
        )

    # Actualizar users_extend
    user_ext.samba_enabled = False
    db.add(user_ext)
    await db.commit()

    return {
        "user_ext_id": user_ext_id,
        "user_id": user_ext.user_id,
        "username": linux_username,
        "samba_enabled": False,
        "message": f"Acceso Samba desactivado para '{linux_username}'.",
    }


@router.get(
    "/users/{user_ext_id}/status",
    summary="Consultar estado Samba de un usuario",
)
async def get_samba_status(
    user_ext_id: int,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Devuelve el estado actual de Samba para el usuario indicado.

    La contraseña **no se incluye en la respuesta** por seguridad.

    **Requiere rol SUPER_ADMIN o AREA_ADMIN.**
    """
    user_ext, linux_username = await _get_user_ext_and_username(user_ext_id, db)

    # Contar ACLs web activos del usuario (los que se replicarían a Samba)
    acl_result = await db.execute(
        select(User_Ruta_Access)
        .where(User_Ruta_Access.user_id == user_ext.user_id)
    )
    acl_count = len(acl_result.scalars().all())

    # Obtener nombre del rol
    rol_result = await db.execute(select(Rol).where(Rol.id == user_ext.rol_id))
    rol = rol_result.scalars().first()

    # Obtener nombre del área
    area_result = await db.execute(select(Area).where(Area.id == user_ext.area_id))
    area_obj = area_result.scalars().first()

    return {
        "user_ext_id": user_ext_id,
        "user_id": user_ext.user_id,
        "username": linux_username,
        "samba_enabled": user_ext.samba_enabled,
        "acl_count": acl_count,
        "rol": rol.role_name if rol else None,
        "area": area_obj.area_name if area_obj else None,
    }


@router.post(
    "/users/{user_ext_id}/sync",
    summary="Re-sincronizar manualmente los permisos Samba con los permisos web",
)
async def sync_samba(
    user_ext_id: int,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Fuerza una re-sincronización de los permisos Linux/Samba del usuario
    con su estado web actual.

    Útil si algo quedó desincronizado (por ejemplo, si el script de sincronización
    falló silenciosamente en una actualización anterior).

    El usuario debe tener `samba_enabled=True`. Si no, retorna error 400.

    **Requiere rol SUPER_ADMIN o AREA_ADMIN.**
    """
    user_ext, linux_username = await _get_user_ext_and_username(user_ext_id, db)

    if not user_ext.samba_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario '{linux_username}' no tiene Samba activo. Actívalo primero con /activate.",
        )

    asyncio.create_task(_run_samba_sync(_SAMBA_SYNC_SCRIPT))

    return {
        "user_ext_id": user_ext_id,
        "username": linux_username,
        "message": "Re-sincronización de permisos Samba iniciada en background.",
    }


@router.post(
    "/users/{user_ext_id}/reset-password",
    summary="Resetear contraseña Samba de un usuario",
)
async def reset_samba_password(
    user_ext_id: int,
    auth: tuple = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Genera una nueva contraseña aleatoria, la asigna en Samba,
    y la devuelve en la respuesta.

    **Solo accesible por SUPER_ADMIN (Sistemas).**
    """
    user_ext, linux_username = await _get_user_ext_and_username(user_ext_id, db)

    if not user_ext.samba_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El usuario '{linux_username}' no tiene Samba activo. "
                "Activa Samba primero con /activate."
            ),
        )

    # Generar nueva contraseña aleatoria
    password = _generate_samba_password()

    # Actualizar el usuario en Samba
    success, error_msg = await _set_samba_user_password(linux_username, password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al cambiar la contraseña en Samba: {error_msg}",
        )

    return {
        "user_ext_id": user_ext_id,
        "user_id": user_ext.user_id,
        "username": linux_username,
        "password": password,
        "warning": (
            "Contraseña actualizada correctamente. "
            "Comunícala al usuario y guárdala ahora. No se volverá a mostrar nunca más."
        ),
    }
