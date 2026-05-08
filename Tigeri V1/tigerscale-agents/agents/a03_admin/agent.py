"""Contain agent backend logic."""
from __future__ import annotations
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional
from agents.a03_admin.config import ADMIN_CONFIG
from agents.a03_admin.prompts import get_admin_tools_prompt
from agents.a03_admin.tools import (
    format_admin_confirmation_llm,
    get_effective_timezone,
    get_storage_integration,
    parse_admin_request,
    validate_admin_request,
)
from agents.base_agent import BaseAgent
from agents.base_tools import ADMIN_TOOLS
from config.db_pool import get_conn
from core.context_builder import build_context, format_for_llm
from integrations.resilience import CircuitBreaker, CircuitOpenError
from memory.agent_memory import recall_memory, save_memory
from memory.rag import retrieve_knowledge
from security.audit import log_action

logger = logging.getLogger(__name__)

_GENERIC_WORDS = frozenset({
    "document", "file", "attachment", "none",
    "the", "a", "an", "it", "this",
})

_FILE_REQUIRED_ACTIONS = frozenset({
    "file_document", "upload_document", "read_document",
})
_FILE_OPTIONAL_ACTIONS = frozenset({
    "move_document", "copy_document",
})

_CLEAR_CACHE_AFTER_ACTIONS = frozenset({
    "upload_document", "file_document", "rename_document",
    "delete_document", "move_document",
})

_UNSUPPORTED_ACTIONS = frozenset({
    "restore_document", "restore_file", "restore",
    "empty_trash", "clear_trash",
})
_UNSUPPORTED_KEYWORDS = (
    "restore it", "restore the file", "restore the document",
    "clear my trash", "clear trash", "empty trash", "empty my trash",
    "recover deleted", "undelete",
)

_UPLOAD_KEYWORDS = (
    "save", "upload", "store", "put in drive", "file this",
    "add to", "add this", "folder name",
)

_DAY_NAME_TO_WEEKDAY = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _normalise_file_item(item: dict) -> dict:
    """
    Map a raw storage API item (Google Drive, SharePoint, or OneDrive)
    to a consistent shape used everywhere in this agent.
    """
    is_folder = (
        item.get("folder") is not None                          
        or "folder" in (item.get("mimeType") or "")
        or item.get("mimeType") == "application/vnd.google-apps.folder"
    )

    if is_folder:
        mime = "folder"
    else:
        mime = (
            item.get("mimeType")
            or (item.get("file") or {}).get("mimeType")
            or "application/octet-stream"
        )
    link = item.get("webViewLink") or item.get("webUrl") or ""
    created = item.get("createdTime")  or item.get("createdDateTime")  or ""
    modified = item.get("modifiedTime") or item.get("lastModifiedDateTime") or ""
    return {
        "id":          item.get("id", ""),
        "name":        item.get("name", ""),
        "link":        link,
        "mime_type":   mime,
        "is_folder":   is_folder,
        "created_at":  created,
        "modified_at": modified,
        "size":        item.get("size", 0),
    }


class AdminAgent(BaseAgent):

    """Represent the AdminAgent component and its related behavior."""
    def __init__(self, client_id: str):
        super().__init__(client_id)
        self.confidence_threshold = ADMIN_CONFIG["confidence_threshold"]
        self._calendar_cb = CircuitBreaker(f"calendar:{client_id}")
        self._email_cb = CircuitBreaker(f"email:{client_id}")

    def get_system_prompt(self) -> str:
        return get_admin_tools_prompt()

    def get_tools(self) -> list[dict]:
        return ADMIN_TOOLS

    def execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        meta = {
            "_sender":    tool_input.pop("_sender", ""),
            "_channel":   tool_input.pop("_channel", "telegram"),
            "_client_id": tool_input.pop("_client_id", self.client_id),
            "_task_id":   tool_input.pop("_task_id", ""),
        }

        dispatch = {
            "file_document":      self._tool_file_document,
            "find_document":      self._tool_find_document,
            "read_document":      self._tool_read_document,
            "list_documents":     self._tool_list_documents,
            "upload_document":    self._tool_upload_document,
            "move_document":      self._tool_move_document,
            "delete_document":    self._tool_delete_document,
            "share_document":     self._tool_share_document,
            "schedule_meeting":   self._tool_schedule_meeting,
            "list_meetings":      self._tool_list_meetings,
            "track_permit":       self._tool_track_permit,
            "send_communication": self._tool_send_communication,
        }

        handler = dispatch.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(tool_input, meta)
        except Exception as exc:
            logger.error("execute_tool %s failed client=%s: %s", tool_name, self.client_id, exc)
            return {"error": str(exc)}

    def _tool_file_document(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":        "file_document",
            "entity_name":   inp.get("entity_name"),
            "document_type": inp.get("document_type", "general"),
            "folder_name":   inp.get("folder_name"),
            "_sender":       meta.get("_sender", ""),
        }
        result = self._action_file_document(data)
        result["action"] = "file_document"
        return result

    def _tool_find_document(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":        "find_document",
            "entity_name":   inp.get("entity_name"),
            "document_type": inp.get("document_type"),
            "folder_name":   inp.get("folder_name"),
            "_sender":       meta.get("_sender", ""),
        }
        result = self._action_find_document(data)
        result["action"] = "find_document"
        return result

    def _tool_read_document(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":      "read_document",
            "entity_name": inp.get("entity_name"),
            "folder_name": inp.get("folder_name"),
            "content":     inp.get("content"),
            "_sender":     meta.get("_sender", ""),
        }
        result = self._action_read_document(data)
        result["action"] = "read_document"
        return result

    def _tool_list_documents(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":        "list_documents",
            "folder_name":   inp.get("folder_name"),
            "document_type": inp.get("document_type"),
            "entity_name":   inp.get("entity_name"),
            "_sender":       meta.get("_sender", ""),
        }
        result = self._action_list_documents(data)
        result["action"] = "list_documents"
        return result

    def _tool_upload_document(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":        "upload_document",
            "folder_name":   inp.get("folder_name"),
            "entity_name":   inp.get("entity_name"),
            "document_type": inp.get("document_type"),
            "_sender":       meta.get("_sender", ""),
        }
        sender = meta.get("_sender", "")
        if sender:
            try:
                from core.conversation import get_file_bytes_context
                cached_bytes, cached_mime, cached_filename = get_file_bytes_context(sender, self.client_id)
                if cached_bytes:
                    data["attachment"] = {
                        "bytes":     cached_bytes,
                        "mime_type": cached_mime or "application/octet-stream",
                        "filename":  cached_filename or "document",
                    }
            except Exception as e:
                logger.warning("Tool upload cache inject failed client=%s: %s", self.client_id, e)
        result = self._action_upload_document(data)
        result["action"] = "upload_document"
        return result

    def _tool_move_document(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":        "move_document",
            "entity_name":   inp.get("entity_name"),
            "folder_name":   inp.get("folder_name"),
            "target_folder": inp.get("target_folder"),
            "_sender":       meta.get("_sender", ""),
        }
        result = self._action_move_document(data)
        result["action"] = "move_document"
        return result

    def _tool_delete_document(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":      "delete_document",
            "entity_name": inp.get("entity_name"),
            "folder_name": inp.get("folder_name"),
            "_sender":     meta.get("_sender", ""),
        }
        result = self._action_delete_document(data)
        result["action"] = "delete_document"
        return result

    def _tool_share_document(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":      "share_document",
            "entity_name": inp.get("entity_name"),
            "folder_name": inp.get("folder_name"),
            "_sender":     meta.get("_sender", ""),
        }
        result = self._action_share_document(data)
        result["action"] = "share_document"
        return result

    def _tool_schedule_meeting(self, inp: dict, meta: dict) -> dict:
        timezone = inp.get("timezone") or get_effective_timezone(self.client_id, "")
        data = {
            "action":           "schedule_meeting",
            "entity_name":      inp.get("entity_name"),
            "meeting_date":     inp.get("meeting_date"),
            "meeting_time":     inp.get("meeting_time"),
            "meeting_duration": inp.get("meeting_duration", 60),
            "attendees":        inp.get("attendees", []),
            "timezone":         timezone,
            "content":          inp.get("content", ""),
            "_sender":          meta.get("_sender", ""),
        }
        result = self._action_schedule_meeting(data)
        result["action"] = "schedule_meeting"
        if result.get("scheduled") and not result.get("error"):
            self._save_meeting(data, result)
        return result

    def _tool_list_meetings(self, inp: dict, meta: dict) -> dict:
        result = self._action_list_meetings({})
        result["action"] = "list_meetings"
        return result

    def _tool_track_permit(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":        "track_permit",
            "entity_name":   inp.get("entity_name"),
            "document_type": inp.get("document_type"),
            "expiry_date":   inp.get("expiry_date"),
            "_sender":       meta.get("_sender", ""),
        }
        result = self._action_track_permit(data)
        result["action"] = "track_permit"
        if result.get("tracking"):
            self._save_to_db(data, result)
        return result

    def _tool_send_communication(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":          "send_communication",
            "recipient_email": inp.get("recipient_email"),
            "entity_name":     inp.get("entity_name"),
            "content":         inp.get("content", ""),
            "_sender":         meta.get("_sender", ""),
        }
        result = self._action_send_communication(data)
        result["action"] = "send_communication"
        return result

    def _run(self, task: dict) -> dict:
        message = task.get("message", "")
        file_bytes = task.get("file_bytes", b"")
        mime_type = task.get("mime_type", "")
        filename = task.get("filename", "")
        sender = task.get("sender", "")
        attachment = None
        if file_bytes:
            attachment = {
                "bytes": file_bytes,
                "mime_type": mime_type or "application/octet-stream",
                "filename": filename or "document",
            }
            if sender:
                try:
                    from core.conversation import save_file_bytes_context, clear_pending_intent
                    save_file_bytes_context(
                        sender=sender,
                        client_id=self.client_id,
                        file_bytes=file_bytes,
                        mime_type=mime_type or "application/octet-stream",
                        filename=filename or "document",
                    )
                    clear_pending_intent(sender, self.client_id)
                except Exception as e:
                    logger.warning("file context save failed client=%s: %s",self.client_id, e)

        lower_msg = message.lower().strip()
        if any(kw in lower_msg for kw in _UNSUPPORTED_KEYWORDS):
            return {
                "status":  "not_supported",
                "message": (
                    "Restoring deleted files and emptying trash aren't supported yet. "
                    "You can recover files directly in Google Drive's Trash folder."
                ),
            }

        try:
            data = parse_admin_request(message)
        except Exception as e:
            logger.error("parse_admin_request failed client=%s: %s", self.client_id, e)
            result = {"status": "error", "message": "Something went wrong reading your request — please try again."}
            log_action(self.client_id, "a03_admin", "admin", message, result, "error",
                    message="parse_admin_request raised")
            return result

        if not data:
            result = {"status": "error", "message": "Could not understand your request — please try rephrasing."}
            log_action(self.client_id, "a03_admin", "admin", message, result, "error",
                    message="parse_admin_request returned empty")
            return result

        if data.get("action") in _UNSUPPORTED_ACTIONS:
            return {
                "status":  "not_supported",
                "message": (
                    "Restoring deleted files and emptying trash aren't supported yet. "
                    "You can recover files directly in Google Drive's Trash folder."
                ),
            }

        if not attachment and sender:
            action_hint = data.get("action", "")
            if action_hint in _FILE_REQUIRED_ACTIONS | _FILE_OPTIONAL_ACTIONS:
                try:
                    from core.conversation import get_file_bytes_context
                    cached_bytes, cached_mime, cached_filename = get_file_bytes_context(
                        sender, self.client_id
                    )
                    if cached_bytes:
                        entity = (data.get("entity_name") or "").lower()
                        cached_lower = cached_filename.lower()
                        entity_tokens = [t for t in entity.split() if len(t) > 3]
                        filename_match = (
                            not entity_tokens
                            or any(t in cached_lower for t in entity_tokens)
                        )
                        if filename_match:
                            attachment = {
                                "bytes":     cached_bytes,
                                "mime_type": cached_mime or "application/octet-stream",
                                "filename":  cached_filename or "document",
                            }
                except Exception as e:
                    logger.warning("cache injection failed client=%s: %s", self.client_id, e)

        if attachment:
            data["attachment"] = attachment
            if not data.get("action") or data.get("action") not in ADMIN_CONFIG["valid_actions"]:
                if any(k in lower_msg for k in _UPLOAD_KEYWORDS):
                    data["action"] = "upload_document"
                else:
                    data["action"] = "read_document"
                data["confidence"] = 0.95

        is_valid, reason = validate_admin_request(data)
        if not is_valid:
            logger.error("Admin validation failed client=%s: %s", self.client_id, reason)
            result = {"status": "error", "message": reason}
            log_action(self.client_id, "a03_admin", "admin", message, result, "error",
                    message=f"Validation failed — {reason}")
            return result

        if data.get("action") == "schedule_meeting":
            data["timezone"] = data.get("timezone") or get_effective_timezone(self.client_id, message)

        entity = data.get("entity_name", "")

        if data.get("action") in ADMIN_CONFIG["valid_actions"] and float(data.get("confidence", 0)) >= self.confidence_threshold:
            pass
        else:
            memory    = recall_memory(self.client_id, "a03_admin", message)
            knowledge = retrieve_knowledge(self.client_id, message, "admin")

            try:
                from core.conversation import _build_enriched_message, _get_context
                ctx_turns = _get_context(sender, self.client_id)
                enriched_task = _build_enriched_message(
                    message, ctx_turns,
                    sender=sender,
                    client_id=self.client_id,
                    domain="admin",
                )
            except Exception:
                enriched_task = message

            context = build_context(
                task=enriched_task, memory=memory, knowledge=knowledge,
                client_id=self.client_id, entity=entity,
            )
            try:
                raw = self.call_llm(task=format_for_llm(context), intent="admin")
                llm_data = self.parse_llm_json(raw)
                for key, value in llm_data.items():
                    if key != "attachment" and value is not None and not data.get(key):
                        data[key] = value
            except json.JSONDecodeError:
                logger.error("Admin LLM parse failed client=%s", self.client_id)
                result = {"status": "error", "message": "Could not parse your request — please try rephrasing."}
                log_action(self.client_id, "a03_admin", "admin", message, result, "error",
                        message="LLM parse failed")
                return result
            except Exception as e:
                logger.error("Admin LLM call failed client=%s: %s", self.client_id, e)
                result = {"status": "error", "message": "Request processing failed — please try again."}
                log_action(self.client_id, "a03_admin", "admin", message, result, "error",
                        message=f"LLM call failed — {e}")
                return result

        confidence = float(data.get("confidence", 0.0))
        if confidence < self.confidence_threshold:
            result = {
                "status": "escalate",
                "message": (
                    "Not sure what you'd like to do. Try: file a document, find a document, "
                    "send a message, track a permit, schedule a meeting, "
                    "or send me a file to read/upload."
                ),
                "raw": data,
            }
            log_action(self.client_id, "a03_admin", "admin", message, result, "escalate",
                    message=f"Low confidence ({confidence:.2f})")
            return result

        action = data.get("action", "unknown")
        data["_sender"] = task.get("sender", "")
        result_data = self._execute_action(action, data)

        if result_data.get("needs_folder"):
            result = {
                "status":  "needs_info",
                "message": result_data.get("error", "Which folder should I save this to?"),
                "action":  action,
            }
            if sender:
                try:
                    from core.conversation import save_pending_intent
                    save_pending_intent(
                        sender=sender,
                        client_id=self.client_id,
                        intent="admin",
                        original_message=message,
                        action=action,
                        partial_data={
                            k: v for k, v in data.items()
                            if k not in ("attachment", "_sender")
                        },
                    )
                except Exception as e:
                    logger.warning("save_pending_intent needs_folder failed client=%s: %s", self.client_id, e)
            log_action(self.client_id, "a03_admin", "admin", message, result, "needs_info",
                    message="No folder specified for upload")
            return result
        
        if result_data.get("needs_file"):
            result = {
                "status": "needs_info",
                "message": result_data["error"],
                "action": action,
            }
            if sender:
                try:
                    from core.conversation import save_pending_intent
                    save_pending_intent(
                        sender=sender,
                        client_id=self.client_id,
                        intent="admin",
                        original_message=message,
                        action=action,
                        partial_data={
                            k: v for k, v in data.items()
                            if k not in ("attachment", "_sender")
                        },
                    )
                except Exception as e:
                    logger.warning("save_pending_intent needs_file failed client=%s: %s", self.client_id, e)
            log_action(self.client_id, "a03_admin", "admin", message, result, "needs_info",
                message="No file attached for file_document")
            return result

        if result_data.get("error"):
            logger.error("Admin %s failed client=%s: %s", action, self.client_id, result_data["error"])
            result = {"status": "error", "message": result_data["error"]}
            log_action(self.client_id, "a03_admin", "admin", message, result, "error",
                    message=f"{action} failed — {result_data['error']}")
            return result

        if result_data.get("unavailable"):
            confirmation = format_admin_confirmation_llm(action, data, result_data)
            result = {
                "status": "success",
                "message": confirmation,
                "action": action,
                "result": result_data,
            }
            log_action(self.client_id, "a03_admin", "admin", message, result, "unavailable",
                    message=f"Schedule conflict for {entity} at {data.get('meeting_date')} {data.get('meeting_time')}")
            return result

        if action in ("file_document", "track_permit"):
            self._save_to_db(data, result_data)
        if action == "upload_document" and result_data.get("uploaded"):
            self._save_uploaded_doc_to_db(data, result_data)
        if action == "schedule_meeting" and not result_data.get("error") and not result_data.get("unavailable"):
            self._save_meeting(data, result_data)

        if sender and action in _CLEAR_CACHE_AFTER_ACTIONS and result_data.get("uploaded") or result_data.get("filed") or result_data.get("renamed") or result_data.get("deleted") or result_data.get("moved"):
            try:
                from core.conversation import clear_file_bytes_context
                clear_file_bytes_context(sender, self.client_id)
            except Exception as e:
                logger.warning("clear_file_bytes_context failed client=%s: %s", self.client_id, e)

        if entity:
            self.record_entity(entity_name=entity, domain="admin")

        try:
            save_memory(
                self.client_id, "a03_admin",
                f"Admin {action} for {entity} — {data.get('document_type', '')}",
            )
        except Exception as e:
            logger.warning("save_memory non-fatal client=%s: %s", self.client_id, e)

        confirmation = format_admin_confirmation_llm(action, data, result_data)
        result = {
            "status": "success",
            "message": confirmation,
            "action": action,
            "result": result_data,
        }
        if (
            action in ("file_document", "upload_document")
            and result.get("status") == "success"
            and sender
            and file_bytes
        ):
            from core.conversation import save_file_bytes_context
            save_file_bytes_context(
                sender=sender,
                client_id=self.client_id,
                file_bytes=file_bytes,
                mime_type=mime_type,
                filename=result_data.get("filename", "document"),
            )

        log_action(self.client_id, "a03_admin", "admin", message, result, "success",
            message=f"Admin {action} for {data.get('entity_name', 'unknown')} — {data.get('document_type', '')}")
        return result

    def _execute_action(self, action: str, data: dict) -> dict:
        handler = getattr(self, f"_action_{action}", None)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        try:
            return handler(data)
        except CircuitOpenError as e:
            logger.warning("Circuit breaker open client=%s action=%s: %s", self.client_id, action, e)
            return {"error": "Integration is temporarily unavailable — please try again in a few minutes."}
        except Exception as e:
            logger.error("Action %s failed client=%s: %s", action, self.client_id, e)
            return {"error": str(e)}

    def _get_storage(self):
        """Return the storage integration for this client. Raises ValueError if none connected."""
        return get_storage_integration(self.client_id)

    def _resolve_folder_id(self, storage, folder_name: str) -> Optional[str]:
        """
        Resolve a folder name to its storage ID.
        """
        if not folder_name or folder_name.lower().strip() in _GENERIC_WORDS:
            return None
        try:
            folder_obj = storage.get_folder_by_name(folder_name)
            if folder_obj and not folder_obj.get("error"):
                return folder_obj.get("id")
        except Exception as e:
            logger.warning("_resolve_folder_id failed client=%s folder=%s: %s",
                           self.client_id, folder_name, e)
        return None

    def _resolve_upload_folder(self, data: dict) -> tuple[str, Optional[str]]:
        """
        Return (folder_name, folder_id) for an upload.
        """
        raw = (data.get("folder_name") or "").strip().lower().removesuffix(" folder").strip()
        if not raw or raw in _GENERIC_WORDS:
            return ("", None)

        folder_id: Optional[str] = None
        try:
            storage   = self._get_storage()
            folder_obj = storage.get_folder_by_name(raw)
            if folder_obj and not folder_obj.get("error"):
                folder_id = folder_obj.get("id")
        except Exception as e:
            logger.warning("_resolve_upload_folder lookup failed client=%s folder=%s: %s",
                           self.client_id, raw, e)

        return (raw, folder_id)

    def _action_file_document(self, data: dict) -> dict:
        """Execute action file document for AdminAgent."""
        if not data.get("attachment"):
            return {
                "needs_file": True,
                "error": "Please send me the file you'd like to file."
            }
        try:
            storage = self._get_storage()
            raw_folder = (
                data.get("folder_name")
                or data.get("document_type")
                or "general"
            )
            folder_name = (raw_folder or "general").strip() or "general"

            existing = storage.get_folder_by_name(folder_name)
            if existing and not existing.get("error"):
                folder = existing
            else:
                folder = storage.create_folder(name=folder_name, parent_id=None)

            if not folder or folder.get("error"):
                return {"error": folder.get("error") if folder else "Storage did not respond — check your connection in integrations."}

            folder_id  = folder.get("id")
            attachment = data["attachment"]

            result = storage.upload_file(
                filename=attachment.get("filename", "document"),
                content=attachment["bytes"],
                folder_id=folder_id,
            )

            if not result or result.get("error"):
                return {"error": result.get("error", "Upload failed.") if result else "No response from storage."}

            return {"filed": True, "folder": folder_name, "filename": attachment.get("filename", "document")}
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("_action_file_document failed client=%s: %s", self.client_id, e)
            return {"error": f"Could not file document — {e}"}

    def _action_find_document(self, data: dict) -> dict:
        try:
            storage = self._get_storage()
        except ValueError as e:
            return {"error": str(e)}

        query_parts = []
        doc_type = (data.get("document_type") or "").strip()
        entity   = (data.get("entity_name")   or "").strip()
        if doc_type and doc_type.lower() not in _GENERIC_WORDS:
            query_parts.append(doc_type)
        if entity and entity.lower() not in _GENERIC_WORDS:
            query_parts.append(entity)

        query = " ".join(query_parts)
        if not query:
            try:
                items = storage.list_all(folder_id=None)
                files = [_normalise_file_item(i) for i in (items or []) if not _normalise_file_item(i)["is_folder"]]
                if not files:
                    return {"files": [], "count": 0, "query": ""}
                return {"files": files[:10], "count": len(files), "query": ""}
            except Exception as e:
                return {"error": f"Could not list files — {e}"}

        folder_name = (data.get("folder_name") or "").strip().lower().removesuffix(" folder").strip()
        folder_id   = self._resolve_folder_id(storage, folder_name) if folder_name else None

        try:
            raw = storage.search_files(query=query, folder_id=folder_id)
            if not raw and folder_id:
                raw = storage.search_files(query=query, folder_id=None)
            files = [_normalise_file_item(f) for f in (raw or [])]
            return {"files": files, "count": len(files), "query": query}
        except Exception as e:
            logger.error("_action_find_document failed client=%s: %s", self.client_id, e)
            return {"error": f"Search failed — {e}"}

    def _action_upload_document(self, data: dict) -> dict:
        """Upload an attached file to storage — requires an explicit folder destination."""
        attachment = data.get("attachment")
        if not attachment:
            return {"error": "No file attached. Send a document or image to upload."}

        folder_name, folder_id = self._resolve_upload_folder(data)

        if not folder_name:
            try:
                storage      = self._get_storage()
                folders      = storage.list_folders()
                folder_names = [f.get("name") for f in (folders or []) if f.get("name")]
                if folder_names:
                    options = ", ".join(f"'{n}'" for n in folder_names[:8])
                    return {
                        "needs_folder": True,
                        "error": (
                            f"Which folder should I save this to? Available: {options}. "
                            f"Or give me a new name and I'll create it."
                        ),
                    }
                return {
                    "needs_folder": True,
                    "error": "Which folder should I save this to? Say a folder name and I'll create it.",
                }
            except Exception as e:
                logger.warning("list_folders during upload prompt failed client=%s: %s", self.client_id, e)
                return {"needs_folder": True, "error": "Which folder should I save this to?"}

        try:
            storage = self._get_storage()

            if folder_id is None:
                existing = storage.get_folder_by_name(folder_name)
                if existing and not existing.get("error"):
                    folder_id = existing.get("id")
                else:
                    folder = storage.create_folder(name=folder_name, parent_id=None)
                    if not folder or folder.get("error"):
                        return {"error": f"Could not create folder '{folder_name}' — {folder.get('error', 'unknown error') if folder else 'no response'}"}
                    folder_id = folder.get("id")

            if not folder_id:
                return {"error": f"Could not resolve folder '{folder_name}' — please try again."}

            original = (attachment.get("filename") or "").strip()
            mime = attachment.get("mime_type", "")

            if "." in original:
                ext = original.rsplit(".", 1)[-1].lower()
            else:
                _MIME_EXT = {
                    "image/jpeg": "jpg",  "image/png": "png",   "image/gif": "gif",
                    "image/webp": "webp", "application/pdf": "pdf",
                    "application/msword": "doc",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                    "application/vnd.ms-excel": "xls",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
                    "text/plain": "txt",  "text/csv": "csv",
                }
                ext = _MIME_EXT.get(mime, "")

            from datetime import datetime as _dt
            timestamp = _dt.utcnow().strftime("%Y%m%d_%H%M%S")

            prefix_parts = []
            for field in ("document_type", "entity_name"):
                val = (data.get(field) or "").strip()
                if val and val.lower() not in _GENERIC_WORDS:
                    prefix_parts.append(val.replace(" ", "_"))

            if prefix_parts:
                base = "_".join(prefix_parts) + f"_{timestamp}"
            elif original and original.lower().rstrip("." + ext) not in _GENERIC_WORDS:
                base = original.rsplit(".", 1)[0] if "." in original else original
            else:
                base = f"upload_{timestamp}"

            smart_filename = f"{base}.{ext}" if ext else base

            result = storage.upload_file(
                filename=smart_filename,
                content=attachment["bytes"],
                folder_id=folder_id,
            )
            if not result or result.get("error"):
                return {"error": result.get("error", "Upload failed — storage returned no response.") if result else "Upload failed — no response from storage."}

            file_link = result.get("webViewLink") or result.get("webUrl") or ""
            file_id   = result.get("id", "")

            return {
                "uploaded": True,
                "file_id": file_id,
                "link": file_link,
                "filename": smart_filename,
                "folder": folder_name,
                "folder_id": folder_id,
            }
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("_action_upload_document failed client=%s: %s", self.client_id, e)
            return {"error": f"Upload failed — {e}"}
    def _action_read_document(self, data: dict) -> dict:
        """Open, read, and summarise a document or image."""
        attachment  = data.get("attachment")
        file_id     = data.get("file_id")
        folder_name = (data.get("folder_name") or "").strip().lower().removesuffix(" folder").strip()

        if (data.get("entity_name") or "").lower() in ("inbox", "emails", "email", "my emails"):
            try:
                from integrations.email_factory import get_email_from_config
                email = get_email_from_config(self.client_id)
                raw = email.list_messages(max_results=10)
                if not raw:
                    return {"read": True, "summary": "No emails found.", "filename": "inbox"}
                lines = []
                for msg in raw[:10]:
                    msg_id = msg.get("id", "")
                    if not msg_id:
                        continue
                    full = email.get_message(msg_id)
                    headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])} if "payload" in full else {}
                    subject = headers.get("subject") or full.get("subject", "No subject")
                    sender = headers.get("from") or full.get("from", {}).get("emailAddress", {}).get("address", "")
                    snippet = full.get("snippet") or full.get("bodyPreview", "")
                    lines.append(f"From: {sender}\nSubject: {subject}\nPreview: {snippet}")
                return {"read": True, "summary": "\n\n".join(lines), "filename": "inbox"}
            except Exception as e:
                logger.error("email read failed client=%s: %s", self.client_id, e)
                return {"error": str(e)}

        if attachment:
            content      = attachment["bytes"]
            doc_mime     = attachment.get("mime_type", "application/octet-stream")
            doc_filename = attachment.get("filename", "document")
        elif file_id:
            try:
                storage = self._get_storage()
                dl = storage.download_file(file_id)
                if dl.get("error"):
                    return {"error": dl["error"]}
                content = dl.get("content", b"")
                doc_mime = dl.get("mime_type", "application/octet-stream")
                doc_filename = dl.get("name", "document")
            except Exception as e:
                return {"error": f"Could not download file — {e}"}
        else:
            query = (data.get("entity_name") or "").strip()

            try:
                storage = self._get_storage()
            except ValueError as e:
                return {"error": str(e)}

            scope_folder_id = self._resolve_folder_id(storage, folder_name) if folder_name else None

            if not query or query.lower() in _GENERIC_WORDS:
                try:
                    all_items  = storage.list_all(folder_id=scope_folder_id)
                    all_normal = [_normalise_file_item(i) for i in (all_items or [])]
                    files      = [f for f in all_normal if not f["is_folder"]]
                    if not files:
                        return {"error": "No files found. Upload a document or image first."}
                    names = [f["name"] for f in files[:8] if f["name"]]
                    return {
                        "error": f"Which file would you like me to open? Available: {', '.join(repr(n) for n in names)}."
                    }
                except Exception as e:
                    return {"error": f"Could not list files — {e}"}

            try:
                candidates_raw = storage.search_files(query=query, folder_id=scope_folder_id)

                if not candidates_raw and scope_folder_id:
                    candidates_raw = storage.search_files(query=query, folder_id=None)

                if not candidates_raw:
                    all_items  = storage.list_all(folder_id=scope_folder_id)
                    all_normal = [_normalise_file_item(i) for i in (all_items or [])]
                    files_only = [f for f in all_normal if not f["is_folder"]]

                    query_tokens = set(query.lower().split())
                    scored = [
                        (f, sum(1 for t in query_tokens if t in f["name"].lower()))
                        for f in files_only
                    ]
                    best_score = max((s for _, s in scored), default=0)

                    if best_score > 0:
                        top = [f for f, s in scored if s == best_score]
                        best_norm = min(top, key=lambda f: abs(len(f["name"]) - len(query)))
                    else:
                        available = [f["name"] for f in files_only[:8]]
                        names_str = ", ".join(repr(n) for n in available) if available else "none"
                        return {
                            "error": (
                                f"Couldn't find a file matching '{query}'. "
                                f"Available: {names_str}. Which one would you like?"
                            )
                        }

                    resolved_id = best_norm["id"]
                    if not resolved_id:
                        return {"error": f"Could not resolve file ID for '{best_norm['name']}'. Try uploading it again."}
                    dl = storage.download_file(resolved_id)
                    if dl.get("error"):
                        return {"error": dl["error"]}
                    content      = dl.get("content", b"")
                    doc_mime     = dl.get("mime_type", "application/octet-stream")
                    doc_filename = dl.get("name", best_norm["name"])

                else:
                    file_candidates = [_normalise_file_item(c) for c in candidates_raw if not _normalise_file_item(c)["is_folder"]]
                    if not file_candidates:
                        return {"error": f"No readable file found matching '{query}' — folders can't be opened directly."}

                    best_norm   = min(file_candidates, key=lambda f: abs(len(f["name"]) - len(query)))
                    resolved_id = best_norm["id"]
                    if not resolved_id:
                        return {"error": f"Could not resolve file ID for '{best_norm['name']}'. Try uploading it again."}

                    dl = storage.download_file(resolved_id)
                    if dl.get("error"):
                        return {"error": dl["error"]}
                    content      = dl.get("content", b"")
                    doc_mime     = dl.get("mime_type", "application/octet-stream")
                    doc_filename = dl.get("name", best_norm["name"])

            except ValueError as e:
                return {"error": str(e)}
            except Exception as e:
                logger.error("_action_read_document resolve failed client=%s: %s", self.client_id, e)
                return {"error": f"Could not locate document — {e}"}

        try:
            import base64
            from anthropic import Anthropic
            from anthropic.types import TextBlockParam, ImageBlockParam, Base64ImageSourceParam, DocumentBlockParam
            from config.settings import settings

            b64 = base64.standard_b64encode(content).decode()
            user_prompt = data.get("content") or "Summarize this document clearly and concisely."

            if doc_mime.startswith("image/"):
                safe_mime = doc_mime if doc_mime in ("image/jpeg", "image/png", "image/gif", "image/webp") else "image/jpeg"
                content_block = ImageBlockParam(
                    type="image",
                    source=Base64ImageSourceParam(type="base64", media_type=safe_mime, data=b64),
                )
            else:
                content_block = DocumentBlockParam(
                    type="document",
                    source={"type": "base64", "media_type": "application/pdf", "data": b64},
                )

            client = Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": [content_block, TextBlockParam(type="text", text=user_prompt)],
                }],
            )
            summary = next((b.text for b in response.content if b.type == "text"), "")
            return {
                "read": True,
                "summary": summary,
                "filename": doc_filename,
                "file_bytes": content,
                "mime_type":  doc_mime,
            }
        except Exception as e:
            logger.error("_action_read_document summarise failed client=%s: %s", self.client_id, e)
            return {"error": f"Could not read document — {e}"}

    def _action_list_documents(self, data: dict) -> dict:
        """List documents — folder-scoped, normalised output, DB fallback."""
        live_items: Optional[list] = None
        live_error = ""

        folder_name = (data.get("folder_name") or "").strip().lower().removesuffix(" folder").strip()

        try:
            storage   = self._get_storage()
            folder_id = self._resolve_folder_id(storage, folder_name) if folder_name else None

            entity = (data.get("entity_name") or "").strip()
            if entity and entity.lower() not in _GENERIC_WORDS:
                live_items = storage.search_files(query=entity, folder_id=folder_id)
            else:
                live_items = storage.list_all(folder_id=folder_id)

        except ValueError as e:
            live_error = str(e)
        except Exception as e:
            live_error = str(e)

        if live_items is not None:
            documents = [_normalise_file_item(i) for i in live_items]
            return {
                "documents": documents,
                "total":     len(documents),
                "source":    "live",
                "folder":    folder_name or "root",
            }

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                params: list = [self.client_id]
                where = ["client_id=%s"]
                if data.get("document_type") and data["document_type"].lower() not in _GENERIC_WORDS:
                    where.append("doc_type=%s")
                    params.append(data["document_type"])
                if data.get("entity_name") and data["entity_name"].lower() not in _GENERIC_WORDS:
                    where.append("client_name ILIKE %s")
                    params.append(f"%{data['entity_name']}%")
                cur.execute(
                    f"SELECT filename, doc_type, client_name, storage_path, status, created_at "
                    f"FROM documents WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT 20",
                    params,
                )
                rows = cur.fetchall()
                cur.close()

            if not rows:
                if live_error:
                    return {"error": live_error}
                return {"documents": [], "total": 0, "source": "db"}

            documents = [
                {
                    "id":          "",
                    "name":        r[0],
                    "mime_type":   r[1],
                    "link":        r[3],
                    "is_folder":   False,
                    "created_at":  str(r[5]),
                    "modified_at": "",
                    "size":        0,
                    "entity":      r[2],
                    "status":      r[4],
                    "source":      "db",
                }
                for r in rows
            ]
            return {"documents": documents, "total": len(documents), "source": "db"}

        except Exception as e:
            logger.error("_action_list_documents DB fallback failed client=%s: %s", self.client_id, e)
            return {"error": live_error or str(e)}
        
    def _resolve_file_id(self, storage, data: dict) -> tuple[str, str]:
        entity = (data.get("entity_name") or "").strip()
        folder = (data.get("folder_name") or "").strip().lower().removesuffix(" folder").strip()

        entity_clean = entity
        if entity_clean.lower().endswith(" folder"):
            entity_clean = entity_clean[:-7].strip()

        _VAGUE = frozenset({"this", "it", "this file", "the file", "this document", "the document", ""})
        if entity_clean.lower() in _VAGUE:
            try:
                from core.conversation import get_action_context
                sender = data.get("_sender", "")
                if sender:
                    ctx = get_action_context(sender, self.client_id, "admin")
                    if ctx.get("filename"):
                        entity_clean = ctx["filename"]
                        if not folder and ctx.get("folder"):
                            folder = ctx["folder"]
            except Exception:
                pass

        if not entity_clean or entity_clean.lower() in _GENERIC_WORDS:
            return "", ""

        folder_id = self._resolve_folder_id(storage, folder) if folder else None
        raw = storage.search_files(query=entity_clean, folder_id=folder_id)
        if not raw and folder_id:
            raw = storage.search_files(query=entity_clean, folder_id=None)

        if raw:
            candidates = [
                _normalise_file_item(f)
                for f in raw
                if not _normalise_file_item(f)["is_folder"]
        ]
            if candidates:
                exact = [f for f in candidates if entity_clean.lower() in f["name"].lower()]
                if len(exact) == 1:
                    return exact[0]["id"], exact[0]["name"]
                if len(exact) > 1:
                    best = min(exact, key=lambda f: abs(len(f["name"]) - len(entity_clean)))
                    return best["id"], best["name"]
                best = min(candidates, key=lambda f: abs(len(f["name"]) - len(entity_clean)))
                return best["id"], best["name"]

        try:
            folder_obj = storage.get_folder_by_name(entity_clean)
            if folder_obj and not folder_obj.get("error"):
                fid   = folder_obj.get("id", "")
                fname = folder_obj.get("name", entity_clean)
                if fid:
                    return fid, fname
        except Exception:
            pass

        return "", ""

    def _action_move_document(self, data: dict) -> dict:
        try:
            storage = self._get_storage()
        except ValueError as e:
            return {"error": str(e)}

        raw_entity = (data.get("entity_name") or "").strip()
        if raw_entity.lower().endswith(" folder"):
            raw_entity = raw_entity[:-7].strip()
        data_for_resolve = {**data, "entity_name": raw_entity}

        file_id, filename = self._resolve_file_id(storage, data_for_resolve)
        if not file_id:
            display = raw_entity or data.get("entity_name") or "that item"
            return {"error": f"Could not find '{display}' — try listing files or folders first to confirm the exact name."}

        target_folder_name = (data.get("target_folder") or "").strip().lower().removesuffix(" folder").strip()
        if not target_folder_name:
            return {"error": "Please specify which folder to move it to."}

        target_folder = storage.get_folder_by_name(target_folder_name)
        if not target_folder or target_folder.get("error"):
            target_folder = storage.create_folder(name=target_folder_name, parent_id=None)
        if not target_folder or target_folder.get("error"):
            return {"error": f"Could not find or create folder '{target_folder_name}'."}

        result = storage.move_file(file_id=file_id, target_folder_id=str(target_folder.get("id")))
        if result.get("error"):
            return {"error": result["error"]}

        return {
            "moved":         True,
            "filename":      filename,
            "from_folder":   data.get("folder_name", "previous location"),
            "to_folder":     target_folder_name,
        }

    def _action_delete_document(self, data: dict) -> dict:
        try:
            storage = self._get_storage()
        except ValueError as e:
            return {"error": str(e)}

        file_id, filename = self._resolve_file_id(storage, data)
        if not file_id:
            display = (data.get("entity_name") or "that item")
            return {"error": f"Could not find '{display}' — try a more specific name."}

        result = storage.delete_file(file_id=file_id)
        if result.get("error"):
            return {"error": result["error"]}

        return {"deleted": True, "filename": filename}

    def _action_rename_document(self, data: dict) -> dict:
        try:
            storage = self._get_storage()
        except ValueError as e:
            return {"error": str(e)}

        new_name = (data.get("new_name") or "").strip()
        if not new_name:
            return {"error": "Please provide a new name for the file."}

        file_id, filename = self._resolve_file_id(storage, data)
        if not file_id:
            display = (data.get("entity_name") or "that file")
            return {"error": f"Could not find '{display}' — try a more specific name."}

        result = storage.rename_file(file_id=file_id, new_name=new_name)
        if result.get("error"):
            return {"error": result["error"]}

        return {"renamed": True, "old_name": filename, "new_name": new_name}

    def _action_copy_document(self, data: dict) -> dict:
        try:
            storage = self._get_storage()
        except ValueError as e:
            return {"error": str(e)}

        file_id, filename = self._resolve_file_id(storage, data)
        if not file_id:
            display = (data.get("entity_name") or "that file")
            return {"error": f"Could not find '{display}' — try a more specific name."}

        target_folder_name = (data.get("target_folder") or "").strip().lower().removesuffix(" folder").strip()
        if not target_folder_name:
            return {"error": "Please specify which folder to copy it to."}

        target_folder = storage.get_folder_by_name(target_folder_name)
        if not target_folder or target_folder.get("error"):
            target_folder = storage.create_folder(name=target_folder_name, parent_id=None)
        if not target_folder or target_folder.get("error"):
            return {"error": f"Could not find or create folder '{target_folder_name}'."}

        result = storage.copy_file(file_id=file_id, target_folder_id=str(target_folder.get("id")))
        if result.get("error"):
            return {"error": result["error"]}

        return {"copied": True, "filename": filename, "to_folder": target_folder_name}

    def _action_delete_folder(self, data: dict) -> dict:
        try:
            storage = self._get_storage()
        except ValueError as e:
            return {"error": str(e)}

        folder_name = (data.get("folder_name") or "").strip().lower().removesuffix(" folder").strip()
        if not folder_name:
            return {"error": "Please specify which folder to delete."}

        folder = storage.get_folder_by_name(folder_name)
        if not folder or folder.get("error"):
            return {"error": f"Folder '{folder_name}' not found."}

        result = storage.delete_folder(folder_id=str(folder.get("id")))
        if result.get("error"):
            return {"error": result["error"]}

        return {"deleted": True, "folder": folder_name}

    def _action_rename_folder(self, data: dict) -> dict:
        try:
            storage = self._get_storage()
        except ValueError as e:
            return {"error": str(e)}

        folder_name = (data.get("folder_name") or "").strip().lower().removesuffix(" folder").strip()
        new_name    = (data.get("new_name") or "").strip()
        if not folder_name:
            return {"error": "Please specify which folder to rename."}
        if not new_name:
            return {"error": "Please provide a new name for the folder."}

        folder = storage.get_folder_by_name(folder_name)
        if not folder or folder.get("error"):
            return {"error": f"Folder '{folder_name}' not found."}

        result = storage.rename_folder(folder_id=str(folder.get("id")), new_name=new_name)
        if result.get("error"):
            return {"error": result["error"]}

        return {"renamed": True, "old_name": folder_name, "new_name": new_name}

    def _action_share_document(self, data: dict) -> dict:
        try:
            storage = self._get_storage()
        except ValueError as e:
            return {"error": str(e)}

        file_id, filename = self._resolve_file_id(storage, data)
        if not file_id:
            display = (data.get("entity_name") or "that file")
            return {"error": f"Could not find '{display}' — try a more specific name."}

        result = storage.share_file(file_id=file_id)
        if result.get("error"):
            return {"error": result["error"]}

        return {"shared": True, "filename": filename, "link": result.get("link", "")}

    def _action_get_document_info(self, data: dict) -> dict:
        try:
            storage = self._get_storage()
        except ValueError as e:
            return {"error": str(e)}

        file_id, filename = self._resolve_file_id(storage, data)
        if not file_id:
            display = (data.get("entity_name") or "that file")
            return {"error": f"Could not find '{display}' — try a more specific name."}

        result = storage.get_file_info(file_id=file_id)
        if result.get("error"):
            return {"error": result["error"]}

        return result


    def _action_list_meetings(self, data: dict) -> dict:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT booking_ref, details, status, created_at FROM bookings "
                    "WHERE client_id=%s AND status='scheduled' ORDER BY created_at DESC LIMIT 20",
                    (self.client_id,),
                )
                rows = cur.fetchall()
                cur.close()
            meetings = []
            for row in rows:
                details = json.loads(row[1]) if row[1] else {}
                meetings.append({
                    "event_id": row[0],
                    "title": details.get("title", "Meeting"),
                    "start": details.get("start"),
                    "link": details.get("link", ""),
                    "attendees": details.get("attendees", []),
                    "entity": details.get("entity_name", ""),
                    "timezone": details.get("timezone", "UTC"),
                })

            return {"meetings": meetings, "total": len(meetings)}
        except Exception as e:
            logger.error("_action_list_meetings failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_meeting_reminder(self, data: dict) -> dict:
        event_id = data.get("event_id") or self._resolve_last_event_id(data.get("entity_name", ""))
        if not event_id:
            return {"error": "No meeting found to send a reminder for."}
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT details FROM bookings WHERE client_id=%s AND booking_ref=%s",
                    (self.client_id, event_id),
                )
                row = cur.fetchone()
                cur.close()

            if not row:
                return {"error": "Meeting not found."}
            details = json.loads(row[0]) if row[0] else {}
            attendees = details.get("attendees", [])
            title = details.get("title", "Meeting")
            start = details.get("start", "")
            link = details.get("link", "")
            timezone = details.get("timezone", "UTC")
            if not attendees:
                return {"error": "No attendees found for this meeting — no reminders sent."}
            sent_to, failed = [], []
            try:
                from integrations.email_factory import get_email_from_config
                email = get_email_from_config(self.client_id)
                for addr in attendees:
                    try:
                        email.send(
                            recipient=addr,
                            subject=f"Reminder: {title}",
                            body=(
                                f"This is a reminder for your upcoming meeting.\n\n"
                                f"Title: {title}\nWhen: {start} ({timezone})\n"
                                f"Link: {link or 'No link available'}\n\nSee you then."
                            ),
                        )
                        sent_to.append(addr)
                    except Exception:
                        failed.append(addr)
            except Exception:
                return {"error": "Email not connected — please connect Gmail or Outlook first."}

            return {"reminder_sent": True, "sent_to": sent_to, "failed": failed, "event_id": event_id}

        except Exception as e:
            logger.error("_action_meeting_reminder failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_send_communication(self, data: dict) -> dict:
        """Execute action send communication for AdminAgent."""
        recipient = data.get("recipient_email")
        if not recipient:
            return {"error": "No recipient email provided."}
        try:
            from integrations.email_factory import get_email_from_config
            email = get_email_from_config(self.client_id)
            if email is None:
                return {"error": "No email integration connected — please connect Gmail or Outlook in integrations."}
            sent = self._email_cb.call(
                email.send,
                recipient=recipient,
                subject=f"Message for {data.get('entity_name', recipient)}",
                body=data.get("content", ""),
            )
            if not sent:
                return {"error": "Email could not be sent — check your Gmail or Outlook connection."}
            return {"sent": True, "to": recipient}
        except CircuitOpenError:
            raise
        except Exception as e:
            logger.error("_action_send_communication failed client=%s: %s", self.client_id, e)
            return {"error": f"Email failed — {e}"}

    def _action_track_permit(self, data: dict) -> dict:
        entity = data.get("entity_name")
        doc_type = data.get("document_type")
        expiry = data.get("expiry_date")
        days_left: Optional[int] = None
        if expiry:
            try:
                days_left = (datetime.strptime(expiry, "%Y-%m-%d").date() - date.today()).days
            except ValueError:
                pass

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE documents SET status='tracked', expiry_date=%s "
                    "WHERE client_id=%s AND (filename=%s OR doc_type=%s) RETURNING id",
                    (expiry, self.client_id, entity, doc_type),
                )
                row = cur.fetchone()
                cur.close()
            return {"tracking": True, "entity": entity, "expiry": expiry,
                    "days_left": days_left, "found": row is not None}
        except Exception as exc:
            logger.error("_action_track_permit failed client=%s: %s", self.client_id, exc)
            return {"error": str(exc)}

    def _action_schedule_meeting(self, data: dict) -> dict:
        meeting_date = data.get("meeting_date")
        meeting_time = data.get("meeting_time")
        duration = int(data.get("meeting_duration") or 60)
        timezone = data.get("timezone", "UTC")

        try:
            from integrations.calendar_factory import get_calendar_from_config
            calendar = get_calendar_from_config(self.client_id)
        except ValueError as e:
            return {"error": str(e)}
        except Exception:
            return {"error": "No calendar connected — please connect Google Calendar or Outlook in integrations."}

        try:
            avail = self._calendar_cb.call(
                calendar.check_availability,
                str(meeting_date), str(meeting_time), duration, timezone,
            )
        except CircuitOpenError:
            raise
        except Exception as e:
            logger.error("check_availability failed client=%s: %s", self.client_id, e)
            return {"error": f"Calendar availability check failed — {e}"}

        if not avail:
            return {"error": "Calendar did not respond — please check your calendar connection."}
        if avail.get("error"):
            return {"error": avail["error"]}
        if not avail.get("available"):
            suggested = self._suggest_alternative_slots(
                calendar, str(meeting_date), str(meeting_time), duration, timezone
            )
            return {"unavailable": True, "conflicts": avail.get("conflicts", []),
                "suggested_slots": suggested, "error": None}
        local_start = datetime.strptime(f"{meeting_date}T{meeting_time}", "%Y-%m-%dT%H:%M")
        local_end = local_start + timedelta(minutes=duration)
        try:
            event = self._calendar_cb.call(
                calendar.create_event,
                {
                    "subject": f"Meeting — {data.get('entity_name', 'Client')}",
                    "description": data.get("content", ""),
                    "start": local_start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "end": local_end.strftime("%Y-%m-%dT%H:%M:%S"),
                    "attendees": data.get("attendees", []),
                    "timezone": timezone,
                },
            )
        except CircuitOpenError:
            raise
        except Exception as e:
            logger.error("create_event failed client=%s: %s", self.client_id, e)
            return {"error": f"Calendar event creation failed — {e}"}
        if not event:
            return {
                "scheduled": True, "timezone": timezone,
                "event": {
                    "event_id": "", "title": f"Meeting — {data.get('entity_name', 'Client')}",
                    "start": local_start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "end": local_end.strftime("%Y-%m-%dT%H:%M:%S"),
                    "link": "", "teams_link": "",
                    "attendees": data.get("attendees", []), "provider": "calendar",
                },
            }
        if event.get("error"):
            return {"error": event["error"]}
        return {"scheduled": True, "timezone": timezone, "event": event}

    def _action_add_attendee(self, data: dict) -> dict:
        event_id = data.get("event_id") or self._resolve_last_event_id(data.get("entity_name", ""))
        new_attendees = data.get("attendees", [])
        if not event_id:
            return {"error": "No event found — please specify the meeting name or date (e.g. 'the Monday meeting' or 'the Acme meeting')."}
        if not new_attendees:
            return {"error": "No attendee email provided."}

        try:
            from integrations.calendar_factory import get_calendar_from_config
            calendar = get_calendar_from_config(self.client_id)
            result = self._calendar_cb.call(calendar.patch_attendees, event_id, new_attendees)

            if result.get("updated"):
                try:
                    with get_conn() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT details FROM bookings WHERE client_id=%s AND booking_ref=%s",
                            (self.client_id, event_id),
                        )
                        row = cur.fetchone()
                        if row:
                            details = json.loads(row[0]) if row[0] else {}
                            details["attendees"] = result.get("attendees", [])
                            cur.execute(
                                "UPDATE bookings SET details=%s WHERE client_id=%s AND booking_ref=%s",
                                (json.dumps(details), self.client_id, event_id),
                            )
                        cur.close()
                except Exception as db_exc:
                    logger.warning("DB attendee update failed client=%s: %s", self.client_id, db_exc)

            return result
        except CircuitOpenError:
            raise
        except Exception as e:
            logger.error("_action_add_attendee failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}


    def _suggest_alternative_slots(
        self, calendar, meeting_date: str, meeting_time: str, duration: int, timezone: str
    ) -> list:
        """Execute suggest alternative slots for AdminAgent."""
        suggestions: list[str] = []
        try:
            base_dt = datetime.strptime(f"{meeting_date}T{meeting_time}", "%Y-%m-%dT%H:%M")
            candidates = [
                base_dt + timedelta(hours=1),
                base_dt + timedelta(hours=2),
                base_dt + timedelta(days=1),
            ]
            for candidate in candidates:
                c_date = candidate.strftime("%Y-%m-%d")
                c_time = candidate.strftime("%H:%M")
                try:
                    avail = self._calendar_cb.call(calendar.check_availability, c_date, c_time, duration)
                    if avail and avail.get("available") and not avail.get("error"):
                        suggestions.append(f"{c_date} at {c_time} ({timezone})")
                except Exception as e:
                    logger.warning("Slot suggestion check failed client=%s: %s", self.client_id, e)
                if len(suggestions) >= 2:
                    break
        except Exception as e:
            logger.error("suggest_alternative_slots failed client=%s: %s", self.client_id, e)
        return suggestions

    def _save_to_db(self, data: dict, result_data: dict) -> None:
        """Execute save to db for AdminAgent."""
        try:
            parsed_expiry: Optional[date] = None
            expiry = data.get("expiry_date")
            if expiry:
                try:
                    parsed_expiry = datetime.strptime(expiry, "%Y-%m-%d").date()
                except ValueError:
                    pass
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO documents "
                    "(client_id, doc_type, filename, client_name, expiry_date, storage_path, status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (client_id, doc_type, filename) DO UPDATE "
                    "SET expiry_date=EXCLUDED.expiry_date, storage_path=EXCLUDED.storage_path, status=EXCLUDED.status",
                    (
                        self.client_id, data.get("document_type"), data.get("entity_name"),
                     data.get("entity_name"), parsed_expiry,
                     result_data.get("storage_path", ""), "processed",
                    ),
                )
                cur.close()
        except Exception as e:
            logger.error("_save_to_db failed client=%s: %s", self.client_id, e)

    def _save_uploaded_doc_to_db(self, data: dict, result_data: dict) -> None:
        try:
            attachment = data.get("attachment", {})
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO documents (client_id, doc_type, filename, client_name, storage_path, status) "
                    "VALUES (%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (client_id, doc_type, filename) DO UPDATE "
                    "SET storage_path=EXCLUDED.storage_path, status=EXCLUDED.status",
                    (
                        self.client_id,
                        data.get("document_type", "general"),
                        attachment.get("filename", result_data.get("filename", "document")),
                        data.get("entity_name", ""),
                        result_data.get("link") or result_data.get("file_id", ""),
                        "uploaded",
                    ),
                )
                cur.close()
        except Exception as e:
            logger.error("_save_uploaded_doc_to_db failed client=%s: %s", self.client_id, e)

    def _save_meeting(self, data: dict, result_data: dict) -> None:
        """Execute save meeting for AdminAgent."""
        try:
            event = result_data.get("event", {})
            event_id = event.get("event_id", "")
            if not event_id:
                event_id = f"local_{self.client_id}_{datetime.utcnow().timestamp()}"
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO bookings (client_id, booking_ref, details, status, raw_message) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (client_id, booking_ref) DO NOTHING",
                    (
                        self.client_id, event_id,
                        json.dumps({
                            "title": event.get("title"),
                            "start": event.get("start"),
                            "end": event.get("end"),
                            "link": event.get("link"),
                            "teams_link": event.get("teams_link"),
                            "attendees": event.get("attendees", []),
                            "provider": event.get("provider"),
                            "entity_name": data.get("entity_name"),
                            "timezone": result_data.get("timezone", "UTC"),
                        }),
                        "scheduled", json.dumps(data),
                    ),
                )
                cur.close()
        except Exception as e:
            logger.error("_save_meeting failed client=%s: %s", self.client_id, e)

    def _resolve_last_event_id(self, entity_name: str) -> str:
        """Resolve the most recent event_id for an entity from bookings."""
        entity_lower = (entity_name or "").lower().strip()
        day_weekday: Optional[int] = None
        for day, num in _DAY_NAME_TO_WEEKDAY.items():
            if day in entity_lower:
                day_weekday = num
                break

        try:
            with get_conn() as conn:
                cur = conn.cursor()

                if day_weekday is not None:
                    cur.execute(
                        "SELECT booking_ref, details FROM bookings "
                        "WHERE client_id=%s AND status='scheduled' "
                        "ORDER BY id DESC LIMIT 20",
                        (self.client_id,),
                    )
                    rows = cur.fetchall()
                    for booking_ref, details_raw in rows:
                        try:
                            details   = json.loads(details_raw) if details_raw else {}
                            start_str = details.get("start", "")
                            if start_str:
                                start_dt = datetime.fromisoformat(start_str.replace("Z", ""))
                                if start_dt.weekday() == day_weekday:
                                    cur.close()
                                    return booking_ref
                        except Exception:
                            continue

                if entity_name:
                    cur.execute(
                        "SELECT booking_ref FROM bookings WHERE client_id=%s "
                        "AND details::text ILIKE %s AND status='scheduled' "
                        "ORDER BY id DESC LIMIT 1",
                        (self.client_id, f"%{entity_name}%"),
                    )
                else:
                    cur.execute(
                        "SELECT booking_ref FROM bookings WHERE client_id=%s "
                        "AND status='scheduled' ORDER BY id DESC LIMIT 1",
                        (self.client_id,),
                    )
                row = cur.fetchone()
                cur.close()
                return row[0] if row else ""
        except Exception as e:
            logger.warning("_resolve_last_event_id failed client=%s: %s", self.client_id, e)
            return ""