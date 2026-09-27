"""
MongoDB operator tool for the Century Gate VMS server (run with the API's Python):

    python deploy\\mongodb\\cgvms_mongo.py prepare  --tls-dir DIR [--host NAME ...] [--renew]
    python deploy\\mongodb\\cgvms_mongo.py init     --tls-dir DIR --secrets-dir DIR [--port 27018]
    python deploy\\mongodb\\cgvms_mongo.py rotate-logs --dump-config FILE --log-dir DIR [--keep-days 30]
    python deploy\\mongodb\\cgvms_mongo.py cert-status --tls-dir DIR [--warn-days 30]
    python deploy\\mongodb\\cgvms_mongo.py init-temp   --tls-dir DIR --port 27029

prepare      Creates a private certificate authority (CA) for the database, the
             server certificate mongod presents (valid for "localhost", 127.0.0.1
             and any --host) and the replica-set key file. Existing files are kept;
             --renew issues a new server certificate from the same CA.
             ca.key is the CA's private key: move it OFF the server to safe
             storage after preparing (it is only needed to renew the certificate).
init         Once, after mongod first starts with the production config: initiates the
             single-node replica set and creates the database accounts through the
             "localhost exception" (only possible while no account exists):
               cgvms_root     break-glass administrator (not used by the application)
               cgvms_app      the API: read/write on century_gate_vms only
               cgvms_migrate  schema migrations: + dbAdmin on century_gate_vms only
               cgvms_backup   mongodump: backup role + mongod log rotation
             Random passwords go into --secrets-dir as ready-made connection files.
             Running it again only adds missing accounts (existing passwords unchanged).
rotate-logs  Starts a new mongod log file and deletes rotated ones older than --keep-days.
cert-status  Days until the database certificates expire (exit 1 if fewer than --warn-days).
init-temp    Initiates the replica set of a TEMPORARY restore-test instance (restore-test.ps1).

It refuses port 27017 (the legacy desktop MongoDB service) and never touches the
legacy database century_gate_system.
"""
import argparse
import base64
import datetime as dt
import ipaddress
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import quote, quote_plus

APP_DB = "century_gate_vms"
LEGACY_DB = "century_gate_system"
LEGACY_PORT = 27017
REPLICA_SET = "cgvms"
CA_YEARS = 10
SERVER_DAYS = 825                  # about 27 months; renew with "prepare --renew"
USERS = {
    "cgvms_app": [{"role": "readWrite", "db": APP_DB}],
    "cgvms_migrate": [{"role": "readWrite", "db": APP_DB}, {"role": "dbAdmin", "db": APP_DB}],
    "cgvms_backup": [{"role": "backup", "db": "admin"}, {"role": "cgvmsLogRotate", "db": "admin"}],
}


# ---------------------------------------------------------------------------------------------- prepare
def _write_private(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    print(f"  wrote {path}")


def prepare(tls_dir: Path, hosts: list[str], renew: bool) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    tls_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC)
    ca_cert_path, ca_key_path = tls_dir / "ca.pem", tls_dir / "ca.key"

    if ca_cert_path.exists():
        ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
        if not ca_key_path.exists():
            if renew or not (tls_dir / "server.pem").exists():
                sys.exit(f"{ca_key_path} is needed to issue a server certificate: copy it back from safe storage.")
            ca_key = None
        else:
            ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        print(f"Using the existing CA (valid until {ca_cert.not_valid_after_utc:%Y-%m-%d}).")
    else:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Century Gate VMS"),
                          x509.NameAttribute(NameOID.COMMON_NAME, "Century Gate VMS database CA")])
        ca_cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(minutes=5))
                   .not_valid_after(now + dt.timedelta(days=365 * CA_YEARS))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                                key_encipherment=False, data_encipherment=False, key_agreement=False,
                                                key_cert_sign=True, crl_sign=True, encipher_only=False,
                                                decipher_only=False), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
                   .sign(ca_key, hashes.SHA256()))
        _write_private(ca_key_path, ca_key.private_bytes(serialization.Encoding.PEM,
                                                         serialization.PrivateFormat.TraditionalOpenSSL,
                                                         serialization.NoEncryption()))
        ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        print(f"  wrote {ca_cert_path}")
        print(f"Created a new CA (valid until {ca_cert.not_valid_after_utc:%Y-%m-%d}).")

    server_path = tls_dir / "server.pem"
    if server_path.exists() and not renew:
        print(f"{server_path} exists; kept (use --renew to issue a new one).")
    else:
        names = ["localhost", *[h for h in hosts if h != "localhost"]]
        alt: list[x509.GeneralName] = [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        for host in names:
            try:
                alt.append(x509.IPAddress(ipaddress.ip_address(host)))
            except ValueError:
                alt.append(x509.DNSName(host))
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
                .issuer_name(ca_cert.subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(minutes=5))
                .not_valid_after(min(now + dt.timedelta(days=SERVER_DAYS), ca_cert.not_valid_after_utc))
                .add_extension(x509.SubjectAlternativeName(alt), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH,
                                                      ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
                               critical=False)
                .sign(ca_key, hashes.SHA256()))
        # mongod on Windows (Schannel) needs an unencrypted RSA key in the same PEM file as the certificate.
        _write_private(server_path, cert.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        print(f"Server certificate for {', '.join(names)} + 127.0.0.1, "
              f"valid until {cert.not_valid_after_utc:%Y-%m-%d}.")

    keyfile = tls_dir / "mongodb.keyfile"
    if not keyfile.exists():
        _write_private(keyfile, base64.b64encode(secrets.token_bytes(756))[:1000])
    print("\nNext: restrict this folder (see README), then MOVE ca.key to offline storage.")


# ---------------------------------------------------------------------------------------------- init
def _refuse_legacy(port: int) -> None:
    if port == LEGACY_PORT:
        sys.exit("Refusing port 27017: that is the legacy desktop MongoDB service.")


def _client(port: int, ca: Path, username: str | None = None, password: str | None = None):
    from pymongo import MongoClient
    return MongoClient(host="localhost", port=port, tls=True, tlsCAFile=str(ca), directConnection=True,
                       username=username, password=password, authSource="admin",
                       serverSelectionTimeoutMS=5000, uuidRepresentation="standard")


def uri(username: str, password: str, port: int, ca: Path, db: str = "") -> str:
    ca_param = quote(ca.resolve().as_posix(), safe=":/")
    return (f"mongodb://{quote_plus(username)}:{quote_plus(password)}@localhost:{port}/{db}"
            f"?replicaSet={REPLICA_SET}&tls=true&tlsCAFile={ca_param}&authSource=admin")


def init(tls_dir: Path, secrets_dir: Path, port: int) -> None:
    from pymongo.errors import OperationFailure
    _refuse_legacy(port)
    ca = tls_dir / "ca.pem"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    root_file = secrets_dir / "mongodb-root.txt"

    anonymous = _client(port, ca)
    try:
        anonymous.admin.command("replSetGetStatus")
    except OperationFailure as e:
        if e.code == 94:                                   # NotYetInitialized
            anonymous.admin.command("replSetInitiate", {"_id": REPLICA_SET,
                                                        "members": [{"_id": 0, "host": f"localhost:{port}"}]})
            print(f"Initiated replica set '{REPLICA_SET}' (localhost:{port}).")
        elif e.code not in (13, 18):                       # Unauthorized: accounts exist already
            raise
    for _ in range(60):
        if anonymous.admin.command("hello").get("isWritablePrimary"):
            break
        time.sleep(0.5)
    else:
        sys.exit("The replica set did not become primary; see the mongod log.")

    if root_file.exists():
        root_password = root_file.read_text(encoding="utf-8").strip()
    else:
        root_password = secrets.token_urlsafe(24)
        try:
            anonymous.admin.command("createUser", "cgvms_root", pwd=root_password, roles=["root"])
        except OperationFailure as e:
            sys.exit(f"Could not create the administrator account ({e.code}): accounts already exist. "
                     f"Put the cgvms_root password into {root_file} and run init again.")
        root_file.write_text(root_password + "\n", encoding="utf-8")
        print(f"Created cgvms_root; password in {root_file} (store it in the password manager).")

    root = _client(port, ca, "cgvms_root", root_password)
    admin = root.admin
    if not admin.command("rolesInfo", "cgvmsLogRotate")["roles"]:
        admin.command("createRole", "cgvmsLogRotate",
                      privileges=[{"resource": {"cluster": True}, "actions": ["logRotate"]}], roles=[])
    existing = {u["user"] for u in admin.command("usersInfo")["users"]}
    for username, roles in USERS.items():
        if username in existing:
            print(f"{username} exists; unchanged.")
            continue
        password = secrets.token_urlsafe(24)
        admin.command("createUser", username, pwd=password, roles=roles)
        if username == "cgvms_backup":
            # mongodump reads its connection from this file, so the password never appears on a command line.
            (secrets_dir / "mongodump.yaml").write_text(f'uri: "{uri(username, password, port, ca)}"\n',
                                                         encoding="utf-8")
        else:
            (secrets_dir / f"{username}.uri.txt").write_text(uri(username, password, port, ca, APP_DB) + "\n",
                                                             encoding="utf-8")
        print(f"Created {username}.")
    print(f"\nConnection files are in {secrets_dir}. Put the contents of cgvms_app.uri.txt into CG_MONGO_URI "
          "in backend\\.env. Never copy these files anywhere else.")


# ---------------------------------------------------------------------------------------------- rotate-logs
def rotate_logs(dump_config: Path, log_dir: Path, keep_days: int) -> None:
    from pymongo import MongoClient
    match = re.search(r'uri:\s*"([^"]+)"', dump_config.read_text(encoding="utf-8"))
    if not match:
        sys.exit(f"No uri found in {dump_config}.")
    client = MongoClient(match.group(1), directConnection=True, serverSelectionTimeoutMS=5000)
    client.admin.command("logRotate")
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for old in log_dir.glob("mongod.log.*"):                # rotated files: mongod.log.2026-09-27T02-00-00
        if old.stat().st_mtime < cutoff:
            old.unlink()
            removed += 1
    print(f"mongod log rotated; {removed} rotated file(s) older than {keep_days} days removed.")


# ---------------------------------------------------------------------------------------------- monitoring
def cert_status(tls_dir: Path, warn_days: int) -> int:
    from cryptography import x509
    now = dt.datetime.now(dt.UTC)
    worst = None
    for name in ("server.pem", "ca.pem"):
        cert = x509.load_pem_x509_certificate((tls_dir / name).read_bytes())
        days = (cert.not_valid_after_utc - now).days
        print(f"{name}: expires {cert.not_valid_after_utc:%Y-%m-%d} ({days} days)")
        worst = days if worst is None else min(worst, days)
    return 0 if worst is not None and worst >= warn_days else 1


def init_temp(tls_dir: Path, port: int, replica_set: str = "cgvmsrestore") -> None:
    """Replica set for an instance started WITHOUT accounts: the restore test's temporary instance, or
    (with --replica-set cgvms) a new production instance during disaster recovery, before the dump
    (which contains the accounts) is restored into it."""
    from pymongo.errors import OperationFailure
    _refuse_legacy(port)
    client = _client(port, tls_dir / "ca.pem")
    try:
        client.admin.command("replSetInitiate", {"_id": replica_set,
                                                 "members": [{"_id": 0, "host": f"localhost:{port}"}]})
    except OperationFailure as e:
        if e.code != 23:                                   # AlreadyInitialized
            raise
    for _ in range(60):
        if client.admin.command("hello").get("isWritablePrimary"):
            print(f"Replica set '{replica_set}' on localhost:{port} is ready.")
            return
        time.sleep(0.5)
    sys.exit("The temporary restore instance did not become primary.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="cgvms_mongo.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--tls-dir", type=Path, required=True)
    p.add_argument("--host", action="append", default=[], help="extra host name/IP for the certificate")
    p.add_argument("--renew", action="store_true", help="issue a new server certificate")
    i = sub.add_parser("init")
    i.add_argument("--tls-dir", type=Path, required=True)
    i.add_argument("--secrets-dir", type=Path, required=True)
    i.add_argument("--port", type=int, default=27018)
    r = sub.add_parser("rotate-logs")
    r.add_argument("--dump-config", type=Path, required=True)
    r.add_argument("--log-dir", type=Path, required=True)
    r.add_argument("--keep-days", type=int, default=30)
    c = sub.add_parser("cert-status")
    c.add_argument("--tls-dir", type=Path, required=True)
    c.add_argument("--warn-days", type=int, default=30)
    t = sub.add_parser("init-temp")
    t.add_argument("--tls-dir", type=Path, required=True)
    t.add_argument("--port", type=int, required=True)
    t.add_argument("--replica-set", default="cgvmsrestore", help="cgvms for disaster recovery (README)")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.tls_dir, args.host, args.renew)
    elif args.command == "init":
        init(args.tls_dir, args.secrets_dir, args.port)
    elif args.command == "cert-status":
        sys.exit(cert_status(args.tls_dir, args.warn_days))
    elif args.command == "init-temp":
        init_temp(args.tls_dir, args.port, args.replica_set)
    else:
        rotate_logs(args.dump_config, args.log_dir, args.keep_days)


if __name__ == "__main__":
    main()
