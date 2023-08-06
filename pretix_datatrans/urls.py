from django.urls import include, re_path
from pretix.multidomain import event_url

from .views import ReturnView, webhook

event_patterns = [
    re_path(
        r"^datatrans/",
        include(
            [
                event_url(r"^webhook/$", webhook, name="webhook", require_live=False),
                re_path(
                    r"^return/(?P<order>[^/]+)/$", ReturnView.as_view(), name="return"
                ),
            ]
        ),
    ),
]
