from fastapi import HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, or_
from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_verified_user, User
from files_server_fastapi.models.permisos_model import User_Ruta_Access, Permisos, Permiso_rol
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.users_extend_model import Users_extend
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.rol_model import Rol


# ── Niveles de acceso web (de mayor a menor prioridad) ──────────────────────
#   web_full   → ver + editar (OnlyOffice) + subir/crear carpetas + eliminar
#   web_upload → ver + editar (OnlyOffice) + subir/crear carpetas
#   web_edit   → ver + editar (OnlyOffice)  [sin descarga, sin subida]
#   web_view   → solo ver (lectura en navegador, OnlyOffice modo lectura)
#   deny_all   → sin acceso

_ACCESS_PRIORITY: list[str] = ["web_full", "web_upload", "web_edit", "web_view"]

# Conjuntos de access_types que habilitan cada acción
_CAN_VIEW:   frozenset[str] = frozenset({"web_view", "web_edit", "web_upload", "web_full"})
_CAN_EDIT:   frozenset[str] = frozenset({"web_edit", "web_upload", "web_full"})
_CAN_UPLOAD: frozenset[str] = frozenset({"web_upload", "web_full"})
_CAN_DELETE: frozenset[str] = frozenset({"web_full"})


# ── Helpers públicos de verificación de permiso ──────────────────────────────

def can_view(access_type: str) -> bool:
    """True si el access_type permite ver archivos/carpetas en la interfaz web."""
    return access_type in _CAN_VIEW

def can_edit(access_type: str) -> bool:
    """True si el access_type permite editar archivos con OnlyOffice."""
    return access_type in _CAN_EDIT

def can_upload(access_type: str) -> bool:
    """True si el access_type permite subir archivos y crear carpetas."""
    return access_type in _CAN_UPLOAD

def can_delete(access_type: str) -> bool:
    """True si el access_type permite eliminar archivos y carpetas."""
    return access_type in _CAN_DELETE


async def resolve_effective_access(
    area: str,
    subpath: str,
    user_id: int,
    user_ext_in_area,
    is_super_admin: bool,
    db: AsyncSession,
    preloaded_acls: dict[str, "User_Ruta_Access"] | None = None,
) -> str | None:
    """
    Resuelve el access_type efectivo de un usuario para un path dado.

    Retorna uno de: 'web_full', 'web_upload', 'web_edit', 'web_view', 'deny_all', None
    - 'deny_all' → el usuario tiene denegación explícita (o heredada) para este path.
    - None       → no hay ninguna regla aplicable (ni ACL ni rol).
    No lanza HTTPException — el caller decide qué hacer con el resultado.

    Args:
        area:              Nombre del área (ej. "VENTAS").
        subpath:           Subpath relativo al área (ej. "/test1" o "/").
        user_id:           ID real del usuario en la tabla users.
        user_ext_in_area:  Objeto Users_extend del usuario en este área, o None.
        is_super_admin:    True si el usuario tiene rol SUPER_ADMIN.
        db:                Sesión de base de datos.
        preloaded_acls:    ACLs ya cargados en bulk (optimización para loops).
                           Formato: {ruta_str: User_Ruta_Access}. Si None, se consulta la BD.
    """
    # SUPER_ADMIN siempre tiene acceso total
    if is_super_admin:
        return "web_full"

    # Construir la jerarquía de paths a revisar (sin barra inicial, más específico primero)
    logical_path = f"{area.upper()}/{subpath.strip('/')}".strip("/")
    parts = logical_path.split("/")
    paths_to_check: list[str] = []
    current_parts: list[str] = []
    for part in parts:
        if part:
            current_parts.append(part)
            paths_to_check.append("/".join(current_parts))
    paths_to_check.reverse()  # Más específico primero

    exact_path = paths_to_check[0] if paths_to_check else area.upper()

    # ── Buscar ACLs del usuario ─────────────────────────────────────────────
    if preloaded_acls is not None:
        # Usar el caché bulk — filtrar solo los paths de esta jerarquía
        acls_encontrados = {
            p: preloaded_acls[p]
            for p in paths_to_check
            if p in preloaded_acls
        }
    else:
        # Consulta individual a la BD (comportamiento original)
        res_acl = await db.execute(
            select(Rutas.ruta, User_Ruta_Access)
            .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
            .where(Rutas.ruta.in_(paths_to_check))
            .where(User_Ruta_Access.user_id == user_id)
        )
        acls_encontrados = {row[0]: row[1] for row in res_acl.all()}

    # ── Evaluar ACL (más específico primero) ────────────────────────────────
    for path_in_tree in paths_to_check:
        if path_in_tree in acls_encontrados:
            acl_obj = acls_encontrados[path_in_tree]
            effective_type: str = acl_obj.access_type

            if effective_type == "deny_all":
                # Excepción de navegación: si el path exacto solicitado (o algún
                # descendiente) tiene un ACL positivo, permitir navegación con web_view.
                res_positive = await db.execute(
                    select(User_Ruta_Access)
                    .join(Rutas, Rutas.id == User_Ruta_Access.ruta_id)
                    .where(User_Ruta_Access.user_id == user_id)
                    .where(User_Ruta_Access.access_type != "deny_all")
                    .where(
                        or_(
                            Rutas.ruta == exact_path,
                            Rutas.ruta.like(exact_path + "/%"),
                        )
                    )
                )
                if res_positive.scalars().first():
                    return "web_view"
                return "deny_all"

            return effective_type

    # ── Evaluar permisos por rol ─────────────────────────────────────────────
    if user_ext_in_area:
        res_role_perms = await db.execute(
            select(Rutas.ruta, Permisos.fastapi_action)
            .join(Permiso_rol, Permiso_rol.id_permiso == Permisos.id)
            .join(Rutas, Rutas.id == Permiso_rol.ruta_id)
            .where(Permiso_rol.id_rol == user_ext_in_area.rol_id)
            .where(Rutas.ruta.in_(paths_to_check))
        )
        role_perms_map: dict[str, set[str]] = {}
        for r, p_action in res_role_perms.all():
            if r not in role_perms_map:
                role_perms_map[r] = set()
            role_perms_map[r].add(p_action)

        for path_in_tree in paths_to_check:
            if path_in_tree in role_perms_map:
                actions = role_perms_map[path_in_tree]
                for access_type in _ACCESS_PRIORITY:
                    if access_type in actions:
                        return access_type

    # Sin regla aplicable
    return None


async def _resolve_user_context(
    current_user: User,
    area: str,
    db: AsyncSession,
) -> tuple[bool, "Users_extend | None"]:
    """
    Resuelve el contexto del usuario: si es SUPER_ADMIN y su Users_extend del área.
    Retorna (is_super_admin, user_ext_in_area).
    """
    result_ext = await db.execute(
        select(Users_extend).where(Users_extend.user_id == current_user.id)
    )
    user_exts = result_ext.scalars().all()

    is_super_admin = False
    user_ext_in_area = None

    for ext in user_exts:
        res_rol = await db.execute(select(Rol).where(Rol.id == ext.rol_id))
        rol = res_rol.scalars().first()
        if rol and rol.role_name.upper() == "SUPER_ADMIN":
            is_super_admin = True
            break

    if not is_super_admin:
        for ext in user_exts:
            res_area = await db.execute(select(Area).where(Area.id == ext.area_id))
            a = res_area.scalars().first()
            if a and a.area_name.upper() == area.upper():
                user_ext_in_area = ext
                break

    return is_super_admin, user_ext_in_area


async def check_folder_access(
    area: str,
    subpath: str = "/",
    required_access: str = "view",
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
) -> str:
    """
    Wrapper FastAPI Depends sobre resolve_effective_access.
    Lanza HTTPException 403 si el acceso es denegado o insuficiente.

    required_access: 'view' | 'edit' | 'upload' | 'delete'
    Retorna el access_type efectivo concedido.
    """
    is_super_admin, user_ext_in_area = await _resolve_user_context(current_user, area, db)

    effective = await resolve_effective_access(
        area=area,
        subpath=subpath,
        user_id=current_user.id,
        user_ext_in_area=user_ext_in_area,
        is_super_admin=is_super_admin,
        db=db,
    )

    if effective is None:
        raise HTTPException(
            status_code=403,
            detail=f"No tienes ningún permiso asignado para esta ruta.",
        )

    if effective == "deny_all":
        raise HTTPException(status_code=403, detail="Acceso denegado.")

    # Verificar que el permiso efectivo cubre la acción requerida
    _check_map = {
        "view":   can_view,
        "edit":   can_edit,
        "upload": can_upload,
        "delete": can_delete,
    }
    checker = _check_map.get(required_access)
    if checker is None:
        raise ValueError(f"required_access inválido: '{required_access}'. Usa: view, edit, upload, delete")

    if checker(effective):
        return effective

    raise HTTPException(
        status_code=403,
        detail=f"Tu nivel de acceso ({effective}) no es suficiente para esta operación.",
    )
