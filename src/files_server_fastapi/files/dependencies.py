from fastapi import HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_verified_user, User
from files_server_fastapi.models.permisos_model import User_Ruta_Access, Permisos, Permiso_rol
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.users_extend_model import Users_extend
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.rol_model import Rol


async def check_folder_access(
    area: str,
    subpath: str = "/",
    required_access: str = "allow_read",
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Verifica si el usuario actual tiene acceso al área y subpath indicados.
    required_access: 'allow_read' (por defecto) o 'allow_write'
    """
    # 1. Obtener extensiones de usuario y roles
    result_ext = await db.execute(
        select(Users_extend).where(Users_extend.user_id == current_user.id)
    )
    user_exts = result_ext.scalars().all()

    # 2. Verificar si el usuario es SUPER_ADMIN en cualquier área
    for ext in user_exts:
        res_rol = await db.execute(select(Rol).where(Rol.id == ext.rol_id))
        rol = res_rol.scalars().first()
        if rol and rol.role_name.upper() == "SUPER_ADMIN":
            return True  # SUPER_ADMIN tiene acceso universal

    # 3. Identificar si el usuario pertenece al área solicitada
    # (Guardamos el rol_id para usarlo si no hay ACL específico)
    user_ext_in_area = None
    for ext in user_exts:
        res_area = await db.execute(select(Area).where(Area.id == ext.area_id))
        a = res_area.scalars().first()
        if a and a.area_name.upper() == area.upper():
            user_ext_in_area = ext
            break

    # 4. Generar lista de rutas (jerarquía) para herencia
    logical_path = f"/{area.upper()}/{subpath.strip('/')}".replace("//", "/")
    parts = logical_path.strip("/").split("/")
    paths_to_check = []
    current_path = ""
    for part in parts:
        if part:
            current_path += f"/{part}"
            paths_to_check.append(current_path)

    paths_to_check.reverse()  # Más específico primero

    # 5. BUSQUEDA DE ACL (User_Ruta_Access) - Manda sobre el rol
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
            if acl_obj.access_type == "deny_all":
                raise HTTPException(status_code=403, detail="Acceso denegado (ACL: deny_all)")
            
            if required_access == "allow_write":
                if acl_obj.access_type == "allow_write":
                    return True
                elif acl_obj.access_type == "allow_read":
                    raise HTTPException(status_code=403, detail="Solo lectura (ACL heredado)")
            
            if required_access == "allow_read" and acl_obj.access_type in ["allow_read", "allow_write"]:
                return True

    # 6. BUSQUEDA POR ROL (Lógica Avanzada Dinámica)
    # Si el usuario pertenece al área, miramos qué permisos tiene su rol para esta ruta o superiores
    if user_ext_in_area:
        res_role_perms = await db.execute(
            select(Rutas.ruta, Permisos.fastapi_action)
            .join(Permiso_rol, Permiso_rol.id_permiso == Permisos.id)
            .join(Rutas, Rutas.id == Permiso_rol.ruta_id)
            .where(Permiso_rol.id_rol == user_ext_in_area.rol_id)
            .where(Rutas.ruta.in_(paths_to_check))
        )
        
        # Agrupamos permisos por ruta para facilitar herencia
        # Estructura: {"/RUTA": set(["allow_read", "allow_write"])}
        role_perms_map = {}
        for r, p_action in res_role_perms.all():
            if r not in role_perms_map: role_perms_map[r] = set()
            role_perms_map[r].add(p_action)

        # Revisamos herencia de permisos de rol
        for path_in_tree in paths_to_check:
            if path_in_tree in role_perms_map:
                actions = role_perms_map[path_in_tree]
                
                if required_access == "allow_write" and "allow_write" in actions:
                    return True
                
                if required_access == "allow_read" and ("allow_read" in actions or "allow_write" in actions):
                    return True

    # 7. Denegación final
    raise HTTPException(
        status_code=403,
        detail=f"No tienes el permiso necesario ({required_access}) para esta ruta."
    )
