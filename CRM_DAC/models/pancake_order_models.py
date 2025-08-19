# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError
import requests # Cần cài đặt thư viện requests: pip install requests
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

class PancakeOrderStatus(models.Model):
    _name = 'pancake.order.status'
    _description = 'Pancake Order Status Mapping'

    pancake_status_key = fields.Char(string='Pancake Status Key', required=True, index=True)
    name = fields.Char(string='Pancake Status Name', required=True)
    # Tùy chọn: Ánh xạ sang trạng thái Sale Order của Odoo nếu cần
    # sale_order_state = fields.Selection([
    #     ('draft', 'Quotation'),
    #     ('sent', 'Quotation Sent'),
    #     ('sale', 'Sales Order'),
    #     ('done', 'Locked'),
    #     ('cancel', 'Cancelled'),
    # ], string='Odoo Sale Order State')

    _sql_constraints = [
        ('pancake_status_key_unique', 'unique(pancake_status_key)', 'Pancake Status Key must be unique!')
    ]

class PancakeOrderTag(models.Model):
    _name = 'pancake.order.tag'
    _description = 'Pancake Order Tag'

    pancake_tag_id = fields.Integer(string='Pancake Tag ID', required=True, index=True)
    name = fields.Char(string='Tag Name', required=True)

    _sql_constraints = [
        ('pancake_tag_id_unique', 'unique(pancake_tag_id)', 'Pancake Tag ID must be unique!')
    ]

class PancakeOrder(models.Model):
    # _inherit = 'sale.order'  # Kế thừa từ sale.order để tận dụng các tính năng của Odoo Sale Order
    _name = 'pancake.order'
    _description = 'Pancake Order'
    _order = 'pancake_inserted_at desc'

    name = fields.Char(string='Pancake Order Reference', compute='_compute_name', store=True, index=True)
    pancake_order_id = fields.Char(string='Pancake Order ID', required=True, index=True, copy=False) # Từ API 'id' hoặc 'system_id'
    pancake_system_id = fields.Char(string='Pancake System ID', index=True, copy=False)

    # --- Thông tin khách hàng ---
    partner_id = fields.Many2one('res.partner', string='Khách hàng (Odoo)', ondelete='restrict')
    pancake_customer_name = fields.Char(string='Tên KH (Pancake)')
    pancake_customer_phone = fields.Char(string='SĐT KH (Pancake)')
    pancake_customer_fb_id = fields.Char(string='Facebook ID KH (Pancake)')
    pancake_shipping_full_name = fields.Char(string='Tên người nhận (GH)')
    pancake_shipping_phone = fields.Char(string='SĐT người nhận (GH)')
    pancake_shipping_address = fields.Text(string='Địa chỉ GH (Pancake)')
    pancake_shipping_province = fields.Char(string='Tỉnh/Thành GH (Pancake)')
    pancake_shipping_district = fields.Char(string='Quận/Huyện GH (Pancake)')
    pancake_shipping_commune = fields.Char(string='Phường/Xã GH (Pancake)')

    # --- Thông tin đơn hàng ---
    pancake_status_name = fields.Char(string='Trạng thái (Pancake Name)') # status_name từ API
    pancake_status_key = fields.Char(string='Trạng thái (Pancake Key)')   # status (số) từ API
    # pancake_order_status_id = fields.Many2one('pancake.order.status', string='Trạng thái ĐH Pancake',
    #                                           compute='_compute_pancake_order_status', store=True)


    pancake_inserted_at = fields.Datetime(string='Ngày tạo (Pancake)')
    pancake_updated_at = fields.Datetime(string='Ngày cập nhật (Pancake)')
    pancake_order_source_name = fields.Char(string='Nguồn đơn (Pancake)')
    pancake_page_name = fields.Char(string='Trang bán hàng (Pancake)') # page.name
    pancake_order_link = fields.Char(string='Link đơn hàng (Pancake)') # order_link

    # --- Thông tin sản phẩm & Thanh toán ---
    line_ids = fields.One2many('pancake.order.line', 'order_id', string='Chi tiết đơn hàng')
    pancake_items_length = fields.Integer(string='Số loại SP (Pancake)')
    pancake_total_quantity = fields.Float(string='Tổng SL SP (Pancake)')

    pancake_total_price = fields.Float(string='Tổng tiền hàng (Pancake)') # total_price
    pancake_total_discount = fields.Float(string='Tổng giảm giá (Pancake)') # total_discount
    pancake_shipping_fee = fields.Float(string='Phí vận chuyển (Pancake)') # shipping_fee
    pancake_surcharge = fields.Float(string='Phụ phí (Pancake)') # surcharge
    pancake_money_to_collect = fields.Float(string='Tiền cần thu (Pancake)') # money_to_collect / cod
    pancake_prepaid = fields.Float(string='Đã trả trước (Pancake)') # prepaid
    pancake_order_currency = fields.Char(string='Tiền tệ (Pancake)', default='VND') # order_currency

    # --- Ghi chú & Tags ---
    pancake_note = fields.Text(string='Ghi chú ĐH (Pancake)') # note
    pancake_note_print = fields.Text(string='Ghi chú in (Pancake)') # note_print
    pancake_customer_note = fields.Text(string='Ghi chú KH (Pancake)') # customer.notes (cần xử lý)
    tag_ids = fields.Many2many('pancake.order.tag', string='Tags (Pancake)')

    # --- Nhân viên & Phân công (Lưu dạng text, có thể map sang res.users nếu cần) ---
    pancake_creator_name = fields.Char(string='Người tạo ĐH (Pancake)') # creator.name
    pancake_assigning_seller_name = fields.Char(string='NV bán hàng (Pancake)') # assigning_seller.name
    # user_id = fields.Many2one('res.users', string='NV bán hàng (Odoo)') # Để map sau

    # --- Thông tin kỹ thuật ---
    last_sync_date = fields.Datetime(string='Ngày đồng bộ cuối', readonly=True)
    pancake_raw_data = fields.Text(string="Dữ liệu thô JSON", readonly=True, copy=False) # Để debug

    _sql_constraints = [
        ('pancake_order_id_uniq', 'unique(pancake_order_id)', 'Pancake Order ID must be unique!')
    ]

    @api.depends('pancake_order_id', 'pancake_customer_name')
    def _compute_name(self):
        for order in self:
            name = order.pancake_order_id or 'N/A'
            if order.pancake_customer_name:
                name = f"{name} - {order.pancake_customer_name}"
            order.name = name

    # @api.depends('pancake_status_key')
    # def _compute_pancake_order_status(self):
    #     for order in self:
    #         if order.pancake_status_key:
    #             status = self.env['pancake.order.status'].search([('pancake_status_key', '=', order.pancake_status_key)], limit=1)
    #             order.pancake_order_status_id = status.id
    #         else:
    #             order.pancake_order_status_id = False

    def _get_pancake_api_key(self):
        api_key = self.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
        if not api_key:
            raise UserError(_("Pancake API Key is not configured in System Parameters (pancake.api_key)."))
        return api_key

    def _get_pancake_shop_id(self):
        shop_id = self.env['ir.config_parameter'].sudo().get_param('pancake.shop_id')
        if not shop_id:
            # Mặc định là shop_id bạn cung cấp, nhưng nên cấu hình
            _logger.warning("Pancake Shop ID is not configured in System Parameters (pancake.shop_id). Using default 714233235.")
            return "714233235"
        return shop_id

    def action_sync_pancake_orders(self):
        _logger.info("Starting Pancake orders synchronization...")
        api_key = self._get_pancake_api_key()
        shop_id = self._get_pancake_shop_id()
        
        # API endpoint - bạn có thể thêm các tham số khác như limit, page, date_from, date_to
        # Ví dụ: &limit=100&page=1&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
        # Hiện tại, API của bạn không có các tham số này trong ví dụ, cần kiểm tra tài liệu API Pancake
        api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/orders?api_key={api_key}"

        try:
            _logger.info(f"Calling Pancake API: {api_url.replace(api_key, '***REDACTED***')}")
            response = requests.get(api_url, timeout=60) # timeout 60 giây
            response.raise_for_status()  # Ném lỗi nếu HTTP status code là 4xx hoặc 5xx
            data = response.json()
        except requests.exceptions.RequestException as e:
            _logger.error(f"API call failed: {e}")
            raise UserError(_("Failed to connect to Pancake API: %s") % e)
        except ValueError as e: # JSONDecodeError kế thừa từ ValueError
            _logger.error(f"Failed to decode JSON response: {e}")
            _logger.error(f"Response text: {response.text[:500]}") # Log một phần response text để debug
            raise UserError(_("Failed to parse response from Pancake API: %s") % e)

        orders_data = data.get('data', [])
        aggs_data = data.get('aggs', {}) # Có thể lưu thông tin tổng hợp này nếu cần

        if not orders_data:
            _logger.info("No orders found in the API response.")
            # Có thể hiển thị thông báo cho người dùng
            return True

        Partner = self.env['res.partner']
        Product = self.env['product.product']
        PancakeOrderLine = self.env['pancake.order.line']
        PancakeTag = self.env['pancake.order.tag']

        processed_count = 0
        created_count = 0
        updated_count = 0

        for order_data in orders_data:
            p_order_id = str(order_data.get('id'))
            if not p_order_id:
                _logger.warning(f"Skipping order with missing ID: {order_data}")
                continue

            existing_order = self.search([('pancake_order_id', '=', p_order_id)], limit=1)
            
            # --- Xử lý Khách hàng (res.partner) ---
            customer_info = order_data.get('customer', {})
            partner = False
            customer_phone = (customer_info.get('phone_numbers') or [None])[0]
            customer_email = (customer_info.get('emails') or [None])[0] # Giả sử email đầu tiên

            if customer_phone: # Ưu tiên tìm theo SĐT
                partner = Partner.search([('phone', '=', customer_phone)], limit=1)
            if not partner and customer_email: # Nếu không thấy, tìm theo email
                partner = Partner.search([('email', '=', customer_email)], limit=1)
            
            # Tạo khách hàng mới nếu không tìm thấy và có thông tin cần thiết
            if not partner and customer_info.get('name') and (customer_phone or customer_email):
                partner_vals = {
                    'name': customer_info.get('name'),
                    'phone': customer_phone,
                    'email': customer_email,
                    'company_type': 'person',
                    # Thêm các trường khác nếu có từ API: street, city, country_id, ...
                    # 'pancake_fb_id': customer_info.get('fb_id') # Có thể thêm trường này vào res.partner
                }
                try:
                    partner = Partner.create(partner_vals)
                    _logger.info(f"Created new partner: {partner.name} (ID: {partner.id}) for Pancake order {p_order_id}")
                except Exception as e:
                    _logger.error(f"Failed to create partner for Pancake order {p_order_id}: {e}")


            # --- Xử lý Tags ---
            tag_ids_to_link = []
            for tag_data in order_data.get('tags', []):
                p_tag_id = tag_data.get('id')
                p_tag_name = tag_data.get('name')
                if p_tag_id and p_tag_name:
                    tag = PancakeTag.search([('pancake_tag_id', '=', p_tag_id)], limit=1)
                    if not tag:
                        try:
                            tag = PancakeTag.create({'pancake_tag_id': p_tag_id, 'name': p_tag_name})
                        except Exception as e:
                            _logger.error(f"Failed to create tag {p_tag_name} (ID: {p_tag_id}): {e}")
                            continue
                    tag_ids_to_link.append(tag.id)


            order_vals = {
                'pancake_order_id': p_order_id,
                'pancake_system_id': str(order_data.get('system_id')),
                'partner_id': partner.id if partner else False,
                'pancake_customer_name': customer_info.get('name'),
                'pancake_customer_phone': customer_phone,
                'pancake_customer_fb_id': customer_info.get('fb_id'),
                
                'pancake_shipping_full_name': order_data.get('shipping_address', {}).get('full_name'),
                'pancake_shipping_phone': order_data.get('shipping_address', {}).get('phone_number'),
                'pancake_shipping_address': order_data.get('shipping_address', {}).get('full_address'),
                'pancake_shipping_province': order_data.get('shipping_address', {}).get('province_name'),
                'pancake_shipping_district': order_data.get('shipping_address', {}).get('district_name'),
                'pancake_shipping_commune': order_data.get('shipping_address', {}).get('commune_name') or order_data.get('shipping_address', {}).get('commnue_name'), # Chú ý lỗi chính tả "commnue_name"

                'pancake_status_name': order_data.get('status_name'),
                'pancake_status_key': str(order_data.get('status')),
                'pancake_inserted_at': order_data.get('inserted_at'),
                'pancake_updated_at': order_data.get('updated_at'),
                'pancake_order_source_name': order_data.get('order_sources_name'),
                'pancake_page_name': order_data.get('page', {}).get('name'),
                'pancake_order_link': order_data.get('order_link'),

                'pancake_items_length': order_data.get('items_length'),
                'pancake_total_quantity': order_data.get('total_quantity'),
                'pancake_total_price': order_data.get('total_price'),
                'pancake_total_discount': order_data.get('total_discount'),
                'pancake_shipping_fee': order_data.get('shipping_fee'),
                'pancake_surcharge': order_data.get('surcharge'),
                'pancake_money_to_collect': order_data.get('money_to_collect') or order_data.get('cod'),
                'pancake_prepaid': order_data.get('prepaid'),
                'pancake_order_currency': order_data.get('order_currency'),

                'pancake_note': order_data.get('note'),
                'pancake_note_print': order_data.get('note_print'),
                'pancake_customer_note': ", ".join(note.get('content', '') for note in customer_info.get('notes', [])) if customer_info.get('notes') else None, # Ví dụ xử lý customer notes
                'tag_ids': [(6, 0, tag_ids_to_link)] if tag_ids_to_link else False,

                'pancake_creator_name': order_data.get('creator', {}).get('name'),
                'pancake_assigning_seller_name': order_data.get('assigning_seller', {}).get('name'),
                'last_sync_date': fields.Datetime.now(),
                'pancake_raw_data': str(order_data), # Lưu trữ dữ liệu thô
            }

            if existing_order:
                try:
                    existing_order.write(order_vals)
                    updated_count += 1
                    # Xóa các line cũ trước khi thêm line mới để tránh trùng lặp
                    existing_order.line_ids.unlink()
                    current_order_for_lines = existing_order
                except Exception as e:
                    _logger.error(f"Failed to update Pancake order {p_order_id}: {e}")
                    self.env.cr.rollback() # Rollback transaction cho đơn hàng này
                    continue 
            else:
                try:
                    current_order_for_lines = self.create(order_vals)
                    created_count +=1
                except Exception as e:
                    _logger.error(f"Failed to create Pancake order {p_order_id}: {e}")
                    self.env.cr.rollback()
                    continue
            
            # --- Xử lý Chi tiết đơn hàng (pancake.order.line) ---
            line_vals_list = []
            for item_data in order_data.get('items', []):
                product_name = item_data.get('variation_info', {}).get('name')
                product = False
                if product_name: # Cố gắng tìm sản phẩm trong Odoo theo tên
                    # Đây là cách tìm đơn giản, bạn có thể cần logic phức tạp hơn (ví dụ: theo mã SKU nếu có)
                    product = Product.search([('name', '=', product_name)], limit=1) 
                
                line_vals = {
                    'order_id': current_order_for_lines.id,
                    'pancake_product_name': product_name,
                    # 'product_id': product.id if product else False, # Liên kết với product.product của Odoo
                    'pancake_quantity': item_data.get('quantity'),
                    'pancake_price_unit': item_data.get('variation_info', {}).get('retail_price'),
                    'pancake_total_discount_item': item_data.get('total_discount'),
                    'pancake_variation_id': str(item_data.get('variation_info',{}).get('display_id')) or str(item_data.get('variation_id')), # Thêm nếu cần
                    'pancake_item_raw_data': str(item_data) # Lưu trữ dữ liệu thô của item
                }
                # PancakeOrderLine.create(line_vals) # Tạo từng dòng
                line_vals_list.append(line_vals)
            
            if line_vals_list:
                try:
                    PancakeOrderLine.create(line_vals_list) # Tạo nhiều dòng một lúc để tối ưu
                except Exception as e:
                    _logger.error(f"Failed to create lines for Pancake order {p_order_id}: {e}")
                    self.env.cr.rollback() # Rollback việc tạo lines
                    if not existing_order: # Nếu đây là đơn mới tạo thì xóa luôn đơn
                        current_order_for_lines.unlink()
                        created_count -=1
                    # Nếu là đơn update thì không xóa, chỉ log lỗi lines
                    continue


            processed_count += 1
            if processed_count % 50 == 0: # Commit mỗi 50 đơn hàng để tránh transaction quá lớn
                self.env.cr.commit()
                _logger.info(f"Committed {processed_count} orders so far...")

        self.env.cr.commit() # Commit những đơn hàng còn lại
        _logger.info(f"Pancake orders synchronization finished. Processed: {processed_count}, Created: {created_count}, Updated: {updated_count}.")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pancake Sync'),
                'message': _('Đồng bộ đơn hàng Pancake hoàn tất. Xử lý: %s, Tạo mới: %s, Cập nhật: %s') % (processed_count, created_count, updated_count),
                'sticky': False,
            }
        }

    def action_sync_pancake_all_orders(self):
        _logger.info("Starting Pancake orders synchronization...")
        api_key = self._get_pancake_api_key()
        shop_id = self._get_pancake_shop_id()
        
        Partner = self.env['res.partner']
        Product = self.env['product.product'] # Dù bạn đã comment out product_id, vẫn nên khai báo
        PancakeOrderLine = self.env['pancake.order.line']
        PancakeTag = self.env['pancake.order.tag']

        all_orders_data = []
        current_page = 1
        # Đặt một giới hạn hợp lý cho mỗi lần gọi API, ví dụ 100. API có thể có giới hạn tối đa riêng.
        limit_per_page = 100 
        
        # Vòng lặp để lấy dữ liệu từ tất cả các trang
        while True:
            # Thêm tham số page và limit vào URL
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/orders?api_key={api_key}&page_size={limit_per_page}&page_number={current_page}"
            # Hoặc nếu API dùng tên tham số khác, ví dụ: &offset=(current_page-1)*limit_per_page

            _logger.info(f"Calling Pancake API (Page {current_page}): {api_url.replace(api_key, '***REDACTED***')}")
            
            try:
                response = requests.get(api_url, timeout=60)
                response.raise_for_status()
                page_data = response.json()
            except requests.exceptions.RequestException as e:
                _logger.error(f"API call failed for page {current_page}: {e}")
                # Quyết định có nên dừng lại hay thử lại, hoặc bỏ qua trang này
                # Trong ví dụ này, chúng ta sẽ dừng nếu có lỗi mạng nghiêm trọng
                raise UserError(_("Failed to connect to Pancake API on page %s: %s") % (current_page, e))
            except ValueError as e: # JSONDecodeError
                _logger.error(f"Failed to decode JSON response for page {current_page}: {e}")
                _logger.error(f"Response text: {response.text[:500]}")
                # Quyết định có nên dừng lại hay bỏ qua
                raise UserError(_("Failed to parse response from Pancake API on page %s: %s") % (current_page, e))

            orders_on_page = page_data.get('data', [])
            
            if not orders_on_page:
                # Không còn đơn hàng nào trên trang này, nghĩa là đã hết dữ liệu
                _logger.info(f"No more orders found on page {current_page}. Ending pagination.")
                break
            
            all_orders_data.extend(orders_on_page)
            
            # Điều kiện dừng nếu API không trả về mảng rỗng khi hết trang
            # Ví dụ: nếu API trả về số lượng item ít hơn limit, có thể là trang cuối
            if len(orders_on_page) < limit_per_page:
                _logger.info(f"Received {len(orders_on_page)} orders, less than limit {limit_per_page}. Assuming last page.")
                break
                
            current_page += 1
            
            # Thêm một khoảng nghỉ nhỏ giữa các request để tránh làm quá tải API (tùy chọn)
            # import time
            # time.sleep(0.5) # Nghỉ 0.5 giây

        if not all_orders_data:
            _logger.info("No orders found in the API response after checking all pages.")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Pancake Sync'),
                    'message': _('Không tìm thấy đơn hàng nào từ API Pancake.'),
                    'sticky': False,
                }
            }

        processed_count = 0
        created_count = 0
        updated_count = 0

        # Phần xử lý `all_orders_data` giữ nguyên như code gốc của bạn
        # Chỉ thay `orders_data` bằng `all_orders_data`
        for order_data in all_orders_data: # <<< THAY ĐỔI Ở ĐÂY
            p_order_id = str(order_data.get('id'))
            if not p_order_id:
                _logger.warning(f"Skipping order with missing ID: {order_data}")
                continue

            existing_order = self.search([('pancake_order_id', '=', p_order_id)], limit=1)
            
            customer_info = order_data.get('customer', {})
            partner = False
            customer_phone = (customer_info.get('phone_numbers') or [None])[0]
            customer_email = (customer_info.get('emails') or [None])[0]

            if customer_phone:
                partner = Partner.search([('phone', '=', customer_phone)], limit=1)
            if not partner and customer_email:
                partner = Partner.search([('email', '=', customer_email)], limit=1)
            
            if not partner and customer_info.get('name') and (customer_phone or customer_email):
                partner_vals = {
                    'name': customer_info.get('name'),
                    'phone': customer_phone,
                    'email': customer_email,
                    'company_type': 'person',
                }
                try:
                    partner = Partner.create(partner_vals)
                    _logger.info(f"Created new partner: {partner.name} (ID: {partner.id}) for Pancake order {p_order_id}")
                except Exception as e:
                    _logger.error(f"Failed to create partner for Pancake order {p_order_id}: {e}")

            tag_ids_to_link = []
            for tag_data in order_data.get('tags', []):
                p_tag_id = tag_data.get('id')
                p_tag_name = tag_data.get('name')
                if p_tag_id and p_tag_name:
                    tag = PancakeTag.search([('pancake_tag_id', '=', p_tag_id)], limit=1)
                    if not tag:
                        try:
                            tag = PancakeTag.create({'pancake_tag_id': p_tag_id, 'name': p_tag_name})
                        except Exception as e:
                            _logger.error(f"Failed to create tag {p_tag_name} (ID: {p_tag_id}): {e}")
                            continue
                    tag_ids_to_link.append(tag.id)


            #######
            
            # - lỗi datetime - 
            inserted_at_str = order_data.get('inserted_at')
            updated_at_str = order_data.get('updated_at')

            pancake_inserted_at_dt = None
            if inserted_at_str:
                try:
                    # Chuỗi đầu vào: '2025-05-26T00:29:16.651041'
                    # Bỏ phần microsecond đi vì Odoo thường lưu đến giây, và format '%f' có thể rắc rối nếu số chữ số thay đổi
                    # Định dạng mới sẽ là '%Y-%m-%dT%H:%M:%S'
                    pancake_inserted_at_dt = datetime.strptime(inserted_at_str.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                except ValueError as ve:
                    _logger.error(f"Lỗi phân tích chuỗi inserted_at '{inserted_at_str}': {ve} cho đơn hàng {p_order_id}")
                    # Bạn có thể quyết định bỏ qua, gán None, hoặc dừng hẳn tùy theo yêu cầu

            pancake_updated_at_dt = None
            if updated_at_str:
                try:
                    pancake_updated_at_dt = datetime.strptime(updated_at_str.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                except ValueError as ve:
                    _logger.error(f"Lỗi phân tích chuỗi updated_at '{updated_at_str}': {ve} cho đơn hàng {p_order_id}")

            # --- Xử lý an toàn cho các trường có thể là None hoặc không phải dict ---
            creator_info = order_data.get('creator')
            pancake_creator_name_val = None
            if isinstance(creator_info, dict):
                pancake_creator_name_val = creator_info.get('name')

            assigning_seller_info = order_data.get('assigning_seller')
            pancake_assigning_seller_name_val = None
            if isinstance(assigning_seller_info, dict):
                pancake_assigning_seller_name_val = assigning_seller_info.get('name')
            
            page_info = order_data.get('page')
            pancake_page_name_val = None
            if isinstance(page_info, dict):
                pancake_page_name_val = page_info.get('name')

            # Tương tự, bạn nên kiểm tra cẩn thận cho shipping_address nếu nó cũng có thể là null
            shipping_address_info = order_data.get('shipping_address', {}) # Giữ lại default {} nếu key 'shipping_address' có thể thiếu hẳn

            

            #######

            order_vals = {
                'pancake_order_id': p_order_id,
                'pancake_system_id': str(order_data.get('system_id')),
                'partner_id': partner.id if partner else False,
                'pancake_customer_name': customer_info.get('name'),
                'pancake_customer_phone': customer_phone,
                'pancake_customer_fb_id': customer_info.get('fb_id'),
                
                'pancake_shipping_full_name': order_data.get('shipping_address', {}).get('full_name'),
                'pancake_shipping_phone': order_data.get('shipping_address', {}).get('phone_number'),
                'pancake_shipping_address': order_data.get('shipping_address', {}).get('full_address'),
                'pancake_shipping_province': order_data.get('shipping_address', {}).get('province_name'),
                'pancake_shipping_district': order_data.get('shipping_address', {}).get('district_name'),
                'pancake_shipping_commune': order_data.get('shipping_address', {}).get('commune_name') or order_data.get('shipping_address', {}).get('commnue_name'),

                'pancake_status_name': order_data.get('status_name'),
                'pancake_status_key': str(order_data.get('status')),
                'pancake_inserted_at': pancake_inserted_at_dt,
                'pancake_updated_at': pancake_updated_at_dt,
                'pancake_order_source_name': order_data.get('order_sources_name'),
                'pancake_page_name': pancake_page_name_val,
                'pancake_order_link': order_data.get('order_link'),

                'pancake_items_length': order_data.get('items_length'),
                'pancake_total_quantity': order_data.get('total_quantity'),
                'pancake_total_price': order_data.get('total_price'),
                'pancake_total_discount': order_data.get('total_discount'),
                'pancake_shipping_fee': order_data.get('shipping_fee'),
                'pancake_surcharge': order_data.get('surcharge'),
                'pancake_money_to_collect': order_data.get('money_to_collect') or order_data.get('cod'),
                'pancake_prepaid': order_data.get('prepaid'),
                'pancake_order_currency': order_data.get('order_currency'),

                'pancake_note': order_data.get('note'),
                'pancake_note_print': order_data.get('note_print'),
                'pancake_customer_note': ", ".join(note.get('content', '') for note in customer_info.get('notes', [])) if customer_info.get('notes') else None,
                'tag_ids': [(6, 0, tag_ids_to_link)] if tag_ids_to_link else False,

                'pancake_creator_name': pancake_creator_name_val,
                'pancake_assigning_seller_name': pancake_assigning_seller_name_val,
                'last_sync_date': fields.Datetime.now(),
                'pancake_raw_data': str(order_data),
            }

            if existing_order:
                try:
                    existing_order.write(order_vals)
                    updated_count += 1
                    existing_order.line_ids.unlink()
                    current_order_for_lines = existing_order
                except Exception as e:
                    _logger.error(f"Failed to update Pancake order {p_order_id}: {e}")
                    self.env.cr.rollback()
                    continue 
            else:
                try:
                    current_order_for_lines = self.create(order_vals)
                    created_count +=1
                except Exception as e:
                    _logger.error(f"Failed to create Pancake order {p_order_id}: {e}")
                    self.env.cr.rollback()
                    continue
            
            line_vals_list = []
            for item_data in order_data.get('items', []):
                product_name = item_data.get('variation_info', {}).get('name')
                product = False
                if product_name:
                    product = Product.search([('name', '=', product_name)], limit=1) 
                
                line_vals = {
                    'order_id': current_order_for_lines.id,
                    'pancake_product_name': product_name,
                    # 'product_id': product.id if product else False, # Vẫn giữ comment nếu bạn chưa muốn link
                    'pancake_quantity': item_data.get('quantity'),
                    'pancake_price_unit': item_data.get('variation_info', {}).get('retail_price'),
                    'pancake_total_discount_item': item_data.get('total_discount'),
                    'pancake_variation_id': str(item_data.get('variation_info',{}).get('display_id')) or str(item_data.get('variation_id')),
                    'pancake_item_raw_data': str(item_data)
                }
                line_vals_list.append(line_vals)
            
            if line_vals_list:
                try:
                    PancakeOrderLine.create(line_vals_list)
                except Exception as e:
                    _logger.error(f"Failed to create lines for Pancake order {p_order_id}: {e}")
                    self.env.cr.rollback()
                    if not existing_order:
                        current_order_for_lines.unlink()
                        created_count -=1
                    continue

            processed_count += 1
            if processed_count % 50 == 0:
                self.env.cr.commit()
                _logger.info(f"Committed {processed_count} orders so far...")

        self.env.cr.commit()
        _logger.info(f"Pancake orders synchronization finished. Processed: {processed_count}, Created: {created_count}, Updated: {updated_count}.")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pancake Sync'),
                'message': _('Đồng bộ đơn hàng Pancake hoàn tất. Xử lý: %s, Tạo mới: %s, Cập nhật: %s') % (processed_count, created_count, updated_count),
                'sticky': False,
            }
        }

class PancakeOrderLine(models.Model):
    _name = 'pancake.order.line'
    _description = 'Pancake Order Line'

    order_id = fields.Many2one('pancake.order', string='Đơn hàng Pancake', required=True, ondelete='cascade')
    
    # --- Thông tin sản phẩm từ Pancake ---
    pancake_product_name = fields.Char(string='Tên SP (Pancake)')
    pancake_variation_id = fields.Char(string='Mã biến thể SP (Pancake)')

    # --- Liên kết với sản phẩm Odoo --- 
    # product_id = fields.Many2one('product.product', string='Sản phẩm (Odoo)', ondelete='restrict',
    #                              help="Liên kết với sản phẩm tương ứng trong Odoo nếu tìm thấy.")
    
    pancake_quantity = fields.Float(string='Số lượng (Pancake)')
    pancake_price_unit = fields.Float(string='Đơn giá (Pancake)')
    pancake_total_discount_item = fields.Float(string='Giảm giá/SP (Pancake)')
    # Bạn có thể thêm các trường khác từ `variation_info` nếu cần

    pancake_item_raw_data = fields.Text(string="Dữ liệu thô Item JSON", readonly=True, copy=False)

    # Thêm các trường tính toán nếu cần, ví dụ:
    # subtotal = fields.Float(string='Thành tiền', compute='_compute_subtotal', store=True)

    # @api.depends('pancake_quantity', 'pancake_price_unit', 'pancake_total_discount_item')
    # def _compute_subtotal(self):
    #     for line in self:
    #         line.subtotal = (line.pancake_quantity * line.pancake_price_unit) - line.pancake_total_discount_item


# --- Kế thừa model product.product để thêm liên kết ngược (tùy chọn) ---
# class ProductProduct(models.Model):
#     _inherit = 'product.product'

#     pancake_order_line_ids = fields.One2many('pancake.order.line', 'product_id', string='Pancake Order Lines')
#     Có thể thêm một trường computed để đếm số lượng đã bán qua Pancake
#     pancake_sales_count = fields.Float(compute='_compute_pancake_sales_count', string='Sold (Pancake)')

    # def _compute_pancake_sales_count(self):
    #     for product in self:
    #         # Logic tính toán số lượng từ pancake_order_line_ids
    #         # Cần xem xét trạng thái đơn hàng Pancake nào được tính là "đã bán"
    #         lines = self.env['pancake.order.line'].search([
    #             ('product_id', '=', product.id),
    #             # ('order_id.pancake_status_key', 'in', ['DANH_SACH_TRANG_THAI_THANH_CONG'])
    #         ])
    #         product.pancake_sales_count = sum(lines.mapped('pancake_quantity'))

# --- Kế thừa model res.partner để thêm liên kết ngược (tùy chọn) ---
class ResPartner(models.Model):
    _inherit = 'res.partner'

    pancake_order_ids = fields.One2many('pancake.order', 'partner_id', string='Pancake Orders')
    # pancake_fb_id = fields.Char(string='Pancake Facebook ID', index=True) # Nếu muốn lưu trực tiếp