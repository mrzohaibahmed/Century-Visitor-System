"""The production deployment files (deploy/) keep their security properties.

These are text-level checks of configuration that cannot run in the test suite itself (Windows
services, Caddy, mongod): a later edit that, say, binds MongoDB to all interfaces or starts the
Next.js development server fails here.
"""
import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"
SECURE_URI = ("mongodb://cgvms_app:App-Pass-1@localhost:27018/century_gate_vms?replicaSet=cgvms&tls=true"
              "&tlsCAFile=C:/CenturyGateVMS/tls/mongodb/ca.pem&authSource=admin")


def _env_file(tmp_path, uri: str) -> Path:
    text = (DEPLOY / "windows" / "api.env.template").read_text(encoding="utf-8")
    text = re.sub(r"^CG_MONGO_URI=.*$", lambda _: f"CG_MONGO_URI={uri}", text, flags=re.M)
    text = re.sub(r"^CG_PHOTO_DIR=.*$", lambda _: f"CG_PHOTO_DIR={tmp_path}", text, flags=re.M)
    path = tmp_path / "api.env"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_production_env_template_gives_valid_secure_settings(tmp_path, monkeypatch):
    for key in ("CG_ENVIRONMENT", "CG_MONGO_URI", "CG_PHOTO_DIR", "CG_COOKIE_SECURE", "CG_API_DOCS"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=_env_file(tmp_path, SECURE_URI))
    assert s.environment == "production" and s.cookie_secure is True and s.docs_enabled is False
    assert s.trusted_proxies == ["127.0.0.1", "::1"] and s.mongo_db == "century_gate_vms"


def test_the_unfilled_template_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("CG_MONGO_URI", raising=False)
    template = (DEPLOY / "windows" / "api.env.template").read_text(encoding="utf-8")
    path = tmp_path / "api.env"
    path.write_text(template.replace(r"D:\CenturyGateVMS-Photos", str(tmp_path)), encoding="utf-8")
    with pytest.raises(ValidationError):
        Settings(_env_file=path)


def test_the_template_contains_no_real_secret():
    text = (DEPLOY / "windows" / "api.env.template").read_text(encoding="utf-8")
    assert "@" not in text.split("CG_MONGO_URI=")[1].splitlines()[0]


def test_mongod_is_loopback_only_with_tls_and_login():
    conf = (DEPLOY / "mongodb" / "mongod.conf.template").read_text(encoding="utf-8")
    assert re.search(r"^\s*bindIp:\s*127\.0\.0\.1\s*$", conf, re.M)
    assert re.search(r"^\s*mode:\s*requireTLS", conf, re.M)
    assert re.search(r"^\s*authorization:\s*enabled", conf, re.M)
    assert re.search(r"^\s*keyFile:", conf, re.M) and re.search(r"^\s*replSetName:\s*cgvms", conf, re.M)
    port = int(re.search(r"^\s*port:\s*(\d+)", conf, re.M).group(1))
    assert port != 27017                                       # the legacy desktop database service
    assert "bindIpAll" not in conf and "0.0.0.0" not in conf


def test_database_accounts_have_least_privilege():
    spec = importlib.util.spec_from_file_location("cgvms_mongo", DEPLOY / "mongodb" / "cgvms_mongo.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert tool.USERS["cgvms_app"] == [{"role": "readWrite", "db": "century_gate_vms"}]
    assert {r["role"] for r in tool.USERS["cgvms_migrate"]} == {"readWrite", "dbAdmin"}
    assert all(r["db"] == "century_gate_vms" for r in tool.USERS["cgvms_migrate"])
    assert "century_gate_system" not in str(tool.USERS)
    # The connection strings it writes are accepted by the production settings as they are.
    uri = tool.uri("cgvms_app", "p@ss w/rd", 27018, Path("C:/CenturyGateVMS/tls/mongodb/ca.pem"), "century_gate_vms")
    assert "p%40ss+w%2Frd" in uri and "tls=true" in uri
    Settings(_env_file=None, environment="production", mongo_uri=uri, photo_dir=Path("C:/x"))


def test_the_proxy_has_https_only_and_no_access_log():
    caddy = (DEPLOY / "windows" / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    assert re.search(r"^\s*admin off\s*$", caddy, re.M)
    assert "Strict-Transport-Security" in caddy and "-Server" in caddy
    assert re.search(r"redir https://\{\$CGVMS_SITE\}\{uri\} 308", caddy)
    upstreams = re.findall(r"reverse_proxy\s+(\S+)", caddy)
    assert upstreams and all(u.startswith("127.0.0.1:") for u in upstreams)
    assert not re.search(r"^\s*log\b", caddy, re.M)               # URLs may contain ID numbers in query strings
    assert "tls_insecure_skip_verify" not in caddy and "file_server" not in caddy
    assert "tls internal" in (DEPLOY / "windows" / "caddy" / "tls-internal.caddy").read_text(encoding="utf-8")


def _service(name: str) -> ET.Element:
    return ET.parse(DEPLOY / "windows" / "services" / f"{name}.xml").getroot()


@pytest.mark.parametrize("name", ["CGVMS-API", "CGVMS-Web", "CGVMS-Proxy"])
def test_services_restart_rotate_logs_and_hold_no_secrets(name):
    svc = _service(name)
    assert svc.findtext("id") == name and svc.findtext("startmode") == "Automatic"
    assert [f.get("action") for f in svc.findall("onfailure")] == ["restart"] * 3
    log = svc.find("log")
    assert log.get("mode") == "roll-by-size" and int(log.findtext("keepFiles")) <= 20
    text = ET.tostring(svc, encoding="unicode")
    assert "CG_MONGO_URI" not in text and "password" not in text.lower() and "mongodb://" not in text


def test_the_api_service_runs_the_production_server_on_loopback():
    args = _service("CGVMS-API").findtext("arguments")
    assert "-m app.serve" in args and "--host 127.0.0.1" in args and "--reload" not in args
    assert _service("CGVMS-API").findtext("depend") == "CGVMS-MongoDB"


def test_the_web_service_runs_the_production_build_on_loopback():
    svc = _service("CGVMS-Web")
    args = svc.findtext("arguments")
    assert "next start" in args and "next dev" not in args and "--hostname 127.0.0.1" in args
    env = {e.get("name"): e.get("value") for e in svc.findall("env")}
    assert env["NODE_ENV"] == "production" and env["API_INTERNAL_URL"].startswith("http://127.0.0.1:")
    assert not any(k.startswith("NEXT_PUBLIC_") for k in env)


def test_secret_files_are_ignored_by_git():
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "secrets/", "*.pem", "*.key", "*.keyfile"):
        assert pattern in ignored, pattern
