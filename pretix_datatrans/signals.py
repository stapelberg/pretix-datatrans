from collections import OrderedDict
from django import forms
from django.dispatch import receiver
from pretix.base.signals import register_global_settings, register_payment_providers


@receiver(register_payment_providers, dispatch_uid="payment_datatrans")
def register_payment_provider(sender, **kwargs):
    from .payment import Datatrans

    return Datatrans


@receiver(register_global_settings, dispatch_uid="datatrans_global_settings")
def register_global_settings(sender, **kwargs):
    return OrderedDict(
        [
            (
                "payment_datatrans_sandbox",
                forms.BooleanField(
                    label="Datatrans: Use Sandbox",
                    required=False,
                ),
            ),
            (
                "payment_datatrans_merchant_id",
                forms.CharField(
                    label="Datatrans: Merchant ID",
                    required=False,
                ),
            ),
            (
                "payment_datatrans_api_password",
                forms.CharField(
                    label="Datatrans: API password",
                    required=False,
                ),
            ),
        ]
    )
