from django.utils.translation import gettext_lazy
from . import __version__

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_datatrans"
    verbose_name = "Datatrans"

    class PretixPluginMeta:
        name = gettext_lazy("Datatrans")
        author = "Michael Stapelberg"
        description = gettext_lazy("datatrans payment provider integration")
        visible = True
        version = __version__
        category = "PAYMENT"
        compatibility = "pretix>=2.7.0"

    def ready(self):
        from . import signals  # NOQA
