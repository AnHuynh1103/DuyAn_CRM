from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError
import logging

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    # Thêm field người phụ trách để phân quyền
    dac_user_id = fields.Many2one('res.users', string='Người phụ trách', default=lambda self: self.env.user)

    @api.model_create_multi
    def create(self, vals_list):
        """Override create để gán người tạo phiếu thu làm người phụ trách"""
        for vals in vals_list:
            if not vals.get('dac_user_id'):
                vals['dac_user_id'] = self.env.user.id
        return super().create(vals_list)

    def unlink(self):
        """Kiểm tra quyền xóa phiếu thu - CHỈ ÁP DỤNG CHO SALES USERS"""
        for payment in self:
            # Nếu user là DAC sale (không phải manager hoặc admin) -> không cho xóa
            if (self.env.user.has_group('dac_erp.group_dac_erp_sale') and 
                not self.env.user.has_group('dac_erp.group_dac_erp_manager') and
                not self.env.user.has_group('base.group_system')):
                raise AccessError(
                    f"Bạn không có quyền xóa phiếu thu {payment.name}!\n"
                    "Liên hệ quản lý để được hỗ trợ."
                )
        
        return super().unlink()


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def action_create_payments(self):
        """Override để hook vào quá trình tạo payment và tự động cập nhật đơn hàng"""
        _logger.info("=== ENHANCED HOOK VÀO ACTION_CREATE_PAYMENTS ===")
        
        # DEBUGGING: Log tất cả thông tin context và data
        _logger.info(f"Context: {self.env.context}")
        _logger.info(f"Model fields: {list(self._fields.keys())}")
        
        # Lưu thông tin invoice trước khi tạo payment - NHIỀU CÁCH KHÁC NHAU
        related_orders = []
        
        # CÁCH MỚI: Sử dụng active_model và active_ids từ context
        if self.env.context.get('active_model') == 'account.move':
            active_ids = self.env.context.get('active_ids', [])
            _logger.info(f"ENHANCED: Using context active_ids: {active_ids}")
            
            for move_id in active_ids:
                move = self.env['account.move'].browse(move_id)
                if move.exists() and move.invoice_origin and move.move_type == 'out_invoice':
                    sale_order = self.env['sale.order'].search([('name', '=', move.invoice_origin)], limit=1)
                    if sale_order:
                        related_orders.append({
                            'order': sale_order,
                            'invoice': move,
                            'is_final_invoice': not move.dac_deposit_invoice
                        })
                        _logger.info(f"ENHANCED: Found order {sale_order.name} for invoice {move.name} (final: {not move.dac_deposit_invoice})")
        
        # CÁCH 1: Thử truy cập qua line_ids (method cũ) - fallback
        if not related_orders and hasattr(self, 'line_ids') and self.line_ids:
            _logger.info(f"ENHANCED: Fallback to line_ids method, found {len(self.line_ids)} line_ids")
            for move_line in self.line_ids:
                move = move_line.move_id
                if move.invoice_origin and move.move_type == 'out_invoice':
                    sale_order = self.env['sale.order'].search([('name', '=', move.invoice_origin)], limit=1)
                    if sale_order:
                        related_orders.append({
                            'order': sale_order,
                            'invoice': move,
                            'is_final_invoice': not move.dac_deposit_invoice
                        })
                        _logger.info(f"ENHANCED: Fallback found order {sale_order.name} for invoice {move.name} (final: {not move.dac_deposit_invoice})")
        
        if not related_orders:
            _logger.warning("ENHANCED: No related orders found!")
        
        # Gọi method gốc để tạo payment
        _logger.info("ENHANCED: Calling parent action_create_payments...")
        result = super().action_create_payments()
        _logger.info(f"ENHANCED: Parent result: {result}")
        
        # OPTIMIZED IMMEDIATE CHECK: Kiểm tra ngay sau khi tạo payment
        if related_orders:
            _logger.info("OPTIMIZED: Running immediate update check...")
            
            # BATCH PROCESSING: Group orders by type để tối ưu
            final_orders = []
            deposit_orders = []
            
            for order_info in related_orders:
                if order_info['is_final_invoice']:
                    final_orders.append(order_info)
                else:
                    deposit_orders.append(order_info)
            
            # Process final invoice orders
            for order_info in final_orders:
                order = order_info['order']
                invoice = order_info['invoice']
                
                try:
                    # SINGLE INVALIDATE và check
                    invoice.invalidate_recordset(['payment_state'])
                    invoice_fresh = self.env['account.move'].browse(invoice.id)
                    
                    if invoice_fresh.payment_state == 'paid':
                        _logger.info(f"OPTIMIZED: Final invoice {invoice_fresh.name} paid, updating order {order.name}")
                        
                        # CHỈ GỌI METHOD UPDATE - không compute thủ công
                        update_result = order.check_and_update_completion_status()
                        _logger.info(f"OPTIMIZED: Update result: {update_result}")
                        
                        # THAY ĐỔI RESULT để auto-reload form view
                        if isinstance(update_result, dict) and update_result.get('tag') == 'reload':
                            result = update_result
                        
                except Exception as e:
                    _logger.error(f"OPTIMIZED: Error in immediate update: {e}")
            
            # Process deposit orders (minimal processing needed)
            for order_info in deposit_orders:
                _logger.info(f"OPTIMIZED: Deposit invoice processing handled by write hook")
            
            # SINGLE COMMIT for all changes
            if final_orders or deposit_orders:
                self.env.cr.commit()
                _logger.info(f"OPTIMIZED: Single commit for {len(related_orders)} orders")
        else:
            _logger.warning("ENHANCED: No related orders found!")
        
        _logger.info("=== ENHANCED HOOK COMPLETED ===")
        return result
