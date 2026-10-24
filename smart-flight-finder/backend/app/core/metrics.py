"""Prometheus text-format counters/gauges — zero-dep, process-local.

Dependency-free so the backend ships with it; swap to prometheus_client when
scaling horizontally and want proper labels/histograms.
"""

from __future__ import annotations

from collections.abc import Iterator
from threading import Lock

_lock = Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}


def _key(name: str, labels: dict[str, str] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
    labs = tuple(sorted((labels or {}).items()))
    return (name, labs)


def inc_counter(name: str, *, by: float = 1.0, labels: dict[str, str] | None = None) -> None:
    with _lock:
        _counters[_key(name, labels)] = _counters.get(_key(name, labels), 0.0) + by


def set_gauge(name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
    with _lock:
        _gauges[_key(name, labels)] = value


def reset_for_tests() -> None:
    with _lock:
        _counters.clear()
        _gauges.clear()


def render_text() -> str:
    lines: list[str] = []
    with _lock:
        for (name, labs), value in _counters.items():
            lines.append(f"# TYPE {name} counter")
            lines.append(_fmt_sample(name, labs, value))
        for (name, labs), value in _gauges.items():
            lines.append(f"# TYPE {name} gauge")
            lines.append(_fmt_sample(name, labs, value))
    return "\n".join(_dedupe_types(lines)) + "\n"


def _fmt_sample(name: str, labs: tuple[tuple[str, str], ...], value: float) -> str:
    if not labs:
        return f"{name} {value}"
    rendered = ",".join(f'{k}="{_escape(v)}"' for k, v in labs)
    return f"{name}{{{rendered}}} {value}"


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _dedupe_types(lines: list[str]) -> Iterator[str]:
    seen: set[str] = set()
    for line in lines:
        if line.startswith("# TYPE "):
            if line in seen:
                continue
            seen.add(line)
        yield line
