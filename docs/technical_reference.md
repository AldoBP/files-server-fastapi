# Documentación Técnica: files-server-fastapi

Este documento describe la arquitectura, la lógica de negocio y los componentes principales del paquete `files-server-fastapi`.

## 1. Visión General

El paquete es un backend construido en **FastAPI** diseñado para la gestión de un servidor de archivos. Actúa como un puente inteligente entre una base de datos **PostgreSQL** y un sistema de archivos físico (**Samba**).

Su objetivo principal es manejar el control de acceso basado en roles (RBAC) a nivel web, y sincronizar de forma automática esos accesos con las Listas de Control de Acceso (ACLs) de Linux. Además, proporciona acceso a los archivos mediante **WebDAV**.

## 2. Modelos de Base de Datos (Models)

El sistema utiliza SQLAlchemy (SQLModel) para mapear sus entidades. Los modelos extienden el sistema de autenticación provisto por la librería `oauth2fast-fastapi`.

### Entidades Core

- **Area (`area_model.py`)**: Representa un departamento o grupo lógico (ej. SISTEMAS, RH). Soporta *soft-delete*.
- **Rol (`rol_model.py`)**: Define los roles de usuario. Introduce un `privilege_level` que desliga el nombre del rol del nivel de autorización:
  - `0`: Usuario regular.
  - `1`: Administrador de Área.
  - `2`: Administrador Global (Sistemas).
- **Users Extend (`users_extend_model.py`)**: Extiende el modelo `User` base de autenticación con campos específicos del sistema: `area_id`, `rol_id`, `puesto`, y el flag `samba_enabled`. También implementa el *soft-delete* (baja lógica del empleado).
- **Rutas (`rutas_model.py`)**: Representa de manera lógica las carpetas y subcarpetas físicas que existen dentro del área. Están atadas a un `area_id` y soportan anidación.

### Permisos y Control de Acceso

- **Permisos (`permisos_model.py`)**: Define los niveles de acceso. Mapea una acción web (`fastapi_action` como `web_view`, `web_full`) a un permiso en Linux (`linux_acl` como `r-x`, `rwx`).
- **User_Ruta_Access (`permisos_model.py`)**: Almacena de forma granular qué nivel de acceso tiene un usuario sobre una ruta (carpeta) en específico.

### Utilidades y Registro

- **UserFavorito (`favoritos_model.py`)**: Permite a los usuarios marcar carpetas como "favoritas" para rápido acceso en la UI.
- **Notificacion (`notificaciones_model.py`)**: Guarda las notificaciones del sistema para eventos como compartición de carpetas o revocación de accesos.
- **UserTrash (`user_trash_model.py`)**: Registra la metadata de archivos o carpetas enviados a la Papelera de Reciclaje (soft-delete de archivos).
- **UserFileAccess (`user_file_access_model.py`)**: Registra accesos recientes a archivos para auditoría y visualización de "elementos recientes".

## 3. Lógica de Autenticación y Autorización (Dependencies)

El archivo `user_dependencies.py` es fundamental para la seguridad. Provee los siguientes inyectables para FastAPI:

- `get_active_user`: Asegura que el usuario autenticado (con JWT) no esté dado de baja (`deleted_at` no nulo).
- `require_area_admin_or_superadmin`: Exige nivel de privilegio >= 1.
- `require_superadmin`: Exige nivel de privilegio >= 2.

Esta separación por `privilege_level` garantiza que si el nombre del rol en la base de datos cambia (ej. de "Administrador" a "Jefe de Departamento"), la lógica del código backend permanezca intacta.

## 4. Rutas de la API (Routers)

Los controladores (endpoints) están segmentados según su dominio de responsabilidad.

### Gestión de Usuarios y Accesos
- **`users_extend_router.py`**: Gestiona la asignación de usuarios a áreas y roles. Expone endpoints para el *soft delete* (`/deactivate`), reactivación, y reseteos de contraseñas. Valida que un Administrador de Área solo modifique usuarios de su propia área.
- **`samba_router.py`**: Gestiona la activación (`/activate`) y desactivación (`/deactivate`) del acceso SMB a nivel usuario (usando comandos de Linux `smbpasswd`). Dispara la sincronización asíncrona de ACLs cuando un usuario se habilita.
- **`permisos_router.py`** y **`rol_router.py`**: Administran catálogos y accesos granulares a las rutas.

### Archivos y Directorios
- **`files_router.py`**: Agrupa los sub-enrutadores del sistema de archivos (`list_router`, `upload_router`, `delete_router`, `trash_router`, etc.).
- **`rutas_router.py`** y **`area_router.py`**: Realizan CRUD sobre las áreas y el árbol virtual de carpetas.

## 5. Scripts de Sincronización

Estos scripts conectan el estado de la base de datos PostgreSQL con el sistema de archivos físico en Linux/Samba.

### `sync_users.py` (Sincronización BD -> Linux ACLs)
Es el motor principal para propagar la seguridad a nivel de sistema operativo.
1. Lee los usuarios verificados y busca sus roles y accesos granulares en BD.
2. Verifica si el usuario tiene `samba_enabled = True`. Si es `False`, usa `setfacl` para revocar completamente su acceso al servidor y deshabilitarlo en `smbpasswd`.
3. Si está activado, aplica **Modo Base** (el permiso por defecto que su Rol dictamina sobre el Área asignada).
4. Aplica **Modo Granular** (excepciones de `user_ruta_access`): Abre el acceso necesario (`r-x`) en los directorios padre para que el usuario pueda navegar, y aplica los permisos dictados (ej. lectura, escritura) en la ruta destino específica.

### `sync_folders_to_db.py` (Sincronización Linux -> BD)
Actualiza el árbol de rutas en la base de datos a partir del disco.
1. Escanea de forma recursiva el directorio raíz (e.g., `/srv/samba_data`).
2. Verifica las carpetas que representan Áreas y registra las subcarpetas faltantes en la tabla `rutas` de PostgreSQL.
3. Esto garantiza que si una carpeta fue creada manualmente a nivel servidor (o vía SMB nativo), la interfaz web o el sistema de DB la reconozca para poder asignar permisos granulares sobre ella.

## 6. WebDAV (Middleware)

En `__init__.py` se expone `get_webdav_wsgi_app()`, el cual monta un servidor WSGI de `wsgidav` dentro de la aplicación asíncrona de FastAPI. Esto habilita que clientes externos se conecten vía protocolo WebDAV bajo el mismo contexto de autenticación o mapeo de disco, integrando así otra forma de consumir los archivos sin depender de Samba exclusivo para usuarios remotos.
