import requests
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from odoo import SUPERUSER_ID
from odoo import models, fields, api, _
from odoo.exceptions import AccessError
from datetime import datetime, timedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
import time
import odoo

_logger = logging.getLogger(__name__)

PAGES_FM_MESSAGES_API_BASE_URL = 'https://pages.fm/api/public_api/v1'
PAGES_FM_API_V1_BASE_URL = "https://pages.fm/api/v1"
_FORM_TOUCH_FIELDS = {
        'partner_id', 'phone',
        'is_unread_fm', 'is_internal_conversation',
        'status_state', 'require_processing', 'suggestion_note',
        'owner_id', 'participant_user_ids',
        # thêm các field hiển thị trên form mà bạn muốn tính là “thay đổi”
    }

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
    _inherit = ['mail.thread', 'mail.activity.mixin']

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

    # --- Dùng cho URL conversation pancake ---
    conv_page_fm_id = fields.Char( 
    string="Conversation Page ID (from API)",
    index=True,
    help="page_id trả về kèm mỗi hội thoại từ API; ưu tiên dùng khi build URL")

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
    is_unread_fm = fields.Boolean(string="Is Unread", help="Đánh dấu hội thoại là chưa đọc (dựa trên logic !conv.seen từ API)", tracking=True)
    platform_fm = fields.Char(string="Platform (FM)", help="Nền tảng của hội thoại (Zalo, Facebook, Instagram, etc.) được suy ra từ API")
    updated_at_fm_by_hand = fields.Datetime(string="Last Updated (by hand)")
    conv_message_ids = fields.One2many('page.fm.message', 'conversation_id', string="Messages")
    message_count = fields.Integer(string="Message Count", compute='_compute_message_count', store=True)
    last_message_sync_fm = fields.Datetime(string="Last Message Sync (FM)", readonly=True, help="Thời điểm cuối cùng đồng bộ tin nhắn cho hội thoại này.")

    _sql_constraints = [
        ('conversation_fm_id_page_uniq', 'unique(conversation_fm_id, page_fm_page_id)', 'Conversation FM ID phải là duy nhất cho mỗi trang!')
    ]
    
    
    # ==== STATUS FIELDS (OPTIMIZED) ====
    status_state = fields.Selection([
        ('new', 'Tin mới'),
        ('recontact', 'Chăm lại khách'),
        ('waiting', 'Đợi khách phản hồi'),
        ('done', 'Đã xử lý'),
    ], string="Trạng thái", default='new', index=True, tracking=True)

    # UNIFIED: Chỉ dùng suggestion_note cho mọi loại ghi chú (từ AI, manual, hoặc status note)
    suggestion_note = fields.Text(string="Ghi chú & Gợi ý xử lý", help="Ghi chú trạng thái, gợi ý từ AI hoặc external system", tracking=True)
    last_suggestion_at = fields.Datetime(string="Thời điểm cập nhật ghi chú")
    
    status_set_by_id = fields.Many2one('res.users', "Người cập nhật", tracking=True)
    status_set_at = fields.Datetime("Thời điểm cập nhật", tracking=True)

    # UNIFIED: Chỉ dùng require_processing - tự động quản lý logic checklist
    require_processing = fields.Boolean(string="Có yêu cầu xử lý", default=False, index=True, tracking=True)

    # COMPUTED: status_label được tính toán thay vì lưu trữ
    status_label = fields.Char(string="Nhãn trạng thái", compute='_compute_status_label', help="Text hiển thị trạng thái")

    # COMPUTED: Cleaned text fields for display
    last_message_snippet_clean = fields.Text(string="Last Message (Clean)", compute='_compute_clean_texts', help="Tin nhắn cuối đã làm sạch HTML tags")
    suggestion_note_clean = fields.Text(string="Note (Clean)", compute='_compute_clean_texts', help="Ghi chú đã làm sạch HTML tags")
    customer_name_clean = fields.Char(string="Customer Name (Clean)", compute='_compute_clean_texts', help="Tên khách hàng đã làm sạch")

    @api.depends('last_message_snippet', 'suggestion_note', 'customer_name_fm')
    def _compute_clean_texts(self):
        """Làm sạch HTML tags và format đặc biệt từ text"""
        for record in self:
            record.last_message_snippet_clean = self._clean_text(record.last_message_snippet or '')
            record.suggestion_note_clean = self._clean_text(record.suggestion_note or '')
            record.customer_name_clean = self._clean_text(record.customer_name_fm or '')

    def _clean_text(self, text):
        """Helper function để làm sạch HTML tags và format đặc biệt"""
        if not text:
            return ""
        
        # Loại bỏ HTML tags
        text = re.sub(r'<[^>]*>', ' ', text)
        
        # Loại bỏ stickers và emojis trong []
        text = re.sub(r'\[sticker\]', '[Sticker]', text, flags=re.IGNORECASE)
        text = re.sub(r'\[emoji\]', '[Emoji]', text, flags=re.IGNORECASE)
        text = re.sub(r'\[.*?\]', '', text)
        
        # Loại bỏ các ký tự HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        
        # Loại bỏ khoảng trắng thừa
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()

    @api.depends('status_state', 'require_processing')
    def _compute_status_label(self):
        """Tính toán nhãn hiển thị dựa trên trạng thái và yêu cầu xử lý"""
        default_labels = {
            'new': 'Có tin nhắn mới',
            'recontact': 'Chăm lại khách', 
            'waiting': 'Đợi khách phản hồi',
            'done': 'Đã xử lý',
        }
        for record in self:
            base_label = default_labels.get(record.status_state, record.status_state or '')
            if record.require_processing and record.status_state != 'done':
                record.status_label = f" {base_label}"
            else:
                record.status_label = base_label

    def action_toggle_require_processing(self):
        """Thay thế action_toggle_checklist_ok - Toggle trạng thái yêu cầu xử lý"""
        self.ensure_one()
        new_val = not bool(self.require_processing)
        vals = {
            'require_processing': new_val,
            'is_unread_fm': False,  # đánh dấu là đã đọc khi toggle
        }

        # Bật/ Tắt yêu cầu xử lý
        if not new_val:
            vals['status_state'] = 'done'
        elif self.status_state == 'done':
            vals['status_state'] = 'new'
        
        # Cho phép vượt qua hạn chế của write cho nhóm sale
        self.with_context(allow_toggle_require_processing=True).sudo().write(vals)

        
        return {
            'require_processing': self.require_processing,
            'is_unread_fm': self.is_unread_fm,
            'status_state': self.status_state,
            'status_label': self.status_label,
        }

    # DEPRECATED: Giữ lại cho backward compatibility
    def action_toggle_checklist_ok(self):
        """DEPRECATED: Chuyển đổi sang dùng action_toggle_require_processing"""
        return self.action_toggle_require_processing()

    def action_update_status(self, state, require_processing=False, note=None):
        """Cập nhật trạng thái conversation"""
        self.ensure_one()
        vals = {
            'status_state': state,
            'require_processing': bool(require_processing),
            'status_set_by_id': self.env.user.id,
            'status_set_at': fields.Datetime.now(),
        }
        if note:
            vals.update({
                'suggestion_note': note,
                'last_suggestion_at': fields.Datetime.now(),
            })
        self.sudo().write(vals)
        return True

    def _auto_bump_require_processing(self):
        """Bật require_processing khi có trạng thái đỏ hoặc chưa đọc."""
        for rec in self:
            # trạng thái đỏ HOẶC chưa đọc
            should_process = (
                rec.status_state in ('new', 'recontact') or 
                bool(getattr(rec, 'is_unread_fm', False))
            )
            
            # Cập nhật require_processing
            if should_process != rec.require_processing:
                rec.require_processing = should_process
                #_logger.info(f"Auto {'bật' if should_process else 'tắt'} require_processing cho conversation {rec.id} - Trạng thái: {rec.status_state}, unread: {bool(getattr(rec, 'is_unread_fm', False))}")

    # (tuỳ chọn) auto gợi ý trạng thái dựa vào unread/last message
    def apply_status_rule(self):
        """Áp dụng quy tắc trạng thái tự động dựa vào tin nhắn
        + Đồng thời refresh last_message_snippet & last_message_id theo tin mới nhất.
        """
        Message = self.env['page.fm.message'].sudo()
        for c in self:
            # Lấy tin nhắn cuối (ưu tiên inserted_at_fm)
            msg_order = 'inserted_at_fm desc, id desc' if 'inserted_at_fm' in Message._fields else 'id desc'
            last_msg = Message.search([('conversation_id', '=', c.id)], limit=1, order=msg_order)

            vals = {}

            # 1) Logic trạng thái
            if getattr(c, 'is_unread_fm', False):
                # Có tin chưa đọc -> 'Tin mới', cần xử lý
                vals.update({'status_state': 'new', 'require_processing': True})
            elif last_msg and (last_msg.sender_name_fm and not last_msg.staff_name_fm):
                # Tin cuối là của KH -> 'Chăm lại khách', cần xử lý
                vals.update({'status_state': 'recontact', 'require_processing': True})
            elif last_msg and last_msg.staff_name_fm:
                # Tin cuối là của NV -> 'Đợi khách phản hồi', không cần xử lý ngay
                vals.update({'status_state': 'waiting', 'require_processing': False})
            else:
                # Không có tin/khác -> 'Đã xử lý'
                vals.update({'status_state': 'done', 'require_processing': False})

            # 2) Làm mới snippet: Ưu tiên tin NHẮN CỦA KHÁCH HÀNG
            if last_msg:
                # Tìm tin khách hàng mới nhất của cuộc hội thoại
                # tiêu chí: không gán staff (staff = False) và không có staff_name_fm
                cust_domain = [
                    ('conversation_id', '=', c.id),
                    ('staff', '=', False),
                    '|', ('staff_name_fm', '=', False), ('staff_name_fm', '=', ''),  # bắt cả None lẫn chuỗi rỗng
                ]
                last_cust_msg = Message.search(cust_domain, limit=1, order=msg_order)

                # Helper dựng snippet ngắn gọn
                def _make_snippet(m):
                    if not m:
                        return False
                    txt = (m.content_html or '').strip()
                    if txt:
                        return txt
                    if m.type_content and m.type_content != 'text':
                        label_map = {'image': 'Ảnh', 'video': 'Video', 'file': 'Tệp', 'audio': 'Audio'}
                        label = label_map.get(m.type_content, m.type_content)
                        suf = (m.url_content or '').strip()
                        return f"[{label}]" + (f" {suf}" if suf else "")
                    return False

                # Ưu tiên snippet từ tin khách; nếu không có thì rơi về tin cuối bất kỳ
                snippet = _make_snippet(last_cust_msg) or _make_snippet(last_msg)

                vals.update({
                    'last_message_snippet': snippet or False,
                    # Giữ nguyên last_message_id theo tin cuối bất kỳ để phục vụ logic sync dừng đúng chỗ
                    'last_message_id': last_msg.message_fm_id or c.last_message_id,
                    # Không đụng vào last_message_sync_fm ở đây
                })

            # Ghi & auto-bump lại theo rule phụ
            if vals:
                c.sudo().write(vals)
                c._auto_bump_require_processing()


    @api.depends('customer_name_fm', 'conversation_fm_id')
    def _compute_name(self):
        for record in self:
            if record.customer_name_fm and record.customer_name_fm not in ['Khách ẩn danh', '']:
                record.name = record.customer_name_fm
            elif record.conversation_fm_id:
                record.name = f"Conv: {record.conversation_fm_id}"
            else:
                record.name = _("N/A")

    @api.depends('conv_message_ids')
    def _compute_message_count(self):
        for record in self:
            record.message_count = len(record.conv_message_ids)

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
        


    def _fetch_message_batch(self, page_specific_access_token, current_offset=0, retry_count=0):
        """Fetch message batch với retry logic và timeout handling"""
        import time
        
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

        max_retries = 3
        timeout_seconds = 25  # Tăng timeout lên 25 giây
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    # Exponential backoff: 2, 4, 8 giây
                    delay = 2 ** attempt
                    _logger.info(f"Retry attempt {attempt} after {delay}s delay for conversation {conv_fm_id}")
                    time.sleep(delay)

                response = requests.get(
                    messages_api_url,
                    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    params=params,
                    timeout=timeout_seconds
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

                # Success - log if this was a retry
                if attempt > 0:
                    _logger.info(f"Successfully fetched messages for {conv_fm_id} on retry attempt {attempt}")
                
                return (should_continue, filtered_msgs)
                
            except requests.exceptions.Timeout as e:
                _logger.warning(f"Timeout fetching messages (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    _logger.error(f"Final timeout for conversation {conv_fm_id} after {max_retries} attempts")
                    return (False, [])
                    
            except requests.exceptions.RequestException as e:
                error_msg = str(e).lower()
                if 'rate limit' in error_msg or 'too many requests' in error_msg:
                    _logger.warning(f"Rate limit hit for {conv_fm_id} (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        time.sleep(5 * (attempt + 1))  # Longer delay for rate limits
                        continue
                
                _logger.error(f"Request error fetching messages (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return (False, [])
                    
            except Exception as e:
                _logger.error(f"Unexpected error fetching messages (attempt {attempt + 1}): {e}", exc_info=True)
                if attempt == max_retries - 1:
                    return (False, [])

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

        # Debug đơn giản
        total_conversations = self.env['page.fm.conversation'].search_count([])
        _logger.info(f"Bắt đầu sync scheduled - Tổng {total_conversations} conversations trong hệ thống")
        
        if total_conversations == 0:
            _logger.warning("Không có conversation nào trong hệ thống! Hãy đồng bộ Pages và Conversations trước.")
            return

        # SIMPLIFIED DOMAIN - Chỉ dùng điều kiện thời gian cơ bản
        conversations = self.env['page.fm.conversation'].search([
            '&',  # AND operator  
            '|',  # OR cho điều kiện thời gian
            ('updated_at_fm_by_hand', '=', False),
            ('updated_at_fm_by_hand', '<', recent_date.strftime('%Y-%m-%d %H:%M:%S')),
            ('updated_at_fm', '>=', recent_month.strftime('%Y-%m-%d %H:%M:%S')),  # AND với cập nhật gần đây
        ])

        # Nếu có conversation được chọn cụ thể (từ UI), dùng chúng thay vì filter
        if len(self) >= 1:  # Sửa từ > 1 thành >= 1 để hỗ trợ chọn 1 conversation
            conversations = self
            _logger.info(f"User đã chọn {len(conversations)} cuộc hội thoại cụ thể để sync")
        else:
            _logger.info(f"Chế độ tự động: Tìm thấy {len(conversations)} cuộc hội thoại cần sync theo filter")
        
        _logger.info(f"Sẽ đồng bộ {len(conversations)} cuộc hội thoại")
        
        if len(conversations) == 0:
            _logger.warning("Không có conversation nào cần đồng bộ sau khi áp dụng filter.")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thông báo',
                    'message': 'Không có conversation nào cần đồng bộ',
                    'type': 'warning'
                }
            }
        
        # Sử dụng helper method chung
        self._perform_sync_batch(conversations)
        
        # Trả về reload action với thông báo
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }



    def _perform_sync_batch(self, conversations):
        """Helper method để thực hiện sync một batch conversations"""
        # Lấy main access token một lần cho tất cả
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token trong system parameters.")
            return

        synced_count = 0
        error_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 5  # Circuit breaker threshold
        
        for conv in conversations:
            try:
                # Circuit breaker: Dừng nếu quá nhiều lỗi liên tiếp
                if consecutive_errors >= max_consecutive_errors:
                    _logger.error(f"Circuit breaker activated: {consecutive_errors} consecutive errors. Stopping sync.")
                    break
                
                customer_name = conv.customer_name_fm or conv.name or f"Conversation {conv.id}"
                _logger.info(f"Bắt đầu sync conversation cho khách hàng: {customer_name} (ID: {conv.id})")
                
                # Kiểm tra token trước khi sync
                page = conv.page_fm_page_id
                if not page:
                    _logger.error(f"Conversation {conv.id} không có page_fm_page_id")
                    error_count += 1
                    consecutive_errors += 1
                    continue
                
                try:
                    page_token = page._generate_page_specific_access_token(main_access_token)
                    if not page_token:
                        _logger.error(f"Không thể tạo token cho page {page.name} (ID: {page.page_fm_id_str})")
                        error_count += 1
                        consecutive_errors += 1
                        continue
                    
                    # Thực hiện sync
                    result = conv.action_sync_messages()
                    message_count = conv.message_count
                    
                    _logger.info(f"✓ Đã sync {message_count} tin nhắn cho cuộc hội thoại của khách hàng: {customer_name}")
                    
                    conv.updated_at_fm_by_hand = datetime.now()
                    synced_count += 1
                    consecutive_errors = 0  # Reset error counter on success
                    self.env.cr.commit()
                    
                    # THÊM RATE LIMITING: Delay giữa các conversation
                    import time
                    time.sleep(0.5)  # Delay 500ms giữa mỗi conversation
                    
                except Exception as token_error:
                    _logger.error(f"Lỗi token/API cho conversation {conv.id} ({customer_name}): {token_error}")
                    error_count += 1
                    consecutive_errors += 1
                    self.env.cr.rollback()
                    
                    # Nếu lỗi timeout, delay lâu hơn trước khi tiếp tục
                    if "timeout" in str(token_error).lower() or "connection" in str(token_error).lower():
                        _logger.warning(f"Network error detected, waiting 5 seconds before continuing...")
                        import time
                        time.sleep(5)
                    
            except Exception as e:
                customer_name = getattr(conv, 'customer_name_fm', None) or getattr(conv, 'name', None) or f"Conversation {conv.id}"
                _logger.error(f"Lỗi khi sync hội thoại {conv.id} ({customer_name}): {e}")
                error_count += 1
                consecutive_errors += 1
                self.env.cr.rollback()
        
        _logger.info(f"Finished sync: {synced_count} thành công, {error_count} lỗi từ tổng {len(conversations)} conversations.")
        
        if error_count > 0:
            _logger.warning(f"Có {error_count} lỗi trong quá trình sync. Kiểm tra: 1) Token API, 2) Kết nối mạng, 3) Log chi tiết ở trên.")

    

    def action_sync_messages(self, date_from=None, date_to=None, unread_first=False, **kwargs):
        """Đồng bộ tin nhắn; hỗ trợ lọc theo khoảng thời gian và cờ ưu tiên (tùy chọn).
       - date_from/date_to: datetime hoặc str (ISO / 'YYYY-MM-DD' / 'YYYY-MM-DD HH:MM:SS')
       - unread_first: hiện tại chỉ để tương thích; không ảnh hưởng thứ tự ghi
       - cũng chấp nhận unread_only từ wizard qua **kwargs
       """
        #_logger.info("------------------------------------------->Hello")
        if 'unread_only' in kwargs and kwargs['unread_only'] is not None:
            unread_first = bool(kwargs['unread_only'])

        def _to_dt_any(v, is_end=False):
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            s = str(v)
            # ISO 8601 (chấp nhận 'Z')
            try:
                return datetime.fromisoformat(s.replace('Z', '+00:00'))
            except Exception:
                pass
            # 'YYYY-MM-DD' hoặc 'YYYY-MM-DD HH:MM:SS'
            try:
                if len(s) == 10:
                    return fields.Datetime.to_datetime(s + (' 23:59:59' if is_end else ' 00:00:00'))
                return fields.Datetime.to_datetime(s)
            except Exception:
                return None

        dt_from = _to_dt_any(date_from, is_end=False)
        dt_to   = _to_dt_any(date_to,   is_end=True)
        
        main_access_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        if not main_access_token:
            _logger.error("Thiếu main_access_token trong system parameters.")
            return False
        
        for record in self:
            page_specific_access_token = record.page_fm_page_id._generate_page_specific_access_token(main_access_token)
            if not page_specific_access_token:
                _logger.error(f"Không thể tạo token cho trang của hội thoại {record.conversation_fm_id}")
                continue

            # Fallback: dữ liệu cũ chưa có conv_page_fm_id thì gán bằng page_fm_id_str_related
            if not record.conv_page_fm_id and record.page_fm_id_str_related:
                record.write({'conv_page_fm_id': record.page_fm_id_str_related})

            messages = record._fetch_all_messages(page_specific_access_token)
            if not messages:
                record.write({'last_message_sync_fm': fields.Datetime.now()})
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
                
                # >>> NEW: lọc theo date_from / date_to nếu có
                if dt_from and dt_obj and dt_obj < dt_from:
                    continue
                if dt_to and dt_obj and dt_obj > dt_to:
                    continue

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

                # ---- Find / create staff safely ----
                Users = self.env['res.users'].sudo()
                from_info  = msg_data.get('from') or {}
                admin_id   = str(from_info.get('admin_id') or '').strip()
                admin_name = (from_info.get('admin_name') or '').strip()

                staff = Users.browse()  # mặc định rỗng

                # Chỉ xử lý staff khi có admin_id (tin do nhân viên gửi)
                if admin_id:
                    # 1) Ưu tiên tìm theo pancake_id nếu field có tồn tại
                    if 'pancake_id' in Users._fields:
                        staff = Users.search([('pancake_id', '=', admin_id)], limit=1)

                    # 2) Không có thì fallback theo tên, nhưng chỉ nhận nếu DUY NHẤT
                    if not staff and admin_name:
                        matches = Users.search([('name', '=', admin_name)], limit=2)
                        if len(matches) == 1:
                            staff = matches

                    # 3) Nếu tìm thấy mà chưa có pancake_id thì gắn thêm (không tạo user mới)
                    if staff and 'pancake_id' in Users._fields and not staff.pancake_id:
                        staff.with_context(no_reset_password=True).write({'pancake_id': admin_id})

                    # 4) Không liên kết vào user hệ thống
                    if staff and staff.login in ('admin', 'public'):
                        staff = Users.browse()

                    # 5) Nếu vẫn không có -> tạo user mới (an toàn)
                    if not staff and admin_name:
                        login_base = f"pancake_{admin_id}"
                        # đảm bảo login duy nhất
                        if Users.search_count([('login', '=', login_base)]) > 0:
                            login_base = f"{login_base}_{int(datetime.now().timestamp())}"

                        vals = {
                            'name': admin_name or 'Unknown Staff',
                            'login': login_base,
                        }
                        if 'pancake_id' in Users._fields:
                            vals['pancake_id'] = admin_id

                        # Tạo không gửi mail reset mật khẩu
                        staff = Users.with_context(no_reset_password=True).create(vals)
                        _logger.info("Created staff user from Pancake: %s (id=%s, admin_id=%s)", staff.name, staff.id, admin_id)
                else:
                    # Tin của khách (không có admin_id) -> không set staff
                    staff = Users.browse()

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

            # Tự động cập nhật require_processing sau khi sync tin nhắn
            try:
                record._auto_bump_require_processing()
            except Exception as e:
                _logger.error(f"Lỗi khi cập nhật require_processing cho conversation {record.id}: {e}")

            # Attempt to find or create a partner after syncing
            try:
                if not record.partner_id:
                    record._find_or_create_partner()
            except Exception as e:
                _logger.error(f"Lỗi khi tìm/tạo partner cho hội thoại {record.id}: {e}", exc_info=True)

            # Áp dụng rule/refresh snippet
            try:
                record.apply_status_rule()
            except Exception:
                _logger.exception("Lỗi khi áp dụng rule/refresh snippet cho conversation %s", record.id)
                
            # >>> NEW: cập nhật owner & participants từ message
            try:
                record._recompute_staff_links()
            except Exception:
                _logger.exception("Lỗi khi gán staff cho conversation %s", record.id)
            
            # >>> NEW: đẩy thông tin phụ trách sang Partner (nếu đã có partner)
            if record.partner_id:
                try:
                    record.partner_id.sync_staff_from_conversations()
                except Exception:
                    _logger.exception("Lỗi khi đồng bộ staff sang partner cho conv %s", record.id)

        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Tự động set require_processing theo logic
        for rec in records:
            try:
                rec._auto_bump_require_processing()
            except Exception as e:
                _logger.error(f"Lỗi khi set require_processing cho conversation {rec.id}: {e}")
        return records



    def write(self, vals):
        """Mô tả:
        - Giới hạn quyền cho nhóm sale (không phải manager)
        - Sau khi ghi, nếu đổi status/unread thì auto cập nhật require_processing
        """
        user = self.env.user
        allow_toggle = self.env.context.get('allow_toggle_require_processing')  # cho phép toggle checklist

        if (user.has_group('dac_erp.group_dac_erp_sale')
            and not user.has_group('dac_erp.group_dac_erp_manager')
            and not allow_toggle):
            allowed = {'status_state', 'is_unread_fm'}
            disallowed = set(vals.keys()) - allowed
            if disallowed:
                raise AccessError(_("Bạn không thể thực hiện thay đổi này. \nVui lòng liên hệ quản lý hoặc quản trị viên để hỗ trợ!"))

        # Nếu sửa suggestion_note -> cập nhật mốc last_suggestion_at
        if 'suggestion_note' in vals:
            # chỉ set khi thực sự có thay đổi nội dung
            now = fields.Datetime.now()
            for rec in self:
                old = (rec.suggestion_note or '').strip()
                new = (vals.get('suggestion_note') or '').strip()
                if old != new:
                    vals = dict(vals)  # tránh mutate
                    vals['last_suggestion_at'] = now
                    break

        # Nếu có thay đổi thuộc nhóm “form”, set last_update_at = now
        if any(k in _FORM_TOUCH_FIELDS for k in vals.keys()):
            vals = dict(vals)  # tránh mutate context
            vals['updated_at_fm_by_hand'] = fields.Datetime.now()  # để compute gom mốc

        res = super(PageFmConversation, self).write(vals)

        # Logic auto-bump khi có thay đổi 2 field này
        if any(k in vals for k in ('status_state', 'is_unread_fm')):
            for rec in self:
                try:
                    rec._auto_bump_require_processing()
                except Exception:
                    _logger.exception("Auto-bump require_processing failed for conv %s", rec.id)
        return res

    def _build_external_url_for_platform(self, platform, page_id, conv_id):
        ICP = self.env['ir.config_parameter'].sudo()

        # Cho phép cấu hình theo nền tảng qua system parameters
        # Token hỗ trợ trong template:
        #   {conversation}          -> nguyên chuỗi id hội thoại (vd: pzl_u_..._7961559...)
        #   {conversation_numeric}  -> chỉ phần số ở cuối (vd: 7961559...), tự động extract
        #   {page}                  -> page_id (pzl_... hoặc fb_.../số)
        tpl_default  = ICP.get_param('pancake.url_template.default')  or \
                    'https://pancake.vn/conversations/{conversation}?page_id={page}'
        tpl_zalo     = ICP.get_param('pancake.url_template.zalo')     or \
                    'https://pancake.vn/conversations/{conversation_numeric}?page_id={page}'
        tpl_facebook = ICP.get_param('pancake.url_template.facebook') or tpl_default
        tpl_instagram= ICP.get_param('pancake.url_template.instagram') or tpl_default

        # Tự động lấy phần số cuối nếu có
        m = re.search(r'(\d+)$', conv_id or '')
        conv_numeric = m.group(1) if m else (conv_id or '')

        platform = (platform or '').strip().lower()
        if platform == 'zalo':
            tpl = tpl_zalo
        elif platform == 'facebook':
            tpl = tpl_facebook
        elif platform == 'instagram':
            tpl = tpl_instagram
        else:
            # fallback: nếu conv_id có đuôi số thì template default vẫn nhận {conversation_numeric}
            tpl = tpl_default

        return tpl.format(conversation=conv_id or '', conversation_numeric=conv_numeric, page=page_id or '')


    external_url = fields.Char(string="Link Pancake", compute="_compute_external_url", store=False)

    def _compute_external_url(self):
        for r in self:
            page_id = r.conv_page_fm_id or r.page_fm_id_str_related
            conv_id = r.conversation_fm_id
            if page_id and conv_id:
                # Ưu tiên platform đã lưu từ API; nếu thiếu, suy ra nhanh theo prefix
                platform = r.platform_fm
                if not platform:
                    cid = conv_id or ''
                    pid = page_id or ''
                    if cid.startswith('pzl_') or pid.startswith('pzl_'):
                        platform = 'Zalo'
                    elif cid.startswith('fb_') or pid.startswith('fb_') or pid.isdigit():
                        platform = 'Facebook'
                    elif cid.startswith('igo_') or pid.startswith('igo_'):
                        platform = 'Instagram'
                    else:
                        platform = 'default'

                r.external_url = self._build_external_url_for_platform(platform, page_id, conv_id)
            else:
                r.external_url = False


    def action_open_on_pancake(self):
        self.ensure_one()
        url = self.external_url or '#'
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }
        
    # === BATCH & CRON SYNC =================================================
    # --- Helper: con trỏ tiến độ ---
    def _get_conv_pointer(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return int(ICP.get_param('pancake.last_conv_id', '0') or 0)

    def _set_conv_pointer(self, value):
        self.env['ir.config_parameter'].sudo().set_param('pancake.last_conv_id', str(int(value or 0)))

    def _reset_conv_pointer(self):
        """Reset con trỏ về 0 để bắt đầu đồng bộ lại từ đầu"""
        self._set_conv_pointer(0)
        _logger.info("Reset con trỏ đồng bộ conversation về 0")
        return True

    def _get_batch_size(self, batch_size=None):
        ICP = self.env['ir.config_parameter'].sudo()
        default_size = int(ICP.get_param('pancake.sync_batch_size', '50'))  # 50 mặc định
        return int(batch_size or default_size or 50)

    @api.model
    def cron_sync_conversations_batch(self, batch_size=None):
        """Đồng bộ theo batch với cơ chế reset con trỏ:
        - Pha 1: các conv mới (id > last_id) theo thứ tự tăng
        - Nếu không có conv mới → Reset con trỏ về 0 và bắt đầu lại từ đầu
        - Pha 2: phần còn lại dành cho conv cần xử lý / chưa đọc (không ảnh hưởng con trỏ)
        - Sau mỗi conv mới thành công → cập nhật con trỏ
        - Log ID cuối cùng đã đồng bộ
        """
        size = self._get_batch_size(batch_size)
        last_id = self._get_conv_pointer()
        processed = 0
        last_processed_id = last_id

        # --- PHA 1: conv mới theo con trỏ, id tăng dần ---
        new_convs = self.search([('id', '>', last_id)], order="id asc", limit=size)
        
        # *** FIX: Nếu không có conversation mới, reset con trỏ về 0 ***
        if not new_convs and last_id > 0:
            _logger.info(f"Pancake Sync: Đã đồng bộ hết conversations (pointer={last_id}). Reset về 0 để bắt đầu lại.")
            self._set_conv_pointer(0)
            last_id = 0
            last_processed_id = 0
            # Lấy lại conversations từ đầu
            new_convs = self.search([('id', '>', 0)], order="id asc", limit=size)

        # --- PHA 2: nếu còn quota, lấy conv cũ nhưng cần xử lý/chưa đọc ---
        remainder = size - len(new_convs)
        extra_convs = self.browse()
        if remainder > 0:
            extra_domain = [
                ('id', '<=', last_id),
                '|', ('require_processing', '=', True),
                    ('is_unread_fm', '=', True),
            ]
            extra_convs = self.search(
                extra_domain,
                order="last_message_sync_fm asc, updated_at_fm desc, id asc",
                limit=remainder,
            )

        # Gộp thứ tự: mới trước, rồi extra
        convs = new_convs | extra_convs
        if not convs:
            _logger.info("Pancake Sync: không có hội thoại nào cần đồng bộ. (pointer=%s)", last_id)
            return 0

        # Chạy đồng bộ
        for conv in convs:
            try:
                conv.action_sync_messages()
                self.env.cr.commit()
                processed += 1

                # Nếu đây là conv mới (id > last_id), cập nhật con trỏ dần lên
                if conv.id > last_processed_id:
                    last_processed_id = conv.id
                    self._set_conv_pointer(last_processed_id)
            except Exception:
                _logger.exception("Pancake Sync: lỗi khi sync hội thoại id=%s", conv.id)
                self.env.cr.rollback()

        _logger.info(
            "Pancake Sync: đã sync %s/%s hội thoại (pointer %s → %s). "
            "ID cuối cùng đã đồng bộ: %s",
            processed, len(convs), last_id, last_processed_id, last_processed_id
        )
        return processed

    @api.model
    def cron_sync_conversations_batch_with_circuit_breaker(self, batch_size=None):
        """Cron sync với circuit breaker - xử lý lỗi token/timeout mạnh mẽ hơn
        
        Circuit Breaker Logic:
        - Nếu có > 3 lỗi liên tiếp → tạm dừng 15 phút
        - Nếu timeout/token error → clear cache và retry
        - Rate limiting: delay giữa các request
        """
        import time
        
        # Kiểm tra circuit breaker
        circuit_key = 'page_fm_circuit_breaker_until'
        circuit_until = self.env['ir.config_parameter'].sudo().get_param(circuit_key)
        
        if circuit_until:
            circuit_datetime = datetime.fromisoformat(circuit_until)
            if datetime.now() < circuit_datetime:
                remaining = (circuit_datetime - datetime.now()).seconds // 60
                _logger.info(f"Circuit breaker active - còn {remaining} phút")
                return 0
        
        # Reset circuit breaker
        self.env['ir.config_parameter'].sudo().set_param(circuit_key, '')
        
        size = self._get_batch_size(batch_size)
        last_id = self._get_conv_pointer()
        processed = 0
        error_count = 0
        consecutive_errors = 0
        last_processed_id = last_id

        # Cho phép batch size lên đến 50, chỉ giảm nếu quá lớn
        if size > 50:
            size = 50
            _logger.info("Giảm batch size xuống 50 để tránh rate limit")
        
        _logger.info(f"Pancake Circuit Breaker Sync: sẽ xử lý tối đa {size} conversations")

        # Lấy conversations cần sync
        new_convs = self.search([('id', '>', last_id)], order="id asc", limit=size)
        
        # *** FIX: Nếu không có conversation mới, reset con trỏ về 0 ***
        if not new_convs and last_id > 0:
            _logger.info(f"Circuit Breaker Sync: Đã đồng bộ hết conversations (pointer={last_id}). Reset về 0 để bắt đầu lại.")
            self._set_conv_pointer(0)
            last_id = 0
            last_processed_id = 0
            # Lấy lại conversations từ đầu
            new_convs = self.search([('id', '>', 0)], order="id asc", limit=size)
        
        remainder = size - len(new_convs)
        extra_convs = self.browse()
        
        if remainder > 0:
            extra_domain = [
                ('id', '<=', last_id),
                '|', ('require_processing', '=', True),
                    ('is_unread_fm', '=', True),
            ]
            extra_convs = self.search(extra_domain, order="last_message_sync_fm asc", limit=remainder)

        convs = new_convs | extra_convs
        if not convs:
            _logger.info("Pancake Circuit Breaker Sync: không có hội thoại nào cần đồng bộ")
            return 0

        _logger.info(f"Pancake Circuit Breaker Sync: bắt đầu sync {len(convs)} conversations")

        for i, conv in enumerate(convs):
            try:
                # Rate limiting: delay giữa các request - giảm delay cho batch size lớn hơn
                if i > 0:
                    delay = 1.5 if len(convs) <= 50 else 2  # 1.5s cho ≤50, 2s cho >50
                    time.sleep(delay)
                
                # Sync conversation
                result = conv.action_sync_messages()
                
                if result:
                    self.env.cr.commit()
                    processed += 1
                    consecutive_errors = 0  # Reset consecutive error count
                    
                    # Cập nhật pointer cho conv mới
                    if conv.id > last_processed_id:
                        last_processed_id = conv.id
                        self._set_conv_pointer(last_processed_id)
                else:
                    _logger.warning(f"Sync failed for conversation {conv.id} - no result")
                    consecutive_errors += 1
                    
            except Exception as e:
                error_msg = str(e).lower()
                error_count += 1
                consecutive_errors += 1
                
                _logger.error(f"Circuit Breaker Sync: lỗi conversation {conv.id}: {e}")
                
                # Xử lý lỗi timeout/token đặc biệt
                if any(keyword in error_msg for keyword in ['timeout', 'token', 'rate limit', 'too many requests']):
                    _logger.warning(f"Detected timeout/token error - clearing token cache")
                    
                    # Clear token cache
                    try:
                        conv.page_fm_page_id.action_clear_token_cache()
                        time.sleep(5)  # Đợi 5 giây sau khi clear cache
                    except:
                        pass
                
                # Circuit breaker: nếu > 3 lỗi liên tiếp → dừng 15 phút
                if consecutive_errors >= 3:
                    circuit_until = (datetime.now() + timedelta(minutes=15)).isoformat()
                    self.env['ir.config_parameter'].sudo().set_param(circuit_key, circuit_until)
                    
                    _logger.error(f"Circuit breaker TRIGGERED after {consecutive_errors} consecutive errors - pausing for 15 minutes")
                    break
                
                # Rollback và tiếp tục với conversation tiếp theo
                self.env.cr.rollback()
                time.sleep(3)  # Delay lâu hơn sau lỗi

        final_message = (f"Circuit Breaker Sync completed: {processed}/{len(convs)} success, "
                        f"{error_count} errors, pointer: {last_id} → {last_processed_id}")
        
        if consecutive_errors >= 3:
            final_message += f" - CIRCUIT BREAKER ACTIVE (15 min pause)"
        
        _logger.info(final_message)
        return processed


       # --- NEW: helper hiển thị thông báo ---
    def _notify(self, title, message, notif_type='warning'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': False,
            }
        }

    # --- NEW: mở form khách hàng ---
    def action_open_partner(self):
        self.ensure_one()
        if not self.partner_id:
            return self._notify(_('Chưa có khách hàng'), _('Hội thoại này chưa liên kết khách hàng.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Khách hàng'),
            'res_model': 'res.partner',
            'view_mode': 'form',
            'res_id': self.partner_id.id,
            'target': 'current',
        }

    # --- NEW: mở danh sách đơn hàng của khách (bao gồm cả công ty mẹ) ---
    def action_open_partner_orders(self):
        self.ensure_one()
        if not self.partner_id:
            return self._notify(_('Chưa có khách hàng'), _('Hội thoại này chưa liên kết khách hàng.'))
        commercial = self.partner_id.commercial_partner_id
        domain = [('partner_id', 'child_of', commercial.id)]
        count = self.env['sale.order'].search_count(domain)
        if not count:
            return self._notify(_('Chưa có đơn hàng'), _('Khách hàng này chưa có đơn hàng nào trên hệ thống.'))
        action = self.env.ref('sale.action_orders').read()[0]
        action['domain'] = domain
        action['context'] = {'search_default_customer': commercial.id}
        return action
    
    
    
    # Dành cho người phụ trách
    owner_id = fields.Many2one(
        'res.users', string="Người phụ trách", index=True, copy=False, tracking=True
    )
    participant_user_ids = fields.Many2many(
        'res.users',
        'page_fm_conv_user_rel', 'conv_id', 'user_id',
        string="Nhóm phụ trách", copy=False, tracking=True
    )

    def _recompute_staff_links(self):
        """Gán owner/participants từ message NHƯNG chỉ khi đang TRỐNG.
        Không xóa/đè giá trị đã gán tay.
        """
        Message = self.env['page.fm.message'].sudo()
        Users   = self.env['res.users'].sudo()

        for rec in self:
            need_owner        = not rec.owner_id
            need_participants = not rec.participant_user_ids

            # nếu cả 2 đều đã có -> bỏ qua
            if not (need_owner or need_participants):
                continue

            # lấy tin có staff mới nhất (để đề xuất owner)
            last_staff_msg = False
            if need_owner:
                last_staff_msg = Message.search(
                    [('conversation_id', '=', rec.id), ('staff', '!=', False)],
                    order='inserted_at_fm desc, id desc', limit=1
                )

            # lấy full danh sách staff đã từng nhắn (để làm participants)
            candidates = Users.browse()
            if need_participants:
                rows = Message.read_group(
                    [('conversation_id', '=', rec.id), ('staff', '!=', False)],
                    ['staff'], ['staff']
                )
                if rows:
                    # rows[i]['staff'] = [id, display_name]
                    candidates = Users.browse([r['staff'][0] for r in rows if r.get('staff')])

            vals = {}
            if need_owner and last_staff_msg and last_staff_msg.staff:
                vals['owner_id'] = last_staff_msg.staff.id

            if need_participants and candidates:
                vals['participant_user_ids'] = [(6, 0, candidates.ids)]

            if vals:
                rec.write(vals)

    def action_assign_to_me(self):
        for rec in self:
            rec.owner_id = self.env.user.id
        return True
    
    
            
    # Cho cuộc trò chuyện nội bộ
    is_internal_conversation = fields.Boolean(
        string="Cuộc trò chuyện nội bộ",
        default=False,
        tracking=True,
        help="Đánh dấu cuộc trò chuyện này là nội bộ, không hiển thị với nhân viên bán hàng."
    )
    
    
    # Mốc hoạt động cuối
    last_update_at = fields.Datetime(
        string="Cập nhật lần cuối",
        compute="_compute_last_update_at",
        store=True,
        index=True,
        help="Mốc cập nhật gần nhất: mọi thay đổi trên form, sync/POST n8n, đổi trạng thái, ghi chú,..."
    )

    @api.depends(
        'updated_at_fm',          # từ API
        'last_message_sync_fm',   # lần sync gần nhất
        'last_suggestion_at',     # n8n/AI/ghi chú
        'status_set_at',          # đổi trạng thái
        'updated_at_fm_by_hand',  # cập nhật thủ công
    )
    def _compute_last_update_at(self):
        for r in self:
            candidates = [
                r.updated_at_fm,
                r.last_message_sync_fm,
                r.last_suggestion_at,
                r.status_set_at,
                r.updated_at_fm_by_hand,
            ]
            r.last_update_at = max([c for c in candidates if c]) if any(candidates) else False
            
            
    @api.onchange('owner_id')
    def _onchange_owner_push_to_participants(self):
        """Khi người dùng chọn/chỉnh owner trên form:
        - Không đụng gì khác
        - Chỉ đảm bảo owner có mặt trong participant_user_ids
        """
        for rec in self:
            if rec.owner_id and rec.owner_id not in rec.participant_user_ids:
                rec.participant_user_ids |= rec.owner_id

    # === Methods for view buttons ===
    
    def action_refresh_conversation(self):
        """Refresh conversation data from Pages.fm"""
        for record in self:
            if record.conversation_fm_id:
                try:
                    # Sync lại conversation này từ API
                    self.env['page.fm.conversation'].with_context(
                        force_sync_conversation_id=record.conversation_fm_id
                    ).sync_all_conversations_scheduled()
                    # Show success message
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Success'),
                            'message': _('Conversation refreshed successfully'),
                            'type': 'success'
                        }
                    }
                except Exception as e:
                    _logger.error(f"Error refreshing conversation {record.conversation_fm_id}: {e}")
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Error'),
                            'message': _('Error refreshing conversation: %s') % str(e),
                            'type': 'danger'
                        }
                    }

    def action_mark_as_read(self):
        """Mark conversation as read"""
        for record in self:
            record.write({'is_unread': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Conversation(s) marked as read'),
                'type': 'success'
            }
        }

    def action_mark_as_unread(self):
        """Mark conversation as unread"""
        for record in self:
            record.write({'is_unread': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Conversation(s) marked as unread'),
                'type': 'success'
            }
        }

    def action_sync_messages_button(self):
        """Nút sync tin nhắn cho form - có thông báo và reload"""
        for record in self:
            try:
                _logger.info(f"Bắt đầu sync tin nhắn cho conversation {record.id} ({record.name})")
                result = record.action_sync_messages()
                
                # Hiển thị thông báo thành công và reload
                self.env.cr.commit()  # Đảm bảo dữ liệu được lưu
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            except Exception as e:
                _logger.error(f"Lỗi khi sync tin nhắn cho conversation {record.id}: {e}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification', 
                    'params': {
                        'title': 'Lỗi đồng bộ',
                        'message': f'Lỗi: {str(e)}',
                        'type': 'danger'
                    }
                }

    def action_debug_conversation(self):
        """Debug conversation - hiển thị thông tin hữu ích"""
        self.ensure_one()
        
        # Lấy thông tin debug
        main_token = self.env['ir.config_parameter'].sudo().get_param('page_fm.access_token')
        page_token = None
        
        try:
            if self.page_fm_page_id and main_token:
                page_token = self.page_fm_page_id._generate_page_specific_access_token(main_token)
        except Exception as e:
            page_token = f"Error: {e}"
        
        message = f"""
📋 Thông tin Debug:
• Conversation ID: {self.conversation_fm_id}
• Customer ID: {self.customer_fm_id}
• Page ID: {self.page_fm_id_str_related}
• Platform: {self.platform_fm}
• Message Count: {self.message_count}
• Last Sync: {self.last_message_sync_fm or 'Chưa sync'}
• Main Token: {'✅ Có' if main_token else '❌ Thiếu'}
• Page Token: {'✅ Có' if page_token and 'Error' not in str(page_token) else f'❌ {page_token}'}
        """
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '🔍 Debug Info',
                'message': message,
                'type': 'info',
                'sticky': True
            }
        }

    def action_sync_all_conversations_force(self):
        """Force sync ALL conversations without any filters"""
        all_conversations = self.env['page.fm.conversation'].search([])
        
        if not all_conversations:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Data'),
                    'message': _('No conversations found in system!'),
                    'type': 'warning'
                }
            }
        
        _logger.info(f"FORCE SYNC: Starting sync for ALL {len(all_conversations)} conversations...")
        
        synced_count = 0
        error_count = 0
        
        for conv in all_conversations:
            try:
                customer_name = getattr(conv, 'customer_name_fm', None) or getattr(conv, 'name', None) or f"Conversation {conv.id}"
                
                # Get page info
                page = conv.page_fm_page_id
                if not page:
                    _logger.warning(f"Conversation {conv.id} ({customer_name}) không có page liên kết")
                    error_count += 1
                    continue
                
                try:
                    # Sync messages using existing method
                    result = conv.action_sync_messages()
                    message_count = conv.message_count
                    
                    _logger.info(f"✓ FORCE SYNC: {message_count} tin nhắn cho cuộc hội thoại: {customer_name}")
                    
                    conv.updated_at_fm_by_hand = datetime.now()
                    synced_count += 1
                    self.env.cr.commit()
                    
                except Exception as sync_error:
                    _logger.error(f"FORCE SYNC error for conversation {conv.id} ({customer_name}): {sync_error}")
                    error_count += 1
                    self.env.cr.rollback()
                    
            except Exception as e:
                customer_name = getattr(conv, 'customer_name_fm', None) or f"Conversation {conv.id}"
                _logger.error(f"FORCE SYNC outer error for conversation {conv.id} ({customer_name}): {e}")
                error_count += 1
                self.env.cr.rollback()
        
        _logger.info(f"FORCE SYNC finished: {synced_count} thành công, {error_count} lỗi từ tổng {len(all_conversations)} conversations.")
        
        # Sau khi sync xong, reload để hiển thị dữ liệu mới
        self.env.cr.commit()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_clear_token_cache(self):
        """Xóa token cache để giải quyết vấn đề timeout"""
        if hasattr(self, 'page_fm_page_id') and self.page_fm_page_id:
            self.page_fm_page_id.clear_token_cache()
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }
        else:
            # Clear all cache
            self.env['page.fm.page'].clear_all_token_cache()
            return {
                'type': 'ir.actions.client', 
                'tag': 'reload',
            }

