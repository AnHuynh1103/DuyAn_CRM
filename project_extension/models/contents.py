from odoo import models, fields , api

class Content(models.Model):
    _name = 'project.contents'
    _description = 'Quản lý nội dung dự án'

    title = fields.Char('Tiêu đề', required=True)
    description = fields.Text('Nội dung')
    content_id = fields.Many2one('project.task', string='Task liên quan')

    # Trường trạng thái với các lựa chọn cụ thể
    state = fields.Selection([
        ('new', 'New'),
        ('in_researching', 'In Researching'),
        ('researched', 'Researched'),
        ('in_writing', 'In Writing'),
        ('writed', 'Writed'),
        ('approving', 'Approving'),
        ('done', 'Done'),
        ('posting', 'Posting'),
        ('close', 'Close'),
    ], string='Giai đoạn', default='new', group_expand='_expand_states')

    # Người thực hiện và người chịu trách nhiệm
    executor_id = fields.Many2one('res.users', string='Người thực hiện')
    responsible_id = fields.Many2one('res.users', string='Người chịu trách nhiệm')

    # Từ khóa chính và phụ
    main_keyword = fields.Char('Từ khóa chính')
    sub_keywords = fields.Char('Từ khóa phụ')

    # Liên kết bài viết và bài đăng
    article_link = fields.Char('Link bài viết')
    post_link = fields.Char('Link bài đăng')

    @api.model
    def _expand_states(self, states, domain, order):
        return [key for key, _ in self._fields['state'].selection]