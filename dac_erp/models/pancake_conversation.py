# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import models, fields, api, _
from datetime import datetime
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class PancakeConversation(models.Model):
    _name = 'pancake.conversation'
    _description = 'Pancake Conversation'
    _order = 'last_message_time desc'

    # === Basic Fields ===
    name = fields.Char(string='Tên cuộc hội thoại', compute='_compute_name', store=True)
    conversation_id = fields.Char(string='Conversation ID', required=True, index=True, copy=False)
    shop_id = fields.Char(string='Shop ID', required=True, index=True)
    
    # === Customer Info ===
    customer_name = fields.Char(string='Tên khách hàng')
    customer_phone = fields.Char(string='Số điện thoại khách hàng')
    customer_email = fields.Char(string='Email khách hàng')
    customer_id_pancake = fields.Char(string='Pancake Customer ID', index=True)
    
    # === Partner Linking ===
    partner_id = fields.Many2one('res.partner', string='Khách hàng (Partner)')
    
    # === Conversation Info ===
    status = fields.Selection([
        ('active', 'Đang hoạt động'),
        ('archived', 'Đã lưu trữ'),
        ('closed', 'Đã đóng')
    ], string='Trạng thái', default='active')
    
    platform = fields.Char(string='Nền tảng')  # Facebook, Zalo, etc.
    last_message_content = fields.Text(string='Nội dung tin nhắn cuối')
    last_message_time = fields.Datetime(string='Thời gian tin nhắn cuối')
    last_message_sender = fields.Char(string='Người gửi tin nhắn cuối')
    
    # === Staff Assignment ===
    assigned_staff_id = fields.Many2one('res.users', string='Nhân viên được giao')
    assigned_staff_name = fields.Char(string='Tên nhân viên (Pancake)')
    
    # === Sync Info ===
    last_sync_time = fields.Datetime(string='Lần đồng bộ cuối', readonly=True)
    raw_data = fields.Text(string='Dữ liệu thô JSON', readonly=True)
    
    # === Related Records ===
    message_ids = fields.One2many('pancake.conversation.message', 'conversation_id', string='Tin nhắn')
    message_count = fields.Integer(string='Số tin nhắn', compute='_compute_message_count', store=True)
    
    _sql_constraints = [
        ('conversation_shop_uniq', 'unique(conversation_id, shop_id)', 
         'Conversation ID phải là duy nhất cho mỗi shop!')
    ]

    @api.depends('customer_name', 'conversation_id')
    def _compute_name(self):
        for record in self:
            if record.customer_name:
                record.name = f"{record.customer_name} - {record.conversation_id}"
            else:
                record.name = f"Cuộc hội thoại {record.conversation_id}"

    @api.depends('message_ids')
    def _compute_message_count(self):
        for record in self:
            record.message_count = len(record.message_ids)

    def action_sync_from_pancake(self):
        """Đồng bộ dữ liệu cuộc hội thoại từ Pancake API"""
        api_key = self.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
        
        if not api_key:
            raise UserError("Chưa cấu hình Pancake API Key trong System Parameters")
        
        for record in self:
            try:
                # Gọi API để lấy chi tiết cuộc hội thoại
                conversation_data = self._fetch_conversation_detail(api_key, record.shop_id, record.conversation_id)
                
                if conversation_data:
                    record._update_from_api_data(conversation_data)
                    record.last_sync_time = fields.Datetime.now()
                    _logger.info(f"Đã đồng bộ cuộc hội thoại {record.conversation_id}")
                else:
                    _logger.warning(f"Không thể lấy dữ liệu cho cuộc hội thoại {record.conversation_id}")
                    
            except Exception as e:
                _logger.error(f"Lỗi khi đồng bộ cuộc hội thoại {record.conversation_id}: {e}")
                raise UserError(f"Lỗi khi đồng bộ: {str(e)}")

    def action_sync_messages(self):
        """Đồng bộ tin nhắn của cuộc hội thoại từ Pancake API"""
        api_key = self.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
        
        if not api_key:
            raise UserError("Chưa cấu hình Pancake API Key trong System Parameters")
        
        for record in self:
            try:
                # Gọi API để lấy tin nhắn
                messages_data = self._fetch_conversation_messages(api_key, record.shop_id, record.conversation_id)
                
                if messages_data and messages_data.get('data'):
                    record._create_or_update_messages(messages_data['data'])
                    _logger.info(f"Đã đồng bộ {len(messages_data['data'])} tin nhắn cho cuộc hội thoại {record.conversation_id}")
                else:
                    _logger.warning(f"Không có tin nhắn mới cho cuộc hội thoại {record.conversation_id}")
                    
            except Exception as e:
                _logger.error(f"Lỗi khi đồng bộ tin nhắn cuộc hội thoại {record.conversation_id}: {e}")
                raise UserError(f"Lỗi khi đồng bộ tin nhắn: {str(e)}")

    def action_view_messages(self):
        """Mở view để xem tin nhắn của cuộc hội thoại"""
        self.ensure_one()
        return {
            'name': f'Tin nhắn - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'pancake.conversation.message',
            'view_mode': 'list,form',
            'domain': [('conversation_id', '=', self.id)],
            'context': {
                'default_conversation_id': self.id,
                'create': False,  # Không cho phép tạo tin nhắn mới từ view này
            },
            'target': 'current',
        }

    def _fetch_conversation_detail(self, api_key, shop_id, conversation_id):
        """Gọi API Pancake để lấy chi tiết cuộc hội thoại"""
        try:
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/conversations/{conversation_id}"
            
            params = {'api_key': api_key}
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            response = requests.get(api_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            _logger.error(f"Lỗi khi gọi API Pancake conversation detail: {e}")
            return None

    def _fetch_conversation_messages(self, api_key, shop_id, conversation_id, page=1, limit=100):
        """Gọi API Pancake để lấy tin nhắn cuộc hội thoại"""
        try:
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/conversations/{conversation_id}/messages"
            
            params = {
                'api_key': api_key,
                'page': page,
                'per_page': limit
            }
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            response = requests.get(api_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            _logger.error(f"Lỗi khi gọi API Pancake conversation messages: {e}")
            return None

    def _update_from_api_data(self, data):
        """Cập nhật thông tin cuộc hội thoại từ dữ liệu API"""
        # Cập nhật các trường từ dữ liệu API
        # Cần điều chỉnh theo cấu trúc thực tế của API response
        self.write({
            'customer_name': data.get('customer_name'),
            'customer_phone': data.get('customer_phone'),
            'customer_email': data.get('customer_email'),
            'customer_id_pancake': data.get('customer_id'),
            'platform': data.get('platform'),
            'last_message_content': data.get('last_message', {}).get('content'),
            'last_message_time': self._parse_datetime(data.get('last_message', {}).get('timestamp')),
            'last_message_sender': data.get('last_message', {}).get('sender_name'),
            'assigned_staff_name': data.get('assigned_staff', {}).get('name'),
            'raw_data': json.dumps(data, indent=2),
        })
        
        # Tìm và liên kết partner
        self._find_or_create_partner()

    def _create_or_update_messages(self, messages_data):
        """Tạo hoặc cập nhật tin nhắn từ dữ liệu API"""
        Message = self.env['pancake.conversation.message']
        
        for msg_data in messages_data:
            message_id = msg_data.get('id')
            if not message_id:
                continue
                
            existing_message = Message.search([
                ('message_id', '=', message_id),
                ('conversation_id', '=', self.id)
            ], limit=1)
            
            message_vals = {
                'message_id': message_id,
                'conversation_id': self.id,
                'content': msg_data.get('content', ''),
                'sender_name': msg_data.get('sender_name', ''),
                'sender_type': msg_data.get('sender_type', ''),  # staff/customer
                'timestamp': self._parse_datetime(msg_data.get('timestamp')),
                'message_type': msg_data.get('type', 'text'),  # text/image/file/etc
                'raw_data': json.dumps(msg_data, indent=2),
            }
            
            if existing_message:
                existing_message.write(message_vals)
            else:
                Message.create(message_vals)

    def _find_or_create_partner(self):
        """Tìm hoặc tạo partner cho khách hàng"""
        if self.partner_id or not self.customer_name:
            return
            
        Partner = self.env['res.partner']
        partner = None
        
        # Tìm theo phone
        if self.customer_phone:
            partner = Partner.search([('phone', '=', self.customer_phone)], limit=1)
        
        # Tìm theo email
        if not partner and self.customer_email:
            partner = Partner.search([('email', '=', self.customer_email)], limit=1)
        
        # Tìm theo customer_id_pancake
        if not partner and self.customer_id_pancake:
            partner = Partner.search([('pancake_id', '=', self.customer_id_pancake)], limit=1)
        
        # Tạo mới nếu không tìm thấy
        if not partner:
            partner = Partner.create({
                'name': self.customer_name,
                'phone': self.customer_phone,
                'email': self.customer_email,
                'pancake_id': self.customer_id_pancake,
                'company_type': 'person',
            })
            _logger.info(f"Đã tạo partner mới {partner.name} cho cuộc hội thoại {self.conversation_id}")
        
        self.partner_id = partner

    def _parse_datetime(self, datetime_str):
        """Parse datetime string từ API"""
        if not datetime_str:
            return False
            
        try:
            # Điều chỉnh format theo định dạng thực tế của API
            if 'T' in datetime_str:
                dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
            return dt
        except:
            return False

    @api.model
    def sync_all_conversations_from_pancake(self):
        """Đồng bộ tất cả cuộc hội thoại từ Pancake"""
        api_key = self.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
        shop_id = self.env['ir.config_parameter'].sudo().get_param('pancake.shop_id')
        
        if not api_key or not shop_id:
            raise UserError("Chưa cấu hình Pancake API Key hoặc Shop ID")
        
        try:
            # Gọi API để lấy danh sách cuộc hội thoại
            conversations_data = self._fetch_all_conversations(api_key, shop_id)
            
            if conversations_data and conversations_data.get('data'):
                created_count = 0
                updated_count = 0
                
                for conv_data in conversations_data['data']:
                    conv_id = conv_data.get('id')
                    if not conv_id:
                        continue
                    
                    existing_conv = self.search([
                        ('conversation_id', '=', conv_id),
                        ('shop_id', '=', shop_id)
                    ], limit=1)
                    
                    if existing_conv:
                        existing_conv._update_from_api_data(conv_data)
                        updated_count += 1
                    else:
                        self._create_from_api_data(conv_data, shop_id)
                        created_count += 1
                
                _logger.info(f"Đồng bộ hoàn thành: {created_count} tạo mới, {updated_count} cập nhật")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Đồng bộ thành công',
                        'message': f'Đã tạo mới {created_count} và cập nhật {updated_count} cuộc hội thoại',
                        'type': 'success',
                    }
                }
            else:
                raise UserError("Không có dữ liệu cuộc hội thoại từ API")
                
        except Exception as e:
            _logger.error(f"Lỗi khi đồng bộ tất cả cuộc hội thoại: {e}")
            raise UserError(f"Lỗi khi đồng bộ: {str(e)}")

    def _fetch_all_conversations(self, api_key, shop_id):
        """Gọi API để lấy tất cả cuộc hội thoại"""
        try:
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/conversations"
            
            params = {
                'api_key': api_key,
                'per_page': 100  # Lấy tối đa 100 cuộc hội thoại
            }
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            response = requests.get(api_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            _logger.error(f"Lỗi khi gọi API Pancake conversations: {e}")
            return None

    @api.model
    def _create_from_api_data(self, data, shop_id):
        """Tạo cuộc hội thoại mới từ dữ liệu API"""
        return self.create({
            'conversation_id': data.get('id'),
            'shop_id': shop_id,
            'customer_name': data.get('customer_name'),
            'customer_phone': data.get('customer_phone'),
            'customer_email': data.get('customer_email'),
            'customer_id_pancake': data.get('customer_id'),
            'platform': data.get('platform'),
            'last_message_content': data.get('last_message', {}).get('content'),
            'last_message_time': self._parse_datetime(data.get('last_message', {}).get('timestamp')),
            'last_message_sender': data.get('last_message', {}).get('sender_name'),
            'assigned_staff_name': data.get('assigned_staff', {}).get('name'),
            'raw_data': json.dumps(data, indent=2),
            'last_sync_time': fields.Datetime.now(),
        })

    def sync_all_conversations_from_pancake(self):
        """Đồng bộ tất cả cuộc hội thoại từ Pancake API"""
        api_key = self.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
        shop_id = self.env['ir.config_parameter'].sudo().get_param('pancake.shop_id', '1')
        
        if not api_key:
            raise UserError("Chưa cấu hình Pancake API Key trong System Parameters")
        
        try:
            # Gọi API để lấy danh sách cuộc hội thoại
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/conversations"
            params = {
                'api_key': api_key,
                'per_page': 100  # Lấy tối đa 100 cuộc hội thoại
            }
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            response = requests.get(api_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get('data'):
                synced_count = 0
                for conversation_data in result['data']:
                    conversation_id = conversation_data.get('id')
                    if conversation_id:
                        # Tìm hoặc tạo cuộc hội thoại
                        conversation = self.search([('conversation_id', '=', conversation_id)], limit=1)
                        if conversation:
                            conversation._update_from_api_data(conversation_data)
                        else:
                            conversation = self._create_from_api_data(conversation_data, shop_id)
                        synced_count += 1
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Đồng bộ thành công',
                        'message': f'Đã đồng bộ {synced_count} cuộc hội thoại từ Pancake',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Không có dữ liệu',
                        'message': 'Không tìm thấy cuộc hội thoại nào từ Pancake',
                        'type': 'warning',
                        'sticky': False,
                    }
                }
                
        except Exception as e:
            _logger.error(f"Lỗi khi đồng bộ tất cả cuộc hội thoại: {e}")
            raise UserError(f"Lỗi khi đồng bộ: {str(e)}")


class PancakeConversationMessage(models.Model):
    _name = 'pancake.conversation.message'
    _description = 'Pancake Conversation Message'
    _order = 'timestamp desc'

    # === Basic Fields ===
    message_id = fields.Char(string='Message ID', required=True, index=True)
    conversation_id = fields.Many2one('pancake.conversation', string='Cuộc hội thoại', required=True, ondelete='cascade')
    
    # === Message Content ===
    content = fields.Text(string='Nội dung tin nhắn')
    message_type = fields.Selection([
        ('text', 'Văn bản'),
        ('image', 'Hình ảnh'),
        ('file', 'File'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('sticker', 'Sticker'),
        ('location', 'Vị trí'),
        ('other', 'Khác')
    ], string='Loại tin nhắn', default='text')
    
    # === Sender Info ===
    sender_name = fields.Char(string='Người gửi')
    sender_type = fields.Selection([
        ('customer', 'Khách hàng'),
        ('staff', 'Nhân viên'),
        ('system', 'Hệ thống')
    ], string='Loại người gửi')
    
    staff_id = fields.Many2one('res.users', string='Nhân viên gửi')
    
    # === Timestamp ===
    timestamp = fields.Datetime(string='Thời gian gửi')
    
    # === Attachments ===
    attachment_url = fields.Char(string='Link đính kèm')
    attachment_name = fields.Char(string='Tên file đính kèm')
    
    # === Raw Data ===
    raw_data = fields.Text(string='Dữ liệu thô JSON', readonly=True)
    
    _sql_constraints = [
        ('message_id_uniq', 'unique(message_id)', 'Message ID phải là duy nhất!')
    ]
