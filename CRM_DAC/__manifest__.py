{
    'name': 'DAC Project Extension',
    'license': 'LGPL-3',
    'author': 'khangnpb',
    'version': '18.0.1.0.0',
    'category': 'Project',
    'summary': 'DAC Pancake Project Extension',
    'depends': ['base','web'],
    'data': [
        # 'security/ir.model.access.csv',
        # 'views/contents_view.xml',
        # 'views/menu.xml',
        # 'data/ir_config_parameter_data.xml',
        'security/ir.model.access.csv', # Đảm bảo file này được khai báo TRƯỚC views
        'views/page_fm_views.xml',
        'views/pancake_order_views.xml',
        'views/pancake_dashboard_views.xml',
        'views/pancake_dashboard_menu.xml',

        'views/KPI_View.xml',
    ],

    'assets': {
        'web.assets_backend': [
            # 'CRM_DAC/static/src/js/pancake_list_controller.js',
            # 'CRM_DAC/static/src/xml/pancake_control_panel.xml',
        ],
    },
    'installable': True,
    'application': False,
}