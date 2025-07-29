from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # company_id đã có sẵn trên sale.order, và currency_id cũng vậy (là currency của pricelist)
    # Không cần thêm trường currency_id riêng nếu dùng currency_id có sẵn của SO.

    x_design_project_id = fields.Many2one(
        'project.project',
        string="Dự án Thiết kế liên quan",
        tracking=True,
        domain="[('x_project_type', '=', 'design')]"
    )
    x_production_project_id = fields.Many2one(
        'project.project',
        string="Dự án Sản xuất",
        tracking=True,
        domain="[('x_project_type', '=', 'production')]"
        )
    x_installation_project_id = fields.Many2one(
        'project.project',
        string="Dự án Thi công",
        tracking=True,
        domain="[('x_project_type', '=', 'installation')]"
        )

    # Thông tin cọc
    x_deposit_invoice_ids = fields.Many2many(
        'account.move',
        string="Hóa đơn Cọc",
        copy=False,
        domain="[('move_type', '=', 'out_invoice'), ('state', '!=', 'cancel')]" # Chỉ hóa đơn khách hàng, không bị hủy
    )
    # currency_id của sale.order được dùng cho các trường monetary của nó
    x_deposit_amount_received = fields.Monetary(
        string="Số tiền cọc đã nhận",
        compute='_compute_deposit_received',
        currency_field='currency_id', # Sử dụng currency_id của sale.order
        store=True,
        tracking=True
    )
    x_is_deposit_fully_paid = fields.Boolean(
        string="Đã thanh toán đủ cọc",
        compute='_compute_deposit_received',
        store=True,
        tracking=True
    )


    @api.depends('x_deposit_invoice_ids.payment_state', 'x_deposit_invoice_ids.amount_total', 'x_deposit_invoice_ids.amount_residual')
    def _compute_deposit_received(self):
        for order in self:
            paid_amount = 0
            all_deposit_invoices_considered_paid = True if order.x_deposit_invoice_ids else False # Mặc định là True nếu không có HĐ cọc

            if not order.x_deposit_invoice_ids:
                order.x_deposit_amount_received = 0
                # Nếu không có hóa đơn cọc, coi như không yêu cầu cọc và đã "thanh toán"
                # Hoặc đặt False nếu quy trình luôn yêu cầu cọc (cần tạo hóa đơn cọc)
                order.x_is_deposit_fully_paid = True # Hoặc False tùy logic
                continue

            total_deposit_due = sum(inv.amount_total for inv in order.x_deposit_invoice_ids)

            for inv in order.x_deposit_invoice_ids.filtered(lambda i: i.state == 'posted'): # Chỉ xét hóa đơn đã vào sổ
                if inv.payment_state in ('paid', 'in_payment'):
                     paid_amount += inv.amount_total - inv.amount_residual
                else:
                    all_deposit_invoices_considered_paid = False # Nếu có bất kỳ HĐ cọc nào chưa paid/in_payment

            order.x_deposit_amount_received = paid_amount
            # Đủ cọc nếu tổng tiền nhận được >= tổng tiền cọc PHẢI THU và tất cả HĐ cọc đều đã paid/in_payment
            order.x_is_deposit_fully_paid = all_deposit_invoices_considered_paid and (paid_amount >= total_deposit_due if total_deposit_due > 0 else True)


    def action_create_production_request(self):
        self.ensure_one()
        if not self.x_is_deposit_fully_paid:
            raise UserError(_("Cần nhận đủ tiền cọc trước khi gửi yêu cầu sản xuất."))

        if self.x_production_project_id:
            raise UserError(_("Dự án Sản xuất đã được tạo cho đơn hàng này: %s") % self.x_production_project_id.name)

        project_vals = {
            'name': _('Sản xuất cho ĐH: %s') % self.name,
            'partner_id': self.partner_id.id,
            'sale_order_id': self.id,
            'allow_timesheets': True,
            'x_project_type': 'production',
            'user_id': self.user_id.id,
            'company_id': self.company_id.id, # Đảm bảo dự án có công ty
        }
        project = self.env['project.project'].create(project_vals)
        self.x_production_project_id = project.id

        if self.x_design_project_id:
            design_tasks = self.env['project.task'].search([('project_id', '=', self.x_design_project_id.id)])
            for dt in design_tasks:
                self.env['project.task'].create({
                    'name': _("SX: %s (từ TK %s)") % (dt.name, self.x_design_project_id.name),
                    'project_id': project.id,
                    'partner_id': self.partner_id.id,
                    'description': dt.description,
                    'user_ids': dt.user_ids,
                })
            for attachment in self.env['ir.attachment'].search([
                ('res_model', '=', 'project.project'),
                ('res_id', '=', self.x_design_project_id.id)
            ]):
                attachment.copy({'res_model': 'project.project', 'res_id': project.id})

        return {
            'type': 'ir.actions.act_window',
            'name': _('Dự án Sản xuất'),
            'res_model': 'project.project',
            'res_id': project.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_installation_request(self):
        self.ensure_one()
        if self.x_installation_project_id:
            raise UserError(_("Dự án Thi công đã được tạo cho đơn hàng này: %s") % self.x_installation_project_id.name)

        project_vals = {
            'name': _('Thi công cho ĐH: %s') % self.name,
            'partner_id': self.partner_id.id,
            'sale_order_id': self.id,
            'allow_timesheets': True,
            'x_project_type': 'installation',
            'user_id': self.user_id.id,
            'company_id': self.company_id.id, # Đảm bảo dự án có công ty
        }
        project = self.env['project.project'].create(project_vals)
        self.x_installation_project_id = project.id

        self.env['project.task'].create({
            'name': _("Chuẩn bị vật tư thi công cho %s") % self.name,
            'project_id': project.id,
            'partner_id': self.partner_id.id,
        })
        self.env['project.task'].create({
            'name': _("Thi công & Lắp đặt cho %s") % self.name,
            'project_id': project.id,
            'partner_id': self.partner_id.id,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Dự án Thi công'),
            'res_model': 'project.project',
            'res_id': project.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        for order in self:
            if order.opportunity_id and order.opportunity_id.x_design_project_id and not order.x_design_project_id:
                order.x_design_project_id = order.opportunity_id.x_design_project_id.id
        return res