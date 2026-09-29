"""
Hikvision gate camera: device information and one still JPEG over ISAPI (HTTP/HTTPS, Digest login).

Server side only: the browser never talks to a camera. Nothing is stored here: the snapshot is
returned in memory, never written to disk, and never becomes a visitor photo by itself (the caller
decides; see services/photos.py for storage).

Standard library only (http.client). Blocking: call from async code via asyncio.to_thread.

Digest authentication (RFC 7616: MD5, SHA-256 and their -sess variants, qop "auth") is done here
rather than with urllib's handler, which retries a refused login up to five times: Hikvision locks an
account after a few failed logins, so a wrong password must cost exactly one attempt. A second
challenge is only answered when the camera says the first nonce was stale.

HTTPS always checks the certificate and host name (ssl.create_default_context). A camera with its
factory self-signed certificate is therefore refused with CERTIFICATE_UNTRUSTED; verification is
never switched off here.

Secrets: the password is only used to compute the Digest response. It never appears in a URL, a log
line or an error; errors carry a fixed code and a fixed, guard-safe message (no camera reply text,
no request headers, no address).

The whole operation (connect, login, reading the reply) must finish within `timeout` seconds: a
camera that disappears or answers byte by byte cannot hold a request.
"""
import hashlib
import http.client
import io
import logging
import re
import secrets
import socket
import ssl
import time
import xml.etree.ElementTree as ET  # noqa: S405 - bounded size, DOCTYPE refused before parsing
from dataclasses import dataclass, field
from enum import StrEnum

from PIL import Image, UnidentifiedImageError
from pydantic import SecretStr

log = logging.getLogger(__name__)

DEVICE_INFO_PATH = "/ISAPI/System/deviceInfo"
SNAPSHOT_PATH = "/ISAPI/Streaming/channels/{channel}/picture"

DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 30.0
MAX_DEVICE_INFO_BYTES = 64 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_PIXELS = 50_000_000          # decompression-bomb guard (a 12 MP camera is 12 000 000)
_CHUNK = 64 * 1024
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*$")          # host name or IPv4 address


class CameraErrorCode(StrEnum):
    UNAVAILABLE = "CAMERA_UNAVAILABLE"                        # refused, unreachable, unknown host name
    TIMEOUT = "CAMERA_TIMEOUT"
    AUTHENTICATION_FAILED = "CAMERA_AUTHENTICATION_FAILED"
    CERTIFICATE_UNTRUSTED = "CAMERA_CERTIFICATE_UNTRUSTED"    # HTTPS certificate not trusted by the server
    NOT_FOUND = "CAMERA_NOT_FOUND"                            # 404: wrong channel, or no such endpoint
    HTTP_ERROR = "CAMERA_HTTP_ERROR"                          # any other non-200 answer (incl. redirects)
    INVALID_RESPONSE = "CAMERA_INVALID_RESPONSE"              # not HTTP, not the expected XML, not an image
    INVALID_IMAGE = "CAMERA_INVALID_IMAGE"                    # looks like a JPEG but cannot be decoded
    SNAPSHOT_FAILED = "CAMERA_SNAPSHOT_FAILED"                # the picture was cut off, or is too large


_MESSAGES = {
    CameraErrorCode.UNAVAILABLE: "The camera cannot be reached. Check that it is switched on and connected.",
    CameraErrorCode.TIMEOUT: "The camera did not answer in time.",
    CameraErrorCode.AUTHENTICATION_FAILED: "The camera refused the user name or password.",
    CameraErrorCode.CERTIFICATE_UNTRUSTED: "The camera's HTTPS certificate is not trusted by the server.",
    CameraErrorCode.NOT_FOUND: "The camera has no picture on this channel. Check the channel number.",
    CameraErrorCode.HTTP_ERROR: "The camera refused the request.",
    CameraErrorCode.INVALID_RESPONSE: "The camera sent an unexpected answer.",
    CameraErrorCode.INVALID_IMAGE: "The camera sent a picture that cannot be read.",
    CameraErrorCode.SNAPSHOT_FAILED: "The camera could not deliver a complete picture.",
}


class CameraError(Exception):
    """A camera request failed. `code` and `message` are safe to log and to show; `status` is the
    camera's HTTP status where there was one."""

    def __init__(self, code: CameraErrorCode, status: int | None = None):
        super().__init__(code.value)
        self.code = code
        self.status = status
        self.message = _MESSAGES[code]

    def __str__(self) -> str:
        return f"{self.code.value} (HTTP {self.status})" if self.status else self.code.value


@dataclass(frozen=True)
class CameraConfig:
    """How to reach one camera. Validated on creation; `password` never shows in repr or str."""

    host: str
    username: str
    password: SecretStr = field(repr=False)
    protocol: str = "https"
    port: int | None = None                      # None: 443 for https, 80 for http
    channel: int = 101                           # ISAPI streaming channel id (e.g. 101 = channel 1, main stream)
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self):
        if self.protocol not in ("http", "https"):
            raise ValueError("protocol must be 'http' or 'https'.")
        if not _valid_host(self.host):
            raise ValueError("host must be an IP address or a host name (no scheme, port or path).")
        if self.port is not None and not 1 <= self.port <= 65535:
            raise ValueError("port must be 1–65535.")
        if not 1 <= self.channel <= 65535:
            raise ValueError("channel must be 1–65535.")
        if not 0 < self.timeout <= MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout must be more than 0 and at most {MAX_TIMEOUT_SECONDS:g} seconds.")
        if not self.username or any(ord(c) < 32 or c in '"\\' for c in self.username):
            raise ValueError("username must be non-empty, without quotes, backslashes or control characters.")
        if not isinstance(self.password, SecretStr):
            raise TypeError("password must be a SecretStr.")

    @property
    def effective_port(self) -> int:
        return self.port or (443 if self.protocol == "https" else 80)


def _valid_host(host: str) -> bool:
    if not host or len(host) > 253:
        return False
    try:
        socket.inet_pton(socket.AF_INET6, host)            # a bare IPv6 address
        return True
    except OSError:
        pass
    return bool(_HOST.match(host))                         # host name or IPv4 (digits and dots)


@dataclass(frozen=True)
class DeviceInfo:
    """Only what the application needs from /ISAPI/System/deviceInfo (no serial or MAC address)."""

    model: str | None
    firmware: str | None
    device_name: str | None


@dataclass(frozen=True)
class Snapshot:
    """One JPEG, exactly as the camera sent it (not re-encoded), in memory only."""

    data: bytes = field(repr=False)
    width: int
    height: int
    content_type: str = "image/jpeg"


# ---------------------------------------------------------------- Digest (RFC 7616)
_AUTH_PARAM = re.compile(r'([A-Za-z0-9_-]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^,\s]*)')
_OTHER_SCHEME = re.compile(r",\s*(?:Basic|Negotiate|NTLM|Bearer)\b", re.IGNORECASE)
# MD5 is what the Digest protocol (and most cameras) use; it is not our choice of password hash.
_HASHES = {"MD5": lambda b: hashlib.md5(b, usedforsecurity=False), "SHA-256": hashlib.sha256}


def _digest_challenge(headers: list[str]) -> dict[str, str] | None:
    """The parameters of the first Digest challenge among the WWW-Authenticate headers (lower-case keys)."""
    for value in headers:
        start = re.search(r"\bDigest\s+", value, re.IGNORECASE)
        if not start:
            continue
        rest = value[start.end():]
        other = _OTHER_SCHEME.search(rest)                 # "Digest ..., Basic realm=..." in one header
        rest = rest[:other.start()] if other else rest
        params = {}
        for key, raw in _AUTH_PARAM.findall(rest):
            params[key.lower()] = re.sub(r"\\(.)", r"\1", raw[1:-1]) if raw.startswith('"') else raw
        if "nonce" in params and "realm" in params:
            return params
    return None


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _digest_header(challenge: dict[str, str], config: CameraConfig, method: str, uri: str) -> str:
    """The Authorization header answering `challenge`. Raises CameraError if it cannot be answered."""
    algorithm = challenge.get("algorithm", "MD5")
    base = algorithm.upper().removesuffix("-SESS")
    if base not in _HASHES:
        raise CameraError(CameraErrorCode.AUTHENTICATION_FAILED)

    def h(text: str) -> str:
        return _HASHES[base](text.encode("utf-8")).hexdigest()

    qops = [q.strip().lower() for q in challenge.get("qop", "").split(",") if q.strip()]
    if qops and "auth" not in qops:                        # auth-int only: not supported
        raise CameraError(CameraErrorCode.AUTHENTICATION_FAILED)
    realm, nonce = challenge["realm"], challenge["nonce"]
    cnonce, nc = secrets.token_hex(8), "00000001"
    ha1 = h(f"{config.username}:{realm}:{config.password.get_secret_value()}")
    if algorithm.upper().endswith("-SESS"):
        ha1 = h(f"{ha1}:{nonce}:{cnonce}")
    ha2 = h(f"{method}:{uri}")
    response = h(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}") if qops else h(f"{ha1}:{nonce}:{ha2}")

    parts = [f"username={_quote(config.username)}", f"realm={_quote(realm)}", f"nonce={_quote(nonce)}",
             f"uri={_quote(uri)}", f"algorithm={algorithm}", f"response={_quote(response)}"]
    if qops:
        parts += ["qop=auth", f"nc={nc}", f"cnonce={_quote(cnonce)}"]
    if "opaque" in challenge:
        parts.append(f"opaque={_quote(challenge['opaque'])}")
    return "Digest " + ", ".join(parts)


# ---------------------------------------------------------------- HTTP
@dataclass
class _Reply:
    status: int
    content_type: str
    body: bytes


class GateCameraClient:
    """One Hikvision camera. Blocking; each method is one complete request (login included)."""

    def __init__(self, config: CameraConfig):
        self._config = config

    def __repr__(self) -> str:
        c = self._config
        return f"GateCameraClient({c.protocol}://{c.host}:{c.effective_port}, channel {c.channel})"

    def get_device_info(self) -> DeviceInfo:
        """Model, firmware and device name. Confirms that the camera answers and accepts the login."""
        reply = self._get(DEVICE_INFO_PATH, MAX_DEVICE_INFO_BYTES, CameraErrorCode.INVALID_RESPONSE)
        return _parse_device_info(reply)

    def capture_snapshot(self) -> Snapshot:
        """One still picture from the configured channel, validated as a decodable JPEG."""
        path = SNAPSHOT_PATH.format(channel=self._config.channel)
        reply = self._get(path, MAX_SNAPSHOT_BYTES, CameraErrorCode.SNAPSHOT_FAILED)
        return _validate_snapshot(reply)

    # -- internals
    def _get(self, path: str, max_bytes: int, cut_off: CameraErrorCode) -> _Reply:
        deadline = time.monotonic() + self._config.timeout
        try:
            reply, challenges = self._request(path, None, deadline, max_bytes, cut_off)
            if reply.status == 401:
                for _ in range(2):                         # the answer, plus one retry for a stale nonce only
                    challenge = _digest_challenge(challenges)
                    if challenge is None:                  # no Digest offered (e.g. Basic only): not used
                        raise CameraError(CameraErrorCode.AUTHENTICATION_FAILED, 401)
                    auth = _digest_header(challenge, self._config, "GET", path)
                    reply, challenges = self._request(path, auth, deadline, max_bytes, cut_off)
                    retry = _digest_challenge(challenges) if reply.status == 401 else None
                    if not (retry and retry.get("stale", "").lower() == "true"):
                        break
            _check_status(reply.status)
            return reply
        except CameraError as error:
            log.warning("Gate camera request failed: %s", error)          # code and status only
            raise

    def _request(self, path: str, auth: str | None, deadline: float, max_bytes: int,
                 cut_off: CameraErrorCode) -> tuple[_Reply, list[str]]:
        conn = self._connection(_remaining(deadline))
        try:
            headers = {"Accept": "*/*", "Connection": "close"}
            if auth:
                headers["Authorization"] = auth
            conn.request("GET", path, headers=headers)
            sock = conn.sock                    # http.client detaches it from conn once a "close" reply arrives
            sock.settimeout(_remaining(deadline))
            response = conn.getresponse()
            declared = response.getheader("Content-Length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise CameraError(cut_off, response.status)
            chunks, size = [], 0
            while not response.isclosed():         # closed (with its socket) once the whole body is read
                sock.settimeout(_remaining(deadline))
                chunk = response.read1(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise CameraError(cut_off, response.status)
                chunks.append(chunk)
            if declared.isdigit() and size < int(declared):       # the camera closed in the middle of the body
                raise CameraError(cut_off, response.status)
            content_type = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
            reply = _Reply(response.status, content_type, b"".join(chunks))
            return reply, response.headers.get_all("WWW-Authenticate") or []
        except CameraError:
            raise
        except ssl.SSLCertVerificationError:
            raise CameraError(CameraErrorCode.CERTIFICATE_UNTRUSTED) from None
        except TimeoutError:
            raise CameraError(CameraErrorCode.TIMEOUT) from None
        except http.client.IncompleteRead:                 # the connection closed in the middle of the body
            raise CameraError(cut_off) from None
        except http.client.HTTPException:                  # not HTTP (bad status line, closed without answer)
            raise CameraError(CameraErrorCode.INVALID_RESPONSE) from None
        except OSError:                                    # refused, unreachable, DNS, TLS handshake
            raise CameraError(CameraErrorCode.UNAVAILABLE) from None
        except Exception as error:                         # a bug here must not reach the caller as a traceback
            log.error("Gate camera request: unexpected %s", type(error).__name__)     # type only, no message
            raise CameraError(cut_off) from None
        finally:
            conn.close()

    def _connection(self, timeout: float) -> http.client.HTTPConnection:
        c = self._config
        if c.protocol == "https":
            # Certificate and host name always checked (the default context); never switched off here.
            return http.client.HTTPSConnection(c.host, c.effective_port, timeout=timeout,
                                               context=ssl.create_default_context())
        return http.client.HTTPConnection(c.host, c.effective_port, timeout=timeout)


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise CameraError(CameraErrorCode.TIMEOUT)
    return left


def _check_status(status: int) -> None:
    if status == 200:
        return
    if status == 401:
        raise CameraError(CameraErrorCode.AUTHENTICATION_FAILED, status)
    if status == 404:
        raise CameraError(CameraErrorCode.NOT_FOUND, status)
    raise CameraError(CameraErrorCode.HTTP_ERROR, status)     # 3xx are not followed (no silent downgrade)


# ---------------------------------------------------------------- parsing and validation
def _parse_device_info(reply: _Reply) -> DeviceInfo:
    body = reply.body
    # Entity declarations are never needed in an ISAPI answer: refuse them before parsing.
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise _invalid(CameraErrorCode.INVALID_RESPONSE)
    try:
        root = ET.fromstring(body)  # noqa: S314 - size-limited, no DOCTYPE/entities (checked above)
    except ET.ParseError:
        raise _invalid(CameraErrorCode.INVALID_RESPONSE) from None
    if _local(root.tag) != "DeviceInfo":
        raise _invalid(CameraErrorCode.INVALID_RESPONSE)

    def text(name: str) -> str | None:
        for el in root:
            if _local(el.tag) == name and el.text and el.text.strip():
                return el.text.strip()[:100]
        return None

    return DeviceInfo(model=text("model"), firmware=text("firmwareVersion"), device_name=text("deviceName"))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]                          # ISAPI answers are namespaced


def _validate_snapshot(reply: _Reply) -> Snapshot:
    """A 200 answer is not enough: cameras answer some errors with an XML body and status 200."""
    body = reply.body
    if reply.content_type and not reply.content_type.startswith("image/"):
        raise _invalid(CameraErrorCode.INVALID_RESPONSE)
    if not body.startswith(b"\xff\xd8\xff"):
        # Not a JPEG at all (XML, HTML, another format): not a picture we accept.
        raise _invalid(CameraErrorCode.INVALID_RESPONSE)
    try:
        with Image.open(io.BytesIO(body)) as img:
            width, height = img.size                        # from the header; nothing decoded yet
            if img.format != "JPEG" or width <= 0 or height <= 0 or width * height > MAX_SNAPSHOT_PIXELS:
                raise _invalid(CameraErrorCode.INVALID_IMAGE)
            img.load()                                      # full decode: a cut-off JPEG fails here
    except CameraError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise _invalid(CameraErrorCode.INVALID_IMAGE) from None
    return Snapshot(data=body, width=width, height=height)


def _invalid(code: CameraErrorCode) -> CameraError:
    error = CameraError(code, 200)
    log.warning("Gate camera request failed: %s", error)
    return error
