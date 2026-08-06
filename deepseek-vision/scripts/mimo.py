#!/usr/bin/env python3
"""Cross-platform MiMo V2.5 helper for the deepseek-vision skill."""

import argparse
import base64
import getpass
import json
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
import wave
from contextlib import contextmanager
from datetime import date
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1"
TOKEN_PLAN_EXAMPLE = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.5"
ASR_MODEL = "mimo-v2.5-asr"
BASE64_LIMIT = 50 * 1024 * 1024
PAYG_LABEL = "按量付费"
TOKEN_LABEL = "Token Plan"
_SSL_CONTEXT = None
DEFAULT_TIMEOUT = 180


class _RequestTimeout(Exception):
    pass


def _request_timeout_call(seconds, func):
    if hasattr(signal, "SIGALRM"):
        def _handler(_signum, _frame):
            raise _RequestTimeout()

        previous = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(seconds)
        try:
            return func()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    socket.setdefaulttimeout(seconds)
    return func()


def _effective_timeout(override=None):
    value = override
    if value is None:
        raw = os.environ.get("MIMO_TIMEOUT", "").strip()
        value = int(raw) if raw else DEFAULT_TIMEOUT
    if value < 1:
        raise MiMoError("timeout 必须大于 0", code="usage")
    return value

EXT_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "wmv": "video/x-ms-wmv",
}


class MiMoError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _default_pricing():
    return {
        DEFAULT_MODEL: {
            "input_uncached_cny_per_mtok": 1.0,
            "input_cached_cny_per_mtok": 0.02,
            "output_cny_per_mtok": 2.0,
        },
        ASR_MODEL: {
            "cny_per_audio_hour": 0.5,
        },
    }


def _default_config():
    return {
        "active_plan": "",
        "payg": {"api_key": "", "base_url": DEFAULT_BASE_URL},
        "token": {"api_key": "", "base_url": ""},
        "pricing": _default_pricing(),
        "pricing_updated": "2026-08-03",
    }


def _config_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "deepseek-vision"


def _credentials_path():
    return _config_dir() / "credentials.json"


def _lock_path():
    return _config_dir() / ".credentials.lock"


def _jobs_dir():
    return _config_dir() / "jobs"


def _job_path(job_id):
    return _jobs_dir() / f"{job_id}.json"


def _use_file_backend():
    return os.environ.get("MIMO_CREDENTIAL_BACKEND", "auto").strip().lower() == "file"


def _secure_mkdir(path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def _sanitize_text(text, secrets=()):
    text = text or ""
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "***")
    return " ".join(text.split())[:500]


def _ssl_context():
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        candidates = [
            os.environ.get("SSL_CERT_FILE"),
            "/etc/ssl/cert.pem",
            "/etc/pki/tls/certs/ca-bundle.crt",
            "/etc/ssl/certs/ca-certificates.crt",
        ]
        for path in candidates:
            if path and Path(path).exists():
                _SSL_CONTEXT = ssl.create_default_context(cafile=path)
                break
        else:
            _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


def _mask_value(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def _mask_url(value):
    if not value:
        return ""
    scheme = value.split("://", 1)[0] if "://" in value else "http"
    return f"{scheme}://***"


def _restrict_windows_file(path):
    user = os.environ.get("USERNAME")
    if not user:
        return
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(R,W)"],
        capture_output=True,
        text=True,
    )


KEYCHAIN_SERVICE = "deepseek-vision"
KEYCHAIN_CHUNK_PREFIX = "deepseek-vision.chunk."
KEYCHAIN_CHUNK_SIZE = 100
MAX_KEYCHAIN_CHUNKS = 100


def _keychain_delete(account):
    subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-a",
            account,
            "-s",
            KEYCHAIN_SERVICE,
        ],
        capture_output=True,
        text=True,
    )


def _keychain_read():
    chunks = []
    for index in range(MAX_KEYCHAIN_CHUNKS):
        proc = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                f"{KEYCHAIN_CHUNK_PREFIX}{index}",
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            break
        value = proc.stdout.strip()
        if not value:
            break
        chunks.append(value)
    if chunks:
        return "".join(chunks)
    proc = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            "default",
            "-s",
            KEYCHAIN_SERVICE,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def _keychain_write(payload):
    try:
        compact = json.dumps(json.loads(payload), ensure_ascii=False, separators=(",", ":"))
    except (ValueError, TypeError):
        compact = " ".join(payload.split())
    chunks = [compact[index:index + KEYCHAIN_CHUNK_SIZE] for index in range(0, len(compact), KEYCHAIN_CHUNK_SIZE)]
    _keychain_delete("default")
    for index in range(MAX_KEYCHAIN_CHUNKS):
        _keychain_delete(f"{KEYCHAIN_CHUNK_PREFIX}{index}")
    for index, chunk in enumerate(chunks):
        proc = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-a",
                f"{KEYCHAIN_CHUNK_PREFIX}{index}",
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            input=f"{chunk}\n{chunk}\n",
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise MiMoError(
                f"无法写入 macOS Keychain: {_sanitize_text(proc.stderr.strip())}",
                code="keychain",
            )


def _dpapi_read():
    secret = _config_dir() / "secret"
    if not secret.exists():
        return None
    command = (
        "$e = Get-Content -LiteralPath $env:MIMO_SECRET_FILE -Raw; "
        "$s = $e | ConvertTo-SecureString; "
        "$b = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); "
        "try { [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } "
        "finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }"
    )
    env = {**os.environ, "MIMO_SECRET_FILE": str(secret)}
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise MiMoError(
            f"无法读取 Windows 凭据: {_sanitize_text(proc.stderr.strip())}",
            code="dpapi",
        )
    value = proc.stdout.strip()
    return value or None


def _dpapi_write(payload):
    secret = _config_dir() / "secret"
    _secure_mkdir(_config_dir())
    command = (
        "$payload = [Console]::In.ReadToEnd(); "
        "$s = ConvertTo-SecureString $payload -AsPlainText -Force; "
        "$e = ConvertFrom-SecureString $s; "
        "Set-Content -LiteralPath $env:MIMO_SECRET_FILE -Value $e -NoNewline"
    )
    env = {
        **os.environ,
        "MIMO_SECRET_FILE": str(secret),
    }
    env.pop("MIMO_CREDENTIALS_JSON", None)
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise MiMoError(
            f"无法写入 Windows 凭据: {_sanitize_text(proc.stderr.strip())}",
            code="dpapi",
        )


def _read_file():
    path = _credentials_path()
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _write_file(payload):
    path = _credentials_path()
    _secure_mkdir(_config_dir())
    tmp = path.with_name(path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600) if os.name != "nt" else os.open(tmp, flags)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
    os.replace(tmp, path)
    if os.name == "nt":
        _restrict_windows_file(path)


def _remove_file():
    try:
        _credentials_path().unlink(missing_ok=True)
    except OSError:
        pass


@contextmanager
def _config_lock():
    _secure_mkdir(_config_dir())
    with open(_lock_path(), "a+b") as handle:
        if fcntl:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            yield


def _write_job_file(job):
    path = _job_path(job["id"])
    _secure_mkdir(_jobs_dir())
    tmp = path.with_name(path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600) if os.name != "nt" else os.open(tmp, flags)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(job, ensure_ascii=False))
    os.replace(tmp, path)


def _read_job(job_id):
    path = _job_path(job_id)
    if not path.exists():
        raise MiMoError(f"任务不存在：{job_id}", code="job_not_found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MiMoError(f"任务文件损坏或不可读：{job_id}", code="job_corrupt") from exc


def _job_stale_after(job):
    return _effective_timeout(job.get("timeout")) * 2 + 120


def _claim_next_job():
    _secure_mkdir(_jobs_dir())
    for path in sorted(_jobs_dir().glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        status = job.get("status")
        if status not in ("pending", "running"):
            continue
        if status == "running":
            started = job.get("started") or 0
            if time.time() - started <= _job_stale_after(job):
                continue
        job["status"] = "running"
        job["started"] = time.time()
        _write_job_file(job)
        return job
    return None


def _spawn_worker():
    script = Path(__file__).resolve()
    _secure_mkdir(_config_dir())
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, str(script), "worker"], **kwargs)
    except OSError as exc:
        raise MiMoError(
            f"无法启动后台任务：{_sanitize_text(str(exc))}",
            code="worker_spawn",
        )


def _job_command(job):
    script = Path(__file__).resolve()
    if job.get("command") == "analyze":
        cmd = [
            sys.executable,
            str(script),
            "analyze",
            "--max-tokens",
            str(job.get("max_tokens", 1024)),
            "--fps",
            str(job.get("fps", 2.0)),
            "--resolution",
            str(job.get("resolution", "default")),
        ]
        for file_path in job.get("files", []):
            cmd += ["--files", file_path]
        for url in job.get("urls", []):
            cmd += ["--urls", url]
        if job.get("kind"):
            cmd += ["--kind", job["kind"]]
        if job.get("timeout"):
            cmd += ["--timeout", str(job["timeout"])]
        cmd += ["--prompt", job.get("prompt") or "请基于附件内容直接、简洁地回答。"]
        return cmd
    cmd = [
        sys.executable,
        str(script),
        "asr",
        "--file",
        str(job.get("file", "")),
        "--language",
        str(job.get("language", "auto")),
        "--max-tokens",
        str(job.get("max_tokens", 2048)),
    ]
    if job.get("timeout"):
        cmd += ["--timeout", str(job["timeout"])]
    return cmd


def _load_raw_config():
    if sys.platform == "darwin" and not _use_file_backend():
        try:
            value = _keychain_read()
        except MiMoError:
            value = None
        if value:
            return value
    if os.name == "nt" and not _use_file_backend():
        try:
            value = _dpapi_read()
        except MiMoError:
            value = None
        if value:
            return value
    return _read_file()


def _decode_config_raw(raw):
    candidates = [raw]
    try:
        candidates.append(bytes.fromhex(raw.strip()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        pass
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise MiMoError("全局配置损坏，请重新运行 configure", code="config")


def _merge_defaults(cfg):
    defaults = _default_config()
    for key, default_value in defaults.items():
        if key not in cfg or cfg[key] is None:
            cfg[key] = default_value
        elif isinstance(default_value, dict) and isinstance(cfg[key], dict):
            merged = dict(default_value)
            merged.update({k: v for k, v in cfg[key].items() if v not in (None, "")})
            cfg[key] = merged
    return cfg


def load_config():
    raw = _load_raw_config()
    if not raw:
        cfg = _default_config()
    else:
        try:
            cfg = _decode_config_raw(raw)
        except MiMoError:
            fallback = _read_file()
            if not fallback:
                raise
            cfg = _decode_config_raw(fallback)
    file_raw = _read_file()
    if file_raw:
        try:
            file_cfg = _decode_config_raw(file_raw)
            if file_cfg.get("saved_at", 0) > cfg.get("saved_at", 0):
                cfg = file_cfg
        except MiMoError:
            pass
    return _merge_defaults(cfg)


def save_config(cfg):
    cfg["saved_at"] = time.time()
    payload = json.dumps(cfg, ensure_ascii=False, indent=2)
    with _config_lock():
        if sys.platform == "darwin" and not _use_file_backend():
            try:
                _keychain_write(payload)
            except MiMoError:
                pass
        if os.name == "nt" and not _use_file_backend():
            try:
                _dpapi_write(payload)
            except MiMoError:
                pass
        _write_file(payload)


def _plan_credentials(cfg, plan):
    return cfg.get(plan) or {}


def active_plan(cfg):
    plan = cfg.get("active_plan") or ""
    return plan if plan in ("payg", "token") else ""


def active_credentials(cfg):
    plan = active_plan(cfg)
    creds = _plan_credentials(cfg, plan)
    if creds.get("api_key") and (plan != "token" or creds.get("base_url")):
        return creds
    return None


def _env_credentials(plan):
    key = os.environ.get("MIMO_API_KEY", "").strip()
    url = os.environ.get("MIMO_BASE_URL", "").strip()
    if not key:
        return None
    if plan == "payg":
        url = url or DEFAULT_BASE_URL
    if plan == "token" and not url:
        return None
    return {"api_key": key, "base_url": url}


def _stdin_tty():
    return sys.stdin is not None and sys.stdin.isatty()


def _choose_plan_interactively():
    print("请选择配置方式：", file=sys.stderr)
    print("1) 按量付费 API Key（sk-xxxxx）", file=sys.stderr)
    print("2) Token Plan（tp-xxxxx + 专属 Base URL）", file=sys.stderr)
    choice = input("请输入 1 或 2: ").strip()
    return {"1": "payg", "2": "token"}.get(choice)


def _validate_prefix(plan, key):
    if plan == "payg" and key.startswith("tp-"):
        raise MiMoError(
            f"key 以 tp- 开头，看起来是 {TOKEN_LABEL}；请使用 --plan token"
        )
    if plan == "token" and key.startswith("sk-"):
        raise MiMoError(
            f"key 以 sk- 开头，看起来是 {PAYG_LABEL}；请使用 --plan payg"
        )


def _write_curl_config(key, auth_header):
    header = f"api-key: {key}" if auth_header == "api-key" else f"Authorization: Bearer {key}"
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        prefix="mimo-curl-",
    )
    handle.write(f'header = "{header}"\n')
    handle.close()
    if os.name != "nt":
        os.chmod(handle.name, 0o600)
    return handle.name


def _http_json(url, credentials, payload=None, method="POST", retries=2, auth_header="api-key", timeout=None):
    timeout = _effective_timeout(timeout)
    key = credentials.get("api_key", "")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    curl = shutil.which("curl")
    use_curl = curl and os.environ.get("MIMO_USE_CURL", "").strip().lower() in ("1", "true")
    if use_curl:
        config_path = _write_curl_config(key, auth_header)
        try:
            cmd = [
                curl,
                "--config",
                config_path,
                "--silent",
                "--show-error",
                "--max-time",
                str(timeout),
                "--connect-timeout",
                "15",
                "--write-out",
                "\n%{http_code}",
                "-X",
                method,
            ]
            cmd += ["-H", "Content-Type: application/json"]
            if data is not None:
                cmd += ["--data-binary", "@-"]
            cmd.append(url)

            last_error = None
            for attempt in range(retries + 1):
                try:
                    proc = subprocess.run(
                        cmd,
                        input=data,
                        capture_output=True,
                        timeout=timeout + 5,
                    )
                except subprocess.TimeoutExpired:
                    raise MiMoError(
                        f"请求超时（超过 {timeout} 秒），已停止；可提高超时（MIMO_TIMEOUT 或 --timeout）后重试",
                        code="timeout",
                    )

                output = proc.stdout.decode("utf-8", errors="replace")
                if proc.returncode != 0:
                    stderr = proc.stderr.decode("utf-8", errors="replace")
                    raw_error = stderr or output
                    if "timed out" in raw_error.lower() or "timeout" in raw_error.lower():
                        raise MiMoError(
                            f"请求超时（超过 {timeout} 秒），已停止；可提高超时（MIMO_TIMEOUT 或 --timeout）后重试",
                            code="timeout",
                        )
                    message = (
                        "网络错误: "
                        + _sanitize_text(raw_error, [key, credentials.get("base_url", "")])
                    )
                    last_error = MiMoError(message, code="network")
                    if attempt < retries:
                        time.sleep(1 + attempt)
                        continue
                    raise last_error

                body = output
                status = 0
                if "\n" in output:
                    body, status_raw = output.rsplit("\n", 1)
                    try:
                        status = int(status_raw.strip())
                    except ValueError:
                        status = 0

                if status >= 400:
                    message = f"HTTP {status}: {_sanitize_text(body, [key, credentials.get('base_url', '')])}"
                    last_error = MiMoError(message, code=status)
                    if status in (429, 500, 502, 503, 504) and attempt < retries:
                        time.sleep(1 + attempt)
                        continue
                    raise last_error

                try:
                    return json.loads(body), status or 200
                except json.JSONDecodeError:
                    message = f"响应解析失败: {_sanitize_text(body, [key, credentials.get('base_url', '')])}"
                    last_error = MiMoError(message, code="parse")
                    if attempt < retries:
                        time.sleep(1 + attempt)
                        continue
                    raise last_error
            raise last_error or MiMoError("请求失败", code="unknown")
        finally:
            try:
                os.unlink(config_path)
            except OSError:
                pass

    headers = {"Content-Type": "application/json"}
    if auth_header == "api-key":
        headers["api-key"] = key
    else:
        headers["Authorization"] = f"Bearer {key}"
    last_error = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with _request_timeout_call(
                timeout,
                lambda: urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()),
            ) as response:
                body = response.read().decode("utf-8", errors="replace")
                return json.loads(body), response.status
        except _RequestTimeout:
            raise MiMoError(
                f"请求超时（超过 {timeout} 秒），已停止；可提高超时（MIMO_TIMEOUT 或 --timeout）后重试",
                code="timeout",
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = f"HTTP {exc.code}: {_sanitize_text(body, [key, credentials.get('base_url', '')])}"
            last_error = MiMoError(message, code=exc.code)
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1 + attempt)
                continue
            raise last_error
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raw_error = str(exc)
            if isinstance(exc, TimeoutError) or "timed out" in raw_error.lower() or "timeout" in raw_error.lower():
                raise MiMoError(
                    f"请求超时（超过 {timeout} 秒），已停止；可提高超时（MIMO_TIMEOUT 或 --timeout）后重试",
                    code="timeout",
                )
            message = f"网络错误: {_sanitize_text(raw_error, [key, credentials.get('base_url', '')])}"
            last_error = MiMoError(message, code="network")
            if attempt < retries:
                time.sleep(1 + attempt)
                continue
            raise last_error
    raise MiMoError("请求失败", code="unknown")


def chat_completions(credentials, payload, timeout=None):
    url = credentials["base_url"].rstrip("/") + "/chat/completions"
    last_error = None
    for auth_header in ("api-key", "bearer"):
        try:
            return _http_json(url, credentials, payload=payload, auth_header=auth_header, timeout=timeout)
        except MiMoError as exc:
            if exc.code in (401, 403):
                last_error = exc
                continue
            raise
    raise last_error or MiMoError("认证失败", code=401)


def list_models(credentials, timeout=None):
    url = credentials["base_url"].rstrip("/") + "/models"
    last_error = None
    for auth_header in ("api-key", "bearer"):
        try:
            data, _ = _http_json(
                url,
                credentials,
                method="GET",
                retries=1,
                auth_header=auth_header,
                timeout=timeout,
            )
            if isinstance(data, dict):
                return data.get("data") or []
            if isinstance(data, list):
                return data
            return []
        except MiMoError as exc:
            if exc.code in (401, 403):
                last_error = exc
                continue
            if exc.code in (404, 405):
                return []
            raise
    raise last_error or MiMoError("认证失败", code=401)


def _data_uri(path):
    ext = path.suffix.lower().lstrip(".")
    mime = EXT_MIME.get(ext)
    if not mime:
        raise MiMoError(
            f"不支持的媒体格式 .{ext or '?'}：{path}；支持 png/jpg/gif/webp/bmp、mp3/wav/flac/m4a/ogg、mp4/mov/avi/wmv"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise MiMoError(f"无法读取文件 {path}：{exc}", code="file") from exc
    encoded = base64.b64encode(data).decode("ascii")
    if len(encoded) > BASE64_LIMIT:
        raise MiMoError(
            f"文件 Base64 超过 50MB 限制：{path}（Base64 约 {len(encoded)} 字节）；请压缩、转码或改用公网 URL"
        )
    return f"data:{mime};base64,{encoded}", mime


def _part_for_mime(mime, data, fps, resolution):
    if mime.startswith("image/"):
        return {"type": "image_url", "image_url": {"url": data}}
    if mime.startswith("audio/"):
        return {"type": "input_audio", "input_audio": {"data": data}}
    if mime.startswith("video/"):
        return {
            "type": "video_url",
            "video_url": {"url": data},
            "fps": fps,
            "media_resolution": resolution,
        }
    raise MiMoError(f"未知媒体类型 {mime}")


def _file_parts(paths, fps, resolution):
    parts = []
    for raw_path in paths:
        data_uri, mime = _data_uri(Path(raw_path))
        parts.append(_part_for_mime(mime, data_uri, fps, resolution))
    return parts


def _url_parts(urls, kind, fps, resolution):
    parts = []
    for url in urls:
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
        mime = EXT_MIME.get(ext)
        if not mime:
            if kind == "image":
                mime = "image/jpeg"
            elif kind == "audio":
                mime = "audio/mpeg"
            elif kind == "video":
                mime = "video/mp4"
            else:
                raise MiMoError(
                    f"无法从 URL 判断媒体类型：{url}；请补充 --kind image|audio|video"
                )
        parts.append(_part_for_mime(mime, url, fps, resolution))
    return parts


def _extract_usage(data):
    usage = data.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "cached_tokens": prompt_details.get("cached_tokens", 0),
        "image_tokens": prompt_details.get("image_tokens"),
        "audio_tokens": prompt_details.get("audio_tokens"),
        "video_tokens": prompt_details.get("video_tokens"),
        "reasoning_tokens": completion_details.get("reasoning_tokens"),
    }


def _extract_content(data):
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    reasoning = message.get("reasoning_content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        content = "".join(parts)
    if content is None or content == "":
        if reasoning:
            return reasoning, True
        return "", False
    return content, False


def _finish_reason(data):
    choice = (data.get("choices") or [{}])[0]
    return choice.get("finish_reason")


def _chat_with_retry(credentials, body, max_tokens, timeout=None):
    data, _ = chat_completions(credentials, body, timeout=timeout)
    current_max = max_tokens
    cap = max(4096, max_tokens * 2)
    for _ in range(2):
        if _finish_reason(data) != "length" or current_max >= cap:
            break
        current_max = min(current_max * 2, cap)
        body["max_completion_tokens"] = current_max
        data, _ = chat_completions(credentials, body, timeout=timeout)
    return data


def _audio_duration(path):
    ext = path.suffix.lower().lstrip(".")
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            proc = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return float(proc.stdout.strip())
        except (OSError, ValueError):
            pass
    if ext == "wav":
        try:
            with wave.open(str(path), "rb") as audio:
                rate = float(audio.getframerate() or 1)
                return audio.getnframes() / rate
        except (OSError, wave.Error, ZeroDivisionError):
            pass
    return None


def _cost_for(plan, model, usage, duration, pricing):
    if plan != "payg":
        return None, None
    rates = pricing.get(model) or pricing.get(DEFAULT_MODEL) or {}
    if model == ASR_MODEL:
        rate = rates.get("cny_per_audio_hour")
        if rate is None or duration is None:
            return None, "金额以官方账单为准"
        return round(duration / 3600.0 * rate, 4), None
    input_rate = rates.get("input_uncached_cny_per_mtok")
    cached_rate = rates.get("input_cached_cny_per_mtok")
    output_rate = rates.get("output_cny_per_mtok")
    if input_rate is None or cached_rate is None or output_rate is None:
        return None, "缺少价格配置，金额以官方账单为准"
    prompt = usage.get("prompt_tokens", 0)
    cached = usage.get("cached_tokens", 0)
    uncached = max(prompt - cached, 0)
    cost = (
        uncached / 1_000_000.0 * input_rate
        + cached / 1_000_000.0 * cached_rate
        + usage.get("completion_tokens", 0) / 1_000_000.0 * output_rate
    )
    return round(cost, 4), None


def _mask_media(value):
    if isinstance(value, dict):
        return {key: _mask_media(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_media(item) for item in value]
    if isinstance(value, str) and value.startswith("data:"):
        return "data:<media>;base64,***"
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(value)
        if parsed.query:
            return urllib.parse.urlunparse(parsed._replace(query="***"))
    return value


def _print_dry_run(command, plan, credentials, body, extra=None):
    output = {
        "ok": True,
        "command": command,
        "dry_run": True,
        "plan": plan,
        "base_url": _mask_url(credentials.get("base_url", "")),
        "request": _mask_media(body),
    }
    if extra:
        output.update(extra)
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_configure(args):
    plan = args.plan
    if not plan:
        if not _stdin_tty():
            raise MiMoError(
                "请指定 --plan payg 或 --plan token；也可交互式运行 configure 选择",
                code="usage",
            )
        plan = _choose_plan_interactively()
        if not plan:
            raise MiMoError("未选择有效的配置方式", code="usage")

    if plan == "payg":
        base_url = args.base_url or os.environ.get("MIMO_BASE_URL", "").strip() or DEFAULT_BASE_URL
    else:
        base_url = args.base_url or os.environ.get("MIMO_BASE_URL", "").strip()
        if not base_url and _stdin_tty():
            print(
                f"Token Plan 专属 Base URL 请从 Token Plan 页面复制（示例：{TOKEN_PLAN_EXAMPLE}，以页面显示为准）",
                file=sys.stderr,
            )
            base_url = input("专属 Base URL: ").strip()
        if not base_url:
            raise MiMoError(
                "Token Plan 需要专属 Base URL；请从 Token Plan 页面复制后通过 --base-url 提供",
                code="usage",
            )

    key = os.environ.get("MIMO_API_KEY", "").strip()
    if not key and _stdin_tty():
        key = getpass.getpass(f"请输入 {TOKEN_LABEL if plan == 'token' else PAYG_LABEL} API Key（输入不回显）: ").strip()
    if not key:
        raise MiMoError(
            "未提供 API Key；请通过 MIMO_API_KEY 环境变量提供，或交互式运行 configure",
            code="usage",
        )
    _validate_prefix(plan, key)

    cfg = load_config()
    cfg[plan] = {"api_key": key, "base_url": base_url}
    cfg["active_plan"] = plan
    save_config(cfg)
    print(
        json.dumps(
            {
                "ok": True,
                "command": "configure",
                "plan": plan,
                "configured": True,
                "next": "run check to verify",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_use(args):
    cfg = load_config()
    creds = _plan_credentials(cfg, args.plan)
    missing = not creds.get("api_key") or (args.plan == "token" and not creds.get("base_url"))
    if missing:
        env_creds = _env_credentials(args.plan)
        if env_creds and (args.plan == "payg" or env_creds.get("base_url")):
            cfg[args.plan] = env_creds
        else:
            label = TOKEN_LABEL if args.plan == "token" else PAYG_LABEL
            raise MiMoError(
                f"{label} 尚未配置；请先运行 configure --plan {args.plan} 配置一次",
                code="not_configured",
            )
    cfg["active_plan"] = args.plan
    save_config(cfg)
    print(
        json.dumps(
            {
                "ok": True,
                "command": "use",
                "active_plan": args.plan,
                "switched": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_status(args):
    cfg = load_config()
    plan = active_plan(cfg)
    creds = _plan_credentials(cfg, plan)
    print(
        json.dumps(
            {
                "ok": True,
                "command": "status",
                "active_plan": plan or None,
                "payg_configured": bool(cfg.get("payg", {}).get("api_key")),
                "token_configured": bool(cfg.get("token", {}).get("api_key")),
                "active_key": _mask_value(creds.get("api_key", "")),
                "active_base_url": _mask_url(creds.get("base_url", "")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_check(args):
    cfg = load_config()
    plan = active_plan(cfg)
    creds = active_credentials(cfg)
    if not creds:
        raise MiMoError("尚未配置 active plan；请先运行 configure", code="not_configured")
    models = list_models(creds)
    model_ids = []
    for item in models or []:
        if isinstance(item, dict):
            model_ids.append(str(item.get("id") or ""))
        elif isinstance(item, str):
            model_ids.append(item)
    has_v25 = DEFAULT_MODEL in model_ids
    has_asr = ASR_MODEL in model_ids
    print(
        json.dumps(
            {
                "ok": True,
                "command": "check",
                "plan": plan,
                "models_listed": bool(model_ids),
                "models": sorted(set(model_ids))[:50],
                "mimo-v2.5": has_v25,
                "mimo-v2.5-asr": has_asr,
                "base_url": _mask_url(creds.get("base_url", "")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_diagnose(args):
    cfg = load_config()
    plan = active_plan(cfg)
    creds = active_credentials(cfg)
    result = {
        "ok": True,
        "command": "diagnose",
        "active_plan": plan or None,
        "config_ok": bool(creds),
        "dns_ok": None,
        "network_ok": None,
    }
    if not creds:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    host = urllib.parse.urlparse(creds.get("base_url", "")).hostname
    if host:
        try:
            socket.getaddrinfo(host, 443)
            result["dns_ok"] = True
        except Exception as exc:
            result["dns_ok"] = False
            result["dns_error"] = _sanitize_text(str(exc), [creds.get("base_url", "")])
    try:
        models = list_models(creds)
        model_ids = []
        for item in models or []:
            if isinstance(item, dict):
                model_ids.append(str(item.get("id") or ""))
            elif isinstance(item, str):
                model_ids.append(item)
        result["network_ok"] = True
        result["models"] = sorted(set(model_ids))[:50]
    except MiMoError as exc:
        result["network_ok"] = False
        result["network_error"] = str(exc)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_poll(args):
    deadline = time.time() + args.wait
    while True:
        job = _read_job(args.job)
        status = job.get("status")
        if status in ("done", "error"):
            result = job.get("result") or {}
            try:
                _job_path(args.job).unlink(missing_ok=True)
            except OSError:
                pass
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if status == "running":
            started = job.get("started") or 0
            if time.time() - started > _job_stale_after(job):
                with _config_lock():
                    fresh = _read_job(args.job)
                    if fresh.get("status") == "running":
                        fresh["status"] = "pending"
                        fresh.pop("started", None)
                        _write_job_file(fresh)
                _spawn_worker()
                continue
        if time.time() >= deadline:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "poll",
                        "job_id": args.job,
                        "status": status,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        time.sleep(1)


def cmd_jobs(args):
    _secure_mkdir(_jobs_dir())
    jobs = []
    now = time.time()
    for path in sorted(_jobs_dir().glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        status = job.get("status")
        if status in ("done", "error"):
            finished = job.get("finished") or job.get("created") or 0
            if now - finished > 86400:
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
        jobs.append(
            {
                "job_id": job.get("id"),
                "command": job.get("command"),
                "status": status,
                "created": job.get("created"),
            }
        )
    print(
        json.dumps(
            {"ok": True, "command": "jobs", "jobs": jobs},
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_worker(args):
    while True:
        with _config_lock():
            job = _claim_next_job()
        if not job:
            break
        job_id = job["id"]
        job_timeout = _effective_timeout(job.get("timeout"))
        try:
            proc = subprocess.run(
                _job_command(job),
                capture_output=True,
                text=True,
                timeout=job_timeout * 2 + 60,
            )
            output = (proc.stdout or "").strip()
            try:
                result = json.loads(output)
            except json.JSONDecodeError:
                result = {
                    "ok": False,
                    "error": _sanitize_text(output or proc.stderr),
                    "code": "worker_parse",
                }
            if not result.get("ok"):
                result = {
                    "ok": False,
                    "error": result.get("error", "worker failed"),
                    "code": result.get("code", "worker"),
                }
        except subprocess.TimeoutExpired:
            result = {"ok": False, "error": "后台任务超时", "code": "worker_timeout"}
        except Exception as exc:
            result = {"ok": False, "error": _sanitize_text(str(exc)), "code": "worker"}
        with _config_lock():
            job["status"] = "done" if result.get("ok") else "error"
            job["result"] = result
            job["finished"] = time.time()
            _write_job_file(job)


def cmd_analyze(args):
    cfg = load_config()
    plan = active_plan(cfg)
    creds = active_credentials(cfg)
    timeout = _effective_timeout(args.timeout)

    if args.media:
        if args.files or args.urls:
            if args.prompt:
                raise MiMoError("不能同时使用位置参数问题和 --prompt", code="usage")
            args.prompt = " ".join(args.media)
        else:
            if len(args.media) > 1 and args.prompt:
                raise MiMoError("不能同时使用位置参数问题和 --prompt", code="usage")
            args.files = [args.media[0]]
            if not args.prompt:
                args.prompt = " ".join(args.media[1:])

    if not args.files and not args.urls:
        raise MiMoError("请提供 --files 或 --urls", code="usage")

    prompt = args.prompt or "请基于附件内容直接、简洁地回答。"
    if args.async_mode:
        job = {
            "id": uuid.uuid4().hex,
            "created": time.time(),
            "status": "pending",
            "command": "analyze",
            "files": args.files,
            "urls": args.urls,
            "kind": args.kind,
            "prompt": prompt,
            "max_tokens": args.max_tokens,
            "fps": args.fps,
            "resolution": args.resolution,
            "timeout": timeout,
        }
        _write_job_file(job)
        try:
            _spawn_worker()
        except MiMoError as exc:
            job["status"] = "error"
            job["result"] = {"ok": False, "error": str(exc), "code": exc.code}
            job["finished"] = time.time()
            _write_job_file(job)
            raise
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "analyze",
                    "async": True,
                    "job_id": job["id"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    parts = _file_parts(args.files, args.fps, args.resolution)
    parts.extend(_url_parts(args.urls, args.kind, args.fps, args.resolution))
    if not parts:
        raise MiMoError("没有可处理的媒体内容", code="usage")

    today = date.today().isoformat()
    system = (
        "You are MiMo, an AI assistant developed by Xiaomi. "
        f"Today is {today}. Answer the user's latest request directly and concisely. "
        "Do not add unrelated reasoning unless asked."
    )
    body = {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [*parts, {"type": "text", "text": prompt}]},
        ],
        "max_completion_tokens": args.max_tokens,
        "stream": False,
    }

    if args.dry_run:
        dry_plan = plan or os.environ.get("MIMO_PLAN", "payg")
        dry_creds = creds or {
            "api_key": "sk-dry-run",
            "base_url": DEFAULT_BASE_URL,
        }
        _print_dry_run("analyze", dry_plan, dry_creds, body)
        return

    if not creds:
        raise MiMoError("尚未配置 active plan；请先运行 configure", code="not_configured")

    data = _chat_with_retry(creds, body, args.max_tokens, timeout=timeout)
    content, reasoning_fallback = _extract_content(data)
    finish_reason = _finish_reason(data)
    usage = _extract_usage(data)
    if not content:
        raise MiMoError("MiMo 未返回可用内容，请缩小问题或提高 --max-tokens 重试", code="empty")

    result = {
        "ok": True,
        "command": "analyze",
        "mimo_used": True,
        "content": content,
        "model": DEFAULT_MODEL,
        "plan": plan,
        "usage": usage,
        "finish_reason": finish_reason,
        "truncated": finish_reason == "length",
        "reasoning_fallback": reasoning_fallback,
    }
    if plan == "payg":
        cost, note = _cost_for(plan, DEFAULT_MODEL, usage, None, cfg.get("pricing", {}))
        result["cost_cny"] = cost
        if note:
            result["cost_note"] = note
    else:
        result["tokens"] = usage.get("total_tokens", 0)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_asr(args):
    path = Path(args.file)
    if not path.exists():
        raise MiMoError(f"文件不存在：{path}", code="file")
    ext = path.suffix.lower().lstrip(".")
    if ext not in ("wav", "mp3"):
        raise MiMoError("ASR 仅支持 wav/mp3 音频", code="usage")
    timeout = _effective_timeout(args.timeout)

    if args.async_mode:
        job = {
            "id": uuid.uuid4().hex,
            "created": time.time(),
            "status": "pending",
            "command": "asr",
            "file": args.file,
            "language": args.language,
            "max_tokens": args.max_tokens,
            "timeout": timeout,
        }
        _write_job_file(job)
        try:
            _spawn_worker()
        except MiMoError as exc:
            job["status"] = "error"
            job["result"] = {"ok": False, "error": str(exc), "code": exc.code}
            job["finished"] = time.time()
            _write_job_file(job)
            raise
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "asr",
                    "async": True,
                    "job_id": job["id"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    data_uri, _ = _data_uri(path)
    body = {
        "model": ASR_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_uri},
                    }
                ],
            }
        ],
        "asr_options": {"language": args.language},
        "max_completion_tokens": args.max_tokens,
        "stream": False,
    }

    cfg = load_config()
    plan = active_plan(cfg)
    creds = active_credentials(cfg)
    if args.dry_run:
        dry_plan = plan or os.environ.get("MIMO_PLAN", "payg")
        dry_creds = creds or {
            "api_key": "sk-dry-run",
            "base_url": DEFAULT_BASE_URL,
        }
        _print_dry_run("asr", dry_plan, dry_creds, body)
        return

    if not creds:
        raise MiMoError("尚未配置 active plan；请先运行 configure", code="not_configured")

    data = _chat_with_retry(creds, body, args.max_tokens, timeout=timeout)
    content, reasoning_fallback = _extract_content(data)
    finish_reason = _finish_reason(data)
    usage = _extract_usage(data)
    duration = _audio_duration(path)
    if not content:
        raise MiMoError("MiMo ASR 未返回可用内容，请重试或检查音频格式", code="empty")

    result = {
        "ok": True,
        "command": "asr",
        "mimo_used": True,
        "content": content,
        "model": ASR_MODEL,
        "plan": plan,
        "usage": usage,
        "finish_reason": finish_reason,
        "truncated": finish_reason == "length",
        "duration_seconds": duration,
        "reasoning_fallback": reasoning_fallback,
    }
    if plan == "payg":
        cost, note = _cost_for(plan, ASR_MODEL, usage, duration, cfg.get("pricing", {}))
        result["cost_cny"] = cost
        if note:
            result["cost_note"] = note
    else:
        result["tokens"] = usage.get("total_tokens", 0)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description="MiMo V2.5 helper for deepseek-vision")
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure", help="Configure pay-as-you-go or Token Plan")
    configure.add_argument("--plan", choices=["payg", "token"], help="Plan to configure")
    configure.add_argument("--base-url", help="Base URL (required for Token Plan)")

    use = subparsers.add_parser("use", help="Switch global active plan")
    use.add_argument("--plan", required=True, choices=["payg", "token"])

    subparsers.add_parser("status", help="Show masked configuration status")
    subparsers.add_parser("check", help="Validate current credentials against MiMo API")
    subparsers.add_parser("diagnose", help="Check config, DNS and MiMo network connectivity")

    analyze = subparsers.add_parser("analyze", help="Analyze image/audio/video with mimo-v2.5")
    analyze.add_argument("media", nargs="*", help="Local media path, then optional prompt words (e.g. /path/a.png 描述这张图)")
    analyze.add_argument("--files", action="append", default=[], help="Local media file (repeatable)")
    analyze.add_argument("--urls", action="append", default=[], help="Remote media URL (repeatable)")
    analyze.add_argument("--url", dest="urls", action="append", help=argparse.SUPPRESS)
    analyze.add_argument("--kind", choices=["image", "audio", "video"], help="Media kind for URLs")
    analyze.add_argument("--prompt", help="Question for MiMo")
    analyze.add_argument("--max-tokens", type=int, default=2048)
    analyze.add_argument("--timeout", type=int, help="Request timeout in seconds (default 180)")
    analyze.add_argument("--fps", type=float, default=2.0)
    analyze.add_argument("--resolution", default="default")
    analyze.add_argument("--dry-run", action="store_true")
    analyze.add_argument("--async", dest="async_mode", action="store_true")

    asr = subparsers.add_parser("asr", help="Transcribe audio with mimo-v2.5-asr")
    asr.add_argument("--file", required=True)
    asr.add_argument("--language", default="auto")
    asr.add_argument("--max-tokens", type=int, default=2048)
    asr.add_argument("--timeout", type=int, help="Request timeout in seconds (default 180)")
    asr.add_argument("--dry-run", action="store_true")
    asr.add_argument("--async", dest="async_mode", action="store_true")

    poll = subparsers.add_parser("poll", help="Poll an async MiMo job")
    poll.add_argument("--job", required=True, help="Job id returned by --async")
    poll.add_argument("--wait", type=int, default=0, help="Seconds to wait for completion")

    subparsers.add_parser("jobs", help="List pending and completed async jobs")
    subparsers.add_parser("worker", help="Internal background worker for async jobs")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    handlers = {
        "configure": cmd_configure,
        "use": cmd_use,
        "status": cmd_status,
        "check": cmd_check,
        "diagnose": cmd_diagnose,
        "poll": cmd_poll,
        "jobs": cmd_jobs,
        "worker": cmd_worker,
        "analyze": cmd_analyze,
        "asr": cmd_asr,
    }
    handler = handlers.get(args.command)
    try:
        if handler:
            handler(args)
    except MiMoError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "command": args.command,
                    "error": str(exc),
                    "code": exc.code,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(
            json.dumps(
                {
                    "ok": False,
                    "command": args.command,
                    "error": _sanitize_text(str(exc)),
                    "code": "unexpected",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
