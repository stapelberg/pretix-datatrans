import hashlib
import json
import logging
from decimal import Decimal

import requests
from requests.auth import HTTPBasicAuth

from django.contrib import messages
from django.core import signing
from django.db.models import Sum
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt

from pretix.base.models import Order, Quota, OrderPayment, OrderRefund
from pretix.base.payment import PaymentException
from pretix.multidomain.urlreverse import eventreverse
from pretix.base.settings import GlobalSettingsObject

logger = logging.getLogger('pretix_datatrans')


@method_decorator(xframe_options_exempt, 'dispatch')
class ReturnView(View):
    def dispatch(self, request, *args, **kwargs):
        try:
            self.order = request.event.orders.get(code=kwargs['order'])
        except Order.DoesNotExist:
            raise Http404()
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def pprov(self):
        return self.request.event.get_payment_providers()[self.order.payment_provider]

    def get(self, request, *args, **kwargs):
        if self.order.status == Order.STATUS_PAID:
            return self._redirect_to_order()

        transactionId = request.GET.get('datatransTrxId')
        gs = GlobalSettingsObject()
        # initialize transaction by calling datatrans API
        transactions_url = 'https://api.sandbox.datatrans.com/v1/transactions/'
        if not gs.settings.payment_datatrans_sandbox:
            transactions_url = transactions_url.replace('.sandbox', '')

        datatrans_url = transactions_url + transactionId
        response = requests.get(
            datatrans_url,
            json={},
            auth=HTTPBasicAuth(
                gs.settings.payment_datatrans_merchant_id,
                gs.settings.payment_datatrans_api_password))
        if not response:
            raise PaymentException(_('datatrans: Fehler %s: %s' % (
                response.status_code, response.content)))
        body = response.json()
        if body['refno'] != self.order.code:
            raise PaymentException(_('transaction id does not match order'))
        status = body['status']
        if status != 'authorized' and status != 'settled' and status != 'transmitted':
            messages.error(self.request, _('unexpected payment status: %s') % status)
            return self._redirect_to_order()

        payment = self.order.payments.filter(
            info__icontains=transactionId,
            provider__startswith='datatrans',
        ).last()
        payment.confirm()
        
        return self._redirect_to_order()

    def _redirect_to_order(self):
        return redirect(eventreverse(self.request.event, 'presale:event.order', kwargs={
            'order': self.order.code,
            'secret': self.order.secret
        }) + ('?paid=yes' if self.order.status == Order.STATUS_PAID else ''))