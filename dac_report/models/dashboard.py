from odoo import api, fields, models, _
from odoo.tools.misc import formatLang
from odoo.exceptions import AccessError
import calendar
from datetime import datetime, timedelta

STATUS_COLOR_MAP = {
    'new': 'danger',      # đỏ
    'recontact': 'danger', # đỏ
    'waiting': 'warning', # vàng
    'done': 'success',    # xám
    False: 'muted',
}

class SaleOrderDashboardService(models.Model):
    _inherit = "sale.order"

    def _dac_build_consulting_cards(self, limit=50):
        Conv = self.env['page.fm.conversation']  # bỏ sudo()

        # chỉ hiển thị hội thoại tôi phụ trách hoặc có tham gia
        my_dom = ['|', ('owner_id', '=', self.env.uid), ('participant_user_ids', 'in', self.env.uid)]

        # đã từng sync dữ liệu
        base_dom = [('last_message_sync_fm', '!=', False)]

        # Lọc 'done' > 2 ngày dựa vào last_processing_change_at
        cutoff = fields.Datetime.to_string(fields.Datetime.now() - timedelta(days=2))
        not_stale_done = ['|',
            ('status_state', '!=', 'done'),
            '&', 
            ('status_state', '=', 'done'), 
            '|',
            ('last_processing_change_at', '=', False),  # Không có thời điểm thay đổi -> hiển thị
            ('last_processing_change_at', '>=', cutoff),  # Thay đổi trong 2 ngày -> hiển thị
        ]

        # GHÉP DOMAIN CUỐI:
        domain = base_dom + my_dom + not_stale_done

        recs = Conv.search(domain, limit=limit, order='updated_at_fm desc')

        out = []
        for c in recs:
            color = STATUS_COLOR_MAP.get(c.status_state or False, 'muted')
            # Tạo status label
            status_labels = {
                'new': 'Có tin nhắn mới',
                'recontact': 'Chăm lại khách', 
                'waiting': 'Cần liên hệ lại',
                'done': 'Đã xử lý',
            }
            label = status_labels.get(c.status_state, '')
            
            out.append({
                'id': c.id,
                'title': getattr(c, 'customer_name_clean', None) or c.display_name or c.name or '',
                'snippet': getattr(c, 'last_message_snippet_clean', None) or c.last_message_snippet or '',
                'note': getattr(c, 'suggestion_note_clean', None) or c.suggestion_note or '',  # <— ƯU TIÊN suggestion từ AI/n8n
                'status_label': label,        # <— DÒNG TRẠNG THÁI
                'status_state': c.status_state,  # <— TRẠNG THÁI GỐC
                'status_color': color,        # <— MÀU: danger / warning / success
                'external_url': c.external_url or '',  # <— NÚT PANCAKE
                'checklist_ok': bool(getattr(c, 'checklist_ok', False)),
                'is_unread_fm': bool(getattr(c, 'is_unread_fm', False)),
                'require_processing': bool(getattr(c, 'require_processing', False)),
                'partner_name': c.partner_id.name if c.partner_id else '',
                'customer_name_fm': c.customer_name_fm or '',
            })
        return out

    # ---- helpers ----
    def _rg_count(self, model, domain, id_field="id"):
        rows = model.read_group(domain, [f"{id_field}:count"], [])
        if not rows:
            return 0
        row = rows[0]
        return row.get(f"{id_field}_count") or row.get("__count") or 0

    def _safe_sum_field(self, model, domain, field_name):
        """Cộng tổng 1 field bất kỳ (kể cả non-stored) bằng search + mapped."""
        recs = model.search(domain)
        return sum(recs.mapped(field_name))

    def _safe_sum_amount_total(self, domain):
        """Tổng amount_total cho sale.order (không dùng read_group)."""
        orders = self.search(domain)
        return sum(orders.mapped("amount_total"))

    @api.model
    def _dashboard_domains(self):
        # hỗ trợ state chuẩn + field tùy biến order_state_custom (nếu có)
        has_custom = "order_state_custom" in self._fields
        
        # QUOTATIONS - chỉ hiện đơn ở trạng thái báo giá và đặt cọc
        quo_dom = [("state", "in", ("draft", "sent"))]
        if has_custom:
            quo_dom = [("order_state_custom", "in", ["quotation", "deposit"])]

        # SALE CONFIRMED/DONE - bao gồm tất cả đơn đã xác nhận (sale/done) 
        # HOẶC các trạng thái tùy chỉnh từ production trở đi (chưa completed)
        sal_dom = [("state", "in", ("sale", "done"))]
        if has_custom:
            sal_dom = [
                "|",
                ("state", "in", ("sale", "done")),
                ("order_state_custom", "in", ["production", "delivery", "payment"])
            ]

        # MANUFACTURING - chỉ hiện đơn ở trạng thái sản xuất
        man_dom = []
        if has_custom:
            man_dom = [("order_state_custom", "=", "production")]
        
        # COMPLETED - chỉ hiện đơn ở trạng thái completed (thực sự hoàn thành)
        completed_dom = []
        if has_custom:
            completed_dom = [("order_state_custom", "=", "completed")]
        
        return {
            "consulting": [],
            "quotation": quo_dom,
            "sale_confirmed": sal_dom,
            "manufacturing": man_dom,
            "completed": completed_dom,
        }

    @api.model
    def _dashboard_expected_revenue(self, date_from, date_to, company):
        """Doanh thu dự kiến từ quotation."""
        doms = self._dashboard_domains()
        dom = [
            ("company_id", "=", company.id),
            ("date_order", ">=", date_from),
            ("date_order", "<=", date_to),
        ] + doms["quotation"]
        orders = self.search(dom)
        return sum(orders.mapped("amount_total"))

    @api.model
    def _dashboard_month_goal(self, year, month, company):
        """Lấy mục tiêu doanh thu tháng"""
        # Tìm mục tiêu trong sales_goal model
        Goal = self.env.get('dac_report.sales_goal')
        if Goal:
            goal = Goal.search([
                ('year', '=', year),
                ('month', '=', month),
                ('company_id', '=', company.id)
            ], limit=1)
            return goal.target_amount if goal else 0.0
        return 0.0

    

    @api.model
    def dac_get_dashboard(self, date_from=False, date_to=False, company_id=False):
        # Kiểm tra quyền xem Dashboard Sale
        user = self.env.user
        if not (user.has_group('dac_erp.group_dac_erp_manager') or 
                user.has_group('dac_erp.group_dac_erp_sale') or
                user.has_group('base.group_system')):
            raise AccessError(_("Bạn không có quyền truy cập dashboard này."))
        
        company = self.env["res.company"].browse(company_id) if company_id else self.env.company
        currency = company.currency_id
        today = fields.Date.context_today(self)
        manager = self.env.user.has_group('dac_erp.group_dac_erp_manager')
        user_name = self.env.user.name
        uid = self.env.uid
        if not date_from:
            date_from = today.replace(day=1)
        if not date_to:
            date_to = today

        fmt = lambda a: formatLang(self.env, a, currency_obj=currency)
        doms = self._dashboard_domains()

        # ---- QUOTATIONS ----
        q_dom = [
            ("company_id", "=", company.id),
            # ("date_order", ">=", date_from),
            # ("date_order", "<=", date_to),  <- Bỏ lọc ngày để hiển thị cả báo giá cũ chưa chốt
        ] + doms["quotation"]
        if not manager:
            q_dom.append(("user_id", "=", uid))              # <- cá nhân
        quotation_amount = self._safe_sum_amount_total(q_dom)

        # ---- CONFIRMED/DONE (doanh thu thực) ----
        # Bao gồm tất cả đơn đã xác nhận: state sale/done HOẶC các trạng thái tùy chỉnh đã xác nhận
        s_dom = [
            ("company_id", "=", company.id),
            ("date_order", ">=", date_from),
            ("date_order", "<=", date_to),
        ]
        # Thêm điều kiện state: tất cả đơn từ sale trở đi (bao gồm cả completed)
        if "order_state_custom" in self._fields:
            s_dom += [
                "|",
                ("state", "in", ("sale", "done")),
                ("order_state_custom", "in", ["production", "delivery", "payment", "completed"])
            ]
        else:
            s_dom += [("state", "in", ("sale", "done"))]
        
        if not manager:
            s_dom.append(("user_id", "=", uid))              # <- cá nhân
        
        total_revenue = self._safe_sum_amount_total(s_dom)
        closed_count = self._rg_count(self, s_dom, "id")

        # ---- EXPECTED (từ quotation) ----
        expected = self._dashboard_expected_revenue(date_from, date_to, company)

        # ---- INVOICES PAID (collected) ----
        Move = self.env["account.move"]
        mv_dom = [
            ("company_id", "=", company.id),
            ("state", "=", "posted"),
            ("move_type", "in", ["out_invoice", "out_receipt"]),
            ("invoice_date", ">=", date_from),
            ("invoice_date", "<=", date_to),
        ]
        if not manager:
            # lọc theo người phụ trách hóa đơn
            if "invoice_user_id" in Move._fields:
                mv_dom.append(("invoice_user_id", "=", uid))
            elif "dac_user_id" in Move._fields:
                mv_dom.append(("dac_user_id", "=", uid))
        field_to_sum = "amount_total_signed" if "amount_total_signed" in Move._fields else "amount_total"
        collected = self._safe_sum_field(Move, mv_dom, field_to_sum)

        # ---- KPI tiến độ ----
        year, month = date_from.year, date_from.month
        goal = self._dashboard_month_goal(year, month, company)
        progress_ratio = (total_revenue / goal) if goal else 0.0
        days_in_month = calendar.monthrange(year, month)[1]
        expected_ratio = min(date_to.day, days_in_month) / days_in_month
        delta_vs_expected = progress_ratio - expected_ratio

        # ---- Lists ----
        consulting_list = self._dac_build_consulting_cards(limit=20)
        
        quotes = self.search(q_dom, limit=30, order="date_order desc, id desc")
        quotation_list = [{
            "id": so.id,
            "title": so.partner_id.display_name,
            "amount": fmt(so.amount_total),
            "date": (so.date_order or fields.Datetime.now()).date().isoformat(),
            "has_unread": getattr(so, "message_needaction", False),
        } for so in quotes]

        manuf_list = []
        if doms.get("manufacturing"):
            so_dom = [("company_id", "=", company.id)] + doms["manufacturing"]
            # mới: thêm ưu tiên is_priority
            orders = self.search(
                so_dom,
                limit=20,
                order="is_priority_today desc, is_priority desc, production_deadline asc, id asc"
            )
            today_d = fields.Date.today()
            for so in orders:
                order_no = (so.order_number or False)  # Char hoặc False
                dln = getattr(so, "production_deadline", False)
                late_days = (today_d - dln).days if dln and dln < today_d else 0
                manuf_list.append({
                    "id": so.id,
                    "title": so.partner_id.display_name or so.name,
                    "deadline": dln and dln.isoformat(),
                    "late_days": late_days,
                    'order_no': order_no,
                    'order_no_label': order_no or _("Chưa có số ĐH"),
                    "has_order_no": bool(order_no),
                    "is_priority": bool(getattr(so, "is_priority", False)),
                    "is_priority_today": bool(getattr(so, "is_priority_today", False)),
                })

        # ---- COMPLETED CUSTOMERS ----
        completed_list = []
        completed_orders = self.env['sale.order']  # khởi tạo empty recordset
        if doms.get("completed"):
            comp_dom = [
                ("company_id", "=", company.id),
                # ("date_order", ">=", date_from),
                # ("date_order", "<=", date_to),
            ] + doms["completed"]
            if not manager:
                comp_dom.append(("user_id", "=", uid))
            
            completed_orders = self.search(comp_dom, limit=50, order="date_order desc")
            
            completed_list = [{
                "id": so.id,
                "name": so.partner_id.display_name,
                "amount": fmt(so.amount_total),
                "date": (so.date_order or fields.Datetime.now()).date().isoformat(),
            } for so in completed_orders[:5]]  # Chỉ lấy 5 đơn đầu

        # ---- CÔNG NỢ THỰC TẾ (hóa đơn chưa thanh toán) ----
        receivables_dom = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial']),
            ('company_id', '=', company.id),
        ]
        # chỉ xem công nợ của tôi nếu không phải quản lý
        if not manager and 'invoice_user_id' in Move._fields:
            receivables_dom.append(('invoice_user_id', '=', uid))

        receivables = Move.search(receivables_dom, limit=10, order='invoice_date_due asc, id asc')
        receivables_list = [{
            "move_id": m.id,
            "partner": m.partner_id.display_name,
            "amount": fmt(m.amount_residual),
            "due_days": (fields.Date.today() - m.invoice_date_due).days if m.invoice_date_due else 0,
            "source_type": "invoice",  # Đánh dấu từ hóa đơn
        } for m in receivables]

        # ---- CÔNG NỢ TỪ ĐƠN HÀNG CHƯA CÓ HÓA ĐƠN CUỐI (bước Thu tiền) ----
        if "order_state_custom" in self._fields:
            # Tìm đơn hàng ở trạng thái 'payment' nhưng chưa có hóa đơn cuối
            payment_orders_dom = [
                ("company_id", "=", company.id),
                ("order_state_custom", "=", "payment"),
                # Không cần kiểm tra state vì đơn ở bước payment có thể vẫn draft
            ]
            if not manager:
                payment_orders_dom.append(("user_id", "=", uid))

            payment_orders = self.search(payment_orders_dom)
            
            for order in payment_orders:
                # Kiểm tra xem đã có hóa đơn cuối ĐÃ XÁC NHẬN chưa (hóa đơn không phải cọc và đã posted)
                final_invoices = Move.search([
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_origin', '=', order.name),
                    ('dac_deposit_invoice', '=', False),  # Không phải hóa đơn cọc
                    ('state', '=', 'posted'),  # Chỉ tính hóa đơn đã xác nhận
                ])
                
                if not final_invoices:  # Chưa có hóa đơn cuối đã xác nhận
                    # Tính số tiền còn nợ
                    order_total = order.amount_total or order.amount_untaxed or 0
                    if hasattr(order, 'has_deposit') and order.has_deposit and hasattr(order, 'total_deposit_paid'):
                        # Có cọc: số tiền còn nợ = tổng đơn hàng - tiền cọc đã thanh toán
                        remaining_amount = order_total - (order.total_deposit_paid or 0)
                    else:
                        # Không cọc: số tiền còn nợ = toàn bộ đơn hàng
                        remaining_amount = order_total
                    
                    if remaining_amount > 0:  # Chỉ thêm nếu còn nợ
                        receivables_list.append({
                            "move_id": f"order_{order.id}",  # ID đặc biệt cho đơn hàng
                            "partner": order.partner_id.display_name,
                            "amount": fmt(remaining_amount),
                            "due_days": "no_invoice",  # Đánh dấu chưa có hóa đơn
                            "source_type": "order",  # Đánh dấu từ đơn hàng
                            "order_id": order.id,  # Để mở đơn hàng thay vì hóa đơn
                        })

        # Sắp xếp lại: hóa đơn trước (theo due date), sau đó đơn hàng chưa có hóa đơn
        receivables_list_invoices = [r for r in receivables_list if r.get("source_type") == "invoice"]
        receivables_list_orders = [r for r in receivables_list if r.get("source_type") == "order"]
        receivables_list = receivables_list_invoices + receivables_list_orders

        recent = self.search(s_dom, limit=5, order="date_order desc")
        recent_list = [{
            "id": so.id,
            "name": so.partner_id.display_name,
            "amount": fmt(so.amount_total),
            "date": (so.date_order or fields.Datetime.now()).date().isoformat(),
        } for so in recent]

        # Tổng tiền cho các bảng dưới
        receivables_total_val = sum(m.amount_residual for m in receivables)  # Từ hóa đơn
        # Cộng thêm tiền từ đơn hàng chưa có hóa đơn cuối
        if 'payment_orders' in locals():
            for order in payment_orders:
                final_invoices = Move.search([
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_origin', '=', order.name),
                    ('dac_deposit_invoice', '=', False),
                    ('state', '=', 'posted'),  # Chỉ tính hóa đơn đã xác nhận
                ])
                if not final_invoices:  # Chưa có hóa đơn cuối đã xác nhận
                    order_total = order.amount_total or order.amount_untaxed or 0
                    if hasattr(order, 'has_deposit') and order.has_deposit and hasattr(order, 'total_deposit_paid'):
                        remaining_amount = order_total - (order.total_deposit_paid or 0)
                    else:
                        remaining_amount = order_total
                    if remaining_amount > 0:
                        receivables_total_val += remaining_amount
            
        recent_total_val      = sum(o.amount_total     for o in recent)
        completed_total_val   = sum(o.amount_total     for o in completed_orders) if 'completed_orders' in locals() else 0
        sums = {
            "receivables_total": receivables_total_val,
            "receivables_total_str": fmt(receivables_total_val),
            "recent_total": recent_total_val,
            "recent_total_str": fmt(recent_total_val),
            "completed_total": completed_total_val,
            "completed_total_str": fmt(completed_total_val),
        }

        return {
            "header": {
                "month_target": fmt(goal),
                "current_revenue": fmt(total_revenue),
                "closed_orders": closed_count,
                "expected_revenue": fmt(expected),
                "progress_ratio": progress_ratio,
                "expected_ratio": expected_ratio,
                "delta_vs_expected": delta_vs_expected,
                # nếu cần hiển thị số tiền báo giá, có thể thêm:
                # "quotation_amount": fmt(quotation_amount),
                "is_manager": manager,

            },
            "lists": {
                "consulting": consulting_list,
                "quotation": quotation_list,
                "manufacturing": manuf_list,
                "receivables": receivables_list,
                "recent_customers": recent_list,
                "completed_customers": completed_list,
            },
            "sums": sums,  # Tổng tiền cho các bảng dưới
            "user_name": user_name, # Tên người dùng hiện tại
        }
