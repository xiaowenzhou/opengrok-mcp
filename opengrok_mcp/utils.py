import json
import re
from typing import Any, Dict, List, Optional


TAG_PATTERN = re.compile(r"<[^>]+>")


def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(value, max_value))


def normalize_path(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        raise ValueError("path must not be empty")
    return normalized


def clean_html(text: str) -> str:
    return TAG_PATTERN.sub("", text)


def normalize_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip().lstrip("/")
    if not normalized:
        raise ValueError("endpoint must not be empty")
    return normalized


def build_cache_key(
    endpoint: str,
    params: Optional[Dict[str, Any]],
    headers: Optional[Dict[str, str]],
) -> str:
    params_items = tuple(sorted((key, str(value)) for key, value in (params or {}).items()))
    headers_items = tuple(
        sorted((key.lower(), str(value)) for key, value in (headers or {}).items())
    )
    return json.dumps(
        (endpoint, params_items, headers_items),
        ensure_ascii=True,
        separators=(",", ":"),
    )


def format_hits(
    file_path: str,
    hits: List[Dict[str, Any]],
    max_hits: Optional[int] = None,
    line_limit: int = 240,
) -> List[str]:
    output = [f"**File: `{file_path}`**"]
    displayed = hits if max_hits is None else hits[:max_hits]

    for hit in displayed:
        line_number = hit.get("lineNumber", "?")
        tag = str(hit.get("tag", "")).strip()
        line_text = clean_html(str(hit.get("line", "")).strip())
        if len(line_text) > line_limit:
            line_text = f"{line_text[:line_limit]}..."
        if tag:
            output.append(f"- Line {line_number} ({tag}): `{line_text}`")
        else:
            output.append(f"- Line {line_number}: `{line_text}`")

    if max_hits is not None and len(hits) > max_hits:
        output.append(f"- ... and {len(hits) - max_hits} more matches")

    output.append("")
    return output
