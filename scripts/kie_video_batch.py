#!/usr/bin/env python
"""Two-stage Kie product workflow.

Stage 1: process PID-named product images into cleaned/enhanced product images.
Stage 2: generate PID-named videos from the processed product images.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


KIE_API_HOST = "https://api.kie.ai"
KIE_FILE_HOST = "https://kieai.redpandaai.co"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LOCAL_API_KEY_FILE = PLUGIN_ROOT / ".h_api_key"
USER_API_KEY_FILE = Path.home() / ".codex" / "secrets" / "h_kie_api_key.txt"
_PROXY_CACHE: dict[str, str] | None = None
_KIE_SUBMIT_LOCK = threading.Lock()

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
    "2": ("Grok Imagine 1.5 Preview", "grok-imagine-video-1-5-preview"),
    "3": ("Veo3.1 Lite", "veo3.1-lite"),
    "4": ("Veo3.1 Fast", "veo3.1-fast"),
    "5": ("Veo3.1 Quality", "veo3.1-quality"),
    "6": ("Gemini Omni Video", "gemini-omni-video"),
    "7": ("Seedance 2.0", "bytedance/seedance-2"),
    "8": ("Seedance 2.0 Fast", "bytedance/seedance-2-fast"),
    "9": ("Seedance 2.0 Mini", "bytedance/seedance-2-mini"),
}

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


class LegacyTLSAdapter(requests.adapters.HTTPAdapter):
    """Adapter for proxy/TUN routes that require OpenSSL legacy server connect."""

    def _ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
            context.options |= ssl.OP_LEGACY_SERVER_CONNECT
        return context

    def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any) -> None:
        pool_kwargs["ssl_context"] = self._ssl_context()
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        proxy_kwargs["ssl_context"] = self._ssl_context()
        return super().proxy_manager_for(proxy, **proxy_kwargs)


@dataclass
class ProductImage:
    pid: str
    path: Path


@dataclass
class ProductFolder:
    name: str
    path: Path
    images: list[ProductImage]


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "product"


def pid_from_path(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"(_processed|_product|_edited|_clean)$", "", stem, flags=re.I)
    return sanitize_filename(stem)


def collect_images(folder: Path) -> list[ProductImage]:
    images = []
    for item in sorted(folder.iterdir(), key=lambda path: path.name.lower()):
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(ProductImage(pid_from_path(item), item))
    return images


def should_skip_folder(folder: Path) -> bool:
    return folder.name.lower() in {"processed_products", "videos", "__pycache__"}


def discover_product_folders(input_dir: Path) -> list[ProductFolder]:
    input_dir = input_dir.resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(str(input_dir))

    folders: list[ProductFolder] = []
    root_images = collect_images(input_dir)
    if root_images:
        folders.append(ProductFolder(sanitize_filename(input_dir.name), input_dir, root_images))

    for child in sorted([item for item in input_dir.iterdir() if item.is_dir() and not should_skip_folder(item)], key=lambda item: item.name.lower()):
        images = collect_images(child)
        if images:
            folders.append(ProductFolder(sanitize_filename(child.name), child, images))

    return folders


def discover_processed_folders(input_dir: Path) -> list[ProductFolder]:
    input_dir = input_dir.resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(str(input_dir))

    folders: list[ProductFolder] = []
    direct_images = collect_images(input_dir)
    if direct_images:
        name = input_dir.parent.name if input_dir.name.lower() == "processed_products" else input_dir.name
        folders.append(ProductFolder(sanitize_filename(name), input_dir, direct_images))

    for child in sorted([item for item in input_dir.iterdir() if item.is_dir() and not should_skip_folder(item)], key=lambda item: item.name.lower()):
        processed = child / "processed_products"
        if processed.is_dir():
            images = collect_images(processed)
            if images:
                folders.append(ProductFolder(sanitize_filename(child.name), processed, images))
            continue
        images = collect_images(child)
        if images:
            folders.append(ProductFolder(sanitize_filename(child.name), child, images))

    return folders


def desktop_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    return Path.home() / "Desktop"


def default_output_root(input_dir: Path) -> Path:
    return desktop_dir() / f"H返回结果_{sanitize_filename(input_dir.resolve().name)}"


def output_root(args: argparse.Namespace, input_dir: Path) -> Path:
    return Path(args.output_dir).resolve() if args.output_dir else default_output_root(input_dir)


def process_output_dir(args: argparse.Namespace, source_root: Path, folder: ProductFolder, multi_folder: bool) -> Path:
    base = output_root(args, source_root) / "图像"
    return base / folder.name if multi_folder else base


def process_text_output_dir(args: argparse.Namespace, source_root: Path, folder: ProductFolder, multi_folder: bool) -> Path:
    base = output_root(args, source_root) / "文本"
    return base / folder.name if multi_folder else base


def video_output_dir(args: argparse.Namespace, source_root: Path, folder: ProductFolder, multi_folder: bool) -> Path:
    base = output_root(args, source_root) / "视频"
    return base / folder.name if multi_folder else base


def video_text_output_dir(args: argparse.Namespace, source_root: Path, folder: ProductFolder, multi_folder: bool) -> Path:
    base = output_root(args, source_root) / "文本"
    return base / folder.name if multi_folder else base


def clean_api_key(api_key: str) -> str:
    value = (api_key or "").strip().lstrip("\ufeff")
    return "".join(ch for ch in value if ch.isprintable() and ch not in {"\ufeff", "\u200b", "\u200c", "\u200d", "\u2060"})


def get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {clean_api_key(api_key)}",
        "Content-Type": "application/json",
    }


def new_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.verify = False
    proxies = configured_proxies()
    if proxies:
        session.proxies.update(proxies)
    retry = requests.adapters.Retry(total=0)
    adapter = LegacyTLSAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
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
            verify=False,
            attempts=5,
            base_delay=2,
        )
    response.raise_for_status()
    data = response.json()
    if data.get("success") and data.get("data", {}).get("downloadUrl"):
        return data["data"]["downloadUrl"]
    raise RuntimeError(data.get("message") or data.get("msg") or f"Upload failed: {path}")



def describe_secret(value: str) -> str:
    value = clean_api_key(value)
    if not value:
        return "empty"
    tail = value[-6:] if len(value) >= 6 else value
    return f"len={len(value)} tail={tail}"


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
    return ""


def normalize_reverse_model(value: str) -> str:
    model = value.strip().strip("/")
    return REVERSE_MODEL_CHOICES.get(model, model)


def reverse_prompt_with_kie(args: argparse.Namespace, pid: str, image_url: str, meta_prompt_template: str) -> tuple[str, dict[str, Any]]:
    meta_prompt = meta_prompt_template.format(pid=pid, product_id=pid)
    base_url = args.reverse_base_url.rstrip("/") if args.reverse_base_url else KIE_API_HOST
    reverse_model = normalize_reverse_model(args.reverse_model)
    use_responses_api = reverse_model in {"gpt-5-4", "gpt-5-5"} or args.reverse_api == "responses"
    if use_responses_api:
        endpoint = f"{base_url}/codex/v1/responses"
        payload = {
            "model": reverse_model,
            "stream": False,
            "reasoning": {"effort": args.reverse_reasoning_effort},
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": meta_prompt},
                        {"type": "input_image", "image_url": image_url},
                    ],
                }
            ],
        }
    else:
        endpoint = f"{base_url}/{reverse_model}/v1/chat/completions"
        payload = {
            "stream": False,
            "reasoning_effort": args.reverse_reasoning_effort,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": meta_prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
        }
    last_data: dict[str, Any] = {}
    reverse_attempts = 8
    for attempt in range(1, reverse_attempts + 1):
        response = request_with_retry(
            "POST",
            endpoint,
            headers=get_headers(args.api_key),
            json=payload,
            timeout=args.reverse_timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = response.text[:1000]
            transient = (
                response.status_code in {429, 500, 502, 503, 504}
                or "Too many pending requests" in body
                or "Unable to download content" in body
                or "system cpu overloaded" in body
                or "frequency" in body.lower()
                or "retry later" in body.lower()
            )
            if transient and attempt < reverse_attempts:
                delay = min(45, (2 ** attempt) + (attempt * 3))
                print(f"Kie reverse transient error ({attempt}/{reverse_attempts}); retrying in {delay}s: {response.status_code} {body}", flush=True)
                time.sleep(delay)
                continue
            raise RuntimeError(f"Kie reverse request failed: {response.status_code} {body}") from exc
        data = response.json()
        last_data = data
        if use_responses_api:
            content = response_output_text(data)
        else:
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
        if content:
            return str(content).strip(), data
        if attempt < reverse_attempts:
            delay = min(30, 2 ** attempt)
            print(f"Kie reverse response missing content ({attempt}/{reverse_attempts}); retrying in {delay}s", flush=True)
            time.sleep(delay)
    raise RuntimeError(f"Kie reverse response missing content: {last_data}")


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


def host_ips(url: str) -> list[str]:
    host = urlparse(url).hostname or url
    try:
        return sorted({item[4][0] for item in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
    except OSError:
        return []


def is_benchmark_tun_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.version == 4 and ipaddress.ip_address("198.18.0.0") <= ip <= ipaddress.ip_address("198.19.255.255")


def assert_kie_reachable(args: argparse.Namespace) -> None:
    if getattr(args, "skip_preflight", False):
        return
    ips = host_ips(KIE_API_HOST)
    proxies = configured_proxies()
    tun_note = ""
    if any(is_benchmark_tun_ip(ip) for ip in ips):
        tun_note = f" DNS resolved {KIE_API_HOST} to {', '.join(ips)}, which is a 198.18/15 proxy/TUN range."
        if proxies:
            print(f"Kie preflight: fake-ip DNS detected; using configured proxy route for {KIE_API_HOST}.", flush=True)
        else:
            raise RuntimeError(
                "Kie API preflight failed before starting batch work."
                f"{tun_note} No HTTP/HTTPS proxy is configured for this process. "
                "Configure the local proxy route for api.kie.ai, then rerun; completed PID outputs will be skipped automatically. "
                "Use --skip-preflight only if you know this route is healthy."
            )
    try:
        response = request_with_retry(
            "GET",
            KIE_API_HOST,
            attempts=2 if proxies else 1,
            base_delay=1,
            timeout=args.preflight_timeout,
        )
        response.close()
    except requests.RequestException as exc:
        proxy_note = " A configured proxy was detected and tried." if proxies else " No configured proxy was detected."
        raise RuntimeError(
            "Kie API preflight failed before starting batch work."
            f"{tun_note}{proxy_note} Current connection error: {exc}. "
            "Fix the proxy/network route for api.kie.ai, then rerun; completed PID outputs will be skipped automatically."
        ) from exc


def request_with_retry(method: str, url: str, *, attempts: int = 3, base_delay: float = 2.0, **kwargs: Any) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return new_session().request(method, url, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == attempts:
                break
            delay = min(20, base_delay * (2 ** (attempt - 1)))
            print(f"Transient request error ({attempt}/{attempts}); retrying in {delay}s: {exc}", flush=True)
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def submit_job(api_key: str, model: str, input_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    submit_attempts = 8
    data: dict[str, Any] = {}
    for attempt in range(1, submit_attempts + 1):
        with _KIE_SUBMIT_LOCK:
            response = request_with_retry(
                "POST",
                f"{KIE_API_HOST}/api/v1/jobs/createTask",
                headers=get_headers(api_key),
                json={"model": model, "input": input_payload},
                timeout=60,
                attempts=8,
                base_delay=2,
            )
        response.raise_for_status()
        data = response.json()
        if data.get("code") == 200:
            break
        message = str(data.get("msg") or data.get("message") or "")
        transient = any(token in message.lower() for token in ["frequency", "too high", "retry later", "rate limit"])
        if transient and attempt < submit_attempts:
            delay = min(60, 5 * attempt)
            print(f"Kie task submission transient error ({attempt}/{submit_attempts}); retrying in {delay}s: {message}", flush=True)
            time.sleep(delay)
            continue
        raise RuntimeError(message or "Kie task submission failed")
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
    payload: dict[str, Any] = {
        "prompt": prompt,
        "model": VEO_MODEL_MAP[model],
        "aspect_ratio": aspect_ratio,
        "enableTranslation": True,
        "resolution": resolution,
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
    submit_attempts = 8
    data: dict[str, Any] = {}
    for attempt in range(1, submit_attempts + 1):
        with _KIE_SUBMIT_LOCK:
            response = request_with_retry(
                "POST",
                f"{KIE_API_HOST}/api/v1/veo/generate",
                headers=get_headers(api_key),
                json=payload,
                timeout=60,
                attempts=8,
                base_delay=2,
            )
        response.raise_for_status()
        data = response.json()
        if data.get("code") == 200:
            break
        message = str(data.get("msg") or data.get("message") or "")
        transient = any(token in message.lower() for token in ["frequency", "too high", "retry later", "rate limit"])
        if transient and attempt < submit_attempts:
            delay = min(60, 5 * attempt)
            print(f"Kie Veo submission transient error ({attempt}/{submit_attempts}); retrying in {delay}s: {message}", flush=True)
            time.sleep(delay)
            continue
        raise RuntimeError(message or "Kie Veo submission failed")
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


def query_job(api_key: str, task_id: str) -> tuple[str, str, str, dict[str, Any]]:
    response = request_with_retry(
        "GET",
        f"{KIE_API_HOST}/api/v1/jobs/recordInfo",
        headers=get_headers(api_key),
        params={"taskId": task_id},
        timeout=30,
        attempts=5,
        base_delay=1,
    )
    response.raise_for_status()
    raw = response.json()
    if raw.get("code") != 200:
        raise RuntimeError(raw.get("msg") or "Kie query failed")
    data = raw.get("data", {})
    success_flag = data.get("successFlag")
    if success_flag == 1:
        state = "success"
    elif success_flag in {2, 3}:
        state = "fail"
    else:
        state = str(data.get("state") or data.get("status") or "waiting").lower()
    if state in {"succeeded", "completed", "done"}:
        state = "success"
    if state in {"failed", "error", "canceled", "cancelled"}:
        state = "fail"
    error = data.get("failMsg") or data.get("errorMessage") or data.get("message") or ""
    return state, kie_result_url(data, "image"), error, raw


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
    response.raise_for_status()
    raw = response.json()
    if raw.get("code") != 200:
        raise RuntimeError(raw.get("msg") or "Kie Veo query failed")
    data = raw.get("data", {})
    flag = data.get("successFlag")
    if flag == 1:
        state = "success"
    elif flag in {2, 3}:
        state = "fail"
    else:
        state = "waiting"
    error = data.get("errorMessage") or ""
    return state, kie_result_url(data, "video"), error, raw


def wait_for_result(api_key: str, task_id: str, query_type: str, kind: str, timeout: int, poll: int, max_query_errors: int) -> tuple[str, str, dict[str, Any]]:
    deadline = time.time() + timeout
    last_raw: dict[str, Any] = {}
    query_errors = 0
    while time.time() <= deadline:
        time.sleep(poll)
        try:
            if query_type == "veo":
                state, url, error, raw = query_veo(api_key, task_id)
            else:
                state, url, error, raw = query_job(api_key, task_id)
                if kind == "video":
                    url = first_url(raw.get("data", {}), "video")
        except requests.RequestException as exc:
            query_errors += 1
            print(f"{task_id}: query error {query_errors}/{max_query_errors}: {exc}", flush=True)
            if query_errors >= max_query_errors:
                raise RuntimeError(
                    f"Kie query failed {query_errors} times in a row for task {task_id}. "
                    "Stopping early so the batch can be rerun after network recovery."
                ) from exc
            continue
        query_errors = 0
        last_raw = raw
        print(f"{task_id}: {state}", flush=True)
        if state == "success" and url:
            return state, url, raw
        if state == "fail":
            raise RuntimeError(error or f"Kie task failed: {task_id}")
    return "timeout", "", last_raw


def is_video_file(path: Path) -> bool:
    try:
        header = path.read_bytes()[:32]
    except Exception:
        return False
    return (len(header) >= 12 and header[4:8] == b"ftyp") or header.startswith(b"\x1aE\xdf\xa3")


def is_image_file(path: Path) -> bool:
    try:
        header = path.read_bytes()[:16]
    except Exception:
        return False
    return (
        header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith(b"\xff\xd8\xff")
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )


def validate_downloaded_file(path: Path, kind: str, url: str) -> None:
    if kind == "video" and not is_video_file(path):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"Downloaded result is not a valid video file: {url}")
    if kind == "image" and is_video_file(path):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"Downloaded result is a video, not an image: {url}")


def download_file(url: str, path: Path, kind: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 6):
        with request_with_retry("GET", url, stream=True, timeout=180, verify=False) as response:
            response.raise_for_status()
            with path.open("wb") as file_obj:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file_obj.write(chunk)
        if path.exists() and path.stat().st_size > 0:
            validate_downloaded_file(path, kind, url)
            return
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        if attempt < 5:
            delay = min(20, 2 ** attempt)
            print(f"Downloaded empty file ({attempt}/5); retrying in {delay}s", flush=True)
            time.sleep(delay)
    raise RuntimeError(f"Downloaded empty file after retries: {path}")


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


def image_input_payload(model: str, prompt: str, image_url: str, aspect_ratio: str, resolution: str) -> dict[str, Any]:
    aspect_ratio = resolve_aspect_ratio(aspect_ratio)
    resolution = resolve_image_resolution(resolution)
    field = IMAGE_MODEL_PAYLOADS[model]
    payload: dict[str, Any] = {"prompt": prompt}
    if field:
        payload[field] = [image_url]
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
) -> dict[str, Any]:
    aspect_ratio = resolve_aspect_ratio(aspect_ratio)
    image_urls = normalize_media_urls(image_url)
    video_refs = normalize_media_urls(video_urls)
    audio_refs = normalize_media_urls(audio_urls)
    if model == "grok-imagine/text-to-video":
        if image_urls or video_refs or audio_refs:
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
        if len(image_urls) != 1 or video_refs or audio_refs:
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
        if len(image_urls) > 1 or video_refs or audio_refs:
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
        payload = {
            "prompt": prompt,
            "duration": str(duration),
        }
        if image_urls:
            payload["image_urls"] = image_urls
        return payload
    if model in {"bytedance/seedance-2", "bytedance/seedance-2-fast", "bytedance/seedance-2-mini"}:
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


def process_single_product(args: argparse.Namespace, folder: ProductFolder, output_dir: Path, text_dir: Path, product: ProductImage, image_model_label: str, image_model: str, aspect_ratio: str) -> dict[str, Any]:
    print(f"Processing folder {folder.name}: {product.pid}", flush=True)
    output_path = output_dir / f"{product.pid}.png"
    reverse_path = text_dir / f"{product.pid}.reverse.txt"
    json_path = text_dir / f"{product.pid}.image.json"
    if args.force:
        for stale_path in (output_path, reverse_path, json_path):
            try:
                stale_path.unlink(missing_ok=True)
            except Exception as exc:
                print(f"Could not remove stale output for forced image rerun: {stale_path}: {exc}", flush=True)
    if not args.force and output_path.exists() and reverse_path.exists() and json_path.exists():
        print(f"Skipping existing processed image: {product.pid}", flush=True)
        return json.loads(json_path.read_text(encoding="utf-8"))
    source_url = upload_file(args.api_key, product.path)
    if not args.force and reverse_path.exists() and reverse_path.stat().st_size > 0:
        reverse_prompt = reverse_path.read_text(encoding="utf-8").strip()
        reverse_raw = {"reused_reverse_path": str(reverse_path)}
    else:
        reverse_prompt, reverse_raw = reverse_prompt_with_kie(args, product.pid, source_url, args.image_reverse_meta_prompt)
        text_dir.mkdir(parents=True, exist_ok=True)
        reverse_path.write_text(reverse_prompt, encoding="utf-8")
    prompt = build_kie_image_prompt(reverse_prompt, product.pid, args.prompt)
    actual_image_model = resolve_image_generation_model(image_model, bool(source_url))
    task_id, submit_raw = submit_job(
        args.api_key,
        actual_image_model,
        image_input_payload(actual_image_model, prompt, source_url, aspect_ratio, args.image_resolution),
    )
    state, result_url, final_raw = wait_for_result(args.api_key, task_id, "jobs", "image", args.timeout, args.poll, args.max_query_errors)
    if result_url == source_url:
        raise RuntimeError("Kie result URL matched the original source URL; refusing to save an unchanged source image.")
    if result_url:
        download_file(result_url, output_path, "image")
    record = {
        "pid": product.pid,
        "folder": folder.name,
        "source_path": str(product.path),
        "source_url": source_url,
        "reverse_provider": "kie",
        "reverse_source_path": str(product.path),
        "reverse_source_url": source_url,
        "processed_path": str(output_path) if result_url else "",
        "reverse_model": args.reverse_model,
        "image_reverse_meta_prompt": args.image_reverse_meta_prompt,
        "reverse_prompt": reverse_prompt,
        "kie_image_prompt": prompt,
        "image_model_choice": args.image_model,
        "image_model_label": image_model_label,
        "image_model": image_model,
        "actual_image_model": actual_image_model,
        "aspect_ratio": aspect_ratio,
        "task_id": task_id,
        "state": state,
        "result_url": result_url,
        "reverse_raw": reverse_raw,
        "submit": submit_raw,
        "final": final_raw,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    reverse_path.write_text(reverse_prompt, encoding="utf-8")
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
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
                manifest.append(
                    {
                        "pid": product.pid,
                        "folder": folder.name,
                        "source_path": str(product.path),
                        "state": "error",
                        "error": str(exc),
                    }
                )
    manifest.sort(key=lambda item: item.get("pid", ""))
    manifest_path = text_dir / "processed_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "folder": folder.name,
        "source_dir": str(folder.path),
        "processed_dir": str(output_dir),
        "manifest": str(manifest_path),
        "count": len(manifest),
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
                record = {
                    "pid": product.pid,
                    "folder": folder.name,
                    "source_path": str(product.path),
                    "state": "error",
                    "error": str(exc),
                }
            manifests[str(folder.path)].append(record)

    summaries: list[dict[str, Any]] = []
    for key in sorted(folder_outputs, key=lambda item: folder_outputs[item][0].name.lower()):
        folder, output_dir, text_dir = folder_outputs[key]
        manifest = sorted(manifests[key], key=lambda item: item.get("pid", ""))
        manifest_path = text_dir / "processed_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        summaries.append(
            {
                "folder": folder.name,
                "source_dir": str(folder.path),
                "text_dir": str(text_dir),
                "image_dir": str(output_dir),
                "processed_dir": str(output_dir),
                "manifest": str(manifest_path),
                "count": len(manifest),
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
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_root": str(root), "text_dir": str(root / "文本"), "image_dir": str(root / "图像"), "video_dir": str(root / "视频"), "batch_manifest": str(summary_path), "folders": summaries}, ensure_ascii=False, indent=2))
    return 0


def submit_video(args: argparse.Namespace, pid: str, processed_image: Path, output_dir: Path, text_dir: Path) -> dict[str, Any]:
    video_model_label, video_model = resolve_video_model(args.video_model)
    aspect_ratio = resolve_aspect_ratio(args.aspect_ratio)
    output_path = output_dir / f"{pid}.mp4"
    reverse_path = text_dir / f"{pid}.video_reverse.txt"
    json_path = text_dir / f"{pid}.video.json"
    if args.force:
        for stale_path in (output_path, reverse_path, json_path):
            try:
                stale_path.unlink(missing_ok=True)
            except Exception as exc:
                print(f"Could not remove stale output for forced video rerun: {stale_path}: {exc}", flush=True)
    if not args.force and output_path.exists() and reverse_path.exists() and json_path.exists():
        print(f"Skipping existing video: {pid}", flush=True)
        return json.loads(json_path.read_text(encoding="utf-8"))
    image_url = upload_file(args.api_key, processed_image)
    if not args.force and reverse_path.exists() and reverse_path.stat().st_size > 0:
        reverse_prompt = reverse_path.read_text(encoding="utf-8").strip()
        reverse_raw = {"reused_reverse_path": str(reverse_path)}
    else:
        reverse_prompt, reverse_raw = reverse_prompt_with_kie(args, pid, image_url, args.video_reverse_meta_prompt)
        text_dir.mkdir(parents=True, exist_ok=True)
        reverse_path.write_text(reverse_prompt, encoding="utf-8")
    prompt = build_kie_video_prompt(reverse_prompt, pid, args.prompt)
    actual_video_model = resolve_video_generation_model(video_model, bool(image_url))
    duration = resolve_video_duration(args.duration, actual_video_model)
    if actual_video_model in VEO_MODEL_MAP:
        task_id, submit_raw = submit_veo(args.api_key, actual_video_model, prompt, image_url, aspect_ratio, args.video_resolution)
        query_type = "veo"
    else:
        task_id, submit_raw = submit_job(
            args.api_key,
            actual_video_model,
            video_input_payload(actual_video_model, prompt, image_url, aspect_ratio, args.video_resolution, duration),
        )
        query_type = "jobs"
    state, video_url, final_raw = wait_for_result(args.api_key, task_id, query_type, "video", args.timeout, args.poll, args.max_query_errors)
    if video_url:
        download_file(video_url, output_path, "video")
    record = {
        "pid": pid,
        "processed_image": str(processed_image),
        "processed_image_url": image_url,
        "video_reverse_provider": "kie",
        "video_path": str(output_path) if video_url else "",
        "video_reverse_model": args.reverse_model,
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
        "task_id": task_id,
        "state": state,
        "video_url": video_url,
        "video_reverse_raw": reverse_raw,
        "submit": submit_raw,
        "final": final_raw,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    reverse_path.write_text(reverse_prompt, encoding="utf-8")
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
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
                record = {
                    "pid": product.pid,
                    "processed_image": str(product.path),
                    "state": "error",
                    "error": str(exc),
                }
            manifests[str(folder.path)].append(record)

    summaries: list[dict[str, Any]] = []
    for key in sorted(folder_outputs, key=lambda item: folder_outputs[item][0].name.lower()):
        folder, output_dir, text_dir = folder_outputs[key]
        records = sorted(manifests[key], key=lambda item: item.get("pid", ""))
        summary_path = text_dir / "video_manifest.json"
        summary_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        summaries.append(
            {
                "folder": folder.name,
                "processed_dir": str(folder.path),
                "text_dir": str(text_dir),
                "video_dir": str(output_dir),
                "manifest": str(summary_path),
                "count": len(records),
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
    batch_summary_path.parent.mkdir(parents=True, exist_ok=True)
    batch_summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_root": str(root), "text_dir": str(root / "文本"), "image_dir": str(root / "图像"), "video_dir": str(root / "视频"), "processed_input_dir": str(processed_input_dir), "batch_manifest": str(batch_summary_path), "folders": summaries}, ensure_ascii=False, indent=2))
    return 0


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
    video_model_ids = {model for _label, model in VIDEO_MODEL_CHOICES.values()}

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
        choices=sorted(set(VIDEO_MODEL_CHOICES) | video_model_ids | set(VEO_MODEL_MAP)),
        help="Video model choice: 1=Grok Imagine, 2=Grok 1.5 Preview, 3=Veo3.1 Lite, 4=Veo3.1 Fast, 5=Veo3.1 Quality, 6=Gemini Omni, 7=Seedance 2.0, 8=Seedance 2.0 Fast, 9=Seedance 2.0 Mini. The script chooses image/text endpoint from whether an input image is present.",
    )
    video.add_argument("--aspect-ratio", default="2", choices=["1", "2", "9:16", "16:9"], help="Aspect ratio: 1=9:16, 2=16:9.")
    video.add_argument("--video-resolution", default="720p", choices=["480p", "720p", "1080p"])
    video.add_argument("--duration", type=int, default=0, choices=[0] + VIDEO_DURATION_CHOICES, help="Video duration in seconds. 0=auto; only confirmed model maximums are blocked before submission.")

    args = parser.parse_args(argv)
    args.api_key = load_api_key(args.api_key)
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
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = parse_args(argv)
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
