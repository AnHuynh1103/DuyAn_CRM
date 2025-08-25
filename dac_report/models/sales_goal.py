from odoo import api, fields, models

class DacSalesGoal(models.Model):
    _name = "dac.sales.goal"
    _description = "Sales Goal by User/Month"
    _order = "year desc, month desc, user_id"

    user_id = fields.Many2one("res.users", string="Nhân viên", required=True, index=True)
    company_id = fields.Many2one("res.company", string="Công ty", required=True,
                                 default=lambda s: s.env.company, index=True)
    year = fields.Integer(string="Năm", required=True,
                          default=lambda s: fields.Date.today().year)
    month = fields.Selection([(str(m), str(m)) for m in range(1, 13)],
                             string="Tháng", required=True,
                             default=lambda s: str(fields.Date.today().month))
    target_amount = fields.Monetary(string="Mục tiêu", required=True, default=0.0,
                                    currency_field="currency_id")
    currency_id = fields.Many2one(related="company_id.currency_id", store=True, readonly=True)
    active = fields.Boolean(default=True)
    note = fields.Char(string="Ghi chú")

    _sql_constraints = [
        ("uniq_goal", "unique(user_id, company_id, year, month)",
         "Đã có mục tiêu cho nhân viên này trong tháng/năm đó!")
    ]

    @api.model
    def get_goal(self, user, company, year, month):
        rec = self.sudo().search([
            ("user_id", "=", user.id),
            ("company_id", "=", company.id),
            ("year", "=", year),
            ("month", "=", str(month)),
            ("active", "=", True),
        ], limit=1)
        return rec.target_amount or 0.0


# Hook để Dashboard lấy mục tiêu theo user hiện tại
class SaleOrderDashboardGoal(models.Model):
    _inherit = "sale.order"

    @api.model
    def _dashboard_month_goal(self, year, month, company):
        return self.env["dac.sales.goal"].sudo().get_goal(
            self.env.user, company, year, str(month)
        )