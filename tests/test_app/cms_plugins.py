from cms.plugin_base import CMSPluginBase
from cms.plugin_pool import plugin_pool

from .models import Link


@plugin_pool.register_plugin
class LinkPlugin(CMSPluginBase):
    model = Link
    render_plugin = False
    text_enabled = True
    allow_children = False
