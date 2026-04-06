from fastapi import APIRouter
from files_server_fastapi.files import (
    list_router,
    folder_router,
    upload_router,
    open_url_router,
    download_router,
    view_router,
    delete_router,
    tree_router,
    acls_router,
)

router = APIRouter(prefix="/files", tags=["Archivos del Sistema"])

router.include_router(list_router.router)
router.include_router(folder_router.router)
router.include_router(upload_router.router)
router.include_router(open_url_router.router)
router.include_router(download_router.router)
router.include_router(view_router.router)
router.include_router(delete_router.router)
router.include_router(tree_router.router)
router.include_router(acls_router.router)
