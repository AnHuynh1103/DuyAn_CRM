from odoo import api, fields, models

class DacSalesGoal(models.Model):
    _name = "dac.sales.goal"
    _description = "Sales Goal by Month"
    _order = "year desc, month desc, id desc"

    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    year = fields.Integer(required=True)
    month = fields.Selection([(str(m), str(m)) for m in range(1, 13)], required=True)
    revenue_target = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    active = fields.Boolean(default=True)

# hook vào service
class SaleOrderDashboardGoal(models.Model):
    _inherit = "sale.order"

    @api.model
    def _dashboard_month_goal(self, year, month, company):
        goal = self.env["dac.sales.goal"].sudo().search([
            ("company_id", "=", company.id),
            ("year", "=", year),
            ("month", "=", str(month)),
            ("active", "=", True),
        ], limit=1)
        return goal.revenue_target or 0.0
