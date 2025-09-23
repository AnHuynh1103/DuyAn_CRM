from odoo import api, fields, models, _
from datetime import date as _date
from odoo.exceptions import AccessError

class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model
    def dac_get_dashboard_design(self):
        """
        Trả về danh sách đơn hàng đang sản xuất mà user hiện tại là user_id_design và user_id_production
        """
        uid = self.env.uid
        user = self.env.user

        if user.has_group("dac_erp.group_dac_erp_production"):
            domain = [("order_state_custom", "=", "production"),
                      ("user_id_production", "=", uid)]
        elif user.has_group("dac_erp.group_dac_erp_design"):
            domain = [("order_state_custom", "=", "production"),
                      ("user_id_design", "=", uid)]
        elif user.has_group("base.group_system"):
            # Admin: xem tất cả đơn đang sản xuất
            domain = [("order_state_custom", "=", "production")]
        else:
            # Không thuộc 2 group trên và không phải admin → chặn
            raise AccessError(_("Bạn không có quyền truy cập dashboard này."))

        orders = self.search(domain, order="is_priority_today desc, is_priority desc, production_deadline asc, id asc")

        today = _date.today()
        out = []
        for so in orders:
            deadline = so.production_deadline
            late_days = (today - deadline).days if deadline and today > deadline else 0
            out.append({
                "id": so.id,
                "title": so.partner_id.display_name or so.name,
                "amount": so.amount_total,
                "date": so.date_order,
                "deadline": deadline,
                "late_days": late_days,
                "is_priority": bool(getattr(so, "is_priority", False)),
                "is_priority_today": bool(getattr(so, "is_priority_today", False)),
            })
        return {
            "lists": {"manufacturing": out},
            "user_name": self.env.user.name,
        }