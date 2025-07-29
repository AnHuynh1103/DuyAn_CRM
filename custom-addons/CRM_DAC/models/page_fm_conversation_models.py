import requests
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from odoo import SUPERUSER_ID
from odoo import models, fields, api, _
from datetime import datetime, timedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
import time
import odoo

_logger = logging.getLogger(__name__)

PAGES_FM_MESSAGES_API_BASE_URL = 'https://pages.fm/api/public_api/v1'
PAGES_FM_API_V1_BASE_URL = "https://pages.fm/api/v1"


def sync_one_conversation(conv_id, dbname):
    try:
        with api.Environment.manage():
            registry = odoo.registry(dbname)
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                conv = env['page.fm.conversation'].browse(conv_id)
                conv.action_sync_messages()
                cr.commit()
    except Exception as e:
        _logger.error(f"Lỗi khi sync hội thoại {conv_id}: {e}")



class PageFmConversation(models.Model):
    _name = 'page.fm.conversation'
    _description = 'Page.fm Conversation'
    _order = 'updated_at_fm desc'

    # == Main Fields ==
    name = fields.Char(string="Customer Name", compute='_compute_name', store=True, help="Tên khách hàng hoặc ID hội thoại")
    conversation_fm_id = fields.Char(string="Conversation FM ID", required=True, index=True, copy=False, help="ID gốc của hội thoại từ API")
    
    page_fm_page_id = fields.Many2one(
        'page.fm.page', 
        string="Page.fm Page", 
        required=True, 
        ondelete='cascade',
        index=True,
        help="Trang Page.fm mà hội thoại này thuộc về"
    )
    page_fm_id_str_related = fields.Char(related='page_fm_page_id.page_fm_id_str', string="Page FM ID (Related)", store=True, readonly=True)

    # == Customer & Partner Fields ==
    customer_fm_id = fields.Char(string="Customer FM ID (for API)", index=True, copy=False, help="Customer ID (UUID) từ API, dùng để lấy tin nhắn chi tiết")
    customer_name_fm = fields.Char(string="Customer Name (from API)", help="Tên khách hàng từ API")
    
    partner_id = fields.Many2one(
        'res.partner',
        string="Customer (Partner)",
        # tracking=True,
        help="Liên kết với Customer trong hệ thống Odoo."
    )
    phone = fields.Char(string="Phone Number", help="Số điện thoại được tìm thấy từ hội thoại.")

    # == Message & Sync Fields ==
    last_message_snippet = fields.Text(string="Last Message Snippet", help="Đoạn tin nhắn cuối cùng")
    last_message_id = fields.Char(string="Last message FM ID")
    updated_at_fm = fields.Datetime(string="Last Updated (FM)", index=True, help="Thời điểm cập nhật cuối cùng của hội thoại từ API")
    is_unread_fm = fields.Boolean(string="Is Unread", help="Đánh dấu hội thoại là chưa đọc (dựa trên logic !conv.seen từ API)")
    platform_fm = fields.Char(string="Platform (FM)", help="Nền tảng của hội thoại (Zalo, Facebook, Instagram, etc.) được suy ra từ API")
    updated_at_fm_by_hand = fields.Datetime(string="Last Updated (by hand)")
    message_ids = fields.One2many('page.fm.message', 'conversation_id', string="Messages")
    message_count = fields.Integer(string="Message Count", compute='_compute_message_count', store=True)
    last_message_sync_fm = fields.Datetime(string="Last Message Sync (FM)", readonly=True, help="Thời điểm cuối cùng đồng bộ tin nhắn cho hội thoại này.")

    _sql_constraints = [
        ('conversation_fm_id_page_uniq', 'unique(conversation_fm_id, page_fm_page_id)', 'Conversation FM ID phải là duy nhất cho mỗi trang!')
    ]

    @api.depends('customer_name_fm', 'conversation_fm_id')
    def _compute_name(self):
        for record in self:
            if record.customer_name_fm and record.customer_name_fm not in ['Khách ẩn danh', '']:
                record.name = record.customer_name_fm
            elif record.conversation_fm_id:
                record.name = f"Conv: {record.conversation_fm_id}"
            else:
                record.name = _("N/A")

    @api.depends('message_ids')
    def _compute_message_count(self):
        for record in self:
            record.message_count = len(record.message_ids)

    def _find_or_create_partner(self):
        """
        Tries to find a phone number in messages, then finds or creates a partner
        based on that phone number.
        """
        self.ensure_one()
        if self.partner_id:
            return  # Already has a partner

        Partner = self.env['res.partner']
        
        partner_domain_ID = ([('pancake_id', '=', self.customer_fm_id)])
        partner = Partner.search(partner_domain_ID, limit=1)

        if not partner:
            partner_vals = {
                'name': self.customer_name_fm or f"Khách hàng {self.conversation_fm_id}", 
                'pancake_id': self.customer_fm_id, 
                'company_type': 'person', 
                'company_id': False,
            }
            partner = Partner.create(partner_vals)
            _logger.info(f"Đã tạo partner mới: {partner.name} (ID: {partner.id}) cho hội thoại {self.conversation_fm_id}")
            
        self.partner_id = partner
        


    def _fetch_message_batch(self, page_specific_access_token, current_offset=0):
        self.ensure_one()
        page_fm_id = self.page_fm_page_id.page_fm_id_str
        conv_fm_id = self.conversation_fm_id
        customer_api_id = self.customer_fm_id

        if not all([page_fm_id, conv_fm_id, customer_api_id, page_specific_access_token]):
            _logger.error(f"Thiếu thông tin để lấy tin nhắn cho hội thoại {conv_fm_id}.")
            return (False, [])

        messages_api_url = f"{PAGES_FM_MESSAGES_API_BASE_URL}/pages/{page_fm_id}/conversations/{conv_fm_id}/messages"
        params = {
            'page_access_token': page_specific_access_token,
            'customer_id': customer_api_id,
            'conversation_id': conv_fm_id,
            'page_id': page_fm_id,
            'current_count': current_offset
        }

        try:
            response = requests.get(
                messages_api_url,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                params=params,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            
            should_continue = True
            all_msgs = data.get('messages', [])
            filtered_msgs = []

            # If we are not loading all, stop when we see the last saved message
            if self.last_message_id and not self.env.context.get('load_all', False):
                for msg in all_msgs:
                    if msg.get('id') == self.last_message_id:
                        should_continue = False
                        break # Stop here, don't add this message or any older ones
                    filtered_msgs.append(msg)
            else:
                filtered_msgs = all_msgs

            return (should_continue, filtered_msgs)
        except Exception as e:
            _logger.error(f"Lỗi khi fetch tin nhắn (offset={current_offset}): {e}", exc_info=True)
            return (False, [])

    def _fetch_all_messages(self, page_specific_access_token):
        self.ensure_one()
        all_messages = []
        offset = 0
        batch_limit = 25

        while True:
            should_continue, batch = self._fetch_message_batch(page_specific_access_token, offset)
            if not batch:
                break
            
            all_messages.extend(batch)
            offset += len(batch)
            
            if not should_continue or len(batch) < batch_limit:
                break

        if all_messages:
            self.last_message_id = all_messages[0].get('id')

        return all_messages
    
    def sync_all_conversations_scheduled(self):
        recent_date = datetime.now() - timedelta(days=1)
        recent_month = datetime.now() - timedelta(days=30)

        conversations = self.env['page.fm.conversation'].search([
            # '|',
            '|',
            ('updated_at_fm_by_hand', '=', False),
            ('updated_at_fm_by_hand', '<', recent_date.strftime('%Y-%m-%d %H:%M:%S')),
            ('updated_at_fm', '>=', recent_month.strftime('%Y-%m-%d %H:%M:%S')),
            ('last_message_sync_fm', 'not ilike', 'Sing nhật của'),
            ('last_message_sync_fm', 'not ilike', 'Zalo chỉ hiển thị tin nhắn từ sau lần đăng nhập đầu tiên'),
        ])

        if len(self) > 1:
            conversations = self
        _logger.info(f"Starting scheduled sync for {len(conversations)} recent conversations...")
        for conv in conversations:
            try:
                conv.action_sync_messages()
                conv.updated_at_fm_by_hand = datetime.now()
                self.env.cr.commit()
            except Exception as e:
                _logger.error(f"Lỗi khi sync hội thoại {conv.id}: {e}")
                self.env.cr.rollback()
        _logger.info(f"Finished scheduled sync for {len(conversations)} recent conversations.")



    # def sync_all_conversations_scheduled(self):
    #     dbname = self.env.cr.dbname
    #     conversations = self.env['page.fm.conversation'].search([])

    #     _logger.info(f"Starting scheduled sync for {len(conversations)} conversations...")

    #     with ThreadPoolExecutor(max_workers=5) as executor:
    #         for conv in conversations:
    #             executor.submit(sync_one_conversation, conv.id, dbname)

    #     _logger.info(f"Finished scheduled sync for {len(conversations)} recent conversations.")
    

    def action_sync_messages(self):
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token trong system parameters.")
            return False
        
        for record in self:
            page_specific_access_token = record.page_fm_page_id._generate_page_specific_access_token(main_access_token)
            if not page_specific_access_token:
                _logger.error(f"Không thể tạo token cho trang của hội thoại {record.conversation_fm_id}")
                continue

            messages = record._fetch_all_messages(page_specific_access_token)
            if not messages:
                _logger.info(f"Không có tin nhắn mới cho hội thoại {record.name}")
                continue

            _logger.info(f"Lấy được {len(messages)} tin nhắn từ API cho hội thoại {record.name}")

            Message = self.env['page.fm.message']
            
            

            messages_reversed = list(reversed(messages))  # Đảm bảo là list
            for i in range(len(messages_reversed)):  # Process oldest first
                msg_data = messages_reversed[i]
                msg_fm_id = msg_data.get('id')
                if not msg_fm_id:
                    continue

                existing = Message.search([
                    ('message_fm_id', '=', msg_fm_id),
                    ('conversation_id', '=', record.id)
                ], limit=1)

                if existing:
                    continue

                inserted_at_api = msg_data.get('inserted_at', datetime.now().isoformat())
                try:
                    dt_obj = datetime.fromisoformat(inserted_at_api.replace('Z', '+00:00'))
                    inserted_at = dt_obj.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                except ValueError:
                    inserted_at = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)

                previous_time = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                if i + 1 < len(messages_reversed):
                    next_msg_data = messages_reversed[i + 1]
                    previous_time_api = next_msg_data.get('inserted_at', datetime.now().isoformat())
                    try:
                        dt_obj = datetime.fromisoformat(previous_time_api.replace('Z', '+00:00'))
                        previous_time = dt_obj.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                    except ValueError:
                        previous_time= datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                else:
                    previous_time = inserted_at

                type_content =  'text'
                url_content = ''

                if msg_data.get('attachments'):
                    msg_attachments =  msg_data.get('attachments')[0]

                    type_content = msg_attachments.get('type', 'text')
                    url_content = msg_attachments.get('url', '')

                    if not type_content or not url_content:
                        attachments = msg_attachments.get('attachments', [])
                        if attachments:
                            type_content = attachments[0].get('type', 'text')
                            url_content = attachments[0].get('url', '')
                            if type_content == 'video':
                                url_content = attachments[0].get('video_data').get('url', '')

                staff =self.env['res.users'].search([
                    ('pancake_id', '=', msg_data.get('from', {}).get('admin_id')),
                ], limit=1)



                if not staff:
                    staff =self.env['res.users'].search([('name', '=', msg_data.get('from', {}).get('admin_name')),], limit=1)

                if not staff:
                    staff = self.env['res.users'].create({
                        'name': msg_data.get('from', {}).get('admin_name', 'Unknown Staff'),
                        'pancake_id': msg_data.get('from', {}).get('admin_id'),
                        # 'login': msg_data.get('from', {}).get('admin_id'),
                        # 'email': f"staff_{msg_data.get('from', {}).get('admin_id')}@example.com",
                    })
                    _logger.info(f"Đã tạo người dùng mới: {staff.name} (ID: {staff.id}) từ API")
                else:
                    staff.pancake_id = msg_data.get('from', {}).get('admin_id')

                if staff.login == 'admin':  # hoặc kiểm tra staff.id != 1
                    staff = False

                values = {
                    'message_fm_id': msg_fm_id,
                    'conversation_id': record.id,
                    'sender_name_fm': msg_data.get('from', {}).get('name'),
                    'staff_name_fm': msg_data.get('from', {}).get('admin_name'),
                    'staff_id_fm': msg_data.get('from', {}).get('admin_id'),
                    'previous_time': previous_time,
                    'staff': staff.id if staff else False,
                    'content_html': msg_data.get('message', ''),
                    # 'attachments_json': json.dumps(msg_data.get('attachments')) if msg_data.get('attachments') else False,
                    'attachments_json': json.dumps(msg_data),
                    'inserted_at_fm': inserted_at,
                    'raw_json_message': json.dumps(msg_data),
                    'type_content': type_content,
                    'url_content': url_content,
                }
                Message.create(values)

            record.write({'last_message_sync_fm': datetime.now()})
            record.invalidate_recordset(['message_count'])

            # Attempt to find or create a partner after syncing
            try:
                if not record.partner_id:
                    record._find_or_create_partner()
            except Exception as e:
                _logger.error(f"Lỗi khi tìm/tạo partner cho hội thoại {record.id}: {e}", exc_info=True)

        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # for rec in records:
        #     try:
        #         # Sync messages right after creation to link partner automatically
        #         _logger.info(f"Đang sync tin nhắn cho hội thoại {rec.conversation_fm_id} sau khi tạo.")
        #         rec.action_sync_messages()

        #     except Exception as e:
        #         _logger.error(f"Lỗi khi tự động đồng bộ tin nhắn sau create: {e}", exc_info=True)
        return records

