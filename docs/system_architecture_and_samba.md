# Arquitectura del Sistema: ¿Cómo Funciona la Capa Web vs Samba?

Una de las características principales de este sistema es su capacidad de desacoplar el acceso a los archivos a través de la web del acceso a nivel de red (Samba).

Para entender cómo es que los usuarios pueden visualizar, descargar y gestionar archivos desde el **frontend** sin necesidad de tener Samba activado, debemos observar la arquitectura en dos capas distintas:

## 1. La Capa Web (FastAPI + PostgreSQL)

Cuando un usuario interactúa con el sistema mediante el navegador web (el frontend), la comunicación se realiza exclusivamente mediante peticiones HTTP(S) hacia el backend desarrollado en FastAPI. 

En este flujo **Samba no participa en absoluto**. El proceso funciona así:

1. **Autenticación y Autorización Lógica**: El usuario inicia sesión y obtiene un token JWT. Al intentar ver una carpeta, el backend de FastAPI consulta la base de datos (tablas `user_ruta_access` y `permisos`) para saber si tiene permisos de lectura (`web_view`, `web_full`, etc.).
2. **Acceso Físico Directo con Python**: Si la base de datos confirma que el usuario tiene acceso, FastAPI utiliza las librerías nativas de Python (`os`, `shutil`, `aiofiles`) para ir directamente al disco duro del servidor (e.g. `/srv/samba_data`), leer los archivos y enviarlos de vuelta al frontend.
3. **El Sistema Ignora a Samba**: Dado que FastAPI es ejecutado por un usuario del sistema (generalmente el usuario que corre la aplicación, como `www-data` o `root`), este tiene privilegios para leer el disco. FastAPI hace de intermediario y **aplica la seguridad lógicamente a través de código**, antes de entregar los archivos.

Por esto es que puedes utilizar todo el sistema web sin tener el flag `samba_enabled` activado.

## 2. La Capa de Red Local (Samba / Linux ACL)

¿Entonces, para qué sirve activar Samba?

Activar Samba (`samba_enabled = True`) es una funcionalidad diseñada **exclusivamente** para aquellos usuarios que necesitan acceder a los archivos desde el **Explorador de Archivos de Windows** o el **Finder de Mac** (mapeando una unidad de red). 

Aquí es donde entra la magia del script `sync_users.py`:

1. **Traducción de Permisos**: Como el Explorador de Archivos de Windows no le pregunta a la base de datos de PostgreSQL si el usuario tiene permiso (Windows se comunica directo con Samba), necesitamos que el sistema operativo Linux sepa qué permisos tiene cada quien.
2. **Las Listas de Control de Acceso (ACLs)**: El script de sincronización toma las reglas lógicas que existen en la base de datos web y las "traduce" a comandos de permisos de bajo nivel de Linux usando `setfacl` (por ejemplo, convierte `web_full` en `rwx`). 
3. **Usuario de Sistema Operativo**: El script también crea al usuario a nivel sistema operativo y le asigna una contraseña Samba usando `smbpasswd`.

### En Resumen

- **El Frontend web**: Utiliza la lógica de Python y PostgreSQL para saber qué mostrar. Nunca se comunica con el servicio Samba, lee el disco duro directamente.
- **Samba activado**: Funciona como una capa extra (paralela) para permitir a usuarios específicos montar las carpetas nativamente en sus computadoras. La seguridad en esta capa se asegura mediante la inyección directa de ACLs de Linux que reflejan los mismos permisos de la web.
