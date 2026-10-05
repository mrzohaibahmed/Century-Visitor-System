"""The production deployment files (deploy/) keep their security properties.

These are text-level checks of the start-production.bat scripts that cannot run in the test suite itself:
a later edit that, say, binds MongoDB to all interfaces or starts the Next.js development server fails here.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"


# ---------------------------------------------------------------- single-PC production (start-production.bat)
# Plain HTTP on the trusted LAN: the web server is the only thing on the network; no Caddy, no certificate.
def _production_script() -> str:
    return (DEPLOY / "windows" / "production.ps1").read_text(encoding="utf-8")


def test_the_local_production_start_runs_the_web_server_on_the_lan():
    """server.mjs (sets the client address the API sees) on all interfaces, plain HTTP, port 6543."""
    script = _production_script()
    assert "server.mjs --hostname 0.0.0.0 --port 6543' -f $node" in script
    assert "next\\dist\\bin\\next" not in script and "next dev" not in script


def test_the_local_production_start_keeps_api_and_database_on_loopback():
    script = _production_script()
    assert "python.exe -m app.serve --host 127.0.0.1 --port 8000'" in script
    assert script.count("--host ") == 1 and "--reload" not in script
    dev_mongo = (DEPLOY.parent / "scripts" / "dev_mongo.py").read_text(encoding="utf-8")
    assert 'HOST = "127.0.0.1"' in dev_mongo and '"--bind_ip", HOST' in dev_mongo and "bind_ip_all" not in dev_mongo


def test_the_local_production_start_selects_http_lan_explicitly():
    script = _production_script()
    assert "$env:CG_ENVIRONMENT = 'production'" in script and "$env:CG_DEPLOYMENT_MODE = 'http-lan'" in script
    assert "CG_COOKIE_SECURE" not in script                    # http-lan is the only switch (Step 1)


def test_the_local_production_start_needs_no_caddy_certificate_or_firewall_change():
    script = _production_script()
    for gone in ("Find-Caddy", "caddy.exe", "Caddyfile", "Start-Process -FilePath $caddy", "Import-Certificate",
                 "root.crt", "New-NetFirewallRule", "Set-NetFirewall", "Get-NetFirewallRule", "configure-firewall",
                 "https://", "Tls12", "Get-Service", "Start-Service", "CGVMS-"):
        assert gone not in script, gone
    # The only Caddy left in the code is stopping one that an earlier version of the script started
    # (never required). The help text above param() and comments are not code.
    code = script[script.index("param("):].splitlines()
    assert [line.strip() for line in code if "caddy" in line.lower() and not line.lstrip().startswith("#")] == [
        "$legacy = Get-Ours 'Caddy' 'caddy'",
        "if ($legacy) { Stop-Process -Id $legacy.Id -Force; Say '  Caddy (former HTTPS setup) stopped.' }",
        "if (Get-Ours 'Caddy' 'caddy') {",
        "Say '      NOTE: Caddy from the former HTTPS setup is still running on 443; stop-production.bat stops it.'",
    ]


def test_the_local_health_check_reads_readiness_over_http_through_the_web_server():
    common = (DEPLOY / "windows" / "cgvms-common.ps1").read_text(encoding="utf-8")
    assert "HealthUrl = 'http://127.0.0.1:6543/api/v1/health/ready'" in common and "https://" not in common
    health = (DEPLOY / "windows" / "check-health.ps1").read_text(encoding="utf-8")
    assert "$cfg = Get-CgvmsLocalConfig" in health and "Get-Url $cfg.HealthUrl" in health
    assert "https" not in health.lower() and "SslStream" not in health and "CGVMS-" not in health


def test_the_former_https_services_deployment_is_gone():
    """Only start-production.bat deploys: no Caddy, Windows services, certificates or firewall scripts."""
    windows = DEPLOY / "windows"
    assert sorted(p.name for p in windows.iterdir()) == [
        "cgvms-common.ps1", "check-health.ps1", "production.ps1",
        "restart-production.bat", "start-production.bat", "stop-production.bat"]
    assert sorted(p.name for p in DEPLOY.iterdir()) == ["PRODUCTION-COMMANDS.md", "windows"]
    for script in windows.iterdir():
        text = script.read_text(encoding="utf-8")
        for gone in ("NetFirewall", "netsh", "Strict-Transport-Security", "CGVMS-Proxy", "install-services"):
            assert gone not in text, (script.name, gone)


def test_the_web_server_defaults_to_loopback():
    server = (DEPLOY.parent / "frontend" / "server.mjs").read_text(encoding="utf-8")
    assert 'hostname: { type: "string", short: "H", default: "127.0.0.1" }' in server
    assert "setClientIdentity(req);" in server and "dev: false" in server


def test_secret_files_are_ignored_by_git():
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "secrets/", "*.pem", "*.key", "*.keyfile"):
        assert pattern in ignored, pattern


# ---------------------------------------------------------------- any organization network
# The VMS starts on whatever network the organization uses: Windows' network profile (Public, Private, Domain),
# the network's name and its addresses never decide. The boundary is the binding (only the web server on
# 0.0.0.0:6543; API and MongoDB on 127.0.0.1), not a network check or a firewall rule.
POWERSHELL = shutil.which("powershell.exe")
WINDOWS = DEPLOY / "windows"


def _code(text: str) -> str:
    """The script's code: no help text (above param(), if any), no comment lines."""
    if "param(" in text:
        text = text[text.index("param("):]
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


@pytest.mark.parametrize("network_detail", [
    "NetworkCategory", "Public", "Private", "DomainAuthenticated",       # Windows network profile
    "Pixel 6a 61", "Gate LAN", "SSID", "netsh",                          # network / Wi-Fi names
    "192.168.", "10.0.", "172.16.", "172.29.", "PrefixLength", "DefaultGateway", "NextHop",  # addresses, subnets
])
def test_starting_production_never_depends_on_the_network(network_detail):
    for name in ("production.ps1", "cgvms-common.ps1", "check-health.ps1"):
        assert network_detail not in _code((WINDOWS / name).read_text(encoding="utf-8")), (name, network_detail)


def test_the_connected_networks_only_list_the_addresses_for_gate_pcs():
    code = _code(_production_script())
    assert "Get-LanExposureProblem" not in code and "$exposure" not in code
    assert "$networks = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)" in code
    assert code.count("$networks") == 2                      # read once, used once: the printed addresses
    assert "Where-Object { $_.InterfaceIndex -in $networks.InterfaceIndex }" in code
    start = code.index("Say '[1/4] MongoDB")
    assert not [line for line in code[:start].splitlines() if "Fail" in line and "network" in line.lower()]


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is needed")
def test_no_network_profile_guard_is_defined():
    script = (f". '{WINDOWS / 'cgvms-common.ps1'}'; "
              "[Console]::Out.Write([bool](Get-Command Get-LanExposureProblem -ErrorAction SilentlyContinue))")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],  # noqa: S603
                            capture_output=True, text=True, timeout=60, check=True)
    assert result.stdout.strip() == "False"
