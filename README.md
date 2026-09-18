# files-server-fastapi

Este repositorio es un paquete Python desarrollado con **FastAPI**. Actúa como un puente integral para la gestión de un servidor de archivos físico (**Samba**) utilizando **PostgreSQL** para administrar la estructura virtual de rutas y el control de acceso basado en roles (RBAC) de los usuarios.

## Características Principales

- **Gestión Avanzada de Usuarios (RBAC)**: Autorización en niveles (Usuarios, Administrador de Área, Administrador Global) para segmentar el acceso a los recursos.
- **Sincronización Transparente Samba/Linux**: Utiliza `setfacl` y `smbpasswd` para traducir los permisos web directamente en la capa de sistema de archivos de Linux.
- **Servidor WebDAV**: Incluye integración nativa vía WSGI con clientes WebDAV.
- **Auditoría y Papelera**: Registro de actividades, archivos recientes y una papelera de reciclaje lógica para evitar pérdida de información.

## Documentación

Para instalar y comprender el funcionamiento interno del paquete, puedes consultar los siguientes documentos:

- 👉 [**Guía de Instalación (Installation Guide)**](docs/installation_guide.md)
- 👉 [**Documentación Técnica Detallada (Technical Reference)**](docs/technical_reference.md)
- 👉 [**Documentación de capa web y samba**](docs/system_architecture_and_samba.md)