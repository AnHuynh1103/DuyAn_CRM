import requests
import json
import logging
from odoo import models, fields, api, _
from datetime import datetime, timedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

_logger = logging.getLogger(__name__)

PAGES_FM_API_V1_BASE_URL = "https://pages.fm/api/v1"
PAGES_FM_PUBLIC_API_V2_BASE_URL = "https://pages.fm/api/public_api/v2"
# Thêm URL cho API messages nếu khác, dựa trên JS của bạn là:
PAGES_FM_MESSAGES_API_BASE_URL = 'https://pages.fm/api/public_api/v1'


class PageFmPage(models.Model):
    _name = 'page.fm.page'
    _description = 'Page.fm Page'
    _order = 'name asc'

    name = fields.Char(string="Page Name", index=True)
    page_fm_id_str = fields.Char(string="Page.fm ID", index=True, required=False, copy=False)
    active = fields.Boolean(string="API Active", default=True, index=True, help="Trạng thái active từ API (dựa trên is_activated)")
    # 'active' của Odoo dùng cho archive/unarchive, trường này có thể đặt tên khác nếu muốn phân biệt rõ
    # Ví dụ: api_is_activated = fields.Boolean(string="API Is Activated")

    conversation_ids = fields.One2many('page.fm.conversation', 'page_fm_page_id', string="Conversations")
    conversation_count = fields.Integer(string="Conversation Count", compute='_compute_conversation_count', store=True)

    _sql_constraints = [
        ('page_fm_id_str_uniq', 'unique (page_fm_id_str)', 'Page.fm ID phải là duy nhất!')
    ]

    @api.depends('conversation_ids')
    def _compute_conversation_count(self):
        for record in self:
            record.conversation_count = len(record.conversation_ids)
    
    def action_view_conversations(self):
        self.ensure_one()
        # Tùy chọn: Kích hoạt đồng bộ hội thoại cho page này trước khi mở view
        # self.action_sync_conversations() 
        return {
            'type': 'ir.actions.act_window',
            'name': _('Conversations for %s') % self.name,
            'res_model': 'page.fm.conversation',
            'view_mode': 'kanban,list,form',
            'domain': [('page_fm_page_id', '=', self.id)],
            'context': {
                'default_page_fm_page_id': self.id, 
                'default_page_fm_id_str_related': self.page_fm_id_str,
                'search_default_filter_unread': 1 
            }
        }
    
    def action_sync_specific_pages_conversations(self):
        # Hàm này có thể được gọi từ một server action trên nhiều page đã chọn
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token, không thể lấy hội thoại.")
            return False # Hoặc raise UserError

        for odoo_page in self: # self ở đây là recordset các page đã chọn
            _logger.info(f"Đang chuẩn bị đồng bộ hội thoại cho page: {odoo_page.name} (FM ID: {odoo_page.page_fm_id_str})")
            conversations_list = odoo_page._fetch_conversations_for_page_record(main_access_token)
            if conversations_list:
                odoo_page._create_or_update_conversations(conversations_list)
            else:
                _logger.info(f"Không có hội thoại nào được lấy hoặc có lỗi khi lấy hội thoại cho page {odoo_page.page_fm_id_str}")
        return True


    def _generate_page_specific_access_token(self, main_access_token):
        self.ensure_one()
        page_fm_id = self.page_fm_id_str
        
        generate_token_url = f"{PAGES_FM_API_V1_BASE_URL}/pages/{page_fm_id}/generate_page_access_token?access_token={main_access_token}&page_id={page_fm_id}"
        # _logger.info(f"API Call: Generate Page Token for {page_fm_id} - URL: {generate_token_url}")

        try:
            response = requests.post(generate_token_url, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get('success') and data.get('page_access_token'):
                return data['page_access_token']
            _logger.error(f"Failed to generate page token for {page_fm_id}: {data.get('message')}")
            return None
        except Exception as e:
            _logger.error(f"Error generating page token for {page_fm_id}: {e}", exc_info=True)
            return None

    def _fetch_conversations_for_page_record(self, main_access_token):
        self.ensure_one()
        page_fm_id = self.page_fm_id_str
        odoo_page_id = self.id
        _logger.info(f"Fetching all conversations for Page Odoo ID: {odoo_page_id}, FM ID: {page_fm_id}")
        page_specific_access_token = self._generate_page_specific_access_token(main_access_token)
        if not page_specific_access_token:
            return []

        processed_conversations = []
        last_conversation_id = None
        fetch_limit = 25  # API always returns up to 25

        con = True
        while con:
            conversations_api_url = f"{PAGES_FM_PUBLIC_API_V2_BASE_URL}/pages/{page_fm_id}/conversations"
            params = {
                'page_access_token': page_specific_access_token,
                'page_id': page_fm_id
            }
            if last_conversation_id:
                params['last_conversation_id'] = last_conversation_id

            _logger.info(f"API Call: {conversations_api_url} - params: {params}")

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
                    break

                api_conversations = data.get('conversations', [])
                if not isinstance(api_conversations, list) or not api_conversations:
                    _logger.info("No more conversations to fetch.")
                    break

                _logger.info(f"Fetched {len(api_conversations)} conversations (last_id: {last_conversation_id})")

                for conv_data in api_conversations:
                    if not isinstance(conv_data, dict) or not conv_data.get('id'):
                        _logger.warning(f"Skipping invalid data: {conv_data}")
                        continue

                    platform = 'Không rõ'
                    from_id = conv_data.get('from', {}).get('id', '').lower()
                    page_id_api = conv_data.get('page_id', '').lower()

                    if from_id.startswith('pzl_') or page_id_api.startswith('pzl_'):
                        platform = 'Zalo'
                    elif from_id.startswith('fb_') or (page_id_api.isdigit() and not page_id_api.startswith('igo_')) or page_id_api.startswith('fb_'):
                        platform = 'Facebook'
                    elif from_id.startswith('igo_') or page_id_api.startswith('igo_'):
                        platform = 'Instagram'
                    elif conv_data.get('type') and conv_data.get('type') != 'INBOX':
                        platform = conv_data['type']

                    customer_id = conv_data.get('customer_id')
                    updated_at_str = conv_data.get('updated_at', datetime.now().isoformat())
                    try:
                        dt_object = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                        updated_at_fmt = dt_object.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                        # Kiểm tra xem updated_at có trễ hơn 2 ngày không
                        # if datetime.now() - dt_object > timedelta(days=2):
                        #     con = False
                    except ValueError:
                        _logger.error(f"Cannot parse updated_at: {updated_at_str}")
                        updated_at_fmt = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)


                    is_unread = not conv_data.get('seen', False)

                    processed_conv = {
                        'conversation_fm_id': conv_data.get('id'),
                        'page_fm_page_id': odoo_page_id,
                        'customer_fm_id': customer_id,
                        'customer_name_fm': conv_data.get('from', {}).get('name') or 'Khách ẩn danh',
                        'last_message_snippet': conv_data.get('snippet') or 'Không có tin nhắn',
                        'updated_at_fm': updated_at_fmt,
                        'is_unread_fm': is_unread,
                        'platform_fm': platform
                    }
                    processed_conversations.append(processed_conv)

                if len(api_conversations) < fetch_limit:
                    break

                last_conversation_id = api_conversations[-1].get('id')

            except Exception as e:
                _logger.error(f"Error fetching conversations: {e}", exc_info=True)
                break

        return processed_conversations



    def _create_or_update_conversations(self, conversations_data_list):
        self.ensure_one()
        ConversationEnv = self.env['page.fm.conversation']
        created_count = 0
        updated_count = 0
        for conv_vals in conversations_data_list:
            conv_fm_id = conv_vals.get('conversation_fm_id')
            if not conv_fm_id: continue
            conv_vals['page_fm_page_id'] = self.id
            existing_conv = ConversationEnv.search([('conversation_fm_id', '=', conv_fm_id), ('page_fm_page_id', '=', self.id)], limit=1)
            try:
                if existing_conv:
                    existing_conv.write(conv_vals)
                    updated_count += 1
                else:
                    ConversationEnv.create(conv_vals)
                    created_count += 1
            except Exception as e:
                _logger.error(f"Error C/U conversation FM ID {conv_fm_id} for page {self.page_fm_id_str}: {e}", exc_info=True)
        _logger.info(f"Conversations for page {self.page_fm_id_str}: {created_count} created, {updated_count} updated.")
        self.invalidate_recordset(['conversation_count'])

    @api.model
    def _create_or_update_page(self, page_data_from_api):
        page_fm_id = page_data_from_api.get('id')
        if not page_fm_id:
            _logger.warning("API page data missing 'id'. Skipping.")
            return None
        page_name = page_data_from_api.get('name', f"Page {page_fm_id}")
        is_api_activated = page_data_from_api.get('is_activated', False) # Lấy trạng thái active từ API
        
        page_values = {
            'name': page_name,
            'active': is_api_activated # Cập nhật trường active của Odoo
        }
        existing_page = self.search([('page_fm_id_str', '=', page_fm_id)], limit=1)
        try:
            if existing_page:
                # Chỉ ghi nếu có thay đổi đáng kể
                if existing_page.name != page_name or existing_page.active != is_api_activated:
                    existing_page.write(page_values)
                _logger.debug(f"Page processed: {page_name} (OdooID: {existing_page.id}, FMID: {page_fm_id})")
            else:
                dup_check = self.sudo().search([('page_fm_id_str', '=', page_fm_id_str)], limit=1)
                if not dup_check:
                    page_values['page_fm_id_str'] = str(page_fm_id).strip()
                    existing_page = self.create(page_values)
                    _logger.info(f"Page created: {page_name} (OdooID: {existing_page.id}, FMID: {page_fm_id})")
            return existing_page
        except Exception as e:
            _logger.error(f"Error C/U page FM ID {page_fm_id}: {e}", exc_info=True)
            return None

    @api.model
    def process_api_pages_data(self, pages_api_response_json):
        if not isinstance(pages_api_response_json, dict):
            _logger.error("Invalid API response for pages list.")
            return []
        categorized_data = pages_api_response_json.get('categorized', {})
        if not isinstance(categorized_data, dict):
             _logger.error("Invalid 'categorized' data for pages list.")
             return []

        # Đồng bộ từ cả 'activated' và 'inactivated' nếu API cung cấp page objects trong cả hai
        # Hoặc chỉ từ 'activated' nếu JS chỉ dùng nó. Dựa trên JS: data.categorized.activated
        # Giả sử 'activated' chứa danh sách các object page đang hoạt động
        pages_to_process_data = categorized_data.get('activated', []) 
        if not isinstance(pages_to_process_data, list):
            _logger.warning("'activated' pages data is not a list. Trying 'inactivated' as fallback for full sync.")
            # Fallback hoặc logic khác nếu 'activated' không phải là list page objects
            # For now, if activated is not a list of objects, we stop here for pages.
            # If your /pages API returns objects in 'inactivated' and just IDs in 'activated', this needs adjustment.
            # The provided JS implies 'activated' is a list of page objects.
            if not isinstance(pages_to_process_data, list): # Double check, could be empty list is intended.
                pages_to_process_data = [] # Avoid error if it's not a list at all

        _logger.info(f"Processing {len(pages_to_process_data)} pages from API's 'activated' list.")
        
        odoo_pages_processed = []
        for page_data_item in pages_to_process_data:
            if isinstance(page_data_item, dict):
                # API trả về `is_activated` cho mỗi page, dùng nó để set trường `active` của Odoo.
                # Nếu page_data_item từ `categorized.activated` thì mặc định `is_activated` là true.
                # Nếu bạn lấy từ nguồn khác, phải đảm bảo có trường `is_activated`.
                # Trong ví dụ JS: return activatedPages.map(page => ({ id: page.id, name: page.name, inactive: !page.is_activated }));
                # Nghĩa là API page object có 'is_activated'.
                odoo_page_record = self._create_or_update_page(page_data_item)
                if odoo_page_record:
                    odoo_pages_processed.append(odoo_page_record)
            else:
                _logger.warning(f"Skipping invalid page data item: {page_data_item}")
        return odoo_pages_processed


    def perform_full_sync(self):
        _logger.info("Starting full Page.fm sync (Pages & Conversations).")
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.warning("Main Page.fm Access Token not configured. Sync aborted.")
            return False

        pages_list_api_url = f"{PAGES_FM_API_V1_BASE_URL}/pages?access_token={main_access_token}"
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        
        try:
            response_pages = requests.get(pages_list_api_url, headers=headers, timeout=15)
            _logger.debug(f"API Get Pages List: {pages_list_api_url} - Status: {response_pages.status_code}")
            response_pages.raise_for_status()
            pages_api_data = response_pages.json()
            
            synced_odoo_pages = self.env[self._name].process_api_pages_data(pages_api_data)
            
            # Bây giờ, lấy hội thoại cho các trang vừa đồng bộ/cập nhật
            if synced_odoo_pages:
                _logger.info(f"Fetching conversations for {len(synced_odoo_pages)} synced/updated pages.")
                for odoo_page in synced_odoo_pages:
                    conversations_list_for_page = odoo_page._fetch_conversations_for_page_record(main_access_token)
                    if conversations_list_for_page:
                        odoo_page._create_or_update_conversations(conversations_list_for_page)
            
            _logger.info("Full Page.fm sync completed successfully.")
            return True
        except Exception as e:
            _logger.error(f"Error during full Page.fm sync: {e}", exc_info=True)
            return False
    
    # @api.model
    # def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, count=False):
    #     # Bỏ gọi API tự động ở đây để tránh quá tải, trừ khi có context đặc biệt
    #     if self.env.context.get('trigger_page_fm_sync_on_search_read'):
    #          _logger.info(">>> PageFmPage search_read: Triggering FULL API sync due to context flag.")
    #          try:
    #              self.env[self._name]._perform_full_sync()
    #          except Exception as e:
    #              _logger.error(f"Error during API sync in search_read: {e}", exc_info=True)
    #     else:
    #         _logger.info(">>> PageFmPage search_read: Skipping automatic API sync.")
            
    #     return super(PageFmPage, self).search_read(domain=domain, fields=fields, offset=offset, limit=limit, order=order, count=count)

    # def read(self, fields=None, load='_classic_read', **kwargs):
    #     _logger.info(f">>> PageFmPage read for records {self.ids}. kwargs: {kwargs}")
    #     # Bỏ gọi API tự động ở đây
    #     return super(PageFmPage, self).read(fields=fields, load=load)