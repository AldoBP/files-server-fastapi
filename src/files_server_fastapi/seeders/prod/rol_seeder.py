from sqlmodel import Session, select
from files_server_fastapi.models.rol_model import Rol


DEFAULT_ROLES = [
    {
        "role_name": "SUPER_ADMIN",
        "description": "Root / Sudoer global",
        "privilege_level": 2,
    },
    {
        "role_name": "AREA_ADMIN",
        "description": "Dueño del Grupo Linux",
        "privilege_level": 1,
    },
    {
        "role_name": "EDITOR",
        "description": "Usuario con permisos RW",
        "privilege_level": 0,
    },
    {
        "role_name": "VIEWER",
        "description": "Usuario con permisos solo lectura",
        "privilege_level": 0,
    },
]


def seed_roles(session: Session) -> None:
    """
    Inserta los roles predeterminados si aún no existen en la base de datos.
    Es idempotente: se puede llamar múltiples veces sin crear duplicados.
    """
    for role_data in DEFAULT_ROLES:
        statement = select(Rol).where(Rol.role_name == role_data["role_name"])
        existing = session.exec(statement).first()

        if not existing:
            session.add(Rol(**role_data))

    session.commit()
