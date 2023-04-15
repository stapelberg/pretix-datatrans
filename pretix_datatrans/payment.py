import logging
from collections import OrderedDict

import requests
from requests.auth import HTTPBasicAuth
from django import forms
from django.http import HttpRequest
from django.shortcuts import redirect
from django.template.loader import get_template
from django.utils.translation import gettext as __, gettext_lazy as _

from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.base.models import Event, Order, OrderPayment, OrderRefund, Quota
from pretix.base.settings import GlobalSettingsObject
from pretix.multidomain.urlreverse import build_absolute_uri


logger = logging.getLogger('pretix.plugins.datatrans')

class Datatrans(BasePaymentProvider):
    identifier = 'datatrans'
    verbose_name = _('Datatrans')

    def __init__(self, event: Event):
        super().__init__(event)

    def payment_is_valid_session(self, request):
        return True

    def payment_form_render(self, request) -> str:
        template = get_template('pretix_datatrans/payment_form.html')
        ctx = {'request': request, 'event': self.event, 'settings': self.settings}
        return template.render(ctx)

    def checkout_confirm_render(self, request) -> str:
        template = get_template('pretix_datatrans/payment_confirm.html')
        ctx = {'request': request, 'event': self.event, 'settings': self.settings}
        return template.render(ctx)

    def execute_payment(self, request: HttpRequest, payment: OrderPayment):
        gs = GlobalSettingsObject()
        # initialize transaction by calling datatrans API
        transactions_url = 'https://api.sandbox.datatrans.com/v1/transactions'
        start_url = 'https://pay.sandbox.datatrans.com/v1/start/'
        if not gs.settings.payment_datatrans_sandbox:
            transactions_url = transactions_url.replace('.sandbox', '')
            start_url = start_url.replace('.sandbox', '')
        url_base = build_absolute_uri(request.event, 'plugins:pretix_datatrans:return',
                                      kwargs={
                                        'order': payment.order.code,
                                        })
        success_url = url_base + '?state=success'
        error_url = url_base + '?state=error'
        cancel_url = url_base + '?state=cancel'
        logger.error('success_url = %s' % str(success_url))

        payment_methods = ['TWI']
        if gs.settings.payment_datatrans_sandbox:
            payment_methods = ['VIS']

        response = requests.post(
            transactions_url,
            json={
                'currency': self.event.currency,
                'refno': payment.order.code,
                'amount': float(payment.amount) * 100,
                'paymentMethods': payment_methods,
                'redirect': {
                    'successUrl': success_url,
                    'cancelUrl': cancel_url,
                    'errorUrl': error_url,
                },
            },
            auth=HTTPBasicAuth(
                gs.settings.payment_datatrans_merchant_id,
                gs.settings.payment_datatrans_api_password))
        if not response:
            raise PaymentException(_('datatrans: Fehler %s: %s' % (
                response.status_code, response.content)))
        body = response.json()
        transactionId = body['transactionId']
        payment.info_data = {'transaction': transactionId}
        payment.save(update_fields=['info'])

        return start_url + transactionId