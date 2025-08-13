# -*- coding: utf-8 -*-

from odoo import models, fields, api

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_back_to_sale_order(self):
        """
        Quay về đơn hàng liên quan từ memo/communication
        """
        # Tìm đơn hàng từ memo field
        if self.memo:
            # Tìm invoice number trong memo (format: INV/2025/00074)
            invoice_parts = self.memo.split('/')
            if len(invoice_parts) >= 3 and invoice_parts[0] == 'INV':
                invoice_name = self.memo
                
                # Tìm invoice từ name
                invoice = self.env['account.move'].search([
                    ('name', '=', invoice_name),
                    ('move_type', 'in', ['out_invoice', 'out_refund'])
                ], limit=1)
                
                if invoice and invoice.invoice_origin:
                    # Tìm sale order từ invoice_origin
                    sale_order = self.env['sale.order'].search([
                        ('name', '=', invoice.invoice_origin)
                    ], limit=1)
                    
                    if sale_order:
                        return {
                            'type': 'ir.actions.act_window',
                            'name': 'Đơn hàng',
                            'view_mode': 'form',
                            'res_model': 'sale.order',
                            'res_id': sale_order.id,
                            'target': 'current',
                        }
        
        # Nếu không tìm thấy, hiển thị thông báo
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thông báo',
                'message': 'Không tìm thấy đơn hàng liên quan.',
                'type': 'warning',
            }
        }
