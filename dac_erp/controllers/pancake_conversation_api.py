# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class PancakeConversationAPIController(http.Controller):

    @http.route('/dac_erp/pancake/conversations', type='http', auth='user', methods=['GET'], csrf=False)
    def get_conversations(self, **kwargs):
        """
        API để lấy danh sách cuộc hội thoại từ Pancake
        URL: /dac_erp/pancake/conversations
        Method: GET
        Parameters:
        - page: Trang (mặc định 1)
        - limit: Số lượng bản ghi trên mỗi trang (mặc định 20)
        - shop_id: ID của shop (optional, lấy từ config nếu không có)
        """
        try:
            # Lấy parameters
            page = int(kwargs.get('page', 1))
            limit = int(kwargs.get('limit', 20))
            shop_id = kwargs.get('shop_id')
            
            # Lấy API key và shop_id từ config nếu không được cung cấp
            api_key = request.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
            if not shop_id:
                shop_id = request.env['ir.config_parameter'].sudo().get_param('pancake.shop_id')
            
            if not api_key:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'Pancake API Key chưa được cấu hình'}),
                    headers={'Content-Type': 'application/json'},
                    status=400
                )
            
            if not shop_id:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'Pancake Shop ID chưa được cấu hình'}),
                    headers={'Content-Type': 'application/json'},
                    status=400
                )
            
            # Gọi API Pancake để lấy cuộc hội thoại
            conversations_data = self._fetch_pancake_conversations(api_key, shop_id, page, limit)
            
            if conversations_data is None:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'Không thể lấy dữ liệu từ Pancake API'}),
                    headers={'Content-Type': 'application/json'},
                    status=500
                )
            
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'data': conversations_data,
                    'page': page,
                    'limit': limit
                }, indent=2),
                headers={'Content-Type': 'application/json'},
                status=200
            )
            
        except Exception as e:
            _logger.error(f"Lỗi trong API get_conversations: {e}", exc_info=True)
            return request.make_response(
                json.dumps({'status': 'error', 'message': f'Lỗi server: {str(e)}'}),
                headers={'Content-Type': 'application/json'},
                status=500
            )

    @http.route('/dac_erp/pancake/conversations/<string:conversation_id>', type='http', auth='user', methods=['GET'], csrf=False)
    def get_conversation_detail(self, conversation_id, **kwargs):
        """
        API để lấy chi tiết một cuộc hội thoại cụ thể từ Pancake
        URL: /dac_erp/pancake/conversations/{conversation_id}
        Method: GET
        Parameters:
        - conversation_id: ID của cuộc hội thoại
        - shop_id: ID của shop (optional, lấy từ config nếu không có)
        """
        try:
            shop_id = kwargs.get('shop_id')
            
            # Lấy API key và shop_id từ config nếu không được cung cấp
            api_key = request.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
            if not shop_id:
                shop_id = request.env['ir.config_parameter'].sudo().get_param('pancake.shop_id')
            
            if not api_key or not shop_id:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'Pancake API Key hoặc Shop ID chưa được cấu hình'}),
                    headers={'Content-Type': 'application/json'},
                    status=400
                )
            
            # Gọi API Pancake để lấy chi tiết cuộc hội thoại
            conversation_data = self._fetch_pancake_conversation_detail(api_key, shop_id, conversation_id)
            
            if conversation_data is None:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'Không thể lấy dữ liệu chi tiết cuộc hội thoại'}),
                    headers={'Content-Type': 'application/json'},
                    status=500
                )
            
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'data': conversation_data
                }, indent=2),
                headers={'Content-Type': 'application/json'},
                status=200
            )
            
        except Exception as e:
            _logger.error(f"Lỗi trong API get_conversation_detail: {e}", exc_info=True)
            return request.make_response(
                json.dumps({'status': 'error', 'message': f'Lỗi server: {str(e)}'}),
                headers={'Content-Type': 'application/json'},
                status=500
            )

    @http.route('/dac_erp/pancake/conversations/<string:conversation_id>/messages', type='http', auth='user', methods=['GET'], csrf=False)
    def get_conversation_messages(self, conversation_id, **kwargs):
        """
        API để lấy tin nhắn của một cuộc hội thoại cụ thể từ Pancake
        URL: /dac_erp/pancake/conversations/{conversation_id}/messages
        Method: GET
        Parameters:
        - conversation_id: ID của cuộc hội thoại
        - page: Trang (mặc định 1)
        - limit: Số lượng tin nhắn trên mỗi trang (mặc định 50)
        - shop_id: ID của shop (optional)
        """
        try:
            page = int(kwargs.get('page', 1))
            limit = int(kwargs.get('limit', 50))
            shop_id = kwargs.get('shop_id')
            
            # Lấy API key và shop_id từ config nếu không được cung cấp
            api_key = request.env['ir.config_parameter'].sudo().get_param('pancake.api_key')
            if not shop_id:
                shop_id = request.env['ir.config_parameter'].sudo().get_param('pancake.shop_id')
            
            if not api_key or not shop_id:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'Pancake API Key hoặc Shop ID chưa được cấu hình'}),
                    headers={'Content-Type': 'application/json'},
                    status=400
                )
            
            # Gọi API Pancake để lấy tin nhắn cuộc hội thoại
            messages_data = self._fetch_pancake_conversation_messages(api_key, shop_id, conversation_id, page, limit)
            
            if messages_data is None:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'Không thể lấy tin nhắn cuộc hội thoại'}),
                    headers={'Content-Type': 'application/json'},
                    status=500
                )
            
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'data': messages_data,
                    'conversation_id': conversation_id,
                    'page': page,
                    'limit': limit
                }, indent=2),
                headers={'Content-Type': 'application/json'},
                status=200
            )
            
        except Exception as e:
            _logger.error(f"Lỗi trong API get_conversation_messages: {e}", exc_info=True)
            return request.make_response(
                json.dumps({'status': 'error', 'message': f'Lỗi server: {str(e)}'}),
                headers={'Content-Type': 'application/json'},
                status=500
            )

    def _fetch_pancake_conversations(self, api_key, shop_id, page=1, limit=20):
        """
        Gọi API Pancake để lấy danh sách cuộc hội thoại
        """
        try:
            # URL API Pancake cho cuộc hội thoại (cần cập nhật theo tài liệu chính thức)
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/conversations"
            
            params = {
                'api_key': api_key,
                'page': page,
                'per_page': limit
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            _logger.info(f"Gọi Pancake API: {api_url} với params: {params}")
            
            response = requests.get(api_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            _logger.info(f"Nhận được dữ liệu cuộc hội thoại từ Pancake: {len(data.get('data', []))} cuộc hội thoại")
            
            return data
            
        except requests.exceptions.RequestException as e:
            _logger.error(f"Lỗi khi gọi API Pancake conversations: {e}")
            return None
        except Exception as e:
            _logger.error(f"Lỗi không xác định khi fetch conversations: {e}")
            return None

    def _fetch_pancake_conversation_detail(self, api_key, shop_id, conversation_id):
        """
        Gọi API Pancake để lấy chi tiết một cuộc hội thoại
        """
        try:
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/conversations/{conversation_id}"
            
            params = {
                'api_key': api_key
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            _logger.info(f"Gọi Pancake API chi tiết cuộc hội thoại: {api_url}")
            
            response = requests.get(api_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            _logger.info(f"Nhận được chi tiết cuộc hội thoại {conversation_id} từ Pancake")
            
            return data
            
        except requests.exceptions.RequestException as e:
            _logger.error(f"Lỗi khi gọi API Pancake conversation detail: {e}")
            return None
        except Exception as e:
            _logger.error(f"Lỗi không xác định khi fetch conversation detail: {e}")
            return None

    def _fetch_pancake_conversation_messages(self, api_key, shop_id, conversation_id, page=1, limit=50):
        """
        Gọi API Pancake để lấy tin nhắn của một cuộc hội thoại
        """
        try:
            api_url = f"https://pos.pages.fm/api/v1/shops/{shop_id}/conversations/{conversation_id}/messages"
            
            params = {
                'api_key': api_key,
                'page': page,
                'per_page': limit
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            _logger.info(f"Gọi Pancake API tin nhắn cuộc hội thoại: {api_url}")
            
            response = requests.get(api_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            _logger.info(f"Nhận được {len(data.get('data', []))} tin nhắn từ cuộc hội thoại {conversation_id}")
            
            return data
            
        except requests.exceptions.RequestException as e:
            _logger.error(f"Lỗi khi gọi API Pancake conversation messages: {e}")
            return None
        except Exception as e:
            _logger.error(f"Lỗi không xác định khi fetch conversation messages: {e}")
            return None
