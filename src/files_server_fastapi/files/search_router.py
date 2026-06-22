"""
search_router.py — Motor de búsqueda del sistema de archivos.

Endpoints:
  GET /files/search       — Busca archivos y carpetas accesibles por el usuario.
  GET /files/search/users — Busca usuarios del área (solo AREA_ADMIN y SUPER_ADMIN).
"""
import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlmodel import select as sm_select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_verified_user, User

from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import (
    resolve_effective_access,
    _resolve_user_context,
)
from files_server_fastapi.models.permisos_model import User_Ruta_Access
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.rol_model import Rol
from files_server_fastapi.models.users_extend_model import Users_extend

router = APIRouter()


# ── Helpers internos ──────────────────────────────────────────────────────────

async def _is_area_admin_or_super(
    current_user: User,
    area: str | None,
    db: AsyncSession,
) -> bool:
    """
    Devuelve True si el usuario es SUPER_ADMIN o AREA_ADMIN del área indicada.
    Si area es None, comprueba solo si es SUPER_ADMIN.
    """
    result_ext = await db.execute(
        select(Users_extend).where(Users_extend.user_id == current_user.id)
    )
    user_exts = result_ext.scalars().all()

    for ext in user_exts:
        res_rol = await db.execute(select(Rol).where(Rol.id == ext.rol_id))
        rol = res_rol.scalars().first()
        if not rol:
            continue
        role_upper = rol.role_name.upper()

        if role_upper == "SUPER_ADMIN":
            return True

        if role_upper == "AREA_ADMIN" and area:
            res_area = await db.execute(select(Area).where(Area.id == ext.area_id))
            a = res_area.scalars().first()
            if a and a.area_name.upper() == area.upper():
                return True

    return False


async def _walk_and_search(
    area: str,
    base_path: str,
    rel_path: str,
    query: str,
    user_id: int,
    user_ext_in_area,
    is_super_admin: bool,
    db: AsyncSession,
    preloaded_acls: dict,
    results: list,
    max_results: int = 50,
) -> None:
    """
    Recorre recursivamente el directorio, aplicando el motor de permisos en
    cada nivel. Agrega al listado `results` los archivos y carpetas cuyo nombre
    contenga `query` (búsqueda case-insensitive).
    """
    if len(results) >= max_results:
        return

    try:
        with os.scandir(base_path) as entries:
            for entry in entries:
                if len(results) >= max_results:
                    return

                child_rel = (rel_path.rstrip("/") + "/" + entry.name).lstrip("/")

                if entry.is_dir(follow_symlinks=False):
                    # Verificar acceso a esta subcarpeta
                    child_access = await resolve_effective_access(
                        area=area,
                        subpath=child_rel,
                        user_id=user_id,
                        user_ext_in_area=user_ext_in_area,
                        is_super_admin=is_super_admin,
                        db=db,
                        preloaded_acls=preloaded_acls,
                    )

                    if child_access is None or child_access == "deny_all":
                        continue  # Carpeta bloqueada → no entrar ni mostrar

                    if query.lower() in entry.name.lower():
                        results.append({
                            "name": entry.name,
                            "type": "folder",
                            "path": "/" + child_rel,
                            "area": area,
                            "access": child_access,
                        })

                    # Recurse dentro de la carpeta accesible
                    await _walk_and_search(
                        area=area,
                        base_path=entry.path,
                        rel_path=child_rel,
                        query=query,
                        user_id=user_id,
                        user_ext_in_area=user_ext_in_area,
                        is_super_admin=is_super_admin,
                        db=db,
                        preloaded_acls=preloaded_acls,
                        results=results,
                        max_results=max_results,
                    )

                else:
                    # Archivos: visibles si llegamos hasta aquí (acceso al padre ya validado)
                    if query.lower() in entry.name.lower():
                        info = entry.stat()
                        size_kb = info.st_size / 1024
                        size_str = (
                            f"{size_kb:.1f} KB" if size_kb < 1024
                            else f"{size_kb / 1024:.1f} MB"
                        )
                        results.append({
                            "name": entry.name,
                            "type": "file",
                            "path": "/" + child_rel.rsplit("/", 1)[0] if "/" in child_rel else "/",
                            "area": area,
                            "size": size_str,
                        })

    except PermissionError:
        pass  # Ignorar silenciosamente errores del SO


# ── Endpoint 1: Búsqueda de archivos y carpetas ───────────────────────────────

@router.get(
    "/search",
    summary="Buscar archivos y carpetas accesibles",
    tags=["Búsqueda"],
)
async def search_files(
    q: str = Query(..., min_length=1, description="Texto a buscar (nombre de archivo o carpeta)"),
    area: str = Query(None, description="Área donde buscar (ej: Ventas). Si se omite, busca en todas las áreas accesibles."),
    limit: int = Query(50, ge=1, le=200, description="Número máximo de resultados"),
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Devuelve archivos y carpetas cuyo nombre contenga el texto buscado,
    filtrando automáticamente según los permisos del usuario.

    - Si no se especifica un área, busca en el área del usuario y en las carpetas que le han compartido.
    - El usuario solo verá resultados de rutas a las que tiene acceso.
    - Las carpetas bloqueadas (deny_all o sin regla) se omiten completamente.
    """
    if ".." in q or (area and ".." in area):
        raise HTTPException(status_code=400, detail="Parámetros inválidos.")

    areas_to_search = set()

    if area:
        areas_to_search.add(area.upper())
    else:
        # 1. Obtener áreas donde el usuario tiene un perfil (rol)
        res_ext = await db.execute(
            select(Users_extend, Area)
            .join(Area, Area.id == Users_extend.area_id)
            .where(Users_extend.user_id == current_user.id)
        )
        for ext, area_obj in res_ext.all():
            areas_to_search.add(area_obj.area_name.upper())

        # 2. Obtener áreas donde tiene algún permiso explícito (ACL)
        res_acls_areas = await db.execute(
            select(Rutas.ruta)
            .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
            .where(User_Ruta_Access.user_id == current_user.id)
            .where(User_Ruta_Access.access_type != "deny_all")
        )
        for ruta in res_acls_areas.scalars().all():
            areas_to_search.add(ruta.split("/")[0].upper())

        # 3. Si es super admin, tiene acceso a todo.
        is_super_admin = False
        res_roles = await db.execute(
            select(Rol.role_name)
            .join(Users_extend, Users_extend.rol_id == Rol.id)
            .where(Users_extend.user_id == current_user.id)
        )
        if any(r.upper() == "SUPER_ADMIN" for r in res_roles.scalars().all()):
            res_all_areas = await db.execute(select(Area.area_name))
            for a_name in res_all_areas.scalars().all():
                areas_to_search.add(a_name.upper())

    if not areas_to_search:
        return {"query": q, "area": "Todas", "total": 0, "results": []}

    # Pre-cargar TODAS las ACLs del usuario para optimizar las queries recursivas
    res_bulk = await db.execute(
        select(Rutas.ruta, User_Ruta_Access)
        .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
        .where(User_Ruta_Access.user_id == current_user.id)
    )
    preloaded_acls: dict = {row[0]: row[1] for row in res_bulk.all()}

    results: list = []

    for current_area in areas_to_search:
        if len(results) >= limit:
            break

        is_super_admin, user_ext_in_area = await _resolve_user_context(current_user, current_area, db)

        # Verificar acceso a la raíz de este área
        root_access = await resolve_effective_access(
            area=current_area,
            subpath="/",
            user_id=current_user.id,
            user_ext_in_area=user_ext_in_area,
            is_super_admin=is_super_admin,
            db=db,
            preloaded_acls=preloaded_acls
        )

        if root_access is None or root_access == "deny_all":
            continue

        root_dir = os.path.join(BASE_DIR, current_area.upper())
        if not os.path.isdir(root_dir):
            continue

        await _walk_and_search(
            area=current_area,
            base_path=root_dir,
            rel_path="",
            query=q,
            user_id=current_user.id,
            user_ext_in_area=user_ext_in_area,
            is_super_admin=is_super_admin,
            db=db,
            preloaded_acls=preloaded_acls,
            results=results,
            max_results=limit,
        )

    return {
        "query": q,
        "area": area if area else "Todas",
        "total": len(results),
        "results": results,
    }


# ── Endpoint 2: Búsqueda de usuarios (solo admins) ────────────────────────────

@router.get(
    "/search/users",
    summary="Buscar usuarios del área (solo administradores)",
    tags=["Búsqueda"],
)
async def search_users(
    q: str = Query(..., min_length=1, description="Nombre o email del usuario a buscar"),
    area: str = Query(None, description="Filtrar por área (ej: Ventas). Si se omite, busca en todas las áreas (solo SUPER_ADMIN)."),
    limit: int = Query(20, ge=1, le=100, description="Número máximo de resultados"),
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Busca usuarios por nombre o email.
    - Solo accesible para SUPER_ADMIN y AREA_ADMIN.
    - AREA_ADMIN solo puede buscar dentro de su propio área.
    - SUPER_ADMIN puede buscar en todas las áreas o filtrar por una específica.
    """
    # 1. Verificar que el usuario tiene permisos de administración
    authorized = await _is_area_admin_or_super(current_user, area, db)
    if not authorized:
        raise HTTPException(
            status_code=403,
            detail="Solo los administradores de área pueden buscar usuarios."
        )

    # 2. Determinar si es super admin (puede ver todas las áreas)
    is_super_admin, _ = await _resolve_user_context(current_user, area or "", db)

    # 3. Construir query base: buscar en users_extend + join con área y rol
    #    La tabla Users (de autenticación) la consultamos por separado vía user_id
    stmt = (
        select(Users_extend, Area, Rol)
        .join(Area, Area.id == Users_extend.area_id)
        .join(Rol, Rol.id == Users_extend.rol_id)
    )

    # Si no es super admin, limitar al área del usuario actual
    if not is_super_admin:
        # Obtener el área_id del admin actual
        res_admin_ext = await db.execute(
            select(Users_extend).where(Users_extend.user_id == current_user.id)
        )
        admin_ext = res_admin_ext.scalars().first()
        if not admin_ext:
            raise HTTPException(status_code=403, detail="No se encontró tu perfil de área.")
        stmt = stmt.where(Users_extend.area_id == admin_ext.area_id)
    elif area:
        # Super admin con filtro de área específica
        res_area = await db.execute(select(Area).where(Area.area_name.ilike(area)))
        area_obj = res_area.scalars().first()
        if not area_obj:
            raise HTTPException(status_code=404, detail=f"Área '{area}' no encontrada.")
        stmt = stmt.where(Users_extend.area_id == area_obj.id)

    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return {"query": q, "area": area, "total": 0, "results": []}

    # 4. Para cada users_extend, buscar el nombre y email en la tabla de autenticación
    #    Usamos la conexión de auth (oauth2fast_fastapi)
    from pgsqlasync2fast_fastapi.dependencies import get_db_session as get_auth_session
    from oauth2fast_fastapi import User as AuthUser

    # Obtener todos los user_ids de los resultados
    user_ids = [row[0].user_id for row in rows]

    # Consultar los datos de autenticación (nombre, email) en la BD de auth
    try:
        from sqlalchemy import text
        auth_result = await db.execute(
            text("SELECT id, name, email FROM users WHERE id = ANY(:ids)"),
            {"ids": user_ids}
        )
        auth_users = {row[0]: {"name": row[1], "email": row[2]} for row in auth_result.all()}
    except Exception:
        # Si la tabla users está en otra BD, fallback con datos disponibles
        auth_users = {}

    # 5. Filtrar por la query (nombre o email) y construir respuesta
    q_lower = q.lower()
    matched = []

    for user_ext, area_obj, rol_obj in rows:
        auth_data = auth_users.get(user_ext.user_id, {})
        name = auth_data.get("name", f"Usuario #{user_ext.user_id}")
        email = auth_data.get("email", "")

        # Filtro por texto: nombre o email deben contener la query
        if q_lower not in name.lower() and q_lower not in email.lower():
            continue

        matched.append({
            "user_id": user_ext.user_id,
            "users_extend_id": user_ext.id,
            "name": name,
            "email": email,
            "role": rol_obj.role_name,
            "area": area_obj.area_name,
            "puesto": user_ext.puesto or "",
        })

    return {
        "query": q,
        "area": area,
        "total": len(matched),
        "results": matched,
    }
