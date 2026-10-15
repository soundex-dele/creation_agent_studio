"""Supported integration API; callers retain permission and transaction contracts."""


_EXPORTS = {'application_for': 'app_center.my_drive.backend.access',
 'complete_upload': 'app_center.my_drive.backend.services',
 'create_upload': 'app_center.my_drive.backend.services',
 'entries': 'app_center.my_drive.backend.services',
 'folder_for': 'app_center.my_drive.backend.services',
 'object_path': 'app_center.my_drive.backend.storage',
 'space_for': 'app_center.my_drive.backend.access',
 'write_chunk': 'app_center.my_drive.backend.services'}

def __getattr__(name):
    from importlib import import_module
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(_EXPORTS[name]), name)
