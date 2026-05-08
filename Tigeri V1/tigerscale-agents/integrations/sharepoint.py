"""Contain sharepoint backend logic."""
import logging
import httpx

logger = logging.getLogger(__name__)
from typing import Optional
from config.settings import settings
from integrations.resilience import with_retry, CircuitBreaker


class SharePointIntegration:
    """Represent the SharePointIntegration component and its related behavior."""
    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id
        self._breaker = CircuitBreaker(f"sharepoint:{client_id}")

    @property
    def _site_id(self) -> str:
        from webhooks.integrations import get_provider_meta
        meta = get_provider_meta(self.client_id, "outlook")
        return meta.get("sharepoint_site_id", "")

    @property
    def headers(self) -> dict:
        """Execute headers for SharePointIntegration."""
        from integrations.token_manager import _get_valid_token
        token = _get_valid_token("outlook", client_id=self.client_id)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _validate_site_id(self) -> Optional[str]:
        """Returns error string if site_id is missing, else None."""
        if not self._site_id:
            return "SharePoint site is not configured — please reconnect SharePoint in integrations."
        return None

    def upload_file(self, filename: str, content: bytes, folder_id: Optional[str] = None) -> dict:
        """Execute upload file for SharePointIntegration."""
        return self._breaker.call(self._upload_file, filename, content, folder_id)

    @with_retry
    def _upload_file(self, filename: str, content: bytes, folder_id: Optional[str] = None) -> dict:
        """Execute upload file for SharePointIntegration."""
        err = self._validate_site_id()
        if err:
            return {"error": err}
        folder_path = folder_id or "General"
        try:
            from integrations.token_manager import _get_valid_token
            token = _get_valid_token("outlook", client_id=self.client_id)
            response = httpx.put(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/root:/{folder_path}/{filename}:/content",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
                content=content,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "SharePoint auth expired — please reconnect in integrations."}
            if e.response.status_code == 404:
                return {"error": f"SharePoint folder '{folder_path}' not found."}
            self._log(f"upload_file failed: {e.response.status_code} — {e.response.text}", "ERROR")
            return {"error": f"SharePoint upload failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            self._log(f"upload_file failed: {e}", "ERROR")
            return {"error": f"SharePoint unreachable: {e}"}

    def get_file(self, file_id: str) -> dict:
        """Return file."""
        return self._breaker.call(self._get_file, file_id)

    @with_retry
    def _get_file(self, file_id: str) -> dict:
        """Return file."""
        err = self._validate_site_id()
        if err:
            return {"error": err}
        try:
            response = httpx.get(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/root:/{file_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "SharePoint auth expired — please reconnect in integrations."}
            if e.response.status_code == 404:
                return {"error": f"File '{file_id}' not found in SharePoint."}
            self._log(f"get_file failed: {e.response.status_code}", "ERROR")
            return {"error": f"SharePoint error: {e.response.status_code}"}
        except httpx.HTTPError as e:
            self._log(f"get_file failed: {e}", "ERROR")
            return {"error": f"SharePoint unreachable: {e}"}

    def search_files(self, query: str, folder_id: Optional[str] = None) -> list[dict]:
        """Execute search files for SharePointIntegration."""
        return self._breaker.call(self._search_files, query, folder_id)

    @with_retry
    def _search_files(self, query: str, folder_id: Optional[str] = None) -> list[dict]:
        """Execute search files for SharePointIntegration."""
        err = self._validate_site_id()
        if err:
            self._log(err, "ERROR")
            return []
        try:
            if folder_id:
                response = httpx.get(
                    f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{folder_id}/children",
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
                f"{self.BASE_URL}/sites/{self._site_id}/drive/root/search(q='{query}')",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("value", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self._log("search_files auth expired", "ERROR")
                return []
            self._log(f"search_files failed: {e.response.status_code}", "ERROR")
            return []
        except httpx.HTTPError as e:
            self._log(f"search_files failed: {e}", "ERROR")
            return []

    def create_folder(self, name: str, parent_id: Optional[str] = None) -> dict:
        """Create folder."""
        return self._breaker.call(self._create_folder, name, parent_id)

    @with_retry
    def _create_folder(self, name: str, parent_id: Optional[str] = None) -> dict:
        """Create folder."""
        err = self._validate_site_id()
        if err:
            return {"error": err}

        existing = self._get_folder_by_name(name, parent_id)
        if existing and not isinstance(existing, dict):
            pass
        elif existing:
            return existing

        parent_path = f"items/{parent_id}" if parent_id else "root"
        try:
            response = httpx.post(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/{parent_path}/children",
                headers=self.headers,
                json={"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
                timeout=10,
            )
            if response.status_code == 409:
                existing = self._get_folder_by_name(name, parent_id)
                if existing:
                    return existing
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "SharePoint auth expired — please reconnect in integrations."}
            if e.response.status_code == 404:
                return {"error": f"SharePoint parent folder not found."}
            if e.response.status_code == 409:
                existing = self._get_folder_by_name(name, parent_id)
                if existing:
                    return existing
                return {"error": f"Folder '{name}' conflict and could not be resolved."}
            self._log(f"create_folder failed: {e.response.status_code} — {e.response.text}", "ERROR")
            return {"error": f"SharePoint folder creation failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            self._log(f"create_folder failed: {e}", "ERROR")
            return {"error": f"SharePoint unreachable: {e}"}

    def download_file(self, file_id: str) -> dict:
        """Return file content by ID."""
        return self._breaker.call(self._download_file, file_id)

    @with_retry
    def _download_file(self, file_id: str) -> dict:
        """Return file content by ID."""
        err = self._validate_site_id()
        if err:
            return {"error": err}
        try:
            meta_resp = httpx.get(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{file_id}",
                headers=self.headers,
                timeout=10,
            )
            meta_resp.raise_for_status()
            meta = meta_resp.json()

            dl_resp = httpx.get(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{file_id}/content",
                headers=self.headers,
                follow_redirects=True,
                timeout=30,
            )
            dl_resp.raise_for_status()
            return {
                "content": dl_resp.content,
                "mime_type": meta.get("file", {}).get("mimeType", "application/octet-stream"),
                "name": meta.get("name", "document"),
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "SharePoint auth expired — please reconnect in integrations."}
            if e.response.status_code == 404:
                return {"error": f"File '{file_id}' not found in SharePoint."}
            self._log(f"download_file failed: {e.response.status_code}", "ERROR")
            return {"error": f"SharePoint error: {e.response.status_code}"}
        except httpx.HTTPError as e:
            self._log(f"download_file failed: {e}", "ERROR")
            return {"error": f"SharePoint unreachable: {e}"}

    def list_all(self, folder_id: Optional[str] = None) -> list[dict]:
        """List all items under a folder (default: drive root)."""
        return self._breaker.call(self._list_all, folder_id)

    @with_retry
    def _list_all(self, folder_id: Optional[str] = None) -> list[dict]:
        """List all items under a folder (default: drive root)."""
        err = self._validate_site_id()
        if err:
            self._log(err, "ERROR")
            return []
        parent = f"items/{folder_id}" if folder_id else "root"
        try:
            response = httpx.get(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/{parent}/children",
                headers=self.headers,
                params={
                    "select": "id,name,file,folder,createdDateTime,lastModifiedDateTime,webUrl,size,parentReference",
                    "top": 100,
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("value", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self._log("list_all auth expired", "ERROR")
                return []
            if e.response.status_code == 404:
                self._log("list_all site or folder not found", "ERROR")
                return []
            self._log(f"list_all failed: {e.response.status_code}", "ERROR")
            return []
        except httpx.HTTPError as e:
            self._log(f"list_all failed: {e}", "ERROR")
            return []

    def list_folders(self, parent_id: Optional[str] = None) -> list[dict]:
        """List only folders under a parent (default: root)."""
        return self._breaker.call(self._list_folders, parent_id)

    @with_retry
    def _list_folders(self, parent_id: Optional[str] = None) -> list[dict]:
        """List only folders under a parent (default: root)."""
        err = self._validate_site_id()
        if err:
            self._log(err, "ERROR")
            return []
        parent = f"items/{parent_id}" if parent_id else "root"
        try:
            response = httpx.get(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/{parent}/children",
                headers=self.headers,
                params={
                    "select": "id,name,file,folder,createdDateTime,lastModifiedDateTime,webUrl,parentReference",
                    "top": 100,
                },
                timeout=10,
            )
            response.raise_for_status()
            items = response.json().get("value", [])
            return [i for i in items if i.get("folder") is not None]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self._log("list_folders auth expired", "ERROR")
                return []
            if e.response.status_code == 404:
                self._log("list_folders site or folder not found", "ERROR")
                return []
            self._log(f"list_folders failed: {e.response.status_code}", "ERROR")
            return []
        except httpx.HTTPError as e:
            self._log(f"list_folders failed: {e}", "ERROR")
            return []

    def get_folder_by_name(self, name: str, parent_id: Optional[str] = None) -> Optional[dict]:
        """Find a folder by exact name under parent. Returns None if not found."""
        return self._breaker.call(self._get_folder_by_name, name, parent_id)

    @with_retry
    def _get_folder_by_name(self, name: str, parent_id: Optional[str] = None) -> Optional[dict]:
        """Find a folder by exact name under parent. Returns None if not found."""
        err = self._validate_site_id()
        if err:
            self._log(err, "ERROR")
            return None
        parent = f"items/{parent_id}" if parent_id else "root"
        try:
            response = httpx.get(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/{parent}/children",
                headers=self.headers,
                params={
                    "select": "id,name,folder,webUrl,parentReference",
                    "top": 100,
                },
                timeout=10,
            )
            response.raise_for_status()
            items = response.json().get("value", [])
            name_lower = name.lower()
            for item in items:
                if item.get("folder") is not None and (item.get("name") or "").lower() == name_lower:
                    return item
            return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self._log("get_folder_by_name auth expired", "ERROR")
                return None
            if e.response.status_code == 404:
                return None
            self._log(f"get_folder_by_name failed: {e.response.status_code}", "ERROR")
            return None
        except httpx.HTTPError as e:
            self._log(f"get_folder_by_name failed: {e}", "ERROR")
            return None
        
    def move_file(self, file_id: str, target_folder_id: str) -> dict:
        return self._breaker.call(self._move_file, file_id, target_folder_id)
    @with_retry
    def _move_file(self, file_id: str, target_folder_id: str) -> dict:
        err = self._validate_site_id()
        if err: return {"error": err}
        try:
            response = httpx.patch(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{file_id}",
                headers=self.headers,
                json={"parentReference": {"id": target_folder_id}},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self._log(f"move_file failed: {e}", "ERROR")
            return {"error": str(e)}

    def copy_file(self, file_id: str, target_folder_id: str) -> dict:
        return self._breaker.call(self._copy_file, file_id, target_folder_id)

    @with_retry
    def _copy_file(self, file_id: str, target_folder_id: str) -> dict:
        err = self._validate_site_id()
        if err: return {"error": err}
        try:
            response = httpx.post(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{file_id}/copy",
                headers=self.headers,
                json={"parentReference": {"id": target_folder_id}},
                timeout=10,
            )
            response.raise_for_status()
            return {"copied": True, "status": response.status_code}
        except httpx.HTTPError as e:
            self._log(f"copy_file failed: {e}", "ERROR")
            return {"error": str(e)}

    def rename_file(self, file_id: str, new_name: str) -> dict:
        return self._breaker.call(self._rename_file, file_id, new_name)

    @with_retry
    def _rename_file(self, file_id: str, new_name: str) -> dict:
        err = self._validate_site_id()
        if err: return {"error": err}
        try:
            response = httpx.patch(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{file_id}",
                headers=self.headers,
                json={"name": new_name},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self._log(f"rename_file failed: {e}", "ERROR")
            return {"error": str(e)}

    def delete_file(self, file_id: str) -> dict:
        return self._breaker.call(self._delete_file, file_id)

    @with_retry
    def _delete_file(self, file_id: str) -> dict:
        err = self._validate_site_id()
        if err: return {"error": err}
        try:
            response = httpx.delete(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{file_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return {"deleted": True}
        except httpx.HTTPError as e:
            self._log(f"delete_file failed: {e}", "ERROR")
            return {"error": str(e)}

    def delete_folder(self, folder_id: str) -> dict:
        return self._breaker.call(self._delete_folder, folder_id)

    @with_retry
    def _delete_folder(self, folder_id: str) -> dict:
        err = self._validate_site_id()
        if err: return {"error": err}
        try:
            response = httpx.delete(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{folder_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return {"deleted": True}
        except httpx.HTTPError as e:
            self._log(f"delete_folder failed: {e}", "ERROR")
            return {"error": str(e)}

    def rename_folder(self, folder_id: str, new_name: str) -> dict:
        return self._breaker.call(self._rename_folder, folder_id, new_name)

    @with_retry
    def _rename_folder(self, folder_id: str, new_name: str) -> dict:
        err = self._validate_site_id()
        if err: return {"error": err}
        try:
            response = httpx.patch(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{folder_id}",
                headers=self.headers,
                json={"name": new_name},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self._log(f"rename_folder failed: {e}", "ERROR")
            return {"error": str(e)}

    def share_file(self, file_id: str) -> dict:
        return self._breaker.call(self._share_file, file_id)

    @with_retry
    def _share_file(self, file_id: str) -> dict:
        err = self._validate_site_id()
        if err: return {"error": err}
        try:
            response = httpx.post(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{file_id}/createLink",
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

    def get_file_info(self, file_id: str) -> dict:
        return self._breaker.call(self._get_file_info, file_id)

    @with_retry
    def _get_file_info(self, file_id: str) -> dict:
        err = self._validate_site_id()
        if err: return {"error": err}
        try:
            response = httpx.get(
                f"{self.BASE_URL}/sites/{self._site_id}/drive/items/{file_id}",
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

    def _log(self, message: str, level: str = "INFO") -> None:
        """Execute log for SharePointIntegration."""
        getattr(logger, level.lower(), logger.info)("[%s] %s", self.client_id, message)