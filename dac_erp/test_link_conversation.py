#!/usr/bin/env python3
"""
Script để test link conversation với sale order
Chạy trong terminal: python test_link_conversation.py
"""

# Script để chạy trong Python console của Odoo hoặc terminal
def link_order_to_conversation():
    """Link đơn hàng S10015 với conversation ID 1"""
    
    # Tìm đơn hàng S10015 (ID: 10015)
    order = env['sale.order'].search([('name', '=', 'S10015')], limit=1)
    if not order:
        print("❌ Không tìm thấy đơn hàng S10015")
        return
    
    # Tìm conversation của khách Út Hằng (ID: 1)  
    conversation = env['page.fm.conversation'].browse(1)
    if not conversation.exists():
        print("❌ Không tìm thấy conversation ID 1")
        return
        
    # Kiểm tra partner có khớp không
    if order.partner_id.id != conversation.partner_id.id:
        print(f"⚠️ Warning: Order partner ({order.partner_id.name}) != Conversation partner ({conversation.partner_id.name})")
    
    # Link conversation
    order.conversation_id = conversation.id
    print(f"✅ Đã link đơn hàng {order.name} với conversation {conversation.conversation_fm_id}")
    
    # Test API
    print("\n🧪 Testing API...")
    print(f"Order conversation_id: {order.conversation_id.id}")
    print(f"Order pancake_conversation_id: {order.conversation_id.conversation_fm_id}")
    
    return order, conversation

# Chạy trong Odoo shell hoặc debug console:
# link_order_to_conversation()

print("""
📋 Để chạy script này trong Odoo:

1. Vào Odoo shell:
   python odoo-bin shell -d your_database

2. Chạy lệnh:
   exec(open('/path/to/test_link_conversation.py').read())
   link_order_to_conversation()

3. Hoặc chạy trực tiếp:
   order = env['sale.order'].search([('name', '=', 'S10015')], limit=1)
   conversation = env['page.fm.conversation'].browse(1)
   order.conversation_id = conversation.id
   
4. Test API sau đó:
   http://localhost:8069/dac_erp/api/export/sales?date=2025-09-09
""")
