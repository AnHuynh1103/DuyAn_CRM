from odoo import models, fields

class ResUsers(models.Model):
    _inherit = 'res.users'
    pancake_id = fields.Char(string="Pancake Admin ID", index=True, copy=False)

class ResPartner(models.Model):
    _inherit = 'res.partner'
    pancake_id = fields.Char(string="Pancake Customer ID", index=True, copy=False)
    