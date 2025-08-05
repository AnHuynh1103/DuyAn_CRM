# -*- coding: utf-8 -*-
{
    'name': "Nhóm Quyền Tùy Chỉnh", # Tên module
    'version': '18.0.1.0.0',
    'summary': "Định nghĩa các nhóm quyền tùy chỉnh cho vai trò cụ thể.", # Tóm tắt
    'description': """
        Module này tạo ra các nhóm quyền sau:
        - Nhà quản lý
        - Sales
        - Kỹ thuật viên thiết kế
        - Kỹ thuật viên sản xuất
        - Kỹ thuật viên thi công
    """, # Mô tả chi tiết hơn
    'author': "DAC", # Tên bạn hoặc công ty
    'category': 'Administration/Security', # Phân loại module
    'depends': ['base'], # Module này phụ thuộc vào module 'base' gốc của Odoo
    'data': [
        # Khai báo các file sẽ được nạp khi cài module
        'security/ir.model.access.csv',
        'security/security_groups.xml',
        'security/menu_access.xml',
    ],
    'installable': True,
    'application': False, # Đánh dấu đây không phải là một ứng dụng chính
    'auto_install': False,
    'license': 'LGPL-3',
}