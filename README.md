# NetForge

Pivot, tunnel, and staging helpers for authorized labs.

D3F4ULT

## Features

| Command | Function |
|---------|----------|
| `tunnels` | List SSH / socat / chisel pivot templates |
| `tunnel` | Print a ready one-liner with your hosts/ports filled in |
| `forward` | Pure-Python TCP port forward (no deps) |
| `stage` | Threaded HTTP staging server for payload delivery |
| `encode` | File encode: base64, hex, PowerShell UTF-16LE |

## Install

```bash
git clone https://github.com/D3F4UL7T/NetForge.git
cd NetForge
python3 netforge.py tunnels
```

Python 3.8+. No external dependencies.

## Usage

```bash
# list pivot templates
python3 netforge.py tunnels

# SSH SOCKS through a jump host
python3 netforge.py tunnel ssh_dynamic --lport 1080 --jump 10.10.14.5 --user root

# SSH reverse port forward
python3 netforge.py tunnel ssh_remote --rport 9090 --local-port 80 --jump 10.10.14.5

# chisel reverse
python3 netforge.py tunnel chisel_client --jump 10.10.14.5 --lport 8000 --rport 445 --target-host 10.10.10.20 --target-port 445

# live TCP forward (built-in)
python3 netforge.py forward --lport 8080 --target-host 10.10.10.5 --target-port 80

# stage payloads over HTTP
python3 netforge.py stage --port 8000 --dir ./payloads

# encode for transfer
python3 netforge.py encode payload.bin --mode b64
python3 netforge.py encode stage.ps1 --mode b64ps
```

## Layout

```
NetForge/
├── netforge.py
├── LICENSE
└── README.md
```

## Notes

Fits with OffKit / HostEnum / ShellGen under the same lab toolkit set.

Lab and authorized use only. Unauthorized access is illegal. Author assumes no liability for misuse.
