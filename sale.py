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

__all__ = ['Sale','SaleLine']

__metaclass__ = PoolMeta

_ZERO = Decimal('0.0')

class Sale():
    __name__ = 'sale.sale'

    all_list_price = fields.One2Many('sale.list_by_product', 'sale', 'Price List', readonly=True)

    warehouse_sale = fields.One2Many('sale.warehouse', 'sale', 'Productos por bodega', readonly=True)

    @fields.depends('lines', 'price_list', 'party')
    def on_change_price_list(self):
        
        res={}
        pool = Pool()
        PriceList = pool.get('product.price_list')
        Party = pool.get('party.party')
        Uom = pool.get('product.uom')
        Template = pool.get('product.template')
        Product = pool.get('product.product')

        if self.price_list:
            price_list = self.price_list

            for line in self.lines:
                id_template = line.product.template.id
                templates = Template.search([('id', '=', id_template)])
                for template in templates:
                    if template.listas_precios:
                        for lista in template.listas_precios:
                            if lista.lista_precio == price_list:
                                res['line.unit_price'] = lista.fijo
                                line.unit_price = res['line.unit_price']
                                res['line.listas_precios'] = lista.lista_precio.id
                                line.listas_precios = lista.lista_precio.id
                                res['line.amount'] = line.on_change_with_amount()
        return res

    @fields.depends('lines', 'currency', 'party', 'all_list_price','warehouse_sale')
    def on_change_lines(self):
        pool = Pool()
        Move = pool.get('stock.product_quantities_warehouse')
        Location = pool.get('stock.location')
        location = Location.search([('type', '=', 'warehouse')])
        Product = Pool().get('product.product')
        Line = pool.get('sale.line')
        #todos los movimientos
        Move = pool.get('stock.move')
        #movimientos de inventario del producto
        StockLine = pool.get('stock.inventory.line')
        stock = 0
        in_s = 0
        Tax = pool.get('account.tax')
        Invoice = pool.get('account.invoice')
        Configuration = pool.get('account.configuration')
        sub14 = Decimal(0.0)
        sub12 = Decimal(0.0)
        sub0= Decimal(0.0)
        total_new = Decimal(0.0)
        config = Configuration(1)
        descuento_total = Decimal(0.0)
        descuento_parcial = Decimal(0.0)

        changes = {
            'untaxed_amount': Decimal('0.0'),
            'tax_amount': Decimal('0.0'),
            'total_amount': Decimal('0.0'),
            'subtotal_12': Decimal('0.0'),
            'subtotal_14': Decimal('0.0'),
            'subtotal_0': Decimal('0.0'),
            'descuento':Decimal('0.0'),

            }
        changes['all_list_price'] = {}
        changes['warehouse_sale'] = {}
        cont = 0

        if self.warehouse_sale:
            changes['warehouse_sale']['remove'] = [x['id'] for x in self.warehouse_sale]
        if self.all_list_price:
            changes['all_list_price']['remove'] = [x['id'] for x in self.all_list_price]

        if self.lines:
            context = self.get_tax_context()
            taxes = {}
            cont = 1
            tam = 1
            for line in self.lines:
                tam += tam

            for line in self.lines:
                if line.product:
                    cont += cont
                    if line.product.listas_precios and cont ==tam:
                        for list_p in line.product.listas_precios:
                            result_list = {
                                'lista_precio': list_p.lista_precio.name,
                                'fijo': list_p.fijo,
                                'fijo_con_iva': list_p.fijo_con_iva,
                            }
                            changes['all_list_price'].setdefault('add', []).append((0, result_list))
                        for lo in location:
                            #inventario por cada uno de los productos
                            in_stock = Move.search([('product', '=', line.product), ('to_location','=', lo.storage_location)])
                            for i in in_stock :
                                in_s += i.quantity
                            #todos los movimientos que ha tenido el producto
                            move = Move.search([('product', '=', line.product), ('from_location','=', lo.storage_location)])
                            for m in move :
                                stock += m.quantity
                            s_total = in_s - stock
                            result = {
                                'product': line.product.name,
                                'warehouse': lo.name,
                                'quantity': str(int(s_total)),
                            }
                            stock = 0
                            in_s = 0
                            changes['warehouse_sale'].setdefault('add', []).append((0, result))

                if  line.taxes:
                    for t in line.taxes:
                        if str('{:.0f}'.format(t.rate*100)) == '12':
                            sub12= sub12 + (line.unit_price * Decimal(line.quantity))
                        elif str('{:.0f}'.format(t.rate*100)) == '0':
                            sub0 = sub0 + (line.unit_price * Decimal(line.quantity))
                        elif str('{:.0f}'.format(t.rate*100)) == '14':
                            sub14 = sub14 + (line.unit_price * Decimal(line.quantity))
                total_new += line.amount_w_tax

                if line.product:
                    descuento_parcial = Decimal(line.product.template.list_price - line.unit_price)
                    if descuento_parcial > 0:
                        descuento_total += descuento_parcial
                    else:
                        descuento_total = Decimal(0.00)

                changes['subtotal_14'] = sub14
                changes['subtotal_12'] = sub12
                changes['subtotal_0'] = sub0
                changes['descuento'] = descuento_total

            if self.currency:
                total_new = self.currency.round(total_new)

            def round_taxes():
                if self.currency:
                    for key, value in taxes.iteritems():
                        taxes[key] = self.currency.round(value)

            for line in self.lines:
                if getattr(line, 'type', 'line') != 'line':
                    continue
                changes['untaxed_amount'] += (getattr(line, 'amount', None)
                    or Decimal(0))
                with Transaction().set_context(context):
                    tax_list = Tax.compute(getattr(line, 'taxes', []),
                        getattr(line, 'unit_price', None) or Decimal('0.0'),
                        getattr(line, 'quantity', None) or 0.0)
                for tax in tax_list:
                    key, val = Invoice._compute_tax(tax, 'out_invoice')
                    if key not in taxes:
                        taxes[key] = val['amount']
                    else:
                        taxes[key] += val['amount']
                if config.tax_rounding == 'line':
                    round_taxes()
            if config.tax_rounding == 'document':
                round_taxes()
            changes['tax_amount'] = sum(taxes.itervalues(), Decimal('0.0'))
        if self.currency:
            changes['untaxed_amount'] = self.currency.round(
                changes['untaxed_amount'])
            changes['tax_amount'] = self.currency.round(changes['tax_amount'])
        changes['total_amount'] = (changes['untaxed_amount']
            + changes['tax_amount'])
        if self.currency:
            changes['total_amount'] = self.currency.round(
                changes['total_amount'])

        if total_new == changes['total_amount']:
            pass
        else:
            changes['total_amount'] = total_new
            changes['untaxed_amount'] = (changes['total_amount']
                - changes['tax_amount'])
        return changes

    @classmethod
    def get_amount(cls, sales, names):
        untaxed_amount = {}
        tax_amount = {}
        total_amount = {}
        sub14 = Decimal(0.0)
        sub12 = Decimal(0.0)
        sub0= Decimal(0.0)
        subtotal_14 = {}
        subtotal_12 = {}
        subtotal_0 = {}
        descuento_desglose = Decimal(0.0)
        discount = Decimal(0.0)

        if {'tax_amount', 'total_amount'} & set(names):
            compute_taxes = True
        else:
            compute_taxes = False
        # Sort cached first and re-instanciate to optimize cache management
        sales = sorted(sales, key=lambda s: s.state in cls._states_cached,
            reverse=True)
        sales = cls.browse(sales)
        for sale in sales:
            module = None
            for line in sale.lines:
                pool = Pool()

                Module = pool.get('ir.module.module')
                module = Module.search([('name', '=', 'sale_discount'), ('state', '=', 'installed')])

                if module:
                    if (line.descuento_desglose > Decimal(0.0)) | (line.discount > Decimal(0.0)):
                        descuento_desglose = line.descuento_desglose
                        discount = line.discount
                        if  line.taxes:
                            for t in line.taxes:
                                if str('{:.0f}'.format(t.rate*100)) == '12':
                                    sub12= sub12 + (line.unit_price * Decimal(line.quantity))
                                elif str('{:.0f}'.format(t.rate*100)) == '14':
                                    sub14 = sub14 + (line.unit_price * Decimal(line.quantity))
                                elif str('{:.0f}'.format(t.rate*100)) == '0':
                                    sub0 = sub0 + (line.unit_price * Decimal(line.quantity))
                    else:
                        if  line.taxes:
                            for t in line.taxes:
                                if str('{:.0f}'.format(t.rate*100)) == '12':
                                    sub12= sub12 + (line.unit_price * Decimal(line.quantity))
                                elif str('{:.0f}'.format(t.rate*100)) == '14':
                                    sub14 = sub14 + (line.unit_price * Decimal(line.quantity))
                                elif str('{:.0f}'.format(t.rate*100)) == '0':
                                    sub0 = sub0 + (line.unit_price * Decimal(line.quantity))
                else:
                    if  line.taxes:
                        for t in line.taxes:
                            if str('{:.0f}'.format(t.rate*100)) == '12':
                                sub12= sub12 + (line.amount)
                            elif str('{:.0f}'.format(t.rate*100)) == '14':
                                sub14 = sub14 + (line.amount)
                            elif str('{:.0f}'.format(t.rate*100)) == '0':
                                sub0 = sub0 + (line.amount)


            if (sale.state in cls._states_cached
                    and sale.untaxed_amount_cache is not None
                    and sale.tax_amount_cache is not None
                    and sale.total_amount_cache is not None
                    and sale.subtotal_0_cache is not None
                    and sale.subtotal_12_cache is not None
                    and sale.subtotal_14_cache is not None):
                untaxed_amount[sale.id] = sale.untaxed_amount_cache
                subtotal_0[sale.id] = sale.subtotal_0_cache
                subtotal_12[sale.id] = sale.subtotal_12_cache
                subtotal_14[sale.id] = sale.subtotal_14_cache
                if compute_taxes:
                    tax_amount[sale.id] = sale.tax_amount_cache
                    total_amount[sale.id] = sale.total_amount_cache
            else:
                if module:
                    if (descuento_desglose > Decimal(0.0)) | (discount > Decimal(0.0)):
                        untaxed_amount[sale.id] = sale.currency.round(sum(
                            ((line.amount) for line in sale.lines
                                if line.type == 'line'), _ZERO))
                    else:
                        untaxed_amount[sale.id] = sale.currency.round(sum(
                            ((line.unit_price * Decimal(line.quantity)) for line in sale.lines
                                if line.type == 'line'), _ZERO))
                else:
                    untaxed_amount[sale.id] = sale.currency.round(sum(
                        ((line.amount) for line in sale.lines
                            if line.type == 'line'), _ZERO))

                subtotal_0[sale.id] = sale.currency.round(sub0)
                subtotal_12[sale.id] = sale.currency.round(sub12)
                subtotal_14[sale.id] = sale.currency.round(sub14)
                if compute_taxes:
                    tax_amount[sale.id] = sale.get_tax_amount()
                    total_amount[sale.id] = (
                        untaxed_amount[sale.id] + tax_amount[sale.id])
        result = {
            'untaxed_amount': untaxed_amount,
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            'subtotal_0': subtotal_0,
            'subtotal_12': subtotal_12,
            'subtotal_14':subtotal_14,
            }
        for key in result.keys():
            if key not in names:
                del result[key]
        return result

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
        if 'unit_price' not in cls.unit_price_w_tax.on_change_with:
            cls.unit_price_w_tax.on_change_with.add('unit_price')
        if 'unit_price' not in cls.amount_w_tax.on_change_with:
            cls.amount_w_tax.on_change_with.add('unit_price')

        if 'type' not in cls.amount.on_change_with:
            cls.amount.on_change_with.add('type')

        if 'amount' not in cls.amount.on_change_with:
            cls.amount.on_change_with.add('amount')
        if 'amount' not in cls.unit_price_w_tax.on_change_with:
            cls.unit_price_w_tax.on_change_with.add('amount')
        if 'amount' not in cls.amount_w_tax.on_change_with:
            cls.amount_w_tax.on_change_with.add('amount')

        if 'listas_precios' not in cls.unit_price_w_tax.on_change_with:
            cls.unit_price_w_tax.on_change_with.add('listas_precios')
        if 'listas_precios' not in cls.amount_w_tax.on_change_with:
            cls.amount_w_tax.on_change_with.add('listas_precios')

    @fields.depends('unit_price', 'listas_precios', 'gross_unit_price', 'discount',
        '_parent_sale.sale_discount', 'product', 'descuento_desglose', 'type',
        'amount','_parent_sale.currency', 'quantity')
    def on_change_listas_precios(self):
        res = {}
        if self.listas_precios:
            res['unit_price'] = self.listas_precios.fijo
            self.unit_price = res['unit_price']
            res['amount'] = self.on_change_with_amount()
        return res

    @fields.depends('type', 'quantity', 'unit_price', 'unit',
        '_parent_sale.currency')
    def on_change_with_amount(self):
        if self.type == 'line':
            currency = self.sale.currency if self.sale else None
            amount = Decimal(str(self.quantity or '0.0')) * \
                (self.unit_price or Decimal('0.0'))
            if currency:
                return currency.round(amount)
            return amount
        return Decimal('0.0')

    @fields.depends('gross_unit_price', 'discount',
        '_parent_sale.sale_discount', 'unit_price', 'type', 'amount', '_parent_sale.currency')
    def on_change_unit_price(self):
        return self.update_prices()

    def update_prices(self):
        unit_price = None
        descuento = Decimal(0.0)
        gross_unit_price = gross_unit_price_wo_round = self.gross_unit_price
        sale_discount = Transaction().context.get('sale_discount')
        producto = self.product

        if producto:
            precio_costo = self.product.cost_price
        else:
            precio_costo = None
        origin = str(self)
        def in_group():
            pool = Pool()
            ModelData = pool.get('ir.model.data')
            User = pool.get('res.user')
            Group = pool.get('res.group')
            group = Group(ModelData.get_id('nodux_sale_pos_discount',
                        'group_cost_price_force_assignment'))
            transaction = Transaction()
            user_id = transaction.user
            if user_id == 0:
                user_id = transaction.context.get('user', user_id)
            if user_id == 0:
                return True
            user = User(user_id)
            return origin and group in user.groups

        if sale_discount == None:
            if self.sale and hasattr(self.sale, 'sale_discount'):
                sale_discount = self.sale.sale_discount or Decimal(0)
            else:
                sale_discount = Decimal(0)
        """
        if sale_discount:
            total = self.sale.total_amount
            value = total - (sale_discount*100)
            sale_discount = ((value * 100) / total)/100
        """
        if self.gross_unit_price is not None and (self.discount is not None
                or sale_discount is not None or self.descuento_desglose is not None):
            unit_price = self.gross_unit_price

            if self.discount and self.descuento_desglose:
                if self.quantity:
                    taxes = self.taxes
                    desglose = self.descuento_desglose
                    for t in taxes:
                        porcentaje = 1 + t.rate
                        unit_price = (desglose / porcentaje)

                    d = (unit_price/self.gross_unit_price)/100
                    dscto = 1- d
                    descuento = self.discount + d
                else:
                    descuento_inicial = 1 - (self.unit_price/self.gross_unit_price)
                    descuento = descuento_inicial + self.discount

                    desglose = self.descuento_desglose
                    taxes = self.taxes
                    if self.discount > 1:
                        e_d = str(self.discount * 100)
                        self.raise_user_error('No se puede aplicar un descuento de %s', e_d)

                    unit_price *= (1 - (descuento))

                    for t in taxes:
                        porcentaje = 1 + t.rate
                        unit = (desglose / porcentaje)

                    d = ((unit*100)/self.gross_unit_price)/100
                    dscto = 1- d


            elif self.discount:
                if self.discount > 1:
                    e_d = str(self.discount * 100)
                    self.raise_user_error('No se puede aplicar un descuento de %s', e_d)
                unit_price *= (1 - self.discount)

            elif self.descuento_desglose:
                taxes = self.taxes
                desglose = self.descuento_desglose
                if self.quantity:
                    for t in taxes:
                        porcentaje = 1 + t.rate
                        unit_price = (desglose / porcentaje)
                d = ((unit_price*100)/self.gross_unit_price)/100
                dscto = 1- d

            if self.discount and sale_discount:
                discount = (self.discount + sale_discount
                    - self.discount * sale_discount)
                if discount != 1:
                    gross_unit_price_wo_round = unit_price / (1 - discount)

            elif self.discount and self.descuento_desglose:
                discount = (self.discount + d)
                if descuento != 1:
                    gross_unit_price_wo_round = self.gross_unit_price

            elif self.discount and self.discount != 1:
                gross_unit_price_wo_round = unit_price / (1 - self.discount)
            elif sale_discount and sale_discount != 1:
                gross_unit_price_wo_round = unit_price / (1 - sale_discount)
            elif self.descuento_desglose and self.descuento_desglose != 0:
                gross_unit_price_wo_round = unit_price / (1 - dscto)

            digits = self.__class__.unit_price.digits[1]
            unit_price = unit_price
            digits = self.__class__.gross_unit_price.digits[1]
            gross_unit_price = gross_unit_price_wo_round.quantize(
                Decimal(str(10.0 ** -digits)))

        return {
            'gross_unit_price': gross_unit_price,
            'gross_unit_price_wo_round': gross_unit_price_wo_round,
            'unit_price': unit_price,
            }
