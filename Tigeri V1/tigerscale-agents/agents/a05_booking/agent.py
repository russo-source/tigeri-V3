"""Contain agent backend logic."""
import json
import psycopg2
from agents.base_agent import BaseAgent
from agents.a05_booking.tools import parse_booking_request, validate_booking, format_booking_confirmation
from agents.a05_booking.config import BOOKING_CONFIG
from memory.agent_memory import save_memory, recall_memory
from memory.rag import retrieve_knowledge
from core.context_builder import build_context, format_for_llm
from core.prompts import BOOKING_AGENT_PROMPT
from config.settings import settings
from security.audit import log_action


class BookingAgent(BaseAgent):

    """Represent the BookingAgent component and its related behavior."""
    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        super().__init__(client_id)
        self.confidence_threshold = BOOKING_CONFIG["confidence_threshold"]

    def get_system_prompt(self) -> str:
        """Return system prompt."""
        return BOOKING_AGENT_PROMPT

    def _run(self, task: dict) -> dict:
        """Run the requested operation."""
        message = task.get("message", "")

        data = parse_booking_request(message)

        is_valid, reason = validate_booking(data)
        if not is_valid:
            self.log(f"Validation failed: {reason}", "ERROR")
            result = {"status": "error", "message": reason}
            log_action(
                client_id=self.client_id,
                agent_name="a05_booking",
                intent="booking",
                input_text=message,
                output=result,
                status="error",
            )
            return result

        memory = recall_memory(
            client_id=self.client_id,
            agent_name="a05_booking",
            query=message,
        )

        knowledge = retrieve_knowledge(
            client_id=self.client_id,
            query=message,
            category="booking",
        )

        context = build_context(
            task=message,
            memory=memory,
            knowledge=knowledge,
            client_id=self.client_id,
        )

        formatted = format_for_llm(context)
        raw = self.call_llm(task=formatted)

        try:
            llm_data = self.parse_llm_json(raw)
        except json.JSONDecodeError:
            self.log("Failed to parse LLM response", "ERROR")
            result = {"status": "error", "message": "Could not parse booking request"}
            log_action(
                client_id=self.client_id,
                agent_name="a05_booking",
                intent="booking",
                input_text=message,
                output=result,
                status="error",
            )
            return result

        data.update(llm_data)
        confidence = data.get("confidence", 0.0)

        if confidence < self.confidence_threshold:
            result = {
                "status": "escalate",
                "message": "Low confidence — needs human review",
                "raw": data
            }
            log_action(
                client_id=self.client_id,
                agent_name="a05_booking",
                intent="booking",
                input_text=message,
                output=result,
                status="escalate",
            )
            return result

        action: str = data.get("action", "unknown")
        result_data = self._execute_action(action, data)

        self._save_to_db(data)

        save_memory(
            client_id=self.client_id,
            agent_name="a05_booking",
            content=f"Booking {action} for {data.get('client_name')} on {data.get('date')} at {data.get('time')}",
        )

        self.log(f"Booking {action} completed for {data.get('client_name')}")

        result = {
            "status": "success",
            "message": format_booking_confirmation(action, data),
            "action": action,
            "result": result_data
        }

        log_action(
            client_id=self.client_id,
            agent_name="a05_booking",
            intent="booking",
            input_text=message,
            output=result,
            status="success",
        )

        return result

    
    def _execute_action(self, action: str, data: dict) -> dict:
        """Execute execute action for BookingAgent."""
        try:
            if action == "create_booking":
                return {
                    "booked": True,
                    "date": data.get("date"),
                    "time": data.get("time"),
                    "client": data.get("client_name"),
                }

            elif action == "cancel_booking":
                return {
                    "cancelled": True,
                    "date": data.get("date"),
                    "client": data.get("client_name"),
                }

            elif action == "reschedule_booking":
                return {
                    "rescheduled": True,
                    "new_date": data.get("date"),
                    "new_time": data.get("time"),
                    "client": data.get("client_name"),
                }

            elif action == "check_availability":
                return {
                    "available": True,
                    "date": data.get("date"),
                }

            return {}

        except Exception as e:
            self.log(f"Action execution failed: {e}", "ERROR")
            return {"error": str(e)}

    def _save_to_db(self, data: dict):
        """Execute save to db for BookingAgent."""
        try:
            conn = psycopg2.connect(
                host=settings.db_host,
                port=settings.db_port,
                user=settings.db_user,
                password=settings.db_password,
                dbname=settings.db_name,
            )
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO bookings
                (client_id, booking_ref, details, status, raw_message)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                self.client_id,
                f"{data.get('date')}-{data.get('client_name', '').replace(' ', '-')}",
                json.dumps(data),
                "confirmed",
                json.dumps(data),
            ))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            self.log(f"DB save failed: {e}", "ERROR")