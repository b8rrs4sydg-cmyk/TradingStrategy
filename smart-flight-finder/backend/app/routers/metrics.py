"""GET /metrics — Prometheus text-format scrape endpoint."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.core.metrics import render_text

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> str:
    return render_text()
