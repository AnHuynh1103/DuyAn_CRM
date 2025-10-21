from odoo import api, fields, models, _
from datetime import date as _date, timedelta
from odoo.exceptions import AccessError

class SaleOrder(models.Model):
    _inherit = "sale.order"

    #Dashboard Design
    @api.model
    def dac_get_dashboard_design(self):
        """
        Payload cho Design Dashboard:
        - ToDo: quotation
        - Designing: deposit
        - Done (week): design_done trong 7 ngày gần nhất
        - Due soon: deadline - today in [0..2] trên Designing
        """
        uid = self.env.uid
        user = self.env.user

        # quyền xem
        if user.has_group("base.group_system"):
            base_domain = []
        elif user.has_group("dac_erp.group_dac_erp_design"):
            base_domain = [("user_id_design", "=", uid)]
        else:
            raise AccessError(_("Bạn không có quyền truy cập dashboard này."))

        today = _date.today()

        # ==== domain theo yêu cầu mới ====
        dom_todo       = base_domain + [("order_state_custom", "=", "quotation")]
        dom_designing  = base_domain + [("order_state_custom", "=", "deposit")]

        # ==== NEW: đơn CHƯA CÓ LINK THIẾT KẾ (deposit|production, chưa done) ====
        dom_missing_link = base_domain + [
            ("order_state_custom", "in", ["deposit", "production"]),
            ("design_done", "=", False),
            ("design_link", "=", False),
        ]

        # LOẠI đơn đã hoàn thành thiết kế khỏi 'Đang thiết kế'
        if "design_done" in self._fields:
            dom_designing += [("design_done", "=", False)]
        
        # done trong 7 ngày gần nhất (bấm "Hoàn thành" thiết kế)
        week_start     = today - timedelta(days=7)
        dom_done_week = base_domain + [
            ("order_state_custom", "in", ["deposit", "production"]),  # include 'production'
            ("write_date", ">=", week_start),
        ]
        if "design_done" in self._fields:
            dom_done_week += [("design_done", "=", True)]

        # query
        orders_todo = self.search(
            dom_todo,
            order="is_priority_today desc, is_priority desc, date asc",
        )
        orders_designing = self.search(
            dom_designing,
            order="is_priority_today desc, is_priority desc, design_deadline asc",
        )
        orders_missing = self.search(                           # NEW
            dom_missing_link,
            order="is_priority_today desc, is_priority desc, id desc",
        )
        # tránh trùng với cột Đang thiết kế (đơn deposit đang làm)
        if orders_designing:
            designing_ids = set(orders_designing.ids)
            orders_missing = orders_missing.filtered(lambda r: r.id not in designing_ids)

        # ---- ORDER: sắp xếp theo thời điểm hoàn thành (mới nhất trước)
        orders_done = self.search(
            dom_done_week,
            order="design_done_date desc, write_date desc, id desc"
        )
        done_week_count = self.search_count(dom_done_week)

        # helper: deadline mặc định (fallback khi chưa có trong DB)
        def _default_deadline(so):
            # Nếu đã có deadline thiết kế -> dùng luôn
            dl = getattr(so, "design_deadline", False)
            if dl:
                return dl
            # Fallback: có ngày phân công → base = ngày phân công
            base = getattr(so, "design_assigned_date", False)
            if base:
                return base if getattr(so, "is_priority_today", False) else (base + timedelta(days=3))
            return False

        # due soon?
        def _due_soon(so):
            dl = _default_deadline(so)
            if not dl:
                return False
            delta = (dl - today).days
            return 0 <= delta <= 2

        def _pack(so):
            dl = _default_deadline(so)
            today = _date.today()
            late_days = (today - dl).days if (dl and today > dl) else 0
            days_left = (dl - today).days if (dl and today <= dl) else False
            done_dt = getattr(so, "design_done_date", False)
            return {
                "id": so.id,
                # nếu chưa có số ĐH thì để False (để frontend hiển thị 'Chưa có số ĐH')
                "order_number": getattr(so, "order_number", False) or False,
                "title": so.partner_id.display_name or so.name,
                "customer": so.partner_id.display_name or "",
                "deadline": dl,                          # vẫn giữ để tính KPI
                "deadline_str": dl.strftime("%d/%m/%Y") if dl else False,
                "done_date_str": done_dt.strftime("%d/%m/%Y") if done_dt else False,
                "days_left": days_left,                  # << thêm
                "late_days": late_days,
                "is_priority": bool(getattr(so, "is_priority", False)),
                "is_priority_today": bool(getattr(so, "is_priority_today", False)),
            }

        designing_list = [_pack(so) for so in orders_designing]

        data = {
            "kpi": {
                "new_pending": len(orders_todo),
                "in_progress": len(designing_list),
                "missing_link": len(orders_missing),      # NEW
                "due_soon": sum(1 for it in designing_list if _due_soon(self.browse(it["id"]))),
                "done_week": int(done_week_count),
            },
            "lists": {
                "todo": [_pack(so) for so in orders_todo],
                "designing": designing_list,
                "missing_link": [_pack(so) for so in orders_missing],   # NEW
                "done":      [_pack(so) for so in orders_done],  # << thêm
            },
            "user_name": user.name,
        }
        return data
    
    
    
    #Dashboard Production
    @api.model
    def dac_get_dashboard_production(self):
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
                "order_number": (
                    getattr(so, 'order_number', None) or None
                ),
                "is_priority": bool(getattr(so, "is_priority", False)),
                "is_priority_today": bool(getattr(so, "is_priority_today", False)),
            })
        return {
            "lists": {"manufacturing": out},
            "user_name": self.env.user.name,
        }