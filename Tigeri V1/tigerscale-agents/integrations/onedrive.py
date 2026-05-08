"""Contain onedrive backend logic."""
import logging
import httpx

logger = logging.getLogger(__name__)
from typing import Optional
from integrations.resilience import with_retry, CircuitBreaker

_breaker = CircuitBreaker("onedrive")


class OneDriveIntegration:

    """Represent the OneDriveIntegration component and its related behavior."""
    BASE_URL = "https://graph.microsoft.com/v1.0/me/drive"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id

    @property
    def headers(self) -> dict:
        """Execute headers for OneDriveIntegration."""
        from integrations.token_manager import _get_valid_token as get_valid_token
        token = get_valid_token("outlook", client_id=self.client_id)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @with_retry
    @_breaker
    def upload_file(self, filename: str, content: bytes, folder_id: Optional[str] = None) -> dict:
        """Execute upload file for OneDriveIntegration."""
        folder = folder_id or "root"
        try:
            upload_headers = {
                "Authorization": self.headers["Authorization"],
                "Content-Type": "application/octet-stream",
            }
            response = httpx.put(
                f"{self.BASE_URL}/items/{folder}:/{filename}:/content",
                headers=upload_headers,
                content=content,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            if "webUrl" not in data:
                data["webUrl"] = data.get("webViewLink", "")
            return data
        except httpx.HTTPError as e:
            self._log(f"upload_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def get_file(self, file_id: str) -> dict:
        """Return file."""
        try:
            response = httpx.get(
                f"{self.BASE_URL}/items/{file_id}",
                headers=self.headers,
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
                f"{self.BASE_URL}/items/{file_id}",
                headers=self.headers,
                params={"select": "id,name,file"},
                timeout=10,
            )
            meta_resp.raise_for_status()
            meta = meta_resp.json()
            mime_type = meta.get("file", {}).get("mimeType", "application/octet-stream")

            dl_resp = httpx.get(
                f"{self.BASE_URL}/items/{file_id}/content",
                headers=self.headers,
                follow_redirects=True,
                timeout=30,
            )
            dl_resp.raise_for_status()
            return {
                "content": dl_resp.content,
                "mime_type": mime_type,
                "name": meta.get("name", "document"),
            }
        except httpx.HTTPError as e:
            self._log(f"download_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def search_files(self, query: str, folder_id: Optional[str] = None) -> list[dict]:
        """Search files — scoped to folder if folder_id provided."""
        try:
            if folder_id:
                response = httpx.get(
                    f"{self.BASE_URL}/items/{folder_id}/children",
                    headers=self.headers,
                    params={
                        "select": "id,name,file,folder,createdDateTime,lastModifiedDateTime,webUrl,size,parentReference",
                        "top": 100,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                items = response.json().get("value", [])
                q_lower = query.lower()
                return [i for i in items if q_lower in (i.get("name") or "").lower() and i.get("file") is not None]
            response = httpx.get(
                f"{self.BASE_URL}/root/search(q='{query}')",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("value", [])
        except httpx.HTTPError as e:
            self._log(f"search_files failed: {e}", "ERROR")
            return []

    @with_retry
    @_breaker
    def create_folder(self, name: str, parent_id: Optional[str] = None) -> dict:
        """Create folder — returns existing folder if one with the same name already exists."""
        existing = self._find_folder_by_name(name, parent_id)
        if existing:
            return existing

        parent_path = f"items/{parent_id}" if parent_id else "root"
        try:
            response = httpx.post(
                f"{self.BASE_URL}/{parent_path}/children",
                headers=self.headers,
                json={"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
                timeout=10,
            )
            if response.status_code == 409:
                existing = self._find_folder_by_name(name, parent_id)
                if existing:
                    return existing
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                existing = self._find_folder_by_name(name, parent_id)
                if existing:
                    return existing
                return {"error": f"Folder '{name}' conflict and could not be resolved."}
            self._log(f"create_folder failed: {e}", "ERROR")
            return {"error": str(e)}
        except httpx.HTTPError as e:
            self._log(f"create_folder failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def list_folders(self, parent_id: Optional[str] = None) -> list[dict]:
        """List only folders under a parent (default: root)."""
        items = self._list_children(parent_id)
        return [i for i in items if i.get("folder") is not None]

    @with_retry
    @_breaker
    def get_folder_by_name(self, name: str, parent_id: Optional[str] = None) -> Optional[dict]:
        """Find a folder by exact name under parent (default: root). Returns None if not found."""
        return self._find_folder_by_name(name, parent_id)

    @with_retry
    @_breaker
    def list_all(self, folder_id: Optional[str] = None) -> list[dict]:
        """List all items under a folder (default: drive root)."""
        parent = f"items/{folder_id}" if folder_id else "root"
        try:
            response = httpx.get(
                f"{self.BASE_URL}/{parent}/children",
                headers=self.headers,
                params={
                    "select": "id,name,file,folder,createdDateTime,lastModifiedDateTime,webUrl,size,parentReference",
                    "top": 100,
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("value", [])
        except httpx.HTTPError as e:
            self._log(f"list_all failed: {e}", "ERROR")
            return []


    def _list_children(self, parent_id: Optional[str] = None) -> list[dict]:
        """Fetch children of a folder without going through breaker/retry."""
        parent = f"items/{parent_id}" if parent_id else "root"
        try:
            response = httpx.get(
                f"{self.BASE_URL}/{parent}/children",
                headers=self.headers,
                params={
                    "select": "id,name,file,folder,webUrl,createdDateTime,lastModifiedDateTime,size,parentReference",
                    "top": 100,
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("value", [])
        except httpx.HTTPError as e:
            self._log(f"_list_children failed: {e}", "ERROR")
            return []
        
    @with_retry
    @_breaker
    def move_file(self, file_id: str, target_folder_id: str) -> dict:
        """Move file to target folder using PATCH."""
        try:
            response = httpx.patch(
                f"{self.BASE_URL}/items/{file_id}",
                headers=self.headers,
                json={"parentReference": {"id": target_folder_id}},
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
                f"{self.BASE_URL}/items/{file_id}/copy",
                headers=self.headers,
                json={"parentReference": {"id": target_folder_id}},
                timeout=10,
            )
            response.raise_for_status()
            # copy is async — 202 means accepted
            return {"copied": True, "status": response.status_code}
        except httpx.HTTPError as e:
            self._log(f"copy_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def rename_file(self, file_id: str, new_name: str) -> dict:
        """Rename file."""
        try:
            response = httpx.patch(
                f"{self.BASE_URL}/items/{file_id}",
                headers=self.headers,
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
                f"{self.BASE_URL}/items/{file_id}",
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
                f"{self.BASE_URL}/items/{folder_id}",
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
                f"{self.BASE_URL}/items/{folder_id}",
                headers=self.headers,
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
            response = httpx.post(
                f"{self.BASE_URL}/items/{file_id}/createLink",
                headers=self.headers,
                json={"type": "view", "scope": "anonymous"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return {"link": data.get("link", {}).get("webUrl", "")}
        except httpx.HTTPError as e:
            self._log(f"share_file failed: {e}", "ERROR")
            return {"error": str(e)}

    @with_retry
    @_breaker
    def get_file_info(self, file_id: str) -> dict:
        """Get file metadata."""
        try:
            response = httpx.get(
                f"{self.BASE_URL}/items/{file_id}",
                headers=self.headers,
                params={"select": "id,name,size,file,createdDateTime,lastModifiedDateTime,webUrl"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return {
                "name":     data.get("name"),
                "size":     data.get("size", 0),
                "mime":     data.get("file", {}).get("mimeType", ""),
                "created":  data.get("createdDateTime", ""),
                "modified": data.get("lastModifiedDateTime", ""),
                "link":     data.get("webUrl", ""),
            }
        except httpx.HTTPError as e:
            self._log(f"get_file_info failed: {e}", "ERROR")
            return {"error": str(e)}

    def _find_folder_by_name(self, name: str, parent_id: Optional[str] = None) -> Optional[dict]:
        """Find a folder by exact name without going through breaker/retry."""
        if not name:
            return None
        name_lower = name.lower()
        for item in self._list_children(parent_id):
            item_name = item.get("name")
            if item_name and item.get("folder") is not None and item_name.lower() == name_lower:
                return item
        return None

    def _log(self, message: str, level: str = "INFO") -> None:
        """Execute log for OneDriveIntegration."""
        getattr(logger, level.lower(), logger.info)("[%s] %s", self.client_id, message)