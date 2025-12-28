# urpm-ng Quickstart

Get started with urpm-ng in 2 minutes.

## Installation via RPM (recommended)

### 1. Install the package

```bash
sudo urpmi urpm-ng
```

The package will:
- Install all dependencies
- Configure firewall ports for P2P sharing
- Start the urpmd daemon

### 2. Import media from urpmi

```bash
sudo urpm media import
```

### 3. Start using urpm

```bash
# Search
urpm search firefox

# Install
sudo urpm install firefox

# Upgrade system
sudo urpm upgrade

# Remove
sudo urpm erase firefox

# Clean orphans
sudo urpm autoremove
```

That's it! Machines with urpmd on the same LAN auto-discover each other and share cached packages.

---

## Development setup (from git)

For contributors or testing the latest code:

### 1. Install prerequisites

```bash
sudo urpmi python3-solv python3-zstandard
```

### 2. Clone

```bash
git clone https://github.com/pvi-github/urpm-ng.git
cd urpm-ng
```

### 3. Configure media

Import from existing urpmi config:
```bash
sudo ./bin/urpm media import
sudo ./bin/urpm media update
```

Or add manually:
```bash
V=$(grep VERSION_ID /etc/os-release | cut -d= -f2)
A=$(uname -m)
sudo ./bin/urpm media add https://mirrors.kernel.org/mageia/distrib/$V/$A/media/core/release/
sudo ./bin/urpm media add https://mirrors.kernel.org/mageia/distrib/$V/$A/media/core/updates/
```

### 4. Open firewall ports

For P2P package sharing:
```
TCP 9876   # urpmd HTTP API
UDP 9878   # Peer discovery
```

### 5. Start the daemon

```bash
sudo ./bin/urpmd
```

### 6. Use urpm

```bash
./bin/urpm search firefox
sudo ./bin/urpm install firefox
```

---

See [README.md](README.md) for full documentation.
