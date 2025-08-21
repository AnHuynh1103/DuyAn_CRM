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
    
    
    # ==== STATUS FIELDS (OPTIMIZED) ====
    status_state = fields.Selection([
        ('new', 'Tin mới'),
        ('recontact', 'Chăm lại khách'),
        ('waiting', 'Đợi khách phản hồi'),
        ('done', 'Đã xử lý'),
    ], string="Trạng thái", default='new', index=True, tracking=True)

    # UNIFIED: Chỉ dùng suggestion_note cho mọi loại ghi chú (từ AI, manual, hoặc status note)
    suggestion_note = fields.Text(string="Ghi chú & Gợi ý xử lý", help="Ghi chú trạng thái, gợi ý từ AI hoặc external system")
    last_suggestion_at = fields.Datetime(string="Thời điểm cập nhật ghi chú")
    
    status_set_by_id = fields.Many2one('res.users', "Người cập nhật", tracking=True)
    status_set_at = fields.Datetime("Thời điểm cập nhật", tracking=True)

    # UNIFIED: Chỉ dùng require_processing - tự động quản lý logic checklist
    require_processing = fields.Boolean(string="Có yêu cầu xử lý", default=False, index=True, tracking=True)

    # COMPUTED: status_label được tính toán thay vì lưu trữ
    status_label = fields.Char(string="Nhãn trạng thái", compute='_compute_status_label', help="Text hiển thị trạng thái")

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

        # Khi tắt require_processing => coi như đã xử lý
        if not new_val:
            vals.update({
                'status_state': 'done',
            })
        else:
            # Khi bật lại => trạng thái về new nếu cần
            if self.status_state == 'done':
                vals['status_state'] = 'new'

        self.write(vals)
        
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
        """Áp dụng quy tắc trạng thái tự động dựa vào tin nhắn."""
        Message = self.env['page.fm.message'].sudo()
        for c in self:
            # Lấy tin nhắn cuối và người gửi
            last_msg = Message.search([('conversation_id', '=', c.id)], limit=1,
                                    order='inserted_at_fm desc' if 'inserted_at_fm' in Message._fields else 'id desc')
            
            vals = {}
            if getattr(c, 'is_unread_fm', False):
                # Có tin chưa đọc -> tin mới, cần xử lý
                vals.update({'status_state': 'new', 'require_processing': True})
            elif last_msg and (last_msg.sender_name_fm and not last_msg.staff_name_fm):
                # Tin cuối là của khách -> chăm lại khách, cần xử lý
                vals.update({'status_state': 'recontact', 'require_processing': True})
            elif last_msg and last_msg.staff_name_fm:
                # Tin cuối là của staff -> chờ khách phản hồi, không cần xử lý ngay
                vals.update({'status_state': 'waiting', 'require_processing': False})
            else:
                # Không có tin nhắn hoặc trường hợp khác -> đã xử lý
                vals.update({'status_state': 'done', 'require_processing': False})
            
            if vals:
                c.sudo().write(vals)
                # Đảm bảo require_processing được cập nhật theo logic
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
        #_logger.info("------------------------------------------->Hello")
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
        result = super().write(vals)
        # Tự động cập nhật require_processing khi thay đổi trạng thái hoặc unread
        if any(key in vals for key in ['status_state', 'is_unread_fm']):
            for rec in self:
                try:
                    rec._auto_bump_require_processing()
                except Exception as e:
                    _logger.error(f"Lỗi khi update require_processing cho conversation {rec.id}: {e}")
        return result


    external_url = fields.Char(string="Link Pancake", compute="_compute_external_url", store=False)

    def _compute_external_url(self):
        ICP = self.env['ir.config_parameter'].sudo()
        # Cho phép override bằng system parameter
        tmpl = ICP.get_param(
            'pancake.conversation_url_template',
            # Template mặc định (bạn đổi cho đúng môi trường nếu cần)
            default='https://pages.fm/conversations/{conversation_fm_id}?page_id={page_fm_id_str}'
        )
        for r in self:
            if r.conversation_fm_id and r.page_fm_id_str_related:
                r.external_url = tmpl.format(
                    conversation_fm_id=r.conversation_fm_id,
                    page_fm_id_str=r.page_fm_id_str_related
                )
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