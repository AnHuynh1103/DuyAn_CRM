# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home
from werkzeug.urls import url_encode
import logging

_logger = logging.getLogger(__name__)

class BeeoneHome(Home):
    """
    Controller để chặn debug mode cho non-admin users
    Mục đích: Bảo mật hệ thống, ngăn user thường bật debug mode
    """
    
    # Override cả /web và /odoo routes
    @http.route(['/web', '/odoo', '/odoo/<path:subpath>'], type='http', auth='none')
    def web_client(self, s_action=None, subpath=None, **kw):
        """Override /web và /odoo routes để kiểm tra và xóa debug params/cookies"""
        try:
            # Kiểm tra xem user đã login chưa
            if request.session.uid:
                user = request.env.user
                
                # Chỉ áp dụng cho non-admin users
                if not user.has_group('base.group_system'):
                    req = request.httprequest
                    args = dict(req.args)
                    has_debug_param = False
                    
                    # Kiểm tra và loại bỏ debug parameters
                    for param_name in ('debug', 'debugMode'):
                        if param_name in args:
                            args.pop(param_name, None)
                            has_debug_param = True
                            _logger.info(f"======= Debug param '{param_name}' blocked for user: {user.name}")
                    
                    # Nếu có debug param, redirect về URL sạch
                    if has_debug_param:
                        clean_query = url_encode(args) if args else ""
                        # Rebuild URL với subpath nếu có
                        if subpath:
                            clean_url = f"/odoo/{subpath}" + (("?" + clean_query) if clean_query else "")
                        else:
                            clean_url = req.path + (("?" + clean_query) if clean_query else "")
                        
                        resp = request.redirect(clean_url, 303)
                        
                        # Xóa tất cả debug cookies
                        for cookie_name in ('debug', 'odoo-debug', 'debugMode'):
                            resp.delete_cookie(cookie_name, path='/')
                            _logger.info(f"====== Debug cookie '{cookie_name}' deleted for user: {user.name}")
                        
                        return resp

            # Gọi parent method để render trang bình thường
            resp = super().web_client(s_action=s_action, subpath=subpath, **kw)

            # Double-check: Luôn xóa debug cookies cho non-admin
            if request.session.uid and not request.env.user.has_group('base.group_system'):
                for cookie_name in ('debug', 'odoo-debug', 'debugMode'):
                    resp.delete_cookie(cookie_name, path='/')
            
            return resp
            
        except Exception as e:
            _logger.error(f"======= Error in debug_guard controller: {str(e)}")
            # Fallback to parent if error
            return super().web_client(s_action=s_action, subpath=subpath, **kw)
            return super().web_client(s_action=s_action, **kw)
