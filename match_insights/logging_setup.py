"""Structured JSON logging + optional Azure Monitor (Application Insights) export."""
from __future__ import annotations
import json, logging, os, sys, time


class JsonFormatter(logging.Formatter):
    def format(self, r):
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)) + "Z", "level": r.levelname,
             "logger": r.name, "msg": r.getMessage()}
        for k in ("agent", "event_id", "status", "attempts", "ms", "session"):
            if hasattr(r, k):
                d[k] = getattr(r, k)
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d)


def setup_logging(level="INFO", json_format=True):
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if json_format else logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
            configure_azure_monitor(logger_name="match_insights")
            logging.getLogger(__name__).info("Azure Monitor OpenTelemetry enabled")
        except Exception as ex:  # pragma: no cover - optional dependency
            logging.getLogger(__name__).warning("Azure Monitor not enabled: %s", ex)


def tracer():
    """OpenTelemetry tracer if installed, else a no-op."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("match_insights")
    except Exception:  # pragma: no cover
        return None
