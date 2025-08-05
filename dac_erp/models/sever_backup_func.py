# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import logging

from collections import defaultdict
from datetime import timedelta
from itertools import groupby

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import (
    AccessError,
    RedirectWarning,
    UserError,
    ValidationError,
)
from odoo.fields import Command
from odoo.http import request
from odoo.osv import expression
from odoo.tools import (
    create_index,
    float_is_zero,
    format_amount,
    format_date,
    is_html_empty,
    SQL,
)
from odoo.tools.mail import html_keep_url

from odoo.addons.payment import utils as payment_utils

import requests # Cần cài đặt thư viện requests: pip install requests
from datetime import datetime
from odoo.exceptions import UserError
import os
import json

from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT


_logger = logging.getLogger(__name__)

INVOICE_STATUS = [
    ('upselling', 'Upselling Opportunity'),
    ('invoiced', 'Fully Invoiced'),
    ('to invoice', 'To Invoice'),
    ('deposit', 'Chưa Thanh Toán'),
    ('no', 'Nothing to Invoice')
]

SALE_ORDER_STATE = [
    ('draft', "Quotation"),
    ('sale', "Đơn hàng"),
    ('sale-staked', "Đã cọc"),
    ('production', "Sản xuất"),
    ('del-cons', "Giao hàng - Thi công"),
    ('debt', "Công nợ"),
    ('done', "Đã thanh toán"),
    ('cancel', "Cancelled"),
]


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['portal.mixin', 'product.catalog.mixin', 'mail.thread', 'mail.activity.mixin', 'utm.mixin']
    _description = "Sales Order"
    _order = 'date_order desc, id desc'
    _check_company_auto = True

    _sql_constraints = [
        ('date_order_conditional_required',
         "CHECK((state = 'sale' AND date_order IS NOT NULL) OR state != 'sale')",
         "A confirmed sales order requires a confirmation date."),
    ]

    @property
    def _rec_names_search(self):
        if self._context.get('sale_show_partner_name'):
            return ['name', 'partner_id.name',  'pancake_order_id']
        return ['name' ,  'pancake_order_id']

    #=== FIELDS ===#

    name = fields.Char(
        string="Order Reference",
        required=True, copy=False, readonly=False,
        index='trigram',
        default=lambda self: _('New'))

    company_id = fields.Many2one(
        comodel_name='res.company',
        required=True, index=True,
        default=lambda self: self.env.company)
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string="Customer",
        required=True, change_default=True, index=True,
        tracking=1,
        check_company=True)
    state = fields.Selection(
        selection=SALE_ORDER_STATE,
        string="Status",
        readonly=True, copy=False, index=True,
        tracking=3,
        default='draft')
    locked = fields.Boolean(
        help="Locked orders cannot be modified.",
        default=False,
        copy=False,
        tracking=True)
    has_archived_products = fields.Boolean(compute="_compute_has_archived_products")

    client_order_ref = fields.Char(string="Customer Reference", copy=False)
    create_date = fields.Datetime(  # Override of default create_date field from ORM
        string="Creation Date", index=True, readonly=True)
    commitment_date = fields.Datetime(
        string="Delivery Date", copy=False,
        help="This is the delivery date promised to the customer. "
             "If set, the delivery order will be scheduled based on "
             "this date rather than product lead times.")
    date_order = fields.Datetime(
        string="Order Date",
        required=True, copy=False,
        help="Creation date of draft/sent orders,\nConfirmation date of confirmed orders.",
        default=fields.Datetime.now)
    origin = fields.Char(
        string="Source Document",
        help="Reference of the document that generated this sales order request")
    reference = fields.Char(
        string="Payment Ref.",
        help="The payment communication of this sale order.",
        copy=False)

    require_signature = fields.Boolean(
        string="Online signature",
        compute='_compute_require_signature',
        store=True, readonly=False, precompute=True,
        help="Request a online signature from the customer to confirm the order.")
    require_payment = fields.Boolean(
        string="Online payment",
        compute='_compute_require_payment',
        store=True, readonly=False, precompute=True,
        help="Request a online payment from the customer to confirm the order.")
    prepayment_percent = fields.Float(
        string="Prepayment percentage",
        compute='_compute_prepayment_percent',
        store=True, readonly=False, precompute=True,
        help="The percentage of the amount needed that must be paid by the customer to confirm the order.")

    signature = fields.Image(
        string="Signature",
        copy=False, attachment=True, max_width=1024, max_height=1024)
    signed_by = fields.Char(
        string="Signed By", copy=False)
    signed_on = fields.Datetime(
        string="Signed On", copy=False)

    validity_date = fields.Date(
        string="Expiration",
        help="Validity of the order, after that you will not able to sign & pay the quotation.",
        compute='_compute_validity_date',
        store=True, readonly=False, copy=False, precompute=True)
    journal_id = fields.Many2one(
        'account.journal', string="Invoicing Journal",
        compute="_compute_journal_id", store=True, readonly=False, precompute=True,
        domain=[('type', '=', 'sale')], check_company=True,
        help="If set, the SO will invoice in this journal; "
             "otherwise the sales journal with the lowest sequence is used.")

    # Partner-based computes
    note = fields.Html(
        string="Terms and conditions",
        compute='_compute_note',
        store=True, readonly=False, precompute=True)

    partner_invoice_id = fields.Many2one(
        comodel_name='res.partner',
        string="Invoice Address",
        compute='_compute_partner_invoice_id',
        store=True, readonly=False, required=True, precompute=True,
        check_company=True,
        index='btree_not_null')
    partner_shipping_id = fields.Many2one(
        comodel_name='res.partner',
        string="Delivery Address",
        compute='_compute_partner_shipping_id',
        store=True, readonly=False, required=True, precompute=True,
        check_company=True,
        index='btree_not_null')

    fiscal_position_id = fields.Many2one(
        comodel_name='account.fiscal.position',
        string="Fiscal Position",
        compute='_compute_fiscal_position_id',
        store=True, readonly=False, precompute=True, check_company=True,
        help="Fiscal positions are used to adapt taxes and accounts for particular customers or sales orders/invoices."
            "The default value comes from the customer.",
    )
    payment_term_id = fields.Many2one(
        comodel_name='account.payment.term',
        string="Payment Terms",
        compute='_compute_payment_term_id',
        store=True, readonly=False, precompute=True, check_company=True,  # Unrequired company
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    pricelist_id = fields.Many2one(
        comodel_name='product.pricelist',
        string="Pricelist",
        compute='_compute_pricelist_id',
        store=True, readonly=False, precompute=True, check_company=True,  # Unrequired company
        tracking=1,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="If you change the pricelist, only newly added lines will be affected.")
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        compute='_compute_currency_id',
        store=True,
        precompute=True,
        ondelete='restrict'
    )
    currency_rate = fields.Float(
        string="Currency Rate",
        compute='_compute_currency_rate',
        digits=0,
        store=True, precompute=True)
    user_id = fields.Many2one(
        comodel_name='res.users',
        string="Salesperson",
        compute='_compute_user_id',
        store=True, readonly=False, precompute=True, index=True,
        tracking=2,
        domain=lambda self: "[('groups_id', '=', {}), ('share', '=', False), ('company_ids', '=', company_id)]".format(
            self.env.ref("sales_team.group_sale_salesman").id
        ))
    creator_id = fields.Many2one(
        comodel_name='res.users',
        string="CreaterPerson",
        # compute='_compute_user_id',
        store=True, readonly=False, precompute=True, index=True,
        tracking=2,
        domain=lambda self: "[('groups_id', '=', {}), ('share', '=', False), ('company_ids', '=', company_id)]".format(
            self.env.ref("sales_team.group_sale_salesman").id
        ))
    team_id = fields.Many2one(
        comodel_name='crm.team',
        string="Sales Team",
        compute='_compute_team_id',
        store=True, readonly=False, precompute=True, ondelete="set null",
        change_default=True, check_company=True,  # Unrequired company
        tracking=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")

    # Lines and line based computes
    order_line = fields.One2many(
        comodel_name='sale.order.line',
        inverse_name='order_id',
        string="Order Lines",
        copy=True, auto_join=True)

    amount_untaxed = fields.Monetary(string="Untaxed Amount", store=True, compute='_compute_amounts', tracking=5)
    amount_tax = fields.Monetary(string="Taxes", store=True, compute='_compute_amounts')
    amount_total = fields.Monetary(string="Total", store=True, compute='_compute_amounts', tracking=4)
    amount_to_invoice = fields.Monetary(string="Un-invoiced Balance", compute='_compute_amount_to_invoice')
    amount_invoiced = fields.Monetary(string="Already invoiced", compute='_compute_amount_invoiced')

    invoice_count = fields.Integer(string="Invoice Count", compute='_get_invoiced')
    invoice_ids = fields.Many2many(
        comodel_name='account.move',
        string="Invoices",
        compute='_get_invoiced',
        search='_search_invoice_ids',
        copy=False)
    invoice_status = fields.Selection(
        selection=INVOICE_STATUS,
        string="Invoice Status",
        compute='_compute_invoice_status',
        store=True)

    # Payment fields
    transaction_ids = fields.Many2many(
        comodel_name='payment.transaction',
        relation='sale_order_transaction_rel', column1='sale_order_id', column2='transaction_id',
        string="Transactions",
        copy=False, readonly=True)
    authorized_transaction_ids = fields.Many2many(
        comodel_name='payment.transaction',
        string="Authorized Transactions",
        compute='_compute_authorized_transaction_ids',
        copy=False,
        compute_sudo=True)
    amount_paid = fields.Float(
        string="Payment Transactions Amount",
        help="Sum of transactions made in through the online payment form that are in the state"
             " 'done' or 'authorized' and linked to this order.",
        compute='_compute_amount_paid',
        compute_sudo=True,
    )

    # UTMs - enforcing the fact that we want to 'set null' when relation is unlinked
    campaign_id = fields.Many2one(ondelete='set null')
    medium_id = fields.Many2one(ondelete='set null')
    source_id = fields.Many2one(ondelete='set null')

    # Followup ?
    tag_ids = fields.Many2many(
        comodel_name='crm.tag',
        relation='sale_order_tag_rel', column1='order_id', column2='tag_id',
        string="Tags")

    # Remaining non stored computed fields (hide/make fields readonly, ...)
    amount_undiscounted = fields.Float(
        string="Amount Before Discount",
        compute='_compute_amount_undiscounted', digits=0)
    country_code = fields.Char(related='company_id.account_fiscal_country_id.code', string="Country code")
    company_price_include = fields.Selection(related='company_id.account_price_include')
    duplicated_order_ids = fields.Many2many(comodel_name='sale.order', compute='_compute_duplicated_order_ids')
    expected_date = fields.Datetime(
        string="Expected Date",
        compute='_compute_expected_date', store=False,  # Note: can not be stored since depends on today()
        help="Delivery date you can promise to the customer, computed from the minimum lead time of the order lines.")
    is_expired = fields.Boolean(string="Is Expired", compute='_compute_is_expired')
    partner_credit_warning = fields.Text(
        compute='_compute_partner_credit_warning')
    tax_calculation_rounding_method = fields.Selection(
        related='company_id.tax_calculation_rounding_method',
        depends=['company_id'])
    tax_country_id = fields.Many2one(
        comodel_name='res.country',
        compute='_compute_tax_country_id',
        # Avoid access error on fiscal position when reading a sale order with company != user.company_ids
        compute_sudo=True)  # used to filter available taxes depending on the fiscal country and position
    tax_totals = fields.Binary(compute='_compute_tax_totals', exportable=False)
    terms_type = fields.Selection(related='company_id.terms_type')
    type_name = fields.Char(string="Type Name", compute='_compute_type_name')

    # Remaining ux fields (not computed, not stored)

    show_update_fpos = fields.Boolean(
        string="Has Fiscal Position Changed", store=False)  # True if the fiscal position was changed
    has_active_pricelist = fields.Boolean(
        compute='_compute_has_active_pricelist')
    show_update_pricelist = fields.Boolean(
        string="Has Pricelist Changed", store=False)  # True if the pricelist was changed

    def init(self):
        create_index(self._cr, 'sale_order_date_order_id_idx', 'sale_order', ["date_order desc", "id desc"])

    # --- Pancake Integration Fields ---
    pancake_order_id = fields.Char(string='Pancake Order ID', index=True, copy=False, readonly=True)
    pancake_system_id = fields.Char(string='Pancake System ID', copy=False, readonly=True)

    pancake_customer_name = fields.Char(string='Tên KH (Pancake)', copy=False, readonly=True)
    pancake_customer_phone = fields.Char(string='SĐT KH (Pancake)', copy=False, readonly=True)
    pancake_customer_fb_id = fields.Char(string='Facebook ID KH (Pancake)', copy=False, readonly=True)

    pancake_shipping_full_name = fields.Char(string='Tên người nhận (GH - Pancake)', copy=False, readonly=True)
    pancake_shipping_phone = fields.Char(string='SĐT người nhận (GH - Pancake)', copy=False, readonly=True)
    pancake_shipping_address = fields.Text(string='Địa chỉ GH (Pancake)', copy=False, readonly=True)
    pancake_shipping_province = fields.Char(string='Tỉnh/Thành GH (Pancake)', copy=False, readonly=True)
    pancake_shipping_district = fields.Char(string='Quận/Huyện GH (Pancake)', copy=False, readonly=True)
    pancake_shipping_commune = fields.Char(string='Phường/Xã GH (Pancake)', copy=False, readonly=True)

    pancake_status_name = fields.Char(string='Trạng thái (Pancake Name)', copy=False, readonly=True)
    pancake_status_key = fields.Char(string='Trạng thái (Pancake Key)', copy=False, readonly=True)
    create_date_ = fields.Datetime(string='Ngày tạo (Pancake)', copy=False, readonly=True)
    pancake_updated_at = fields.Datetime(string='Ngày cập nhật (Pancake)', copy=False, readonly=True)
    pancake_order_source_name = fields.Char(string='Nguồn đơn (Pancake)', copy=False, readonly=True)
    pancake_page_name = fields.Char(string='Trang bán hàng (Pancake)', copy=False, readonly=True)
    pancake_order_link = fields.Char(string='Link đơn hàng (Pancake)', copy=False, readonly=True)

    pancake_items_length = fields.Integer(string='Số loại SP (Pancake)', copy=False, readonly=True)
    pancake_total_quantity = fields.Float(string='Tổng SL SP (Pancake)', copy=False, readonly=True)
    pancake_total_price = fields.Float(string='Tổng tiền hàng (Pancake)', copy=False, readonly=True)
    pancake_total_discount_amount = fields.Float(string='Tổng giảm giá (Pancake)', copy=False, readonly=True)
    pancake_shipping_fee = fields.Float(string='Phí vận chuyển (Pancake)', copy=False, readonly=True)
    pancake_surcharge = fields.Float(string='Phụ phí (Pancake)', copy=False, readonly=True)
    pancake_money_to_collect = fields.Float(string='Tiền cần thu (Pancake)', copy=False, readonly=True)
    pancake_prepaid = fields.Float(string='Đã trả trước (Pancake)', copy=False, readonly=True)
    pancake_order_currency_code = fields.Char(string='Mã Tiền tệ (Pancake)', copy=False, default='VND', readonly=True)

    pancake_note = fields.Text(string='Ghi chú ĐH (Pancake)', copy=False, readonly=True)
    pancake_note_print = fields.Text(string='Ghi chú in (Pancake)', copy=False, readonly=True)
    pancake_customer_note = fields.Text(string='Ghi chú KH (Pancake)', copy=False, readonly=True)
    
    pancake_creator_name = fields.Char(string='Người tạo ĐH (Pancake)', copy=False, readonly=True)
    pancake_assigning_seller_name = fields.Char(string='NV bán hàng (Pancake)', copy=False, readonly=True)

    last_sync_date = fields.Datetime(string='Ngày đồng bộ cuối', readonly=True, copy=False)
    pancake_raw_data = fields.Text(string="Dữ liệu thô JSON (Pancake)", readonly=True, copy=False)
    
    # Thêm trường boolean mới
    x_is_readonly = fields.Boolean(
        string="Is Form Readonly",
        compute='_compute_x_is_readonly',
        store=False  # Không cần lưu vào database
    )

    @api.depends('state')
    def _compute_x_is_readonly(self):
        """
        Trường này sẽ là True nếu state nằm trong danh sách các trạng thái cuối,
        khiến cho form trở thành chỉ đọc.
        """
        # Danh sách các trạng thái bạn muốn form bị khóa
        readonly_states = ['sale-staked', 'production', 'del-cons', 'debt', 'done']
        for order in self:
            if order.state in readonly_states:
                order.x_is_readonly = True
            else:
                order.x_is_readonly = False

    
    # --- Pancake Functions ---

    def action_open_pancake_link(self):
        self.ensure_one()
        if not self.pancake_order_link:
            raise UserError("Không có link đơn hàng Pancake.")

        return {
            'type': 'ir.actions.act_url',
            'url': self.pancake_order_link,
            'target': 'new',  # <-- Mở trong tab mới
        } 
    

    #=== COMPUTE METHODS ===#

    @api.depends('partner_id')
    @api.depends_context('sale_show_partner_name')
    def _compute_display_name(self):
        if not self._context.get('sale_show_partner_name'):
            return super()._compute_display_name()
        for order in self:
            name = order.name
            if order.partner_id.name:
                name = f'{name} - {order.partner_id.name}'
            order.display_name = name

    @api.depends('order_line.product_id')
    def _compute_has_archived_products(self):
        for order in self:
            order.has_archived_products = any(
                not product.active for product in order.order_line.product_id
            )

    @api.depends('company_id')
    def _compute_require_signature(self):
        for order in self:
            order.require_signature = order.company_id.portal_confirmation_sign

    @api.depends('company_id')
    def _compute_require_payment(self):
        for order in self:
            order.require_payment = order.company_id.portal_confirmation_pay

    @api.depends('require_payment')
    def _compute_prepayment_percent(self):
        for order in self:
            order.prepayment_percent = order.company_id.prepayment_percent

    @api.depends('company_id')
    def _compute_validity_date(self):
        today = fields.Date.context_today(self)
        for order in self:
            days = order.company_id.quotation_validity_days
            if days > 0:
                order.validity_date = today + timedelta(days)
            else:
                order.validity_date = False

    def _compute_journal_id(self):
        self.journal_id = False

    @api.depends('partner_id')
    def _compute_note(self):
        use_invoice_terms = self.env['ir.config_parameter'].sudo().get_param('account.use_invoice_terms')
        if not use_invoice_terms:
            return
        for order in self:
            order = order.with_company(order.company_id)
            if order.terms_type == 'html' and self.env.company.invoice_terms_html:
                baseurl = html_keep_url(order._get_note_url() + '/terms')
                context = {'lang': order.partner_id.lang or self.env.user.lang}
                order.note = _('Terms & Conditions: %s', baseurl)
                del context
            elif not is_html_empty(self.env.company.invoice_terms):
                if order.partner_id.lang:
                    order = order.with_context(lang=order.partner_id.lang)
                order.note = order.env.company.invoice_terms

    @api.model
    def _get_note_url(self):
        return self.env.company.get_base_url()

    @api.depends('partner_id')
    def _compute_partner_invoice_id(self):
        for order in self:
            order.partner_invoice_id = order.partner_id.address_get(['invoice'])['invoice'] if order.partner_id else False

    @api.depends('partner_id')
    def _compute_partner_shipping_id(self):
        for order in self:
            order.partner_shipping_id = order.partner_id.address_get(['delivery'])['delivery'] if order.partner_id else False

    @api.depends('partner_shipping_id', 'partner_id', 'company_id')
    def _compute_fiscal_position_id(self):
        """
        Trigger the change of fiscal position when the shipping address is modified.
        """
        cache = {}
        for order in self:
            if not order.partner_id:
                order.fiscal_position_id = False
                continue
            fpos_id_before = order.fiscal_position_id.id
            key = (order.company_id.id, order.partner_id.id, order.partner_shipping_id.id)
            if key not in cache:
                cache[key] = self.env['account.fiscal.position'].with_company(
                    order.company_id
                )._get_fiscal_position(order.partner_id, order.partner_shipping_id).id
            if fpos_id_before != cache[key] and order.order_line:
                order.show_update_fpos = True
            order.fiscal_position_id = cache[key]

    @api.depends('partner_id')
    def _compute_payment_term_id(self):
        for order in self:
            order = order.with_company(order.company_id)
            order.payment_term_id = order.partner_id.property_payment_term_id

    @api.depends('partner_id', 'company_id')
    def _compute_pricelist_id(self):
        for order in self:
            if order.state != 'draft':
                continue
            if not order.partner_id:
                order.pricelist_id = False
                continue
            order = order.with_company(order.company_id)
            order.pricelist_id = order.partner_id.property_product_pricelist

    @api.depends('pricelist_id', 'company_id')
    def _compute_currency_id(self):
        for order in self:
            order.currency_id = order.pricelist_id.currency_id or order.company_id.currency_id

    @api.depends('currency_id', 'date_order', 'company_id')
    def _compute_currency_rate(self):
        for order in self:
            order.currency_rate = self.env['res.currency']._get_conversion_rate(
                from_currency=order.company_id.currency_id,
                to_currency=order.currency_id,
                company=order.company_id,
                date=(order.date_order or fields.Datetime.now()).date(),
            )

    @api.depends('company_id')
    def _compute_has_active_pricelist(self):
        for order in self:
            order.has_active_pricelist = bool(self.env['product.pricelist'].search(
                [('company_id', 'in', (False, order.company_id.id)), ('active', '=', True)],
                limit=1,
            ))

    @api.depends('partner_id')
    def _compute_user_id(self):
        for order in self:
            if order.partner_id and not (order._origin.id and order.user_id):
                # Recompute the salesman on partner change
                #   * if partner is set (is required anyway, so it will be set sooner or later)
                #   * if the order is not saved or has no salesman already
                order.user_id = (
                    order.partner_id.user_id
                    or order.partner_id.commercial_partner_id.user_id
                    or (self.env.user.has_group('sales_team.group_sale_salesman') and self.env.user)
                )

    @api.depends('partner_id', 'user_id')
    def _compute_team_id(self):
        cached_teams = {}
        for order in self:
            default_team_id = self.env.context.get('default_team_id', False) or order.team_id.id
            user_id = order.user_id.id
            company_id = order.company_id.id
            key = (default_team_id, user_id, company_id)
            if key not in cached_teams:
                cached_teams[key] = self.env['crm.team'].with_context(
                    default_team_id=default_team_id,
                )._get_default_team_id(
                    user_id=user_id,
                    domain=self.env['crm.team']._check_company_domain(company_id),
                )
            order.team_id = cached_teams[key]

    @api.depends('order_line.price_subtotal', 'currency_id', 'company_id', 'payment_term_id')
    def _compute_amounts(self):
        AccountTax = self.env['account.tax']
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]
            base_lines += order._add_base_lines_for_early_payment_discount()
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
            )
            order.amount_untaxed = tax_totals['base_amount_currency']
            order.amount_tax = tax_totals['tax_amount_currency']
            order.amount_total = tax_totals['total_amount_currency']

    def _add_base_lines_for_early_payment_discount(self):
        """
        When applying a payment term with an early payment discount, and when said payment term computes the tax on the
        'mixed' setting, the tax computation is always based on the discounted amount untaxed.
        Creates the necessary line for this behavior to be displayed.
        :returns: array containing the necessary lines or empty array if the payment term isn't epd mixed
        """
        self.ensure_one()
        epd_lines = []
        if (
            self.payment_term_id.early_discount
            and self.payment_term_id.early_pay_discount_computation == 'mixed'
            and self.payment_term_id.discount_percentage
        ):
            percentage = self.payment_term_id.discount_percentage
            currency = self.currency_id or self.company_id.currency_id
            for line in self.order_line.filtered(lambda x: not x.display_type):
                line_amount_after_discount = (line.price_subtotal / 100) * percentage
                epd_lines.append(self.env['account.tax']._prepare_base_line_for_taxes_computation(
                    record=self,
                    price_unit=-line_amount_after_discount,
                    quantity=1.0,
                    currency_id=currency,
                    sign=1,
                    special_type='early_payment',
                    tax_ids=line.tax_id,
                ))
                epd_lines.append(self.env['account.tax']._prepare_base_line_for_taxes_computation(
                    record=self,
                    price_unit=line_amount_after_discount,
                    quantity=1.0,
                    currency_id=currency,
                    sign=1,
                    special_type='early_payment',
                ))
        return epd_lines

    @api.depends('order_line.invoice_lines')
    def _get_invoiced(self):
        # The invoice_ids are obtained thanks to the invoice lines of the SO
        # lines, and we also search for possible refunds created directly from
        # existing invoices. This is necessary since such a refund is not
        # directly linked to the SO.
        for order in self:
            invoices = order.order_line.invoice_lines.move_id.filtered(lambda r: r.move_type in ('out_invoice', 'out_refund'))
            order.invoice_ids = invoices
            order.invoice_count = len(invoices)

    def _search_invoice_ids(self, operator, value):
        if operator == 'in' and value:
            self.env.cr.execute("""
                SELECT array_agg(so.id)
                    FROM sale_order so
                    JOIN sale_order_line sol ON sol.order_id = so.id
                    JOIN sale_order_line_invoice_rel soli_rel ON soli_rel.order_line_id = sol.id
                    JOIN account_move_line aml ON aml.id = soli_rel.invoice_line_id
                    JOIN account_move am ON am.id = aml.move_id
                WHERE
                    am.move_type in ('out_invoice', 'out_refund') AND
                    am.id = ANY(%s)
            """, (list(value),))
            so_ids = self.env.cr.fetchone()[0] or []
            return [('id', 'in', so_ids)]
        elif operator == '=' and not value:
            # special case for [('invoice_ids', '=', False)], i.e. "Invoices is not set"
            #
            # We cannot just search [('order_line.invoice_lines', '=', False)]
            # because it returns orders with uninvoiced lines, which is not
            # same "Invoices is not set" (some lines may have invoices and some
            # doesn't)
            #
            # A solution is making inverted search first ("orders with invoiced
            # lines") and then invert results ("get all other orders")
            #
            # Domain below returns subset of ('order_line.invoice_lines', '!=', False)
            order_ids = self._search([
                ('order_line.invoice_lines.move_id.move_type', 'in', ('out_invoice', 'out_refund'))
            ])
            return [('id', 'not in', order_ids)]
        return [
            ('order_line.invoice_lines.move_id.move_type', 'in', ('out_invoice', 'out_refund')),
            ('order_line.invoice_lines.move_id', operator, value),
        ]

    @api.depends('state', 'order_line.invoice_status')
    def _compute_invoice_status(self):
        """
        Compute the invoice status of a SO. Possible statuses:
        - no: if the SO is not in status 'sale' or 'done', we consider that there is nothing to
          invoice. This is also the default value if the conditions of no other status is met.
        - to invoice: if any SO line is 'to invoice', the whole SO is 'to invoice'
        - invoiced: if all SO lines are invoiced, the SO is invoiced.
        - upselling: if all SO lines are invoiced or upselling, the status is upselling.
        """
        confirmed_orders = self.filtered(lambda so: so.state == 'sale')
        (self - confirmed_orders).invoice_status = 'no'
        if not confirmed_orders:
            return
        lines_domain = [('is_downpayment', '=', False), ('display_type', '=', False)]
        line_invoice_status_all = [
            (order.id, invoice_status)
            for order, invoice_status in self.env['sale.order.line']._read_group(
                lines_domain + [('order_id', 'in', confirmed_orders.ids)],
                ['order_id', 'invoice_status']
            )
        ]
        for order in confirmed_orders:
            line_invoice_status = [d[1] for d in line_invoice_status_all if d[0] == order.id]
            if order.state not in ('sale', 'done', 'sale-staked', 'production', 'del-cons', 'debt'):
                order.invoice_status = 'no'
            elif any(invoice_status == 'to invoice' for invoice_status in line_invoice_status):
                if any(invoice_status == 'no' for invoice_status in line_invoice_status):
                    # If only discount/delivery/promotion lines can be invoiced, the SO should not
                    # be invoiceable.
                    invoiceable_domain = lines_domain + [('invoice_status', '=', 'to invoice')]
                    invoiceable_lines = order.order_line.filtered_domain(invoiceable_domain)
                    special_lines = invoiceable_lines.filtered(
                        lambda sol: not sol._can_be_invoiced_alone()
                    )
                    if invoiceable_lines == special_lines:
                        order.invoice_status = 'no'
                    else:
                        order.invoice_status = 'to invoice'
                else:
                    order.invoice_status = 'to invoice'
            elif line_invoice_status and all(invoice_status == 'invoiced' for invoice_status in line_invoice_status):
                order.invoice_status = 'invoiced'
                if (not order.order_line.check_all_invoices_paid()):
                    order.invoice_status = 'deposit'  # If all invoices are paid, then the status is 'invoiced', otherwise 'deposit'
            elif line_invoice_status and all(invoice_status in ('invoiced', 'upselling') for invoice_status in line_invoice_status):
                order.invoice_status = 'upselling'
            else:
                order.invoice_status = 'no'

    @api.depends('transaction_ids')
    def _compute_authorized_transaction_ids(self):
        for trans in self:
            trans.authorized_transaction_ids = trans.transaction_ids.filtered(lambda t: t.state == 'authorized')

    @api.depends('transaction_ids')
    def _compute_amount_paid(self):
        """ Sum of the amount paid through all transactions for this SO. """
        for order in self:
            order.amount_paid = sum(
                tx.amount for tx in order.transaction_ids if tx.state in ('authorized', 'done')
            )

    def _compute_amount_undiscounted(self):
        for order in self:
            total = 0.0
            for line in order.order_line:
                total += (line.price_subtotal * 100)/(100-line.discount) if line.discount != 100 else (line.price_unit * line.product_uom_qty)
            order.amount_undiscounted = total

    @api.depends('client_order_ref', 'date_order', 'origin', 'partner_id')
    def _compute_duplicated_order_ids(self):
        order_to_duplicate_orders = self._fetch_duplicate_orders()
        for order in self:
            order.duplicated_order_ids = [Command.set(order_to_duplicate_orders.get(order.id, []))]

    def _fetch_duplicate_orders(self):
        """ Fectch duplicated orders.

        :return: Dictionary mapping order to it's related duplicated orders.
        :rtype: dict
        """
        orders = self.filtered(lambda order: order.id and order.client_order_ref)
        if not orders:
            return {}

        used_fields = (
            'company_id',
            'partner_id',
            'client_order_ref',
            'origin',
            'date_order',
            'state',
        )
        self.env['sale.order'].flush_model(used_fields)

        result = self.env.execute_query(SQL("""
            SELECT
                sale_order.id AS order_id,
                array_agg(duplicate_order.id) AS duplicate_ids
              FROM sale_order
              JOIN sale_order AS duplicate_order
                ON sale_order.company_id = duplicate_order.company_id
                 AND sale_order.id != duplicate_order.id
                 AND duplicate_order.state != 'cancel'
                 AND sale_order.partner_id = duplicate_order.partner_id
                 AND sale_order.date_order = duplicate_order.date_order
                 AND sale_order.client_order_ref = duplicate_order.client_order_ref
                 AND (
                    sale_order.origin = duplicate_order.origin
                    OR (sale_order.origin IS NULL AND duplicate_order.origin IS NULL)
                )
             WHERE sale_order.id IN %(orders)s
             GROUP BY sale_order.id
            """,
            orders=tuple(orders.ids),
        ))
        return {
            order_id: set(duplicate_ids)
            for order_id, duplicate_ids in result
        }

    @api.depends('order_line.customer_lead', 'date_order', 'state')
    def _compute_expected_date(self):
        """ For service and consumable, we only take the min dates. This method is extended in sale_stock to
            take the picking_policy of SO into account.
        """
        self.mapped("order_line")  # Prefetch indication
        for order in self:
            if order.state == 'cancel':
                order.expected_date = False
                continue
            dates_list = order.order_line.filtered(
                lambda line: not line.display_type and not line._is_delivery()
            ).mapped(lambda line: line and line._expected_date())
            if dates_list:
                order.expected_date = order._select_expected_date(dates_list)
            else:
                order.expected_date = False

    def _select_expected_date(self, expected_dates):
        self.ensure_one()
        return min(expected_dates)

    def _compute_is_expired(self):
        today = fields.Date.today()
        for order in self:
            order.is_expired = (
                order.state in ('draft', 'sent')
                and order.validity_date
                and order.validity_date < today
            )

    @api.depends('company_id', 'fiscal_position_id')
    def _compute_tax_country_id(self):
        for record in self:
            if record.fiscal_position_id.foreign_vat:
                record.tax_country_id = record.fiscal_position_id.country_id
            else:
                record.tax_country_id = record.company_id.account_fiscal_country_id

    @api.depends('order_line.amount_to_invoice')
    def _compute_amount_to_invoice(self):
        for order in self:
            order.amount_to_invoice = sum(order.order_line.mapped('amount_to_invoice'))

    @api.depends('order_line.amount_invoiced')
    def _compute_amount_invoiced(self):
        for order in self:
            order.amount_invoiced = sum(order.order_line.mapped('amount_invoiced'))

    @api.depends('company_id', 'partner_id', 'amount_total')
    def _compute_partner_credit_warning(self):
        for order in self:
            order.with_company(order.company_id)
            order.partner_credit_warning = ''
            show_warning = order.state in ('draft', 'sent') and \
                           order.company_id.account_use_credit_limit
            if show_warning:
                order.partner_credit_warning = self.env['account.move']._build_credit_warning_message(
                    order.sudo(),  # ensure access to `credit` & `credit_limit` fields
                    current_amount=(order.amount_total / order.currency_rate),
                )

    @api.depends_context('lang')
    @api.depends('order_line.price_subtotal', 'currency_id', 'company_id', 'payment_term_id')
    def _compute_tax_totals(self):
        AccountTax = self.env['account.tax']
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]
            base_lines += order._add_base_lines_for_early_payment_discount()
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            order.tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
            )

    @api.depends('state')
    def _compute_type_name(self):
        for record in self:
            if record.state in ('draft', 'sent', 'cancel'):
                record.type_name = _("Quotation")
            else:
                record.type_name = _("Sales Order")

    # portal.mixin override
    def _compute_access_url(self):
        super()._compute_access_url()
        for order in self:
            order.access_url = f'/my/orders/{order.id}'

    #=== CONSTRAINT METHODS ===#

    @api.constrains('company_id', 'order_line')
    def _check_order_line_company_id(self):
        for order in self:
            invalid_companies = order.order_line.product_id.company_id.filtered(
                lambda c: order.company_id not in c._accessible_branches()
            )
            if invalid_companies:
                bad_products = order.order_line.product_id.filtered(
                    lambda p: p.company_id and p.company_id in invalid_companies
                )
                raise ValidationError(_(
                    "Your quotation contains products from company %(product_company)s whereas your quotation belongs to company %(quote_company)s. \n Please change the company of your quotation or remove the products from other companies (%(bad_products)s).",
                    product_company=', '.join(invalid_companies.sudo().mapped('display_name')),
                    quote_company=order.company_id.display_name,
                    bad_products=', '.join(bad_products.mapped('display_name')),
                ))

    @api.constrains('prepayment_percent')
    def _check_prepayment_percent(self):
        for order in self:
            if order.require_payment and not (0 < order.prepayment_percent <= 1.0):
                raise ValidationError(_("Prepayment percentage must be a valid percentage."))

    #=== ONCHANGE METHODS ===#

    def onchange(self, values, field_names, fields_spec):
        self_with_context = self
        if not field_names: # Some warnings should not be displayed for the first onchange
            self_with_context = self.with_context(sale_onchange_first_call=True)
        return super(SaleOrder, self_with_context).onchange(values, field_names, fields_spec)

    @api.onchange('commitment_date', 'expected_date')
    def _onchange_commitment_date(self):
        """ Warn if the commitment dates is sooner than the expected date """
        if self.commitment_date and self.expected_date and self.commitment_date < self.expected_date:
            return {
                'warning': {
                    'title': _('Requested date is too soon.'),
                    'message': _("The delivery date is sooner than the expected date."
                                 " You may be unable to honor the delivery date.")
                }
            }

    @api.onchange('company_id')
    def _onchange_company_id_warning(self):
        self.show_update_pricelist = True
        if self.env.context.get('sale_onchange_first_call'):
            return
        if self.order_line and self.state == 'draft':
            return {
                'warning': {
                    'title': _("Warning for the change of your quotation's company"),
                    'message': _("Changing the company of an existing quotation might need some "
                                 "manual adjustments in the details of the lines. You might "
                                 "consider updating the prices."),
                }
            }

    @api.onchange('company_id')
    def _onchange_company_id(self):
        for order in self:
            # This can't be caught by a python constraint as it is only triggered at save
            # and a compute methodd needs this data to be set correctly before saving
            if not order.company_id:
                raise ValidationError(_("The company is required, please select one before making any other changes to the sale order."))

    @api.onchange('fiscal_position_id')
    def _onchange_fpos_id_show_update_fpos(self):
        if self.order_line and (
            not self.fiscal_position_id
            or (self.fiscal_position_id and self._origin.fiscal_position_id != self.fiscal_position_id)
        ):
            self.show_update_fpos = True

    @api.onchange('partner_id')
    def _onchange_partner_id_warning(self):
        if not self.partner_id:
            return

        partner = self.partner_id

        # If partner has no warning, check its company
        if partner.sale_warn == 'no-message' and partner.parent_id:
            partner = partner.parent_id

        if partner.sale_warn and partner.sale_warn != 'no-message':
            # Block if partner only has warning but parent company is blocked
            if partner.sale_warn != 'block' and partner.parent_id and partner.parent_id.sale_warn == 'block':
                partner = partner.parent_id

            if partner.sale_warn == 'block':
                self.partner_id = False

            return {
                'warning': {
                    'title': _("Warning for %s", partner.name),
                    'message': partner.sale_warn_msg,
                }
            }

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id_show_update_prices(self):
        self.show_update_pricelist = bool(self.order_line)

    @api.onchange('prepayment_percent')
    def _onchange_prepayment_percent(self):
        if not self.prepayment_percent:
            self.require_payment = False

    @api.onchange('order_line')
    def _onchange_order_line(self):
        for index, line in enumerate(self.order_line):
            if line.product_type == 'combo' and line.selected_combo_items:
                linked_lines = line._get_linked_lines()
                selected_combo_items = json.loads(line.selected_combo_items)
                if (
                    selected_combo_items
                    and len(selected_combo_items) != len(line.product_template_id.combo_ids)
                ):
                    raise ValidationError(_(
                        "The number of selected combo items must match the number of available"
                        " combo choices."
                    ))

                # Delete any existing combo item lines.
                delete_commands = [Command.delete(linked_line.id) for linked_line in linked_lines]
                # Create a new combo item line for each selected combo item.
                create_commands = [Command.create({
                    'product_id': combo_item['product_id'],
                    'product_uom_qty': line.product_uom_qty,
                    'combo_item_id': combo_item['combo_item_id'],
                    'product_no_variant_attribute_value_ids': [
                        Command.set(combo_item['no_variant_attribute_value_ids'])
                    ],
                    'product_custom_attribute_value_ids': [Command.clear()] + [
                        Command.create(attribute_value)
                        for attribute_value in combo_item['product_custom_attribute_values']
                    ],
                    # Combo item lines should come directly after their combo product line.
                    'sequence': line.sequence + item_index + 1,
                    # If the linked line exists in DB, populate linked_line_id, otherwise populate
                    # linked_virtual_id.
                    'linked_line_id': line.id if line._origin else False,
                    'linked_virtual_id': line.virtual_id if not line._origin else False,
                }) for item_index, combo_item in enumerate(selected_combo_items)]
                # Shift any lines coming after the combo product line so that the combo item lines
                # come first.
                update_commands = [Command.update(
                    order_line.id,
                    {'sequence': line.sequence + len(selected_combo_items) + line_index - index},
                ) for line_index, order_line in enumerate(self.order_line) if line_index > index]

                # Clear `selected_combo_items` to avoid applying the same changes multiple times.
                line.selected_combo_items = False
                self.order_line = delete_commands + create_commands + update_commands

    #=== CRUD METHODS ===#

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _("New")) == _("New"):
                seq_date = fields.Datetime.context_timestamp(
                    self, fields.Datetime.to_datetime(vals['date_order'])
                ) if 'date_order' in vals else None
                vals['name'] = self.env['ir.sequence'].with_company(vals.get('company_id')).next_by_code(
                    'sale.order', sequence_date=seq_date) or _("New")

        return super().create(vals_list)

    def _get_copiable_order_lines(self):
        """Returns the order lines that can be copied to a new order."""
        return self.order_line.filtered(lambda l: not l.is_downpayment)

    def copy_data(self, default=None):
        default = dict(default or {})
        default_has_no_order_line = 'order_line' not in default
        default.setdefault('order_line', [])
        vals_list = super().copy_data(default=default)
        if default_has_no_order_line:
            for order, vals in zip(self, vals_list):
                vals['order_line'] = [
                    Command.create(line_vals)
                    for line_vals in order._get_copiable_order_lines().copy_data()
                ]
        return vals_list

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft_or_cancel(self):
        for order in self:
            if order.state not in ('draft', 'cancel'):
                raise UserError(_(
                    "You can not delete a sent quotation or a confirmed sales order."
                    " You must first cancel it."))

    def write(self, vals):
        if 'pricelist_id' in vals and any(so.state == 'sale' for so in self):
            raise UserError(_("You cannot change the pricelist of a confirmed order !"))
        res = super().write(vals)
        if vals.get('partner_id'):
            self.filtered(lambda so: so.state in ('sent', 'sale')).message_subscribe(
                partner_ids=[vals['partner_id']],
            )
        return res

    #=== ACTION METHODS ===#

    def action_open_discount_wizard(self):
        self.ensure_one()
        return {
            'name': _("Discount"),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.discount',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_draft(self):
        orders = self.filtered(lambda s: s.state in ['cancel', 'sale'])
        return orders.write({
            'state': 'draft',
            'signature': False,
            'signed_by': False,
            'signed_on': False,
        })

    def action_quotation_send(self):
        """ Opens a wizard to compose an email, with relevant mail template loaded by default """
        self.filtered(lambda so: so.state in ('draft', 'sent')).order_line._validate_analytic_distribution()
        lang = self.env.context.get('lang')

        ctx = {
            'default_model': 'sale.order',
            'default_res_ids': self.ids,
            'default_composition_mode': 'comment',
            'default_email_layout_xmlid': 'mail.mail_notification_layout_with_responsible_signature',
            'email_notification_allow_footer': True,
            'proforma': self.env.context.get('proforma', False),
        }

        if len(self) > 1:
            ctx['default_composition_mode'] = 'mass_mail'
        else:
            ctx.update({
                'force_email': True,
                'model_description': self.with_context(lang=lang).type_name,
            })
            if not self.env.context.get('hide_default_template'):
                mail_template = self._find_mail_template()
                if mail_template:
                    ctx.update({
                        'default_template_id': mail_template.id,
                        'mark_so_as_sent': True,
                    })
                if mail_template and mail_template.lang:
                    lang = mail_template._render_lang(self.ids)[self.id]
            else:
                for order in self:
                    order._portal_ensure_token()

        action = {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(False, 'form')],
            'view_id': False,
            'target': 'new',
            'context': ctx,
        }
        if (
            self.env.context.get('check_document_layout')
            and not self.env.context.get('discard_logo_check')
            and self.env.is_admin()
            and not self.env.company.external_report_layout_id
        ):
            layout_action = self.env['ir.actions.report']._action_configure_external_report_layout(
                action,
            )
            # Need to remove this context for windows action
            action.pop('close_on_report_download', None)
            layout_action['context']['dialog_size'] = 'extra-large'
            return layout_action
        return action

    def _find_mail_template(self):
        """ Get the appropriate mail template for the current sales order based on its state.

        If the SO is confirmed, we return the mail template for the sale confirmation.
        Otherwise, we return the quotation email template.

        :return: The correct mail template based on the current status
        :rtype: record of `mail.template` or `None` if not found
        """
        self.ensure_one()
        if self.env.context.get('proforma') or self.state not in ('sale', 'done', 'sale-staked', 'production', 'del-cons', 'debt'):
            return self.env.ref('sale.email_template_edi_sale', raise_if_not_found=False)
        else:
            return self._get_confirmation_template()

    def _get_confirmation_template(self):
        """ Get the mail template sent on SO confirmation (or for confirmed SO's).

        :return: `mail.template` record or None if default template wasn't found
        """
        self.ensure_one()
        default_confirmation_template_id = self.env['ir.config_parameter'].sudo().get_param(
            'sale.default_confirmation_template'
        )
        default_confirmation_template = default_confirmation_template_id \
            and self.env['mail.template'].browse(int(default_confirmation_template_id)).exists()
        if default_confirmation_template:
            return default_confirmation_template
        else:
            return self.env.ref('sale.mail_template_sale_confirmation', raise_if_not_found=False)

    def action_quotation_sent(self):
        """ Mark the given draft quotation(s) as sent.

        :raise: UserError if any given SO is not in draft state.
        """
        if any(order.state != 'draft' for order in self):
            raise UserError(_("Only draft orders can be marked as sent directly."))

        for order in self:
            order.message_subscribe(partner_ids=order.partner_id.ids)

        self.write({'state': 'sent'})

    def action_confirm(self):
        """ Confirm the given quotation(s) and set their confirmation date.

        If the corresponding setting is enabled, also locks the Sale Order.

        :return: True
        :rtype: bool
        :raise: UserError if trying to confirm cancelled SO's
        """
        for order in self:
            error_msg = order._confirmation_error_message()
            if error_msg:
                raise UserError(error_msg)

        self.order_line._validate_analytic_distribution()

        for order in self:
            if order.partner_id in order.message_partner_ids:
                continue
            order.message_subscribe([order.partner_id.id])

        self.write(self._prepare_confirmation_values())

        # Context key 'default_name' is sometimes propagated up to here.
        # We don't need it and it creates issues in the creation of linked records.
        context = self._context.copy()
        context.pop('default_name', None)

        self.with_context(context)._action_confirm()
        user = self[:1].create_uid
        if user and user.sudo().has_group('sale.group_auto_done_setting'):
            # Public user can confirm SO, so we check the group on any record creator.
            self.action_lock()

        if self.env.context.get('send_email'):
            self._send_order_confirmation_mail()

        return True

    def _should_be_locked(self):
        self.ensure_one()
        # Public user can confirm SO, so we check the group on any record creator.
        user = self[:1].create_uid
        return user and user.sudo().has_group('sale.group_auto_done_setting')

    def _confirmation_error_message(self):
        """ Return whether order can be confirmed or not if not then returm error message. """
        self.ensure_one()
        if self.state not in {'draft', 'sent'}:
            return _("Some orders are not in a state requiring confirmation.")
        if any(
            not line.display_type
            and not line.is_downpayment
            and not line.product_id
            for line in self.order_line
        ):
            return _("A line on these orders missing a product, you cannot confirm it.")

        return False

    def _prepare_confirmation_values(self):
        """ Prepare the sales order confirmation values.

        Note: self can contain multiple records.

        :return: Sales Order confirmation values
        :rtype: dict
        """
        return {
            'state': 'sale',
            'date_order': fields.Datetime.now()
        }

    def _action_confirm(self):
        """ Implementation of additional mechanism of Sales Order confirmation.
            This method should be extended when the confirmation should generated
            other documents. In this method, the SO are in 'sale' state (not yet 'done').
        """
        pass

    def _send_order_confirmation_mail(self):
        """ Send a mail to the SO customer to inform them that their order has been confirmed.

        :return: None
        """
        for order in self:
            mail_template = order._get_confirmation_template()
            order._send_order_notification_mail(mail_template)

    def _send_payment_succeeded_for_order_mail(self):
        """ Send a mail to the SO customer to inform them that a payment has been initiated.

        :return: None
        """
        mail_template = self.env.ref(
            'sale.mail_template_sale_payment_executed', raise_if_not_found=False
        )
        for order in self:
            order._send_order_notification_mail(mail_template)

    def _send_order_notification_mail(self, mail_template):
        """ Send a mail to the customer

        Note: self.ensure_one()

        :param mail.template mail_template: the template used to generate the mail
        :return: None
        """
        self.ensure_one()

        if not mail_template:
            return

        if self.env.su:
            # sending mail in sudo was meant for it being sent from superuser
            self = self.with_user(SUPERUSER_ID)

        self.with_context(force_send=True).message_post_with_source(
            mail_template,
            email_layout_xmlid='mail.mail_notification_layout_with_responsible_signature',
            subtype_xmlid='mail.mt_comment',
        )

    def action_lock(self):
        self.locked = True

    def action_unlock(self):
        self.locked = False

    def action_cancel(self):
        """ Cancel SO after showing the cancel wizard when needed. (cfr :meth:`_show_cancel_wizard`)

        For post-cancel operations, please only override :meth:`_action_cancel`.

        note: self.ensure_one() if the wizard is shown.
        """
        if any(order.locked for order in self):
            raise UserError(_("You cannot cancel a locked order. Please unlock it first."))
        cancel_warning = self._show_cancel_wizard()
        if cancel_warning:
            self.ensure_one()
            template_id = self.env['ir.model.data']._xmlid_to_res_id(
                'sale.mail_template_sale_cancellation', raise_if_not_found=False
            )
            lang = self.env.context.get('lang')
            template = self.env['mail.template'].browse(template_id)
            if template.lang:
                lang = template._render_lang(self.ids)[self.id]
            ctx = {
                'default_template_id': template_id,
                'default_order_id': self.id,
                'mark_so_as_canceled': True,
                'default_email_layout_xmlid': "mail.mail_notification_layout_with_responsible_signature",
                'model_description': self.with_context(lang=lang).type_name,
            }
            return {
                'name': _('Cancel %s', self.type_name),
                'view_mode': 'form',
                'res_model': 'sale.order.cancel',
                'view_id': self.env.ref('sale.sale_order_cancel_view_form').id,
                'type': 'ir.actions.act_window',
                'context': ctx,
                'target': 'new'
            }
        else:
            return self._action_cancel()

    def _action_cancel(self):
        inv = self.invoice_ids.filtered(lambda inv: inv.state == 'draft')
        inv.button_cancel()
        return self.write({'state': 'cancel'})

    def _show_cancel_wizard(self):
        """ Decide whether the sale.order.cancel wizard should be shown to cancel specified orders.

        :return: True if there is any non-draft order in the given orders
        :rtype: bool
        """
        if self.env.context.get('disable_cancel_warning'):
            return False
        return any(so.state != 'draft' for so in self)

    def action_preview_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'target': 'self',
            'url': self.get_portal_url(),
        }

    def action_update_taxes(self):
        self.ensure_one()

        self._recompute_taxes()

        if self.partner_id:
            self.message_post(body=_("Product taxes have been recomputed according to fiscal position %s.",
                self.fiscal_position_id._get_html_link() if self.fiscal_position_id else "")
            )

    def _recompute_taxes(self):
        lines_to_recompute = self.order_line.filtered(lambda line: not line.display_type)
        lines_to_recompute._compute_tax_id()
        self.show_update_fpos = False

    def action_update_prices(self):
        self.ensure_one()

        self._recompute_prices()

        if self.pricelist_id:
            message = _("Product prices have been recomputed according to pricelist %s.",
                self.pricelist_id._get_html_link())
        else:
            message = _("Product prices have been recomputed.")
        self.message_post(body=message)

    def _recompute_prices(self):
        lines_to_recompute = self._get_update_prices_lines()
        lines_to_recompute.invalidate_recordset(['pricelist_item_id'])
        lines_to_recompute.with_context(force_price_recomputation=True)._compute_price_unit()
        # Special case: we want to overwrite the existing discount on _recompute_prices call
        # i.e. to make sure the discount is correctly reset
        # if pricelist rule is different than when the price was first computed.
        lines_to_recompute.discount = 0.0
        lines_to_recompute._compute_discount()
        self.show_update_pricelist = False

    def _default_order_line_values(self, child_field=False):
        default_data = super()._default_order_line_values(child_field)
        new_default_data = self.env['sale.order.line']._get_product_catalog_lines_data()
        return {**default_data, **new_default_data}

    def _get_action_add_from_catalog_extra_context(self):
        return {
            **super()._get_action_add_from_catalog_extra_context(),
            'product_catalog_currency_id': self.currency_id.id,
            'product_catalog_digits': self.order_line._fields['price_unit'].get_digits(self.env),
        }

    def _get_product_catalog_domain(self):
        return expression.AND([super()._get_product_catalog_domain(), [('sale_ok', '=', True)]])

    def action_open_business_doc(self):
        self.ensure_one()
        return {
            'name': _("Order"),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.id,
            'views': [(False, 'form')],
        }

    # INVOICING #

    def _prepare_invoice(self):
        """
        Prepare the dict of values to create the new invoice for a sales order. This method may be
        overridden to implement custom invoice generation (making sure to call super() to establish
        a clean extension chain).
        """
        self.ensure_one()

        txs_to_be_linked = self.transaction_ids.sudo().filtered(
            lambda tx: (
                tx.state in ('pending', 'authorized')
                or tx.state == 'done' and not (tx.payment_id and tx.payment_id.is_reconciled)
            )
        )

        values = {
            'ref': self.client_order_ref or '',
            'move_type': 'out_invoice',
            'narration': self.note,
            'currency_id': self.currency_id.id,
            'campaign_id': self.campaign_id.id,
            'medium_id': self.medium_id.id,
            'source_id': self.source_id.id,
            'team_id': self.team_id.id,
            'partner_id': self.partner_invoice_id.id,
            'partner_shipping_id': self.partner_shipping_id.id,
            'fiscal_position_id': (self.fiscal_position_id or self.fiscal_position_id._get_fiscal_position(self.partner_invoice_id)).id,
            'invoice_origin': self.name,
            'invoice_payment_term_id': self.payment_term_id.id,
            'invoice_user_id': self.user_id.id,
            'payment_reference': self.reference,
            'transaction_ids': [Command.set(txs_to_be_linked.ids)],
            'company_id': self.company_id.id,
            'invoice_line_ids': [],
            'user_id': self.user_id.id,
        }
        if self.journal_id:
            values['journal_id'] = self.journal_id.id
        return values

    def action_view_invoice(self, invoices=False):
        if not invoices:
            invoices = self.mapped('invoice_ids')
        action = self.env['ir.actions.actions']._for_xml_id('account.action_move_out_invoice_type')
        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            form_view = [(self.env.ref('account.view_move_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state,view) for state,view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = invoices.id
        else:
            action = {'type': 'ir.actions.act_window_close'}

        context = {
            'default_move_type': 'out_invoice',
        }
        if len(self) == 1:
            context.update({
                'default_partner_id': self.partner_id.id,
                'default_partner_shipping_id': self.partner_shipping_id.id,
                'default_invoice_payment_term_id': self.payment_term_id.id or self.partner_id.property_payment_term_id.id or self.env['account.move'].default_get(['invoice_payment_term_id']).get('invoice_payment_term_id'),
                'default_invoice_origin': self.name,
            })
        action['context'] = context
        return action

    def _get_invoice_grouping_keys(self):
        return ['company_id', 'partner_id', 'currency_id']

    def _nothing_to_invoice_error_message(self):
        return _(
            "Cannot create an invoice. No items are available to invoice.\n\n"
            "To resolve this issue, please ensure that:\n"
            "   \u2022 The products have been delivered before attempting to invoice them.\n"
            "   \u2022 The invoicing policy of the product is configured correctly.\n\n"
            "If you want to invoice based on ordered quantities instead:\n"
            "   \u2022 For consumable or storable products, open the product, go to the 'General Information' tab and change the 'Invoicing Policy' from 'Delivered Quantities' to 'Ordered Quantities'.\n"
            "   \u2022 For services (and other products), change the 'Invoicing Policy' to 'Prepaid/Fixed Price'.\n"
        )

    def _get_update_prices_lines(self):
        """ Hook to exclude specific lines which should not be updated based on price list recomputation """
        return self.order_line.filtered(lambda line: not line.display_type)

    def _get_invoiceable_lines(self, final=False):
        """Return the invoiceable lines for order `self`."""
        down_payment_line_ids = []
        invoiceable_line_ids = []
        pending_section = None
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        c1 = 0
        c2 = 0
        c3 = 0

        for line in self.order_line:

            if line.product_id.invoice_policy == 'order':
                line.qty_to_invoice = line.product_uom_qty - line.qty_invoiced
            else:
                line.qty_to_invoice = line.qty_delivered - line.qty_invoiced

            if line.display_type == 'line_section':
                # Only invoice the section if one of its lines is invoiceable
                pending_section = line
                c1+=1
                continue
            if line.display_type != 'line_note' and float_is_zero(line.qty_to_invoice, precision_digits=precision):
                c2+=1
                continue
            if line.qty_to_invoice > 0 or (line.qty_to_invoice < 0 and final) or line.display_type == 'line_note':
                if line.is_downpayment:
                    # Keep down payment lines separately, to put them together
                    # at the end of the invoice, in a specific dedicated section.
                    down_payment_line_ids.append(line.id)
                    c3+=1
                    continue
                if pending_section:
                    invoiceable_line_ids.append(pending_section.id)
                    pending_section = None
                invoiceable_line_ids.append(line.id)
        _logger.info(f"In {len(self.order_line)} line: Invoiceable lines: {c1}, Not invoiceable lines: {c2}, Downpayment lines: {c3}")
        return self.env['sale.order.line'].browse(invoiceable_line_ids + down_payment_line_ids)

    def _create_account_invoices(self, invoice_vals_list, final):
        """Small method to allow overriding the behavior right after an invoice is created."""
        # Manage the creation of invoices in sudo because a salesperson must be able to generate an invoice from a
        # sale order without "billing" access rights. However, he should not be able to create an invoice from scratch.
        return self.env['account.move'].sudo().with_context(default_move_type='out_invoice').create(invoice_vals_list)

    def _create_invoices(self, grouped=False, final=False, date=None):
        """ Create invoice(s) for the given Sales Order(s).

        :param bool grouped: if True, invoices are grouped by SO id.
            If False, invoices are grouped by keys returned by :meth:`_get_invoice_grouping_keys`
        :param bool final: if True, refunds will be generated if necessary
        :param date: unused parameter
        :returns: created invoices
        :rtype: `account.move` recordset
        :raises: UserError if one of the orders has no invoiceable lines.
        """
        if not self.env['account.move'].has_access('create'):
            try:
                self.check_access('write')
            except AccessError:
                return self.env['account.move']

        # 1) Create invoices.
        invoice_vals_list = []
        invoice_item_sequence = 0 # Incremental sequencing to keep the lines order on the invoice.
        for order in self:
            if order.partner_invoice_id.lang:
                order = order.with_context(lang=order.partner_invoice_id.lang)
            order = order.with_company(order.company_id)

            invoice_vals = order._prepare_invoice()
            invoiceable_lines = order._get_invoiceable_lines(final)

            if not any(not line.display_type for line in invoiceable_lines):
                continue

            invoice_line_vals = []
            down_payment_section_added = False
            for line in invoiceable_lines:
                if not down_payment_section_added and line.is_downpayment:
                    # Create a dedicated section for the down payments
                    # (put at the end of the invoiceable_lines)
                    invoice_line_vals.append(
                        Command.create(
                            order._prepare_down_payment_section_line(sequence=invoice_item_sequence)
                        ),
                    )
                    down_payment_section_added = True
                    invoice_item_sequence += 1
                invoice_line_vals.append(
                    Command.create(
                        line._prepare_invoice_line(sequence=invoice_item_sequence)
                    ),
                )
                invoice_item_sequence += 1

            invoice_vals['invoice_line_ids'] += invoice_line_vals
            invoice_vals_list.append(invoice_vals)

        if not invoice_vals_list and self._context.get('raise_if_nothing_to_invoice', True):
            raise UserError(self._nothing_to_invoice_error_message())

        # 2) Manage 'grouped' parameter: group by (partner_id, currency_id).
        if not grouped:
            new_invoice_vals_list = []
            invoice_grouping_keys = self._get_invoice_grouping_keys()
            invoice_vals_list = sorted(
                invoice_vals_list,
                key=lambda x: [
                    x.get(grouping_key) for grouping_key in invoice_grouping_keys
                ]
            )
            for _grouping_keys, invoices in groupby(invoice_vals_list, key=lambda x: [x.get(grouping_key) for grouping_key in invoice_grouping_keys]):
                origins = set()
                payment_refs = set()
                refs = set()
                ref_invoice_vals = None
                for invoice_vals in invoices:
                    if not ref_invoice_vals:
                        ref_invoice_vals = invoice_vals
                    else:
                        ref_invoice_vals['invoice_line_ids'] += invoice_vals['invoice_line_ids']
                    origins.add(invoice_vals['invoice_origin'])
                    payment_refs.add(invoice_vals['payment_reference'])
                    refs.add(invoice_vals['ref'])
                ref_invoice_vals.update({
                    'ref': ', '.join(refs)[:2000],
                    'invoice_origin': ', '.join(origins),
                    'payment_reference': len(payment_refs) == 1 and payment_refs.pop() or False,
                })
                new_invoice_vals_list.append(ref_invoice_vals)
            invoice_vals_list = new_invoice_vals_list

        # 3) Create invoices.

        # As part of the invoice creation, we make sure the sequence of multiple SO do not interfere
        # in a single invoice. Example:
        # SO 1:
        # - Section A (sequence: 10)
        # - Product A (sequence: 11)
        # SO 2:
        # - Section B (sequence: 10)
        # - Product B (sequence: 11)
        #
        # If SO 1 & 2 are grouped in the same invoice, the result will be:
        # - Section A (sequence: 10)
        # - Section B (sequence: 10)
        # - Product A (sequence: 11)
        # - Product B (sequence: 11)
        #
        # Resequencing should be safe, however we resequence only if there are less invoices than
        # orders, meaning a grouping might have been done. This could also mean that only a part
        # of the selected SO are invoiceable, but resequencing in this case shouldn't be an issue.
        if len(invoice_vals_list) < len(self):
            SaleOrderLine = self.env['sale.order.line']
            for invoice in invoice_vals_list:
                sequence = 1
                for line in invoice['invoice_line_ids']:
                    line[2]['sequence'] = SaleOrderLine._get_invoice_line_sequence(new=sequence, old=line[2]['sequence'])
                    sequence += 1

        moves = self._create_account_invoices(invoice_vals_list, final)

        if(self.state == 'sale'):
            self.action_next_step()

        # 4) Some moves might actually be refunds: convert them if the total amount is negative
        # We do this after the moves have been created since we need taxes, etc. to know if the total
        # is actually negative or not
        if final and (moves_to_switch := moves.sudo().filtered(lambda m: m.amount_total < 0)):
            with self.env.protecting([moves._fields['team_id']], moves_to_switch):
                moves_to_switch.action_switch_move_type()
                self.invoice_ids._set_reversed_entry(moves_to_switch)

        for move in moves:
            if final:
                # Downpayment might have been determined by a fixed amount set by the user.
                # This amount is tax included. This can lead to rounding issues.
                # E.g. a user wants a 100€ DP on a product with 21% tax.
                # 100 / 1.21 = 82.64, 82.64 * 1,21 = 99.99
                # This is already corrected by adding/removing the missing cents on the DP invoice,
                # but must also be accounted for on the final invoice.

                delta_amount = 0
                for order_line in self.order_line:
                    if not order_line.is_downpayment:
                        continue
                    inv_amt = order_amt = 0
                    for invoice_line in order_line.invoice_lines:
                        sign = 1 if invoice_line.move_id.is_inbound() else -1
                        if invoice_line.move_id == move:
                            inv_amt += invoice_line.price_total * sign
                        elif invoice_line.move_id.state != 'cancel':  # filter out canceled dp lines
                            order_amt += invoice_line.price_total * sign
                    if inv_amt and order_amt:
                        # if not inv_amt, this order line is not related to current move
                        # if no order_amt, dp order line was not invoiced
                        delta_amount += inv_amt + order_amt

                if not move.currency_id.is_zero(delta_amount):
                    receivable_line = move.line_ids.filtered(
                        lambda aml: aml.account_id.account_type == 'asset_receivable')[:1]
                    product_lines = move.line_ids.filtered(
                        lambda aml: aml.display_type == 'product' and aml.is_downpayment)
                    tax_lines = move.line_ids.filtered(
                        lambda aml: aml.tax_line_id.amount_type not in (False, 'fixed'))
                    if tax_lines and product_lines and receivable_line:
                        line_commands = [Command.update(receivable_line.id, {
                            'amount_currency': receivable_line.amount_currency + delta_amount,
                        })]
                        delta_sign = 1 if delta_amount > 0 else -1
                        for lines, attr, sign in (
                            (product_lines, 'price_total', -1 if move.is_inbound() else 1),
                            (tax_lines, 'amount_currency', 1),
                        ):
                            remaining = delta_amount
                            lines_len = len(lines)
                            for line in lines:
                                if move.currency_id.compare_amounts(remaining, 0) != delta_sign:
                                    break
                                amt = delta_sign * max(
                                    move.currency_id.rounding,
                                    abs(move.currency_id.round(remaining / lines_len)),
                                )
                                remaining -= amt
                                line_commands.append(Command.update(line.id, {attr: line[attr] + amt * sign}))
                        move.line_ids = line_commands

            move.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': move, 'origin': move.line_ids.sale_line_ids.order_id},
                subtype_xmlid='mail.mt_note',
            )
        return moves

    # MAIL #

    def _discard_tracking(self):
        self.ensure_one()
        return (
            self.state == 'draft'
            and request and request.env.context.get('catalog_skip_tracking')
        )

    def _track_finalize(self):
        """ Override of `mail` to prevent logging changes when the SO is in a draft state. """
        if (len(self) == 1
            # The method _track_finalize is sometimes called too early or too late and it
            # might cause a desynchronization with the cache, thus this condition is needed.
            and self.env.cache.contains(self, self._fields['state']) and self._discard_tracking()):
            self.env.cr.precommit.data.pop(f'mail.tracking.{self._name}', {})
            self.env.flush_all()
            return
        return super()._track_finalize()

    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        if self.env.context.get('mark_so_as_sent'):
            self.filtered(lambda o: o.state == 'draft').with_context(tracking_disable=True).write({'state': 'sale'})
        so_ctx = {'mail_post_autofollow': self.env.context.get('mail_post_autofollow', True)}
        if self.env.context.get('mark_so_as_sent') and 'mail_notify_author' not in kwargs:
            kwargs['notify_author'] = self.env.user.partner_id.id in (kwargs.get('partner_ids') or [])
        return super(SaleOrder, self.with_context(**so_ctx)).message_post(**kwargs)

    def _notify_get_recipients_groups(self, message, model_description, msg_vals=None):
        """ Give access button to users and portal customer as portal is integrated
        in sale. Customer and portal group have probably no right to see
        the document so they don't have the access button. """
        groups = super()._notify_get_recipients_groups(
            message, model_description, msg_vals=msg_vals
        )
        if not self:
            return groups

        self.ensure_one()
        if self._context.get('proforma'):
            for group in [g for g in groups if g[0] in ('portal_customer', 'portal', 'follower', 'customer')]:
                group[2]['has_button_access'] = False
            return groups
        local_msg_vals = dict(msg_vals or {})

        # portal customers have full access (existence not granted, depending on partner_id)
        try:
            customer_portal_group = next(group for group in groups if group[0] == 'portal_customer')
        except StopIteration:
            pass
        else:
            access_opt = customer_portal_group[2].setdefault('button_access', {})
            is_tx_pending = self.get_portal_last_transaction().state == 'pending'
            if self._has_to_be_signed():
                if self._has_to_be_paid():
                    access_opt['title'] = _("View Quotation") if is_tx_pending else _("Sign & Pay Quotation")
                else:
                    access_opt['title'] = _("Accept & Sign Quotation")
            elif self._has_to_be_paid() and not is_tx_pending:
                access_opt['title'] = _("Accept & Pay Quotation")
            elif self.state in ('draft', 'sale'):
                access_opt['title'] = _("View Quotation")

        return groups

    def _notify_by_email_prepare_rendering_context(self, message, msg_vals=False, model_description=False,
                                                   force_email_company=False, force_email_lang=False):
        render_context = super()._notify_by_email_prepare_rendering_context(
            message, msg_vals, model_description=model_description,
            force_email_company=force_email_company, force_email_lang=force_email_lang
        )
        lang_code = render_context.get('lang')
        record = render_context['record']
        subtitles = [f"{record.name} - {record.partner_id.name}" if record.partner_id else record.name]
        if self.amount_total:
            # Do not show the price in subtitles if zero (e.g. e-commerce orders are created empty)
            subtitles.append(
                format_amount(self.env, self.amount_total, self.currency_id, lang_code=lang_code),
            )

        render_context['subtitles'] = subtitles
        return render_context

    def _phone_get_number_fields(self):
        """ No phone or mobile field is available on sale model. Instead SMS will
        fallback on partner-based computation using ``_mail_get_partner_fields``. """
        return []

    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'state' in init_values and self.state == 'sale':
            return self.env.ref('sale.mt_order_confirmed')
        elif 'state' in init_values and self.state == 'draft':
            return self.env.ref('sale.mt_order_sent')
        return super()._track_subtype(init_values)

    def _message_get_suggested_recipients(self):
        recipients = super()._message_get_suggested_recipients()
        if self.partner_id:
            self._message_add_suggested_recipient(
                recipients, partner=self.partner_id, reason=_("Customer")
            )
        return recipients

    # PAYMENT #

    def _force_lines_to_invoice_policy_order(self):
        """Force the qty_to_invoice to be computed as if the invoice_policy
        was set to "Ordered quantities", independently of the product configuration.

        This is needed for the automatic invoice logic, as we want to automatically
        invoice the full SO when it's paid.
        """
        for line in self.order_line:
            if line.state in ['sale', 'sale-staked', 'done']:
                # No need to set 0 as it is already the standard logic in the compute method.
                line.qty_to_invoice = line.product_uom_qty - line.qty_invoiced

    def payment_action_capture(self):
        """ Capture all transactions linked to this sale order. """
        self.ensure_one()
        payment_utils.check_rights_on_recordset(self)

        # In sudo mode to bypass the checks on the rights on the transactions.
        return self.transaction_ids.sudo().action_capture()

    def payment_action_void(self):
        """ Void all transactions linked to this sale order. """
        payment_utils.check_rights_on_recordset(self)

        # In sudo mode to bypass the checks on the rights on the transactions.
        self.authorized_transaction_ids.sudo().action_void()

    def get_portal_last_transaction(self):
        self.ensure_one()
        return self.transaction_ids.sudo()._get_last()

    def _get_order_lines_to_report(self):
        down_payment_lines = self.order_line.filtered(lambda line:
            line.is_downpayment
            and not line.display_type
            and not line._get_downpayment_state()
        )

        def show_line(line):
            if not line.is_downpayment:
                return True
            elif line.display_type and down_payment_lines:
                return True  # Only show the down payment section if down payments were posted
            elif line in down_payment_lines:
                return True  # Only show posted down payments
            else:
                return False

        return self.order_line.filtered(show_line)

    def _get_default_payment_link_values(self):
        self.ensure_one()
        amount_max = self.amount_total - self.amount_paid

        # Always default to the minimum value needed to confirm the order:
        # - order is not confirmed yet
        # - can be confirmed online
        # - we have still not paid enough for confirmation.
        prepayment_amount = self._get_prepayment_required_amount()
        if (
            self.state in ('draft', 'sent')
            and self.require_payment
            and self.currency_id.compare_amounts(prepayment_amount, self.amount_paid) > 0
        ):
            amount = prepayment_amount - self.amount_paid
        else:
            amount = amount_max

        return {
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_invoice_id.id,
            'amount': amount,
            'amount_max': amount_max,
            'amount_paid': self.amount_paid,
        }

    # EDI #

    def create_document_from_attachment(self, attachment_ids):
        """ Create the sale orders from given attachment_ids and redirect newly create order view.

        :param list attachment_ids: List of attachments process.
        :return: An action redirecting to related sale order view.
        :rtype: dict
        """
        orders = self._create_order_from_attachment(attachment_ids)
        return orders._get_records_action(name=_("Generated Orders"))

    @api.model
    def _create_order_from_attachment(self, attachment_ids):
        """ Create the sale orders from given attachment_ids and fill data by extracting detail
        from attachments and return generated orders.

        :param list attachment_ids: List of attachments process.
        :return: Recordset of order.
        """
        attachments = self.env['ir.attachment'].browse(attachment_ids)
        if not attachments:
            raise UserError(_("No attachment was provided"))

        orders = self.browse()
        for attachment in attachments:
            order = self.create({
                'partner_id': self.env.user.partner_id.id,
            })
            order._extend_with_attachments(attachment)
            orders |= order
            order.message_post(attachment_ids=attachment.ids)
            attachment.write({'res_model': self._name, 'res_id': order.id})

        return orders

    def _extend_with_attachments(self, attachment):
        """ Main entry point to extend/enhance order with attachment.

        :param attachment: A recordset of ir.attachment.
        :returns: None
        """
        self.ensure_one()

        file_data = attachment._unwrap_edi_attachments()[0]
        decoder = self._get_order_edi_decoder(file_data)
        if decoder:
            try:
                with self.env.cr.savepoint():
                    decoder(self, file_data)
            except RedirectWarning:
                raise
            except Exception:
                message = _(
                    "Error importing attachment '%(file_name)s' as order (decoder=%(decoder)s)",
                    file_name=file_data['filename'],
                    decoder=decoder.__name__,
                )
                self.with_user(SUPERUSER_ID).message_post(body=message)
                _logger.exception(message)

        if file_data.get('on_close'):
            file_data['on_close']()
        return True

    def _get_order_edi_decoder(self, file_data):
        """ To be extended with decoding capabilities of order data from file data.

        :returns:  Function to be later used to import the file.
                   Function' args:
                   - order: sale.order
                   - file_data: attachemnt information / value
                   returns True if was able to process the order
        """
        if file_data['type'] in ('pdf', 'binary'):
            return lambda *args: False
        return

    # PORTAL #

    def _has_to_be_signed(self):
        """A sale order has to be signed when:
        - its state is 'draft' or `sent`
        - it's not expired;
        - it requires a signature;
        - it's not already signed.

        Note: self.ensure_one()

        :return: Whether the sale order has to be signed.
        :rtype: bool
        """
        self.ensure_one()
        return (
            self.state in ['draft', 'sent']
            and not self.is_expired
            and self.require_signature
            and not self.signature
        )

    def _has_to_be_paid(self):
        """A sale order has to be paid when:
        - its state is 'draft' or `sent`;
        - it's not expired;
        - it requires a payment;
        - the last transaction's state isn't `done`;
        - the total amount is strictly positive.
        - confirmation amount is not reached

        Note: self.ensure_one()

        :return: Whether the sale order has to be paid.
        :rtype: bool
        """
        self.ensure_one()
        return (
            self.state in ['draft', 'sent']
            and not self.is_expired
            and self.require_payment
            and self.amount_total > 0
            and not self._is_confirmation_amount_reached()
        )

    def _get_portal_return_action(self):
        """ Return the action used to display orders when returning from customer portal. """
        self.ensure_one()
        return self.env.ref('sale.action_quotations_with_onboarding')

    def _get_name_portal_content_view(self):
        """ This method can be inherited by localizations who want to localize the online quotation view. """
        self.ensure_one()
        return 'sale.sale_order_portal_content'

    def _get_name_tax_totals_view(self):
        """ This method can be inherited by localizations who want to localize the taxes displayed on the portal and sale order report. """
        return 'sale.document_tax_totals'

    def _get_report_base_filename(self):
        self.ensure_one()
        return f'{self.type_name} {self.name}'

    #=== CORE METHODS OVERRIDES ===#

    @api.model
    def get_empty_list_help(self, help_msg):
        self = self.with_context(
            empty_list_help_document_name=_("sale order"),
        )
        return super().get_empty_list_help(help_msg)

    def _compute_field_value(self, field):
        if field.name != 'invoice_status' or self.env.context.get('mail_activity_automation_skip'):
            return super()._compute_field_value(field)

        filtered_self = self.filtered(
            lambda so: so.ids
                and (so.user_id or so.partner_id.user_id)
                and so._origin.invoice_status != 'upselling')
        super()._compute_field_value(field)

        upselling_orders = filtered_self.filtered(lambda so: so.invoice_status == 'upselling')
        upselling_orders._create_upsell_activity()

    #=== BUSINESS METHODS ===#

    def _create_upsell_activity(self):
        if not self:
            return

        self.activity_unlink(['sale.mail_act_sale_upsell'])
        for order in self:
            order_ref = order._get_html_link()
            customer_ref = order.partner_id._get_html_link()
            order.activity_schedule(
                'sale.mail_act_sale_upsell',
                user_id=order.user_id.id or order.partner_id.user_id.id,
                note=_("Upsell %(order)s for customer %(customer)s", order=order_ref, customer=customer_ref))

    def _prepare_analytic_account_data(self, prefix=None):
        """ Prepare SO analytic account creation values.

        :return: `account.analytic.account` creation values
        :rtype: dict
        """
        self.ensure_one()
        name = self.name
        if prefix:
            name = prefix + ": " + self.name
        project_plan, _other_plans = self.env['account.analytic.plan']._get_all_plans()
        return {
            'name': name,
            'code': self.client_order_ref,
            'company_id': self.company_id.id,
            'plan_id': project_plan.id,
            'partner_id': self.partner_id.id,
        }

    def _prepare_down_payment_section_line(self, **optional_values):
        """ Prepare the values to create a new down payment section.

        :param dict optional_values: any parameter that should be added to the returned down payment section
        :return: `account.move.line` creation values
        :rtype: dict
        """
        self.ensure_one()
        context = {'lang': self.partner_id.lang}
        down_payments_section_line = {
            'display_type': 'line_section',
            'name': _("Cọc Trước"),
            'product_id': False,
            'product_uom_id': False,
            'quantity': 0,
            'discount': 0,
            'price_unit': 0,
            'account_id': False,
            **optional_values
        }
        del context
        return down_payments_section_line

    def _get_prepayment_required_amount(self):
        """ Return the minimum amount needed to confirm automatically the quotation.

        Note: self.ensure_one()

        :return: The minimum amount needed to confirm automatically the quotation.
        :rtype: float
        """
        self.ensure_one()
        if self.prepayment_percent == 1.0 or not self.require_payment:
            return self.amount_total
        else:
            return self.currency_id.round(self.amount_total * self.prepayment_percent)

    def _is_confirmation_amount_reached(self):
        """ Return whether `self.amount_paid` is higher than the prepayment required amount.

        Note: self.ensure_one()

        :return: Whether `self.amount_paid` is higher than the prepayment required amount.
        :rtype: bool
        """
        self.ensure_one()
        amount_comparison = self.currency_id.compare_amounts(
            self._get_prepayment_required_amount(), self.amount_paid,
        )
        return amount_comparison <= 0

    def _generate_downpayment_invoices(self):
        """ Generate invoices as down payments for sale order.

        :return: The generated down payment invoices.
        :rtype: recordset of `account.move`
        """
        generated_invoices = self.env['account.move']

        for order in self:
            downpayment_wizard = order.env['sale.advance.payment.inv'].create({
                'sale_order_ids': order,
                'advance_payment_method': 'fixed',
                'fixed_amount': order.amount_paid,
            })
            generated_invoices |= downpayment_wizard._create_invoices(order)

        return generated_invoices

    def _get_product_catalog_order_data(self, products, **kwargs):
        pricelist = self.pricelist_id._get_products_price(
            quantity=1.0,
            products=products,
            currency=self.currency_id,
            date=self.date_order,
            **kwargs,
        )
        res = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            res[product.id]['price'] = pricelist.get(product.id)
            if product.sale_line_warn != 'no-message' and product.sale_line_warn_msg:
                res[product.id]['warning'] = product.sale_line_warn_msg
            if product.sale_line_warn == "block":
                res[product.id]['readOnly'] = True
        return res

    def _get_product_catalog_record_lines(self, product_ids, **kwargs):
        grouped_lines = defaultdict(lambda: self.env['sale.order.line'])
        for line in self.order_line:
            if line.display_type or line.product_id.id not in product_ids:
                continue
            grouped_lines[line.product_id] |= line
        return grouped_lines

    def _get_product_documents(self):
        self.ensure_one()

        documents = (
            self.order_line.product_id.product_document_ids
            | self.order_line.product_template_id.product_document_ids
        )
        return self._filter_product_documents(documents).sorted()

    def _filter_product_documents(self, documents):
        return documents.filtered(
            lambda document:
                document.attached_on_sale == 'quotation'
                or (self.state == 'sale' and document.attached_on_sale == 'sale_order')
        )

    def _update_order_line_info(self, product_id, quantity, **kwargs):
        """ Update sale order line information for a given product or create a
        new one if none exists yet.
        :param int product_id: The product, as a `product.product` id.
        :return: The unit price of the product, based on the pricelist of the
                 sale order and the quantity selected.
        :rtype: float
        """
        request.update_context(catalog_skip_tracking=True)
        sol = self.order_line.filtered(lambda line: line.product_id.id == product_id)
        if sol:
            if quantity != 0:
                sol.product_uom_qty = quantity
            elif self.state in ['draft', 'sent']:
                price_unit = self.pricelist_id._get_product_price(
                    product=sol.product_id,
                    quantity=1.0,
                    currency=self.currency_id,
                    date=self.date_order,
                    **kwargs,
                )
                sol.unlink()
                return price_unit
            else:
                sol.product_uom_qty = 0
        elif quantity > 0:
            sol = self.env['sale.order.line'].create({
                'order_id': self.id,
                'product_id': product_id,
                'product_uom_qty': quantity,
                'sequence': ((self.order_line and self.order_line[-1].sequence + 1) or 10),  # put it at the end of the order
            })
        return sol.price_unit * (1-(sol.discount or 0.0)/100.0)

    #=== TOOLING ===#

    def _is_readonly(self):
        """ Return Whether the sale order is read-only or not based on the state or the lock status.

        A sale order is considered read-only if its state is 'cancel' or if the sale order is
        locked.

        :return: Whether the sale order is read-only or not.
        :rtype: bool
        """
        self.ensure_one()
        return self.state == 'cancel' or self.locked

    def _is_paid(self):
        """ Return whether the sale order is paid or not based on the linked transactions.

        A sale order is considered paid if the sum of all the linked transaction is equal to or
        higher than `self.amount_total`.

        :return: Whether the sale order is paid or not.
        :rtype: bool
        """
        self.ensure_one()
        return self.currency_id.compare_amounts(self.amount_paid, self.amount_total) >= 0

    def _get_lang(self):
        self.ensure_one()

        if self.partner_id.lang and not self.partner_id.is_public:
            return self.partner_id.lang

        return self.env.lang

    def _validate_order(self):
        """
        Confirm the sale order and send a confirmation email.

        :return: None
        """
        self.with_context(send_email=True).action_confirm()

    # ---- Customization ---- #

    def action_next_step(self):
        """Chuyển sang bước kế tiếp trong chuỗi trạng thái"""
        sequence = ['draft', 'sale', 'sale-staked', 'production', 'del-cons', 'debt', 'done']
        for record in self:
            try:
                current_index = sequence.index(record.state)
                if current_index < len(sequence) - 1:
                    record.state = sequence[current_index + 1]
            except ValueError:
                pass  # Trường hợp state không nằm trong danh sách
    

    def action_done_invoice(self):
        # self.ensure_one() # Đảm bảo hàm chạy trên một đơn hàng

        for record in self:
            try:
                if not record.order_line.check_all_invoices_paid():
                    record.invoice_status = 'deposit'
                    record.state = 'debt'
                    return {
                        'warning': {
                            'title': "Thông báo",
                            'message': "Đơn hàng chưa được thanh toán đầy đủ. Tiến hành chuyển sang trạng thái 'Công Nợ'.",
                        }
                    }
                else:
                    record.state = 'done'
                    record.invoice_status = 'invoiced'

            except ValueError:
                pass

    def action_done_debt(self):
        # self.ensure_one() # Đảm bảo hàm chạy trên một đơn hàng

        for record in self:
            try:
                if record.invoice_status == 'no':
                    raise UserError("Đơn hàng chưa được lập hóa đơn.")
                elif not record.order_line.check_all_invoices_paid():
                    raise UserError("Đơn hàng chưa được thanh toán đầy đủ.")
                else:
                    record.state = 'done'
            except ValueError:
                pass

#=== Pancake ===#

    # --- Helper methods to be implemented by you ---
    def _get_pancake_api_key(self):
        # Ví dụ: return self.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
        # Đây là placeholder, bạn cần triển khai logic thực tế
        param = self.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
        if not param:
            raise UserError(_("Pancake API Key not configured in System Parameters (pancake.api_key)."))
        return param

    def _get_pancake_shop_id(self):
        # Ví dụ: return self.env['ir.config_parameter'].sudo().get_param('pancake.shop_id')
        # Đây là placeholder, bạn cần triển khai logic thực tế
        param = self.env['ir.config_parameter'].sudo().get_param('pancake.shop_id')
        if not param:
            raise UserError(_("Pancake Shop ID not configured in System Parameters (pancake.shop_id)."))
        return param

    def _get_pancake_status_to_odoo_state_mapping(self):
        # Ánh xạ key trạng thái Pancake (dạng số string) sang state của Odoo
        # Cần điều chỉnh dựa trên các status thực tế của Pancake
        # Ví dụ: '1': 'draft', '7': 'sale', '9': 'cancel', ...
        # pancake_status_key -> state
        return {
            # THÊM CÁC MAPPING CỤ THỂ CỦA BẠN VÀO ĐÂY
            # Ví dụ: 
            # '1': 'draft',  # Trạng thái mới chờ xử lý
            # '2': 'draft',  # Đã xác nhận thông tin
            # '3': 'draft', # Chờ lấy hàng
            # '7': 'sale',   # Hoàn thành (đã giao)
            # '8': 'cancel', # Khách hủy
            # '9': 'cancel', # Shop hủy
            # '10': 'sale', # Đã đối soát (nếu coi như hoàn thành)
            # '11': 'draft', # Đang vận chuyển
            # '12': 'cancel', # Chuyển hoàn
        }

    @api.model
    def action_sync_pancake_all_orders(self, *args, **kwargs):
        _logger.info("Starting Pancake orders synchronization for SaleOrder...")

        # Lấy thời điểm lần chạy cuối từ config
        param_key = 'pancake.last_sync_time'
        config_param = self.env['ir.config_parameter']
        last_sync_str = config_param.sudo().get_param(param_key)

        if last_sync_str:
            last_sync_time = datetime.strptime(last_sync_str, DEFAULT_SERVER_DATETIME_FORMAT)
            now = datetime.now()
            _logger.info(f"Last sync time: {last_sync_time}, Current time: {now}")

            if now - last_sync_time < timedelta(seconds=10):
                _logger.info("Too speed, please wait...")
                return {
                    'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': _('Pancake Sync'), 'message': _('Please wait at least 10 seconds between synchronizations.'), 'sticky': False, 'type': 'warning'}
                }

        # Cập nhật thời điểm chạy hiện tại
        now_str = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        config_param.sudo().set_param(param_key, now_str)

        # Đảm bảo self là một recordset hợp lệ để truy cập env và các phương thức
        if not self:
            self = self.env['sale.order'] # Khởi tạo một recordset rỗng nếu self không có

        api_key = self._get_pancake_api_key()
        shop_id = self._get_pancake_shop_id()

        Partner = self.env['res.partner']
        Product = self.env['product.product']
        CrmTag = self.env['crm.tag']
        ResUsers = self.env['res.users']
        ResCurrency = self.env['res.currency']
        CrmTeam = self.env['crm.team'] # Thêm model CRM Team

        status_mapping = self._get_pancake_status_to_odoo_state_mapping()

        # Cải thiện logic xác định company_id:
        # Lấy company_id từ context (nếu có), nếu không có, lấy từ công ty hiện tại của environment.
        # Nếu vẫn không có (ví dụ: môi trường global hoặc lỗi cấu hình), đặt là False để tìm kiếm các bản ghi không thuộc công ty nào.
        current_company_id = self.env.context.get('company_id')
        if current_company_id is None: # If not explicitly set in context
            if self.env.company: # If there's a company in the environment
                current_company_id = self.env.company.id
            else:
                current_company_id = False # No company, set to False for global records


        if current_company_id is False:
            company_domain_for_search = [('company_id', '=', False)]
        else:
            company_domain_for_search = ['|', ('company_id', '=', False), ('company_id', '=', current_company_id)]
       
        # Construct company_domain safely
        if current_company_id is False:
            # If current_company_id is False, search for records with company_id = False (global)
            company_domain = [('company_id', '=', False)]
        else:
            # If current_company_id is an integer, search for global records OR records of that company
            company_domain = ([ '|',('company_id', '=', False), ('company_id', '=', current_company_id)])

        all_orders_data = []
        current_page = 1
        limit_per_page_param = self.env['ir.config_parameter'].sudo().get_param('pancake.sync.limit_per_page', '50')
        try:
            limit_per_page = int(limit_per_page_param)
        except ValueError:
            limit_per_page = 50

        while True:
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/orders?api_key={api_key}&page_size={limit_per_page}&page_number={current_page}"
            _logger.info(f"Calling Pancake API (Page {current_page}): {api_url.replace(api_key, '***REDACTED***')}")

            try:
                response = requests.get(api_url, timeout=120)
                response.raise_for_status()
                page_data = response.json()
            except requests.exceptions.Timeout:
                _logger.error(f"API call timed out for page {current_page}.")
                self.env.cr.commit() # Commit những gì đã xử lý trước đó
                raise UserError(_("Pancake API call timed out for page %s. Processed orders before timeout have been saved.") % current_page)
            except requests.exceptions.RequestException as e:
                _logger.error(f"API call failed for page {current_page}: {e}")
                self.env.cr.commit()
                raise UserError(_("Failed to connect to Pancake API on page %s: %s. Processed orders before error have been saved.") % (current_page, e))
            except ValueError as e: # JSONDecodeError
                _logger.error(f"Failed to decode JSON response for page {current_page}: {e}. Response text: {response.text[:500]}")
                self.env.cr.commit()
                raise UserError(_("Failed to parse response from Pancake API on page %s: %s. Processed orders before error have been saved.") % (current_page, e))

            orders_on_page = page_data.get('data', [])
            if not orders_on_page:
                break
            
            all_orders_data.extend(orders_on_page)
            
            if len(orders_on_page) < limit_per_page:
                break
            current_page += 1
            
        if not all_orders_data:
            _logger.info("No orders found in the API response after checking all pages.")
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Pancake Sync'), 'message': _('No orders found from Pancake API.'), 'sticky': False, 'type': 'warning'}
            }
        
        processed_count = 0
        created_count = 0
        updated_count = 0
        skipped_count = 0
        error_count = 0

        # Lấy sản phẩm dịch vụ cho phí vận chuyển và phụ phí (tạo nếu chưa có)
        # Sử dụng domain rõ ràng cho company_id: False (global) hoặc company_id cụ thể
        # company_domain = expression.OR([('company_id', '=', False), ('company_id', '=', company_id)]) if company_id else [('company_id', '=', False)]

                # Lấy sản phẩm dịch vụ cho phí vận chuyển và phụ phí (tạo nếu chưa có)
        # Bạn nên tạo các sản phẩm này trong Odoo trước với default_code cố định
        # shipping_product = Product.search([('default_code', '=', 'DELIV_PANCAKE'), ('type', '=', 'service'), '|', ('company_id', '=', None), ('company_id', '=', company_id)], limit=1)
        # if not shipping_product:
        #     try:
        #         shipping_product = Product.create({
        #             'name': 'Phí vận chuyển (Pancake)', 'default_code': 'DELIV_PANCAKE', 'type': 'service',
        #             'sale_ok': True, 'purchase_ok': False, 'invoice_policy': 'order', 'company_id': company_id,
        #             'categ_id': self.env.ref('product.product_category_all').id, 'lst_price': 0
        #         })
        #         _logger.info("Created 'Phí vận chuyển (Pancake)' service product (DELIV_PANCAKE).")
        #     except Exception as e:
        #         _logger.error(f"Failed to create shipping product: {e}")
        #         shipping_product = False # Không thể tạo, sẽ bỏ qua thêm dòng này

        # domain = [
        #     ('default_code', '=', 'DELIV_PANCAKE'),
        #     ('type', '=', 'service'),
        #     # '|', ('company_id', '=', None), ('company_id', '=', company_id)
        # ]
        
        # # Chỉ thêm company_domain nếu nó không rỗng
        # if company_domain:
        #     domain += company_domain

        # shipping_product = Product.search(domain, limit=1)

        shipping_product = Product.search(([('default_code', '=', 'DELIV_PANCAKE'), ('type', '=', 'service')]+company_domain), limit=1)
        if not shipping_product:
            try:
                shipping_product = Product.create({
                    'name': 'Phí vận chuyển (Pancake)', 'default_code': 'DELIV_PANCAKE', 'type': 'service',
                    'sale_ok': True, 'purchase_ok': False, 'invoice_policy': 'order', 'company_id': current_company_id if current_company_id else False,
                    'categ_id': self.env.ref('product.product_category_all').id, 'lst_price': 0
                })
                _logger.info("Created 'Phí vận chuyển (Pancake)' service product (DELIV_PANCAKE).")
            except Exception as e:
                _logger.error(f"Failed to create shipping product: {e}")
                shipping_product = False

        surcharge_product = Product.search(([('default_code', '=', 'SURCH_PANCAKE'), ('type', '=', 'service')] +company_domain), limit=1)
        if not surcharge_product:
            try:
                surcharge_product = Product.create({
                    'name': 'Phụ phí (Pancake)', 'default_code': 'SURCH_PANCAKE', 'type': 'service',
                    'sale_ok': True, 'purchase_ok': False, 'invoice_policy': 'order', 'company_id': current_company_id if current_company_id else False,
                    'categ_id': self.env.ref('product.product_category_all').id, 'lst_price': 0
                })
                _logger.info("Created 'Phụ phí (Pancake)' service product (SURCH_PANCAKE).")
            except Exception as e:
                _logger.error(f"Failed to create surcharge product: {e}")
                surcharge_product = False

        for order_data in all_orders_data:
            p_order_id = str(order_data.get('id'))
            if not p_order_id:
                _logger.warning(f"Skipping order with missing ID in data: {str(order_data)[:200]}")
                skipped_count += 1
                continue

            if len(order_data.get('status_history', [])) == 0:
                _logger.info(f"Skipping Pancake Order ID {p_order_id} due to empty status history.")
                skipped_count += 1
                continue 

            try:
                # --- Creator ---
                creator_info = order_data.get('creator')
                odoo_creator = self.env.user # Mặc định là người dùng hiện tại
                if creator_info:    
                    # create_id = (creator_info.get('id')) # Không sử dụng, có thể gây nhầm lẫn với ID Odoo
                    creator_name = (creator_info.get('name'))
                    creator_email = (creator_info.get('email'))
                    creator_phone = (creator_info.get('phone_number'))

                    # Tìm kiếm user theo email hoặc login
                    if creator_email:
                        odoo_creator = ResUsers.sudo().search([('login', '=', creator_email)], limit=1)
                    
                    if not odoo_creator and creator_name: # Tạo user nếu không tìm thấy và có tên
                        _logger.info(f"Creating new Odoo user for Pancake creator: {creator_name} ({creator_email})")
                        try:
                            # Lấy group nội bộ (Internal User) để gán quyền cơ bản
                            internal_group = self.env.ref('base.group_user')
                            odoo_creator = ResUsers.sudo().create({
                                'name': creator_name,
                                'login': creator_email if creator_email else creator_name.lower().replace(' ', '.'), # Tạo login từ email hoặc tên
                                'email': creator_email,
                                'phone': creator_phone,
                                'password': creator_email if creator_email else 'odoo_temp_pass', # Đặt password tạm thời
                                'active': True,
                                'share': False, # Không phải user chia sẻ
                                'company_id': current_company_id if current_company_id else False,
                                'groups_id': [(6, 0, [internal_group.id])],
                            })
                        except Exception as e_user:
                            _logger.error(f"Failed to create Odoo user for Pancake creator {creator_name}: {e_user}")
                            # Nếu không tạo được user, vẫn dùng user mặc định (self.env.user)

                # ---- Salesperson (user_id) & Team (team_id) ---
                assigning_seller_info = order_data.get('assigning_seller')
                p_assigning_seller_name = (assigning_seller_info.get('name') 
                                             if isinstance(assigning_seller_info, dict) else None)
                p_assigning_seller_email = (assigning_seller_info.get('email')
                                             if isinstance(assigning_seller_info, dict) else None)
                
                user_id_val = self.env.user.id # Default to current user's ID

                if p_assigning_seller_name:
                    salesperson = ResUsers.search([
                        ('name', '=ilike', p_assigning_seller_name),
                        ('share', '=', False) # Chỉ tìm kiếm user nội bộ
                    ], limit=1)

                    if not salesperson and p_assigning_seller_email:
                        salesperson = ResUsers.search([
                            ('login', '=', p_assigning_seller_email),
                            ('share', '=', False)
                        ], limit=1)

                    if not salesperson:
                        _logger.info(f"Creating new Odoo user for Pancake salesperson: {p_assigning_seller_name} ({p_assigning_seller_email})")
                        try:
                            login_val = p_assigning_seller_email if p_assigning_seller_email else p_assigning_seller_name.lower().replace(' ', '_')
                            # Đảm bảo login là duy nhất
                            existing_user_with_login = ResUsers.search([('login', '=', login_val)], limit=1)
                            if existing_user_with_login:
                                login_val = f"{login_val}_{existing_user_with_login.id}" # Thêm ID để đảm bảo duy nhất

                            internal_group = self.env.ref('base.group_user')
                            salesperson = ResUsers.create({
                                'name': p_assigning_seller_name,
                                'login': login_val,
                                'email': p_assigning_seller_email,
                                'password': login_val, # Đặt password tạm thời
                                'company_id': current_company_id if current_company_id else False,
                                'active': True,
                                'share': False, # Không phải user chia sẻ 
                                'groups_id': [(6, 0, [internal_group.id])],
                            })
                            _logger.info(f"Created salesperson {salesperson.name} (ID: {salesperson.id}) for Pancake order {p_order_id}")
                        except Exception as e_saler:
                            _logger.error(f"Failed to create Odoo user for Pancake salesperson {p_assigning_seller_name}: {e_saler}")
                            salesperson = False # Đảm bảo salesperson là False nếu tạo lỗi

                    if salesperson:
                        user_id_val = salesperson.id
                    else:
                        _logger.warning(f"Could not find or create salesperson for Pancake Order ID: {p_order_id}. Using current user.")
                        user_id_val = self.env.user.id # Nếu không tìm/tạo được, dùng user hiện tại

                # TÌM HOẶC TẠO SALES TEAM dựa trên Salesperson nếu có
                final_team_id_val = False
                if user_id_val:
                    # Odoo thường có team mặc định hoặc team tự động tạo cho user
                    # Chúng ta có thể tìm team liên kết với user này hoặc team mặc định
                    sales_team = CrmTeam.search([
                         ('user_id', '=', user_id_val), # Team có user này là trưởng nhóm
                        # ('member_ids', 'in', user_id_val) # Hoặc user này là thành viên
                    ], limit=1)
                    
                    if not sales_team:
                        # Thử lấy team mặc định nếu có
                        sales_team = self.env.ref('sales_team.team_sales_department', raise_if_not_found=False)
                        if not sales_team:
                            # Tạo một sales team mới nếu không có team mặc định và không tìm thấy
                            _logger.info(f"Creating new Sales Team for salesperson ID: {user_id_val}")
                            sales_team = CrmTeam.create({
                                'name': f"Pancake Sales Team - {ResUsers.browse(user_id_val).name}",
                                'user_id': user_id_val, # Gán salesperson làm trưởng nhóm
                                'company_id': current_company_id if current_company_id else False,
                            })
                            _logger.info(f"Created sales team {sales_team.name} (ID: {sales_team.id})")
                    
                    if sales_team:
                        final_team_id_val = sales_team.id


                # --- Customer (partner_id) ---
                customer_info = order_data.get('customer', {})
                partner = False
                customer_id = customer_info.get('id')
                customer_phone_list = customer_info.get('phone_numbers', [])
                customer_phone = customer_phone_list[0] if customer_phone_list else None
                customer_email_list = customer_info.get('emails', [])
                customer_email = customer_email_list[0] if customer_email_list else None
                customer_name = customer_info.get('name')

                # Tìm kiếm partner theo phone (company_id = False hoặc company_id cụ thể)
                partner_domain_phone = ([('phone', '=', customer_phone)])
                if customer_phone:
                    partner = Partner.search(partner_domain_phone, limit=1)
                    # _logger.info(f"Tìm thấy partner theo phone: {customer_phone} cho Pancake order {p_order_id}")

                if not partner:
                    partner_domain_ID = ([('pancake_id', '=', customer_id)])
                    partner = Partner.search(partner_domain_ID, limit=1)

                    

                # Nếu chưa tìm thấy, tìm theo email
                if not partner and customer_email:
                    partner_domain_email = ([('email', '=ilike', customer_email)])
                    partner = Partner.search(partner_domain_email, limit=1)
                    _logger.info(f"Tìm thấy partner theo email: {customer_email} cho Pancake order {p_order_id}")
                
                # Nếu vẫn chưa tìm thấy và có tên & (phone hoặc email), tạo mới partner
                if not partner and customer_name and (customer_phone or customer_email):
                    _logger.info(f"Creating new partner: {customer_name} ({customer_phone or customer_email}) for Pancake order {p_order_id}")
                    partner_vals = {
                        'name': customer_name, 'phone': customer_phone, 'email': customer_email,
                        'company_type': 'person', 'company_id': current_company_id if current_company_id else False,
                    }
                    partner = Partner.create(partner_vals)
                    _logger.info(f"Created new partner: {partner.name} (ID: {partner.id}) Company: {partner.company_id} for Pancake order {p_order_id}")
                
                if not partner:
                    _logger.warning(f"Could not find or create customer for Pancake Order ID: {p_order_id}. Skipping order.")
                    skipped_count += 1
                    continue
                else:
                # In thông tin partner
                    _logger.info(f"Found or created partner: ID={partner.id}, Name={partner.name}, Email={partner.email}, Phone={partner.phone}")
                    partner.phone = customer_phone or partner.phone # Cập nhật phone nếu có từ Pancake
                    # Để in thông tin company, bạn cần truy cập nó thông qua partner
                    # Partner có trường company_id. Nếu partner là một công ty (is_company=True),
                    # thì company_id của nó chính là bản thân nó.
                    # Nếu partner là một cá nhân, company_id của nó có thể là công ty mà nó liên kết.
                    # Trong bối cảnh này, nếu bạn muốn biết công ty nào đang xử lý đơn hàng,
                    # đó thường là self.env.company.
                    
                    # In thông tin công ty hiện tại của môi trường (công ty Odoo đang hoạt động)
                    current_company = self.env.company
                    _logger.info(f"Current Odoo Company: ID={current_company.id}, Name={current_company.name}")

                    # Nếu bạn muốn thông tin công ty liên kết với đối tác (nếu có, thường là đối tác loại cá nhân)
                    if partner.company_id:
                        _logger.info(f"Partner's linked company: ID={partner.company_id.id}, Name={partner.company_id.name}")
                    elif partner.is_company: # Nếu đối tác là một công ty
                        _logger.info(f"Partner itself is a company: ID={partner.id}, Name={partner.name}")



                # --- Shipping Address (partner_shipping_id) ---
                shipping_address_info = order_data.get('shipping_address', {})
                partner_shipping_id = partner.id # Default to customer's main address
                
                sfn = shipping_address_info.get('full_name')
                sp = shipping_address_info.get('phone_number')
                s_addr = shipping_address_info.get('full_address')
                s_prov = shipping_address_info.get('province_name')
                s_dist = shipping_address_info.get('district_name')
                s_comm = shipping_address_info.get('commune_name') or shipping_address_info.get('commnue_name') # Fix typo in API data if any

                # Logic để xác định nếu địa chỉ giao hàng khác với địa chỉ chính của đối tác
                # Nếu tên người nhận hoặc số điện thoại hoặc địa chỉ khác, coi là địa chỉ phụ
                if sfn and (sfn != partner.name or (sp and sp != partner.phone) or s_addr and s_addr != partner.street):
                    shipping_contact_domain = [
                        ('parent_id', '=', partner.id), 
                        ('type', '=', 'delivery'),
                        ('name', '=', sfn),
                    ]
                    if sp:
                        shipping_contact_domain.append(('phone', '=', sp))
                    if s_addr:
                        shipping_contact_domain.append(('street', '=', s_addr))

                    shipping_contact = Partner.search(shipping_contact_domain, limit=1)
                    if not shipping_contact:
                        _logger.info(f"Creating new shipping contact for {sfn} for Pancake order {p_order_id}")
                        shipping_contact_vals = {
                            'name': sfn, 'parent_id': partner.id, 'type': 'delivery',
                            'phone': sp or partner.phone, # Ưu tiên SĐT người nhận GH, fallback về SĐT chính của partner
                            'street': s_addr, 
                            'city': s_dist, # Odoo 'city' thường là quận/huyện hoặc tỉnh/thành phố
                            # Có thể map province/district/commune sang các trường địa chỉ chuẩn của Odoo
                            # nếu có các module localization phù hợp, hoặc các trường tùy chỉnh (x_...)
                            # 'x_province': s_prov, # Ví dụ các trường tùy chỉnh nếu có
                            # 'x_district': s_dist,
                            # 'x_commune': s_comm,
                        }
                        shipping_contact = Partner.create(shipping_contact_vals)
                        _logger.info(f"Created shipping contact ID {shipping_contact.id} for Pancake order {p_order_id}")
                    partner_shipping_id = shipping_contact.id
                
                # --- Currency & Pricelist ---
                p_currency_code = order_data.get('order_currency', 'VND')
                currency = ResCurrency.search([('name', '=', p_currency_code)], limit=1)
                currency_id_val = currency.id if currency else self.env.company.currency_id.id
                
                

                pricelist = False
                if partner.company_id and partner.property_product_pricelist and \
                   partner.property_product_pricelist.currency_id.id == currency_id_val:
                    pricelist = partner.property_product_pricelist
                
                if not pricelist:
                    # Tìm pricelist theo currency và company
                    pricelist_domain = ([('currency_id', '=', currency_id_val)] + company_domain)
                    # Sắp xếp để ưu tiên pricelist của công ty hiện tại nếu có
                    pricelist = self.env['product.pricelist'].search(pricelist_domain, order='company_id desc, sequence, id', limit=1) 
                
                pricelist_id_val = pricelist.id if pricelist else False
                if not pricelist_id_val:
                    _logger.error(f"Pricelist not found for currency {p_currency_code} and company {current_company_id} for order {p_order_id}. Skipping order.")
                    try:
                        pricelist = self.env['product.pricelist'].sudo().create({
                            'name': f'Default {p_currency_code} Pricelist - {self.env.company.name if current_company_id else "Global"}',
                            'currency_id': currency_id_val,
                            'company_id': current_company_id if current_company_id else False,
                        })
                        _logger.info(f"Successfully created new pricelist '{pricelist.name}' (ID: {pricelist.id}) for order {p_order_id}.")
                    except Exception as e_pricelist:
                        _logger.error(f"Failed to create a default pricelist for order {p_order_id}: {e_pricelist}")
                        skipped_count += 1
                        continue # Không thể tiếp tục nếu không có bảng giá
                pricelist_id_val = pricelist.id

                # --- Datetimes ---
                p_inserted_at_dt = False
                inserted_at_str_from_api = order_data.get('inserted_at')
                if inserted_at_str_from_api:
                    try:
                        p_inserted_at_dt = datetime.strptime(inserted_at_str_from_api.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                    except Exception: 
                        _logger.warning(f"Could not parse inserted_at: {inserted_at_str_from_api} for order {p_order_id}")

                p_updated_at_dt = False
                updated_at_str_from_api = order_data.get('updated_at')
                if updated_at_str_from_api:
                    try:
                        p_updated_at_dt = datetime.strptime(updated_at_str_from_api.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                    except Exception:
                        _logger.warning(f"Could not parse updated_at: {updated_at_str_from_api} for order {p_order_id}")

                # --- Odoo Tags (crm.tag) ---
                odoo_tag_ids = []
                for tag_data in order_data.get('tags', []):
                    p_tag_name = tag_data.get('name')
                    if p_tag_name:
                        odoo_tag = CrmTag.search([('name', '=', p_tag_name)], limit=1)
                        if not odoo_tag:
                            try:
                                odoo_tag = CrmTag.create({'name': p_tag_name})
                                _logger.info(f"Created CRM Tag: {p_tag_name}")
                            except Exception as e_tag:
                                _logger.error(f"Failed to create CRM tag {p_tag_name}: {e_tag}")
                        if odoo_tag:
                            odoo_tag_ids.append(odoo_tag.id)
                
                # --- Status Mapping ---
                p_status_key = str(order_data.get('status'))
                odoo_state = status_mapping.get(p_status_key, 'draft')

                # --- Creator & Page Name ---
                p_creator_name = (order_data.get('creator').get('name') 
                                  if isinstance(order_data.get('creator'), dict) else None)
                p_page_name = (order_data.get('page').get('name')
                               if isinstance(order_data.get('page'), dict) else None)

                # --- Prepare Sale Order Values ---
                order_vals = {
                    'pancake_order_id': p_order_id,
                    'partner_id': partner.id,
                    'partner_shipping_id': partner_shipping_id,
                    'date_order': p_inserted_at_dt or fields.Datetime.now(), # Sử dụng thời gian hiện tại nếu không có
                    'state': odoo_state, # Initial state
                    'user_id': user_id_val,
                    'creator_id': odoo_creator.id,
                    'team_id': final_team_id_val,
                    'company_id': current_company_id if current_company_id else False,
                    'currency_id': currency_id_val,
                    'pricelist_id': pricelist_id_val,
                    'origin': f"Pancake: {p_order_id} - {order_data.get('order_sources_name', '')}".strip()[:64],
                    'client_order_ref': p_order_id,
                    'note': order_data.get('note'),
                    'tag_ids': [(6, 0, odoo_tag_ids)] if odoo_tag_ids else False,

                    'pancake_system_id': str(order_data.get('system_id')),
                    'pancake_customer_name': customer_name,
                    'pancake_customer_phone': customer_phone,
                    'pancake_customer_fb_id': customer_info.get('fb_id'),
                    'pancake_shipping_full_name': sfn,
                    'pancake_shipping_phone': sp,
                    'pancake_shipping_address': s_addr,
                    'pancake_shipping_province': s_prov,
                    'pancake_shipping_district': s_dist,
                    'pancake_shipping_commune': s_comm,
                    'pancake_status_name': order_data.get('status_name'),
                    'pancake_status_key': p_status_key,
                    'pancake_updated_at': p_updated_at_dt or fields.Datetime.now(),
                    'pancake_order_source_name': order_data.get('order_sources_name'),
                    'pancake_page_name': p_page_name,
                    'pancake_order_link': order_data.get('link_confirm_order'),
                    'pancake_items_length': order_data.get('items_length'),
                    'pancake_total_quantity': order_data.get('total_quantity'),
                    'pancake_total_price': order_data.get('total_price'),
                    'pancake_total_discount_amount': order_data.get('total_discount'),
                    'pancake_shipping_fee': order_data.get('shipping_fee'),
                    'pancake_surcharge': order_data.get('surcharge'),
                    'pancake_money_to_collect': order_data.get('money_to_collect') or order_data.get('cod'),
                    'pancake_prepaid': order_data.get('prepaid'),
                    'pancake_order_currency_code': p_currency_code,
                    'pancake_note': order_data.get('note'),
                    'pancake_note_print': order_data.get('note_print'),
                    'pancake_customer_note': ", ".join(cn_note.get('content', '') for cn_note in customer_info.get('notes', [])) if customer_info.get('notes') else None,
                    'pancake_creator_name': p_creator_name,
                    'pancake_assigning_seller_name': p_assigning_seller_name,
                    'last_sync_date': fields.Datetime.now(),
                    'pancake_raw_data': str(order_data),
                }
                
                existing_order = self.search([('pancake_order_id', '=', p_order_id), ('company_id', '=', current_company_id)], limit=1)
                current_sale_order = False
                order_line_commands = [] # Khởi tạo ở đây để dùng cho cả create và write

                # --- Order Lines (sale.order.line) ---
                for item_data in order_data.get('items', []):
                    p_item_name = item_data.get('variation_info', {}).get('name')
                    p_item_sku = str(item_data.get('variation_info', {}).get('sku')) or \
                                 str(item_data.get('variation_info',{}).get('display_id')) or \
                                 str(item_data.get('variation_id')) # Ưu tiên SKU
                    p_item_qty = item_data.get('quantity', 0.0)
                    p_item_price = item_data.get('variation_info', {}).get('retail_price', 0.0)
                    p_item_discount_val = item_data.get('total_discount', 0.0)

                    product_variant = False
                    # Search product by SKU first, then by name
                    if p_item_sku and p_item_sku != 'None' and p_item_sku != '0': # 'None' hoặc '0' là string rỗng hoặc không có SKU
                        product_variant_domain = ([('default_code', '=', p_item_sku)] +company_domain)
                        product_variant = Product.search(product_variant_domain, limit=1)
                    
                    if not product_variant and p_item_name:
                        product_name_domain = ([('name', '=', p_item_name)]+company_domain)
                        product_variant = Product.search(product_name_domain, limit=1)
                    
                    if not product_variant and p_item_name: # Tạo mới nếu không tìm thấy
                        _logger.info(f"Creating new product {p_item_name} (SKU: {p_item_sku}) for Pancake order {p_order_id}")
                        try:
                            product_variant = Product.sudo().create({ # Sudo nếu user không có quyền tạo product
                                'name': p_item_name, 
                                'default_code': p_item_sku if (p_item_sku and p_item_sku != 'None' and p_item_sku != '0') else False,
                                'type': 'product', 'categ_id': self.env.ref('product.product_category_all').id,
                                'sale_ok': True, 'purchase_ok': False, 'lst_price': p_item_price,
                                'company_id': current_company_id if current_company_id else False,
                            })
                            _logger.info(f"Created product {product_variant.name} (SKU: {product_variant.default_code}) for order {p_order_id}")
                        except Exception as e_prod:
                            _logger.error(f"Failed to create product {p_item_name} (SKU: {p_item_sku}): {e_prod}")
                            product_variant = False # Set to False if creation failed
                    
                    if not product_variant:
                        _logger.warning(f"Product not found/created for Pancake item '{p_item_name}' (SKU: {p_item_sku}) in order {p_order_id}. Skipping line.")
                        continue

                    line_discount_percentage = 0.0
                    if p_item_price * p_item_qty > 0: # Tránh chia cho 0
                        line_discount_percentage = min(max((p_item_discount_val / (p_item_price * p_item_qty)) * 100, 0.0), 100.0)

                    line_vals = {
                        'product_id': product_variant.id,
                        'name': product_variant.get_product_multiline_description_sale(),
                        'product_uom_qty': p_item_qty,
                        'price_unit': p_item_price,
                        'discount': line_discount_percentage,
                        'product_uom': product_variant.uom_id.id,
                        'company_id': current_company_id if current_company_id else False,
                    }
                    order_line_commands.append(Command.create(line_vals))

                # --- Add Shipping Fee as Order Line ---
                p_shipping_fee = order_data.get('shipping_fee', 0.0)
                if p_shipping_fee > 0 and shipping_product:
                    order_line_commands.append(Command.create({
                        'product_id': shipping_product.id,
                        'name': shipping_product.name,
                        'product_uom_qty': 1,
                        'price_unit': p_shipping_fee,
                        'is_delivery': True,
                        'company_id': current_company_id if current_company_id else False,
                    }))

                # --- Add Surcharge as Order Line ---
                p_surcharge_val = order_data.get('surcharge', 0.0)
                if p_surcharge_val > 0 and surcharge_product:
                    order_line_commands.append(Command.create({
                        'product_id': surcharge_product.id,
                        'name': surcharge_product.name,
                        'product_uom_qty': 1,
                        'price_unit': p_surcharge_val,
                        'company_id': current_company_id if current_company_id else False,
                    }))

                if existing_order:
                    # Cập nhật thông tin chính của đơn hàng
                    existing_order.sudo().write(order_vals) 
                    # Xóa các dòng cũ và thêm các dòng mới
                    existing_order.order_line.sudo().unlink() 
                    if order_line_commands:
                        existing_order.sudo().write({'order_line': order_line_commands})
                    current_sale_order = existing_order
                    updated_count += 1
                    _logger.info(f"Updated SaleOrder Odoo ID: {current_sale_order.id} ({current_sale_order.name}) for Pancake Order ID: {p_order_id}")
                else:
                    order_vals['order_line'] = order_line_commands
                    current_sale_order = self.sudo().create(order_vals) 
                    created_count +=1
                    _logger.info(f"Created SaleOrder Odoo ID: {current_sale_order.id} ({current_sale_order.name}) for Pancake Order ID: {p_order_id}")
                
                # Logic chuyển trạng thái Odoo sau khi đồng bộ
                if current_sale_order:
                    try:
                        if odoo_state == 'sale' and current_sale_order.state == 'draft':
                            current_sale_order.sudo().action_confirm()
                            _logger.info(f"Confirmed SaleOrder {current_sale_order.name} based on Pancake status.")
                        elif odoo_state == 'done' and current_sale_order.state == 'sale':
                            # Nếu Odoo sale.order không có action_done trực tiếp, có thể cần confirm/validate invoice/delivery
                            # Tùy thuộc vào luồng nghiệp vụ của bạn. Ở đây chỉ là ví dụ.
                            # current_sale_order.sudo().action_done() 
                            _logger.info(f"SaleOrder {current_sale_order.name} is in 'sale' state and Pancake status is 'done'. Manual review may be needed to complete.")
                        elif odoo_state == 'cancel' and current_sale_order.state not in ['cancel', 'done']:
                            current_sale_order.sudo().action_cancel()
                            _logger.info(f"Cancelled SaleOrder {current_sale_order.name} based on Pancake status.")
                    except Exception as e_state_change:
                        _logger.error(f"Failed to change state of SaleOrder {current_sale_order.name}: {e_state_change}")

                processed_count += 1
                self.env.cr.commit() # Commit sau khi xử lý thành công một đơn hàng

            except Exception as e_outer:
                _logger.error(f"CRITICAL ERROR processing Pancake Order ID {p_order_id}: {e_outer}", exc_info=True)
                self.env.cr.rollback() # Rollback transaction của đơn hàng hiện tại nếu có lỗi
                error_count += 1
                continue # Chuyển sang đơn hàng tiếp theo

        sync_message = _('Pancake orders sync finished. Processed: %s, Created: %s, Updated: %s, Skipped: %s, Errors: %s') % \
                        (processed_count, created_count, updated_count, skipped_count, error_count)
        _logger.info(sync_message)
        
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Pancake Sync'), 'message': sync_message, 'sticky': False, 'type': 'success' if error_count == 0 else 'warning'}
        }

    @api.model
    def action_sync_single_pancake_order(self, order_data):
        """
        Processes a single order data dictionary from Pancake to create or update a Sale Order in Odoo.
        This method is ideal for webhook integrations.

        :param order_data: A dictionary containing the data for a single Pancake order.
        :return: A recordset of the created or updated 'sale.order'.
                Returns an empty recordset if the order is skipped or an error occurs.
        """
        _logger.info(f"Processing single Pancake order with ID: {order_data.get('id')}")

        # --- Pre-computation and Model Initialization ---
        Partner = self.env['res.partner']
        Product = self.env['product.product']
        CrmTag = self.env['crm.tag']
        ResUsers = self.env['res.users']
        ResCurrency = self.env['res.currency']
        CrmTeam = self.env['crm.team']
        SaleOrder = self.env['sale.order']

        status_mapping = self._get_pancake_status_to_odoo_state_mapping()

        # --- Company Context ---
        current_company_id = self.env.company.id if self.env.company else False
        company_domain = ['|', ('company_id', '=', False), ('company_id', '=', current_company_id)] if current_company_id else [('company_id', '=', False)]

        p_order_id = str(order_data.get('id'))
        if not p_order_id:
            _logger.warning("Skipping order with missing ID.")
            return SaleOrder
        
        # Bỏ qua đơn hàng nếu không có lịch sử trạng thái (đơn nháp, chưa hoàn chỉnh)
        if not order_data.get('status_history'):
            _logger.info(f"Skipping Pancake Order ID {p_order_id} due to empty status history.")
            return SaleOrder

        try:
            # --- 1. Find or Create Creator (res.users) ---
            creator_info = order_data.get('creator', {})
            odoo_creator = self.env.user # Default to current user
            if creator_info:
                creator_email = creator_info.get('email')
                creator_name = creator_info.get('name')
                if creator_email:
                    odoo_creator = ResUsers.sudo().search([('login', '=', creator_email)], limit=1)
                
                if not odoo_creator and creator_name:
                    # Logic để tạo người dùng mới có thể được thêm ở đây nếu cần
                    _logger.warning(f"Creator '{creator_name}' with email '{creator_email}' not found. Defaulting to current user.")

            # --- 2. Find or Create Salesperson (user_id) & Sales Team (team_id) ---
            assigning_seller_info = order_data.get('assigning_seller', {})
            p_assigning_seller_name = assigning_seller_info.get('name')
            user_id_val = self.env.user.id # Default
            salesperson = False
            
            if p_assigning_seller_name:
                salesperson = ResUsers.search([('name', '=ilike', p_assigning_seller_name), ('share', '=', False)], limit=1)

            if salesperson:
                user_id_val = salesperson.id

            final_team_id_val = self.env['crm.team']._get_default_team_id(user_id=user_id_val)

            # --- 3. Find or Create Customer (partner_id) ---
            customer_info = order_data.get('customer', {})
            partner = False
            customer_phone = (customer_info.get('phone_numbers') or [None])[0]
            customer_email = (customer_info.get('emails') or [None])[0]
            customer_name = customer_info.get('name')

            if not customer_name:
                _logger.error(f"Cannot process order {p_order_id}: Customer name is missing.")
                return SaleOrder

            if customer_phone:
                partner = Partner.search([('phone', '=', customer_phone)] + company_domain, limit=1)
            if not partner and customer_email:
                partner = Partner.search([('email', '=ilike', customer_email)] + company_domain, limit=1)

            if not partner:
                partner_vals = {
                    'name': customer_name,
                    'phone': customer_phone,
                    'email': customer_email,
                    'company_type': 'person',
                    'company_id': current_company_id,
                }
                partner = Partner.create(partner_vals)
                _logger.info(f"Created new partner: {partner.name} (ID: {partner.id}) for Pancake order {p_order_id}")
            
            # --- 4. Find or Create Shipping Address (partner_shipping_id) ---
            shipping_address_info = order_data.get('shipping_address', {})
            partner_shipping_id = partner.id # Default to customer
            sfn = shipping_address_info.get('full_name')
            sp = shipping_address_info.get('phone_number')
            s_addr = shipping_address_info.get('full_address')

            if sfn and (sfn != partner.name or sp != partner.phone):
                # Tìm địa chỉ giao hàng đã có
                shipping_contact = Partner.search([
                    ('parent_id', '=', partner.id),
                    ('type', '=', 'delivery'),
                    ('name', '=', sfn),
                    ('phone', '=', sp)
                ], limit=1)
                
                if not shipping_contact:
                    shipping_contact = Partner.create({
                        'name': sfn, 'parent_id': partner.id, 'type': 'delivery',
                        'phone': sp, 'street': s_addr,
                        'company_id': current_company_id,
                    })
                partner_shipping_id = shipping_contact.id

            # --- 5. Find or Create Pricelist ---
            p_currency_code = order_data.get('order_currency', 'VND')
            currency = ResCurrency.search([('name', '=', p_currency_code)], limit=1)
            currency_id_val = currency.id if currency else self.env.company.currency_id.id

            pricelist = self.env['product.pricelist'].search(
                [('currency_id', '=', currency_id_val)] + company_domain, 
                order='company_id desc, sequence, id', limit=1
            )
            if not pricelist:
                _logger.warning(f"Pricelist not found for currency {p_currency_code}. Creating a new one.")
                pricelist = self.env['product.pricelist'].sudo().create({
                    'name': f'Default {p_currency_code} Pricelist - {self.env.company.name if current_company_id else "Global"}',
                    'currency_id': currency_id_val,
                    'company_id': current_company_id,
                })
            pricelist_id_val = pricelist.id

            # --- 6. Prepare Order Lines ---
            order_line_commands = []
            for item_data in order_data.get('items', []):
                variation_info = item_data.get('variation_info', {})
                p_item_name = variation_info.get('name')
                p_item_sku = str(variation_info.get('sku') or variation_info.get('display_id')) or None
                
                product_variant = False
                if p_item_sku and p_item_sku != 'None':
                    product_variant = Product.search([('default_code', '=', p_item_sku)] + company_domain, limit=1)
                if not product_variant and p_item_name:
                    product_variant = Product.search([('name', '=', p_item_name)] + company_domain, limit=1)

                if not product_variant and p_item_name:
                    product_variant = Product.create({
                        'name': p_item_name,
                        'default_code': p_item_sku,
                        'type': 'product',
                        'sale_ok': True, 'purchase_ok': False,
                        'lst_price': variation_info.get('retail_price', 0.0),
                        'company_id': current_company_id,
                    })

                if product_variant:
                    order_line_commands.append((0, 0, {
                        'product_id': product_variant.id,
                        'name': product_variant.name,
                        'product_uom_qty': item_data.get('quantity', 0.0),
                        'price_unit': variation_info.get('retail_price', 0.0),
                    }))

            # --- 7. Prepare Main Order Values ---
            p_status_key = str(order_data.get('status'))
            odoo_state = status_mapping.get(p_status_key, 'draft')
            inserted_at_str = order_data.get('inserted_at', '').split('.')[0].replace('T', ' ')
            date_order = fields.Datetime.from_string(inserted_at_str) if inserted_at_str else fields.Datetime.now()
            
            customer_notes_list = [note.get('message', '') for note in customer_info.get('notes', [])]
            
            order_vals = {
                'pancake_order_id': p_order_id,
                'partner_id': partner.id,
                'partner_shipping_id': partner_shipping_id,
                'date_order': date_order,
                'state': odoo_state,
                'user_id': user_id_val,
                'team_id': final_team_id_val.id,
                'company_id': current_company_id,
                'pricelist_id': pricelist_id_val,
                'origin': f"Pancake: {p_order_id}",
                'note': order_data.get('note'),
                'client_order_ref': p_order_id,
                'order_line': order_line_commands,
                'pancake_customer_note': "\n".join(customer_notes_list),
                'pancake_status_name': order_data.get('status_name'),
                'pancake_status_key': p_status_key,
                'pancake_order_link': order_data.get('link_confirm_order'),
                'last_sync_date': fields.Datetime.now(),
                'pancake_raw_data': str(order_data),
            }

            # --- 8. Create or Update Sale Order ---
            existing_order = SaleOrder.search([('pancake_order_id', '=', p_order_id), ('company_id', '=', current_company_id)], limit=1)
            
            if existing_order:
                # Xóa các dòng cũ trước khi thêm dòng mới để tránh trùng lặp
                existing_order.order_line.unlink()
                existing_order.write(order_vals)
                current_sale_order = existing_order
                _logger.info(f"Updated SaleOrder Odoo ID: {current_sale_order.id} for Pancake Order ID: {p_order_id}")
            else:
                current_sale_order = SaleOrder.create(order_vals)
                _logger.info(f"Created SaleOrder Odoo ID: {current_sale_order.id} for Pancake Order ID: {p_order_id}")
            
            # --- 9. Final State Transition ---
            if odoo_state == 'sale' and current_sale_order.state == 'draft':
                current_sale_order.action_confirm()
            elif odoo_state == 'cancel' and current_sale_order.state not in ['cancel', 'done']:
                current_sale_order.action_cancel()

            self.env.cr.commit()
            return current_sale_order

        except Exception as e:
            _logger.error(f"CRITICAL ERROR processing Pancake Order ID {p_order_id}: {e}", exc_info=True)
            self.env.cr.rollback()
            return SaleOrder