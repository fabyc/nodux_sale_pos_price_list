# This file is part of the sale_payment module for Tryton.
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
#! -*- coding: utf8 -*-
from decimal import Decimal
from trytond.model import ModelView, fields, ModelSQL, Workflow
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Bool, Eval, Not, If, PYSONEncoder, Id, Get
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateView, StateTransition, Button, StateAction
from datetime import datetime,timedelta
from trytond.transaction import Transaction
from trytond.model import fields

__all__ = ['SaleLine']

__metaclass__ = PoolMeta

class SaleLine(ModelSQL, ModelView):
    'Sale Line'
    __name__ = 'sale.line'
    _rec_name = 'description'

    listas_precios = fields.Many2One('product.list_by_product', 'Listas de Precios', domain=[
        ('product', '=', Eval('product'))
        ])

    @classmethod
    def __setup__(cls):
        super(SaleLine, cls).__setup__()
        if 'unit_price' not in cls.amount.on_change_with:
            cls.amount.on_change_with.add('unit_price')

    @fields.depends('unit_price', 'listas_precios', 'gross_unit_price', 'discount',
        '_parent_sale.sale_discount', 'product', 'descuento_desglose')
    def on_change_listas_precios(self):
        res = {}
        if self.listas_precios:
            res['unit_price'] = self.listas_precios.fijo
            self.unit_price = res['unit_price']
            res['amount'] = self.on_change_with_amount()
        return res

    @fields.depends('gross_unit_price', 'discount',
        '_parent_sale.sale_discount')
    def on_change_unit_price(self):
        return self.update_prices()
