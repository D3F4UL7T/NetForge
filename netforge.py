#!/usr/bin/env python3
"""
NetForge — pivot, tunnel, and staging helpers
D3F4UL7T

Lab / authorized testing only.
"""

from __future__ import annotations

import argparse
import base64
import os
import select
import socket
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.0.0"

BANNER = r"""
    _   __     __  ______
   / | / /__  / /_/ ____/___  _________ ____
  /  |/ / _ \/ __/ /_  / __ \/ ___/ __ `/ _ \
 / /|  /  __/ /_/ __/ / /_/ / /  / /_/ /  __/
/_/ |_/\___/\__/_/    \____/_/   \__, /\___/
                                /____/
  pivot · tunnel · stage  |  D3F4UL7T
"""


# ---------------------------------------------------------------------------
# tunnel / pivot one-liners
# ---------------------------------------------------------------------------

TUNNELS = {
    "ssh_local": {
        "desc": "SSH local port forward (-L)",
        "template": "ssh -N -L {LPORT}:{TARGET_HOST}:{TARGET_PORT} {USER}@{JUMP}",
    },
    "ssh_remote": {
        "desc": "SSH remote port forward (-R)",
        "template": "ssh -N -R {RPORT}:127.0.0.1:{LOCAL_PORT} {USER}@{JUMP}",
    },
    "ssh_dynamic": {
        "desc": "SSH dynamic SOCKS (-D)",
        "template": "ssh -N -D {LPORT} {USER}@{JUMP}",
    },
    "ssh_reverse_socks": {
        "desc": "SSH reverse + dynamic (jump as SOCKS egress)",
        "template": "ssh -N -R {RPORT} -D {LPORT} {USER}@{JUMP}",
    },
    "socat_tcp": {
        "desc": "socat TCP relay",
        "template": "socat TCP-LISTEN:{LPORT},fork,reuseaddr TCP:{TARGET_HOST}:{TARGET_PORT}",
    },
    "socat_ssl": {
        "desc": "socat SSL listener -> TCP",
        "template": "socat OPENSSL-LISTEN:{LPORT},cert=cert.pem,verify=0,fork TCP:{TARGET_HOST}:{TARGET_PORT}",
    },
    "chisel_server": {
        "desc": "chisel server (listen)",
        "template": "./chisel server -p {LPORT} --reverse",
    },
    "chisel_client": {
        "desc": "chisel client reverse forward",
        "template": "./chisel client {JUMP}:{LPORT} R:{RPORT}:{TARGET_HOST}:{TARGET_PORT}",
    },
    "chisel_socks": {
        "desc": "chisel client SOCKS",
        "template": "./chisel client {JUMP}:{LPORT} R:socks",
    },
    "python_forward": {
        "desc": "python pure TCP forward (no deps)",
        "template": (
            "python3 -c \"import socket,threading,select\n"
            "L,T,P={LPORT},'{TARGET_HOST}',{TARGET_PORT}\n"
            "def pipe(a,b):\n"
            "  while True:\n"
            "    r,_,_=select.select([a,b],[],[])\n"
            "    for s in r:\n"
            "      d=s.recv(4096)\n"
            "      if not d: return\n"
            "      (b if s is a else a).sendall(d)\n"
            "s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
            "s.bind(('0.0.0.0',L));s.listen(5)\n"
            "while True:\n"
            "  c,_=s.accept();t=socket.create_connection((T,P))\n"
            "  threading.Thread(target=pipe,args=(c,t),daemon=True).start()\""
        ),
    },
}


def list_tunnels() -> None:
    print("[*] tunnels / pivots\n")
    for k, v in TUNNELS.items():
        print(f"  {k:22}  {v['desc']}")
    print()


def emit_tunnel(key: str, args: argparse.Namespace) -> None:
    if key not in TUNNELS:
        print(f"[!] unknown tunnel: {key}")
        list_tunnels()
        sys.exit(1)
    t = TUNNELS[key]["template"]
    try:
        out = t.format(
            LPORT=args.lport or 1080,
            RPORT=args.rport or 1080,
            LOCAL_PORT=args.local_port or 8080,
            TARGET_HOST=args.target_host or "127.0.0.1",
            TARGET_PORT=args.target_port or 80,
            JUMP=args.jump or "jump.lab",
            USER=args.user or "root",
        )
    except KeyError as e:
        print(f"[!] missing field: {e}")
        sys.exit(1)
    print(f"\n[*] {key} — {TUNNELS[key]['desc']}")
    print("-" * 60)
    print(out)
    print("-" * 60)


# ---------------------------------------------------------------------------
# pure-python port forward (built-in)
# ---------------------------------------------------------------------------

def pipe(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            r, _, _ = select.select([a, b], [], [])
            for s in r:
                data = s.recv(8192)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass


def run_forward(listen_port: int, target_host: str, target_port: int, bind: str = "0.0.0.0") -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((bind, listen_port))
    srv.listen(32)
    print(f"[*] forward  {bind}:{listen_port}  ->  {target_host}:{target_port}")
    print("[*] ctrl+c to stop\n")
    try:
        while True:
            client, addr = srv.accept()
            print(f"[+] {addr[0]}:{addr[1]}")
            try:
                remote = socket.create_connection((target_host, target_port), timeout=10)
            except OSError as e:
                print(f"[!] target connect failed: {e}")
                client.close()
                continue
            threading.Thread(target=pipe, args=(client, remote), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[*] stopped")
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# staging HTTP server
# ---------------------------------------------------------------------------

class StageHandler(BaseHTTPRequestHandler):
    stage_dir: Path = Path(".")
    quiet: bool = False

    def log_message(self, fmt: str, *args) -> None:
        if not self.quiet:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()}  {args[0]}")

    def do_GET(self) -> None:
        rel = self.path.lstrip("/") or "index.html"
        # block path traversal
        target = (self.stage_dir / rel).resolve()
        if not str(target).startswith(str(self.stage_dir.resolve())):
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(data)


def run_stage(port: int, directory: str, bind: str = "0.0.0.0") -> None:
    StageHandler.stage_dir = Path(directory).resolve()
    httpd = ThreadingHTTPServer((bind, port), StageHandler)
    print(f"[*] staging  http://{bind}:{port}/  root={StageHandler.stage_dir}")
    print("[*] ctrl+c to stop\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] stopped")
    finally:
        httpd.server_close()


# ---------------------------------------------------------------------------
# encode helpers
# ---------------------------------------------------------------------------

def encode_file(path: str, mode: str) -> None:
    data = Path(path).read_bytes()
    if mode == "b64":
        print(base64.b64encode(data).decode())
    elif mode == "hex":
        print(data.hex())
    elif mode == "b64ps":
        # UTF-16LE for PowerShell -EncodedCommand style
        # if text, re-encode; if binary, just b64 of raw
        try:
            text = data.decode("utf-8")
            enc = base64.b64encode(text.encode("utf-16le")).decode()
        except UnicodeDecodeError:
            enc = base64.b64encode(data).decode()
        print(enc)
    else:
        print(f"[!] unknown mode: {mode}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    print(BANNER)
    p = argparse.ArgumentParser(
        prog="netforge",
        description="NetForge — pivot / tunnel / stage (D3F4UL7T)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  netforge tunnels
  netforge tunnel ssh_dynamic --lport 1080 --jump 10.10.14.5 --user root
  netforge forward --lport 8080 --target-host 10.10.10.5 --target-port 80
  netforge stage --port 8000 --dir ./payloads
  netforge encode payload.bin --mode b64
        """,
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("tunnels", help="list tunnel templates")

    t = sub.add_parser("tunnel", help="print a tunnel/pivot one-liner")
    t.add_argument("name", help="template key")
    t.add_argument("--lport", type=int, default=1080)
    t.add_argument("--rport", type=int, default=1080)
    t.add_argument("--local-port", type=int, default=8080)
    t.add_argument("--target-host", default="127.0.0.1")
    t.add_argument("--target-port", type=int, default=80)
    t.add_argument("--jump", default="jump.lab")
    t.add_argument("--user", default="root")

    f = sub.add_parser("forward", help="pure-python TCP port forward")
    f.add_argument("--lport", type=int, required=True)
    f.add_argument("--target-host", required=True)
    f.add_argument("--target-port", type=int, required=True)
    f.add_argument("--bind", default="0.0.0.0")

    s = sub.add_parser("stage", help="HTTP staging server")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--dir", default=".")
    s.add_argument("--bind", default="0.0.0.0")

    e = sub.add_parser("encode", help="encode a file (b64 / hex / b64ps)")
    e.add_argument("file")
    e.add_argument("--mode", choices=["b64", "hex", "b64ps"], default="b64")

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        print()
        list_tunnels()
        return

    if args.cmd == "tunnels":
        list_tunnels()
    elif args.cmd == "tunnel":
        emit_tunnel(args.name, args)
    elif args.cmd == "forward":
        run_forward(args.lport, args.target_host, args.target_port, args.bind)
    elif args.cmd == "stage":
        run_stage(args.port, args.dir, args.bind)
    elif args.cmd == "encode":
        encode_file(args.file, args.mode)


if __name__ == "__main__":
    main()
