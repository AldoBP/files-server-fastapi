"""
Router de Notificaciones
========================

Endpoints:
  GET  /notificaciones/         — Lista notificaciones del usuario autenticado
  GET  /notificaciones/stream   — Conexión SSE en tiempo real
  PATCH /notificaciones/{id}/leer   — Marcar una notificación como leída
  PATCH /notificaciones/leer-todas  — Marcar todas como leídas
  DELETE /notificaciones/{id}       — Eliminar una notificación
  DELETE /notificaciones/todas      — Eliminar todas las notificaciones del usuario
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from oauth2fast_fastapi import User
from pgsqlasync2fast_fastapi.dependencies import get_db_session

from files_server_fastapi.dependencies.user_dependencies import (
    get_active_user,
    get_active_user_stream,
)
from files_server_fastapi.models.notificaciones_model import Notificacion
from files_server_fastapi.notificaciones.service import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones"])


# ── GET /notificaciones/ ─────────────────────────────────────────────────────

@router.get(
    "/",
    summary="Listar notificaciones del usuario autenticado",
    response_model=list[dict],
)
async def list_notificaciones(
    solo_no_leidas: bool = Query(False, description="Si True, devuelve solo las no leídas"),
    limit: int = Query(50, ge=1, le=200, description="Máximo de notificaciones a retornar"),
    offset: int = Query(0, ge=0, description="Desplazamiento para paginación"),
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Devuelve las notificaciones del usuario autenticado ordenadas de más
    reciente a más antigua. Soporta paginación y filtro por estado de lectura.
    """
    query = (
        select(Notificacion)
        .where(Notificacion.user_id == current_user.id)
        .order_by(Notificacion.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if solo_no_leidas:
        query = query.where(Notificacion.leida == False)  # noqa: E712

    result = await db.execute(query)
    notifs = result.scalars().all()

    return [
        {
            "id": n.id,
            "tipo": n.tipo,
            "titulo": n.titulo,
            "mensaje": n.mensaje,
            "leida": n.leida,
            "created_at": n.created_at.isoformat(),
            "meta": json.loads(n.meta) if n.meta else None,
        }
        for n in notifs
    ]


# ── GET /notificaciones/stream — SSE ────────────────────────────────────────

@router.get(
    "/stream",
    summary="Conexión SSE en tiempo real para recibir notificaciones",
    response_class=StreamingResponse,
)
async def stream_notificaciones(
    current_user: User = Depends(get_active_user_stream),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Establece una conexión Server-Sent Events (SSE) persistente.

    El frontend debe abrir esta conexión con `EventSource`:

    ```js
    const es = new EventSource("/notificaciones/stream", { withCredentials: true });
    es.onmessage = (e) => {
        const notif = JSON.parse(e.data);
        // Mostrar la notificación en la UI
    };
    ```

    Cuando se asigne un ACL a este usuario, el servidor empuja el evento
    de forma instantánea sin que el cliente tenga que hacer polling.

    La conexión se mantiene abierta hasta que el cliente la cierre.
    Se envían heartbeats cada 30 segundos para evitar timeouts de proxy.
    """
    user_id = current_user.id
    q = manager.subscribe(user_id)

    # Cargar notificaciones no leídas pendientes al conectar
    pending_result = await db.execute(
        select(Notificacion)
        .where(Notificacion.user_id == user_id)
        .where(Notificacion.leida == False)  # noqa: E712
        .order_by(Notificacion.created_at.asc())
    )
    pending = pending_result.scalars().all()

    async def event_generator():
        try:
            # 1. Enviar notificaciones no leídas pendientes al reconectar
            for n in pending:
                payload = {
                    "id": n.id,
                    "tipo": n.tipo,
                    "titulo": n.titulo,
                    "mensaje": n.mensaje,
                    "leida": n.leida,
                    "created_at": n.created_at.isoformat(),
                    "meta": json.loads(n.meta) if n.meta else None,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # 2. Escuchar nuevos eventos en tiempo real
            while True:
                try:
                    # Esperar hasta 30 s; si no llega nada, mandar heartbeat
                    payload = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat para mantener la conexión viva ante proxies
                    yield ": heartbeat\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            manager.unsubscribe(user_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Nginx: deshabilitar buffer para SSE
        },
    )


# ── PATCH /notificaciones/{id}/leer ─────────────────────────────────────────

@router.patch(
    "/{notif_id}/leer",
    summary="Marcar una notificación como leída",
)
async def marcar_leida(
    notif_id: int,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(
        select(Notificacion)
        .where(Notificacion.id == notif_id)
        .where(Notificacion.user_id == current_user.id)
    )
    notif = result.scalars().first()

    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificación no encontrada.",
        )

    notif.leida = True
    db.add(notif)
    await db.commit()
    return {"message": "Notificación marcada como leída.", "id": notif_id}


# ── PATCH /notificaciones/leer-todas ────────────────────────────────────────

@router.patch(
    "/leer-todas",
    summary="Marcar todas las notificaciones del usuario como leídas",
)
async def marcar_todas_leidas(
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    await db.execute(
        update(Notificacion)
        .where(Notificacion.user_id == current_user.id)
        .where(Notificacion.leida == False)  # noqa: E712
        .values(leida=True)
    )
    await db.commit()
    return {"message": "Todas las notificaciones marcadas como leídas."}


# ── DELETE /notificaciones/{id} ──────────────────────────────────────────────

@router.delete(
    "/{notif_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una notificación",
)
async def eliminar_notificacion(
    notif_id: int,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(
        select(Notificacion)
        .where(Notificacion.id == notif_id)
        .where(Notificacion.user_id == current_user.id)
    )
    notif = result.scalars().first()

    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificación no encontrada.",
        )

    await db.delete(notif)
    await db.commit()


# ── DELETE /notificaciones/todas ─────────────────────────────────────────────

@router.delete(
    "/todas",
    status_code=status.HTTP_200_OK,
    summary="Eliminar todas las notificaciones del usuario",
)
async def eliminar_todas(
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    await db.execute(
        delete(Notificacion).where(Notificacion.user_id == current_user.id)
    )
    await db.commit()
    return {"message": "Todas las notificaciones eliminadas."}
