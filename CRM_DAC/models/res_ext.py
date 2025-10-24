from odoo import models, fields, api, _

class ResUsers(models.Model):
    _inherit = 'res.users'
    
    # Field chính - đang dùng trong code
    pancake_id = fields.Char(string="Pancake Admin ID", index=True, copy=False)

    
    # Field mới - phân biệt rõ ràng 2 loại ID
    pancake_uuid = fields.Char(string="Pancake UUID (Đúng)", index=True, copy=False,
                                help="UUID từ creator.id - Định dạng: bd901904-38fd-4e4d-a839-1adc1e651f54")
    pancake_number_id = fields.Char(string="Pancake number ID (Số)", index=True, copy=False,
                                 help="id số - Định dạng: 741331342729875")

class ResPartner(models.Model):
    _inherit = 'res.partner'
    pancake_id = fields.Char(string="Pancake Customer ID", index=True, copy=False)
    
    conversation_ids = fields.One2many(
        'page.fm.conversation', 'partner_id', string='Conversations'
    )
    conversation_count = fields.Integer(
        string='Conversations', compute='_compute_conversation_count'
    )
    is_pancake_customer = fields.Boolean(
        string='Khách từ Pancake', compute='_compute_is_pancake_customer'
    )

    def _compute_conversation_count(self):
        read_group = self.env['page.fm.conversation'].read_group(
            [('partner_id', 'in', self.ids)],
            ['partner_id'], ['partner_id']
        )
        map_count = {r['partner_id'][0]: r['partner_id_count'] for r in read_group}
        for p in self:
            p.conversation_count = map_count.get(p.id, 0)

    def _compute_is_pancake_customer(self):
        for p in self:
            p.is_pancake_customer = bool(p.conversation_count)

    def action_view_conversations(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Conversations'),
            'res_model': 'page.fm.conversation',
            'view_mode': 'list,form',
            'target': 'current',
            'domain': [('partner_id', 'child_of', self.commercial_partner_id.id)],
            'context': {'search_default_partner_id': self.id},
        }
        return action

    def action_view_partner_orders(self):
        self.ensure_one()
        commercial = self.commercial_partner_id
        domain = [('partner_id', 'child_of', commercial.id)]
        count = self.env['sale.order'].search_count(domain)
        if not count:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Chưa có đơn hàng'),
                    'message': _('Khách hàng này chưa có đơn hàng nào trên hệ thống.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        # Sử dụng action custom của DAC thay vì action gốc của Odoo
        action = self.env.ref('dac_erp.dac_sale_order_custom_action').read()[0]
        action['domain'] = domain
        action['context'] = {'search_default_partner_id': commercial.id}
        return action
    
    
    responsible_user_id = fields.Many2one(
        'res.users', string="Người phụ trách (Pancake)", index=True, copy=False
    )
    participant_user_ids = fields.Many2many(
        'res.users', 'res_partner_conv_user_rel', 'partner_id', 'user_id',
        string="Nhóm phụ trách (Pancake)", copy=False
    )

    def sync_staff_from_conversations(self):
        """Đẩy owner/participants mới nhất từ hội thoại sang khách hàng."""
        Conv = self.env['page.fm.conversation'].sudo()
        for partner in self:
            conv = Conv.search(
                [('partner_id', '=', partner.id)],
                order='updated_at_fm desc, id desc', limit=1
            )
            vals = {}
            if conv:
                vals['responsible_user_id'] = conv.owner_id.id or False
                vals['participant_user_ids'] = [(6, 0, conv.participant_user_ids.ids)]
            if vals:
                partner.write(vals)
                
    _sql_constraints = [
        ('pancake_id_company_uniq',
        'unique(pancake_id, company_id)',
        'Pancake Customer ID must be unique per company.')
    ]