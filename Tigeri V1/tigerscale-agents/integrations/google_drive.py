"""Contain google drive backend logic."""
import logging
import httpx

logger = logging.getLogger(__name__)
from typing import Optional
from integrations.resilience import with_retry, CircuitBreaker

_breaker = CircuitBreaker("google_drive")


class GoogleDriveIntegration:

    """Represent the GoogleDriveIntegration component and its related behavior."""
    BASE_URL = "https://www.googleapis.com/drive/v3"
    UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id

    @property
    def headers(self) -> dict:
        """Execute headers for GoogleDriveIntegration."""
        from integrations.token_manager import _get_valid_token as get_valid_token
        token = get_valid_token("google", client_id=self.client_id)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @with_retry
    @_breaker
    def upload_file(
        self,
        filename: str,
        content: bytes,
        mime_type: str = "application/octet-stream",
        folder_id: Optional[str] = None,
    ) -> dict:
        """Execute upload file for GoogleDriveIntegration."""
        metadata: dict = {"name": filename}
        if folder_id:
            metadata["parents"] = [folder_id]

        if mime_type == "application/octet-stream":
            import mimetypes
            guessed, _ = mimetypes.guess_type(filename)
            if guessed:
                mime_type = guessed

        try:
            import json as _json
            response = httpx.post(
                f"{self.UPLOAD_URL}/files?uploadType=multipart",
                headers={"Authorization": self.headers["Authorization"]},
                files={
                    "metadata": (None, _json.dumps(metadata), "application/json"),
                    "file": (filename, content, mime_type),
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            if result.get("id"):
                try:
                    share_resp = httpx.post(
                        f"{self.BASE_URL}/files/{result['id']}/permissions",
                        headers=self.headers,
                        json={"role": "reader", "type": "anyone"},
                        timeout=10,
                    )
                    if share_resp.status_code == 200:
                        meta_resp = httpx.get(
                            f"{self.BASE_URL}/files/{result['id']}",
                            headers=self.headers,
                            params={"fields": "id,name,webViewLink"},
                            timeout=10,
                        )
                        if meta_resp.status_code == 200:
                            result.update(meta_resp.json())
                except Exception:
                    pass
            return result
        except httpx.HTTPError as e:
            self._log(f"upload_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def get_file(self, file_id: str) -> dict:
        """Return file metadata."""
        try:
            response = httpx.get(
                f"{self.BASE_URL}/files/{file_id}",
                headers=self.headers,
                params={"fields": "id,name,mimeType,createdTime,webViewLink"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self._log(f"get_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def download_file(self, file_id: str) -> dict:
        """Download file content and metadata."""
        try:
            meta_resp = httpx.get(
                f"{self.BASE_URL}/files/{file_id}",
                headers=self.headers,
                params={"fields": "id,name,mimeType"},
                timeout=10,
            )
            meta_resp.raise_for_status()
            meta = meta_resp.json()

            content_resp = httpx.get(
                f"{self.BASE_URL}/files/{file_id}?alt=media",
                headers=self.headers,
                timeout=30,
            )
            content_resp.raise_for_status()
            return {
                "content": content_resp.content,
                "mime_type": meta.get("mimeType", "application/octet-stream"),
                "name": meta.get("name", "document"),
            }
        except httpx.HTTPError as e:
            self._log(f"download_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def search_files(self, query: str, folder_id: Optional[str] = None) -> list[dict]:
        """Search files by name — scoped to folder if folder_id provided."""
        q = f"name contains '{query}' and trashed=false and mimeType!='application/vnd.google-apps.folder'"
        if folder_id:
            q += f" and '{folder_id}' in parents"
        try:
            response = httpx.get(
                f"{self.BASE_URL}/files",
                headers=self.headers,
                params={
                    "q": q,
                    "fields": "files(id,name,mimeType,createdTime,webViewLink,parents)",
                    "pageSize": 20,
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("files", [])
        except httpx.HTTPError as e:
            self._log(f"search_files failed: {e}", "ERROR")
            return []

    @with_retry
    @_breaker
    def create_folder(self, name: str, parent_id: Optional[str] = None) -> dict:
        """Create folder — returns existing folder if one already exists with that name."""
        existing = self.get_folder_by_name(name, parent_id)
        if existing and not existing.get("error"):
            return existing

        metadata: dict = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]
        try:
            response = httpx.post(
                f"{self.BASE_URL}/files",
                headers=self.headers,
                json=metadata,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self._log(f"create_folder failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def list_folders(self, parent_id: Optional[str] = None) -> list[dict]:
        """List only folders under a parent (default: root)."""
        q = "mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            q += f" and '{parent_id}' in parents"
        try:
            response = httpx.get(
                f"{self.BASE_URL}/files",
                headers=self.headers,
                params={
                    "q": q,
                    "fields": "files(id,name,mimeType,webViewLink)",
                    "pageSize": 100,
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("files", [])
        except httpx.HTTPError as e:
            self._log(f"list_folders failed: {e}", "ERROR")
            return []

    @with_retry
    @_breaker
    def get_folder_by_name(self, name: str, parent_id: Optional[str] = None) -> Optional[dict]:
        """Find a folder by exact name under parent. Returns None if not found."""
        name_escaped = name.replace("'", "\\'")
        q = f"name='{name_escaped}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            q += f" and '{parent_id}' in parents"
        try:
            response = httpx.get(
                f"{self.BASE_URL}/files",
                headers=self.headers,
                params={
                    "q": q,
                    "fields": "files(id,name,mimeType,webViewLink)",
                    "pageSize": 1,
                },
                timeout=10,
            )
            response.raise_for_status()
            files = response.json().get("files", [])
            return files[0] if files else None
        except httpx.HTTPError as e:
            self._log(f"get_folder_by_name failed: {e}", "ERROR")
            return None

    @with_retry
    @_breaker
    def list_all(self, folder_id: Optional[str] = None) -> list[dict]:
        """List all items under a folder (default: drive root)."""
        q = "trashed=false"
        if folder_id:
            q += f" and '{folder_id}' in parents"
        try:
            response = httpx.get(
                f"{self.BASE_URL}/files",
                headers=self.headers,
                params={
                    "q": q,
                    "fields": "files(id,name,mimeType,createdTime,modifiedTime,webViewLink,size,parents)",
                    "pageSize": 100,
                    "orderBy": "modifiedTime desc",
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("files", [])
        except httpx.HTTPError as e:
            self._log(f"list_all failed: {e}", "ERROR")
            return []
        
    @with_retry
    @_breaker
    def move_file(self, file_id: str, target_folder_id: str) -> dict:
        """Move file by updating parents."""
        try:
            # Get current parents first
            meta = httpx.get(
                f"{self.BASE_URL}/files/{file_id}",
                headers=self.headers,
                params={"fields": "parents"},
                timeout=10,
            )
            meta.raise_for_status()
            current_parents = ",".join(meta.json().get("parents", []))
            response = httpx.patch(
                f"{self.BASE_URL}/files/{file_id}",
                headers=self.headers,
                params={
                    "addParents":    target_folder_id,
                    "removeParents": current_parents,
                    "fields":        "id,name,parents,webViewLink",
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self._log(f"move_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def copy_file(self, file_id: str, target_folder_id: str) -> dict:
        """Copy file to target folder."""
        try:
            response = httpx.post(
                f"{self.BASE_URL}/files/{file_id}/copy",
                headers=self.headers,
                json={"parents": [target_folder_id]},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self._log(f"copy_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def rename_file(self, file_id: str, new_name: str) -> dict:
        """Rename file."""
        try:
            response = httpx.patch(
                f"{self.BASE_URL}/files/{file_id}",
                headers=self.headers,
                params={"fields": "id,name"},
                json={"name": new_name},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self._log(f"rename_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def delete_file(self, file_id: str) -> dict:
        """Delete file permanently."""
        try:
            response = httpx.delete(
                f"{self.BASE_URL}/files/{file_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return {"deleted": True}
        except httpx.HTTPError as e:
            self._log(f"delete_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def delete_folder(self, folder_id: str) -> dict:
        """Delete folder and all contents recursively."""
        try:
            response = httpx.delete(
                f"{self.BASE_URL}/files/{folder_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return {"deleted": True}
        except httpx.HTTPError as e:
            self._log(f"delete_folder failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def rename_folder(self, folder_id: str, new_name: str) -> dict:
        """Rename folder."""
        try:
            response = httpx.patch(
                f"{self.BASE_URL}/files/{folder_id}",
                headers=self.headers,
                params={"fields": "id,name"},
                json={"name": new_name},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self._log(f"rename_folder failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def share_file(self, file_id: str) -> dict:
        """Generate shareable link."""
        try:
            httpx.post(
                f"{self.BASE_URL}/files/{file_id}/permissions",
                headers=self.headers,
                json={"role": "reader", "type": "anyone"},
                timeout=10,
            )
            meta = httpx.get(
                f"{self.BASE_URL}/files/{file_id}",
                headers=self.headers,
                params={"fields": "webViewLink"},
                timeout=10,
            )
            meta.raise_for_status()
            return {"link": meta.json().get("webViewLink", "")}
        except httpx.HTTPError as e:
            self._log(f"share_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def get_file_info(self, file_id: str) -> dict:
        """Get file metadata."""
        try:
            response = httpx.get(
                f"{self.BASE_URL}/files/{file_id}",
                headers=self.headers,
                params={"fields": "id,name,size,mimeType,createdTime,modifiedTime,webViewLink"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return {
                "name":     data.get("name"),
                "size":     data.get("size", 0),
                "mime":     data.get("mimeType", ""),
                "created":  data.get("createdTime", ""),
                "modified": data.get("modifiedTime", ""),
                "link":     data.get("webViewLink", ""),
            }
        except httpx.HTTPError as e:
            self._log(f"get_file_info failed: {e}", "ERROR")
            return {"error": str(e)}

    def _log(self, message: str, level: str = "INFO") -> None:
        """Execute log for GoogleDriveIntegration."""
        getattr(logger, level.lower(), logger.info)("[%s] %s", self.client_id, message)