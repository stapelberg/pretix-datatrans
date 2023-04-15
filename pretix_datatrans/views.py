import hashlib
import hmac
import json
import logging
import re
import requests
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from pretix.base.models import Order, OrderPayment
from pretix.base.payment import PaymentException
from pretix.base.settings import GlobalSettingsObject
from pretix.multidomain.urlreverse import eventreverse
from requests.auth import HTTPBasicAuth

logger = logging.getLogger("pretix_datatrans")


def _redirect_to_order(event, order):
    return redirect(
        eventreverse(
            event,
            "presale:event.order",
            kwargs={"order": order.code, "secret": order.secret},
        )
        + ("?paid=yes" if order.status == Order.STATUS_PAID else "")
    )


def confirm_payment(event, order, request, transaction_id, body):
    if body["refno"] != order.code:
        raise PaymentException(_("transaction id does not match order"))

    status = body["status"]
    if status != "authorized" and status != "settled" and status != "transmitted":
        return _("unexpected payment status: %s") % status

    payment = order.payments.filter(
        info__contains=transaction_id,
        provider__exact="datatrans",
    ).last()
    payment.confirm()

    return ""  # no error


@csrf_exempt
@require_POST
def webhook(request, *args, **kwargs):
    # See https://api-reference.datatrans.ch/#section/Webhook

    if "datatrans-signature" not in request.headers:
        raise PermissionDenied()

    # TODO: add a test for this webhook

    # TODO: whitelist IP ranges? hard-coding would require updating the plugin
    # whenever IPs change :-/. maybe easier in nginx frontend?
    # https://docs.datatrans.ch/docs/additional-security#ip-whitelisting

    # Verify the HMAC signature of this webhook request:
    # https://api-reference.datatrans.ch/#section/Webhook/Webhook-signing
    # https://docs.datatrans.ch/docs/additional-security#section-signing-your-webhooks
    payload = request.body.decode("utf-8")
    # sigheader is e.g.:
    # t=1681477968899,s0=f3fe103b3319848c7e71560739c8da3f64e5007a4ef4a04b1cd135e7d64e29c6
    sigheader = request.headers["datatrans-signature"]
    sigheader_match = re.search("t=([0-9]*),s0=(.*)", sigheader)
    if not sigheader_match:
        raise PermissionDenied()

    timestamp = sigheader_match.group(1)
    s0 = sigheader_match.group(2)

    gs = GlobalSettingsObject()
    signing_key = gs.settings.payment_datatrans_hmac_signing_key
    if not signing_key:
        logging.error(
            (
                "global setting payment_datatrans_hmac_signing_key not "
                "set, cannot verify datatrans webhook signature"
            )
        )
    else:
        key = bytes.fromhex(signing_key)
        msg = bytes(str(timestamp) + payload, "utf-8")
        sign = hmac.new(key, msg, hashlib.sha256)
        want = sign.hexdigest()
        if want != s0:
            logger.error(
                (
                    "datatrans webhook signature verification failed: "
                    "got %s, want %s" % (s0, want)
                )
            )
            raise PermissionDenied()

    status_json = json.loads(payload)

    transaction_id = status_json["transactionId"]
    logger.info("datatrans webhook for transaction id %s" % transaction_id)
    logger.debug("status_json: %s" % status_json)
    payment = (
        OrderPayment.objects.filter(
            order__event=request.event,
            info__contains=transaction_id,
            provider__exact="datatrans",
        )
        .select_related("order")
        .last()
    )
    error_message = confirm_payment(
        request.event, payment.order, request, transaction_id, status_json
    )
    if error_message != "":
        raise Exception(error_message)

    return HttpResponse("okay")


@method_decorator(xframe_options_exempt, "dispatch")
class ReturnView(View):
    def dispatch(self, request, *args, **kwargs):
        try:
            self.order = request.event.orders.get(code=kwargs["order"])
        except Order.DoesNotExist:
            raise Http404()
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def pprov(self):
        return self.request.event.get_payment_providers()[self.order.payment_provider]

    def get(self, request, *args, **kwargs):
        if self.order.status == Order.STATUS_PAID:
            return _redirect_to_order(self.request.event, self.order)

        gs = GlobalSettingsObject()
        # Get transaction status from datatrans.
        transactions_url = "https://api.sandbox.datatrans.com/v1/transactions/"
        if not gs.settings.payment_datatrans_sandbox:
            transactions_url = transactions_url.replace(".sandbox", "")

        transaction_id = request.GET.get("datatransTrxId")
        datatrans_url = transactions_url + transaction_id
        response = requests.get(
            datatrans_url,
            json={},
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
        error_message = confirm_payment(
            self.request.event, self.order, request, transaction_id, body
        )
        if error_message != "":
            messages.error(request, error_message)
        # TODO: update self.order.status so that it is PAID,
        # otherwise the ?paid=yes parameter is missing in the redirect
        return _redirect_to_order(self.request.event, self.order)
