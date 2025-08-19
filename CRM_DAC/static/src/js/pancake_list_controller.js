// odoo.define('your_module_name.pancake_list_controller_ext', function (require) {
//     "use strict";

//     var ListController = require('web.ListController');
//     var rpc = require('web.rpc');
//     var core = require('web.core');
//     var _t = core._t;

//     ListController.include({
//         /**
//          * Xử lý sự kiện click cho nút đồng bộ tùy chỉnh.
//          * Được gọi từ template QWeb.
//          */
//         _onPancakeSyncOrdersClickCustom: function () {
//             // Đảm bảo hàm này chỉ có ý nghĩa với model 'pancake.order'
//             // Mặc dù t-if trong QWeb đã kiểm tra, thêm một lớp bảo vệ ở đây cũng tốt.
//             if (this.modelName !== 'pancake.order') {
//                 // Hoặc không làm gì cả, hoặc gọi super nếu có hành động mặc định
//                 return;
//             }

//             var self = this;
//             this.displayNotification({ type: 'info', title: _t('Pancake Sync'), message: _t('Bắt đầu quá trình đồng bộ...') });

//             return rpc.query({
//                 model: 'pancake.order',
//                 method: 'action_sync_pancake_all_orders', // Tên hàm Python của bạn
//                 args: [[]], // Truyền ID nếu cần, hoặc mảng rỗng cho hàm ở cấp model
//                 context: self.getContext(), // Lấy context hiện tại của view
//             }).then(function(result) {
//                 // Xử lý kết quả trả về từ Python (ví dụ: một action khác hoặc thông báo)
//                 if (result && result.type === 'ir.actions.client' && result.tag === 'display_notification' && result.params) {
//                      self.displayNotification({
//                         title: result.params.title || _t('Pancake Sync'),
//                         message: result.params.message,
//                         type: result.params.type || 'info',
//                         sticky: result.params.sticky || false,
//                     });
//                 } else if (result && result.type) {
//                     // Nếu Python trả về một action (ví dụ: mở một view khác)
//                     self.do_action(result);
//                 } else {
//                     // Mặc định thông báo thành công (nếu Python không trả về gì cụ thể)
//                     self.displayNotification({ title: _t('Hoàn tất'), message: _t('Đồng bộ đơn hàng Pancake thành công.'), type: 'success' });
//                 }
//                 // Tải lại view để cập nhật dữ liệu
//                 return self.reload();
//             }).fail(function (error) {
//                 var errorMessage = _t('Không thể thực hiện đồng bộ.');
//                 if (error.message && error.message.data && error.message.data.message) {
//                     errorMessage = error.message.data.message;
//                 } else if (error.message && error.message.message) {
//                     errorMessage = error.message.message;
//                 }
//                 self.displayNotification({ title: _t('Lỗi'), message: errorMessage, type: 'danger', sticky: true });
//                 console.error("Pancake Sync RPC error:", error);
//             });
//         },
//     });
// });


odoo.define('button_near_create.tree_button', function (require) {
"use strict";
var ListController = require('web.ListController');
var ListView = require('web.ListView');
var viewRegistry = require('web.view_registry');
var TreeButton = ListController.extend({
   buttons_template: 'button_near_create.buttons',
   events: _.extend({}, ListController.prototype.events, {
       'click .open_wizard_action': '_OpenWizard',
   }),
   _OpenWizard: function () {
       var self = this;
        this.do_action({
           type: 'ir.actions.act_window',
           res_model: 'test.wizard',
           name :'Open Wizard',
           view_mode: 'form',
           view_type: 'form',
           views: [[false, 'form']],
           target: 'new',
           res_id: false,
       });
   }
});
var SaleOrderListView = ListView.extend({
   config: _.extend({}, ListView.prototype.config, {
       Controller: TreeButton,
   }),
});
viewRegistry.add('button_in_tree', SaleOrderListView);
});