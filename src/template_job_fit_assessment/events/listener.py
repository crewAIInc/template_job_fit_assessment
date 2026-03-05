import logging
import os

import requests as http_requests
from crewai.events import (
    BaseEventListener,
    FlowFinishedEvent,
    MethodExecutionFinishedEvent,
    MethodExecutionStartedEvent,
)

logger = logging.getLogger(__name__)

STEP_LABELS = {
    "extract_job_details": "Extracting job requirements",
    "analyze_resume": "Analyzing resume",
    "write_report": "Writing report",
}


class WebhookEventListener(BaseEventListener):
    def __init__(self):
        super().__init__()
        self.webhook_url = os.getenv("WEBHOOK_URL", "")

    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(MethodExecutionStartedEvent)
        def on_step_started(source, event):
            step = event.method_name
            if step in STEP_LABELS:
                session_id = self._extract_session_id(event.state)
                self._post_step(session_id, step, "in_progress", STEP_LABELS[step])

        @crewai_event_bus.on(MethodExecutionFinishedEvent)
        def on_step_finished(source, event):
            step = event.method_name
            if step in STEP_LABELS:
                session_id = self._extract_session_id(event.state)
                self._post_step(session_id, step, "completed", STEP_LABELS[step])

        @crewai_event_bus.on(FlowFinishedEvent)
        def on_flow_finished(source, event):
            session_id = self._extract_session_id(event.state)
            self._post_report(session_id, event.result)

    def _extract_session_id(self, state):
        if hasattr(state, "session_id"):
            return state.session_id
        if isinstance(state, dict):
            return state.get("session_id", "")
        return ""

    def _post_step(self, session_id, step, status, label):
        if not self.webhook_url:
            return
        try:
            http_requests.post(
                self.webhook_url,
                json={
                    "session_id": session_id,
                    "type": "step_update",
                    "step": step,
                    "status": status,
                    "label": label,
                },
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Webhook step POST failed: %s", exc)

    def _post_report(self, session_id, report):
        if not self.webhook_url:
            return
        try:
            http_requests.post(
                self.webhook_url,
                json={
                    "session_id": session_id,
                    "type": "final_report",
                    "report": str(report) if report else "",
                },
                timeout=10,
            )
        except Exception as exc:
            logger.warning("Webhook report POST failed: %s", exc)
