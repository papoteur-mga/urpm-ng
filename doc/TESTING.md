# urpm-ng Testing

## Manual Tests

### Orphan detection during upgrade
- [ ] Wait for available updates
- [ ] Test `urpm upgrade --test` to check orphan detection
- [ ] Verify requires diff works correctly
- [ ] Test `--noerase-orphans` to keep orphans

### GPG signature verification
- [ ] Install signed package (should work)
- [ ] Install with missing key (should fail)
- [ ] `--nosignature` to bypass
- [ ] `urpm key import <url>` with HTTPS URL

### GPG key import during media add
- [ ] Key already present → shows "already in keyring"
- [ ] Key missing → shows info and asks confirmation
- [ ] `--auto` for automatic import without confirmation
- [ ] `--nokey` to skip verification
- [ ] Media without pubkey → shows "No pubkey found"

### mark command
- [ ] `urpm mark show <pkg>` - shows manual/auto
- [ ] `urpm mark manual <pkg>` - protects from autoremove
- [ ] `urpm mark auto <pkg>` - makes autoremovable
- [ ] Verify installed-through-deps.list is updated
- [ ] Uninstalled package → shows error

### Alternatives (OR deps)
- [ ] Install with alternatives (e.g., task-plasma pulling task-sound)
- [ ] `--auto` mode takes first choice
- [ ] Re-resolution after user choice

### --unavailable option
- [ ] `urpm q --unavailable` lists installed packages missing from media
- [ ] Install a package then remove from media → appears in list
- [ ] Pattern: `urpm q --unavailable php` filters by name
- [ ] gpg-pubkey doesn't appear in list
- [ ] Clean system → "All installed packages are available"

### --prefer option
**Intensive testing required - complex feature**

Basic cases:
- [ ] `urpm i phpmyadmin --prefer=php:8.4` → chooses php8.4-*
- [ ] `urpm i phpmyadmin --prefer=apache` → favors packages that REQUIRE/PROVIDE apache
- [ ] `urpm i phpmyadmin --prefer=-apache-mod_php` → excludes apache-mod_php

Combined cases:
- [ ] `--prefer=php:8.4,apache,php-fpm,-apache-mod_php` → php8.4-fpm-apache
- [ ] `--prefer=php:8.4,nginx,php-fpm` → php8.4-fpm-nginx

Edge cases:
- [ ] Preference without match → continues and asks
- [ ] Contradictory preferences → behavior to define
- [ ] With `--auto` → uses preferences without asking

Verify:
- [ ] Selection based on REQUIRES/PROVIDES, not package names
- [ ] Disfavored packages never installed unless absolutely required
- [ ] Preference order is respected

---

## Automated Test Infrastructure

### Test RPM packages to create

**Simple cases:**
- Package without dependencies
- Package with simple dependencies (A → B → C)
- Package with conflict
- Package with obsoletes

**Weak dependencies:**
- Package with Recommends
- Package with Suggests
- Package with Supplements
- Package with Enhances

**Alternatives (OR deps):**
- Dependency satisfied by multiple packages (A requires X, X provided by B or C)
- Alternative chain (task-sound → task-pulseaudio | task-pipewire)
- Alternatives with preference (already installed package)

**Edge cases:**
- Circular dependencies (A → B → C → A)
- Virtual provides (ksysguard provided by libksysguard)
- Versioned families (php8.4, php8.5)
- Transitive conflicts
- Obsoletes with version

### pytest structure

```
tests/
├── conftest.py          # Shared fixtures
├── test_database.py     # Database unit tests
├── test_resolver.py     # Dependency resolution tests
├── test_parsing.py      # Synthesis/hdlist parsing tests
├── test_install.py      # Install integration tests
├── test_erase.py        # Erase integration tests
├── test_upgrade.py      # Upgrade integration tests
└── fixtures/
    ├── rpms/            # Generated test RPMs
    └── repos/           # Test repositories
```

### To implement

- [ ] Test RPM generation script (spec files + rpmbuild)
- [ ] pytest fixture for temporary DB with test media
- [ ] Fixture for isolated RPM environment (chroot or container)
- [ ] Unit tests: parsing, resolver, database
- [ ] Integration tests: install/erase/upgrade end-to-end
- [ ] GitHub Actions CI

---

## Future Ideas

### Unavailable packages reporting to community

**Priority: Low**

Anonymous reporting to help Mageia maintainers identify:
- Installed packages no longer in repos
- Missing packages to rebuild
- Deprecated package usage

```bash
urpm q --unavailable --report  # One-shot manual report
urpm config reporting enable   # Opt-in automatic via urpmd
```

Requires webservice infrastructure on Mageia side.
