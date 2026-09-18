# Guía de Instalación: files-server-fastapi

Esta guía describe los pasos necesarios para instalar y configurar el backend del servidor de archivos junto con sus dependencias en el sistema operativo.

## Prerrequisitos del Sistema (Linux)

Dado que este proyecto interactúa estrechamente con el sistema operativo para gestionar permisos y accesos de red, se requiere un entorno Linux (recomendado Debian/Ubuntu) con los siguientes paquetes instalados:

```bash
# Actualizar repositorios
sudo apt update

# Instalar Python (>=3.10), PostgreSQL (o cliente) y utilidades de ACL/Samba
sudo apt install -y python3 python3-pip python3-venv acl samba smbclient sudo
```

Asegúrate de que el paquete `acl` esté instalado, ya que el sistema utiliza `setfacl` de manera extensiva para asegurar las carpetas.

## 1. Clonar el Repositorio e Instalar Dependencias

Este proyecto utiliza [uv](https://github.com/astral-sh/uv) como gestor de paquetes por su increíble velocidad, aunque puedes usar `pip` estándar.

```bash
# Clonar el proyecto
git clone https://github.com/AldoBP/files-server-fastapi.git
cd files-server-fastapi

# Opcional pero recomendado: usar uv para instalar
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv
source .venv/bin/activate
uv pip install -r pyproject.toml
```

## 2. Configurar la Estructura de Directorios (Samba/Disco)

Debes crear el directorio raíz que el sistema gestionará y asegurarte de tener los permisos correctos.

```bash
# Por defecto el sistema asume /srv/samba_data
sudo mkdir -p /srv/samba_data

# Asegurar que el usuario que corre la aplicación web (ej. el tuyo actual o www-data) sea el dueño
sudo chown -R $USER:$USER /srv/samba_data
```

## 3. Configuración del Archivo `.env`

Copia o crea el archivo `.env` en la raíz del proyecto. Este archivo contiene la configuración de la base de datos y de la ruta del servidor de archivos.

```env
# Ejemplo de configuración .env
DB_CONNECTIONS__DEFAULT__HOST=127.0.0.1
DB_CONNECTIONS__DEFAULT__PORT=5432
DB_CONNECTIONS__DEFAULT__DATABASE=files_server_db
DB_CONNECTIONS__DEFAULT__USERNAME=postgres
DB_CONNECTIONS__DEFAULT__PASSWORD=tu_contraseña

FILES_BASE_DIR=/srv/samba_data
SYNC_FS_LOG_FILE=/var/log/sync_folders.log
SYNC_LOG_FILE=/var/log/sync_users.log
SAMBA_SYNC_SCRIPT=sync_users.py
```

## 4. Configurar Permisos de `sudo` sin contraseña (Requerido para Samba)

Para que FastAPI pueda activar usuarios de Samba sin colgarse esperando una contraseña de sudo, debes permitir al usuario que ejecuta el backend correr comandos específicos de Samba sin contraseña.

Abre el archivo de configuración de sudoers:
```bash
sudo visudo
```
Y agrega al final del archivo (reemplazando `tu_usuario` por el usuario que ejecutará el servidor):
```text
tu_usuario ALL=(ALL) NOPASSWD: /usr/bin/smbpasswd, /usr/sbin/useradd, /usr/bin/python3 /ruta/absoluta/a/tu/proyecto/sync_users.py
```

## 5. Levantar el Servidor FastAPI

Una vez que la base de datos está corriendo y los permisos están dados, puedes iniciar el servidor:

```bash
# Ejecutar en modo desarrollo
fastapi dev src/files_server_fastapi/main.py
# O usando uvicorn directamente
uvicorn files_server_fastapi.main:app --host 0.0.0.0 --port 8000 --reload
```

## 6. Sincronización Inicial (Opcional)

Si ya tienes una estructura de carpetas creada físicamente en `/srv/samba_data`, puedes sincronizarla hacia la base de datos de PostgreSQL corriendo:

```bash
python3 sync_folders_to_db.py
```
