# Premier démarrage préconfiguré

Arrêter OctoPrint avant d'injecter la configuration. Depuis le clone du fork,
après `task init-dev` :

```sh
task configure
task dev PORT=5001
```

Le preset `configs/atelier-local.yaml` remplit les choix non renseignés :
français, nom Atelier, télémétrie désactivée, vérification de connexion Internet
et blocage des plugins problématiques activés, confirmations d'impression.
Les choix déjà enregistrés prennent le dessus sur ces valeurs par défaut.

La tâche termine explicitement le premier démarrage et enregistre les versions
actuelles des assistants Core Wizard (4) et File Check (1). Les plugins restent
actifs ; une nouvelle version de leur assistant pourra être présentée après
une mise à jour. Cela ne désactive pas les contrôles de fichiers à l'impression.
Aucun profil d'imprimante, port USB, dimensions ou flux caméra n'est inventé.
Vérifier ces paramètres avant la première impression réelle.

## Compte et connexion automatique

Sur une installation vide, un compte administrateur `atelier` est créé par le
gestionnaire natif d'OctoPrint. Son mot de passe est aléatoire et propre à cette
installation, jamais versionné ni affiché dans les logs. Les identifiants de
secours sont enregistrés dans `BASEDIR/atelier-credentials.yaml`, permissions
`0600`. Garder ce fichier privé : il contient le mot de passe en clair pour la
récupération et les actions nécessitant une nouvelle authentification.

Un unique administrateur actif existant est réutilisé sans changer son mot de
passe. S'il y en a plusieurs, choisir explicitement :

```sh
task configure LOCAL_USER=chris
```

L'AutoLogin natif est activé uniquement pour `127.0.0.1/32` et `::1/128` par
défaut. Ce n'est pas une suppression de l'authentification. La protection CSRF,
les autorisations et la réauthentification des actions sensibles sont conservées.
Le bandeau de prudence relatif aux reverse proxies n'est pas acquitté à ta place.

Pour un téléphone ou une tablette, ajouter explicitement le vrai sous-réseau LAN.
Exemple uniquement, à adapter à ton réseau :

```sh
task configure LOCAL_NETWORKS=192.168.42.0/24
task dev HOST=0.0.0.0 PORT=5001
```

Les plages publiques et les jokers `0.0.0.0/0` ou `::/0` sont refusés. Tous les
appareils de la plage autorisée auront accès au compte choisi : ne pas exposer
ce service sur Internet et vérifier les en-têtes transmis par un reverse proxy.
Les réglages de confiance du proxy ne sont pas modifiés par cet outil.

## Raspberry Pi

Même injecteur, avec le clone disponible sur le Pi et l'environnement Python
de l'installation cible. Exemple pour les chemins OctoPi du builder :

```sh
sudo systemctl stop octoprint
task configure BASEDIR=/home/pi/.octoprint OCTOPRINT_PYTHON=/home/pi/oprint/bin/python
sudo systemctl start octoprint
```

Exécuter la tâche avec l'utilisateur propriétaire des fichiers OctoPrint, pas
avec sudo. Ajouter `LOCAL_NETWORKS` pour autoriser les navigateurs du LAN.
Les noms d'utilisateur, chemins et nom de service sont à adapter s'ils diffèrent.
Cette tâche ne configure ni Wi-Fi, ni SSH, ni une carte SD. Elle n'est pas
exécutée automatiquement pendant le build de l'image : aucun compte ou secret
commun n'est embarqué dans des images destinées à plusieurs installations.

## Conservation de la configuration

Chaque exécution sauvegarde un éventuel `config.yaml` sous
`config.yaml.before-atelier-<date>`, avec permissions `0600`. Les mots de passe,
clés API, profils, fichiers et paramètres existants ne sont pas remplacés.
Seuls le statut de premier démarrage, les versions d'assistants connues et
l'AutoLogin demandé sont explicitement appliqués. Une seconde exécution ne
recrée pas le compte et ne fait pas tourner son mot de passe.

Un autre preset sans secret peut être passé avec `CONFIG_PRESET=/chemin/preset.yaml`.
Les gestionnaires de comptes personnalisés, chemins de comptes externes et
liens symboliques sur les fichiers ciblés nécessitent une configuration manuelle.
Les assistants de plugins tiers ne sont pas globalement désactivés.
