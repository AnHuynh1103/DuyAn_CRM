# DAC_CRM/models/project_project.py
# -*- coding: utf-8 -*-

from odoo import models, fields

class Project(models.Model):
    _inherit = 'project.project'

    # Trường x_is_design_project không còn cần thiết nếu dùng x_project_type
    # x_is_design_project = fields.Boolean(string="Là Dự án Thiết kế/Khảo sát", default=False)

    # Liên kết ngược lại CRM Lead/Opportunity
    crm_lead_id = fields.Many2one('crm.lead', string="Tiềm năng/Cơ hội liên quan", readonly=True, copy=False)
    # Liên kết với Đơn hàng (Sale Order) cho các dự án Sản xuất, Thi công
    sale_order_id = fields.Many2one('sale.order', string="Đơn hàng liên quan", readonly=True, copy=False)

    # Phân loại dự án để dễ dàng lọc và quản lý
    x_project_type = fields.Selection([
        ('design', 'Thiết kế & Khảo sát'),
        ('production', 'Sản xuất'),
        ('installation', 'Thi công & Lắp đặt')
    ], string="Loại Dự án", default='design', tracking=True, required=True)