from odoo import models, fields, api, _
from odoo.exceptions import UserError

class Task(models.Model):
    _inherit = 'project.task'

    # --- Trường tiền tệ liên quan đến công ty của Task ---
    # Trường này sẽ được sử dụng bởi các trường Monetary khác trên model này.
    # project_id.company_id.currency_id hoặc company_id.currency_id (task có company_id)
    task_currency_id = fields.Many2one(
        related='company_id.currency_id', # Lấy currency từ company của task
        string="Task Currency",
        readonly=True,
        store=True, # Store để có thể sử dụng trong domain hoặc group by nếu cần
        help="Đơn vị tiền tệ của công ty liên quan đến Công việc này."
    )

    # Thêm trường để lưu chi phí nội bộ từ thiết kế
    # Sửa currency_field để trỏ đến trường task_currency_id vừa thêm
    x_internal_estimated_cost = fields.Monetary(
        string="Chi phí Thiết kế ước tính (Nội bộ)",
        currency_field='task_currency_id' # SỬA Ở ĐÂY
    )
    x_design_notes_for_sale = fields.Text(string="Ghi chú Thiết kế cho Sales")

    def action_send_quotation_info_to_sale(self):
        """
        Hành động này được gọi từ một nút trên task thiết kế.
        Nó sẽ cập nhật thông tin trên CRM Lead/Opportunity liên quan.
        """
        self.ensure_one()
        if self.project_id.x_project_type != 'design':
            raise UserError(_("Hành động này chỉ dành cho các task thuộc Dự án Thiết kế."))

        if not self.project_id.crm_lead_id:
            raise UserError(_("Task này không được liên kết với một Tiềm năng/Cơ hội CRM nào."))

        crm_lead = self.project_id.crm_lead_id
        crm_lead.write({
            'x_internal_quotation_received': True,
            'x_internal_estimated_cost': self.x_internal_estimated_cost,
        })

        # Chuyển giai đoạn của task (ví dụ)
        # Cần tạo stage 'project_task_type_info_sent_to_sale' trong data file project_stage_data.xml
        # Ví dụ:
        # stage_info_sent = self.env.ref('DAC_CRM.project_task_type_design_info_sent', raise_if_not_found=False)
        # if stage_info_sent:
        #     self.stage_id = stage_info_sent.id # stage_id là đúng, không phải type_id

        # Tạo một activity cho người bán hàng trên CRM Lead
        if crm_lead.user_id:
            self.env['mail.activity'].create({
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'summary': _('Thông tin Thiết kế đã sẵn sàng để báo giá'),
                'note': _('Từ Dự án %s, Task %s: Chi phí ước tính %s %s. Ghi chú: %s') % (
                    self.project_id.name,
                    self.name,
                    self.x_internal_estimated_cost,
                    self.task_currency_id.symbol if self.task_currency_id else '', # Thêm ký hiệu tiền tệ
                    self.x_design_notes_for_sale or _("Không có")
                ),
                'res_id': crm_lead.id,
                'res_model_id': self.env['ir.model']._get('crm.lead').id,
                'user_id': crm_lead.user_id.id,
            })

        # Chuyển giai đoạn của CRM Lead sang "Sẵn sàng Báo giá Khách hàng"
        stage_ready_for_quotation = self.env.ref('DAC_CRM.stage_lead_ready_for_customer_quotation', raise_if_not_found=False)
        if stage_ready_for_quotation and crm_lead.stage_id != stage_ready_for_quotation:
            crm_lead.stage_id = stage_ready_for_quotation.id

        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('Thành công'),
            'message': _('Đã gửi thông tin thiết kế cho Sales.'),
            'type': 'success',
        }}