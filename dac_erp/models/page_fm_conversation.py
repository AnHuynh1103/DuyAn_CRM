import requests
import json
import logging
from odoo import models, fields, api, _
from datetime import datetime
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PancakePageConversation(models.Model):
    _name = 'pancake.page.conversation'
    _description = 'Pancake Page Conversation'
    _order = 'last_message_time desc'
    _rec_name = 'customer_name'

    # === Basic Info ===
    conversation_id = fields.Char(string="Conversation ID", index=True, required=True, copy=False)
    page_id = fields.Many2one('pancake.page', string="Page", required=True, ondelete='cascade', index=True)
    
    # === Customer Info ===
    customer_name = fields.Char(string="Customer Name")
    customer_email = fields.Char(string="Customer Email")
    customer_phone = fields.Char(string="Customer Phone")
    partner_id = fields.Many2one('res.partner', string="Odoo Partner")
    
    # === Message Info ===
    last_message_content = fields.Text(string="Last Message")
    last_message_sender = fields.Char(string="Last Message Sender")
    last_message_time = fields.Datetime(string="Last Message Time", index=True)
    
    # === Platform & Type ===
    platform = fields.Selection([
        ('Facebook', 'Facebook'),
        ('Zalo', 'Zalo'),
        ('Instagram', 'Instagram'),
        ('Other', 'Other')
    ], string="Platform", default='Other', index=True)
    
    conversation_type = fields.Selection([
        ('INBOX', 'Inbox'),
        ('COMMENT', 'Comment'),
        ('LIVESTREAM', 'Livestream')
    ], string="Type", default='INBOX')
    
    # === Tags ===
    tags = fields.Text(string="Tags (JSON)")
    
    # === Relations ===
    message_ids = fields.One2many('pancake.page.conversation.message', 'conversation_id', string="Messages")
    message_count = fields.Integer(string="Message Count", compute='_compute_message_count', store=True)
    
    # === Sync Info ===
    last_sync_time = fields.Datetime(string="Last Sync Time")
    raw_data = fields.Text(string="Raw API Data")

    _sql_constraints = [
        ('conversation_id_page_uniq', 'unique (conversation_id, page_id)', 
         'Conversation ID phải unique trong cùng một page!')
    ]

    @api.depends('message_ids')
    def _compute_message_count(self):
        for record in self:
            record.message_count = len(record.message_ids)

    def action_view_messages(self):
        """Xem tin nhắn của cuộc hội thoại"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Messages - {self.customer_name}',
            'res_model': 'pancake.page.conversation.message',
            'view_mode': 'list,form',
            'domain': [('conversation_id', '=', self.id)],
            'context': {
                'default_conversation_id': self.id,
                'create': False,
            },
            'target': 'current',
        }

    def action_sync_messages(self):
        """Đồng bộ tin nhắn từ Page.fm API"""
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            raise UserError("Thiếu main_access_token trong System Parameters")

        for conversation in self:
            try:
                messages_data = conversation._fetch_messages_from_api(main_access_token)
                if messages_data:
                    conversation._create_or_update_messages(messages_data)
                    conversation.last_sync_time = fields.Datetime.now()
                    _logger.info(f"Đã đồng bộ tin nhắn cho conversation {conversation.conversation_id}")
                else:
                    _logger.warning(f"Không có tin nhắn cho conversation {conversation.conversation_id}")
            except Exception as e:
                _logger.error(f"Lỗi khi đồng bộ tin nhắn: {e}")
                raise UserError(f"Lỗi khi đồng bộ tin nhắn: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã đồng bộ tin nhắn cho {len(self)} cuộc hội thoại',
                'type': 'success',
                'sticky': False,
            }
        }
    
    def fetch_messages(self):
        """Public method để fetch messages - dùng cho controller"""
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            raise UserError("Thiếu main_access_token trong System Parameters")
        
        self.ensure_one()
        messages_data = self._fetch_messages_from_api(main_access_token)
        if messages_data:
            self._create_or_update_messages(messages_data)
            self.last_sync_time = fields.Datetime.now()
        return messages_data

    def action_create_partner(self):
        """Tạo partner từ thông tin khách hàng"""
        self.ensure_one()
        if self.partner_id:
            raise UserError("Partner đã tồn tại cho cuộc hội thoại này")

        if not self.customer_name:
            raise UserError("Không có tên khách hàng để tạo partner")

        partner_vals = {
            'name': self.customer_name,
            'email': self.customer_email,
            'phone': self.customer_phone,
            'is_company': False,
            'category_id': [(6, 0, [])],  # Có thể thêm tag cho khách hàng từ Pancake
        }

        # Thêm thông tin platform vào comment
        if self.platform:
            partner_vals['comment'] = f"Khách hàng từ {self.platform} - Pancake"

        partner = self.env['res.partner'].create(partner_vals)
        self.partner_id = partner.id

        return {
            'type': 'ir.actions.act_window',
            'name': f'Partner - {partner.name}',
            'res_model': 'res.partner',
            'res_id': partner.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _fetch_messages_from_api(self, main_access_token):
        """Lấy tin nhắn từ Pancake API"""
        self.ensure_one()
        
        # API URL theo documentation: /pages/{page_id}/conversations/{conversation_id}/messages
        messages_api_url = f"https://pages.fm/api/public_api/v1/pages/{self.page_id.page_id}/conversations/{self.conversation_id}/messages"
        
        params = {
            'access_token': main_access_token,
            'page_id': self.page_id.page_id,
            'conversation_id': self.conversation_id,
            'current_count': 0  # Lấy từ đầu
        }

        try:
            response = requests.get(
                messages_api_url,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                params=params,
                timeout=20
            )
            response.raise_for_status()
            data = response.json()

            if data.get('success') and data.get('messages'):
                return data['messages']
            else:
                _logger.warning(f"No messages found for conversation {self.conversation_id}")
                return []

        except Exception as e:
            _logger.error(f"Error fetching messages for conversation {self.conversation_id}: {e}")
            return []

    def _create_or_update_messages(self, messages_data):
        """Tạo hoặc cập nhật tin nhắn"""
        self.ensure_one()
        MessageEnv = self.env['page.fm.conversation.message']
        created_count = 0
        updated_count = 0

        for msg_data in messages_data:
            if not isinstance(msg_data, dict) or not msg_data.get('id'):
                continue

            message_vals = self._prepare_message_vals(msg_data)
            if not message_vals:
                continue

            existing_msg = MessageEnv.search([
                ('message_fm_id', '=', msg_data['id']),
                ('conversation_id', '=', self.id)
            ], limit=1)

            try:
                if existing_msg:
                    existing_msg.write(message_vals)
                    updated_count += 1
                else:
                    MessageEnv.create(message_vals)
                    created_count += 1
            except Exception as e:
                _logger.error(f"Error C/U message {msg_data['id']}: {e}")

        _logger.info(f"Messages for conversation {self.conversation_fm_id}: {created_count} created, {updated_count} updated.")

    def _prepare_message_vals(self, msg_data):
        """Chuẩn bị dữ liệu tin nhắn từ API"""
        try:
            # Parse timestamp - API trả về inserted_at
            inserted_at_str = msg_data.get('inserted_at', datetime.now().isoformat())
            try:
                dt_object = datetime.fromisoformat(inserted_at_str.replace('Z', '+00:00'))
                inserted_at_fmt = dt_object.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            except ValueError:
                inserted_at_fmt = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)

            # Lấy thông tin từ API
            message_content = msg_data.get('message', '')
            message_type = msg_data.get('type', 'text')
            
            # Thông tin người gửi từ "from" object
            from_info = msg_data.get('from', {})
            sender_name = from_info.get('name', 'Unknown')
            sender_email = from_info.get('email', '')
            
            # Xác định xem có phải tin nhắn từ khách hàng không
            # Dựa trên trường is_hidden, is_removed hoặc logic khác
            is_from_customer = not msg_data.get('is_hidden', False)
            
            # Xử lý phone number nếu có
            has_phone = msg_data.get('has_phone', False)
            phone_number = ''
            if has_phone and from_info:
                phone_number = from_info.get('phone', '')

            return {
                'message_pancake_id': msg_data.get('conversation_id', ''),  # ID của message trong conversation
                'conversation_id': self.id,
                'content': message_content,
                'message_type': message_type,
                'sender_name': sender_name,
                'sender_email': sender_email,
                'sender_phone': phone_number,
                'is_from_customer': is_from_customer,
                'has_phone': has_phone,
                'is_hidden': msg_data.get('is_hidden', False),
                'is_removed': msg_data.get('is_removed', False),
                'inserted_at': inserted_at_fmt,
                'raw_data': json.dumps(msg_data, indent=2),
            }

        except Exception as e:
            _logger.error(f"Error preparing message vals: {e}")
            return None


class PancakePageConversationMessage(models.Model):
    _name = 'pancake.page.conversation.message'
    _description = 'Pancake Page Conversation Message'
    _order = 'inserted_at desc'
    _rec_name = 'content'

    # === Basic Info ===
    message_pancake_id = fields.Char(string="Message Pancake ID", index=True, copy=False)
    conversation_id = fields.Many2one('pancake.page.conversation', string="Conversation", required=True, ondelete='cascade', index=True)
    
    # === Message Content ===
    content = fields.Text(string="Message Content")
    message_type = fields.Char(string="Message Type")  # text, image, etc.
    
    # === Sender Info ===
    sender_name = fields.Char(string="Sender Name")
    sender_email = fields.Char(string="Sender Email")
    sender_phone = fields.Char(string="Sender Phone")
    is_from_customer = fields.Boolean(string="From Customer", default=True, index=True)
    
    # === Message Status ===
    has_phone = fields.Boolean(string="Has Phone", default=False)
    is_hidden = fields.Boolean(string="Is Hidden", default=False)
    is_removed = fields.Boolean(string="Is Removed", default=False)
    
    # === Time Info ===
    inserted_at = fields.Datetime(string="Inserted At", index=True)
    
    # === Raw Data ===
    raw_data = fields.Text(string="Raw API Data")

    _sql_constraints = [
        ('message_pancake_id_conversation_uniq', 'unique (message_pancake_id, conversation_id)', 
         'Message Pancake ID phải unique trong cùng một conversation!')
    ]
