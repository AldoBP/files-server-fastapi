import os
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_verified_user, User
from files_server_fastapi.files.path_utils import normalize_subpath, build_logical_path
from files_server_fastapi.models.permisos_model import User_Ruta_Access, Permisos
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.users_extend_model import Users_extend
from files_server_fastapi.models.rol_model import Rol

router = APIRouter()

# ── Sincronización Samba ────────────────────────────────────────────────────
# La ruta al script se configura en .env con SAMBA_SYNC_SCRIPT.
# Si no está definida o el archivo no existe (ej: entorno de desarrollo), se omite silenciosamente.
_SAMBA_SYNC_SCRIPT: str = os.getenv("SAMBA_SYNC_SCRIPT", "")

async def _sync_samba_background() -> None:
    """Lanza el script de sincronización Samba en background sin bloquear la respuesta."""
    if not _SAMBA_SYNC_SCRIPT or not os.path.exists(_SAMBA_SYNC_SCRIPT):
        return
    await asyncio.create_subprocess_exec(
        "python3", _SAMBA_SYNC_SCRIPT,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

# ── Mapa: role_name → access_type por defecto ────────────────────────────────
_ROL_DEFAULT_ACCESS: dict[str, str] = {
    "SUPER_ADMIN": "web_full",
    "AREA_ADMIN":  "web_full",
    "EDITOR":      "web_upload",
    "VIEWER":      "web_view",
}


async def _sync_samba_if_enabled(user_id: int, db: AsyncSession) -> None:
    """
    Sincroniza Samba en background SOLO si el usuario tiene samba_enabled=True.
    Se llama automáticamente cada vez que se modifica un ACL web del usuario.
    """
    result = await db.execute(
        select(Users_extend).where(Users_extend.user_id == user_id)
    )
    user_ext = result.scalars().first()
    if user_ext and user_ext.samba_enabled:
        asyncio.create_task(_sync_samba_background())

class AclDetail(BaseModel):
    path: str
    permission: str

class AclCreate(BaseModel):
    area: str
    user_id: int
    acls: list[AclDetail]

@router.post("/acls", summary="Asignar acceso a una carpeta específica (ACL)")
async def create_acl(
    req: AclCreate,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Crea o actualiza los accesos (ACLs) enviados desde el frontend.
    """
    # 0. Traducir el ID que manda el frontend (users_extend.id) al verdadero user_id de la tabla Users
    ext_result = await db.execute(select(Users_extend).where(Users_extend.id == req.user_id))
    user_ext_obj = ext_result.scalars().first()
    
    if not user_ext_obj:
        raise HTTPException(status_code=404, detail=f"No se encontró ninguna extensión de usuario activa con el ID {req.user_id}.")

    real_user_id = user_ext_obj.user_id

    # 1. Verificar si el Área existe para crear la Ruta adecuadamente
    area_result = await db.execute(select(Area).where(Area.area_name.ilike(req.area)))
    area_obj = area_result.scalars().first()
    if not area_obj:
        raise HTTPException(status_code=404, detail=f"Área '{req.area}' no encontrada")

    processed_acls = []

    for acl_item in req.acls:
        print(f"[acls_router] INPUT  → area={req.area!r}  path={acl_item.path!r}  permission={acl_item.permission!r}")

        # Las rutas en DB se almacenan SIN barra inicial (ej: "VENTAS/test1/sub")
        # Normalizar siempre usando path_utils para eliminar prefijos de área duplicados
        clean_sub = normalize_subpath(req.area, acl_item.path)
        # build_logical_path retorna el path sin barra inicial (ej: "VENTAS/test1")
        # coincidiendo con el formato de almacenamiento en la tabla rutas
        logical_path_full = build_logical_path(req.area, clean_sub)

        parts = logical_path_full.split("/")
        folder_name = parts[-1] if parts else req.area.upper()

        # Determinar el área real de la ruta (primer segmento del path)
        first_area_of_path = parts[0].upper() if parts else req.area.upper()

        # PASO 1 — Buscar con la ruta canónica normalizada (sin barra inicial)
        ruta_result = await db.execute(select(Rutas).where(Rutas.ruta == logical_path_full))
        ruta_obj = ruta_result.scalars().first()

        if ruta_obj:
            print(f"[acls_router] FOUND  → ruta canónica en DB: {logical_path_full!r} (area_id={ruta_obj.area_id})")
        else:
            # PASO 2 — Intentar también con barra inicial por compatibilidad con registros antiguos
            ruta_slash_result = await db.execute(select(Rutas).where(Rutas.ruta == "/" + logical_path_full))
            ruta_obj = ruta_slash_result.scalars().first()

            if ruta_obj:
                print(f"[acls_router] FOUND  → ruta con slash en DB: /{logical_path_full!r} (area_id={ruta_obj.area_id})")
            else:
                # PASO 3 — Realmente no existe: buscar el área correcta para la nueva ruta
                # Si la ruta es cross-área (ej: INGENIERIA/...) buscar el área correcta
                area_for_ruta = area_obj
                if first_area_of_path != req.area.strip().upper():
                    cross_area_result = await db.execute(
                        select(Area).where(Area.area_name.ilike(first_area_of_path))
                    )
                    cross_area = cross_area_result.scalars().first()
                    if cross_area:
                        area_for_ruta = cross_area

                print(f"[acls_router] BUILD  → no encontrada, construyendo: {logical_path_full!r}")
                ruta_obj = Rutas(
                    ruta=logical_path_full,
                    name=folder_name,
                    area_id=area_for_ruta.id
                )
                db.add(ruta_obj)
                await db.commit()
                await db.refresh(ruta_obj)

        # Consultar la DB dinámicamente para averiguar qué acción implica el permiso solicitado de frontend
        perm_result = await db.execute(select(Permisos).where(Permisos.permiso_name.ilike(acl_item.permission)))
        permiso_obj = perm_result.scalars().first()

        if not permiso_obj:
            raise HTTPException(status_code=400, detail=f"El permiso '{acl_item.permission}' no existe en la base de datos.")
            
        db_access_type = permiso_obj.fastapi_action

        # 3. Asignar el ACL en User_Ruta_Access
        acl_result = await db.execute(
            select(User_Ruta_Access)
            .where(User_Ruta_Access.user_id == real_user_id)
            .where(User_Ruta_Access.ruta_id == ruta_obj.id)
        )
        existing_acl = acl_result.scalars().first()

        if existing_acl:
            existing_acl.access_type = db_access_type
            await db.commit()
            processed_acls.append(existing_acl.id)
        else:
            new_acl = User_Ruta_Access(
                user_id=real_user_id,
                ruta_id=ruta_obj.id,
                access_type=db_access_type
            )
            db.add(new_acl)
            await db.commit()
            await db.refresh(new_acl)
            processed_acls.append(new_acl.id)

    return {"message": "ACLs asignados correctamente", "processed_acls": processed_acls}

@router.get("/acls", summary="Obtener las carpetas compartidas del usuario")
async def get_user_acls(
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Devuelve la lista de rutas (carpetas) a las que el usuario tiene acceso
    mediante asignación directa en la tabla User_Ruta_Access.
    """
    # Buscar el ID real de la tabla Users_extend del usuario activo
    ext_result = await db.execute(select(Users_extend).where(Users_extend.user_id == current_user.id))
    user_exts = ext_result.scalars().all()
    
    if not user_exts:
        return []

    # Se obtienen todos los ACLs del usuario para cualquier ruta (donde no sea deny_all)
    # y hacemos join con Rutas para traer el path
    result = await db.execute(
        select(Rutas.ruta, Rutas.name, User_Ruta_Access.access_type, Area.area_name)
        .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
        .join(Area, Area.id == Rutas.area_id)
        .where(User_Ruta_Access.user_id == current_user.id)
        .where(User_Ruta_Access.access_type != "deny_all")
    )
    
    # Obtener el mapeo de acciones a nombres (Reverse lookup)
    perm_result = await db.execute(select(Permisos.fastapi_action, Permisos.permiso_name))
    action_to_name = {action: name for action, name in perm_result.all()}

    shared_folders = []
    for row in result.all():
        ruta, nombre, access_type, area_name = row
        shared_folders.append({
            "path": "/" + ruta if not ruta.startswith("/") else ruta,
            "name": nombre,
            "permission": action_to_name.get(access_type, access_type),
            "area": area_name,
            "type": "folder",
            "is_shared": True
        })

    return {"shared_folders": shared_folders}

@router.get("/acls/user/{user_id}", summary="Obtener los ACLs de un usuario específico")
async def get_specific_user_acls(
    user_id: int,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Devuelve las reglas actuales de un usuario en un formato simple para el modal de React.
    Ejemplo: {"/ruta/1": "EDITOR", "/ruta/2": "VIEWER"}
    """
    # 0. Traducir el ID que manda el frontend (users_extend.id) al verdadero user_id
    ext_result = await db.execute(select(Users_extend).where(Users_extend.id == user_id))
    user_ext_obj = ext_result.scalars().first()
    
    if not user_ext_obj:
        raise HTTPException(status_code=404, detail=f"No se encontró ninguna extensión de usuario con el ID {user_id}.")

    real_user_id = user_ext_obj.user_id

    # 1. Consultar los ACLs en la base de datos
    result = await db.execute(
        select(Rutas.ruta, User_Ruta_Access.access_type)
        .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
        .where(User_Ruta_Access.user_id == real_user_id)
    )
    
    # 2. Obtener el mapeo de acciones a nombres (Reverse lookup dinámico)
    perm_result = await db.execute(select(Permisos.fastapi_action, Permisos.permiso_name))
    action_to_name = {action: name for action, name in perm_result.all()}

    # 3. Convertir al formato simple que espera el frontend (CON barra inicial)
    acls_dict = {}
    for ruta, access_type in result.all():
        formatted_ruta = "/" + ruta if not ruta.startswith("/") else ruta
        acls_dict[formatted_ruta] = action_to_name.get(access_type, access_type)
    
    return acls_dict


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS NUEVOS — Sistema de permisos "Cerrado por defecto"
# ════════════════════════════════════════════════════════════════════════════

@router.post(
    "/acls/users/{user_ext_id}/initialize",
    summary="Inicializar permisos de un usuario recién registrado",
)
async def initialize_user_acl(
    user_ext_id: int,
    grant_full_area: bool = False,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Debe llamarse desde el frontend justo después de registrar un usuario
    en oauth2fast_fastapi.

    Por defecto bloquea todo el área del usuario (deny_all).
    Si grant_full_area=True, otorga el permiso completo del área según su rol:
      EDITOR / AREA_ADMIN / SUPER_ADMIN → allow_write
      VIEWER                            → allow_read
      Cualquier otro rol no mapeado     → deny_all
    """
    # 1. Resolver el users_extend por su propio id (el que maneja el frontend)
    ext_result = await db.execute(select(Users_extend).where(Users_extend.id == user_ext_id))
    user_ext = ext_result.scalars().first()
    if not user_ext:
        raise HTTPException(status_code=404, detail=f"Usuario con id {user_ext_id} no encontrado.")

    # 2. Obtener el nombre del rol
    rol_result = await db.execute(select(Rol).where(Rol.id == user_ext.rol_id))
    rol = rol_result.scalars().first()
    rol_name = rol.role_name.upper() if rol else ""

    # 3. Obtener el área
    area_result = await db.execute(select(Area).where(Area.id == user_ext.area_id))
    area_obj = area_result.scalars().first()
    if not area_obj:
        raise HTTPException(status_code=404, detail="Área del usuario no encontrada.")

    # 4. Buscar la ruta raíz del área (ruta == area_name en mayúsculas)
    ruta_result = await db.execute(
        select(Rutas)
        .where(Rutas.area_id == user_ext.area_id)
        .where(Rutas.ruta == area_obj.area_name.upper())
        .limit(1)
    )
    ruta_raiz = ruta_result.scalars().first()
    if not ruta_raiz:
        raise HTTPException(
            status_code=404,
            detail=f"Ruta raíz del área '{area_obj.area_name}' no encontrada en la tabla rutas.",
        )

    # 5. Determinar el access_type
    access_type = _ROL_DEFAULT_ACCESS.get(rol_name, "deny_all") if grant_full_area else "deny_all"

    # 6. Upsert en user_ruta_access
    acl_result = await db.execute(
        select(User_Ruta_Access)
        .where(User_Ruta_Access.user_id == user_ext.user_id)
        .where(User_Ruta_Access.ruta_id == ruta_raiz.id)
    )
    existing = acl_result.scalars().first()
    if existing:
        existing.access_type = access_type
    else:
        db.add(User_Ruta_Access(
            user_id=user_ext.user_id,
            ruta_id=ruta_raiz.id,
            access_type=access_type,
        ))
    await db.commit()

    # 7. Sync Samba en background (solo si el usuario tiene samba_enabled=True)
    await _sync_samba_if_enabled(user_ext.user_id, db)

    return {
        "user_ext_id": user_ext_id,
        "user_id": user_ext.user_id,
        "area": area_obj.area_name,
        "ruta_raiz": ruta_raiz.ruta,
        "access_type": access_type,
        "message": f"Usuario inicializado con acceso '{access_type}' en '{ruta_raiz.ruta}'.",
    }


@router.post(
    "/acls/users/{user_ext_id}/grant-area",
    summary="Habilitar acceso completo al área según el rol del usuario",
)
async def grant_full_area(
    user_ext_id: int,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Cambia el acceso del usuario en la raíz de su área al permiso por defecto de su rol.
    Equivalente a llamar a /initialize con grant_full_area=True.
    No elimina los permisos granulares en subcarpetas — solo actualiza la raíz.
    """
    # Reutiliza la misma lógica de initialize con grant_full_area=True
    return await initialize_user_acl(
        user_ext_id=user_ext_id,
        grant_full_area=True,
        current_user=current_user,
        db=db,
    )


@router.post(
    "/acls/users/{user_ext_id}/revoke-area",
    summary="Revocar todos los permisos del usuario y bloquear el área completa",
)
async def revoke_full_area(
    user_ext_id: int,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Elimina TODOS los permisos granulares del usuario en user_ruta_access
    y restaura únicamente el deny_all en la raíz de su área.
    """
    # 1. Resolver users_extend
    ext_result = await db.execute(select(Users_extend).where(Users_extend.id == user_ext_id))
    user_ext = ext_result.scalars().first()
    if not user_ext:
        raise HTTPException(status_code=404, detail=f"Usuario con id {user_ext_id} no encontrado.")

    # 2. Obtener área y ruta raíz
    area_result = await db.execute(select(Area).where(Area.id == user_ext.area_id))
    area_obj = area_result.scalars().first()
    if not area_obj:
        raise HTTPException(status_code=404, detail="Área del usuario no encontrada.")

    ruta_result = await db.execute(
        select(Rutas)
        .where(Rutas.area_id == user_ext.area_id)
        .where(Rutas.ruta == area_obj.area_name.upper())
        .limit(1)
    )
    ruta_raiz = ruta_result.scalars().first()
    if not ruta_raiz:
        raise HTTPException(status_code=404, detail="Ruta raíz del área no encontrada.")

    # 3. Eliminar TODOS los ACLs del usuario
    await db.execute(
        delete(User_Ruta_Access).where(User_Ruta_Access.user_id == user_ext.user_id)
    )
    await db.commit()

    # 4. Insertar deny_all en la raíz del área
    db.add(User_Ruta_Access(
        user_id=user_ext.user_id,
        ruta_id=ruta_raiz.id,
        access_type="deny_all",
    ))
    await db.commit()

    # 5. Sync Samba en background (solo si el usuario tiene samba_enabled=True)
    await _sync_samba_if_enabled(user_ext.user_id, db)

    return {
        "user_ext_id": user_ext_id,
        "user_id": user_ext.user_id,
        "area": area_obj.area_name,
        "access_type": "deny_all",
        "message": "Todos los permisos revocados. Área bloqueada completamente.",
    }


@router.delete(
    "/acls/users/{user_ext_id}/ruta/{ruta_id}",
    summary="Eliminar el permiso explícito de un usuario en una ruta específica",
)
async def delete_user_acl(
    user_ext_id: int,
    ruta_id: int,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Elimina la fila de user_ruta_access para ese usuario y ruta.
    La carpeta queda sin permiso explícito y hereda el del padre.
    PRECAUCIÓN: Si eliminas el deny_all de la raíz sin otro permiso,
    el usuario podría ganar acceso por herencia de rol.
    """
    # 1. Resolver real user_id
    ext_result = await db.execute(select(Users_extend).where(Users_extend.id == user_ext_id))
    user_ext = ext_result.scalars().first()
    if not user_ext:
        raise HTTPException(status_code=404, detail=f"Usuario con id {user_ext_id} no encontrado.")

    # 2. Buscar el ACL existente
    acl_result = await db.execute(
        select(User_Ruta_Access)
        .where(User_Ruta_Access.user_id == user_ext.user_id)
        .where(User_Ruta_Access.ruta_id == ruta_id)
    )
    acl = acl_result.scalars().first()
    if not acl:
        raise HTTPException(
            status_code=404,
            detail=f"No existe un permiso explícito para el usuario {user_ext_id} en la ruta {ruta_id}.",
        )

    # 3. Eliminar
    await db.delete(acl)
    await db.commit()

    # 4. Sync Samba en background (solo si el usuario tiene samba_enabled=True)
    await _sync_samba_if_enabled(user_ext.user_id, db)

    return {
        "message": f"Permiso eliminado. La ruta {ruta_id} ahora hereda el permiso de su carpeta padre.",
        "user_ext_id": user_ext_id,
        "ruta_id": ruta_id,
    }
