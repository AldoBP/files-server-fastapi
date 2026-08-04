from sqlmodel import Session, select
from files_server_fastapi.models.permisos_model import Permisos


DEFAULT_PERMISOS = [
    {
        "permiso_name": "Solo Vista",
        "description": (
            "Solo puede ver archivos y carpetas en la interfaz web. "
            "Puede abrir documentos Office en OnlyOffice en modo solo lectura."
        ),
        "linux_acl": "r--",
        "fastapi_action": "web_view",
    },
    {
        "permiso_name": "Vista y Edición",
        "description": (
            "Puede ver y editar archivos con OnlyOffice. "
            "Sin descarga ni subida de archivos."
        ),
        "linux_acl": "r--",
        "fastapi_action": "web_edit",
    },
    {
        "permiso_name": "Vista, Edición y Subida",
        "description": (
            "Puede ver, editar con OnlyOffice, descargar, "
            "subir archivos y crear carpetas."
        ),
        "linux_acl": "rw-",
        "fastapi_action": "web_upload",
    },
    {
        "permiso_name": "Control Total",
        "description": (
            "Todos los permisos: ver, editar, descargar, "
            "subir, crear carpetas y eliminar."
        ),
        "linux_acl": "rwx",
        "fastapi_action": "web_full",
    },
    {
        "permiso_name": "Sin Acceso",
        "description": "Bloquea por completo el acceso a la carpeta y anula cualquier rol.",
        "linux_acl": "---",
        "fastapi_action": "deny_all",
    },
]


def seed_permisos(session: Session) -> None:
    """
    Inserta los permisos predeterminados si aún no existen en la base de datos.
    Es idempotente: se puede llamar múltiples veces sin crear duplicados.
    Usa 'fastapi_action' como clave única para evitar duplicados.
    """
    for permiso_data in DEFAULT_PERMISOS:
        statement = select(Permisos).where(
            Permisos.fastapi_action == permiso_data["fastapi_action"]
        )
        existing = session.exec(statement).first()

        if not existing:
            session.add(Permisos(**permiso_data))

    session.commit()
