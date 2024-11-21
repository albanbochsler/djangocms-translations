from cms.utils.plugins import get_bound_plugins

from . import helpers


def get_placeholder_export_data(placeholder, language):
    get_data = helpers.get_plugin_data
    plugins = placeholder.get_plugins(language)
    # The following results in two queries;
    # First all the root plugins are fetched, then all child plugins.
    # This is needed to account for plugin path corruptions.

    return [get_data(plugin) for plugin in get_bound_plugins(list(plugins))]


def get_page_export_data(cms_page, language):
    data = []
    placeholders = cms_page.rescan_placeholders(language).values()

    for placeholder in list(placeholders):
        plugins = get_placeholder_export_data(placeholder, language)
        data.append({"placeholder": placeholder.slot, "plugins": plugins})
    return data
