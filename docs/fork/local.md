# Lancer Atelier en local avec uv

Sur macOS ou Linux, installer **uv** et **Go Task v3**. Sur macOS, uv peut être
installé avec `brew install uv`. Pas besoin de pipx, d'un Python Homebrew 3.11
fonctionnel ou d'activer manuellement un environnement.

Dans le clone, sur `feat/atelier-mobile-tablet` :

```sh
task init-dev
task dev
```

Ouvrir `http://127.0.0.1:5000/?l10n=fr`, terminer l'assistant OctoPrint et créer
un compte local. Sans imprimante connectée, les commandes matérielles restent
indisponibles. Ctrl+C arrête le serveur. `?classic=1` permet de revenir à
l'interface historique.

`task init-dev` prépare `.venv` avec un **Python 3.11 géré par uv**, puis installe
le fork en mode éditable, ses dépendances de développement, plugins/documentation,
et le hook pre-commit. Les paquets sont installés via **uv pip**, jamais via le
pip système. Le paquet `pip` est présent uniquement pour les fonctions natives
du gestionnaire de plugins OctoPrint ; pipx n'est pas utilisé.

`task dev` peut aussi être lancé seul pour une prévisualisation : il prépare
l'environnement et installe les dépendances de fonctionnement, compile/intègre
les traductions et lance le binaire `.venv/bin/octoprint`. Il n'installe pas les
hooks de développement. Les étapes sont séquentielles et s'arrêtent à la première
erreur. Aucun `source .venv/bin/activate` ou export de version n'est nécessaire.
Les deux branches du fork sont reconnues par le calcul de version.

## Réparer un environnement partiellement créé

Le script ne lance pas `python -m venv` ni `ensurepip`. Il sélectionne le Python
géré par uv avant de toucher à l'environnement existant. Une `.venv` incomplète,
invalide ou utilisant un autre interpréteur est **renommée**, pas supprimée :

```text
.venv.broken-<date>-<pid>/
```

Un environnement valide est réutilisé. Une `.venv` qui est un lien symbolique ou
un fichier ordinaire est refusée. `.venv/`, les sauvegardes `.venv.broken-*/` et
les environnements `venv*` sont ignorés par Git. Cela ne retire pas rétroactivement
des fichiers déjà suivis ; vérifier un éventuel cas avec `git ls-files .venv venv`.
Les fichiers source et la configuration OctoPrint ne sont pas effacés.

## Téléphone et tablette

Pour écouter sur le réseau local, après avoir créé le compte :

```sh
task dev HOST=0.0.0.0
```

Ouvrir `http://IP_LOCALE_DU_POSTE:5000/?l10n=fr` depuis le même réseau.
Ne pas ouvrir ce port sur Internet. Par défaut, l'écoute reste limitée à
`127.0.0.1`. Les variables `PORT` et `BASEDIR` sont aussi configurables :

```sh
task dev PORT=5001 BASEDIR="$HOME/.octoprint-atelier-local"
```

Le répertoire par défaut est `$HOME/.octoprint-atelier-local`, distinct d'une
installation OctoPrint habituelle. Le Python peut être choisi avec
`PYTHON_VERSION=3.12` (versions acceptées : 3.10 à 3.14). Un changement
d’interpréteur conserve également l'ancien environnement sous un nom de secours.

Ce démarrage local ne construit pas d'image Pi et ne flashe aucune carte.
Les tâches `pi:*` restent séparées. Les tests du bootstrap sont dans
`tests/ci/test_dev_environment.py` : ils utilisent un faux uv et ne téléchargent
ni Python ni dépendances.

Références : [installation de uv](https://docs.astral.sh/uv/getting-started/installation/),
[interpréteurs gérés par uv](https://docs.astral.sh/uv/concepts/python-versions/),
[environnements isolés](https://docs.astral.sh/uv/pip/environments/).
