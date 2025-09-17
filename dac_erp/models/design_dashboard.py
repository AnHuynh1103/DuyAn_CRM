from odoo import api, fields, models

class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model
    def dac_get_dashboard_design(self):
        """
        Trả về danh sách đơn hàng đang sản xuất mà user hiện tại là user_id_design
        """
        user_id = self.env.uid
        # Lọc các đơn hàng có trạng thái sản xuất (production) và user_id_design là user hiện tại
        domain = [
            ("order_state_custom", "=", "production"),
            ("user_id_design", "=", user_id),
        ]
        orders = self.search(domain, order="date_order desc")
        result = []
        for so in orders:
            result.append({
                "id": so.id,
                "title": so.partner_id.display_name or so.name,
                "amount": so.amount_total,
                "date": so.date_order,
                "late_days": (fields.Date.today() - so.commitment_date).days if so.commitment_date and fields.Date.today() > so.commitment_date else 0,
                "user_id_design": [so.user_id_design.id, so.user_id_design.name] if so.user_id_design else None,
            })
        return {"manufacturing": result}