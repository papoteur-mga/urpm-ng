# Revue comparative : DNF vs urpm-ng

Ce document identifie les fonctionnalités de DNF (et DNF5) absentes ou incomplètes dans urpm-ng, afin de prioriser les développements pour atteindre la parité fonctionnelle.

## Légende

| Symbole | Signification |
|---------|---------------|
| ✅ | Implémenté dans urpm-ng |
| ⚠️ | Partiellement implémenté |
| ❌ | Non implémenté (gap à combler) |
| ➖ | Non applicable à Mageia |

---

## 1. Gestion des paquets de base

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| install | `dnf install` | ✅ `urpm install` | Complet |
| remove | `dnf remove` | ✅ `urpm erase` | Complet |
| upgrade | `dnf upgrade` | ✅ `urpm upgrade` | Complet |
| downgrade | `dnf downgrade` | ❌ | **À implémenter** |
| reinstall | `dnf reinstall` | ✅ `urpm install --reinstall` | Complet |
| autoremove | `dnf autoremove` | ✅ `urpm autoremove` | Complet, même étendu |
| swap | `dnf swap pkg1 pkg2` | ❌ | Transaction combinée remove+install |
| distro-sync | `dnf distro-sync` | ❌ | Sync vers versions exactes du dépôt |
| check | `dnf check` | ❌ | Vérification intégrité BDD |

### Priorités
- **downgrade** : DIFFÉRÉE - rollback manuel, cas d'usage moins fréquent
- **distro-sync** : MOYENNE - utile pour réaligner un système sur le dépôt

---

## 2. Mises à jour de sécurité et advisories

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| Lister advisories | `dnf updateinfo list` | ❌ | Afficher les advisories disponibles |
| Info advisory | `dnf updateinfo info XXXX` | ❌ | Détails d'un advisory |
| Filtrer par CVE | `--cve CVE-2024-xxxx` | ❌ | Installer/lister par CVE |
| Filtrer par advisory | `--advisory MGASA-2024-xxxx` | ❌ | Installer par ID advisory |
| Filtrer par sévérité | `--security --sec-severity Critical` | ❌ | Critical/Important/Moderate/Low |
| Updates sécurité only | `dnf upgrade --security` | ❌ | N'installer que les patches sécu |
| Bugzilla filter | `--bz 12345` | ❌ | Filtrer par bug ID |

### Priorité : DIFFÉRÉE
Fonctionnalité entreprise nécessitant une infrastructure conséquente. À aborder une fois la base stabilisée.

### Prérequis
- Mageia doit publier des métadonnées d'advisories (format updateinfo.xml ou équivalent)
- Parser et stocker ces métadonnées dans la BDD urpm
- Base urpm-ng stable et communauté établie

---

## 3. Mises à jour automatiques et hors-ligne

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| Updates automatiques | `dnf-automatic` | ⚠️ | urpmd pré-télécharge mais n'installe pas auto |
| Config auto-updates | `/etc/dnf/automatic.conf` | ❌ | Scheduling, notification, auto-install |
| Offline upgrade | `dnf offline-upgrade download` | ❌ | Télécharger puis appliquer au reboot |
| Upgrade minimal | `dnf upgrade-minimal` | ❌ | Minimum nécessaire pour fix sécu/bug |

### Priorité : MOYENNE
- **offline-upgrade** : Important pour serveurs de production (appliquer au reboot propre)
- **automatic** : urpmd a la base, manque la partie auto-install configurable

---

## 4. Recherche et requêtes avancées

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| search | `dnf search` | ✅ `urpm search` | Complet |
| info | `dnf info` | ✅ `urpm show` | Complet |
| list | `dnf list` | ✅ `urpm list` | Complet |
| provides | `dnf provides` | ✅ `urpm whatprovides` | Complet |
| repoquery | `dnf repoquery` | ⚠️ | Partiel, options limitées |
| repoquery --files | `dnf repoquery -l pkg` | ⚠️ | Nécessite parsing hdlist.cz |
| repoquery --requires | `dnf repoquery --requires` | ✅ `urpm depends` | Complet |
| repoquery --whatrequires | `dnf repoquery --whatrequires` | ✅ `urpm rdepends` | Complet |
| deplist | `dnf deplist` | ✅ `urpm depends` | Équivalent |

### Priorité : BASSE
urpm-ng couvre la majorité des cas d'usage. Le parsing hdlist.cz améliorerait les requêtes fichiers.

---

## 5. Groupes de paquets

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| group list | `dnf group list` | ❌ | Lister les groupes disponibles |
| group info | `dnf group info "Group Name"` | ❌ | Contenu d'un groupe |
| group install | `dnf group install "Group Name"` | ❌ | Installer un groupe |
| group remove | `dnf group remove "Group Name"` | ❌ | Supprimer un groupe |
| group upgrade | `dnf group upgrade` | ❌ | Mettre à jour un groupe |
| group mark | `dnf group mark install` | ❌ | Marquer groupe installé |

### Priorité : HAUTE
Les groupes de paquets facilitent l'installation d'environnements complets et attirent les utilisateurs.

**Implémentation** : Réutiliser la même source de données que le seeding (rpmsrate/compssUsers.pl). Cette approche garantit la cohérence entre :
- `urpm group list/install` pour les utilisateurs
- `urpm seed` pour la création de miroirs thématiques

```
urpm group list           → Liste les groupes disponibles (Plasma, GNOME, Développement, etc.)
urpm group info plasma    → Détail du contenu du groupe
urpm group install plasma → Installe l'ensemble des paquets du groupe
```

---

## 6. Modules (streams de versions)

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| module list | `dnf module list` | ➖ | Mageia n'utilise pas les modules |
| module enable | `dnf module enable nodejs:18` | ➖ | |
| module install | `dnf module install nodejs:18/default` | ➖ | |

### Non applicable
Mageia gère les versions multiples différemment (php8.3, php8.4 comme paquets séparés). Le système de préférences urpm (`--prefer=php:8.4`) couvre ce besoin.

---

## 7. Gestion des dépôts

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| repolist | `dnf repolist` | ✅ `urpm media list` | Complet |
| repoinfo | `dnf repoinfo` | ⚠️ | Basique, pas toutes les stats |
| config-manager | `dnf config-manager --add-repo` | ✅ `urpm media add` | Complet |
| repo enable/disable | `dnf config-manager --enable/--disable` | ✅ `urpm media enable/disable` | Complet |
| repo priority | Configuration priorité | ✅ `urpm server priority` | Complet |
| makecache | `dnf makecache` | ✅ `urpm media update` | Complet |
| clean | `dnf clean all` | ✅ `urpm cache clean` | Complet |

### Priorité : BASSE
Couverture fonctionnelle satisfaisante.

---

## 8. Historique et rollback

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| history list | `dnf history` | ✅ `urpm history` | Complet |
| history info | `dnf history info N` | ✅ `urpm history N` | Complet |
| history undo | `dnf history undo N` | ✅ `urpm undo N` | Complet |
| history redo | `dnf history redo N` | ❌ | Rejouer une transaction |
| history rollback | `dnf history rollback N` | ✅ `urpm rollback` | Complet |
| history replay | `dnf history replay file.json` | ❌ | Rejouer depuis fichier |
| history store | `dnf history store` | ❌ | Sauvegarder transaction |
| history userinstalled | `dnf history userinstalled` | ⚠️ | Via installed-through-deps.list |

### Priorité : BASSE
Les fonctions essentielles sont présentes. `redo` et `replay` sont des nice-to-have.

---

## 9. Options de téléchargement

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| --downloadonly | `dnf install --downloadonly` | ❌ | Télécharger sans installer |
| download command | `dnf download pkg` | ❌ | Télécharger RPM localement |
| --cacheonly | `dnf --cacheonly` | ❌ | Opérer depuis cache uniquement |

### Priorité : HAUTE
- **--downloadonly** : Préparer des updates, utile pour utilisateurs avancés
- **download** : Récupérer des RPM directement

---

## 10. Développement et debug

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| builddep | `dnf builddep foo.spec` | ❌ | Installer les dépendances de build |
| debuginfo-install | `dnf debuginfo-install pkg` | ❌ | Installer les debuginfo |
| download --source | `dnf download --source pkg` | ❌ | Télécharger le SRPM |

### Priorité : HAUTE pour builddep
- **builddep** : Essentiel pour attirer les contributeurs et packagers Mageia
- debuginfo-install, download --source : MOYENNE

---

## 11. Plugins et extensions

| Fonctionnalité | DNF | urpm-ng | Notes |
|----------------|-----|---------|-------|
| Système de plugins | Architecture modulaire | ❌ | Pas de système de plugins |
| versionlock | `dnf versionlock` | ⚠️ | blacklist existe, pas versionlock |
| needs-restarting | `dnf needs-restarting` | ❌ | Services à redémarrer après update |
| system-upgrade | `dnf system-upgrade` | ❌ | Upgrade de version majeure |

### Priorités
- **system-upgrade** : HAUTE - **killer feature** pour l'adoption (Mageia 9 → 10)
- **needs-restarting** : HAUTE - fonctionnalité attendue par les utilisateurs
- **versionlock** : DIFFÉRÉE - cas d'usage entreprise

---

## 12. Performance et architecture (DNF5)

| Fonctionnalité | DNF5 | urpm-ng | Notes |
|----------------|------|---------|-------|
| Backend C++ | Oui | Non (Python) | DNF5 plus rapide |
| libsolv | Oui | ✅ Oui | Même résolveur |
| Téléchargements parallèles | Oui | ✅ Oui | Complet |
| Cache partagé | dnf5 + dnf5daemon | ⚠️ | urpm + urpmd partagent la BDD |
| Daemon D-Bus | dnf5daemon | ⚠️ urpmd HTTP | Différente approche |
| Taille installation | ~60% plus petit | N/A | Python vs C++ |

### Note
urpm-ng utilise Python ce qui est un choix raisonnable pour la maintenabilité. La performance est acceptable grâce à libsolv en C++.

---

## 13. Fonctionnalités uniques à urpm-ng

Ces fonctionnalités n'existent PAS dans DNF et sont un avantage de urpm-ng :

| Fonctionnalité | urpm-ng | Notes |
|----------------|---------|-------|
| P2P LAN | ✅ | Partage de paquets entre machines LAN |
| Découverte peers | ✅ | Broadcast UDP automatique |
| Préférences installation | ✅ `--prefer` | Guider les choix (php:8.4, etc.) |
| Replication DVD-like | ✅ seed | Créer un miroir type DVD |
| Proxy cross-version | 🚧 | Servir des paquets pour autre version Mageia |
| Gestion parc | 🚧 | Inventaire et déploiement centralisé |

---

## Résumé des priorités

> **Vision** : Construire une base saine qui attire la communauté, avant d'aborder les chantiers entreprise. L'algorithme de résolution des dépendances doit être battle-tested, l'architecture doit permettre le développement de GUI et d'outils tiers.

### Priorité HAUTE (attirer la communauté, killer features)

1. **system-upgrade** (Section 11)
   - Upgrade de version majeure Mageia (9 → 10)
   - **Killer feature** pour l'adoption

2. **groups** (Section 5)
   - Basé sur la même source que le seeding (rpmsrate)
   - Installation simplifiée d'environnements complets

3. **needs-restarting** (Section 11)
   - Indiquer si reboot/restart services nécessaire
   - Fonctionnalité attendue par les utilisateurs

4. **--downloadonly** et `download` (Section 9)
   - Préparer des mises à jour, récupérer des RPM
   - Utile pour les utilisateurs avancés

5. **builddep** (Section 10)
   - Essentiel pour les contributeurs et packagers
   - Attire la communauté de développeurs

6. **automatic** config complète (Section 3)
   - Compléter urpmd avec configuration auto-install

### Priorité MOYENNE

7. **offline-upgrade** (Section 3)
8. **distro-sync** (Section 1)
9. **swap** (Section 1)
10. **check** intégrité BDD (Section 1)
11. **debuginfo-install** (Section 10)
12. **history redo/replay** (Section 8)

### Priorité DIFFÉRÉE (chantiers entreprise)

Ces fonctionnalités nécessitent une infrastructure conséquente (APIs sécurisées, métadonnées advisories, pilotage centralisé). À aborder une fois la base stabilisée et la communauté établie.

13. **Sécurité / Advisories** (Section 2)
    - Parsing métadonnées MGASA, filtres --security/--cve
    - Requiert que Mageia publie les métadonnées

14. **versionlock** (Section 11)
    - Bloquer paquet à version spécifique

15. **downgrade** (Section 1)
    - Revenir à version antérieure

16. **APIs pilotage centralisé**
    - /api/upgrade, /api/install sécurisés
    - Console de gestion, inventaire parc

---

## Plan d'action suggéré

### Phase 0 : Fondations (en continu)

```
- Stabiliser l'algorithme de résolution des dépendances
  - Tests approfondis sur cas réels complexes
  - Couverture de tests unitaires et d'intégration

- Architecture extensible
  - API interne claire pour futures GUI
  - Séparation CLI / bibliothèque / daemon
  - Documentation développeur
```

### Phase 1 : Killer features et adoption (Priorité HAUTE)

```
1. Implémenter `urpm system-upgrade`
   - Phase download : télécharger tous les paquets nouvelle version
   - Phase apply : appliquer au reboot (ou online si possible)
   - Gestion des conflits de version majeure

2. Implémenter `urpm group`
   - Réutiliser la source rpmsrate/compssUsers.pl (comme seeding)
   - urpm group list / info / install / remove
   - Cohérence avec urpm seed

3. Implémenter `urpm needs-restarting`
   - Détecter si reboot nécessaire (kernel, glibc, etc.)
   - Lister les services à redémarrer

4. Implémenter --downloadonly et `urpm download`
   - Option --downloadonly sur install/upgrade
   - Commande `urpm download pkg` pour récupérer RPM

5. Implémenter `urpm builddep`
   - Parser les BuildRequires du SRPM ou spec
   - Installer les dépendances de build
   - Attire les contributeurs Mageia

6. Compléter automatic config (urpmd)
   - Configuration auto-install (pas seulement pré-téléchargement)
   - Équivalent dnf-automatic
```

### Phase 2 : Consolidation (Priorité MOYENNE)

```
7. offline-upgrade (télécharger puis appliquer au reboot)
8. distro-sync (réaligner sur versions exactes du dépôt)
9. swap (transaction combinée remove+install)
10. check intégrité BDD
11. debuginfo-install
```

### Phase 3 : Entreprise (Priorité DIFFÉRÉE)

À aborder une fois la communauté établie et la base stable.

```
12. Infrastructure advisories (nécessite métadonnées Mageia)
13. versionlock
14. downgrade
15. APIs sécurisées pour pilotage centralisé
```

---

## Sources

- [DNF Command Reference](https://dnf.readthedocs.io/en/latest/command_ref.html)
- [Fedora DNF Documentation](https://docs.fedoraproject.org/en-US/quick-docs/dnf/)
- [DNF5 Switch - Fedora Wiki](https://fedoraproject.org/wiki/Changes/SwitchToDnf5)
- [Red Hat Security Updates](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html-single/managing_and_monitoring_security_updates/index)
- [DNF vs DNF5 - TecMint](https://www.tecmint.com/dnf-vs-dnf5/)
