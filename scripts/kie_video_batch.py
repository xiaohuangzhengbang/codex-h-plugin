#!/usr/bin/env python
"""Two-stage Kie product workflow.

Stage 1: process PID-named product images into cleaned/enhanced product images.
Stage 2: generate PID-named videos from the processed product images.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


KIE_API_HOST = "https://api.kie.ai"
KIE_FILE_HOST = "https://kieai.redpandaai.co"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LOCAL_API_KEY_FILE = PLUGIN_ROOT / ".h_api_key"
USER_API_KEY_FILE = Path.home() / ".codex" / "secrets" / "h_kie_api_key.txt"
_PROXY_CACHE: dict[str, str] | None = None
_SESSION_LOCAL = threading.local()
TRANSIENT_HTTP_STATUSES = {429, 455, 500, 502, 503, 504}
RESUMABLE_STATES = {"submitted", "waiting", "queueing", "generating", "timeout"}

IMAGE_MODEL_PAYLOADS = {
    "gpt-image-2-text-to-image": "",
    "gpt-image-2-image-to-image": "input_urls",
    "google/nano-banana": "",
    "google/nano-banana-edit": "image_urls",
    "nano-banana-2": "image_input",
    "nano-banana-2-lite": "image_urls",
    "nano-banana-pro": "image_input",
    "seedream/5-lite-text-to-image": "",
    "seedream/5-lite-image-to-image": "image_urls",
}

# Kie model input limits from each model's current OpenAPI schema. Family IDs
# are included because single mode resolves them to text/image endpoints after
# checking whether reference images were supplied.
IMAGE_MODEL_REFERENCE_LIMITS = {
    "gpt-image-2": 16,
    "gpt-image-2-text-to-image": 0,
    "gpt-image-2-image-to-image": 16,
    "google/nano-banana": 10,
    "google/nano-banana-edit": 10,
    "nano-banana-pro": 8,
    "nano-banana-2": 14,
    "nano-banana-2-lite": 10,
    "seedream/5-lite": 14,
    "seedream/5-lite-text-to-image": 0,
    "seedream/5-lite-image-to-image": 14,
}

IMAGE_MODELS_REQUIRING_REFERENCES = {
    "gpt-image-2-image-to-image",
    "google/nano-banana-edit",
    "seedream/5-lite-image-to-image",
}

IMAGE_MODEL_CHOICES = {
    "1": ("GPT Image-2", "gpt-image-2"),
    "2": ("Nano Banana", "google/nano-banana"),
    "3": ("Nano Banana Pro", "nano-banana-pro"),
    "4": ("Nano Banana 2", "nano-banana-2"),
    "5": ("Nano Banana 2 Lite", "nano-banana-2-lite"),
    "6": ("Seedream 5.0 Lite", "seedream/5-lite"),
}

VIDEO_MODEL_CHOICES = {
    "1": ("Grok Imagine", "grok-imagine"),
    "2": ("Grok Imagine Video 1.5 Preview", "grok-imagine-video-1-5-preview"),
    "3": ("Veo3.1 Lite", "veo3.1-lite"),
    "4": ("Veo3.1 Fast", "veo3.1-fast"),
    "5": ("Veo3.1 Quality", "veo3.1-quality"),
    "6": ("Gemini Omni Video", "gemini-omni-video"),
    "7": ("Seedance 2.0", "bytedance/seedance-2"),
    "8": ("Seedance 2.0 Fast", "bytedance/seedance-2-fast"),
    "9": ("Seedance 2.0 Mini", "bytedance/seedance-2-mini"),
    "10": ("Grok Imagine Video Upscale", "grok-imagine/upscale"),
    "11": ("Grok Imagine Video Extend", "grok-imagine/extend"),
}

VIDEO_TRANSFORM_MODELS = {"grok-imagine/upscale", "grok-imagine/extend"}

VIDEO_MODEL_MAX_SECONDS = {
    "grok-imagine": 30,
    "grok-imagine/text-to-video": 30,
    "grok-imagine/image-to-video": 30,
    "grok-imagine-video-1-5-preview": 15,
    "veo3.1-lite": 8,
    "veo3.1-fast": 8,
    "veo3.1-quality": 8,
    "gemini-omni-video": None,
    "bytedance/seedance-2": 15,
    "bytedance/seedance-2-fast": 15,
    "bytedance/seedance-2-mini": 15,
    "grok-imagine/upscale": None,
    "grok-imagine/extend": None,
}
VEO_FIXED_SECONDS = 8
VIDEO_DURATION_CHOICES = [4, 6, 8, 10, 15, 20, 25, 30]

ASPECT_RATIO_CHOICES = {
    "1": "9:16",
    "2": "16:9",
}

IMAGE_RESOLUTION_CHOICES = {
    "1": "1K",
    "2": "2K",
    "3": "4K",
}

VEO_MODEL_MAP = {
    "veo3.1-lite": "veo3_lite",
    "veo3.1-fast": "veo3_fast",
    "veo3.1-quality": "veo3",
}

REVERSE_MODEL_CHOICES = {
    "1": "gpt-5-5",
    "2": "gpt-5-4",
    "3": "gemini-3.1-pro",
    "4": "gemini-3-pro",
    "5": "gemini-3-5-flash-openai",
    "6": "gemini-3-flash",
    "gpt-5-5": "gpt-5-5",
    "gpt-5-4": "gpt-5-4",
    "gemini-3.1-pro": "gemini-3.1-pro",
    "gemini-3-pro": "gemini-3-pro",
    "gemini-3.5-flash": "gemini-3-5-flash-openai",
    "gemini-3-flash": "gemini-3-flash",
}

TEXT_MODEL_CHOICES = {
    "1": ("GPT 5.5 Response", "gpt-5-5"),
    "2": ("GPT 5.4 Response", "gpt-5-4"),
    "3": ("Gemini 3.1 Pro", "gemini-3.1-pro"),
    "4": ("Gemini 3 Pro", "gemini-3-pro"),
    "5": ("Gemini 3.5 Flash", "gemini-3-5-flash-openai"),
    "6": ("Gemini 3 Flash", "gemini-3-flash"),
}


class KieAPIError(RuntimeError):
    def __init__(
        self,
        category: str,
        message: str,
        *,
        status: int | None = None,
        resumable: bool | None = None,
    ) -> None:
        self.category = category
        self.status = status
        self.resumable = resumable
        super().__init__(f"[{category}] {message}")


def configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def print_json(value: Any) -> None:
    configure_utf8_output()
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    try:
        print(payload, flush=True)
    except UnicodeEncodeError:
        print(json.dumps(value, ensure_ascii=True, indent=2), flush=True)


@dataclass
class ProductImage:
    pid: str
    path: Path


@dataclass
class ProductFolder:
    name: str
    path: Path
    images: list[ProductImage]
    relative_path: Path = Path(".")

    @property
    def output_path(self) -> Path:
        if self.relative_path == Path("."):
            return Path(sanitize_filename(self.name))
        return Path(*(sanitize_filename(part) for part in self.relative_path.parts))


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "product"


def pid_from_path(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"(_processed|_product|_edited|_clean)$", "", stem, flags=re.I)
    return sanitize_filename(stem)


def collect_images(folder: Path) -> list[ProductImage]:
    images: list[ProductImage] = []
    seen: dict[str, Path] = {}
    for item in sorted(folder.iterdir(), key=lambda path: path.name.lower()):
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
            pid = pid_from_path(item)
            if pid in seen:
                raise ValueError(f"Duplicate PID '{pid}' in {folder}: {seen[pid].name} and {item.name}")
            seen[pid] = item
            images.append(ProductImage(pid, item))
    return images


def iter_image_directories(input_dir: Path, *, processed: bool) -> list[Path]:
    skipped = {"videos", "__pycache__", ".git", ".h_venv", "文本", "视频"}
    if not processed:
        skipped.update({"processed_products", "图像"})
    directories: list[Path] = []
    for current, child_names, _file_names in os.walk(input_dir, followlinks=False):
        child_names[:] = sorted(
            [
                name
                for name in child_names
                if name.lower() not in skipped and not name.startswith(".")
            ],
            key=str.lower,
        )
        folder = Path(current)
        if folder.is_symlink():
            child_names[:] = []
            continue
        directories.append(folder)
    return directories


def product_folder_for(input_dir: Path, folder: Path, images: list[ProductImage]) -> ProductFolder:
    relative = folder.relative_to(input_dir)
    if relative == Path("."):
        name = input_dir.name
    else:
        name = relative.as_posix()
    return ProductFolder(sanitize_filename(name), folder, images, relative)


def discover_product_folders(input_dir: Path) -> list[ProductFolder]:
    input_dir = input_dir.resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(str(input_dir))

    folders: list[ProductFolder] = []
    for folder in iter_image_directories(input_dir, processed=False):
        images = collect_images(folder)
        if images:
            folders.append(product_folder_for(input_dir, folder, images))

    return folders


def discover_processed_folders(input_dir: Path) -> list[ProductFolder]:
    input_dir = input_dir.resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(str(input_dir))

    folders: list[ProductFolder] = []
    for folder in iter_image_directories(input_dir, processed=True):
        images = collect_images(folder)
        if images:
            record = product_folder_for(input_dir, folder, images)
            if folder.name.lower() == "processed_products":
                parent_relative = folder.parent.relative_to(input_dir)
                record = ProductFolder(
                    sanitize_filename(folder.parent.name),
                    folder,
                    images,
                    parent_relative,
                )
            folders.append(record)

    return folders


def desktop_dir() -> Path:
    if os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "Desktop")
                if value:
                    return Path(os.path.expandvars(str(value))).expanduser()
        except (OSError, ImportError):
            pass
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    return Path.home() / "Desktop"


def default_output_root(input_dir: Path) -> Path:
    return desktop_dir() / f"H返回结果_{sanitize_filename(input_dir.resolve().name)}"


def output_root(args: argparse.Namespace, input_dir: Path) -> Path:
    return Path(args.output_dir).resolve() if args.output_dir else default_output_root(input_dir)


def process_output_dir(args: argparse.Namespace, source_root: Path, folder: ProductFolder, multi_folder: bool) -> Path:
    base = output_root(args, source_root) / "图像"
    return base / folder.output_path if multi_folder else base


def process_text_output_dir(args: argparse.Namespace, source_root: Path, folder: ProductFolder, multi_folder: bool) -> Path:
    base = output_root(args, source_root) / "文本"
    return base / folder.output_path if multi_folder else base


def video_output_dir(args: argparse.Namespace, source_root: Path, folder: ProductFolder, multi_folder: bool) -> Path:
    base = output_root(args, source_root) / "视频"
    return base / folder.output_path if multi_folder else base


def video_text_output_dir(args: argparse.Namespace, source_root: Path, folder: ProductFolder, multi_folder: bool) -> Path:
    base = output_root(args, source_root) / "文本"
    return base / folder.output_path if multi_folder else base


def clean_api_key(api_key: str) -> str:
    value = (api_key or "").strip().lstrip("\ufeff")
    return "".join(
        ch
        for ch in value
        if ch.isprintable()
        and not ch.isspace()
        and ch not in {"\ufeff", "\u200b", "\u200c", "\u200d", "\u2060"}
    )


def get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {clean_api_key(api_key)}",
        "Content-Type": "application/json",
    }


def new_session() -> requests.Session:
    cached = getattr(_SESSION_LOCAL, "session", None)
    if isinstance(cached, requests.Session):
        return cached
    session = requests.Session()
    session.trust_env = True
    session.verify = True
    proxies = configured_proxies()
    if proxies:
        session.proxies.update(proxies)
    retry = requests.adapters.Retry(total=0)
    adapter = requests.adapters.HTTPAdapter(
        max_retries=retry,
        pool_connections=64,
        pool_maxsize=64,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    _SESSION_LOCAL.session = session
    return session


def normalize_proxy_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    return value


def parse_proxy_server(value: str) -> dict[str, str]:
    value = (value or "").strip()
    if not value:
        return {}
    if "=" not in value:
        proxy = normalize_proxy_url(value)
        return {"http": proxy, "https": proxy} if proxy else {}
    parsed: dict[str, str] = {}
    for part in value.split(";"):
        if "=" not in part:
            continue
        scheme, proxy = part.split("=", 1)
        scheme = scheme.strip().lower()
        proxy = normalize_proxy_url(proxy)
        if scheme in {"http", "https"} and proxy:
            parsed[scheme] = proxy
    if "https" not in parsed and "http" in parsed:
        parsed["https"] = parsed["http"]
    if "http" not in parsed and "https" in parsed:
        parsed["http"] = parsed["https"]
    return parsed


def windows_user_proxy() -> dict[str, str]:
    if os.name != "nt":
        return {}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return {}
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            return parse_proxy_server(str(server))
    except Exception:
        return {}


def configured_proxies() -> dict[str, str]:
    global _PROXY_CACHE
    if _PROXY_CACHE is not None:
        return _PROXY_CACHE
    env_https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    env_http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or ""
    proxies: dict[str, str] = {}
    if env_http:
        proxies["http"] = normalize_proxy_url(env_http)
    if env_https:
        proxies["https"] = normalize_proxy_url(env_https)
    if not proxies:
        proxies = windows_user_proxy()
    _PROXY_CACHE = proxies
    return proxies


def upload_file(api_key: str, path: Path) -> str:
    with path.open("rb") as file_obj:
        response = request_with_retry(
            "POST",
            f"{KIE_FILE_HOST}/api/file-stream-upload",
                    headers={"Authorization": f"Bearer {clean_api_key(api_key)}"},
            data={"uploadPath": "codex-kie-product-video", "fileName": path.name},
            files={"file": (path.name, file_obj)},
            timeout=120,
            attempts=5,
            base_delay=2,
        )
    raise_for_kie_status(response, "file upload")
    data = response_json(response, "file upload")
    if data.get("success") and data.get("data", {}).get("downloadUrl"):
        return data["data"]["downloadUrl"]
    raise KieAPIError("upload", str(data.get("message") or data.get("msg") or f"Upload failed: {path}"))



def describe_secret(value: str) -> str:
    value = clean_api_key(value)
    if not value:
        return "empty"
    fingerprint = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"sha256={fingerprint}"


def choose_secret(candidates: list[tuple[str, str]], label: str) -> str:
    seen: list[tuple[str, str]] = []
    for name, candidate in candidates:
        value = clean_api_key(candidate)
        if value:
            seen.append((name, value))
    if not seen:
        return ""
    chosen_name, chosen = seen[0]
    if len({value for _name, value in seen}) > 1:
        sources = ", ".join(f"{name}:{describe_secret(value)}" for name, value in seen)
        print(f"{label} key sources differ; using {chosen_name} ({describe_secret(chosen)}). Sources: {sources}", flush=True)
    return chosen


def response_output_text(data: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in data.get("output", []) or []:
        if isinstance(item, dict):
            for content in item.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") == "output_text" and content.get("text"):
                    texts.append(str(content["text"]))
    if texts:
        return "\n".join(texts).strip()
    if data.get("output_text"):
        return str(data["output_text"]).strip()
    for choice in data.get("choices", []) or []:
        if not isinstance(choice, dict):
            continue
        content = (choice.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            texts.append(content.strip())
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]).strip())
    for candidate in data.get("candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            if isinstance(part, dict) and part.get("text"):
                texts.append(str(part["text"]).strip())
    if texts:
        return "\n".join(text for text in texts if text).strip()
    return ""


def normalize_reverse_model(value: str) -> str:
    model = value.strip().strip("/")
    return REVERSE_MODEL_CHOICES.get(model, model)


def resolve_text_model(value: str) -> tuple[str, str]:
    if value in TEXT_MODEL_CHOICES:
        return TEXT_MODEL_CHOICES[value]
    normalized = normalize_reverse_model(value)
    for label, model in TEXT_MODEL_CHOICES.values():
        if normalized == model or value.lower() == label.lower():
            return label, model
    raise ValueError(f"Unsupported text model choice: {value}")


def text_request_payload(model: str, prompt: str, media_urls: list[str], reasoning_effort: str) -> tuple[str, dict[str, Any]]:
    if model in {"gpt-5-4", "gpt-5-5"}:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        content.extend({"type": "input_image", "image_url": url} for url in media_urls)
        return "/codex/v1/responses", {
            "model": model,
            "stream": False,
            "reasoning": {"effort": reasoning_effort},
            "input": [{"role": "user", "content": content}],
        }
    content = [{"type": "text", "text": prompt}]
    content.extend({"type": "image_url", "image_url": {"url": url}} for url in media_urls)
    return f"/{model}/v1/chat/completions", {
        "stream": False,
        "reasoning_effort": reasoning_effort,
        "messages": [{"role": "user", "content": content}],
    }


def text_with_kie(
    api_key: str,
    model: str,
    prompt: str,
    media_urls: list[str] | None = None,
    *,
    base_url: str = KIE_API_HOST,
    timeout: int = 180,
    reasoning_effort: str = "high",
) -> tuple[str, dict[str, Any]]:
    selected = normalize_reverse_model(model)
    candidates = [selected, "gpt-5-4"] if selected == "gpt-5-5" else [selected]
    last_error: Exception | None = None
    last_data: dict[str, Any] = {}
    for index, candidate in enumerate(candidates):
        endpoint_path, payload = text_request_payload(candidate, prompt, media_urls or [], reasoning_effort)
        endpoint = f"{base_url.rstrip('/')}{endpoint_path}"
        try:
            for empty_attempt in range(2):
                response = request_with_retry(
                    "POST",
                    endpoint,
                    headers=get_headers(api_key),
                    json=payload,
                    timeout=timeout,
                    attempts=3,
                    base_delay=2,
                )
                raise_for_kie_status(response, f"text model {candidate}")
                data = response_json(response, f"text model {candidate}")
                raise_for_kie_code(data, f"text model {candidate}")
                last_data = data
                content = response_output_text(data)
                if content:
                    result = dict(data)
                    result["_h_meta"] = {
                        "requested_model": selected,
                        "actual_model": candidate,
                        "fallback_used": candidate != selected,
                    }
                    return content, result
                if empty_attempt == 0:
                    time.sleep(1)
            raise KieAPIError("invalid_response", f"text model {candidate} returned no text")
        except KieAPIError as exc:
            last_error = exc
            can_fallback = index + 1 < len(candidates) and exc.category in {
                "provider",
                "maintenance",
                "rate_limit",
                "feature_disabled",
                "invalid_response",
                "network",
            }
            if not can_fallback:
                raise
            print(f"{candidate} temporarily unavailable; falling back to {candidates[index + 1]}: {exc}", flush=True)
    if last_error:
        raise last_error
    raise KieAPIError("invalid_response", f"text generation returned no content: {last_data}")


def reverse_prompt_with_kie(args: argparse.Namespace, pid: str, image_url: str, meta_prompt_template: str) -> tuple[str, dict[str, Any]]:
    meta_prompt = meta_prompt_template.format(pid=pid, product_id=pid)
    return text_with_kie(
        args.api_key,
        args.reverse_model,
        meta_prompt,
        [image_url],
        base_url=args.reverse_base_url or KIE_API_HOST,
        timeout=args.reverse_timeout,
        reasoning_effort=args.reverse_reasoning_effort,
    )


def build_kie_image_prompt(reverse_prompt: str, pid: str, extra_prompt: str) -> str:
    parts = [reverse_prompt.strip()]
    if extra_prompt.strip():
        parts.append(render_prompt(extra_prompt, pid))
    parts.append(f"PID: {pid}. Use the uploaded product image as the visual reference. Keep the product identity accurate.")
    return "\n\n".join(part for part in parts if part)


def build_kie_video_prompt(reverse_prompt: str, pid: str, extra_prompt: str) -> str:
    parts = [reverse_prompt.strip()]
    if extra_prompt.strip():
        parts.append(render_prompt(extra_prompt, pid))
    parts.append(f"PID: {pid}. Use the uploaded processed product image as the visual reference. Keep the product identity accurate.")
    return "\n\n".join(part for part in parts if part)


def resolve_workers(requested: int, item_count: int) -> int:
    if item_count <= 0:
        return 1
    if requested and requested > 0:
        return max(1, min(requested, item_count))
    return max(1, min(item_count, 64))


def assert_kie_reachable(args: argparse.Namespace) -> None:
    if getattr(args, "skip_preflight", False):
        return
    credits = check_kie_account(args.api_key, timeout=args.preflight_timeout)
    print(f"Kie preflight passed; available credits: {credits}", flush=True)


def kie_error_category(status: int | None) -> str:
    if status == 401:
        return "authentication"
    if status == 403:
        return "authorization"
    if status == 402:
        return "quota"
    if status in {400, 422}:
        return "validation"
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status == 429:
        return "rate_limit"
    if status in {455, 503}:
        return "maintenance"
    if status == 505:
        return "feature_disabled"
    if status is not None and status >= 500:
        return "provider"
    return "request"


def response_message(response: requests.Response) -> str:
    body = response.text.strip()[:1200]
    if not body:
        return response.reason or f"HTTP {response.status_code}"
    try:
        data = response.json()
    except (ValueError, requests.JSONDecodeError):
        return body
    if isinstance(data, dict):
        return str(data.get("msg") or data.get("message") or data.get("error") or body)
    return body


def response_json(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        data = response.json()
    except (ValueError, requests.JSONDecodeError) as exc:
        raise KieAPIError("invalid_response", f"{operation} returned non-JSON data: {response.text[:500]}") from exc
    if not isinstance(data, dict):
        raise KieAPIError("invalid_response", f"{operation} returned a non-object JSON response")
    return data


def raise_for_kie_status(response: requests.Response, operation: str) -> None:
    if response.status_code < 400:
        return
    category = kie_error_category(response.status_code)
    raise KieAPIError(
        category,
        f"{operation} failed with HTTP {response.status_code}: {response_message(response)}",
        status=response.status_code,
    )


def raise_for_kie_code(data: dict[str, Any], operation: str) -> None:
    raw_code = data.get("code")
    if raw_code in {None, 200, "200"}:
        return
    try:
        status = int(raw_code)
    except (TypeError, ValueError):
        status = None
    category = kie_error_category(status)
    message = str(data.get("msg") or data.get("message") or data.get("error") or "unknown Kie error")
    raise KieAPIError(category, f"{operation} failed with Kie code {raw_code}: {message}", status=status)


def check_kie_account(api_key: str, *, timeout: int = 15) -> float:
    response = request_with_retry(
        "GET",
        f"{KIE_API_HOST}/api/v1/chat/credit",
        headers=get_headers(api_key),
        attempts=3,
        base_delay=1,
        timeout=timeout,
    )
    raise_for_kie_status(response, "credit check")
    data = response_json(response, "credit check")
    raise_for_kie_code(data, "credit check")
    try:
        credits = float(data.get("data"))
    except (TypeError, ValueError) as exc:
        raise KieAPIError("invalid_response", f"credit check returned an invalid balance: {data.get('data')!r}") from exc
    if credits <= 0:
        raise KieAPIError("quota", "Kie account has no available credits", status=402)
    return credits


def request_with_retry(method: str, url: str, *, attempts: int = 3, base_delay: float = 2.0, **kwargs: Any) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = new_session().request(method, url, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == attempts:
                break
            delay = min(20.0, base_delay * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
            print(f"Transient request error ({attempt}/{attempts}); retrying in {delay}s: {exc}", flush=True)
            time.sleep(delay)
            continue
        if response.status_code in TRANSIENT_HTTP_STATUSES and attempt < attempts:
            message = response_message(response)
            response.close()
            delay = min(30.0, base_delay * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
            print(
                f"Transient Kie HTTP error ({attempt}/{attempts}); retrying in {delay:.1f}s: "
                f"{response.status_code} {message}",
                flush=True,
            )
            time.sleep(delay)
            continue
        return response
    assert last_exc is not None
    raise KieAPIError("network", f"request failed after {attempts} attempts: {last_exc}") from last_exc


def submit_job(api_key: str, model: str, input_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    submit_attempts = 4
    data: dict[str, Any] = {}
    for attempt in range(1, submit_attempts + 1):
        response = request_with_retry(
            "POST",
            f"{KIE_API_HOST}/api/v1/jobs/createTask",
            headers=get_headers(api_key),
            json={"model": model, "input": input_payload},
            timeout=60,
            attempts=4,
            base_delay=2,
        )
        raise_for_kie_status(response, f"submit {model}")
        data = response_json(response, f"submit {model}")
        if data.get("code") in {200, "200"}:
            break
        message = str(data.get("msg") or data.get("message") or "")
        code = data.get("code")
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = None
        transient = status in TRANSIENT_HTTP_STATUSES or any(
            token in message.lower()
            for token in ["frequency", "too high", "retry later", "rate limit", "overloaded"]
        )
        if transient and attempt < submit_attempts:
            delay = min(30.0, 3 * attempt) + random.uniform(0, 0.5)
            print(f"Kie task submission transient error ({attempt}/{submit_attempts}); retrying in {delay:.1f}s: {message}", flush=True)
            time.sleep(delay)
            continue
        raise_for_kie_code(data, f"submit {model}")
    task_id = data.get("data", {}).get("taskId")
    if not task_id:
        raise RuntimeError("Kie response did not include taskId")
    return task_id, data


def normalize_media_urls(urls: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if not urls:
        return []
    if isinstance(urls, str):
        return [urls] if urls else []
    return [url for url in urls if url]


def veo_input_payload(model: str, prompt: str, image_urls: str | list[str] | tuple[str, ...], aspect_ratio: str, resolution: str) -> dict[str, Any]:
    images = normalize_media_urls(image_urls)
    if len(images) > 3:
        raise ValueError("Veo3.1 supports 0 images for text-to-video, 1-2 images for first/last frames, or 3 reference images; more than 3 images are not supported.")
    if len(images) == 3 and model == "veo3.1-quality":
        raise ValueError("Veo3.1 Quality does not support reference-image mode; choose Veo3.1 Lite or Fast for 3 reference images.")
    payload: dict[str, Any] = {
        "prompt": prompt,
        "model": VEO_MODEL_MAP[model],
        "aspect_ratio": aspect_ratio,
        "enableTranslation": True,
    }
    if not images:
        payload["generationType"] = "TEXT_2_VIDEO"
    elif len(images) <= 2:
        payload["generationType"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
        payload["imageUrls"] = images
    else:
        payload["generationType"] = "REFERENCE_2_VIDEO"
        payload["imageUrls"] = images
    return payload


def submit_veo(api_key: str, model: str, prompt: str, image_urls: str | list[str] | tuple[str, ...], aspect_ratio: str, resolution: str) -> tuple[str, dict[str, Any]]:
    payload = veo_input_payload(model, prompt, image_urls, aspect_ratio, resolution)
    submit_attempts = 4
    data: dict[str, Any] = {}
    for attempt in range(1, submit_attempts + 1):
        response = request_with_retry(
            "POST",
            f"{KIE_API_HOST}/api/v1/veo/generate",
            headers=get_headers(api_key),
            json=payload,
            timeout=60,
            attempts=4,
            base_delay=2,
        )
        raise_for_kie_status(response, f"submit {model}")
        data = response_json(response, f"submit {model}")
        if data.get("code") in {200, "200"}:
            break
        message = str(data.get("msg") or data.get("message") or "")
        code = data.get("code")
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = None
        transient = status in TRANSIENT_HTTP_STATUSES or any(
            token in message.lower()
            for token in ["frequency", "too high", "retry later", "rate limit", "overloaded"]
        )
        if transient and attempt < submit_attempts:
            delay = min(30.0, 3 * attempt) + random.uniform(0, 0.5)
            print(f"Kie Veo submission transient error ({attempt}/{submit_attempts}); retrying in {delay:.1f}s: {message}", flush=True)
            time.sleep(delay)
            continue
        raise_for_kie_code(data, f"submit {model}")
    task_id = data.get("data", {}).get("taskId")
    if not task_id:
        raise RuntimeError("Kie Veo response did not include taskId")
    return task_id, data


def collect_urls(value: Any, results: list[str]) -> None:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("http://") or text.startswith("https://"):
            results.append(text)
        elif text and text[0] in "[{":
            try:
                collect_urls(json.loads(text), results)
            except Exception:
                pass
    elif isinstance(value, list):
        for item in value:
            collect_urls(item, results)
    elif isinstance(value, dict):
        for item in value.values():
            collect_urls(item, results)


def first_url(data: dict[str, Any], kind: str) -> str:
    urls: list[str] = []
    collect_urls(data, urls)
    if kind == "image":
        extensions = [".png", ".jpg", ".jpeg", ".webp"]
        tokens = ["image", "img"]
    else:
        extensions = [".mp4", ".mov", ".webm"]
        tokens = ["download"]
    for url in urls:
        lowered = url.lower()
        url_path = lowered.split("?", 1)[0]
        if any(url_path.endswith(extension) for extension in extensions):
            return url
    for url in urls:
        lowered = url.lower()
        if any(token in lowered for token in tokens) and not any(
            lowered.split("?", 1)[0].endswith(extension)
            for extension in [".png", ".jpg", ".jpeg", ".webp"] if kind == "video"
        ):
            return url
    if kind == "video":
        return ""
    return urls[0] if urls else ""


def kie_result_url(data: dict[str, Any], kind: str) -> str:
    result_json = data.get("resultJson")
    if isinstance(result_json, str) and result_json.strip():
        try:
            parsed = json.loads(result_json)
        except Exception:
            parsed = result_json
        url = first_url({"result": parsed}, kind)
        if url:
            return url
    if isinstance(result_json, dict):
        url = first_url({"result": result_json}, kind)
        if url:
            return url

    response_data = data.get("response")
    if isinstance(response_data, dict):
        url = first_url({"response": response_data}, kind)
        if url:
            return url

    fallback = dict(data)
    fallback.pop("param", None)
    fallback.pop("paramJson", None)
    fallback.pop("input", None)
    fallback.pop("input_urls", None)
    fallback.pop("imageUrls", None)
    fallback.pop("originUrls", None)
    return first_url(fallback, kind)


def query_job(api_key: str, task_id: str, kind: str = "image") -> tuple[str, str, str, dict[str, Any]]:
    response = request_with_retry(
        "GET",
        f"{KIE_API_HOST}/api/v1/jobs/recordInfo",
        headers=get_headers(api_key),
        params={"taskId": task_id},
        timeout=30,
        attempts=5,
        base_delay=1,
    )
    raise_for_kie_status(response, "query task")
    raw = response_json(response, "query task")
    raise_for_kie_code(raw, "query task")
    data = raw.get("data", {})
    success_flag = data.get("successFlag")
    if str(success_flag) == "1":
        state = "success"
    elif str(success_flag) in {"2", "3"}:
        state = "fail"
    else:
        state = str(data.get("state") or data.get("status") or "waiting").lower()
    if state in {"succeeded", "completed", "done"}:
        state = "success"
    if state in {"failed", "error", "canceled", "cancelled"}:
        state = "fail"
    error = data.get("failMsg") or data.get("errorMessage") or data.get("message") or ""
    return state, kie_result_url(data, kind), error, raw


def query_veo(api_key: str, task_id: str) -> tuple[str, str, str, dict[str, Any]]:
    response = request_with_retry(
        "GET",
        f"{KIE_API_HOST}/api/v1/veo/record-info",
        headers=get_headers(api_key),
        params={"taskId": task_id},
        timeout=30,
        attempts=5,
        base_delay=1,
    )
    raise_for_kie_status(response, "query Veo task")
    raw = response_json(response, "query Veo task")
    raise_for_kie_code(raw, "query Veo task")
    data = raw.get("data", {})
    flag = data.get("successFlag")
    if str(flag) == "1":
        state = "success"
    elif str(flag) in {"2", "3"}:
        state = "fail"
    else:
        state = str(data.get("state") or data.get("status") or "waiting").lower()
    if state in {"succeeded", "completed", "done"}:
        state = "success"
    if state in {"failed", "error", "canceled", "cancelled"}:
        state = "fail"
    error = data.get("errorMessage") or ""
    return state, kie_result_url(data, "video"), error, raw


def task_failure_category(raw: dict[str, Any], message: str) -> str:
    data = raw.get("data") or {}
    raw_code = data.get("failCode") or data.get("errorCode")
    try:
        status = int(raw_code)
    except (TypeError, ValueError):
        status = None
    if status is not None:
        category = kie_error_category(status)
        if category != "request":
            return category
    lowered = message.lower()
    if any(token in lowered for token in ("credit", "quota", "balance", "余额", "额度")):
        return "quota"
    if any(token in lowered for token in ("content policy", "safety", "nsfw", "moderation", "敏感", "审核")):
        return "content_policy"
    if any(token in lowered for token in ("download image", "fetch image", "image url", "reference image", "素材")):
        return "input_media"
    if any(token in lowered for token in ("rate limit", "frequency", "too many", "限流", "频率")):
        return "rate_limit"
    return "task_failed"


def wait_for_result(api_key: str, task_id: str, query_type: str, kind: str, timeout: int, poll: int, max_query_errors: int) -> tuple[str, str, dict[str, Any]]:
    deadline = time.time() + timeout
    last_raw: dict[str, Any] = {}
    query_errors = 0
    while time.time() <= deadline:
        try:
            if query_type == "veo":
                state, url, error, raw = query_veo(api_key, task_id)
            else:
                state, url, error, raw = query_job(api_key, task_id, kind)
        except KieAPIError as exc:
            if exc.category not in {"network", "rate_limit", "maintenance", "provider", "invalid_response"}:
                raise
            query_errors += 1
            print(f"{task_id}: query error {query_errors}/{max_query_errors}: {exc}", flush=True)
            if query_errors >= max_query_errors:
                raise KieAPIError(
                    "network",
                    f"Kie query failed {query_errors} times in a row for task {task_id}. "
                    "The saved task will be resumed after network recovery.",
                    resumable=True,
                ) from exc
            continue
        query_errors = 0
        last_raw = raw
        print(f"{task_id}: {state}", flush=True)
        if state == "success" and url:
            return state, url, raw
        if state == "fail":
            message = error or f"Kie task failed: {task_id}"
            raise KieAPIError(task_failure_category(raw, message), message, resumable=False)
        time.sleep(max(1, poll))
    return "timeout", "", last_raw


def veo_response_resolution(raw: dict[str, Any]) -> str:
    data = raw.get("data") or {}
    response = data.get("response") or {}
    if isinstance(response, dict) and response.get("resolution"):
        return str(response["resolution"]).lower()
    return ""


def ensure_veo_resolution(
    api_key: str,
    task_id: str,
    requested: str,
    initial_url: str,
    initial_raw: dict[str, Any],
    timeout: int,
    poll: int,
) -> tuple[str, dict[str, Any]]:
    requested = requested.lower()
    if requested == "720p" or veo_response_resolution(initial_raw) == requested:
        return initial_url, {"source": "initial_result", "resolution": veo_response_resolution(initial_raw) or requested}
    if requested != "1080p":
        raise ValueError("Veo3.1 supports 720p initial output or the separate 1080p retrieval flow; 480p is not supported.")
    deadline = time.time() + timeout
    last_data: dict[str, Any] = {}
    while time.time() <= deadline:
        response = request_with_retry(
            "GET",
            f"{KIE_API_HOST}/api/v1/veo/get-1080p-video",
            headers=get_headers(api_key),
            params={"taskId": task_id, "index": 0},
            timeout=30,
            attempts=2,
            base_delay=2,
        )
        if response.status_code in {400, 404, 409, 422, 425, 429, 500, 502, 503, 504}:
            last_data = {"http_status": response.status_code, "message": response_message(response)}
        else:
            raise_for_kie_status(response, "get Veo 1080p result")
            data = response_json(response, "get Veo 1080p result")
            last_data = data
            if data.get("code") in {200, "200"}:
                result_url = str((data.get("data") or {}).get("resultUrl") or "")
                if result_url:
                    return result_url, data
            else:
                raw_code = data.get("code")
                try:
                    status = int(raw_code)
                except (TypeError, ValueError):
                    status = None
                if status not in {400, 404, 409, 422, 425, 429, 500, 502, 503, 504}:
                    raise_for_kie_code(data, "get Veo 1080p result")
        time.sleep(max(5, poll))
    raise KieAPIError(
        "resolution_pending",
        f"Veo 1080p result is not ready yet for task {task_id}; resume the saved task later. Last response: {last_data}",
        resumable=True,
    )


def is_video_file(path: Path) -> bool:
    try:
        header = path.read_bytes()[:32]
    except Exception:
        return False
    iso_video = (
        len(header) >= 12
        and header[4:8] == b"ftyp"
        and header[8:12] not in {b"avif", b"avis", b"heic", b"heif", b"mif1", b"msf1"}
    )
    return iso_video or header.startswith(b"\x1aE\xdf\xa3")


def is_image_file(path: Path) -> bool:
    try:
        header = path.read_bytes()[:16]
    except Exception:
        return False
    return (
        header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith(b"\xff\xd8\xff")
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        or header.startswith((b"GIF87a", b"GIF89a", b"BM"))
        or (len(header) >= 12 and header[4:12] in {b"ftypavif", b"ftypavis"})
    )


def validate_downloaded_file(path: Path, kind: str, url: str) -> None:
    if kind == "video" and not is_video_file(path):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise KieAPIError("invalid_result", f"Downloaded result is not a valid video file: {url}")
    if kind == "image" and not is_image_file(path):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise KieAPIError("invalid_result", f"Downloaded result is not a valid image file: {url}")


def download_file(url: str, path: Path, kind: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, 6):
        temporary = path.with_name(f"{path.name}.part-{uuid.uuid4().hex}")
        try:
            with request_with_retry("GET", url, stream=True, timeout=180, attempts=3) as response:
                raise_for_kie_status(response, "download result")
                with temporary.open("wb") as file_obj:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            file_obj.write(chunk)
            if temporary.exists() and temporary.stat().st_size > 0:
                validate_downloaded_file(temporary, kind, url)
                os.replace(temporary, path)
                return
            last_error = KieAPIError("invalid_result", f"Downloaded an empty result file: {url}")
        except KieAPIError as exc:
            last_error = exc
            if exc.category != "invalid_result" or attempt == 5:
                raise
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        if attempt < 5:
            delay = min(20, 2 ** attempt)
            print(f"Invalid or empty download ({attempt}/5); retrying in {delay}s", flush=True)
            time.sleep(delay)
    raise last_error or KieAPIError("invalid_result", f"Downloaded empty file after retries: {path}")


def render_prompt(template: str, pid: str) -> str:
    return template.format(pid=pid, product_id=pid)


def resolve_image_model(value: str) -> tuple[str, str]:
    if value in IMAGE_MODEL_CHOICES:
        return IMAGE_MODEL_CHOICES[value]
    for label, model in IMAGE_MODEL_CHOICES.values():
        if value == model or value.lower() == label.lower():
            return label, model
    if value in IMAGE_MODEL_PAYLOADS:
        return value, value
    raise ValueError(f"Unsupported image model choice: {value}")


def resolve_image_generation_model(model: str, has_image: bool) -> str:
    if model == "gpt-image-2":
        return "gpt-image-2-image-to-image" if has_image else "gpt-image-2-text-to-image"
    if model == "google/nano-banana":
        return "google/nano-banana-edit" if has_image else "google/nano-banana"
    if model == "seedream/5-lite":
        return "seedream/5-lite-image-to-image" if has_image else "seedream/5-lite-text-to-image"
    return model


def resolve_video_model(value: str) -> tuple[str, str]:
    if value in VIDEO_MODEL_CHOICES:
        return VIDEO_MODEL_CHOICES[value]
    for label, model in VIDEO_MODEL_CHOICES.values():
        if value == model or value.lower() == label.lower():
            return label, model
    if value in VEO_MODEL_MAP:
        return value, value
    raise ValueError(f"Unsupported video model choice: {value}")


def resolve_video_generation_model(model: str, has_image: bool) -> str:
    if model == "grok-imagine":
        return "grok-imagine/image-to-video" if has_image else "grok-imagine/text-to-video"
    return model


def resolve_aspect_ratio(value: str) -> str:
    if value in ASPECT_RATIO_CHOICES:
        return ASPECT_RATIO_CHOICES[value]
    if value in ASPECT_RATIO_CHOICES.values():
        return value
    raise ValueError(f"Unsupported aspect ratio choice: {value}")


def resolve_image_resolution(value: str) -> str:
    if value in IMAGE_RESOLUTION_CHOICES:
        return IMAGE_RESOLUTION_CHOICES[value]
    if value in IMAGE_RESOLUTION_CHOICES.values() or value == "":
        return value
    raise ValueError(f"Unsupported image resolution choice: {value}")


def image_reference_limit(model: str) -> int:
    try:
        return IMAGE_MODEL_REFERENCE_LIMITS[model]
    except KeyError as exc:
        raise ValueError(f"No reference-image limit is registered for image model: {model}") from exc


def validate_image_references(model: str, image_urls: list[str]) -> None:
    limit = image_reference_limit(model)
    count = len(image_urls)
    if count > limit:
        raise ValueError(f"{model} supports at most {limit} reference images, but {count} were provided.")
    if count == 0 and model in IMAGE_MODELS_REQUIRING_REFERENCES:
        raise ValueError(f"{model} requires at least one reference image.")
    if count and not IMAGE_MODEL_PAYLOADS[model]:
        raise ValueError(
            f"{model} is a text-to-image endpoint and cannot accept reference images; "
            "select the model family so H can route to image-to-image automatically."
        )


def video_max_seconds(model: str) -> int | None:
    return VIDEO_MODEL_MAX_SECONDS.get(model)


def allowed_video_durations(model: str) -> list[int]:
    if model in VEO_MODEL_MAP:
        return [VEO_FIXED_SECONDS]
    max_seconds = video_max_seconds(model)
    if max_seconds is None:
        return VIDEO_DURATION_CHOICES[:]
    allowed = [duration for duration in VIDEO_DURATION_CHOICES if duration <= max_seconds]
    if max_seconds not in allowed:
        allowed.append(max_seconds)
    return sorted(set(allowed))


def resolve_video_duration(requested: int, model: str) -> int:
    if model in VEO_MODEL_MAP:
        return VEO_FIXED_SECONDS
    max_seconds = video_max_seconds(model)
    if requested <= 0:
        return min(6, max_seconds) if max_seconds is not None else 6
    if max_seconds is not None and requested > max_seconds:
        raise ValueError(f"{model} supports up to {max_seconds}s, but --duration was {requested}s.")
    return requested


def image_input_payload(
    model: str,
    prompt: str,
    image_url: str | list[str] | tuple[str, ...] | None,
    aspect_ratio: str,
    resolution: str,
) -> dict[str, Any]:
    aspect_ratio = resolve_aspect_ratio(aspect_ratio)
    resolution = resolve_image_resolution(resolution)
    field = IMAGE_MODEL_PAYLOADS[model]
    image_urls = normalize_media_urls(image_url)
    validate_image_references(model, image_urls)
    payload: dict[str, Any] = {"prompt": prompt}
    if field:
        if image_urls:
            payload[field] = image_urls
    if model in {"gpt-image-2-text-to-image", "gpt-image-2-image-to-image"}:
        payload["aspect_ratio"] = aspect_ratio
    elif model in {"google/nano-banana", "google/nano-banana-edit"}:
        payload["output_format"] = "png"
        payload["aspect_ratio"] = aspect_ratio
    elif model == "nano-banana-2-lite":
        payload["aspect_ratio"] = aspect_ratio
        payload["output_format"] = "png"
    elif model in {"nano-banana-2", "nano-banana-pro"}:
        payload["output_format"] = "png"
        payload["aspect_ratio"] = aspect_ratio
        if resolution:
            payload["resolution"] = resolution
    elif model in {"seedream/5-lite-text-to-image", "seedream/5-lite-image-to-image"}:
        payload["aspect_ratio"] = aspect_ratio
        payload["quality"] = "high" if resolution == "4K" else "basic"
        payload["output_format"] = "png"
        payload["nsfw_checker"] = False
    else:
        payload["aspect_ratio"] = aspect_ratio
        if resolution:
            payload["resolution"] = resolution
    return payload


def video_input_payload(
    model: str,
    prompt: str,
    image_url: str | list[str] | tuple[str, ...],
    aspect_ratio: str,
    resolution: str,
    duration: int,
    video_urls: list[str] | tuple[str, ...] | None = None,
    audio_urls: list[str] | tuple[str, ...] | None = None,
    audio_ids: list[str] | tuple[str, ...] | None = None,
    character_ids: list[str] | tuple[str, ...] | None = None,
    source_task_id: str = "",
    extend_at: int = 2,
    extend_times: int = 1,
) -> dict[str, Any]:
    aspect_ratio = resolve_aspect_ratio(aspect_ratio)
    image_urls = normalize_media_urls(image_url)
    video_refs = normalize_media_urls(video_urls)
    audio_refs = normalize_media_urls(audio_urls)
    omni_audio_ids = normalize_media_urls(audio_ids)
    omni_character_ids = normalize_media_urls(character_ids)
    if model == "grok-imagine/upscale":
        if image_urls or video_refs or audio_refs or omni_audio_ids or omni_character_ids:
            raise ValueError("Grok Imagine Video Upscale accepts a Kie task ID only; external media is not supported.")
        if not source_task_id:
            raise ValueError("Grok Imagine Video Upscale requires --source-task-id from a previous Kie Grok video task.")
        return {"task_id": source_task_id}
    if model == "grok-imagine/extend":
        if image_urls or video_refs or audio_refs or omni_audio_ids or omni_character_ids:
            raise ValueError("Grok Imagine Video Extend accepts a Kie task ID only; external media is not supported.")
        if not source_task_id:
            raise ValueError("Grok Imagine Video Extend requires --source-task-id from a previous Kie Grok video task.")
        return {
            "task_id": source_task_id,
            "prompt": prompt,
            "extend_at": extend_at,
            "extend_times": str(extend_times),
        }
    if model == "grok-imagine/text-to-video":
        if image_urls or video_refs or audio_refs or omni_audio_ids or omni_character_ids:
            raise ValueError("Grok Imagine text-to-video supports 0 images and no video/audio references.")
        return {
            "prompt": prompt,
            "mode": "normal",
            "duration": str(duration),
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "nsfw_checker": False,
        }
    if model == "grok-imagine/image-to-video":
        if len(image_urls) != 1 or video_refs or audio_refs or omni_audio_ids or omni_character_ids:
            raise ValueError("Grok Imagine image-to-video supports exactly 1 image and no video/audio references.")
        return {
            "prompt": prompt,
            "image_urls": image_urls,
            "mode": "normal",
            "duration": str(duration),
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "nsfw_checker": False,
        }
    if model == "grok-imagine-video-1-5-preview":
        if len(image_urls) > 1 or video_refs or audio_refs or omni_audio_ids or omni_character_ids:
            raise ValueError("Grok Imagine Video 1.5 Preview supports 0-1 images and no video/audio references.")
        payload = {
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        }
        if image_urls:
            payload["image_urls"] = image_urls
        return payload
    if model == "gemini-omni-video":
        if audio_refs:
            raise ValueError("Gemini Omni Video accepts Kie audio IDs, not external audio files; use --audio-id.")
        if len(video_refs) > 1:
            raise ValueError("Gemini Omni Video supports at most one video reference.")
        if len(omni_character_ids) > 3:
            raise ValueError("Gemini Omni Video supports at most 3 character IDs.")
        quota = len(image_urls) + (2 * len(video_refs)) + len(omni_character_ids)
        if quota > 7:
            raise ValueError("Gemini Omni Video reference quota exceeded: images + 2*videos + character IDs must be at most 7.")
        payload = {
            "prompt": prompt,
            "duration": str(duration),
        }
        if image_urls:
            payload["image_urls"] = image_urls
        if video_refs:
            payload["video_list"] = [{"url": video_refs[0], "start": 0, "ends": 10}]
        if omni_audio_ids:
            payload["audio_ids"] = omni_audio_ids
        if omni_character_ids:
            payload["character_ids"] = omni_character_ids
        return payload
    if model in {"bytedance/seedance-2", "bytedance/seedance-2-fast", "bytedance/seedance-2-mini"}:
        if omni_audio_ids or omni_character_ids:
            raise ValueError("Seedance 2.0 accepts media references, not Gemini Omni audio/character IDs.")
        if len(image_urls) > 9:
            raise ValueError("Seedance 2.0 supports at most 9 image references.")
        payload = {
            "prompt": prompt,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "duration": duration,
            "generate_audio": False,
            "web_search": False,
        }
        multimodal_reference = len(image_urls) >= 3 or bool(video_refs) or bool(audio_refs)
        if multimodal_reference:
            if image_urls:
                payload["reference_image_urls"] = image_urls
            if video_refs:
                payload["reference_video_urls"] = video_refs
            if audio_refs:
                payload["reference_audio_urls"] = audio_refs
        elif len(image_urls) == 1:
            payload["first_frame_url"] = image_urls[0]
        elif len(image_urls) == 2:
            payload["first_frame_url"] = image_urls[0]
            payload["last_frame_url"] = image_urls[1]
        return payload
    raise ValueError(f"Unsupported video model payload: {model}")


def utc_timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def write_json_atomic(path: Path, value: Any) -> None:
    write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2))


def result_file_valid(path: Path, kind: str) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    return is_image_file(path) if kind == "image" else is_video_file(path)


def exception_category(exc: Exception) -> str:
    if isinstance(exc, KieAPIError):
        return exc.category
    if isinstance(exc, (ValueError, FileNotFoundError)):
        return "validation"
    return "runtime"


def failed_record(pid: str, source_path: Path, exc: Exception, *, folder: str = "") -> dict[str, Any]:
    return {
        "pid": pid,
        "folder": folder,
        "source_path": str(source_path),
        "state": "error",
        "error_category": exception_category(exc),
        "error": str(exc),
        "updated_at": utc_timestamp(),
    }


def record_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [
        {
            "pid": str(record.get("pid") or "unknown"),
            "category": str(record.get("error_category") or record.get("state") or "unknown"),
            "message": str(record.get("error") or "No usable output was returned."),
        }
        for record in records
        if record.get("state") != "success"
    ]
    return {
        "total": len(records),
        "success": len(records) - len(failures),
        "failed": len(failures),
        "failures": failures,
    }


def batch_exit_code(stats: dict[str, Any]) -> int:
    failed = int(stats.get("failed") or 0)
    success = int(stats.get("success") or 0)
    if not failed:
        return 0
    return 2 if success else 1


def next_actions(stage: str) -> list[dict[str, str]]:
    if stage == "images":
        return [
            {"id": "1", "action": "继续生成视频"},
            {"id": "2", "action": "只重试失败项"},
            {"id": "3", "action": "处理新的文件夹"},
            {"id": "4", "action": "结束"},
        ]
    if stage == "videos":
        return [
            {"id": "1", "action": "只重试失败项"},
            {"id": "2", "action": "处理新的文件夹"},
            {"id": "3", "action": "结束"},
        ]
    return [
        {"id": "1", "action": "重试或继续当前任务（已提交任务只查询，不重复提交）"},
        {"id": "2", "action": "继续新的单处理"},
        {"id": "3", "action": "切换到批处理"},
        {"id": "4", "action": "结束"},
    ]


def process_single_product(args: argparse.Namespace, folder: ProductFolder, output_dir: Path, text_dir: Path, product: ProductImage, image_model_label: str, image_model: str, aspect_ratio: str) -> dict[str, Any]:
    print(f"Processing folder {folder.name}: {product.pid}", flush=True)
    output_path = output_dir / f"{product.pid}.png"
    reverse_path = text_dir / f"{product.pid}.reverse.txt"
    json_path = text_dir / f"{product.pid}.image.json"
    if args.force:
        for stale_path in (output_path, reverse_path, json_path):
            try:
                stale_path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"Could not remove stale output for forced image rerun: {stale_path}: {exc}", flush=True)

    source_digest = file_sha256(product.path)
    reverse_signature = stable_hash(
        {
            "version": 2,
            "source_sha256": source_digest,
            "model": normalize_reverse_model(args.reverse_model),
            "api": args.reverse_api,
            "reasoning": args.reverse_reasoning_effort,
            "meta_prompt": args.image_reverse_meta_prompt,
        }
    )
    existing = load_json(json_path)
    reverse_prompt = ""
    reverse_raw: dict[str, Any] = {}
    source_url = ""
    if (
        not args.force
        and existing.get("reverse_signature") == reverse_signature
        and reverse_path.is_file()
    ):
        reverse_prompt = reverse_path.read_text(encoding="utf-8-sig").strip()
        reverse_raw = existing.get("reverse_raw") or {"reused_reverse_path": str(reverse_path)}
    if not reverse_prompt:
        source_url = upload_file(args.api_key, product.path)
        reverse_prompt, reverse_raw = reverse_prompt_with_kie(
            args,
            product.pid,
            source_url,
            args.image_reverse_meta_prompt,
        )
        write_text_atomic(reverse_path, reverse_prompt)

    prompt = build_kie_image_prompt(reverse_prompt, product.pid, args.prompt)
    actual_image_model = resolve_image_generation_model(image_model, True)
    generation_signature = stable_hash(
        {
            "version": 2,
            "reverse_signature": reverse_signature,
            "reverse_prompt": reverse_prompt,
            "model": actual_image_model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolve_image_resolution(args.image_resolution),
        }
    )
    if (
        not args.force
        and existing.get("generation_signature") == generation_signature
        and existing.get("state") == "success"
        and result_file_valid(output_path, "image")
    ):
        existing["cached"] = True
        print(f"Using verified cached image: {product.pid}", flush=True)
        return existing

    task_id = ""
    query_type = "jobs"
    record = dict(existing) if existing.get("generation_signature") == generation_signature else {}
    if (
        not args.force
        and record.get("task_id")
        and str(record.get("state", "")).lower() in RESUMABLE_STATES
    ):
        task_id = str(record["task_id"])
        query_type = str(record.get("query_type") or "jobs")
        source_url = str(record.get("source_url") or source_url)
        print(f"Resuming saved image task {task_id} for {product.pid}", flush=True)
    else:
        if not source_url:
            source_url = upload_file(args.api_key, product.path)
        task_id, submit_raw = submit_job(
            args.api_key,
            actual_image_model,
            image_input_payload(actual_image_model, prompt, source_url, aspect_ratio, args.image_resolution),
        )
        record = {
            "pid": product.pid,
            "folder": folder.name,
            "source_path": str(product.path),
            "source_sha256": source_digest,
            "source_url": source_url,
            "reverse_provider": "kie",
            "reverse_source_path": str(product.path),
            "reverse_source_url": source_url,
            "processed_path": "",
            "expected_output_path": str(output_path),
            "requested_reverse_model": normalize_reverse_model(args.reverse_model),
            "reverse_model": (reverse_raw.get("_h_meta") or {}).get("actual_model", normalize_reverse_model(args.reverse_model)),
            "image_reverse_meta_prompt": args.image_reverse_meta_prompt,
            "reverse_prompt": reverse_prompt,
            "kie_image_prompt": prompt,
            "image_model_choice": args.image_model,
            "image_model_label": image_model_label,
            "image_model": image_model,
            "actual_image_model": actual_image_model,
            "aspect_ratio": aspect_ratio,
            "image_resolution": resolve_image_resolution(args.image_resolution),
            "reverse_signature": reverse_signature,
            "generation_signature": generation_signature,
            "task_id": task_id,
            "query_type": query_type,
            "state": "submitted",
            "result_url": "",
            "reverse_raw": reverse_raw,
            "submit": submit_raw,
            "created_at": utc_timestamp(),
            "updated_at": utc_timestamp(),
        }
        write_json_atomic(json_path, record)

    try:
        state, result_url, final_raw = wait_for_result(
            args.api_key,
            task_id,
            query_type,
            "image",
            args.timeout,
            args.poll,
            args.max_query_errors,
        )
        if result_url and source_url and result_url == source_url:
            raise KieAPIError(
                "invalid_result",
                "Kie returned the uploaded source URL instead of a generated image.",
                resumable=False,
            )
        if result_url:
            download_file(result_url, output_path, "image")
        resolved_state = "success" if result_url and result_file_valid(output_path, "image") else state
        if resolved_state == "success" and not result_url:
            resolved_state = "error"
        record.update(
            {
                "state": resolved_state,
                "processed_path": str(output_path) if result_url else "",
                "result_url": result_url,
                "final": final_raw,
                "updated_at": utc_timestamp(),
            }
        )
        if record["state"] == "timeout":
            record["error_category"] = "timeout"
            record["error"] = "Task is still saved and will resume on the next run."
        elif record["state"] == "error" and not result_url:
            record["error_category"] = "invalid_result"
            record["error"] = "Kie reported success but returned no generated image URL."
    except Exception as exc:
        resumable = isinstance(exc, KieAPIError) and (
            exc.resumable
            if exc.resumable is not None
            else exc.category in {"network", "rate_limit", "maintenance", "provider", "invalid_response", "invalid_result"}
        )
        record.update(
            {
                "state": "waiting" if resumable else "error",
                "error_category": exception_category(exc),
                "error": str(exc),
                "updated_at": utc_timestamp(),
            }
        )
    write_json_atomic(json_path, record)
    return record


def process_product_folder(args: argparse.Namespace, folder: ProductFolder, output_dir: Path, text_dir: Path, image_model_label: str, image_model: str, aspect_ratio: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    workers = resolve_workers(args.workers, len(folder.images))
    manifest: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_single_product, args, folder, output_dir, text_dir, product, image_model_label, image_model, aspect_ratio): product
            for product in folder.images
        }
        for future in concurrent.futures.as_completed(futures):
            product = futures[future]
            try:
                manifest.append(future.result())
            except Exception as exc:
                print(f"Product failed; continuing: {product.pid}: {exc}", flush=True)
                manifest.append(failed_record(product.pid, product.path, exc, folder=folder.name))
    manifest.sort(key=lambda item: item.get("pid", ""))
    manifest_path = text_dir / "processed_manifest.json"
    write_json_atomic(manifest_path, manifest)
    stats = record_stats(manifest)
    return {
        "folder": folder.name,
        "source_dir": str(folder.path),
        "processed_dir": str(output_dir),
        "manifest": str(manifest_path),
        "count": len(manifest),
        **stats,
        "workers": workers,
    }


def process_product_folders_concurrently(args: argparse.Namespace, folders: list[ProductFolder], input_dir: Path, multi_folder: bool, image_model_label: str, image_model: str, aspect_ratio: str) -> list[dict[str, Any]]:
    task_specs: list[tuple[ProductFolder, Path, Path, ProductImage]] = []
    folder_outputs: dict[str, tuple[ProductFolder, Path, Path]] = {}
    for folder in folders:
        output_dir = process_output_dir(args, input_dir, folder, multi_folder)
        text_dir = process_text_output_dir(args, input_dir, folder, multi_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        text_dir.mkdir(parents=True, exist_ok=True)
        folder_outputs[str(folder.path)] = (folder, output_dir, text_dir)
        for product in folder.images:
            task_specs.append((folder, output_dir, text_dir, product))

    workers = resolve_workers(args.workers, len(task_specs))
    manifests: dict[str, list[dict[str, Any]]] = {key: [] for key in folder_outputs}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_single_product, args, folder, output_dir, text_dir, product, image_model_label, image_model, aspect_ratio): (folder, output_dir, text_dir, product)
            for folder, output_dir, text_dir, product in task_specs
        }
        for future in concurrent.futures.as_completed(futures):
            folder, _output_dir, _text_dir, product = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                print(f"Product failed; continuing: {folder.name}/{product.pid}: {exc}", flush=True)
                record = failed_record(product.pid, product.path, exc, folder=folder.name)
            manifests[str(folder.path)].append(record)

    summaries: list[dict[str, Any]] = []
    for key in sorted(folder_outputs, key=lambda item: folder_outputs[item][0].name.lower()):
        folder, output_dir, text_dir = folder_outputs[key]
        manifest = sorted(manifests[key], key=lambda item: item.get("pid", ""))
        manifest_path = text_dir / "processed_manifest.json"
        write_json_atomic(manifest_path, manifest)
        stats = record_stats(manifest)
        summaries.append(
            {
                "folder": folder.name,
                "source_dir": str(folder.path),
                "text_dir": str(text_dir),
                "image_dir": str(output_dir),
                "processed_dir": str(output_dir),
                "manifest": str(manifest_path),
                "count": len(manifest),
                **stats,
                "workers": workers,
            }
        )
    return summaries


def process_images(args: argparse.Namespace) -> int:
    assert_kie_reachable(args)
    input_dir = Path(args.input).resolve()
    folders = discover_product_folders(input_dir)
    if not folders:
        raise ValueError(f"No product image folders found in {input_dir}")
    image_model_label, image_model = resolve_image_model(args.image_model)
    aspect_ratio = resolve_aspect_ratio(args.aspect_ratio)
    multi_folder = len(folders) > 1 or not collect_images(input_dir)
    summaries = process_product_folders_concurrently(args, folders, input_dir, multi_folder, image_model_label, image_model, aspect_ratio)
    root = output_root(args, input_dir)
    summary_path = root / "文本" / "h_processed_batch_manifest.json"
    aggregate = {
        "total": sum(int(item["total"]) for item in summaries),
        "success": sum(int(item["success"]) for item in summaries),
        "failed": sum(int(item["failed"]) for item in summaries),
        "failures": [failure for item in summaries for failure in item["failures"]],
    }
    result = {
        "mode": "批处理",
        "stage": "图片",
        "output_root": str(root),
        "text_dir": str(root / "文本"),
        "image_dir": str(root / "图像"),
        "video_dir": str(root / "视频"),
        "batch_manifest": str(summary_path),
        "stats": aggregate,
        "folders": summaries,
        "next_actions": next_actions("images"),
    }
    write_json_atomic(summary_path, result)
    print_json(result)
    return batch_exit_code(aggregate)


def submit_video(args: argparse.Namespace, pid: str, processed_image: Path, output_dir: Path, text_dir: Path) -> dict[str, Any]:
    video_model_label, video_model = resolve_video_model(args.video_model)
    if video_model in VIDEO_TRANSFORM_MODELS:
        raise ValueError(f"{video_model_label} is available in single mode only because it requires an existing Kie task ID.")
    if video_model in VEO_MODEL_MAP and args.video_resolution == "480p":
        raise ValueError("Veo3.1 does not provide a 480p output option; choose 720p or 1080p.")
    aspect_ratio = resolve_aspect_ratio(args.aspect_ratio)
    output_path = output_dir / f"{pid}.mp4"
    reverse_path = text_dir / f"{pid}.video_reverse.txt"
    json_path = text_dir / f"{pid}.video.json"
    if args.force:
        for stale_path in (output_path, reverse_path, json_path):
            try:
                stale_path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"Could not remove stale output for forced video rerun: {stale_path}: {exc}", flush=True)

    source_digest = file_sha256(processed_image)
    reverse_signature = stable_hash(
        {
            "version": 2,
            "source_sha256": source_digest,
            "model": normalize_reverse_model(args.reverse_model),
            "api": args.reverse_api,
            "reasoning": args.reverse_reasoning_effort,
            "meta_prompt": args.video_reverse_meta_prompt,
        }
    )
    existing = load_json(json_path)
    reverse_prompt = ""
    reverse_raw: dict[str, Any] = {}
    image_url = ""
    if (
        not args.force
        and existing.get("reverse_signature") == reverse_signature
        and reverse_path.is_file()
    ):
        reverse_prompt = reverse_path.read_text(encoding="utf-8-sig").strip()
        reverse_raw = existing.get("video_reverse_raw") or {"reused_reverse_path": str(reverse_path)}
    if not reverse_prompt:
        image_url = upload_file(args.api_key, processed_image)
        reverse_prompt, reverse_raw = reverse_prompt_with_kie(args, pid, image_url, args.video_reverse_meta_prompt)
        write_text_atomic(reverse_path, reverse_prompt)

    prompt = build_kie_video_prompt(reverse_prompt, pid, args.prompt)
    actual_video_model = resolve_video_generation_model(video_model, True)
    duration = resolve_video_duration(args.duration, actual_video_model)
    generation_signature = stable_hash(
        {
            "version": 2,
            "reverse_signature": reverse_signature,
            "reverse_prompt": reverse_prompt,
            "model": actual_video_model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": args.video_resolution,
            "duration": duration,
        }
    )
    if (
        not args.force
        and existing.get("generation_signature") == generation_signature
        and existing.get("state") == "success"
        and result_file_valid(output_path, "video")
    ):
        existing["cached"] = True
        print(f"Using verified cached video: {pid}", flush=True)
        return existing

    task_id = ""
    query_type = "veo" if actual_video_model in VEO_MODEL_MAP else "jobs"
    record = dict(existing) if existing.get("generation_signature") == generation_signature else {}
    if (
        not args.force
        and record.get("task_id")
        and str(record.get("state", "")).lower() in RESUMABLE_STATES
    ):
        task_id = str(record["task_id"])
        query_type = str(record.get("query_type") or query_type)
        image_url = str(record.get("processed_image_url") or image_url)
        print(f"Resuming saved video task {task_id} for {pid}", flush=True)
    else:
        if not image_url:
            image_url = upload_file(args.api_key, processed_image)
        if actual_video_model in VEO_MODEL_MAP:
            task_id, submit_raw = submit_veo(
                args.api_key,
                actual_video_model,
                prompt,
                image_url,
                aspect_ratio,
                args.video_resolution,
            )
        else:
            task_id, submit_raw = submit_job(
                args.api_key,
                actual_video_model,
                video_input_payload(actual_video_model, prompt, image_url, aspect_ratio, args.video_resolution, duration),
            )
        record = {
            "pid": pid,
            "processed_image": str(processed_image),
            "source_sha256": source_digest,
            "processed_image_url": image_url,
            "video_reverse_provider": "kie",
            "video_path": "",
            "expected_output_path": str(output_path),
            "requested_reverse_model": normalize_reverse_model(args.reverse_model),
            "video_reverse_model": (reverse_raw.get("_h_meta") or {}).get("actual_model", normalize_reverse_model(args.reverse_model)),
            "video_reverse_meta_prompt": args.video_reverse_meta_prompt,
            "video_reverse_prompt": reverse_prompt,
            "kie_video_prompt": prompt,
            "video_model_choice": args.video_model,
            "video_model_label": video_model_label,
            "video_model": video_model,
            "actual_video_model": actual_video_model,
            "duration": duration,
            "max_duration": video_max_seconds(actual_video_model),
            "aspect_ratio": aspect_ratio,
            "video_resolution": args.video_resolution,
            "reverse_signature": reverse_signature,
            "generation_signature": generation_signature,
            "task_id": task_id,
            "query_type": query_type,
            "state": "submitted",
            "video_url": "",
            "video_reverse_raw": reverse_raw,
            "submit": submit_raw,
            "created_at": utc_timestamp(),
            "updated_at": utc_timestamp(),
        }
        write_json_atomic(json_path, record)

    try:
        state, video_url, final_raw = wait_for_result(
            args.api_key,
            task_id,
            query_type,
            "video",
            args.timeout,
            args.poll,
            args.max_query_errors,
        )
        resolution_raw: dict[str, Any] = {}
        if video_url and query_type == "veo":
            video_url, resolution_raw = ensure_veo_resolution(
                args.api_key,
                task_id,
                args.video_resolution,
                video_url,
                final_raw,
                args.timeout,
                args.poll,
            )
        if video_url:
            download_file(video_url, output_path, "video")
        resolved_state = "success" if video_url and result_file_valid(output_path, "video") else state
        if resolved_state == "success" and not video_url:
            resolved_state = "error"
        record.update(
            {
                "state": resolved_state,
                "video_path": str(output_path) if video_url else "",
                "video_url": video_url,
                "final": final_raw,
                "resolution_result": resolution_raw,
                "updated_at": utc_timestamp(),
            }
        )
        if record["state"] == "timeout":
            record["error_category"] = "timeout"
            record["error"] = "Task is still saved and will resume on the next run."
        elif record["state"] == "error" and not video_url:
            record["error_category"] = "invalid_result"
            record["error"] = "Kie reported success but returned no generated video URL."
    except Exception as exc:
        resumable = isinstance(exc, KieAPIError) and (
            exc.resumable
            if exc.resumable is not None
            else exc.category in {
                "network",
                "rate_limit",
                "maintenance",
                "provider",
                "invalid_response",
                "invalid_result",
                "resolution_pending",
            }
        )
        record.update(
            {
                "state": "waiting" if resumable else "error",
                "error_category": exception_category(exc),
                "error": str(exc),
                "updated_at": utc_timestamp(),
            }
        )
    write_json_atomic(json_path, record)
    return record


def generate_video_folders_concurrently(args: argparse.Namespace, folders: list[ProductFolder], source_root: Path, multi_folder: bool) -> list[dict[str, Any]]:
    task_specs: list[tuple[ProductFolder, Path, Path, ProductImage]] = []
    folder_outputs: dict[str, tuple[ProductFolder, Path, Path]] = {}
    for folder in folders:
        output_dir = video_output_dir(args, source_root, folder, multi_folder)
        text_dir = video_text_output_dir(args, source_root, folder, multi_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        text_dir.mkdir(parents=True, exist_ok=True)
        folder_outputs[str(folder.path)] = (folder, output_dir, text_dir)
        for product in folder.images:
            task_specs.append((folder, output_dir, text_dir, product))

    workers = resolve_workers(args.workers, len(task_specs))
    manifests: dict[str, list[dict[str, Any]]] = {key: [] for key in folder_outputs}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(submit_video, args, product.pid, product.path, output_dir, text_dir): (folder, output_dir, text_dir, product)
            for folder, output_dir, text_dir, product in task_specs
        }
        for future in concurrent.futures.as_completed(futures):
            folder, _output_dir, _text_dir, product = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                print(f"Video failed; continuing: {folder.name}/{product.pid}: {exc}", flush=True)
                record = failed_record(product.pid, product.path, exc, folder=folder.name)
                record["processed_image"] = str(product.path)
            manifests[str(folder.path)].append(record)

    summaries: list[dict[str, Any]] = []
    for key in sorted(folder_outputs, key=lambda item: folder_outputs[item][0].name.lower()):
        folder, output_dir, text_dir = folder_outputs[key]
        records = sorted(manifests[key], key=lambda item: item.get("pid", ""))
        summary_path = text_dir / "video_manifest.json"
        write_json_atomic(summary_path, records)
        stats = record_stats(records)
        summaries.append(
            {
                "folder": folder.name,
                "processed_dir": str(folder.path),
                "text_dir": str(text_dir),
                "video_dir": str(output_dir),
                "manifest": str(summary_path),
                "count": len(records),
                **stats,
                "workers": workers,
            }
        )
    return summaries


def generate_videos(args: argparse.Namespace) -> int:
    assert_kie_reachable(args)
    input_dir = Path(args.input).resolve()
    root = output_root(args, input_dir)
    desktop_image_dir = root / "图像"
    processed_input_dir = desktop_image_dir if desktop_image_dir.is_dir() and input_dir.name not in {"图像", "processed_products"} else input_dir
    folders = discover_processed_folders(processed_input_dir)
    if not folders:
        raise ValueError(f"No processed product image folders found in {processed_input_dir}")
    multi_folder = len(folders) > 1 or not collect_images(processed_input_dir)
    summaries = generate_video_folders_concurrently(args, folders, input_dir, multi_folder)
    batch_summary_path = root / "文本" / "h_video_batch_manifest.json"
    aggregate = {
        "total": sum(int(item["total"]) for item in summaries),
        "success": sum(int(item["success"]) for item in summaries),
        "failed": sum(int(item["failed"]) for item in summaries),
        "failures": [failure for item in summaries for failure in item["failures"]],
    }
    result = {
        "mode": "批处理",
        "stage": "视频",
        "output_root": str(root),
        "text_dir": str(root / "文本"),
        "image_dir": str(root / "图像"),
        "video_dir": str(root / "视频"),
        "processed_input_dir": str(processed_input_dir),
        "batch_manifest": str(batch_summary_path),
        "stats": aggregate,
        "folders": summaries,
        "next_actions": next_actions("videos"),
    }
    write_json_atomic(batch_summary_path, result)
    print_json(result)
    return batch_exit_code(aggregate)


def model_catalog() -> dict[str, Any]:
    return {
        "text": [
            {"choice": choice, "name": label, "model": model}
            for choice, (label, model) in TEXT_MODEL_CHOICES.items()
        ],
        "image": [
            {
                "choice": choice,
                "name": label,
                "model": model,
                "mode": f"0张参考图=文生图；1-{image_reference_limit(model)}张参考图=多图参考生成",
                "max_reference_images": image_reference_limit(model),
                "reference_usage": "多张图片会一起进入同一个生成任务；每张图片都必须作为独立 --media 传入",
                "aspect_ratios": list(ASPECT_RATIO_CHOICES.values()),
                "resolution_choices": list(IMAGE_RESOLUTION_CHOICES.values()),
            }
            for choice, (label, model) in IMAGE_MODEL_CHOICES.items()
        ],
        "video": [
            {
                "choice": choice,
                "name": label,
                "model": model,
                "max_seconds": video_max_seconds(model),
                "fixed_seconds": VEO_FIXED_SECONDS if model in VEO_MODEL_MAP else None,
                "resolution_choices": (
                    ["继承原Kie任务"]
                    if model in VIDEO_TRANSFORM_MODELS
                    else ["720p", "1080p"]
                    if model in VEO_MODEL_MAP
                    else ["由模型决定"]
                    if model == "gemini-omni-video"
                    else ["480p", "720p", "1080p"]
                ),
                "input_rule": (
                    "已有Kie Grok视频task_id"
                    if model in VIDEO_TRANSFORM_MODELS
                    else "Veo: 0图文生，1-2图首尾帧，3图仅Lite/Fast参考图"
                    if model in VEO_MODEL_MAP
                    else "Grok: 0图文生，1图图生"
                    if model.startswith("grok-imagine")
                    else "Seedance: 0图文生，1图首帧，2图首尾帧，3-9图或含视频/音频走多模态"
                    if model.startswith("bytedance/seedance")
                    else "Gemini Omni: 图片 + 2*视频 + 角色ID <= 7，视频最多1个"
                ),
            }
            for choice, (label, model) in VIDEO_MODEL_CHOICES.items()
        ],
    }


def catalog_command() -> int:
    print_json(model_catalog())
    return 0


def doctor_command(args: argparse.Namespace) -> int:
    credits = check_kie_account(args.api_key, timeout=args.timeout)
    result = {
        "ready": True,
        "kie_api": "ok",
        "credits": credits,
        "key_fingerprint": describe_secret(args.api_key),
        "tls_verification": True,
    }
    print_json(result)
    return 0


def single_output_root(args: argparse.Namespace) -> Path:
    return Path(args.output_dir).expanduser().resolve() if args.output_dir else desktop_dir() / "H返回结果_单处理"


def upload_reference(api_key: str, value: str, allowed: set[str], label: str) -> str:
    if value.startswith(("https://", "http://")):
        return value
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if allowed and path.suffix.lower() not in allowed:
        raise ValueError(f"Unsupported {label} file type: {path.suffix}")
    return upload_file(api_key, path)


def single_result_stem() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


def single_call(args: argparse.Namespace) -> int:
    assert_kie_reachable(args)
    root = single_output_root(args)
    text_dir = root / "文本"
    image_dir = root / "图像"
    video_dir = root / "视频"
    for folder in (text_dir, image_dir, video_dir):
        folder.mkdir(parents=True, exist_ok=True)
    stem = single_result_stem()
    json_path = text_dir / f"{stem}.json"
    common = {
        "mode": "单处理",
        "kind": args.kind,
        "output_root": str(root),
        "text_dir": str(text_dir),
        "image_dir": str(image_dir),
        "video_dir": str(video_dir),
        "prompt": args.prompt,
        "created_at": utc_timestamp(),
        "next_actions": next_actions("single"),
    }
    try:
        is_video_transform = args.kind == "video" and resolve_video_model(args.model)[1] in VIDEO_TRANSFORM_MODELS
        if not args.prompt.strip() and not is_video_transform:
            raise ValueError("A non-empty --prompt is required for this single model call.")
        image_urls = [upload_reference(args.api_key, value, IMAGE_EXTENSIONS, "image") for value in args.media]
        if args.kind == "text":
            label, model = resolve_text_model(args.model)
            content, raw = text_with_kie(
                args.api_key,
                model,
                args.prompt,
                image_urls,
                timeout=args.timeout,
                reasoning_effort=args.reasoning_effort,
            )
            output_path = text_dir / f"{stem}.txt"
            write_text_atomic(output_path, content)
            result = {
                **common,
                "state": "success",
                "model_choice": args.model,
                "model_label": label,
                "requested_model": model,
                "actual_model": (raw.get("_h_meta") or {}).get("actual_model", model),
                "media_urls": image_urls,
                "output_path": str(output_path),
                "raw": raw,
                "updated_at": utc_timestamp(),
            }
            write_json_atomic(json_path, result)
            print_json(result)
            return 0

        if args.kind == "image":
            label, model = resolve_image_model(args.model)
            actual_model = resolve_image_generation_model(model, bool(image_urls))
            task_id, submit_raw = submit_job(
                args.api_key,
                actual_model,
                image_input_payload(actual_model, args.prompt, image_urls, args.aspect_ratio, args.image_resolution),
            )
            output_path = image_dir / f"{stem}.png"
            result = {
                **common,
                "state": "submitted",
                "model_choice": args.model,
                "model_label": label,
                "model": actual_model,
                "media_urls": image_urls,
                "aspect_ratio": resolve_aspect_ratio(args.aspect_ratio),
                "image_resolution": resolve_image_resolution(args.image_resolution),
                "task_id": task_id,
                "query_type": "jobs",
                "submit": submit_raw,
                "output_path": "",
                "expected_output_path": str(output_path),
                "updated_at": utc_timestamp(),
            }
            write_json_atomic(json_path, result)
            state, result_url, final_raw = wait_for_result(
                args.api_key, task_id, "jobs", "image", args.timeout, args.poll, args.max_query_errors
            )
            if result_url and result_url in image_urls:
                raise KieAPIError(
                    "invalid_result",
                    "Kie returned a reference image URL instead of a generated result.",
                    resumable=False,
                )
            if result_url:
                download_file(result_url, output_path, "image")
            result.update(
                {
                    "state": "success" if result_url and result_file_valid(output_path, "image") else state,
                    "result_url": result_url,
                    "output_path": str(output_path) if result_url else "",
                    "final": final_raw,
                    "updated_at": utc_timestamp(),
                }
            )
            if result["state"] == "success" and not result_url:
                result["state"] = "error"
                result["error_category"] = "invalid_result"
                result["error"] = "Kie reported success but returned no generated image URL."
            write_json_atomic(json_path, result)
            print_json(result)
            return 0 if result["state"] == "success" else 1

        label, model = resolve_video_model(args.model)
        video_urls = [upload_reference(args.api_key, value, VIDEO_EXTENSIONS, "video") for value in args.video_ref]
        audio_urls = [upload_reference(args.api_key, value, AUDIO_EXTENSIONS, "audio") for value in args.audio_ref]
        actual_model = resolve_video_generation_model(model, bool(image_urls))
        duration = 0 if actual_model in VIDEO_TRANSFORM_MODELS else resolve_video_duration(args.duration, actual_model)
        if actual_model in VEO_MODEL_MAP:
            if args.video_resolution == "480p":
                raise ValueError("Veo3.1 does not provide a 480p output option; choose 720p or 1080p.")
            if video_urls or audio_urls:
                raise ValueError("Veo3.1 does not accept video or audio references.")
            task_id, submit_raw = submit_veo(
                args.api_key,
                actual_model,
                args.prompt,
                image_urls,
                args.aspect_ratio,
                args.video_resolution,
            )
            query_type = "veo"
        else:
            payload = video_input_payload(
                actual_model,
                args.prompt,
                image_urls,
                args.aspect_ratio,
                args.video_resolution,
                duration,
                video_urls=video_urls,
                audio_urls=audio_urls,
                audio_ids=args.audio_id,
                character_ids=args.character_id,
                source_task_id=args.source_task_id,
                extend_at=args.extend_at,
                extend_times=args.extend_times,
            )
            task_id, submit_raw = submit_job(args.api_key, actual_model, payload)
            query_type = "jobs"
        output_path = video_dir / f"{stem}.mp4"
        result = {
            **common,
            "state": "submitted",
            "model_choice": args.model,
            "model_label": label,
            "model": actual_model,
            "image_urls": image_urls,
            "video_urls": video_urls,
            "audio_urls": audio_urls,
            "audio_ids": args.audio_id,
            "character_ids": args.character_id,
            "duration": duration,
            "max_duration": video_max_seconds(actual_model),
            "aspect_ratio": resolve_aspect_ratio(args.aspect_ratio),
            "video_resolution": args.video_resolution,
            "task_id": task_id,
            "query_type": query_type,
            "submit": submit_raw,
            "output_path": "",
            "expected_output_path": str(output_path),
            "updated_at": utc_timestamp(),
        }
        write_json_atomic(json_path, result)
        state, result_url, final_raw = wait_for_result(
            args.api_key, task_id, query_type, "video", args.timeout, args.poll, args.max_query_errors
        )
        resolution_raw: dict[str, Any] = {}
        if result_url and query_type == "veo":
            result_url, resolution_raw = ensure_veo_resolution(
                args.api_key,
                task_id,
                args.video_resolution,
                result_url,
                final_raw,
                args.timeout,
                args.poll,
            )
        if result_url:
            download_file(result_url, output_path, "video")
        result.update(
            {
                "state": "success" if result_url and result_file_valid(output_path, "video") else state,
                "result_url": result_url,
                "output_path": str(output_path) if result_url else "",
                "final": final_raw,
                "resolution_result": resolution_raw,
                "updated_at": utc_timestamp(),
            }
        )
        if result["state"] == "success" and not result_url:
            result["state"] = "error"
            result["error_category"] = "invalid_result"
            result["error"] = "Kie reported success but returned no generated video URL."
        write_json_atomic(json_path, result)
        print_json(result)
        return 0 if result["state"] == "success" else 1
    except Exception as exc:
        category = exception_category(exc)
        previous = load_json(json_path)
        resumable = bool(previous.get("task_id")) and isinstance(exc, KieAPIError) and (
            exc.resumable
            if exc.resumable is not None
            else category in {"network", "rate_limit", "maintenance", "provider", "invalid_response", "invalid_result", "resolution_pending"}
        )
        result = {
            **common,
            "state": "waiting" if resumable else "error",
            "error_category": category,
            "error": str(exc),
            "updated_at": utc_timestamp(),
        }
        if previous:
            result = {**previous, **result}
        write_json_atomic(json_path, result)
        print_json(result)
        return 1


def resume_command(args: argparse.Namespace) -> int:
    assert_kie_reachable(args)
    record_path = Path(args.record).expanduser().resolve()
    record = load_json(record_path)
    if not record:
        raise ValueError(f"Invalid or empty H task record: {record_path}")
    task_id = str(record.get("task_id") or "")
    if not task_id:
        raise ValueError(f"H task record has no task_id: {record_path}")
    query_type = str(record.get("query_type") or "jobs")
    kind = str(record.get("kind") or "")
    if kind not in {"image", "video"}:
        kind = "video" if any(key in record for key in ("video_model", "actual_video_model", "video_path")) else "image"
    output_value = str(record.get("expected_output_path") or record.get("output_path") or "")
    if not output_value:
        raise ValueError(f"H task record has no expected output path: {record_path}")
    output_path = Path(output_value).expanduser().resolve()
    stage = "single" if record.get("mode") == "单处理" else ("videos" if kind == "video" else "images")
    try:
        state, result_url, final_raw = wait_for_result(
            args.api_key,
            task_id,
            query_type,
            kind,
            args.timeout,
            args.poll,
            args.max_query_errors,
        )
        resolution_raw: dict[str, Any] = {}
        if result_url and query_type == "veo":
            requested_resolution = str(record.get("video_resolution") or "720p")
            result_url, resolution_raw = ensure_veo_resolution(
                args.api_key,
                task_id,
                requested_resolution,
                result_url,
                final_raw,
                args.timeout,
                args.poll,
            )
        if result_url:
            download_file(result_url, output_path, kind)
        resolved_state = "success" if result_url and result_file_valid(output_path, kind) else state
        if resolved_state == "success" and not result_url:
            resolved_state = "error"
        record.update(
            {
                "state": resolved_state,
                "result_url": result_url,
                "output_path": str(output_path) if result_url else "",
                "final": final_raw,
                "resolution_result": resolution_raw,
                "updated_at": utc_timestamp(),
                "next_actions": next_actions(stage),
            }
        )
        if kind == "image":
            record["processed_path"] = str(output_path) if result_url else ""
        else:
            record["video_path"] = str(output_path) if result_url else ""
        if resolved_state == "timeout":
            record["error_category"] = "timeout"
            record["error"] = "Task remains saved; run resume again later."
        elif resolved_state == "error":
            record["error_category"] = "invalid_result"
            record["error"] = f"Kie returned no generated {kind} URL."
    except Exception as exc:
        category = exception_category(exc)
        resumable = isinstance(exc, KieAPIError) and (
            exc.resumable
            if exc.resumable is not None
            else category in {"network", "rate_limit", "maintenance", "provider", "invalid_result", "resolution_pending"}
        )
        record.update(
            {
                "state": "waiting" if resumable else "error",
                "error_category": category,
                "error": str(exc),
                "updated_at": utc_timestamp(),
                "next_actions": next_actions(stage),
            }
        )
    write_json_atomic(record_path, record)
    print_json(record)
    return 0 if record.get("state") == "success" else 1


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", help="Input folder.")
    parser.add_argument("--api-key", default="", help="Kie API key. Defaults to env/local secret files.")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait per task.")
    parser.add_argument("--poll", type=int, default=10, help="Polling interval in seconds.")
    parser.add_argument("--output-dir", default="", help="Output directory.")
    parser.add_argument("--workers", type=int, default=0, help="Concurrent workers across the whole input root. 0 means one worker per product image, capped at 64.")
    parser.add_argument("--force", action="store_true", help="Regenerate outputs even when PID-named output files already exist.")
    parser.add_argument("--preflight-timeout", type=int, default=12, help="Seconds for the fast Kie API reachability check before submitting work.")
    parser.add_argument("--max-query-errors", type=int, default=3, help="Stop polling a submitted task after this many consecutive Kie query network errors.")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip the fast Kie API reachability check.")


def add_reverse_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reverse-base-url", default=KIE_API_HOST, help="Kie reverse chat base URL. Default: https://api.kie.ai.")
    parser.add_argument("--reverse-model", default="gpt-5-5", help="Kie multimodal model for reverse prompting. Accepts 1=gpt-5-5, 2=gpt-5-4, 3=gemini-3.1-pro, 4=gemini-3-pro, 5=gemini-3.5-flash, 6=gemini-3-flash. Default: gpt-5-5.")
    parser.add_argument("--reverse-api", default="auto", choices=["auto", "responses", "chat"], help="Kie reverse API style. Default: auto.")
    parser.add_argument("--reverse-reasoning-effort", default="high", choices=["low", "medium", "high", "xhigh"], help="Kie reverse reasoning effort.")
    parser.add_argument("--reverse-timeout", type=int, default=180, help="Seconds to wait for each Kie reverse chat call.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Two-stage Kie PID product image and video workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    image_model_ids = {model for _label, model in IMAGE_MODEL_CHOICES.values()}
    video_model_ids = {model for _label, model in VIDEO_MODEL_CHOICES.values() if model not in VIDEO_TRANSFORM_MODELS}
    video_model_keys = {choice for choice, (_label, model) in VIDEO_MODEL_CHOICES.items() if model not in VIDEO_TRANSFORM_MODELS}

    subparsers.add_parser("catalog", help="List every selectable text, image, and video model with its constraints.")

    doctor = subparsers.add_parser("doctor", help="Validate the Kie key, TLS connection, and available credits.")
    doctor.add_argument("--api-key", default="", help="Kie API key. Defaults to env/user secret files.")
    doctor.add_argument("--timeout", type=int, default=15)

    resume = subparsers.add_parser("resume", help="Resume polling a previously submitted H task record without resubmitting it.")
    resume.add_argument("record", help="Path to a .json task record written by H.")
    resume.add_argument("--api-key", default="")
    resume.add_argument("--timeout", type=int, default=900)
    resume.add_argument("--poll", type=int, default=10)
    resume.add_argument("--max-query-errors", type=int, default=3)
    resume.add_argument("--preflight-timeout", type=int, default=15)
    resume.add_argument("--skip-preflight", action="store_true")

    single = subparsers.add_parser("single", help="Call one selected Kie text, image, or video model.")
    single.add_argument("--kind", required=True, choices=["text", "image", "video"])
    single.add_argument("--model", required=True, help="Number or model ID from the catalog command.")
    single.add_argument("--prompt", default="")
    single.add_argument(
        "--media",
        action="append",
        default=[],
        help="Local image path or image URL. Repeat once per reference image; H enforces the selected model's limit.",
    )
    single.add_argument("--video-ref", action="append", default=[], help="Local video path or video URL. Repeat when supported.")
    single.add_argument("--audio-ref", action="append", default=[], help="Local audio path or audio URL. Repeat when supported.")
    single.add_argument("--audio-id", action="append", default=[], help="Gemini Omni audio ID. Repeat when needed.")
    single.add_argument("--character-id", action="append", default=[], help="Gemini Omni character ID. Repeat when needed.")
    single.add_argument("--source-task-id", default="", help="Required for Grok upscale/extend.")
    single.add_argument("--extend-at", type=int, default=2)
    single.add_argument("--extend-times", type=int, default=1)
    single.add_argument("--aspect-ratio", default="2", choices=["1", "2", "9:16", "16:9"])
    single.add_argument("--image-resolution", default="1", choices=["", "1", "2", "3", "1K", "2K", "4K"])
    single.add_argument("--video-resolution", default="720p", choices=["480p", "720p", "1080p"])
    single.add_argument("--duration", type=int, default=0, choices=[0] + VIDEO_DURATION_CHOICES)
    single.add_argument("--reasoning-effort", default="high", choices=["low", "medium", "high", "xhigh"])
    single.add_argument("--api-key", default="")
    single.add_argument("--timeout", type=int, default=900)
    single.add_argument("--poll", type=int, default=10)
    single.add_argument("--max-query-errors", type=int, default=3)
    single.add_argument("--preflight-timeout", type=int, default=15)
    single.add_argument("--skip-preflight", action="store_true")
    single.add_argument("--output-dir", default="")

    process = subparsers.add_parser("process-images", help="Process original PID product images into cleaned product images.")
    add_common_args(process)
    add_reverse_args(process)
    process.add_argument("--image-reverse-meta-prompt", required=True, help="Meta prompt sent to Kie multimodal chat to reverse each original product image into the final Kie image prompt. Supports {pid}.")
    process.add_argument("--prompt", default="", help="Optional extra instruction appended to the Kie reversed prompt. Supports {pid}.")
    process.add_argument(
        "--image-model",
        default="1",
        choices=sorted(set(IMAGE_MODEL_CHOICES) | image_model_ids),
        help="Image model choice: 1=GPT Image-2, 2=Nano Banana, 3=Nano Banana Pro, 4=Nano Banana 2, 5=Nano Banana 2 Lite, 6=Seedream 5.0 Lite. The script chooses image/text endpoint from whether an input image is present.",
    )
    process.add_argument("--aspect-ratio", default="2", choices=["1", "2", "9:16", "16:9"], help="Aspect ratio: 1=9:16, 2=16:9.")
    process.add_argument("--image-resolution", default="1", choices=["", "1", "2", "3", "1K", "2K", "4K"], help="Image resolution: 1=1K, 2=2K, 3=4K. The script only passes resolution to models that support it.")
    process.add_argument("--resolution", dest="image_resolution", choices=["", "1", "2", "3", "1K", "2K", "4K"], help=argparse.SUPPRESS)

    video = subparsers.add_parser("generate-videos", help="Generate videos from processed PID product images.")
    add_common_args(video)
    add_reverse_args(video)
    video.add_argument("--video-reverse-meta-prompt", required=True, help="Meta prompt sent to Kie multimodal chat to reverse each processed image into the final Kie video prompt. Supports {pid}.")
    video.add_argument("--prompt", default="", help="Optional extra instruction appended to the Kie reversed video prompt. Supports {pid}.")
    video.add_argument(
        "--video-model",
        default="3",
        choices=sorted(video_model_keys | video_model_ids | set(VEO_MODEL_MAP)),
        help="Video model choice: 1=Grok Imagine, 2=Grok 1.5 Preview, 3=Veo3.1 Lite, 4=Veo3.1 Fast, 5=Veo3.1 Quality, 6=Gemini Omni, 7=Seedance 2.0, 8=Seedance 2.0 Fast, 9=Seedance 2.0 Mini. The script chooses image/text endpoint from whether an input image is present.",
    )
    video.add_argument("--aspect-ratio", default="2", choices=["1", "2", "9:16", "16:9"], help="Aspect ratio: 1=9:16, 2=16:9.")
    video.add_argument("--video-resolution", default="720p", choices=["480p", "720p", "1080p"])
    video.add_argument("--duration", type=int, default=0, choices=[0] + VIDEO_DURATION_CHOICES, help="Video duration in seconds. 0=auto; only confirmed model maximums are blocked before submission.")

    args = parser.parse_args(argv)
    if args.command == "catalog":
        return args
    args.api_key = load_api_key(getattr(args, "api_key", ""))
    if not args.api_key:
        parser.error("Missing Kie API key. Pass --api-key, set KIE_API_KEY/H_KIE_API_KEY, or create a local H key file.")
    return args


def read_text_if_exists(path: Path) -> str:
    try:
        if path.exists():
            return clean_api_key(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    return ""


def load_api_key(explicit: str) -> str:
    candidates = [
        ("--api-key", clean_api_key(explicit)),
        ("H_KIE_API_KEY", clean_api_key(os.environ.get("H_KIE_API_KEY", ""))),
        ("KIE_API_KEY", clean_api_key(os.environ.get("KIE_API_KEY", ""))),
        ("user_secret", read_text_if_exists(USER_API_KEY_FILE)),
        ("plugin_local", read_text_if_exists(LOCAL_API_KEY_FILE)),
    ]
    return choose_secret(candidates, "Kie")


def main(argv: list[str]) -> int:
    configure_utf8_output()
    args = parse_args(argv)
    if args.command == "catalog":
        return catalog_command()
    if args.command == "doctor":
        return doctor_command(args)
    if args.command == "single":
        return single_call(args)
    if args.command == "resume":
        return resume_command(args)
    if args.command == "process-images":
        return process_images(args)
    if args.command == "generate-videos":
        return generate_videos(args)
    raise ValueError(args.command)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
