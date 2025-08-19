# -*- coding: utf-8 -*-

import json
import logging
from datetime import datetime, date
from odoo import http, fields, models
from odoo.http import request

_logger = logging.getLogger(__name__)


class DataExportController(http.Controller):
    """
    Controller API để export toàn bộ dữ liệu từ Odoo
    Endpoints:
    - /api/export/all - Get tất cả dữ liệu
    - /api/export/sales - Get dữ liệu đơn hàng
    - /api/export/customers - Get dữ liệu khách hàng
    - /api/export/invoices - Get dữ liệu hóa đơn
    - /api/export/payments - Get dữ liệu phiếu thu
    - /api/export/employees - Get dữ liệu nhân viên
    """

    def _json_response(self, data, status_code=200):
        """Helper để trả response JSON chuẩn"""
        response = {
            'success': True,
            'data': data,
            'timestamp': datetime.now().isoformat(),
            'status_code': status_code
        }
        return http.Response(
            json.dumps(response, ensure_ascii=False, default=str),
            content_type='application/json',
            status=status_code
        )

    def _error_response(self, message, status_code=400):
        """Helper để trả error response"""
        response = {
            'success': False,
            'error': message,
            'timestamp': datetime.now().isoformat(),
            'status_code': status_code
        }
        return http.Response(
            json.dumps(response, ensure_ascii=False),
            content_type='application/json',
            status=status_code
        )

    def _serialize_record(self, record, fields_to_include):
        """Helper để serialize record thành dict"""
        result = {}
        for field_name in fields_to_include:
            if hasattr(record, field_name):
                value = getattr(record, field_name)
                
                # Xử lý các loại field đặc biệt
                if isinstance(value, models.Model):
                    # Many2one field
                    result[field_name] = {
                        'id': value.id,
                        'name': value.display_name if hasattr(value, 'display_name') else str(value)
                    }
                elif hasattr(value, '__iter__') and not isinstance(value, (str, bytes)):
                    # One2many/Many2many fields
                    result[field_name] = [{'id': r.id, 'name': r.display_name if hasattr(r, 'display_name') else str(r)} for r in value]
                elif isinstance(value, (date, datetime)):
                    # Date/Datetime fields
                    result[field_name] = value.isoformat() if value else None
                else:
                    # Các field khác
                    result[field_name] = value
        
        return result

    @http.route('/dac_erp/api/test', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def test_api(self, **kwargs):
        """Test endpoint để kiểm tra API hoạt động"""
        _logger.info("API Test endpoint được gọi")
        data = {
            'message': 'API hoạt động tốt!',
            'timestamp': datetime.now().isoformat(),
            'controller': 'DataExportController'
        }
        return http.Response(
            json.dumps(data, ensure_ascii=False),
            content_type='application/json',
            status=200
        )

    @http.route('/dac_erp/api/export/all', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_all_data(self, **kwargs):
        """API endpoint để get tất cả dữ liệu"""
        try:
            _logger.info("API Export All Data được gọi")
            data = {
                'sales': self._get_sales_data(**kwargs),
                'customers': self._get_customers_data(**kwargs),
                'invoices': self._get_invoices_data(**kwargs),
                'payments': self._get_payments_data(**kwargs),
                'employees': self._get_employees_data(**kwargs),
                'products': self._get_products_data(**kwargs),
                'summary': self._get_summary_stats(**kwargs)
            }
            
            _logger.info(f"API Export All Data - Total records: {sum(len(v) if isinstance(v, list) else 0 for v in data.values())}")
            
            # Trả về HTTP response thay vì JSON response
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
            
        except Exception as e:
            _logger.error(f"Error in export_all_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export dữ liệu: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/sales', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_sales_data(self, **kwargs):
        """API endpoint để get dữ liệu đơn hàng"""
        try:
            data = self._get_sales_data(**kwargs)
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_sales_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export đơn hàng: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/customers', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_customers_data(self, **kwargs):
        """API endpoint để get dữ liệu khách hàng"""
        try:
            data = self._get_customers_data(**kwargs)
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_customers_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export khách hàng: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/invoices', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_invoices_data(self, **kwargs):
        """API endpoint để get dữ liệu hóa đơn"""
        try:
            data = self._get_invoices_data(**kwargs)
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_invoices_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export hóa đơn: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/payments', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_payments_data(self, **kwargs):
        """API endpoint để get dữ liệu phiếu thu"""
        try:
            data = self._get_payments_data(**kwargs)
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_payments_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export phiếu thu: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    @http.route('/dac_erp/api/export/employees', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def export_employees_data(self, **kwargs):
        """API endpoint để get dữ liệu nhân viên"""
        try:
            data = self._get_employees_data(**kwargs)
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_employees_data: {str(e)}", exc_info=True)
            return http.Response(
                json.dumps({'error': f"Lỗi khi export nhân viên: {str(e)}"}),
                content_type='application/json',
                status=500
            )

    def _get_sales_data(self, limit=None, date_from=None, date_to=None, **kwargs):
        """Get dữ liệu đơn hàng"""
        domain = []
        
        # Filter theo ngày nếu có
        if date_from:
            domain.append(('create_date', '>=', date_from))
        if date_to:
            domain.append(('create_date', '<=', date_to))
        
        # Limit results
        limit = int(limit) if limit else 1000
        
        # Sử dụng sudo() để bypass permission check
        orders = request.env['sale.order'].sudo().search(domain, limit=limit, order='create_date desc')
        
        sales_data = []
        for order in orders:
            order_data = {
                'id': order.id,
                'name': order.name,
                'partner_id': {
                    'id': order.partner_id.id,
                    'name': order.partner_id.name,
                    'phone': order.partner_id.phone,
                    'email': order.partner_id.email
                },
                'user_id': {
                    'id': order.user_id.id,
                    'name': order.user_id.name
                } if order.user_id else None,
                'date_order': order.date_order.isoformat() if order.date_order else None,
                'create_date': order.create_date.isoformat() if order.create_date else None,
                'amount_total': order.amount_total,
                'amount_untaxed': order.amount_untaxed,
                'amount_tax': order.amount_tax,
                'state': order.state,
                'order_state_custom': getattr(order, 'order_state_custom', None),
                'has_deposit': getattr(order, 'has_deposit', False),
                'deposit_amount': getattr(order, 'deposit_amount', 0),
                'is_order_completed': getattr(order, 'is_order_completed', False),
                'production_deadline': order.production_deadline.isoformat() if hasattr(order, 'production_deadline') and order.production_deadline else None,
                'delivery_address': getattr(order, 'delivery_address', None),
                'order_lines': [
                    {
                        'id': line.id,
                        'product_id': {
                            'id': line.product_id.id,
                            'name': line.product_id.name
                        } if line.product_id else None,
                        'name': line.name,
                        'product_uom_qty': line.product_uom_qty,
                        'price_unit': line.price_unit,
                        'price_subtotal': line.price_subtotal,
                        'display_type': line.display_type
                    } for line in order.order_line
                ]
            }
            sales_data.append(order_data)
        
        return sales_data

    def _get_customers_data(self, limit=None, **kwargs):
        """Get dữ liệu khách hàng"""
        limit = int(limit) if limit else 1000
        partners = request.env['res.partner'].sudo().search([
            ('is_company', '=', False),  # Chỉ lấy khách hàng cá nhân
            ('customer_rank', '>', 0)    # Chỉ lấy customer
        ], limit=limit, order='create_date desc')
        
        customers_data = []
        for partner in partners:
            customer_data = {
                'id': partner.id,
                'name': partner.name,
                'phone': partner.phone,
                'email': partner.email,
                'mobile': partner.mobile,
                'street': partner.street,
                'street2': partner.street2,
                'city': partner.city,
                'state_id': {
                    'id': partner.state_id.id,
                    'name': partner.state_id.name
                } if partner.state_id else None,
                'country_id': {
                    'id': partner.country_id.id,
                    'name': partner.country_id.name
                } if partner.country_id else None,
                'zip': partner.zip,
                'vat': partner.vat,
                'create_date': partner.create_date.isoformat() if partner.create_date else None,
                'write_date': partner.write_date.isoformat() if partner.write_date else None,
                'customer_rank': partner.customer_rank,
                'supplier_rank': partner.supplier_rank,
                'is_company': partner.is_company,
                # Thống kê đơn hàng
                'total_orders': request.env['sale.order'].sudo().search_count([('partner_id', '=', partner.id)]),
                'total_invoiced': sum(request.env['sale.order'].sudo().search([('partner_id', '=', partner.id)]).mapped('amount_total'))
            }
            customers_data.append(customer_data)
        
        return customers_data

    def _get_invoices_data(self, limit=None, date_from=None, date_to=None, **kwargs):
        """Get dữ liệu hóa đơn"""
        domain = [('move_type', '=', 'out_invoice')]
        
        if date_from:
            domain.append(('create_date', '>=', date_from))
        if date_to:
            domain.append(('create_date', '<=', date_to))
        
        limit = int(limit) if limit else 1000
        invoices = request.env['account.move'].sudo().search(domain, limit=limit, order='create_date desc')
        
        invoices_data = []
        for invoice in invoices:
            invoice_data = {
                'id': invoice.id,
                'name': invoice.name,
                'partner_id': {
                    'id': invoice.partner_id.id,
                    'name': invoice.partner_id.name
                },
                'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                'invoice_date_due': invoice.invoice_date_due.isoformat() if invoice.invoice_date_due else None,
                'create_date': invoice.create_date.isoformat() if invoice.create_date else None,
                'amount_total': invoice.amount_total,
                'amount_untaxed': invoice.amount_untaxed,
                'amount_tax': invoice.amount_tax,
                'amount_residual': invoice.amount_residual,
                'state': invoice.state,
                'payment_state': invoice.payment_state,
                'invoice_origin': invoice.invoice_origin,
                'dac_deposit_invoice': getattr(invoice, 'dac_deposit_invoice', False),
                'invoice_lines': [
                    {
                        'id': line.id,
                        'product_id': {
                            'id': line.product_id.id,
                            'name': line.product_id.name
                        } if line.product_id else None,
                        'name': line.name,
                        'quantity': line.quantity,
                        'price_unit': line.price_unit,
                        'price_subtotal': line.price_subtotal,
                        'display_type': line.display_type
                    } for line in invoice.invoice_line_ids
                ]
            }
            invoices_data.append(invoice_data)
        
        return invoices_data

    def _get_payments_data(self, limit=None, date_from=None, date_to=None, **kwargs):
        """Get dữ liệu phiếu thu"""
        domain = [('payment_type', '=', 'inbound')]
        
        if date_from:
            domain.append(('create_date', '>=', date_from))
        if date_to:
            domain.append(('create_date', '<=', date_to))
        
        limit = int(limit) if limit else 1000
        payments = request.env['account.payment'].sudo().search(domain, limit=limit, order='create_date desc')
        
        payments_data = []
        for payment in payments:
            payment_data = {
                'id': payment.id,
                'name': payment.name,
                'partner_id': {
                    'id': payment.partner_id.id,
                    'name': payment.partner_id.name
                } if payment.partner_id else None,
                'amount': payment.amount,
                'currency_id': {
                    'id': payment.currency_id.id,
                    'name': payment.currency_id.name
                },
                'payment_date': payment.date.isoformat() if payment.date else None,
                'create_date': payment.create_date.isoformat() if payment.create_date else None,
                'state': payment.state,
                'payment_method_line_id': {
                    'id': payment.payment_method_line_id.id,
                    'name': payment.payment_method_line_id.name
                } if payment.payment_method_line_id else None,
                'memo': getattr(payment, 'memo', None),  # Thay vì communication
                # Thông tin custom nếu có
                'sale_order_origin': getattr(payment, 'sale_order_origin', None),
                'is_deposit_payment': getattr(payment, 'is_deposit_payment', False),
                'is_final_payment': getattr(payment, 'is_final_payment', False)
            }
            payments_data.append(payment_data)
        
        return payments_data

    def _get_employees_data(self, limit=None, **kwargs):
        """Get dữ liệu nhân viên"""
        # Kiểm tra xem module HR có được cài đặt không
        if 'hr.employee' not in request.env:
            _logger.warning("Module HR chưa được cài đặt, bỏ qua dữ liệu employees")
            return []
            
        limit = int(limit) if limit else 500
        employees = request.env['hr.employee'].sudo().search([], limit=limit, order='create_date desc')
        
        employees_data = []
        for employee in employees:
            employee_data = {
                'id': employee.id,
                'name': employee.name,
                'work_email': employee.work_email,
                'work_phone': employee.work_phone,
                'mobile_phone': employee.mobile_phone,
                'job_title': employee.job_title,
                'department_id': {
                    'id': employee.department_id.id,
                    'name': employee.department_id.name
                } if employee.department_id else None,
                'manager_id': {
                    'id': employee.parent_id.id,
                    'name': employee.parent_id.name
                } if employee.parent_id else None,
                'user_id': {
                    'id': employee.user_id.id,
                    'name': employee.user_id.name,
                    'login': employee.user_id.login
                } if employee.user_id else None,
                'create_date': employee.create_date.isoformat() if employee.create_date else None,
                'active': employee.active,
                'company_id': {
                    'id': employee.company_id.id,
                    'name': employee.company_id.name
                }
            }
            employees_data.append(employee_data)
        
        return employees_data

    def _get_products_data(self, limit=None, **kwargs):
        """Get dữ liệu sản phẩm"""
        limit = int(limit) if limit else 1000
        products = request.env['product.product'].sudo().search([
            ('sale_ok', '=', True)  # Chỉ lấy sản phẩm có thể bán
        ], limit=limit, order='create_date desc')
        
        products_data = []
        for product in products:
            product_data = {
                'id': product.id,
                'name': product.name,
                'default_code': product.default_code,
                'barcode': product.barcode,
                'list_price': product.list_price,
                'standard_price': product.standard_price,
                'type': product.type,
                'categ_id': {
                    'id': product.categ_id.id,
                    'name': product.categ_id.name
                },
                'uom_id': {
                    'id': product.uom_id.id,
                    'name': product.uom_id.name
                },
                'active': product.active,
                'sale_ok': product.sale_ok,
                'purchase_ok': product.purchase_ok,
                'create_date': product.create_date.isoformat() if product.create_date else None,
                # Sử dụng getattr để tránh lỗi nếu field không tồn tại
                'qty_available': getattr(product, 'qty_available', 0),
                'virtual_available': getattr(product, 'virtual_available', 0)
            }
            products_data.append(product_data)
        
        return products_data

    def _get_summary_stats(self, **kwargs):
        """Get thống kê tổng quan"""
        # Kiểm tra modules có tồn tại không
        total_employees = 0
        if 'hr.employee' in request.env:
            total_employees = request.env['hr.employee'].sudo().search_count([])
            
        return {
            'total_orders': request.env['sale.order'].sudo().search_count([]),
            'total_customers': request.env['res.partner'].sudo().search_count([('customer_rank', '>', 0)]),
            'total_invoices': request.env['account.move'].sudo().search_count([('move_type', '=', 'out_invoice')]),
            'total_payments': request.env['account.payment'].sudo().search_count([('payment_type', '=', 'inbound')]),
            'total_employees': total_employees,
            'total_products': request.env['product.product'].sudo().search_count([('sale_ok', '=', True)]),
            'total_revenue_this_month': self._get_monthly_revenue(),
            'orders_by_state': self._get_orders_by_state()
        }

    def _get_monthly_revenue(self):
        """Tính doanh thu tháng hiện tại"""
        current_month_start = fields.Date.today().replace(day=1)
        orders = request.env['sale.order'].sudo().search([
            ('date_order', '>=', current_month_start),
            ('state', 'in', ['sale', 'done'])
        ])
        return sum(orders.mapped('amount_total'))

    def _get_orders_by_state(self):
        """Thống kê đơn hàng theo trạng thái"""
        states = ['draft', 'sent', 'sale', 'done', 'cancel']
        result = {}
        for state in states:
            count = request.env['sale.order'].sudo().search_count([('state', '=', state)])
            result[state] = count
        
        # Thống kê custom state nếu có
        if hasattr(request.env['sale.order'], 'order_state_custom'):
            custom_states = ['quotation', 'deposit', 'production', 'delivery', 'payment']
            result['custom_states'] = {}
            for state in custom_states:
                count = request.env['sale.order'].sudo().search_count([('order_state_custom', '=', state)])
                result['custom_states'][state] = count
        
        return result

    # --- MESSAGES EXPORT -------------------------------------------------
    @http.route('/dac_erp/api/export/messages', type='http', auth='public', csrf=False, methods=['GET'])
    def export_messages_data(self,
                            conversation_id=None,
                            conversation_fm_id=None,
                            date=None,            # YYYY-MM-DD (lấy đúng 1 ngày)
                            date_from=None,       # YYYY-MM-DD hoặc YYYY-MM-DD HH:MM:SS
                            date_to=None,
                            limit=None,
                            offset=0,
                            asc='1',              # '1' = ASC, '0' = DESC
                            include_raw='0',      # '1' để gửi cả raw_json_message
                            **kwargs):
        """
        Trả về danh sách message của 1 conversation, có lọc theo ngày.
        BẮT BUỘC truyền 1 trong 2: conversation_id (Odoo ID) hoặc conversation_fm_id (ID từ Pages/Pancake).
        """
        try:
            data = self._get_messages_data(
                conversation_id=conversation_id,
                conversation_fm_id=conversation_fm_id,
                date=date,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                offset=offset,
                asc=asc,
                include_raw=include_raw,
            )
            return http.Response(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type='application/json',
                status=200
            )
        except Exception as e:
            _logger.error(f"Error in export_messages_data: {e}", exc_info=True)
            return http.Response(
                json.dumps({'error': f'Lỗi khi export messages: {e}'}),
                content_type='application/json',
                status=500
            )

    def _get_messages_data(self,
                        conversation_id=None,
                        conversation_fm_id=None,
                        date=None,
                        date_from=None,
                        date_to=None,
                        limit=None,
                        offset=0,
                        asc='1',
                        include_raw='0',
                        **kwargs):
        """Lấy dữ liệu message theo conversation + ngày."""
        domain = []

        # --- bắt buộc: xác định conversation ---
        if conversation_id:
            try:
                conversation_id = int(conversation_id)
            except Exception:
                raise ValueError("conversation_id phải là số nguyên.")
            domain.append(('conversation_id', '=', conversation_id))
        elif conversation_fm_id:
            domain.append(('conversation_id.conversation_fm_id', '=', conversation_fm_id))
        else:
            raise ValueError("Thiếu conversation_id hoặc conversation_fm_id.")

        # --- chuẩn hoá ngày ---
        # Nếu có 'date' => lấy trọn ngày đó
        if date and (not date_from and not date_to):
            date_from = f"{date} 00:00:00"
            date_to   = f"{date} 23:59:59"

        if date_from:
            domain.append(('inserted_at_fm', '>=', date_from))
        if date_to:
            domain.append(('inserted_at_fm', '<=', date_to))

        # --- paging & sort ---
        limit = int(limit) if limit else 200
        offset = int(offset) if offset else 0
        order = 'inserted_at_fm asc' if str(asc) in ('1', 'true', 'True') else 'inserted_at_fm desc'

        Message = request.env['page.fm.message'].sudo()
        messages = Message.search(domain, limit=limit, offset=offset, order=order)

        rows = []
        for m in messages:
            # attachments_json có thể là str; parse an toàn
            try:
                attachments = json.loads(m.attachments_json) if m.attachments_json else None
            except Exception:
                attachments = m.attachments_json

            row = {
                # khóa chính
                'id': m.id,
                'message_fm_id': getattr(m, 'message_fm_id', None),

                # thông tin conversation (đủ để đối soát)
                'conversation': {
                    'id': m.conversation_id.id if m.conversation_id else None,
                    'name': m.conversation_id.display_name if m.conversation_id else None,
                    'conversation_fm_id': getattr(m.conversation_id, 'conversation_fm_id', None),
                    'page': {
                        'id': m.conversation_id.page_fm_page_id.id if m.conversation_id and m.conversation_id.page_fm_page_id else None,
                        'name': m.conversation_id.page_fm_page_id.name if m.conversation_id and m.conversation_id.page_fm_page_id else None,
                        'page_fm_id_str': getattr(m.conversation_id.page_fm_page_id, 'page_fm_id_str', None),
                    } if m.conversation_id else None,
                },

                # mốc thời gian
                'inserted_at_fm': m.inserted_at_fm.isoformat() if getattr(m, 'inserted_at_fm', None) else None,
                'previous_time':  m.previous_time.isoformat()  if getattr(m, 'previous_time', None)  else None,

                # người gửi / staff
                'sender_name_fm': getattr(m, 'sender_name_fm', None),
                'staff_name_fm':  getattr(m, 'staff_name_fm', None),
                'staff_id_fm':    getattr(m, 'staff_id_fm', None),
                'staff_user': ({
                    'id': m.staff.id,
                    'name': m.staff.display_name
                } if getattr(m, 'staff', False) else None),

                # nội dung
                'content_html': getattr(m, 'content_html', None),
                'type_content': getattr(m, 'type_content', None),
                'url_content':  getattr(m, 'url_content', None),
                'attachments':  attachments,
            }

            if str(include_raw) in ('1', 'true', 'True'):
                row['raw_json_message'] = getattr(m, 'raw_json_message', None)

            rows.append(row)

        return {
            'count': len(rows),
            'limit': limit,
            'offset': offset,
            'order': order,
            'items': rows,
        }
    # --- /MESSAGES EXPORT ------------------------------------------------

