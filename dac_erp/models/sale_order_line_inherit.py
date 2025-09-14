from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError
import logging

_logger = logging.getLogger(__name__)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    description = fields.Text(string='Nội dung')
    height = fields.Float(string='Chiều cao')
    width = fields.Float(string='Chiều ngang')

    def unlink(self):
        """Chỉ cho phép admin (base.group_system) xóa dòng sản phẩm sau khi đã xác nhận đặt cọc"""
        for line in self:
            if line.order_id:
                order = line.order_id
                # Nếu KHÔNG phải admin và đơn hàng đã xác nhận đặt cọc thì không cho xóa bất kỳ dòng nào
                if (not self.env.user.has_group('base.group_system') and order.is_deposit_confirmed):
                    raise AccessError(
                        "Không thể xóa dòng nào sau khi đã lên cọc!\n"
                        "Liên hệ quản trị viên để được hỗ trợ."
                    )
        return super().unlink()
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Nếu là dòng ghi chú (không sản phẩm, giá = 0, có tên, không display_type) thì gán là line_note
            if (not vals.get('product_id') and vals.get('name') and 
                not vals.get('display_type') and vals.get('price_unit', 0) == 0):
                vals['display_type'] = 'line_note'
                vals['product_uom_qty'] = 0
            # Nếu là dòng section (tùy ý, nếu bạn muốn giữ logic cũ)
            elif (not vals.get('product_id') and vals.get('name') and 
                  not vals.get('display_type') and vals.get('price_unit', 0) == 0 and 
                  ('mục' in vals.get('name', '').lower() or 'section' in vals.get('name', '').lower())):
                vals['display_type'] = 'line_section'
                vals['product_uom_qty'] = 0
            # Đảm bảo name không bị rỗng nếu là ghi chú/section
            if vals.get('display_type') and not vals.get('name'):
                vals['name'] = vals.get('display_type') == 'line_section' and 'Đầu mục' or 'Ghi chú'
        return super().create(vals_list)

    def write(self, vals):
        # Ngăn việc xóa display_type
        if 'display_type' in vals and not vals['display_type']:
            current_display_type = self.display_type
            if current_display_type in ('line_section', 'line_note'):
                vals.pop('display_type')
        return super().write(vals)

    @api.onchange('display_type')
    def _onchange_display_type(self):
        if self.display_type:
            self.product_id = False
            self.product_uom_qty = 0.0
            self.price_unit = 0.0
            self.product_uom = False


