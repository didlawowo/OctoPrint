"""Mobile/tablet presentation layer for this fork; no new printer API."""

import octoprint.plugin


class AtelierPlugin(octoprint.plugin.AssetPlugin, octoprint.plugin.TemplatePlugin):
    def get_assets(self):
        return {"js": ["js/atelier.js"], "css": ["css/atelier.css"]}

    def get_template_configs(self):
        return [
            {"type": "tab", "name": "Accueil", "custom_bindings": True},
            {"type": "generic", "template": "atelier_navigation.jinja2"},
        ]


__plugin_name__ = "Atelier — interface mobile et tablette"
__plugin_description__ = "Tableau de bord tactile du fork, avec accès à l'interface classique."
__plugin_license__ = "AGPLv3"
__plugin_pythoncompat__ = ">=3.10,<4"
__plugin_implementation__ = AtelierPlugin()
