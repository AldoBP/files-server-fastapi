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


# Tipos de acceso que solo permiten visualización web — nunca descarga ni edición.
#   allow_view      → linux_acl "r-x": puede navegar subcarpetas en Samba y ver en web.
#   allow_view_root → linux_acl "r--": solo ve la raíz asignada, sin navegar subcarpetas.
VIEW_ONLY_ACCESS_TYPES: frozenset[str] = frozenset({"allow_view", "allow_view_root"})

# Conjunto completo de access_types que satisfacen un check de "allow_read"
_READ_COMPATIBLE: frozenset[str] = frozenset({"allow_read", "allow_write"}) | VIEW_ONLY_ACCESS_TYPES

# Prioridad de tipos de acceso (de mayor a menor) para desambiguar cuando hay varios permisos de rol
_ACCESS_PRIORITY: list[str] = ["allow_write", "allow_read", "allow_view", "allow_view_root"]


async def check_folder_access(
    area: str,
    subpath: str = "/",
    required_access: str = "allow_read",
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
) -> str:
    """
    Verifica si el usuario actual tiene acceso al área y subpath indicados.

    required_access: 'allow_read' (por defecto) o 'allow_write'

    Retorna el access_type efectivo concedido (str) o lanza HTTPException 403.
    Los callers que necesitan saber si el acceso es solo-visualización pueden comparar
    el valor retornado contra VIEW_ONLY_ACCESS_TYPES.
    """
    # 1. Obtener extensiones de usuario y roles
    result_ext = await db.execute(
        select(Users_extend).where(Users_extend.user_id == current_user.id)
    )
    user_exts = result_ext.scalars().all()

    # 2. Verificar si el usuario es SUPER_ADMIN en cualquier área → acceso universal
    for ext in user_exts:
        res_rol = await db.execute(select(Rol).where(Rol.id == ext.rol_id))
        rol = res_rol.scalars().first()
        if rol and rol.role_name.upper() == "SUPER_ADMIN":
            return "allow_write"

    # 3. Identificar si el usuario pertenece al área solicitada
    user_ext_in_area = None
    for ext in user_exts:
        res_area = await db.execute(select(Area).where(Area.id == ext.area_id))
        a = res_area.scalars().first()
        if a and a.area_name.upper() == area.upper():
            user_ext_in_area = ext
            break

    # 4. Generar lista de rutas (jerarquía) para herencia — SIN barra inicial para hacer match con DB
    logical_path = f"{area.upper()}/{subpath.strip('/')}".strip("/")
    parts = logical_path.split("/")
    paths_to_check: list[str] = []
    current_path_parts: list[str] = []
    for part in parts:
        if part:
            current_path_parts.append(part)
            paths_to_check.append("/".join(current_path_parts))

    paths_to_check.reverse()  # Más específico primero

    # El path exacto que se está solicitando (el más específico, tras el reverse = índice 0)
    exact_path = paths_to_check[0] if paths_to_check else area.upper()

    # 5. BUSQUEDA DE ACL (User_Ruta_Access) — Manda sobre el rol
    res_acl = await db.execute(
        select(Rutas.ruta, User_Ruta_Access)
        .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
        .where(Rutas.ruta.in_(paths_to_check))
        .where(User_Ruta_Access.user_id == current_user.id)
    )
    acls_encontrados = {row[0]: row[1] for row in res_acl.all()}

    for path_in_tree in paths_to_check:
        if path_in_tree in acls_encontrados:
            acl_obj = acls_encontrados[path_in_tree]
            effective_type: str = acl_obj.access_type

            if effective_type == "deny_all":
                # ── Excepción de navegación ────────────────────────────────────
                # Solo se permite navegar (allow_view) si el path EXACTO solicitado
                # (exact_path) o alguno de sus descendientes tiene un permiso positivo.
                # Esto evita que /test2 sea accesible solo porque /test1 tiene permiso,
                # ya que ambos son hijos de VENTAS pero son carpetas independientes.
                if required_access == "allow_read":
                    res_positive = await db.execute(
                        select(User_Ruta_Access)
                        .join(Rutas, Rutas.id == User_Ruta_Access.ruta_id)
                        .where(User_Ruta_Access.user_id == current_user.id)
                        .where(User_Ruta_Access.access_type != "deny_all")
                        .where(
                            or_(
                                Rutas.ruta == exact_path,
                                Rutas.ruta.like(exact_path + "/%"),
                            )
                        )
                    )
                    if res_positive.scalars().first():
                        # El path solicitado (o un descendiente) tiene permisos → permite navegar
                        return "allow_view"
                raise HTTPException(status_code=403, detail="Acceso denegado (ACL: deny_all)")

            if required_access == "allow_write":
                if effective_type == "allow_write":
                    return effective_type
                # allow_read, allow_view y allow_view_root no satisfacen write
                raise HTTPException(
                    status_code=403,
                    detail="Solo lectura (ACL heredado). Se requiere permiso de escritura.",
                )

            if required_access == "allow_read" and effective_type in _READ_COMPATIBLE:
                return effective_type

    # 6. BUSQUEDA POR ROL (Lógica Avanzada Dinámica)
    if user_ext_in_area:
        res_role_perms = await db.execute(
            select(Rutas.ruta, Permisos.fastapi_action)
            .join(Permiso_rol, Permiso_rol.id_permiso == Permisos.id)
            .join(Rutas, Rutas.id == Permiso_rol.ruta_id)
            .where(Permiso_rol.id_rol == user_ext_in_area.rol_id)
            .where(Rutas.ruta.in_(paths_to_check))
        )

        # Agrupamos permisos por ruta — {ruta: set(fastapi_actions)}
        role_perms_map: dict[str, set[str]] = {}
        for r, p_action in res_role_perms.all():
            if r not in role_perms_map:
                role_perms_map[r] = set()
            role_perms_map[r].add(p_action)

        # Revisamos herencia de permisos de rol (más específico primero)
        for path_in_tree in paths_to_check:
            if path_in_tree in role_perms_map:
                actions = role_perms_map[path_in_tree]

                if required_access == "allow_write" and "allow_write" in actions:
                    return "allow_write"

                if required_access == "allow_read":
                    # Retornar el tipo de mayor prioridad disponible
                    for access_type in _ACCESS_PRIORITY:
                        if access_type in actions:
                            if access_type in _READ_COMPATIBLE:
                                return access_type

    # 7. Denegación final
    raise HTTPException(
        status_code=403,
        detail=f"No tienes el permiso necesario ({required_access}) para esta ruta.",
    )
