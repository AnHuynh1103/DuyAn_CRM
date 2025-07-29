# -*- coding: utf-8 -*-
# Copyright 2021, 2022 Odooland - Milad Sadeghi
# License LGPL-3.0 or later (https://choosealicense.com/licenses/agpl-3.0/).
{
    'name': "Modern Backend Theme",
    'version': '18.0.1.0.0',
    'sequence': 1,
    'summary': """
        Odoo Land Modern Theme""",

    'description': """
        Modern theme is a Odoo backend theme for Community edition, with the latest template design methods and support full responsive.
    """,

    'author': "Odoo Land, Fadoo",
    'maintainer': ["milad-sadeghi"],
    'website': "http://www.odooland.com",
    'support': "odooland.dev@gmail.com",
    'category': "Themes/Backend",
    'depends': ['base', 'web', 'mail'],
    'images': ['static/description/logo.png'],
    'Live_test_url':'demo.odooland.com',
    'assets': {
        'web._assets_primary_variables': [
            'static/src/scss/primary_variables_custom.scss',
        ],
        'web._assets_backend_helpers': [
            'static/src/webclient/mixins.scss',
        ],
        'web.assets_backend': [
            'static/src/css/main.css',
            'static/src/css/navbar.css',
            'static/src/css/header.css',
            'static/src/css/form.css',
            'static/src/css/list.css',
            'static/src/css/kanban.css',
            'static/src/css/calendar.css',
            'static/src/css/pivot.css',
            'static/src/css/graph.css',
            'static/src/css/activity.css',
            'static/src/css/mail.css',
            'static/src/css/card.css',
            'static/src/css/dashboard.css',
            'static/src/css/chatter.css',
            'static/src/css/other.css',
            # 'static/src/xml/mail.xml',
            'static/src/webclient/**/*.xml',
            'static/src/webclient/**/*.scss',
            'static/src/webclient/**/*.js',
        ],
        'point_of_sale.assets': [
            'static/src/css/pos.css',
        ]
        
    },
    'images': [
        'static/description/logo.png',
        'static/description/theme_screenshot.png',
    ],
    'price': 0.0,
    'currency': 'USD',
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
