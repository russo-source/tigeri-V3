"""Contain storage factory backend logic."""
from typing import Optional, Protocol


class StorageSystem(Protocol):
    """Protocol defining the interface all storage integrations must satisfy."""
    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...
    def upload_file(self, filename: str, content: bytes, folder_id: Optional[str] = None) -> dict: ...
    def get_file(self, file_id: str) -> dict: ...
    def download_file(self, file_id: str) -> dict: ...
    def search_files(self, query: str, folder_id: Optional[str] = None) -> list[dict]: ...
    def create_folder(self, name: str, parent_id: Optional[str] = None) -> dict: ...
    def list_folders(self, parent_id: Optional[str] = None) -> list[dict]: ...
    def get_folder_by_name(self, name: str, parent_id: Optional[str] = None) -> Optional[dict]: ...
    def list_all(self, folder_id: Optional[str] = None) -> list[dict]: ...
    def move_file(self, file_id: str, target_folder_id: str) -> dict: ...
    def copy_file(self, file_id: str, target_folder_id: str) -> dict: ...
    def rename_file(self, file_id: str, new_name: str) -> dict: ...
    def delete_file(self, file_id: str) -> dict: ...
    def delete_folder(self, folder_id: str) -> dict: ...
    def rename_folder(self, folder_id: str, new_name: str) -> dict: ...
    def share_file(self, file_id: str) -> dict: ...
    def get_file_info(self, file_id: str) -> dict: ...


class _StorageUploadMixin:
    """
    Mixin that adds a uniform `upload(key, data, content_type) -> str` method
    """

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        parts = key.rsplit("/", 1)
        filename = parts[-1]
        folder_id = parts[0] if len(parts) == 2 else None

        result: dict = self.upload_file(  # type: ignore[attr-defined]
            filename=filename,
            content=data,
            folder_id=folder_id,
        )

        if result.get("error"):
            raise RuntimeError(f"Storage upload failed: {result['error']}")

        url = (
            result.get("webViewLink")
            or result.get("webUrl")
            or result.get("id")
            or ""
        )
        return str(url)


def get_storage_system(client_id: str, system: str):
    """Return storage system instance for the given provider string."""
    normalized = (system or "").lower().strip()

    if normalized in ("google_drive", "google"):
        from integrations.google_drive import GoogleDriveIntegration
        class _GDrive(_StorageUploadMixin, GoogleDriveIntegration):
            pass
        return _GDrive(client_id=client_id)

    elif normalized in ("sharepoint", "microsoft", "ms365", "outlook"):
        from integrations.sharepoint import SharePointIntegration

        class _SharePoint(_StorageUploadMixin, SharePointIntegration):
            pass
        return _SharePoint(client_id=client_id)

    elif normalized in ("onedrive", "one_drive"):
        from integrations.onedrive import OneDriveIntegration

        class _OneDrive(_StorageUploadMixin, OneDriveIntegration):
            pass

        return _OneDrive(client_id=client_id)

    else:
        raise ValueError(
            f"Unsupported storage system (resolved: '{system}'). "
            "Please connect Google Drive, OneDrive, or SharePoint in integrations."
        )


def get_storage_from_config(client_id: str):
    """Return storage integration resolved from client config."""
    from integrations.integration_resolver import resolve_storage_provider  # type: ignore
    system = resolve_storage_provider(client_id)
    return get_storage_system(client_id=client_id, system=system)