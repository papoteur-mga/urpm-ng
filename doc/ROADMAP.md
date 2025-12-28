# urpm-ng Roadmap

> **Vision** : Construire une base saine qui attire la communauté, avant d'aborder les chantiers entreprise. L'algorithme de résolution des dépendances doit être battle-tested, l'architecture doit permettre le développement de GUI et d'outils tiers.

## Phase 0 : Fondations (en continu)

### Stabilisation du coeur
- [ ] Tests approfondis de l'algorithme de résolution sur cas réels complexes
- [ ] Couverture de tests unitaires et d'intégration
- [ ] Validation des alternatives et --prefer sur cas variés

### Architecture extensible
- [ ] API interne claire pour futures GUI (mgaonline-ng, rpmdrake-ng)
- [ ] Séparation nette CLI / bibliothèque / daemon
- [ ] Documentation développeur

---

## Phase 1 : Killer features et adoption

### 1. system-upgrade (Mageia 9 → 10)
**Priorité : HAUTE** - Killer feature pour l'adoption

- [ ] Phase download : télécharger tous les paquets nouvelle version
- [ ] Phase apply : appliquer au reboot (ou online si possible)
- [ ] Gestion des conflits de version majeure
- [ ] Tests sur upgrade réel mga9 → mga10

### 2. groups (basé sur rpmsrate)
**Priorité : HAUTE** - Installation simplifiée d'environnements

Réutiliser la source rpmsrate/compssUsers.pl (même source que seeding).

- [ ] `urpm group list` - lister les groupes disponibles
- [ ] `urpm group info <group>` - détail du contenu
- [ ] `urpm group install <group>` - installer l'ensemble
- [ ] `urpm group remove <group>` - supprimer le groupe
- [ ] Cohérence avec `urpm seed`

### 3. needs-restarting
**Priorité : HAUTE** - Fonctionnalité attendue par les utilisateurs

- [ ] Détecter si reboot nécessaire (kernel, glibc, systemd, etc.)
- [ ] Lister les services à redémarrer après mise à jour
- [ ] Intégration avec urpmd pour notification

### 4. --downloadonly et download
**Priorité : HAUTE** - Utile pour utilisateurs avancés

- [ ] Option `--downloadonly` sur install/upgrade
- [ ] Commande `urpm download <pkg>` pour récupérer RPM sans installer

### 5. builddep
**Priorité : HAUTE** - Attire les contributeurs et packagers

- [ ] Parser les BuildRequires du SRPM ou .spec
- [ ] `urpm builddep <pkg.spec>` ou `urpm builddep <pkg.src.rpm>`
- [ ] Installer les dépendances de build

### 6. automatic config (urpmd)
**Priorité : HAUTE**

- [ ] Configuration auto-install (pas seulement pré-téléchargement)
- [ ] Équivalent dnf-automatic avec options de notification
- [ ] Fichier de config `/etc/urpm/automatic.conf`

---

## Phase 2 : Consolidation

| Fonctionnalité | Description |
|----------------|-------------|
| offline-upgrade | Télécharger puis appliquer au reboot |
| distro-sync | Réaligner sur versions exactes du dépôt |
| swap | Transaction combinée remove+install |
| check | Vérification intégrité BDD |
| debuginfo-install | Installer les paquets debuginfo |

---

## Phase 3 : GUI et outils tiers

### mgaonline-ng (applet systray)
- [ ] Notification des mises à jour disponibles
- [ ] Liste/choix des updates avec gestion dépendances
- [ ] Suivi visuel de l'avancement

### rpmdrake-ng (application complète)
- [ ] IHM de base
- [ ] Recherche et sélection multicritères
- [ ] Install/update/remove avec suivi
- [ ] Gestion des médias
- [ ] Gestion des blacklists/redlists
- [ ] Affichage et gestion des peers
- [ ] Configuration (kernels, quotas, urpmd)

---

## Phase 4 : Entreprise (différée)

Ces fonctionnalités nécessitent une infrastructure conséquente. À aborder une fois la communauté établie et la base stable.

| Fonctionnalité | Description |
|----------------|-------------|
| Advisories/Sécurité | Parsing MGASA, filtres --security/--cve |
| versionlock | Bloquer paquet à version spécifique |
| downgrade | Revenir à version antérieure |
| APIs sécurisées | /api/upgrade, /api/install avec auth |
| Gestion de parc | Inventaire, déploiement centralisé |

---

## Référence

Voir [revue_dnf_vs_urpm.md](revue_dnf_vs_urpm.md) pour le comparatif détaillé DNF vs urpm-ng.
