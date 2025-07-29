#!/bin/sh

# Đặt quyền sở hữu cho thư mục volume để user odoo có thể ghi dữ liệu
chown -R odoo:odoo /var/lib/odoo

# Chạy lệnh gốc của container (tức là CMD trong Dockerfile)
exec "$@"