"""
Servicio de Notificaciones
==========================

Responsabilidades:
  1. Persistir la notificación en la tabla `notificaciones`.
  2. Entregar el evento en tiempo real al usuario si tiene una conexión
     SSE activa, usando asyncio.Queue en memoria.

El manager de queues (NotificationManager) es un singleton de proceso.
Cada usuario puede tener varias pestañas/conexiones abiertas, por eso
se mantiene una lista de queues por user_id.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from files_server_fastapi.models.notificaciones_model import Notificacion

logger = logging.getLogger(__name__)


# ── SSE Queue Manager ────────────────────────────────────────────────────────

class NotificationManager:
    """
    Mantiene las colas asyncio de los clientes SSE conectados.

    Diseño:
        _queues: dict[user_id, list[asyncio.Queue]]

    Soporta múltiples pestañas/conexiones por usuario.
    """

    def __init__(self) -> None:
        self._queues: dict[int, list[asyncio.Queue]] = {}

    def subscribe(self, user_id: int) -> asyncio.Queue:
        """Registra una nueva conexión SSE para el usuario y devuelve su queue."""
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(user_id, []).append(q)
        logger.debug("SSE: usuario %s suscrito (%d conexiones activas)", user_id, len(self._queues[user_id]))
        return q

    def unsubscribe(self, user_id: int, q: asyncio.Queue) -> None:
        """Elimina la queue cuando el cliente cierra la conexión SSE."""
        queues = self._queues.get(user_id, [])
        if q in queues:
            queues.remove(q)
        if not queues:
            self._queues.pop(user_id, None)
        logger.debug("SSE: usuario %s desuscrito", user_id)

    async def push(self, user_id: int, payload: dict) -> None:
        """
        Envía el payload a todas las queues activas del usuario.
        Si el usuario no tiene conexiones abiertas, no hace nada
        (la notificación ya quedó guardada en BD).
        """
        for q in self._queues.get(user_id, []):
            await q.put(payload)


# Singleton compartido por todo el proceso FastAPI
manager = NotificationManager()


# ── Función principal del servicio ───────────────────────────────────────────

async def crear_notificacion(
    db: AsyncSession,
    user_id: int,
    tipo: str,
    titulo: str,
    mensaje: str,
    meta: dict[str, Any] | None = None,
) -> Notificacion:
    """
    Crea una notificación en la BD y la empuja por SSE si el usuario
    tiene una conexión activa.

    Args:
        db:       Sesión de base de datos activa.
        user_id:  ID del usuario destinatario.
        tipo:     Categoría del evento (ej: "acceso_carpeta").
        titulo:   Título corto (se muestra en el badge de notificaciones).
        mensaje:  Texto completo con el contexto del evento.
        meta:     Diccionario opcional con datos extra para el frontend
                  (ej: ruta_id, area, permiso). Se serializa a JSON.

    Returns:
        La instancia `Notificacion` recién creada.
    """
    meta_json = json.dumps(meta, ensure_ascii=False) if meta else None

    notif = Notificacion(
        user_id=user_id,
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        meta=meta_json,
    )
    db.add(notif)
    await db.commit()
    await db.refresh(notif)

    # Empujar por SSE si el usuario está conectado
    payload = {
        "id": notif.id,
        "tipo": notif.tipo,
        "titulo": notif.titulo,
        "mensaje": notif.mensaje,
        "leida": notif.leida,
        "created_at": notif.created_at.isoformat(),
        "meta": meta,
    }
    await manager.push(user_id, payload)

    logger.info("Notificación creada: user_id=%s tipo=%s", user_id, tipo)
    return notif
