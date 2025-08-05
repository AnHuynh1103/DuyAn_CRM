import json
import logging
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PancakeAPIController(http.Controller):
    """Controller for Pancake API integration"""

    @http.route('/dac_erp/pancake/sync_all', type='http', auth='user', methods=['GET', 'POST'])
    def sync_all_pages_conversations(self):
        """API để đồng bộ tất cả pages và conversations từ Pancake"""
        try:
            result = request.env['pancake.page'].sync_all_pages_and_conversations()
            
            return request.make_response(
                json.dumps({
                    'status': 'success', 
                    'message': 'Đồng bộ thành công từ Pancake',
                    'result': result
                }),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            _logger.error(f"Lỗi đồng bộ Pancake: {e}")
            response = request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers={'Content-Type': 'application/json'}
            )
            response.status_code = 500
            return response

    @http.route('/dac_erp/pancake/pages', type='http', auth='user', methods=['GET'])
    def get_all_pages(self):
        """API để lấy tất cả pages từ Pancake"""
        try:
            pages = request.env['pancake.page'].search([])
            pages_data = []
            
            for page in pages:
                pages_data.append({
                    'id': page.id,
                    'name': page.name,
                    'page_id': page.page_id,
                    'active': page.active,
                    'conversation_count': page.conversation_count,
                })
            
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'pages': pages_data
                }),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            _logger.error(f"Lỗi lấy pages: {e}")
            response = request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers={'Content-Type': 'application/json'}
            )
            response.status_code = 500
            return response

    @http.route('/dac_erp/pancake/pages/<int:page_id>/conversations', type='http', auth='user', methods=['GET'])
    def get_page_conversations(self, page_id):
        """API để lấy conversations của một page"""
        try:
            page = request.env['pancake.page'].browse(page_id)
            if not page.exists():
                response = request.make_response(
                    json.dumps({'status': 'error', 'message': 'Page không tồn tại'}),
                    headers={'Content-Type': 'application/json'}
                )
                response.status_code = 404
                return response
            
            conversations_data = []
            for conv in page.conversation_ids:
                conversations_data.append({
                    'id': conv.id,
                    'conversation_id': conv.conversation_id,
                    'customer_name': conv.customer_name,
                    'customer_email': conv.customer_email,
                    'customer_phone': conv.customer_phone,
                    'platform': conv.platform,
                    'conversation_type': conv.conversation_type,
                    'last_message_content': conv.last_message_content,
                    'last_message_time': conv.last_message_time.isoformat() if conv.last_message_time else None,
                    'last_message_sender': conv.last_message_sender,
                    'message_count': conv.message_count,
                    'partner_id': conv.partner_id.id if conv.partner_id else None,
                })
            
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'page_name': page.name,
                    'conversations': conversations_data
                }),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            _logger.error(f"Lỗi lấy conversations: {e}")
            response = request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers={'Content-Type': 'application/json'}
            )
            response.status_code = 500
            return response

    @http.route('/dac_erp/pancake/conversations/<int:conversation_id>/messages', type='http', auth='user', methods=['GET'])
    def get_conversation_messages(self, conversation_id):
        """API để lấy messages của một conversation"""
        try:
            conversation = request.env['pancake.page.conversation'].browse(conversation_id)
            if not conversation.exists():
                response = request.make_response(
                    json.dumps({'status': 'error', 'message': 'Conversation không tồn tại'}),
                    headers={'Content-Type': 'application/json'}
                )
                response.status_code = 404
                return response
            
            messages_data = []
            for msg in conversation.message_ids:
                messages_data.append({
                    'id': msg.id,
                    'message_id': msg.message_id,
                    'sender_name': msg.sender_name,
                    'is_from_customer': msg.is_from_customer,
                    'message_type': msg.message_type,
                    'content': msg.content,
                    'inserted_at': msg.inserted_at.isoformat() if msg.inserted_at else None,
                    'has_phone': msg.has_phone,
                })
            
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'conversation_customer': conversation.customer_name,
                    'messages': messages_data
                }),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            _logger.error(f"Lỗi lấy messages: {e}")
            response = request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers={'Content-Type': 'application/json'}
            )
            response.status_code = 500
            return response

    @http.route('/dac_erp/pancake/conversations/<int:conversation_id>/sync_messages', type='http', auth='user', methods=['POST'])
    def sync_conversation_messages(self, conversation_id):
        """API để đồng bộ messages của một conversation"""
        try:
            conversation = request.env['pancake.page.conversation'].browse(conversation_id)
            if not conversation.exists():
                response = request.make_response(
                    json.dumps({'status': 'error', 'message': 'Conversation không tồn tại'}),
                    headers={'Content-Type': 'application/json'}
                )
                response.status_code = 404
                return response
            
            messages = conversation.fetch_messages()
            
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'message': f'Đồng bộ thành công {len(messages)} tin nhắn',
                    'synced_messages': len(messages)
                }),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            _logger.error(f"Lỗi đồng bộ messages: {e}")
            response = request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers={'Content-Type': 'application/json'}
            )
            response.status_code = 500
            return response

    @http.route('/dac_erp/pancake/conversations/<int:conversation_id>/create_partner', type='http', auth='user', methods=['POST'])
    def create_partner_from_conversation(self, conversation_id):
        """API để tạo partner từ conversation"""
        try:
            conversation = request.env['pancake.page.conversation'].browse(conversation_id)
            if not conversation.exists():
                response = request.make_response(
                    json.dumps({'status': 'error', 'message': 'Conversation không tồn tại'}),
                    headers={'Content-Type': 'application/json'}
                )
                response.status_code = 404
                return response
            
            if conversation.partner_id:
                return request.make_response(
                    json.dumps({
                        'status': 'info',
                        'message': 'Partner đã tồn tại',
                        'partner_id': conversation.partner_id.id,
                        'partner_name': conversation.partner_id.name
                    }),
                    headers={'Content-Type': 'application/json'}
                )
            
            partner = conversation.create_partner()
            
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'message': 'Tạo partner thành công',
                    'partner_id': partner.id,
                    'partner_name': partner.name
                }),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            _logger.error(f"Lỗi tạo partner: {e}")
            response = request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers={'Content-Type': 'application/json'}
            )
            response.status_code = 500
            return response

    @http.route('/dac_erp/pancake/pages/<int:page_id>/sync_conversations', type='http', auth='user', methods=['POST'])
    def sync_page_conversations(self, page_id):
        """API để đồng bộ conversations của một page"""
        try:
            page = request.env['pancake.page'].browse(page_id)
            if not page.exists():
                response = request.make_response(
                    json.dumps({'status': 'error', 'message': 'Page không tồn tại'}),
                    headers={'Content-Type': 'application/json'}
                )
                response.status_code = 404
                return response
            
            conversations = page.fetch_conversations()
            
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'message': f'Đồng bộ thành công {len(conversations)} cuộc hội thoại',
                    'synced_conversations': len(conversations)
                }),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            _logger.error(f"Lỗi đồng bộ conversations: {e}")
            response = request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers={'Content-Type': 'application/json'}
            )
            response.status_code = 500
            return response
