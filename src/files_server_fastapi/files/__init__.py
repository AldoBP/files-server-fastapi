"""
Paquete de sub-módulos para el router de archivos.

  constants.py          — BASE_DIR, ONLYOFFICE_*, INLINE_MIME_TYPES
  dependencies.py       — check_folder_access, can_view/edit/upload/delete
  list_router.py        — GET  /files/list
  folder_router.py      — POST /files/folder
  upload_router.py      — POST /files/upload
  open_url_router.py    — GET  /files/open-url
  download_router.py    — GET  /files/download
  tree_router.py        — GET  /files/tree
  onlyoffice_router.py  — GET  /files/onlyoffice/open
                          POST /files/onlyoffice/callback
  search_router.py      — GET  /files/search         (archivos y carpetas)
                          GET  /files/search/users    (usuarios, solo admins)
"""
