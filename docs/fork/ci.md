# CI du fork OctoPrint

Le workflow `Atelier` utilise les actions partagées de `didlawowo/workflow-ci`
**v1.18.3**, épinglées au commit
`b4688812f0262a7cd385f2ae729dca9b2f0e1e85`.

## Runner local

La sélection utilise uniquement la variable de dépôt `RUNNER`, avec le défaut
`arc-runner-octoprint`. Il n'y a pas de repli vers un runner GitHub hébergé.

Le runner est déclaré dans le dépôt `didlawowo/continuous-delivery`, fichier
`infrastructure-crds/rke2-infra/ci/arc-runner-octoprint.yaml`. Ce pool ARC dédié
au fork est limité à **0–2 runners Linux amd64 éphémères**, sans Docker-in-Docker,
sans montage de disque physique et sans jeton Kubernetes dans le pod de travail.
Les téléchargements Python et npm passent par Proxpi et Verdaccio configurés par
l'infrastructure. Une panne des proxies doit être corrigée côté infrastructure,
pas masquée par un repli vers les registres publics.

**L'ajout du workflow ne provisionne pas le runner.** Fusionner d'abord la PR
correspondante de `continuous-delivery`, attendre la synchronisation ArgoCD et
l'enregistrement ARC. Un job peut rester en attente tant que cette étape n'est
pas terminée. Si `RUNNER` existe déjà dans les variables du fork, vérifier qu'elle
cible bien ce pool ; sans variable, le défaut suffit.

## Déclenchements et confiance

Le fork est public et le runner est sur le réseau local. Le workflow exécute le
code sur les événements `push` des branches du dépôt et `workflow_dispatch`,
pas sur `pull_request` ou `pull_request_target`. Une PR issue d'un dépôt externe
ne déclenche donc pas l'exécution de son code sur le réseau local. Son contenu
doit être revu avant d'être repris sur une branche du fork.

Les checks des pushes sont attachés au commit de la branche de PR. Le lancement
manuel depuis l'interface Actions nécessite également que le workflow soit
présent sur la branche par défaut. Les tokens de travail restent en lecture
seule et les checkouts ne conservent pas les credentials Git.

## Contrôles exécutés

- Contrat pre-commit partagé, sans désactiver les hooks existants du fork.
- Suite Python sous 3.11 et doctests selon `pytest.ini` (`src` et `tests`, hors
  marqueur `http_api`), rapports JUnit et couverture via l'action partagée.
  Le contrat CI est couvert par `tests/ci/test_local_workflow.py`.
  L'extra OctoPrint `develop` est explicitement installé. La couverture est
  publiée comme preuve, sans nouveau seuil arbitraire ni compte Codecov requis.
- `task pi:test` : protections SD sur doubles de test, tests Node du dashboard et
  syntaxe Bash, sans accès matériel.
- Compilation des traductions et construction des distributions Python wheel
  et sdist. Ce sont des paquets Python, **pas une image SD**.
- Recette Chromium Atelier aux largeurs prévues dans les tests, y compris le
  retour à l'interface classique. Le serveur utilise uniquement une copie
  temporaire des fixtures CI et écoute sur la boucle locale.

Les paquets, rapports Python, captures, traces, vidéos et rapports navigateur
sont conservés sept jours. Les preuves navigateur sont sauvegardées même si un
test échoue. Les assertions existantes restent bloquantes : ajouter ce workflow
ne signifie pas que les tests sont déjà verts.

La matrice upstream `Build` est conservée, sans modification, dans
`.github/upstream-workflows/build.yml`, hors du répertoire actif des workflows.
Elle ne s'exécute plus en parallèle sur les runners GitHub hébergés. La CI locale
ne prétend pas remplacer sa validation exhaustive sur Python 3.10–3.14, les
variantes d'installation et les suites API amont. Ces tests restent disponibles
dans le dépôt. L'ancien helper ponctuel `atelier-prepare.yml` est également
archivé : ses transformations ne sont plus réexécutées automatiquement.

## Test sur Raspberry Pi

La préparation de l'image et le flash restent des actions **manuelles locales** :

```sh
task pi:prepare
task pi:test
task pi:build
task pi:flash
```

Le build de l'image nécessite Linux x86_64, Docker et un checkout propre, selon
[le guide Atelier](atelier.md). Le flash efface la carte choisie ; utiliser une
seconde SD pour la recette. La CI ne lance ni `pi:build`, ni `pi:flash`, ni une
commande de l'imprimante.
