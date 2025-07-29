
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class Lead(models.Model):
    _inherit = 'crm.lead'

    # --- Trường tiền tệ liên quan đến công ty của Lead ---
    # Trường này sẽ được sử dụng bởi các trường Monetary khác trên model này.
    # company_id đã có sẵn trên crm.lead và có currency_id.
    lead_currency_id = fields.Many2one(
        related='company_id.currency_id',
        string="Lead Currency",
        readonly=True,
        store=True, # Store để có thể sử dụng trong domain hoặc group by nếu cần
        help="Đơn vị tiền tệ của công ty liên quan đến Tiềm năng này."
    )

    # --- Trường tùy chỉnh ---
    x_has_design_file = fields.Boolean(string="Có sẵn file Thiết kế")
    x_survey_required = fields.Boolean(string="Yêu cầu Khảo sát")

    # Liên kết tới dự án thiết kế/khảo sát
    x_design_project_id = fields.Many2one(
        'project.project',
        string="Dự án Thiết kế/Khảo sát",
        help="Dự án được tạo cho giai đoạn thiết kế hoặc khảo sát.",
        tracking=True,
        domain="[('x_project_type', '=', 'design')]" # Sử dụng x_project_type thay vì x_is_design_project
    )
    x_internal_quotation_received = fields.Boolean(string="Đã nhận Báo giá nội bộ", tracking=True, default=False)
    # Sửa currency_field để trỏ đến trường lead_currency_id vừa thêm
    x_internal_estimated_cost = fields.Monetary(
        string="Chi phí Thiết kế ước tính (Nội bộ)",
        currency_field='lead_currency_id', # SỬA Ở ĐÂY
        tracking=True
    )


    # --- Phương thức tùy chỉnh ---
    def action_create_design_project(self):
        """
        Tạo một Dự án Thiết kế/Khảo sát từ Tiềm năng (Lead/Opportunity).
        Hành động này được kích hoạt từ một nút trên form view của crm.lead.
        """
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Vui lòng chọn Khách hàng trước khi tạo Dự án Thiết kế."))

        project_vals = {
            'name': _('Thiết kế cho: %s') % self.name,
            'partner_id': self.partner_id.id,
            'user_id': self.user_id.id,
            'crm_lead_id': self.id,
            'allow_timesheets': True,
            'x_project_type': 'design', # Đánh dấu đây là dự án thiết kế
            'company_id': self.company_id.id if self.company_id else self.env.company.id, # Đảm bảo dự án có công ty
        }
        project = self.env['project.project'].create(project_vals)
        self.x_design_project_id = project.id

        task_name = ""
        if self.x_survey_required and not self.x_has_design_file: # Ưu tiên khảo sát nếu được chọn và chưa có file
            task_name = _("Khảo sát Thiết kế cho %s") % self.name
        elif self.x_has_design_file:
            task_name = _("Kiểm tra file Thiết kế cho %s") % self.name
        else: # Mặc định là tư vấn nếu không có lựa chọn rõ ràng hoặc chỉ yêu cầu khảo sát nhưng đã có file (trường hợp này ít xảy ra)
            task_name = _("Tư vấn & Lên Thiết kế Sơ bộ cho %s") % self.name


        if task_name:
            self.env['project.task'].create({
                'name': task_name,
                'project_id': project.id,
                'partner_id': self.partner_id.id,
                'user_ids': [(6, 0, [self.user_id.id])] if self.user_id else False,
            })

        # Chuyển giai đoạn của Lead
        stage_waiting_design = self.env.ref('DAC_CRM.stage_lead_waiting_design_survey', raise_if_not_found=False)
        if stage_waiting_design and self.stage_id != stage_waiting_design:
            self.stage_id = stage_waiting_design.id

        return {
            'type': 'ir.actions.act_window',
            'name': _('Dự án Thiết kế'),
            'res_model': 'project.project',
            'res_id': project.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_design_project(self):
        """Mở dự án thiết kế liên quan."""
        self.ensure_one()
        if not self.x_design_project_id:
            raise UserError(_("Không có Dự án Thiết kế nào được liên kết."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dự án Thiết kế'),
            'res_model': 'project.project',
            'res_id': self.x_design_project_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
