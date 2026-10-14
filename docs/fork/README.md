# Atelier sur la base OctoPrint 2.0.0rc6

Cette branche `feat/atelier-2.0-rc6` part directement du tag upstream
`2.0.0rc6`, commit `75fef2506e6f4ce62b4b4e6eb6810ea67833622a`.
Elle ne fusionne pas la lignée 2.1.dev dans la release candidate : seuls les
ajouts du fork sont portés depuis `3c6f4eb` (interface Atelier, français,
uv/Taskfile, préconfiguration, outils SD/SSH, CI et tests associés).
La version s'affiche `2.0.0rc6+atelier.g<commit>`, sans se présenter comme une
version stable officielle. La base et la source du portage sont tracées dans
`configs/atelier-base.json`.

La comparaison de l'ancienne base `feat/translate-fr` au tag rc6 trouvait
93 commits propres à cette ancienne lignée et 21 commits rc6 non intégrés.
Le nouveau commit a rc6 pour parent, sans importer ces développements 2.1.
La branche `feat/atelier-mobile-tablet` reste intacte hors correctif de build SSH,
et permet le retour au prototype précédent ; aucune réécriture d'historique.

## Essai sur Mac

Pour éviter de partager une configuration déjà migrée par 2.1.dev, utiliser un
nouveau clone et un nouveau répertoire de configuration pour cette recette :

```sh
git clone --branch feat/atelier-2.0-rc6 https://github.com/didlawowo/OctoPrint.git OctoPrint-rc6
cd OctoPrint-rc6
task init-dev
task configure BASEDIR="$HOME/.octoprint-atelier-rc6"
task dev PORT=5001 BASEDIR="$HOME/.octoprint-atelier-rc6"
```

Ouvrir `http://127.0.0.1:5001/?l10n=fr`. Les autres guides sous `docs/fork/`
restent utiles pour les fonctions, mais leurs références à l'ancienne branche
2.1.dev doivent être remplacées par cette branche pour cette recette.
L'authentification reste native ; l'AutoLogin de préconfiguration est limité
à localhost sauf ajout explicite du sous-réseau privé.

## Image SD depuis le Mac

```sh
task pi:prepare
task pi:build
# Si seuls des résultats de génération salissent le checkout et que l'on veut HEAD :
# task pi:build BUILD_COMMITTED=1
task pi:flash
```

Le build est délégué à `ssh nvidia` depuis macOS et récupère le commit exact de
cette branche. Les résultats reviennent sur le Mac et sont vérifiés. Le flash
reste local dans Raspberry Pi Imager. Voir [Build SSH](remote-build.md) pour
les prérequis Docker/Linux et la reprise du téléchargement.
Ne pas réutiliser la SD de l'installation actuelle : conserver un rollback.

## Validation et limites

Les quatre tests de version couvrent Git, les archives avec un nom de branche
contenant des chiffres et le tag officiel. Les douze tests du build SSH ne font
aucun accès réseau ou disque physique. Le workflow ARC de la branche relance
les tests Python, Node, le build des paquets et la recette Playwright ; un
portage proposé n'est pas une preuve que tous ces contrôles ont réussi.
L'image complète CustoPiZer et le démarrage matériel du Pi restent à tester.

La matrice upstream Build de rc6 est conservée sans exécution automatique dans
`.github/upstream-workflows/2.0.0rc6-build.yml`. Les mises à jour ultérieures de
la base doivent être explicites, testées et reportées dans le fichier de provenance.
