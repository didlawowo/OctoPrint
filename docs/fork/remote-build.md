# Construire la SD depuis macOS via SSH

`task pi:build` détecte maintenant le poste : sur macOS (Apple Silicon ou Intel),
il délègue le build Linux à l'alias SSH **nvidia**, puis récupère les résultats.
Sur Linux x86_64, le build reste local. Docker Desktop sur le Mac n'est pas requis
ni utilisé pour les montages loopback privilégiés de CustoPiZer.
Cette page complète le mode de build Linux décrit dans `atelier.md`.

```sh
git pull --ff-only
task pi:prepare
task pi:build
task pi:flash
```

Le Mac doit disposer de Git, Python >=3.10, Go Task et OpenSSH. Le serveur doit
être joignable avec `ssh nvidia`, disposer de Python >=3.10, Git, Docker Linux
accessible au compte SSH sans sudo, et au moins 20 Gio libres dans son home.
Il doit pouvoir accéder au fork GitHub public, à GHCR et aux dépendances du build.
La tâche ne tente ni d'installer Docker, ni de changer les droits du compte.

Les clés et options de connexion sont celles de ton `~/.ssh/config`. L'agent SSH
n'est pas transmis au serveur et la vérification des clés d'hôte n'est pas
désactivée. Pour une première connexion, établir manuellement `ssh nvidia`
et vérifier l'empreinte ; le build utilise ensuite l'authentification par clé
sans demande interactive de mot de passe.

Pour un autre serveur, ou pour forcer le mode distant depuis Linux :

```sh
task pi:build BUILD_MODE=ssh BUILD_HOST=cluster@nvidia
```

## Quel code est construit ?

Le serveur crée un **nouveau clone isolé** dans
`~/.cache/octoprint-atelier/build-*/source`, et récupère exactement le SHA de
`HEAD` sur ton Mac. Le commit doit donc être poussé dans `didlawowo/OctoPrint`.
Aucun checkout, environnement d'inférence ou service déjà présent sur le serveur
n'est modifié par ces commandes. Aucun fichier `.venv`, secret local ou fichier
non suivi n'est envoyé : le serveur lit le dépôt public au commit sélectionné.
Le build emploie un conteneur CustoPiZer privilégié, comme le build Linux natif.

Un arbre de travail modifié est refusé par défaut. Pour construire le dernier
commit poussé tout en gardant tes modifications locales intactes, le mode SSH
propose une option explicite :

```sh
task pi:build BUILD_COMMITTED=1
```

Cette option **n'inclut pas** les changements non committés et ne les efface pas.
Elle est utile notamment si la compilation des traductions a sali le checkout.
Ne pas utiliser `git reset --hard` pour contourner ce contrôle.

## Résultat sur le Mac

L'image, son SHA256 et `build.json` reviennent dans `build/atelier-pi/`. Le SHA256
et le commit sont vérifiés avant de remplacer une image locale existante ; un
transfert incomplet ou corrompu laisse l'ancienne image intacte. Le catalogue
Raspberry Pi Imager est régénéré avec le chemin du Mac, pas celui du serveur.

`task pi:flash` ouvre **Imager sur le Mac** et demande de sélectionner/confirmer
la carte SD locale. Il n'existe pas de flash distant ni d'accès SD/USB du serveur.
Le flash efface la carte choisie : conserver la SD actuelle pour revenir en arrière.

Les dossiers distants sont conservés pour diagnostic et récupération ; ils peuvent
être volumineux et devront être nettoyés après vérification de la nouvelle image
et de l'absence de build actif. Aucun nettoyage privilégié automatique n'est lancé.

Après une interruption du téléchargement, si l'image distante est bien terminée :

```sh
task pi:fetch
```

Cette tâche utilise `build/atelier-pi/remote-build.json` et retélécharge les
résultats sans reconstruire. Elle ne relance pas un build distant interrompu.
Ne pas lancer plusieurs builds simultanés dans le même checkout local.

Les tests `tests/atelier/test_remote.py` couvrent la sélection du builder,
les paramètres SSH, le commit exact, les échecs de transfert et la conservation
de l'image précédente, avec des doublures : aucun serveur ni disque n'est touché.
