# Atelier : interface mobile/tablette et SD de test

La branche `main` du fork ajoute un tableau de bord sombre, tactile et français.
Il est activé par défaut ; `?classic=1` retrouve l'interface historique.
Le code dérive d'**OctoPrint 2.0.0rc6 épinglé**, et non de la branche `dev` upstream :
ce n'est pas une release stable officielle. Utiliser une **seconde carte SD** pour tester
et conserver la carte actuelle intacte. Le flash efface entièrement la cible.

## Construire l'image pour le Raspberry Pi 4

Sur le Mac (build délégué automatiquement à `ssh nvidia`) ou un hôte
**Linux x86_64** avec Python 3.10+, Git, Docker accessible à
l'utilisateur, Go Task v3 et au moins **20 Gio libres** côté builder :

```sh
git clone --branch main https://github.com/didlawowo/OctoPrint.git
cd OctoPrint
task pi:prepare
task pi:test  # nécessite aussi Node.js >= 18
task pi:build
```

Dans un clone existant : `git fetch origin`, puis `git switch main`
(ou `git switch --track origin/main` si la branche locale n'existe pas).

`task build` garde son rôle amont : construire le package Python. **La tâche SD
est `task pi:build`.** Le checkout doit être propre : le builder embarque
exactement `git archive HEAD`, pas des changements locaux oubliés. Les sorties
restent sous `build/atelier-pi/` et ne doivent pas être committées.

Le build vérifie le SHA256 d'une image OctoPi officielle épinglée, résout le
conteneur officiel CustoPiZer vers son digest, puis remplace OctoPrint dans
l'image par ce checkout. Le catalogue FR est compilé et embarqué, le français
est la langue par défaut et les confirmations de lancement/annulation sont
activées. Les dépendances Python sont installées dans le venv de l'image.
Le build vérifie leur cohérence et la présence des fichiers du nouveau plugin.

CustoPiZer nécessite **Docker privileged**, utilise des loopbacks et un chroot
QEMU. L'exécuter sur un hôte de confiance, pas dans un cluster de production.
Aucun disque physique n'est sélectionné par la commande de build.
L'accès Internet est nécessaire. Les versions des dépendances Python sont celles
résolues au build : le SHA du code et le digest du builder sont tracés, mais
on ne prétend pas à des images reproductibles bit à bit.

Sorties :

```text
build/atelier-pi/octopi-atelier.img
build/atelier-pi/octopi-atelier.img.sha256
build/atelier-pi/build.json
build/atelier-pi/atelier.rpi-imager-manifest
```

`build.json` contient le commit, la base OS, son SHA256 et le digest du builder.
Un build réussi ne remplace pas un essai de démarrage sur le Pi.

## Flasher et configurer le premier démarrage

Installer Raspberry Pi Imager sur le poste disposant du lecteur SD, puis :

```sh
task pi:flash
```

La tâche vérifie d'abord le SHA256 de l'image, puis ouvre un catalogue local
Imager contenant cette image, avec la personnalisation **systemd de Bookworm**.
Dans Imager, sélectionner l'image Atelier et **vérifier attentivement la carte
cible**, puis renseigner utilisateur, réseau Wi-Fi si nécessaire et SSH.
Choisir par exemple le nom d'hôte `octopi-atelier` pour éviter un conflit avec
l'installation actuelle. Confirmer l'effacement dans Imager et laisser finir
la vérification. Aucun mot de passe, clé SSH ou accès automatique n'est intégré
par nos scripts ; ne pas partager une SD déjà personnalisée ou démarrée.

Sur un autre poste, copier l'image **et son fichier `.sha256`**, avec le checkout,
puis lancer :

```sh
task pi:flash IMAGE=/chemin/octopi-atelier.img
```

Le catalogue est régénéré pour ce chemin local. `RPI_IMAGER` permet de spécifier
l'exécutable s'il n'est pas dans le PATH. Le build local direct n'est pas pris en charge sur macOS/Windows ; macOS
utilise `ssh nvidia` pour le build. Le lancement d'Imager est prévu pour Linux/macOS et un Python
local compatible. Sur Windows, utiliser directement Imager et son catalogue
local ou une image personnalisée ; vérifier que les options de personnalisation
sont effectivement proposées avant de faire un démarrage sans écran.

Éteindre le Pi avant de changer de SD. Pour le premier essai, laisser l'USB de
l'imprimante débranché, attendre le démarrage, puis ouvrir
`http://octopi-atelier.local/`. Le service Atelier du premier démarrage crée
un compte administrateur avec un secret aléatoire propre à la SD, et termine
l'assistant. Les identifiants de secours se trouvent dans le répertoire OctoPrint
de l'utilisateur Pi, fichier privé `atelier-credentials.yaml` (mode 0600).
**Attention : les sous-réseaux privés détectés au démarrage sont autorisés pour
l'AutoLogin administrateur.** Ne pas exposer OctoPi à un réseau non fiable.
Tester l'interface avant de reconnecter une imprimante au repos.

## Flash brut Linux, facultatif

Imager est recommandé pour un premier démarrage : le flash brut **ne configure
ni utilisateur, ni Wi-Fi, ni SSH**. Il convient à une image déjà préparée ou à
une configuration locale avec écran/clavier.

```sh
task pi:devices
task pi:flash-check DEVICE=/dev/sdX  # remplacer sdX par la vraie carte
# Démonter les partitions de cette carte avec l'outil du système, puis :
task pi:flash-cli DEVICE=/dev/sdX
```

La vérification refuse une partition, un disque non amovible, un disque monté,
le swap, LVM/RAID, une cible trop petite et un SHA256 absent ou incorrect.
Aucun démontage automatique et aucun `--yes`. La commande exige un terminal,
sudo, et la saisie exacte `EFFACER /dev/sdX`. L'identité de la cible est revérifiée
après confirmation ; le périphérique est ouvert exclusivement, puis relu
intégralement après écriture pour contrôler son SHA256. Les lecteurs qui ne
signalent pas leur caractère amovible sont refusés : utiliser Imager dans ce cas.

## Interface et recette

Le tableau de bord montre les vraies températures et leurs courbes, le fichier
sélectionné, la progression, les estimations, les derniers fichiers et la caméra.
Les valeurs absentes restent absentes : pas de faux état d'impression ni de
coordonnées XYZ/vitesse inventées. La navigation passe en barre basse sur mobile,
puis en barre latérale et en grille sur tablette paysage.

Les actions réutilisent les viewmodels OctoPrint : permissions, confirmations,
hooks de plugins, sélection et téléversement des fichiers restent natifs. Les
panneaux Contrôle, températures détaillées, Réglages et extensions sont conservés
et habillés, pas réécrits. « Plus » expose les onglets avancés ; la barre OctoPrint
d'origine conserve le compte utilisateur et les paramètres. La page Fichiers
réutilise le widget d'origine sans le cloner ni le rebinder.

L'aperçu caméra du dashboard prend en charge le flux HTTP(S)/MJPEG de Classic
Webcam, respecte ses transformations et s'arrête quand il n'est plus visible.
HLS, WebRTC et les autres fournisseurs restent dans **Lecteur natif et autres
caméras**. L'aperçu n'est pas chargé sur l'accueil d'un petit écran.

Recette conseillée : vérifier à 360/390 px et en tablette portrait/paysage ;
ouvrir Fichiers, Contrôle, Caméra, Plus, Connexion et Réglages ; vérifier l'absence
de défilement horizontal de la page, puis la déconnexion/reconnexion du serveur.
Sans fichier sélectionné, Imprimer doit être désactivé. Sur une petite impression
surveillée, tester Pause/Reprendre et le refus d'une annulation non confirmée.
Les plugins tiers modifiant fortement le DOM doivent faire l'objet d'une recette.

Secours, y compris après un bug JavaScript :

```text
http://octopi-atelier.local/?classic=1
```

Revenir à l'URL sans `classic` réactive Atelier. La carte SD d'origine fournit
le rollback OS complet. Ne pas lancer une mise à jour vers OctoPrint officiel
en pensant conserver les fichiers propres au fork.

## Tests

`task pi:test` exécute les tests Node/Python sans serveur, sans sudo et sans carte.
Ils couvrent les gardes des actions, les valeurs absentes, l'historique borné,
les permissions caméra/fichiers et les protections du flasheur.
Les spécifications `tests/playwright/specs/atelier.spec.js` testent le rendu réel
avec le serveur et les comptes de test existants. Elles ne lancent ni impression
ni mouvement moteur. Le workflow Atelier lance les unités et cette recette
Chromium. Les tests amont continuent à viser explicitement l'interface classique.

La validation unitaire ne constitue pas une validation matérielle du boot,
du Wi-Fi, du port série ou de la caméra du Raspberry Pi.

## Références amont

- [OctoPi / téléchargement et sommes de contrôle](https://octoprint.org/download/)
- [CustoPiZer : construction et scripts de personnalisation](https://github.com/OctoPrint/CustoPiZer)
- [Raspberry Pi Imager : catalogue personnalisé](https://github.com/raspberrypi/rpi-imager)
