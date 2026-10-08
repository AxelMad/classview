"""Адрес панели: справочник filedrop (hostname -> IP) и проверка доступности."""
import json
import socket
import urllib.parse
import urllib.request


def resolve(hostname: str, url: str, token: str, timeout: float = 3.0):
    """GET <url>/resolve?hostname=<h>. Понимает JSON {"ip": ...} и plain text. None при ошибке."""
    if not url:
        return None
    q = urllib.parse.urlencode({"name": hostname})
    req = urllib.request.Request(f"{url.rstrip('/')}/resolve?{q}")
    if token:
        req.add_header("X-Filedrop-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace").strip()
    except Exception:
        return None
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            for key in ("ip", "IP", "address", "addr"):
                if data.get(key):
                    return str(data[key])
        elif isinstance(data, str):
            return data or None
    except ValueError:
        pass
    try:
        socket.inet_aton(body)
        return body
    except OSError:
        return None


def port_open(ip: str, port: int, timeout: float = 2.0) -> bool:
    if not ip:
        return False
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def stream_url(cfg, ip: str, path: str) -> str:
    user = urllib.parse.quote(cfg.rtsp_user, safe="")
    pwd = urllib.parse.quote(cfg.rtsp_password, safe="")
    auth = f"{user}:{pwd}@" if cfg.rtsp_user else ""
    return f"rtsp://{auth}{ip}:{cfg.rtsp_port}/{path}"
