# Refonte de la gestion des médias et du stockage RPM

## Demande initiale

Je voudrais retravailler la façon dont on gère les médias et le stockage des RPM.

### Problème actuel

Les médias sont stockés comme ça :
```
/var/lib/urpm(ou urpm-dev)/medias/<serveur>/<media_name>/
```

Et déclarés dans la base de données avec serveur + nom du média et l'URL.

Ça pose un souci : je voudrais pouvoir paralléliser sur plusieurs serveurs les downloads upstream pour :
- Répartir la charge
- Éviter le throttling
- Gérer les éventuelles indisponibilités

En fait pour les miroirs officiels, le `Core Release` sera toujours le même et le `Core Updates` sera toujours le même quel que soit le serveur miroir.

Par ailleurs, comme il est prévu que urpmd puisse servir de proxy, il faut anticiper de pouvoir relayer plusieurs versions : Mageia 9 et Mageia 10 par exemple.

### Nouvelle structure proposée

**Médias officiels :**
```
/var/lib/urpm(ou urpm-dev)/medias/<mageia_version>/<architecture>/media/<class>/<media_short_name>/
```

**Médias tiers :**
```
/var/lib/urpm(ou urpm-dev)/medias/<mageia_version>/<architecture>/media/custom/<media_short_name>/
```

**Paramètres :**
- `mageia_version` : 8, 9, 10, cauldron
- `architecture` : aarch64, armv7hl, i586, i686, x86_64
- `class` : core, debug, nonfree, tainted
- `media_short_name` : release, updates, backports, backport_testing, updates_testing

**Noms visibles :** Core Release, Core Updates, Core Backports, etc.

### Concept clé : découpler médias et serveurs

L'idée c'est de décorréler les médias et les serveurs capables de les servir. Donc avoir :
- Une liste de médias
- Une liste de serveurs
- Un lien pour dire quel serveur peut servir quel média

**Structure des serveurs officiels :**
```
http(s)://<nom_serveur>/<base_path>/<mageia_version>/<architecture>/media/<class>/<media_short_name>
```

(On oublie volontairement les serveurs ftp et rsync dans un premier temps)

### Fonctionnalités visées

1. **Déclaration de plusieurs serveurs**
2. **Test périodique de disponibilité**
3. **Mesure du temps de réaction** sur la récup des métadonnées (synthesis)
4. **Mesure du temps de récupération** des fichiers RPM/synthesis
5. **Mesure de la bande passante effective** (taille fichier / temps) pour classer les serveurs
6. **Parallélisation** sur les 4 "meilleurs" serveurs disponibles

### Priorité peers

Sans casser la logique des peers :
- On privilégie toujours les peers (les chemins seront à adapter)
- Ensuite si les peers n'ont pas, on passe au download upstream

### Import et liste de serveurs

- `urpm media import` importe un seul serveur
- Prévoir la publication centrale d'une liste de serveurs dans un format intelligent (JSON) pour que urpm et urpmd puissent compléter leur liste de serveurs dynamiquement

---

## Analyse de l'architecture actuelle

### Fichiers concernés

| Fichier | Rôle |
|---------|------|
| `urpm/core/database.py` | Schéma BDD, opérations médias |
| `urpm/core/sync.py` | Download synthesis/hdlist, cache |
| `urpm/core/download.py` | Download RPM, parallélisation, peers |
| `urpm/core/peer_client.py` | Découverte peers, requêtes disponibilité |
| `urpm/core/config.py` | Chemins, extraction hostname |
| `urpm/core/resolver.py` | Résolution deps avec media_id |
| `urpm/cli/main.py` | Commandes CLI media/sync/install |

### Schéma BDD actuel (table media)

```sql
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    url TEXT,
    mirrorlist TEXT,
    enabled INTEGER DEFAULT 1,
    update_media INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 50,
    last_sync INTEGER,
    synthesis_md5 TEXT,
    hdlist_md5 TEXT,
    added_timestamp INTEGER
);
```

**Relation actuelle :** 1 média = 1 URL = 1 serveur

### Construction des chemins actuels

```python
# Cache : <base_dir>/medias/<hostname>/<media_name>/
# URL RPM : {media_url}/{filename}
# Peer : http://<peer>/media/{hostname}/{media_name}/{file}
```

### Fonctions clés à modifier

1. `config.py:get_hostname_from_url()` - Parsing URL
2. `config.py:get_media_dir()` - Structure cache
3. `sync.py:get_media_cache_dir()` - Chemin sync
4. `sync.py:build_synthesis_url()` - URL synthesis
5. `download.py:DownloadItem.url` - URL RPM
6. `download.py:Downloader.get_cache_path()` - Cache RPM
7. `download.py:download_from_peer()` - URL peer
8. `peer_client.py:query_peers_have()` - Réponse avec path
9. `database.py:add_media()` - Création média

---

## Architecture proposée

### Nouvelle structure de chemins

```
Officiels:
/var/lib/urpm/medias/<version>/<arch>/media/<class>/<short_name>/
Exemple: /var/lib/urpm/medias/9/x86_64/media/core/release/

Tiers:
/var/lib/urpm/medias/<version>/<arch>/media/custom/<short_name>/
Exemple: /var/lib/urpm/medias/9/x86_64/media/custom/rpmfusion/
```

### Nouveau schéma de base de données

```sql
-- Médias (découplés des serveurs)
CREATE TABLE media (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,           -- Display name : 'Core Release', 'RPM Fusion Free'
    short_name TEXT NOT NULL,            -- Identifiant : 'core_release', 'rpmfusion-free'
    mageia_version TEXT NOT NULL,        -- '9', '10', 'cauldron' (filtrage peers)
    architecture TEXT NOT NULL,           -- 'x86_64', 'aarch64' (filtrage peers)
    relative_path TEXT NOT NULL,          -- '9/x86_64/media/core/release'
    is_official INTEGER DEFAULT 1,        -- 0 = custom
    enabled INTEGER DEFAULT 1,
    update_media INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 50,
    last_sync INTEGER,
    synthesis_md5 TEXT
);

-- Serveurs (miroirs upstream ou locaux)
CREATE TABLE server (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,              -- Nom d'affichage : 'mageia-official', 'distrib-coffee', 'local-mirror'
    protocol TEXT NOT NULL DEFAULT 'https', -- 'http', 'https', 'file'
    host TEXT NOT NULL,                     -- FQDN : 'mirrors.mageia.org', 'localhost' pour file
    base_path TEXT NOT NULL DEFAULT '',     -- Chemin de base : '/mageia', '/pub/linux/Mageia', '/mirrors/mageia'
    is_official INTEGER DEFAULT 1,          -- 0 = serveur custom
    enabled INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 50,            -- Préférence manuelle (V1: seul critère de tri)
    -- Qualimétrie (post-V1, NULL pour l'instant)
    latency_ms INTEGER,
    bandwidth_kbps INTEGER,
    failure_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    last_check INTEGER,
    UNIQUE(protocol, host, base_path)       -- Un seul enregistrement par combinaison
);

-- Liaison N:M (quels serveurs servent quels médias)
CREATE TABLE server_media (
    server_id INTEGER REFERENCES server(id),
    media_id INTEGER REFERENCES media(id),
    PRIMARY KEY (server_id, media_id)
);
```

### Construction des URLs / chemins

**Logique unifiée :**
```python
if server.protocol == 'file':
    # Miroir local : chemin direct, pas de téléchargement
    path = f"{server.base_path}/{media.relative_path}"
else:
    # Miroir distant : URL complète
    url = f"{server.protocol}://{server.host}{server.base_path}/{media.relative_path}"
```

**Exemples :**

| name | protocol | host | base_path | relative_path | Résultat |
|------|----------|------|-----------|---------------|----------|
| mageia-official | https | mirrors.mageia.org | /mageia | 9/x86_64/media/core/release | `https://mirrors.mageia.org/mageia/9/x86_64/...` |
| distrib-coffee | https | distrib-coffee.ipsl.jussieu.fr | /pub/linux/Mageia | 9/x86_64/media/core/release | `https://distrib-coffee.ipsl.jussieu.fr/pub/linux/Mageia/9/x86_64/...` |
| local-mirror | file | localhost | /mirrors/mageia | 9/x86_64/media/core/release | `/mirrors/mageia/9/x86_64/...` (chemin direct) |
| custom-repo | https | download1.rpmfusion.org | | free/fedora/40/x86_64/os | `https://download1.rpmfusion.org/free/fedora/40/x86_64/os` |

### Miroirs locaux (file://)

**Cas d'usage :** Développeurs Mageia qui rsync un miroir local.

```bash
urpm media add file:///mirrors/mageia/9/x86_64/media/core/release/
```

**Comportement spécifique :**
- Pas de téléchargement, lecture directe du chemin
- Pas de cache local (inutile, c'est déjà local)
- urpmd expose le contenu aux peers (comme s'il l'avait téléchargé)
- Priorité haute par défaut (local = rapide)

### Structure de fichiers locale

**Arborescences séparées pour la sécurité :**
```
/var/lib/urpm/medias/
├── official/                              ← médias officiels uniquement
│   └── 9/
│       └── x86_64/
│           └── media/
│               ├── core/
│               │   ├── release/
│               │   └── updates/
│               └── nonfree/
│                   └── release/
└── custom/                                ← médias custom (isolés)
    ├── rpmfusion/
    └── autre-repo/
```

**Calcul du chemin local :**
```python
if media.is_official:
    local_path = f"/var/lib/urpm/medias/official/{media.relative_path}/"
else:
    local_path = f"/var/lib/urpm/medias/custom/{media.short_name}/"
```

**Génération du short_name :**
- Officiels : concaténation automatique `{class}_{type}` → `core_release`, `nonfree_updates`, `tainted_backports`
- Custom : fourni par l'utilisateur lors de l'ajout

**Sécurité :** Un média custom ne peut jamais écrire dans l'arborescence officielle,
même avec un `relative_path` malveillant comme `"9/x86_64/media/core/release"`.

**Notes :**
- Un serveur officiel peut servir N médias officiels (tous les miroirs Mageia)
- Un serveur custom sert généralement 1 média, mais le mirroring custom est possible
- `mageia_version` et `architecture` sont utilisés pour le filtrage (peers, compatibilité locale)

---

## Points de discussion

### 1. Médias tiers/custom

**Question** : Un média custom peut-il avoir plusieurs serveurs ou est-ce toujours 1:1 ?

**Proposition** : Pour les médias `class='custom'`, on peut avoir un seul serveur dédié ou plusieurs. Le `base_url` pour un custom serait l'URL complète jusqu'au parent de `media_info/`.

### 2. Import de médias (`urpm media import`)

**Actuel** : On donne une URL complète, on extrait le hostname.

**Nouveau** : On doit parser l'URL pour extraire version/arch/class/name.

```
URL: https://mirrors.mageia.org/mageia/9/x86_64/media/core/release/
     └─ base_url ─────────────────────┘ │  │      │    └ short_name
                                        │  │      └ class
                                        │  └ architecture
                                        └ mageia_version
```

**Question** : Comment gérer les URLs non-standard (tiers) ?

### 3. Peers et chemins

**Impact majeur** : Le chemin local change complètement.

**Actuel** : Peer expose `/api/media/{hostname}/{media_name}/{file}`

**Nouveau** : Peer expose `/api/media/{version}/{arch}/media/{class}/{short_name}/{file}`

Les peers doivent utiliser la même structure. Quand un peer répond à `/api/have`, il retourne le nouveau chemin.

### 4. Sélection de serveur pour download

**Algorithme proposé** :
1. Filtrer serveurs enabled et non-blacklistés
2. Classer par score = f(latency, bandwidth, failure_rate, priority_manuelle)
3. Prendre les N meilleurs (4 par défaut)
4. Répartir les fichiers à télécharger entre eux
5. Si un serveur échoue, redistribuer sur les autres

### 5. Liste de serveurs publique

**Format JSON proposé** :
```json
{
  "version": 1,
  "updated": "2025-12-26T12:00:00Z",
  "servers": [
    {
      "name": "mageia-official",
      "base_url": "https://mirrors.mageia.org/mageia",
      "official": true,
      "countries": ["*"]
    },
    {
      "name": "distrib-coffee-fr",
      "base_url": "https://distrib-coffee.ipsl.jussieu.fr/pub/linux/Mageia",
      "official": true,
      "countries": ["FR"]
    }
  ]
}
```

### 6. Migration

**Stratégie** :
1. Créer nouvelles tables `server`, `server_media`
2. Modifier table `media` (ajouter colonnes, supprimer `url`)
3. Script de migration qui :
   - Parse les URLs existantes
   - Crée les entrées dans les nouvelles tables
   - Déplace les fichiers cache vers la nouvelle structure

---

## Questions clés à trancher

1. **Médias custom** : Structure rigide `custom/<name>` ou URL libre ?

2. **Découverte auto des serveurs** : `urpm` télécharge-t-il périodiquement la liste officielle ?

3. **Test des serveurs** : Fréquence ? Au sync seulement ou en background ?

4. **Parallélisation** : 4 serveurs simultanés par défaut, configurable ?

5. **Priorité peers vs upstream** : Toujours peers d'abord, puis les N meilleurs upstreams ?

6. **urpmd multi-version** : Un seul daemon sert plusieurs versions ? Ou un daemon par version ?

---

## Décisions prises

### 1. Ajout de médias simplifié
**Décision** : Une seule URL, parsing automatique

L'utilisateur ne voit jamais la séparation server/media. Le système parse et découpe automatiquement.

**Officiels - une seule URL :**
```bash
urpm media add https://mirrors.mageia.org/mageia/9/x86_64/media/core/release/
```

Parsing automatique :
- Détecte pattern officiel Mageia (`*/media/{class}/{type}`)
- Extrait `base_url = https://mirrors.mageia.org/mageia`
- Extrait `relative_path = 9/x86_64/media/core/release`
- Génère `name = "Core Release"`, `short_name = "core_release"`
- Crée le serveur s'il n'existe pas, puis le média, puis le lien

**Custom - URL + identifiants :**
```bash
urpm media add --custom "RPM Fusion Free" rpmfusion-free https://download1.rpmfusion.org/free/fedora/40/x86_64/os/
```

Parsing automatique :
- Extrait `base_url = https://download1.rpmfusion.org` (scheme + hostname)
- Extrait `relative_path = free/fedora/40/x86_64/os`
- Utilise le name et short_name fournis
- Crée serveur + média + lien

**En base de données (transparent pour l'utilisateur) :**
- Table `server` : créé/réutilisé automatiquement
- Table `media` : créé avec les valeurs extraites/fournies
- Table `server_media` : lien créé automatiquement

**Logique upsert (pas de doublons) :**

```python
def add_media_from_url(url):
    protocol, host, base_path, relative_path, name, short_name, version, arch = parse_url(url)

    # Upsert serveur (clé : protocol + host + base_path)
    server = get_server_by_location(protocol, host, base_path)
    if not server:
        server = create_server(name=generate_server_name(host),
                               protocol=protocol, host=host, base_path=base_path)

    # Upsert média (clé : version + arch + short_name)
    media = get_media_by_version_arch_shortname(version, arch, short_name)
    if not media:
        media = create_media(name, short_name, relative_path, version, arch)

    # Créer lien si pas déjà existant
    if not link_exists(server.id, media.id):
        create_server_media_link(server.id, media.id)
```

**Exemples :**

| Commande | Résultat |
|----------|----------|
| `add https://mirrors.mageia.org/mageia/9/.../core/release/` | +1 server, +1 media, +1 link |
| `add https://distrib-coffee.ipsl.fr/pub/linux/Mageia/9/.../core/release/` | +1 server, media existant, +1 link |
| `add https://mirrors.mageia.org/mageia/9/.../nonfree/release/` | server existant, +1 media, +1 link |
| `add file:///mirrors/mageia/9/.../core/release/` | +1 server (file/localhost), +1 media, +1 link |

**Structure locale (isolée pour sécurité) :**
```
Officiels : /var/lib/urpm/medias/official/9/x86_64/media/core/release/
Custom :    /var/lib/urpm/medias/custom/rpmfusion-free/
```

**Avantages :**
- UX simple : une seule commande avec une URL
- Logique unifiée en interne (URL = server.base_url + media.relative_path)
- Le mirroring de médias custom est possible (rare mais supporté)
- Arborescence custom isolée : impossible de polluer les médias officiels

### 2. Découverte auto des serveurs
**Décision** : DIFFÉRÉ (post-V1)

Liste publique de serveurs en JSON, téléchargement automatique → plus tard.

### 3. Test et qualimétrie des serveurs
**Décision** : DIFFÉRÉ (post-V1)

Pour la V1 :
- Pas de mesure de latence/bande passante
- Pas de scoring automatique
- Sélection basée sur `priority` manuelle et `enabled`
- Fallback simple : si un serveur échoue, passer au suivant

Post-V1 (à implémenter plus tard) :
- Mesure latence au sync (HEAD request)
- Mesure bande passante au download
- Test périodique en background (urpmd)
- Score de classement automatique

### 4. Parallélisation
**Décision** : 4 serveurs simultanés par défaut, configurable

Configuration via `/etc/urpm/urpm.conf` ou argument CLI.

### 5. Priorité peers vs upstream
**Décision** : Toujours peers d'abord, puis les N meilleurs upstreams

Ordre de priorité :
1. Peers disponibles (load-balanced entre eux)
2. Si peers n'ont pas le fichier → upstreams classés par score
3. Fallback sur upstream suivant si échec

### 6. urpmd multi-version
**Décision** : Un seul daemon sert toutes les versions

Le daemon urpmd peut servir Mageia 9, 10, cauldron depuis la même instance.
La structure de chemins le permet naturellement :
```
/var/lib/urpm/medias/9/x86_64/media/...
/var/lib/urpm/medias/10/x86_64/media/...
/var/lib/urpm/medias/cauldron/x86_64/media/...
```

---

## Plan d'implémentation V1

**Scope V1 :** Structure de base, pas de qualimétrie, pas de liste publique.

### Phase 1 - Schéma BDD et migration ✅
**Fichier principal :** `urpm/core/database.py`

- [x] Créer table `server` (avec ip_mode pour IPv4/IPv6)
- [x] Créer table `server_media`
- [x] Modifier table `media` (nouvelles colonnes : short_name, relative_path, is_official)
- [x] Script de migration des données existantes (v7→v8, v8→v9, v9→v10)
- [x] Fonctions CRUD pour `server` : `add_server()`, `get_server()`, `get_server_by_location()`, `list_servers()`, `remove_server()`
- [x] Fonctions pour `server_media` : `link_server_media()`, `get_servers_for_media()`, `get_media_for_server()`
- [x] Fonction `get_best_server_for_media(media_id)` : retourne le serveur enabled avec la plus haute priority

### Phase 2 - Nouvelle structure de chemins ✅
**Fichiers :** `urpm/core/config.py`, `urpm/core/sync.py`

- [x] Nouvelle fonction `get_media_local_path(media)` → `official/{relative_path}/` ou `custom/{short_name}/`
- [x] Adapter `get_media_cache_dir()` pour utiliser la nouvelle structure
- [x] Fonction `build_media_url(media, server)` → `{server.base_url}/{media.relative_path}`
- [x] Adapter `build_synthesis_url()`, `build_hdlist_url()`, `build_md5sum_url()`
- [x] Script de migration des fichiers cache existants

### Phase 3 - Sync avec sélection serveur ✅
**Fichier :** `urpm/core/sync.py`

- [x] `sync_media()` : utiliser `get_best_server_for_media()` pour choisir le serveur
- [x] Fallback simple : si échec, passer au serveur suivant par priority

### Phase 4 - Download multi-serveurs ✅
**Fichier :** `urpm/core/download.py`

- [x] `get_servers_for_media(media_id, n=4)` : retourne les N serveurs enabled triés par priority
- [x] Modifier `DownloadItem` pour utiliser la nouvelle logique
- [x] `DownloadCoordinator` : répartir les fichiers entre serveurs disponibles (slot-based)
- [x] Gestion des échecs : redistribuer sur autres serveurs
- [x] Support ip_mode per-server (évite timeout IPv6)

### Phase 5 - Adaptation peers ✅
**Fichiers :** `urpm/core/peer_client.py`, `urpm/daemon/server.py`

- [x] Adapter `/api/have` pour retourner les nouveaux chemins (official/... ou custom/...)
- [x] Adapter `/api/media/` pour servir avec la nouvelle structure
- [x] Adapter `download_from_peer()` pour les nouveaux chemins
- [x] ThreadingHTTPServer pour requêtes parallèles

### Phase 6 - CLI ✅
**Fichier :** `urpm/cli/main.py`

- [x] `urpm media add <url>` : parsing auto, création server+media+lien (upsert)
- [x] `urpm media add --custom <name> <short_name> <url>` : ajout custom
- [x] Adapter `urpm media list` pour afficher les serveurs liés
- [x] `urpm server list` : lister les serveurs avec priority/enabled/ip_mode
- [x] `urpm server add` : ajouter serveur + test IP + scan media existants
- [x] `urpm server remove <name>` : supprimer un serveur (cascade liens)
- [x] `urpm server enable/disable <name>` : activer/désactiver
- [x] `urpm server priority <name> <priority>` : changer la priorité
- [x] `urpm server test [name]` : tester connectivité et détecter ip_mode
- [x] `urpm server ip-mode <name> <mode>` : forcer mode IP manuellement

---

## Post-V1 (différé)

- [ ] Qualimétrie : mesure latence, bande passante, scoring automatique
- [ ] Test périodique des serveurs (urpmd scheduler)
- [ ] Liste publique de serveurs en JSON

---

## Implémentation V1 - TERMINÉE ✅

Toutes les phases ont été implémentées :
1. ✅ Phase 1 - BDD (fondation) + migration v7→v10
2. ✅ Phase 2 - Chemins (official/custom)
3. ✅ Phase 3 - Sync avec sélection serveur
4. ✅ Phase 4 - Download multi-serveurs + ip_mode
5. ✅ Phase 5 - Peers adaptés
6. ✅ Phase 6 - CLI complète (media + server)

**Bonus implémentés :**
- ip_mode per-server (auto/ipv4/ipv6/dual) pour éviter timeout IPv6
- Test connectivité IPv4/IPv6 lors de l'ajout de serveur
- Scan parallèle des media existants lors de server add
- ThreadingHTTPServer pour peer downloads parallèles
