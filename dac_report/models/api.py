import logging
from datetime import datetime, timedelta
from odoo import api, models, fields

_logger = logging.getLogger(__name__)

class DacSaleDashboardApi(models.AbstractModel):
    _name = "dac.sale.dashboard.api"
    _description = "DAC Sale Dashboard - OWL API"

    @api.model
    def get_data(self, date_from=False, date_to=False, company_id=False):
        data = self.env["sale.order"].dac_get_dashboard(date_from, date_to, company_id)

        # ---- Gắn danh sách hội thoại “Đang tư vấn” ----
        try:
            Conv = self.env["page.fm.conversation"].sudo()

            # Lấy hội thoại chưa đọc trước rồi tới mới cập nhật gần đây (giới hạn để nhanh UI)
            threshold = fields.Datetime.to_string(datetime.utcnow() - timedelta(days=14))
            domain = [
                ("page_fm_page_id.active", "=", True),
                "|", ("is_unread_fm", "=", True),
                     ("updated_at_fm", ">=", threshold),
            ]
            convs = Conv.search(domain, order="is_unread_fm desc, updated_at_fm desc", limit=50)

            consulting = []
            for c in convs:
                title = c.partner_id.display_name or c.customer_name_fm or (c.name or c.conversation_fm_id)
                consulting.append({
                    "id": c.id,
                    "model": "page.fm.conversation",
                    "title": title,
                    "subtitle": (c.last_message_snippet or "").strip(),
                    "has_unread": bool(c.is_unread_fm),
                })

            data.setdefault("lists", {})
            data["lists"]["consulting"] = consulting
        except Exception as e:
            _logger.exception("Dashboard: cannot load Page.fm conversations: %s", e)

        return data

# (tùy chọn) alias giữ tương thích API cũ
class DacReportDashboardCompat(models.AbstractModel):
    _name = "dac.report.dashboard"
    _description = "DAC Dashboard API (compat)"

    @api.model
    def get_data(self, date_from=False, date_to=False, company_id=False):
        return self.env["dac.sale.dashboard.api"].get_data(date_from, date_to, company_id)
