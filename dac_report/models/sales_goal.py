# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class DacSalesGoal(models.Model):
    _name = "dac.sales.goal"
    _description = "Sales Goal by User/Team per Month"
    _order = "year desc, month desc, goal_scope, team_id, user_id"
    _rec_name = "display_name"

    # Phạm vi
    goal_scope = fields.Selection(
        [("user", "Cá nhân"), ("team", "Phòng/Đội (Sales Team)")],
        string="Phạm vi", default="user", required=True,
        help="Chọn 'Cá nhân' cho 1 nhân viên; 'Phòng/Đội' cho 1 Sales Team."
    )
    user_id = fields.Many2one("res.users", string="Nhân viên", index=True)
    team_id = fields.Many2one("crm.team", string="Phòng/Đội", index=True)

    # Ngữ cảnh
    company_id = fields.Many2one(
        "res.company", string="Công ty", required=True,
        default=lambda s: s.env.company, index=True
    )
    year = fields.Integer(string="Năm", required=True, default=lambda s: fields.Date.today().year)
    month = fields.Selection([(str(m), str(m)) for m in range(1, 13)],
                             string="Tháng", required=True,
                             default=lambda s: str(fields.Date.today().month))

    # KPI chính & KPI đếm (chỉ nhập/hiển thị)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True, readonly=True)
    target_amount = fields.Monetary(string="Mục tiêu doanh thu", required=True,
                                    default=0.0, currency_field="currency_id")

    kpi_cared_count = fields.Integer(string="KH đã chăm sóc (mục tiêu)", default=0)
    kpi_quotation_count = fields.Integer(string="Số báo giá (mục tiêu)", default=0)
    kpi_closed_count = fields.Integer(string="Đơn đã chốt (mục tiêu)", default=0)
    kpi_completed_customer_count = fields.Integer(string="KH đã hoàn thành (mục tiêu)", default=0)

    # Trọng số
    weight_revenue   = fields.Float(string="Trọng số Doanh thu", default=1.0, digits=(16, 2))
    weight_cared     = fields.Float(string="Trọng số KH đã chăm sóc", default=1.0, digits=(16, 2))
    weight_quotation = fields.Float(string="Trọng số Báo giá",       default=1.0, digits=(16, 2))
    weight_closed    = fields.Float(string="Trọng số Đơn đã chốt",    default=1.0, digits=(16, 2))
    weight_completed = fields.Float(string="Trọng số KH hoàn thành",  default=1.0, digits=(16, 2))

    # Phân bổ thành viên (khi scope=team)
    member_line_ids = fields.One2many("dac.sales.goal.member", "goal_id", string="Phân bổ thành viên")

    # Khác
    active = fields.Boolean(default=True)
    note = fields.Char(string="Ghi chú")
    display_name = fields.Char(string="Tên hiển thị", compute="_compute_display_name", store=False)

    _sql_constraints = [
        ("uniq_goal_scope",
         "unique(goal_scope, user_id, team_id, company_id, year, month)",
         "Đã có mục tiêu cho thực thể này trong tháng/năm đó!"),
    ]

    @api.depends("goal_scope", "user_id", "team_id", "year", "month")
    def _compute_display_name(self):
        for r in self:
            who = r.user_id.name if r.goal_scope == "user" else (r.team_id.name or _("(Chưa chọn đội)"))
            scope = _("Cá nhân") if r.goal_scope == "user" else _("Phòng/Đội")
            r.display_name = f"{scope}: {who} - {r.month}/{r.year}"

    @api.constrains("goal_scope", "user_id", "team_id")
    def _check_scope_target(self):
        for r in self:
            if r.goal_scope == "user" and not r.user_id:
                raise ValidationError(_("Vui lòng chọn Nhân viên khi phạm vi là Cá nhân."))
            if r.goal_scope == "team" and not r.team_id:
                raise ValidationError(_("Vui lòng chọn Phòng/Đội khi phạm vi là Phòng/Đội."))

    # Giữ hook cũ để dashboard gọi (không đổi logic)
    @api.model
    def get_goal(self, user, company, year, month):
        rec = self.sudo().search([
            ("goal_scope", "=", "user"),
            ("user_id", "=", user.id),
            ("company_id", "=", company.id),
            ("year", "=", year),
            ("month", "=", str(month)),
            ("active", "=", True),
        ], limit=1)
        return rec.target_amount or 0.0


class DacSalesGoalMember(models.Model):
    _name = "dac.sales.goal.member"
    _description = "Member Allocation for Team Goal"
    _order = "id"

    goal_id = fields.Many2one("dac.sales.goal", string="Mục tiêu", required=True, ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", string="Thành viên", required=True, index=True)
    member_target_amount = fields.Monetary(string="Mục tiêu doanh thu (thành viên)",
                                           default=0.0, currency_field="currency_id")
    note = fields.Char(string="Ghi chú")

    currency_id = fields.Many2one(related="goal_id.currency_id", store=True, readonly=True)
    company_id  = fields.Many2one(related="goal_id.company_id",  store=True, readonly=True)

    _sql_constraints = [
        ("uniq_member_in_goal", "unique(goal_id, user_id)",
         "Một thành viên chỉ được khai báo một lần trong mục tiêu này!"),
    ]


# Giữ hook để dashboard sử dụng (không thay đổi)
class SaleOrderDashboardGoal(models.Model):
    _inherit = "sale.order"

    @api.model
    def _dashboard_month_goal(self, year, month, company):
        return self.env["dac.sales.goal"].sudo().get_goal(
            self.env.user, company, year, str(month)
        )
