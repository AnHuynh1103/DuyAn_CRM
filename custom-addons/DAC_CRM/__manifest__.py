{
    'name': "DAC_CRM", # Updated name
    'version': '18.0.1.0.0',
    'summary': """
        Quản lý quy trình tùy chỉnh cho các dự án thi công/thiết kế
        từ giai đoạn tiềm năng đến khi hoàn thành, tích hợp CRM, Sales, Project.
    """,
    'description': """
        Module này tùy chỉnh Odoo để theo một quy trình công việc cụ thể cho DAC Company:
        1. Khách hàng liên hệ (CRM).
        2. Tư vấn ban đầu & chuyên sâu (CRM).
        3. Nếu chưa có thiết kế: Khảo sát (Project - Kỹ thuật viên - Thiết kế).
        4. Nếu có sẵn thiết kế: Kiểm tra file (Project - Kỹ thuật viên - Thiết kế).
        5. Thiết kế (Project - Kỹ thuật viên - Thiết kế).
        6. Gửi báo giá nội bộ cho Sales (Project -> Sales).
        7. Sales gửi báo giá cho khách hàng (Sales).
        8. Nhận cọc (Sales/Account).
        9. Gửi yêu cầu sản xuất (Sales -> Project/MRP - Sản xuất).
        10. Sản xuất (Project/MRP - Sản xuất).
        11. Thi công (Project - Thi công).
        12. Giao hàng (bên thứ 3) (Project - Thi công).
        13. Ghi công nợ & Hoàn thành công nợ (Account).
        14. Thu tiền & Hoàn thành đơn hàng (Sales/Account).
    """,
    'category': 'Services/Project',
    'author': "DAC Company (hoặc tên của bạn)",
    'website': "https://www.yourcompany.com", # Thay bằng website của DAC Company
    'depends': [
        'crm',
        'sale_management',
        'project',
        'account',
        # 'documents', # Để quản lý file thiết kế, bản vẽ
        # 'mrp', # Bỏ comment nếu quy trình sản xuất phức tạp và cần MRP
    ],
    'data': [
        # Security
        # 'security/ir.model.access.csv',
        # 'security/custom_groups.xml', # Tùy chọn nếu cần nhóm người dùng mới (ví dụ: Kỹ thuật viên, Sản xuất)

        # Data
        # 'data/crm_stage_data.xml',
        # 'data/project_stage_data.xml', # Sẽ cần cho các giai đoạn của Project (Thiết kế, Sản xuất, Thi công)
        # 'data/mail_template_data.xml', # Template email cho các thông báo tự động

        # Wizards (nếu có)
        # 'wizard/send_design_to_sale_wizard_views.xml',

        # Views
        'views/crm_lead_views.xml',
        'views/sale_order_views.xml',
        'views/project_project_views.xml',
        'views/project_task_views.xml',
        # 'views/account_move_views.xml', # Nếu có tùy chỉnh trên hóa đơn
        'views/custom_menus.xml', # Menu tùy chỉnh (nếu có)
        # 'views/assets.xml', # Cho CSS/JS tùy chỉnh nếu cần
    ],
    'installable': True,
    'application': True, # Đặt là True nếu đây là một ứng dụng chính
    'auto_install': False,
    'license': 'LGPL-3',
}