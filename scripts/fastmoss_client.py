#!/usr/bin/env python3
"""FastMoss product lookup helpers used by the H launcher."""

from __future__ import annotations

import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


FASTMOSS_BASE_URL = "https://openapi.fastmoss.com"
FASTMOSS_PRODUCT_PATH = "/product/v1/search"
MAX_PIDS_PER_REQUEST = 100
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 25 * 1024 * 1024
PID_RE = re.compile(r"^[0-9]+$")
TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
PRODUCT_FIELDS = (
    "product_id",
    "title",
    "cover",
    "region",
    "currency",
    "category",
    "price",
    "commission_rate",
    "product_rating",
    "creator_count",
    "video_count",
    "day7_units_sold",
    "day28_units_sold",
    "day90_units_sold",
    "total_units_sold",
    "day7_gmv",
    "day28_gmv",
    "day90_gmv",
    "total_gmv",
    "tiktok_url",
    "fastmoss_url",
    "shop",
)
SECRET_FIELD_TOKENS = ("authorization", "api_key", "apikey", "access_token", "secret")


class FastMossError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str,
        code: int | str = "",
        request_id: str = "",
        http_status: int = 0,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.code = code
        self.request_id = request_id
        self.http_status = http_status

    def as_dict(self) -> dict[str, object]:
        return {
            "error_category": self.category,
            "error_code": self.code,
            "request_id": self.request_id,
            "http_status": self.http_status,
            "error": str(self),
        }


def normalize_pids(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        parts = [part for part in re.split(r"[\s,，]+", str(value).strip()) if part]
        for pid in parts:
            if not PID_RE.fullmatch(pid):
                raise FastMossError(
                    f"PID must contain digits only: {pid}",
                    category="validation",
                )
            if len(pid) > 64:
                raise FastMossError("PID is too long.", category="validation")
            if pid not in seen:
                seen.add(pid)
                normalized.append(pid)
    if not normalized:
        raise FastMossError("At least one PID is required.", category="validation")
    if len(normalized) > MAX_PIDS_PER_REQUEST:
        raise FastMossError(
            f"One FastMoss request supports at most {MAX_PIDS_PER_REQUEST} PIDs.",
            category="validation",
        )
    return normalized


def _business_category(code: int) -> str:
    return {
        10001: "validation",
        20001: "not_found",
        30001: "permission",
        30002: "validation",
        30003: "quota",
        40001: "provider",
    }.get(code, "provider")


def _http_category(status: int) -> str:
    if status in {401, 403}:
        return "authentication"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "provider"
    return "network"


def _redact_text(value: object, secret: str) -> str:
    text = str(value or "")
    return text.replace(secret, "[REDACTED]") if secret else text


def _redact_value(value: Any, secret: str) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for field, item in value.items():
            field_name = str(field)
            if any(token in field_name.lower() for token in SECRET_FIELD_TOKENS):
                cleaned[field_name] = "[REDACTED]"
            else:
                cleaned[field_name] = _redact_value(item, secret)
        return cleaned
    if isinstance(value, list):
        return [_redact_value(item, secret) for item in value]
    if isinstance(value, str):
        return _redact_text(value, secret)
    return value


def _default_post(url: str, **kwargs: Any) -> Any:
    try:
        import requests
    except ImportError as exc:
        raise FastMossError(
            "The requests dependency is not installed.",
            category="runtime",
        ) from exc
    try:
        return requests.post(url, **kwargs)
    except requests.RequestException as exc:
        raise FastMossError(
            f"FastMoss network request failed: {exc}",
            category="network",
        ) from exc


def _default_get(url: str, **kwargs: Any) -> Any:
    try:
        import requests
    except ImportError as exc:
        raise FastMossError(
            "The requests dependency is not installed.",
            category="runtime",
        ) from exc
    try:
        return requests.get(url, **kwargs)
    except requests.RequestException as exc:
        raise FastMossError(
            f"Product cover download failed: {exc}",
            category="network",
        ) from exc


def query_products(
    pids: list[str],
    api_key: str,
    *,
    base_url: str = FASTMOSS_BASE_URL,
    timeout: int = 60,
    attempts: int = 3,
    post: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    pids = normalize_pids(pids)
    key = "".join(character for character in api_key.strip().lstrip("\ufeff") if character.isprintable() and not character.isspace())
    if not key:
        raise FastMossError("FastMoss API key is missing.", category="authentication")
    request_body = {
        "filter": {"product_id": pids[0] if len(pids) == 1 else pids},
        "page": 1,
        "pagesize": len(pids),
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "H-Codex-Plugin/0.4",
    }
    post_request = post or _default_post
    last_error: FastMossError | None = None
    for attempt in range(max(1, min(attempts, 5))):
        try:
            response = post_request(
                f"{base_url.rstrip('/')}{FASTMOSS_PRODUCT_PATH}",
                headers=headers,
                json=request_body,
                timeout=(10, max(10, min(timeout, 300))),
                allow_redirects=False,
            )
        except FastMossError as exc:
            last_error = exc
            if exc.category != "network" or attempt + 1 >= attempts:
                raise
            sleep(float(2**attempt))
            continue
        except Exception as exc:
            last_error = FastMossError(
                f"FastMoss network request failed: {exc}",
                category="network",
            )
            if attempt + 1 >= attempts:
                raise last_error from exc
            sleep(float(2**attempt))
            continue

        status = int(getattr(response, "status_code", 0) or 0)
        content = bytes(getattr(response, "content", b"") or b"")
        close = getattr(response, "close", None)
        if callable(close):
            close()
        if len(content) > MAX_RESPONSE_BYTES:
            raise FastMossError("FastMoss response was unexpectedly large.", category="provider", http_status=status)
        try:
            payload = response.json()
        except Exception as exc:
            preview = _redact_text(content[:300].decode("utf-8", errors="replace"), key)
            error = FastMossError(
                f"FastMoss returned invalid JSON: {preview}",
                category=_http_category(status),
                http_status=status,
            )
            if status in TRANSIENT_HTTP_STATUSES and attempt + 1 < attempts:
                last_error = error
                sleep(float(2**attempt))
                continue
            raise error from exc
        if not isinstance(payload, dict):
            raise FastMossError(
                "FastMoss returned a non-object JSON response.",
                category="provider",
                http_status=status,
            )
        payload = _redact_value(payload, key)
        request_id = str(payload.get("request_id") or "")
        message = str(payload.get("msg") or payload.get("message") or "FastMoss request failed")
        if status != 200:
            error = FastMossError(
                f"FastMoss HTTP {status}: {message}",
                category=_http_category(status),
                request_id=request_id,
                http_status=status,
            )
            if status in TRANSIENT_HTTP_STATUSES and attempt + 1 < attempts:
                last_error = error
                sleep(float(2**attempt))
                continue
            raise error
        try:
            code = int(payload.get("code", -1))
        except (TypeError, ValueError):
            code = -1
        if code != 0:
            error = FastMossError(
                f"FastMoss {code}: {message}",
                category=_business_category(code),
                code=code,
                request_id=request_id,
                http_status=status,
            )
            if code == 40001 and attempt + 1 < attempts:
                last_error = error
                sleep(float(2**attempt))
                continue
            raise error
        data = payload.get("data")
        products = data.get("list") if isinstance(data, dict) else None
        if not isinstance(products, list):
            raise FastMossError(
                "FastMoss response is missing data.list.",
                category="provider",
                request_id=request_id,
                http_status=status,
            )
        return {
            "pids": pids,
            "request": request_body,
            "request_id": request_id,
            "timestamp": payload.get("timestamp"),
            "total": data.get("total", len(products)),
            "products": [item for item in products if isinstance(item, dict)],
            "raw": payload,
        }
    if last_error:
        raise last_error
    raise FastMossError("FastMoss request failed.", category="network")


def _response_product_id(value: object) -> str:
    if isinstance(value, str) and PID_RE.fullmatch(value):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    return ""


def normalize_product(product: dict[str, Any], requested_pid: str) -> dict[str, Any]:
    normalized = {field: product.get(field) for field in PRODUCT_FIELDS}
    normalized["product_id"] = _response_product_id(product.get("product_id")) or requested_pid
    return normalized


def _image_extension(header: bytes) -> str:
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    if header.startswith(b"BM"):
        return ".bmp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        if header[8:12] in {b"avif", b"avis"}:
            return ".avif"
        if header[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
            return ".heic"
    return ""


def validate_local_reference_image(path: Path) -> tuple[Path, str]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise FastMossError(
            f"Uploaded reference image does not exist: {source}",
            category="validation",
        )
    size = source.stat().st_size
    if size <= 0 or size > MAX_IMAGE_BYTES:
        raise FastMossError(
            f"Uploaded reference image must be between 1 byte and 25 MB: {source}",
            category="validation",
        )
    with source.open("rb") as handle:
        extension = _image_extension(handle.read(32))
    if not extension:
        raise FastMossError(
            f"Uploaded reference is not a supported image: {source}",
            category="validation",
        )
    return source, extension


def copy_local_reference_image(source: Path, product_dir: Path, pid: str) -> str:
    source, extension = validate_local_reference_image(source)
    product_dir.mkdir(parents=True, exist_ok=True)
    destination = product_dir / f"{pid}{extension}"
    if source != destination.resolve():
        temporary = product_dir / f".{pid}.upload.part"
        try:
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return str(destination)


def download_product_cover(
    url: str,
    product_dir: Path,
    pid: str,
    *,
    get: Callable[..., Any] | None = None,
) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FastMossError("FastMoss returned an invalid product cover URL.", category="provider")
    get_request = get or _default_get
    response = get_request(
        url,
        headers={"Accept": "image/*", "User-Agent": "H-Codex-Plugin/0.4"},
        timeout=(10, 90),
        allow_redirects=True,
        stream=True,
    )
    try:
        status = int(getattr(response, "status_code", 0) or 0)
        if status != 200:
            raise FastMossError(
                f"Product cover download returned HTTP {status}.",
                category=_http_category(status),
                http_status=status,
            )
        declared_length = str(getattr(response, "headers", {}).get("Content-Length") or "")
        if declared_length.isdigit() and int(declared_length) > MAX_IMAGE_BYTES:
            raise FastMossError("Product cover exceeds the 25 MB limit.", category="validation")
        product_dir.mkdir(parents=True, exist_ok=True)
        temporary = product_dir / f".{pid}.cover.part"
        total = 0
        header = b""
        try:
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise FastMossError("Product cover exceeds the 25 MB limit.", category="validation")
                    if len(header) < 32:
                        header += chunk[: 32 - len(header)]
                    handle.write(chunk)
            extension = _image_extension(header)
            if not extension:
                raise FastMossError("FastMoss cover URL did not return a supported image.", category="invalid_result")
            destination = product_dir / f"{pid}{extension}"
            temporary.replace(destination)
            return str(destination)
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def save_product_results(
    query: dict[str, Any],
    work_dir: Path,
    *,
    download_images: bool = True,
    reference_images: dict[str, Path] | None = None,
    get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    work_dir = work_dir.expanduser().resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = work_dir / f"PID_{stamp}"
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"fastmoss-product-{stamp}.json"
    raw_path.write_text(
        json.dumps(query["raw"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    by_pid: dict[str, dict[str, Any]] = {}
    for item in query["products"]:
        product_id = _response_product_id(item.get("product_id"))
        if product_id and product_id not in by_pid:
            by_pid[product_id] = item
    results: list[dict[str, Any]] = []
    reference_images = reference_images or {}
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for pid in query["pids"]:
        item = by_pid.get(pid)
        if item is None:
            results.append({"pid": pid, "state": "not_found", "product": None, "product_file": ""})
            continue
        product = normalize_product(item, pid)
        product_dir = run_dir / pid
        product_dir.mkdir(parents=True, exist_ok=True)
        product_path = product_dir / "fastmoss-product.json"
        product_path.write_text(
            json.dumps(
                {
                    "source": "FastMoss",
                    "fetched_at": fetched_at,
                    "request_id": query["request_id"],
                    "product": product,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        title_path = product_dir / "product-title.txt"
        title_path.write_text(str(product.get("title") or "").strip() + "\n", encoding="utf-8")
        results.append(
            {
                "pid": pid,
                "state": "success",
                "product": product,
                "reference_image": "",
                "reference_source": "",
                "cover_url": str(product.get("cover") or ""),
                "cover_error": "",
                "title_file": str(title_path),
                "product_file": str(product_path),
            }
        )
    for item in results:
        pid = str(item["pid"])
        supplied_image = reference_images.get(pid)
        if item["state"] != "success" or supplied_image is None:
            continue
        try:
            item["reference_image"] = copy_local_reference_image(
                supplied_image,
                run_dir / pid,
                pid,
            )
            item["reference_source"] = "user-upload"
        except Exception as exc:
            item["state"] = "partial"
            item["cover_error"] = str(exc)[:500]
    downloadable = [
        item
        for item in results
        if item["state"] == "success" and not item.get("reference_image") and item.get("cover_url")
    ]
    if download_images and downloadable:
        workers = min(8, len(downloadable))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    download_product_cover,
                    str(item["cover_url"]),
                    run_dir / str(item["pid"]),
                    str(item["pid"]),
                    get=get,
                ): item
                for item in downloadable
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    item["reference_image"] = future.result()
                    item["reference_source"] = "fastmoss-cover"
                except Exception as exc:
                    item["state"] = "partial"
                    item["cover_error"] = str(exc)[:500]
    return {
        "work_dir": str(work_dir),
        "generation_root": str(run_dir),
        "raw_response": str(raw_path),
        "request_id": query["request_id"],
        "requested": len(query["pids"]),
        "success": sum(item["state"] in {"success", "partial"} for item in results),
        "ready_for_generation": sum(item["state"] == "success" and bool(item.get("reference_image")) for item in results),
        "partial": sum(item["state"] == "partial" for item in results),
        "not_found": sum(item["state"] == "not_found" for item in results),
        "results": results,
    }
