import logging
import requests
from django.http import HttpRequest
from django.template.loader import get_template
from django.utils.translation import gettext_lazy as _
from pretix.base.models import Event, OrderPayment, OrderRefund
from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.base.settings import GlobalSettingsObject
from pretix.multidomain.urlreverse import build_absolute_uri
from requests.auth import HTTPBasicAuth

logger = logging.getLogger("pretix.plugins.datatrans")


class Datatrans(BasePaymentProvider):
    identifier = "datatrans"
    verbose_name = _("Datatrans")

    def __init__(self, event: Event):
        super().__init__(event)

    def payment_is_valid_session(self, request):
        return True

    def payment_form_render(self, request) -> str:
        template = get_template("pretix_datatrans/payment_form.html")
        ctx = {"request": request, "event": self.event, "settings": self.settings}
        return template.render(ctx)

    def checkout_confirm_render(self, request) -> str:
        template = get_template("pretix_datatrans/payment_confirm.html")
        ctx = {"request": request, "event": self.event, "settings": self.settings}
        return template.render(ctx)

    def payment_refund_supported(self, payment: OrderPayment):
        return True

    def payment_partial_refund_supported(self, payment: OrderPayment):
        return True

    def execute_refund(self, refund: OrderRefund):
        payment_info = refund.payment.info_data
        if not payment_info:
            raise PaymentException(_("datatrans: no payment info found"))

        gs = GlobalSettingsObject()
        # initialize transaction by calling datatrans API
        refund_url = (
            "https://api.sandbox.datatrans.com/v1/transactions/"
            + payment_info["transaction"]
            + "/credit"
        )
        if not gs.settings.payment_datatrans_sandbox:
            refund_url = refund_url.replace(".sandbox", "")

        logger.info("refund_url = %s" % refund_url)

        # https://api-reference.datatrans.ch/#tag/v1transactions/operation/credit
        response = requests.post(
            refund_url,
            json={
                "currency": self.event.currency,
                "refno": refund.full_id,
                "amount": float(refund.amount) * 100,
            },
            auth=HTTPBasicAuth(
                gs.settings.payment_datatrans_merchant_id,
                gs.settings.payment_datatrans_api_password,
            ),
        )
        if not response:
            raise PaymentException(
                _("datatrans: Fehler %s: %s" % (response.status_code,
                                                response.content))
            )
        refund.done()
        body = response.json()
        logger.info("datatrans credit body = %s" % body)

    def execute_payment(self, request: HttpRequest, payment: OrderPayment):
        gs = GlobalSettingsObject()
        # initialize transaction by calling datatrans API
        transactions_url = "https://api.sandbox.datatrans.com/v1/transactions"
        start_url = "https://pay.sandbox.datatrans.com/v1/start/"
        if not gs.settings.payment_datatrans_sandbox:
            transactions_url = transactions_url.replace(".sandbox", "")
            start_url = start_url.replace(".sandbox", "")
        url_base = build_absolute_uri(
            request.event,
            "plugins:pretix_datatrans:return",
            kwargs={
                "order": payment.order.code,
            },
        )
        success_url = url_base + "?state=success"
        error_url = url_base + "?state=error"
        cancel_url = url_base + "?state=cancel"
        logger.info("datatrans success_url = %s" % success_url)

        webhook_url = build_absolute_uri(
            request.event,
            "plugins:pretix_datatrans:webhook",
        )
        logger.info("datatrans webhook_url = %s" % webhook_url)

        payment_methods = ["TWI"]
        if gs.settings.payment_datatrans_sandbox:
            payment_methods = ["VIS"]

        # https://api-reference.datatrans.ch/#tag/v1transactions/operation/init
        response = requests.post(
            transactions_url,
            json={
                "currency": self.event.currency,
                "refno": payment.full_id,
                "amount": float(payment.amount) * 100,
                "paymentMethods": payment_methods,
                "redirect": {
                    "successUrl": success_url,
                    "cancelUrl": cancel_url,
                    "errorUrl": error_url,
                },
                "webhook": {
                    "url": webhook_url,
                },
            },
            auth=HTTPBasicAuth(
                gs.settings.payment_datatrans_merchant_id,
                gs.settings.payment_datatrans_api_password,
            ),
        )
        if not response:
            raise PaymentException(
                _("datatrans: Fehler %s: %s" % (response.status_code, response.content))
            )
        body = response.json()
        transaction_id = body["transactionId"]
        payment.info_data = {"transaction": transaction_id}
        payment.save(update_fields=["info"])

        return start_url + transaction_id
