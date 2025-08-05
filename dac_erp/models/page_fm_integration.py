import requests
import json
import logging
from odoo import models, fields, api, _
from datetime import datetime, timedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Pancake API URLs - Cập nhật theo documentation
PANCAKE_API_BASE_URL = "https://pages.fm/api/public_api/v2"
PANCAKE_MESSAGES_API_BASE_URL = "https://pages.fm/api/public_api/v1"


class PancakePageIntegration(models.Model):
    _name = 'pancake.page'
    _description = 'Pancake Page Integration'
    _order = 'name asc'

    name = fields.Char(string="Page Name", index=True)
    page_id = fields.Char(string="Pancake Page ID", index=True, required=True, copy=False)
    active = fields.Boolean(string="Active", default=True, index=True)
    
    conversation_ids = fields.One2many('pancake.page.conversation', 'page_id', string="Conversations")
    conversation_count = fields.Integer(string="Conversation Count", compute='_compute_conversation_count', store=True)

    _sql_constraints = [
        ('page_id_uniq', 'unique (page_id)', 'Pancake Page ID phải là duy nhất!')
    ]

    @api.depends('conversation_ids')
    def _compute_conversation_count(self):
        for record in self:
            record.conversation_count = len(record.conversation_ids)
    
    def action_view_conversations(self):
        """Xem cuộc hội thoại của page"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Conversations for %s') % self.name,
            'res_model': 'pancake.page.conversation',
            'view_mode': 'list,form',
            'domain': [('page_id', '=', self.id)],
            'context': {
                'default_page_id': self.id, 
                'search_default_filter_unread': 1 
            }
        }
    
    def action_sync_conversations(self):
        """Đồng bộ cuộc hội thoại cho page này"""
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            raise UserError("Thiếu main_access_token trong System Parameters")

        for page in self:
            _logger.info(f"Đang đồng bộ hội thoại cho page: {page.name} (Page ID: {page.page_id})")
            conversations_list = page._fetch_conversations_from_pancake_api(main_access_token)
            if conversations_list:
                page._create_or_update_conversations(conversations_list)
            else:
                _logger.info(f"Không có hội thoại nào cho page {page.page_id}")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã đồng bộ cuộc hội thoại cho {len(self)} trang',
                'type': 'success',
                'sticky': False,
            }
        }
    
    def fetch_conversations(self):
        """Public method để fetch conversations - dùng cho controller"""
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            raise UserError("Thiếu main_access_token trong System Parameters")
        
        self.ensure_one()
        conversations_list = self._fetch_conversations_from_pancake_api(main_access_token)
        if conversations_list:
            self._create_or_update_conversations(conversations_list)
        return conversations_list
    
    def _generate_page_specific_access_token(self, main_access_token):
        """Tạo token riêng cho page"""
        self.ensure_one()
        page_fm_id = self.page_id
        
        generate_token_url = f"{PANCAKE_MESSAGES_API_BASE_URL}/pages/{page_fm_id}/generate_page_access_token?access_token={main_access_token}&page_id={page_fm_id}"

        try:
            response = requests.post(generate_token_url, 
                                   headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, 
                                   timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get('success') and data.get('page_access_token'):
                return data['page_access_token']
            _logger.error(f"Failed to generate page token for {page_fm_id}: {data.get('message')}")
            return None
        except Exception as e:
            _logger.error(f"Error generating page token for {page_fm_id}: {e}")
            return None

    def _fetch_conversations_from_pancake_api(self, main_access_token):
        """Lấy cuộc hội thoại từ Pancake API sử dụng main token"""
        self.ensure_one()
        page_id = self.page_id
        
        # API URL theo documentation: /pages/{page_id}/conversations
        conversations_api_url = f"{PANCAKE_API_BASE_URL}/pages/{page_id}/conversations"
        
        params = {
            'access_token': main_access_token,
            'page_id': page_id
        }

        try:
            response = requests.get(
                conversations_api_url,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                params=params,
                timeout=20
            )
            response.raise_for_status()
            data = response.json()

            if not data.get('success'):
                _logger.error(f"API fetch failed: {data.get('message')}")
                return []

            conversations = data.get('conversations', [])
            if not isinstance(conversations, list):
                return []

            processed_conversations = []
            for conv_data in conversations:
                if not isinstance(conv_data, dict) or not conv_data.get('id'):
                    continue

                # Xác định platform dựa trên type
                platform = conv_data.get('type', 'INBOX')
                if platform == 'INBOX':
                    # Xác định platform dựa trên page_uid structure
                    page_uid = conv_data.get('page_uid', '')
                    if page_uid.startswith('fb_'):
                        platform = 'Facebook'
                    elif page_uid.startswith('pzl_'):
                        platform = 'Zalo'
                    elif page_uid.startswith('igo_'):
                        platform = 'Instagram'
                    else:
                        platform = 'Other'

                # Parse timestamps
                updated_at_str = conv_data.get('updated_at')
                
                try:
                    if updated_at_str:
                        updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                        updated_at_fmt = updated_at.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                    else:
                        updated_at_fmt = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                except ValueError:
                    updated_at_fmt = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)

                # Lấy thông tin từ last_message và participants
                last_message = conv_data.get('last_message', {})
                participants = conv_data.get('participants', [])
                
                customer_info = {}
                if participants:
                    # Lấy participant đầu tiên (thường là khách hàng)
                    customer_info = participants[0] if isinstance(participants, list) else {}

                processed_conv = {
                    'conversation_id': conv_data.get('id'),
                    'page_id': self.id,
                    'customer_name': customer_info.get('name', 'Unknown Customer'),
                    'customer_email': customer_info.get('email', ''),
                    'customer_phone': customer_info.get('phone', ''),
                    'platform': platform,
                    'last_message_content': last_message.get('text', ''),
                    'last_message_sender': last_message.get('sender', ''),
                    'last_message_time': updated_at_fmt,
                    'conversation_type': conv_data.get('type', 'INBOX'),
                    'tags': json.dumps(conv_data.get('tags', [])),
                    'raw_data': json.dumps(conv_data, indent=2),
                }
                processed_conversations.append(processed_conv)

            return processed_conversations

        except Exception as e:
            _logger.error(f"Error fetching conversations: {e}")
            return []

    def _create_or_update_conversations(self, conversations_data_list):
        """Tạo hoặc cập nhật cuộc hội thoại"""
        self.ensure_one()
        ConversationEnv = self.env['pancake.page.conversation']
        created_count = 0
        updated_count = 0
        
        for conv_vals in conversations_data_list:
            conv_id = conv_vals.get('conversation_id')
            if not conv_id: 
                continue
                
            conv_vals['page_id'] = self.id
            existing_conv = ConversationEnv.search([
                ('conversation_id', '=', conv_id), 
                ('page_id', '=', self.id)
            ], limit=1)
            
            try:
                if existing_conv:
                    existing_conv.write(conv_vals)
                    updated_count += 1
                else:
                    ConversationEnv.create(conv_vals)
                    created_count += 1
            except Exception as e:
                _logger.error(f"Error C/U conversation ID {conv_id}: {e}")
                
        _logger.info(f"Conversations for page {self.page_id}: {created_count} created, {updated_count} updated.")

    @api.model
    def sync_all_pages_and_conversations(self):
        """Đồng bộ tất cả pages và conversations từ Page.fm"""
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            raise UserError("Chưa cấu hình Page.fm Access Token trong System Parameters")

        try:
            # Lấy danh sách pages
            pages_list_api_url = f"{PANCAKE_MESSAGES_API_BASE_URL}/pages?access_token={main_access_token}"
            headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
            
            response_pages = requests.get(pages_list_api_url, headers=headers, timeout=15)
            response_pages.raise_for_status()
            pages_api_data = response_pages.json()
            
            # Xử lý pages data
            synced_pages = self._process_api_pages_data(pages_api_data)
            
            # Lấy conversations cho các pages
            if synced_pages:
                for page in synced_pages:
                    conversations_list = page._fetch_conversations_from_pancake_api(main_access_token)
                    if conversations_list:
                        page._create_or_update_conversations(conversations_list)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Đồng bộ thành công',
                    'message': f'Đã đồng bộ {len(synced_pages)} trang và cuộc hội thoại từ Page.fm',
                    'type': 'success',
                    'sticky': False,
                }
            }
            
        except Exception as e:
            _logger.error(f"Error during full Page.fm sync: {e}")
            raise UserError(f"Lỗi khi đồng bộ: {str(e)}")

    @api.model
    def _process_api_pages_data(self, pages_api_response_json):
        """Xử lý dữ liệu pages từ API"""
        if not isinstance(pages_api_response_json, dict):
            return []
            
        categorized_data = pages_api_response_json.get('categorized', {})
        pages_to_process = categorized_data.get('activated', [])
        
        if not isinstance(pages_to_process, list):
            pages_to_process = []

        processed_pages = []
        for page_data in pages_to_process:
            if isinstance(page_data, dict):
                page = self._create_or_update_page(page_data)
                if page:
                    processed_pages.append(page)
                    
        return processed_pages

    @api.model
    def _create_or_update_page(self, page_data_from_api):
        """Tạo hoặc cập nhật page từ API data"""
        page_fm_id = page_data_from_api.get('id')
        if not page_fm_id:
            return None
            
        page_name = page_data_from_api.get('name', f"Page {page_fm_id}")
        is_api_activated = page_data_from_api.get('is_activated', False)
        
        page_values = {
            'name': page_name,
            'active': is_api_activated
        }
        
        existing_page = self.search([('page_id', '=', page_fm_id)], limit=1)
        
        try:
            if existing_page:
                if existing_page.name != page_name or existing_page.active != is_api_activated:
                    existing_page.write(page_values)
            else:
                page_values['page_id'] = page_fm_id
                existing_page = self.create(page_values)
                
            return existing_page
        except Exception as e:
            _logger.error(f"Error C/U page FM ID {page_fm_id}: {e}")
            return None
