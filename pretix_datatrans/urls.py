from django.conf.urls import include, url

from .views import ReturnView

event_patterns = [
    url(
        r"^datatrans/",
        include(
            [
                url(r"^return/(?P<order>[^/]+)/$", ReturnView.as_view(), name="return"),
            ]
        ),
    ),
]
