from odoo import api, models

class DacSaleDashboardApi(models.AbstractModel):
    _name = "dac.sale.dashboard.api"
    _description = "DAC Sale Dashboard - OWL API"

    @api.model
    def get_data(self, date_from=False, date_to=False, company_id=False):
        return self.env["sale.order"].dac_get_dashboard(date_from, date_to, company_id)

# (tùy chọn) alias giữ tương thích API cũ
class DacReportDashboardCompat(models.AbstractModel):
    _name = "dac.report.dashboard"
    _description = "DAC Dashboard API (compat)"

    @api.model
    def get_data(self, date_from=False, date_to=False, company_id=False):
        return self.env["sale.order"].dac_get_dashboard(date_from, date_to, company_id)
