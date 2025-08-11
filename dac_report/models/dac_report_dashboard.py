# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, SUPERUSER_ID

_logger = logging.getLogger(__name__)

class DacReportDashboard(models.Model):
    _name = "dac.report.dashboard"
    _description = "DAC Simple Revenue Dashboard"
    _rec_name = "name"

    name = fields.Char(default="Báo cáo doanh thu", readonly=True)
    company_id  = fields.Many2one('res.company', default=lambda s: s.env.company, readonly=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)

    quote_amount    = fields.Monetary(currency_field="currency_id", compute="_compute_amounts")
    expected_amount = fields.Monetary(currency_field="currency_id", compute="_compute_amounts")
    total_amount    = fields.Monetary(currency_field="currency_id", compute="_compute_amounts")
    paid_amount     = fields.Monetary(currency_field="currency_id", compute="_compute_amounts")

    @api.depends()
    def _compute_amounts(self):
        company_id = self.env.company.id
        Sale = self.env["sale.order"].sudo().with_context(active_test=False)
        Pay  = self.env["account.payment"].sudo().with_context(active_test=False)

        def _sum(model, base_domain, field_name, label):
            domain = list(base_domain) + [("company_id", "=", company_id)]
            cnt = model.search_count(domain)
            rg  = model.read_group(domain, [f"{field_name}:sum"], [])
            val = (rg and rg[0].get(f"{field_name}_sum")) or 0.0
            #_logger.info("[DAC-REPORT] %s RG | cnt=%s val=%s", label, cnt, val)
            if cnt and (not rg or val in (None, 0.0)):
                val = sum(model.search(domain).mapped(field_name)) or 0.0
                #_logger.info("[DAC-REPORT] %s FB | val=%s", label, val)
            return val or 0.0

        dom_quote    = [("order_state_custom", "=", "quotation")]
        dom_expected = [("order_state_custom", "in", ("deposit", "production", "delivery")),
                        ("is_order_completed", "=", False)]
        dom_paid     = [("payment_type", "=", "inbound"), ("state", "in", ("posted", "paid"))]

        quote    = _sum(Sale, dom_quote,    "amount_total", "QUOTE")
        expected = _sum(Sale, dom_expected, "amount_total", "EXPECTED")
        paid     = _sum(Pay,  dom_paid,     "amount",       "PAID")

        for rec in self:
            rec.quote_amount    = quote
            rec.expected_amount = expected
            rec.paid_amount     = paid
            rec.total_amount    = expected + paid

            #_logger.info("[DAC-REPORT] FINAL | quote=%s expected=%s paid=%s total=%s",
            #              rec.quote_amount, rec.expected_amount, rec.paid_amount, rec.total_amount)

    # Smart buttons
    def action_open_quotes(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Báo giá",
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("order_state_custom", "=", "quotation"),
                       ("company_id", "=", self.env.company.id)],
            "target": "current",
        }

    def action_open_expected(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Đơn hàng (chưa thu tiền)",
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("order_state_custom", "in", ("deposit","production","delivery")),
                       ("is_order_completed","=", False),
                       ("company_id","=", self.env.company.id)],
            "target": "current",
        }

    def action_open_total(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Phiếu thu đã thanh toán",
            "res_model": "account.payment",
            "view_mode": "list,form",
            "domain": [("payment_type","=","inbound"),
                       ("state","in",("posted","paid")),
                       ("company_id","=", self.env.company.id)],
            "target": "current",
        }
