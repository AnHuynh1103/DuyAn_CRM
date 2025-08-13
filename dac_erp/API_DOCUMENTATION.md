# DAC ERP - Data Export API Documentation

## Tổng quan
API này cung cấp khả năng export toàn bộ dữ liệu từ hệ thống Odoo bao gồm: đơn hàng, khách hàng, hóa đơn, phiếu thu, nhân viên, sản phẩm.

## Authentication
- Yêu cầu đăng nhập Odoo user có quyền truy cập dữ liệu
- Sử dụng auth='user' cho tất cả endpoints

## Base URL
```
http://your-odoo-domain:port
```

## Endpoints

### 1. Export All Data
**GET** `/api/export/all`

Export tất cả dữ liệu cùng lúc.

**Parameters:**
- `limit` (optional): Giới hạn số bản ghi cho mỗi loại dữ liệu (default: 1000)
- `date_from` (optional): Lọc từ ngày (format: YYYY-MM-DD)
- `date_to` (optional): Lọc đến ngày (format: YYYY-MM-DD)

**Response:**
```json
{
  "success": true,
  "data": {
    "sales": [...],
    "customers": [...],
    "invoices": [...],
    "payments": [...],
    "employees": [...],
    "products": [...],
    "summary": {...}
  },
  "timestamp": "2025-01-01T00:00:00",
  "status_code": 200
}
```

### 2. Export Sales Data
**GET** `/api/export/sales`

Export dữ liệu đơn hàng.

**Parameters:**
- `limit` (optional): Số lượng đơn hàng (default: 1000)
- `date_from` (optional): Từ ngày
- `date_to` (optional): Đến ngày

**Sample Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "S00001",
      "partner_id": {
        "id": 10,
        "name": "Nguyễn Văn A",
        "phone": "0123456789",
        "email": "email@example.com"
      },
      "user_id": {
        "id": 2,
        "name": "Sale User"
      },
      "date_order": "2025-01-01T00:00:00",
      "amount_total": 1000000,
      "amount_untaxed": 909090.91,
      "amount_tax": 90909.09,
      "state": "sale",
      "order_state_custom": "production",
      "has_deposit": true,
      "deposit_amount": 500000,
      "is_order_completed": false,
      "production_deadline": "2025-01-15T00:00:00",
      "delivery_address": "123 ABC Street",
      "order_lines": [
        {
          "id": 1,
          "product_id": {
            "id": 5,
            "name": "Product ABC"
          },
          "name": "Product ABC",
          "product_uom_qty": 1,
          "price_unit": 1000000,
          "price_subtotal": 1000000,
          "display_type": false
        }
      ]
    }
  ]
}
```

### 3. Export Customers Data
**GET** `/api/export/customers`

Export dữ liệu khách hàng.

**Parameters:**
- `limit` (optional): Số lượng khách hàng (default: 1000)

**Sample Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 10,
      "name": "Nguyễn Văn A",
      "phone": "0123456789",
      "email": "customer@example.com",
      "mobile": "0987654321",
      "street": "123 Main St",
      "city": "Hồ Chí Minh",
      "country_id": {
        "id": 241,
        "name": "Vietnam"
      },
      "create_date": "2025-01-01T00:00:00",
      "customer_rank": 1,
      "total_orders": 5,
      "total_invoiced": 5000000
    }
  ]
}
```

### 4. Export Invoices Data
**GET** `/api/export/invoices`

Export dữ liệu hóa đơn.

**Parameters:**
- `limit` (optional): Số lượng hóa đơn (default: 1000)
- `date_from` (optional): Từ ngày
- `date_to` (optional): Đến ngày

**Sample Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "INV/2025/00001",
      "partner_id": {
        "id": 10,
        "name": "Nguyễn Văn A"
      },
      "invoice_date": "2025-01-01",
      "amount_total": 1100000,
      "amount_untaxed": 1000000,
      "amount_tax": 100000,
      "amount_residual": 0,
      "state": "posted",
      "payment_state": "paid",
      "invoice_origin": "S00001",
      "dac_deposit_invoice": false,
      "invoice_lines": [...]
    }
  ]
}
```

### 5. Export Payments Data
**GET** `/api/export/payments`

Export dữ liệu phiếu thu.

**Parameters:**
- `limit` (optional): Số lượng phiếu thu (default: 1000)
- `date_from` (optional): Từ ngày
- `date_to` (optional): Đến ngày

### 6. Export Employees Data
**GET** `/api/export/employees`

Export dữ liệu nhân viên.

**Parameters:**
- `limit` (optional): Số lượng nhân viên (default: 500)

## Error Response Format
```json
{
  "success": false,
  "error": "Error message",
  "timestamp": "2025-01-01T00:00:00",
  "status_code": 400
}
```

## Usage Examples

### 1. Get all data with date filter
```bash
curl -X GET "http://localhost:8069/api/export/all?date_from=2025-01-01&date_to=2025-01-31" \
  -H "Cookie: session_id=your_session_id"
```

### 2. Get sales data with limit
```bash
curl -X GET "http://localhost:8069/api/export/sales?limit=100" \
  -H "Cookie: session_id=your_session_id"
```

### 3. Get customers data
```bash
curl -X GET "http://localhost:8069/api/export/customers" \
  -H "Cookie: session_id=your_session_id"
```

## Features

### Custom Fields Support
- API tự động detect và include các custom fields như:
  - `order_state_custom` trong sale.order
  - `dac_deposit_invoice` trong account.move
  - `is_deposit_payment`, `is_final_payment` trong account.payment

### Relationship Handling
- Many2one fields được serialize thành object với id và name
- One2many/Many2many fields được serialize thành array of objects
- Date/Datetime fields được format theo ISO 8601

### Performance Optimization
- Default limit để tránh timeout
- Lazy loading cho relationship fields
- Efficient domain filtering

### Error Handling
- Comprehensive error logging
- User-friendly error messages
- Proper HTTP status codes

## Security Notes
- Yêu cầu authentication
- Chỉ trả về dữ liệu user có quyền truy cập
- No CSRF protection (API dành cho internal use)

## Integration Examples

### Python
```python
import requests

session = requests.Session()
# Login first
login_data = {
    'login': 'admin',
    'password': 'admin',
    'db': 'your_db'
}
session.post('http://localhost:8069/web/login', data=login_data)

# Get data
response = session.get('http://localhost:8069/api/export/all')
data = response.json()
```

### JavaScript
```javascript
fetch('/api/export/sales?limit=50')
  .then(response => response.json())
  .then(data => {
    console.log('Sales data:', data.data);
  });
```
