from django.conf import settings
from django.core import serializers

from . import get_serializer_name


def get_plugin_data(plugin, only_meta=False):
    from .utils import get_plugin_fields
    if only_meta:
        custom_data = None
    else:
        plugin_fields = get_plugin_fields(plugin.plugin_type)
        _plugin_data = serializers.serialize(get_serializer_name(), (plugin,), fields=plugin_fields)[0]
        custom_data = _plugin_data["fields"]

    plugin_data = {
        "pk": plugin.pk,
        "creation_date": plugin.creation_date,
        "position": plugin.position,
        "plugin_type": plugin.plugin_type,
        "parent_id": plugin.parent_id,
        "data": custom_data,
    }

    gpd = getattr(settings, "DJANGOCMS_TRANSFER_PROCESS_EXPORT_PLUGIN_DATA", None)
    if gpd:
        module, function = gpd.rsplit(".", 1)
        return getattr(__import__(module, fromlist=[""]), function)(plugin, plugin_data)
    else:
        return plugin_data
