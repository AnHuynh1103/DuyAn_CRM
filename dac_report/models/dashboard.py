from odoo import api, fields, models, _
from odoo.tools.misc import formatLang
import calendar
from datetime import datetime, timedelta

STATUS_COLOR_MAP = {
    'new': 'danger',      # đỏ
    'recontact': 'danger', # đỏ
    'waiting': 'warning', # vàng
    'done': 'success',    # xanh
    False: 'muted',
}

class SaleOrderDashboardService(models.Model):
    _inherit = "sale.order"

    def _dac_build_consulting_cards(self, limit=50):
        Conv = self.env['page.fm.conversation'].sudo()
        # Domain ví dụ: lấy theo hoạt động gần đây
        domain = [('last_message_sync_fm', '!=', False)]
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
                'title': c.display_name or c.name or '',
                'snippet': c.last_message_snippet or '',
                'note': c.suggestion_note or '',  # <— ƯU TIÊN suggestion từ AI/n8n
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
        quo_dom = [("state", "in", ("draft", "sent"))]
        sal_dom = [("state", "in", ("sale", "done"))]
        if has_custom:
            quo_dom = ["|"] + quo_dom + [("order_state_custom", "=", "quotation")]
            sal_dom = ["|"] + sal_dom + [("order_state_custom", "in", ["delivery", "payment"])]

        man_dom = [("order_state_custom", "=", "production")] if has_custom else []
        return {
            "consulting": [],
            "quotation": quo_dom,
            "sale_confirmed": sal_dom,
            "manufacturing": man_dom,
        }

    @api.model
    def _dashboard_expected_revenue(self, date_from, date_to, company):
        """Doanh thu dự kiến từ quotation."""
        dom = [
            ("company_id", "=", company.id),
            ("date_order", ">=", date_from),
            ("date_order", "<=", date_to),
            ("state", "in", ("draft", "sent")),
        ]
        orders = self.search(dom)
        return sum(orders.mapped("amount_total"))

    @api.model
    def _dashboard_month_goal(self, year, month, company):
        # Nếu bạn có override trong sales_goal.py thì giá trị thật sẽ được trả về từ đó.
        return 0.0

    @api.model
    def dac_get_dashboard(self, date_from=False, date_to=False, company_id=False):
        company = self.env["res.company"].browse(company_id) if company_id else self.env.company
        currency = company.currency_id
        today = fields.Date.context_today(self)
        if not date_from:
            date_from = today.replace(day=1)
        if not date_to:
            date_to = today

        fmt = lambda a: formatLang(self.env, a, currency_obj=currency)
        doms = self._dashboard_domains()

        # ---- QUOTATIONS ----
        q_dom = [
            ("company_id", "=", company.id),
            ("date_order", ">=", date_from),
            ("date_order", "<=", date_to),
        ] + doms["quotation"]
        quotation_amount = self._safe_sum_amount_total(q_dom)

        # ---- CONFIRMED/DONE ----
        s_dom = [
            ("company_id", "=", company.id),
            ("date_order", ">=", date_from),
            ("date_order", "<=", date_to),
        ] + doms["sale_confirmed"]
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
        
        quotes = self.search(q_dom, limit=10, order="date_order desc, id desc")
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
            orders = self.search(so_dom, limit=20, order="production_deadline asc, id asc")
            today_d = fields.Date.today()
            for so in orders:
                dln = getattr(so, "production_deadline", False)
                late_days = (today_d - dln).days if dln and dln < today_d else 0
                manuf_list.append({
                    "id": so.id,
                    "title": so.partner_id.display_name or so.name,
                    "deadline": dln and dln.isoformat(),
                    "late_days": late_days,
                })

        receivables = Move.search([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in", ["not_paid", "partial"]),
            ("company_id", "=", company.id),
        ], limit=5, order="invoice_date_due asc, id asc")
        receivables_list = [{
            "move_id": m.id,
            "partner": m.partner_id.display_name,
            "amount": fmt(m.amount_residual),
            "due_days": (fields.Date.today() - m.invoice_date_due).days if m.invoice_date_due else 0,
        } for m in receivables]

        recent = self.search(s_dom, limit=5, order="date_order desc")
        recent_list = [{
            "id": so.id,
            "name": so.partner_id.display_name,
            "amount": fmt(so.amount_total),
            "date": (so.date_order or fields.Datetime.now()).date().isoformat(),
        } for so in recent]

        # Tổng tiền cho 2 bảng dưới
        receivables_total_val = sum(m.amount_residual for m in receivables)
        recent_total_val      = sum(o.amount_total     for o in recent)
        sums = {
            "receivables_total": receivables_total_val,
            "receivables_total_str": fmt(receivables_total_val),
            "recent_total": recent_total_val,
            "recent_total_str": fmt(recent_total_val),
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

            },
            "lists": {
                "consulting": consulting_list,
                "quotation": quotation_list,
                "manufacturing": manuf_list,
                "receivables": receivables_list,
                "recent_customers": recent_list,
            },
            "sums": sums,  # <<< NEW
        }
