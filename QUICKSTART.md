# urpm-ng Quickstart

Get started with urpm-ng in 5 minutes.

## 1. Install prerequisites

```bash
sudo urpmi python3-solv python3-zstandard
```

## 2. Clone

```bash
git clone https://github.com/pvi-github/urpm-ng.git
cd urpm-ng
```

## 3. Configure media

Import from existing urpmi config:
```bash
sudo ./bin/urpm media import /etc/urpmi/urpmi.cfg
sudo ./bin/urpm media update
```

Or add manually:
```bash
sudo ./bin/urpm media add https://mirrors.kernel.org/mageia/distrib/$(grep VERSION_ID /etc/os-release | cut -d= -f2)/$(uname -m)/media/core/release/
sudo ./bin/urpm media add https://mirrors.kernel.org/mageia/distrib/$(grep VERSION_ID /etc/os-release | cut -d= -f2)/$(uname -m)/media/core/updates/
```

## 4. Open firewall ports

For P2P package sharing between LAN machines:

```
TCP 9876   # urpmd HTTP API
UDP 9878   # Peer discovery
```

Use MCC > Security > Firewall, or edit `/etc/shorewall/rules`.

## 5. Start the daemon

```bash
sudo ./bin/urpmd
```

Machines with urpmd on the same LAN auto-discover each other and share cached packages.

## 6. Basic usage

```bash
# Search
./bin/urpm search firefox

# Install
sudo ./bin/urpm install firefox

# Upgrade system
sudo ./bin/urpm upgrade

# Remove
sudo ./bin/urpm erase firefox

# Clean orphans
sudo ./bin/urpm autoremove
```

---

See [README.md](README.md) for full documentation.
