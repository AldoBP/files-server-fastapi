from fastapi import HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_user, User
from files_server_fastapi.models.permisos_model import User_Ruta_Access
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.users_extend_model import Users_extend
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.rol_model import Rol


async def check_folder_access(
    area: str,
    subpath: str = "/",
    required_access: str = "allow_read",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Verifica si el usuario actual tiene acceso al área y subpath indicados.
    required_access: 'allow_read' (por defecto) o 'allow_write'
    """
    # 1. Obtener extensión de usuario y verificar roles/áreas
    result_ext = await db.execute(
        select(Users_extend).where(Users_extend.user_id == current_user.id)
    )
    user_exts = result_ext.scalars().all()
    
    # 2. Verificar si el usuario es SUPER_ADMIN en cualquier área
    for ext in user_exts:
        res_rol = await db.execute(select(Rol).where(Rol.id == ext.rol_id))
        rol = res_rol.scalars().first()
        if rol and rol.role_name.upper() == "SUPER_ADMIN":
            return True  # SUPER_ADMIN tiene acceso universal a todas las carpetas, salta otras validaciones.

    # 3. Si no es SUPER_ADMIN, verificar pertenencia al área indicada
    area_obj = None
    user_ext_match = None
    rol_name = ""
    
    for ext in user_exts:
        res_area = await db.execute(select(Area).where(Area.id == ext.area_id))
        a = res_area.scalars().first()
        if a and a.area_name.upper() == area.upper():
            area_obj = a
            user_ext_match = ext
            break

    if not area_obj or not user_ext_match:
        raise HTTPException(status_code=403, detail="No perteneces a esta área")

    # Obtener el Rol Base del usuario en ESTA área específica
    res_rol = await db.execute(select(Rol).where(Rol.id == user_ext_match.rol_id))
    rol_obj = res_rol.scalars().first()
    rol_name = rol_obj.role_name.lower() if rol_obj else ""

    # 2. Verificar ACL específico por ruta y herencia de padres
    logical_path = f"/{area.upper()}/{subpath.strip('/')}".replace("//", "/")
    parts = logical_path.strip("/").split("/")
    paths_to_check = []
    current_path = ""
    for part in parts:
        if part:
            current_path += f"/{part}"
            paths_to_check.append(current_path)

    paths_to_check.reverse()  # Más específico primero

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
                raise HTTPException(status_code=403, detail="Acceso denegado a esta carpeta o heredado de una superior")

            if required_access == "allow_write":
                if acl_obj.access_type == "allow_write":
                    return True
                elif acl_obj.access_type == "allow_read":
                    raise HTTPException(status_code=403, detail="Solo tienes permiso de lectura (regla heredada)")

            if required_access == "allow_read":
                if acl_obj.access_type in ["allow_read", "allow_write"]:
                    return True

    # 3. Sin ACL explícito → aplicar reglas del Rol Base
    if required_access == "allow_write":
        if "editor" not in rol_name and "admin" not in rol_name:
            raise HTTPException(status_code=403, detail="Tu rol no permite modificar esta carpeta")

    return True
