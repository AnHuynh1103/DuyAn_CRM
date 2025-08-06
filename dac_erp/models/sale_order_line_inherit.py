from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError
import logging

_logger = logging.getLogger(__name__)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    description = fields.Text(string='Nội dung')
    height = fields.Float(string='Chiều cao')
    immediately = fields.Boolean(string='Giao ngay', default=True)

    def unlink(self):
        """Kiểm tra quyền xóa dòng sản phẩm"""
        for line in self:
            # Chỉ kiểm tra với dòng sản phẩm thực (không phải section/note)
            if not line.display_type and line.product_id and line.order_id:
                order = line.order_id
                
                # Nếu user là sale và đơn hàng đã xác nhận báo giá -> không cho xóa
                if (self.env.user.has_group('sales_team.group_sale_salesman') and 
                    not self.env.user.has_group('sales_team.group_sale_manager') and
                    order.is_quotation_confirmed):
                    raise AccessError(
                        "Không thể xóa sản phẩm sau khi đã xác nhận báo giá!\n"
                        "Liên hệ quản lý để được hỗ trợ."
                    )
        
        return super().unlink()
    
    @api.model_create_multi
    def create(self, vals_list):
        _logger.info(f"---------------------------->Creating sale.order.line with values: {vals_list}")
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
        _logger.info(f"---------------------------->Writing sale.order.line with values: {vals}")
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


