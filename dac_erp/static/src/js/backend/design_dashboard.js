/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

class DesignDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.notification = useService("notification");
    this.state = useState({ loading: true, data: null, error: null });

    onWillStart(async () => {
      await this._load();
    });
  }

  async _load() {
    this.state.loading = true;
    try {
      // Gọi đúng method domain riêng cho dashboard design
      const data = await this.orm.call(
        "sale.order",
        "dac_get_dashboard_design",
        []
      );
      // Lấy tên user (nếu muốn hiển thị)
      let user_name = null;
      try {
        const session = await rpc("/web/session/get_session_info", {});
        user_name = session && session.name ? session.name : null;
      } catch (e) {
        user_name = null;
      }
      this.state.data = {
        lists: {
          manufacturing: data && data.manufacturing ? data.manufacturing : [],
        },
        user_name: user_name,
      };
    } catch (e) {
      this.state.error = (e && e.message) || String(e);
      console.error(e);
    } finally {
      this.state.loading = false;
    }
  }

  async openOrderList() {
    await this.action.doAction("dac_erp.dac_sale_order_custom_action_design");
  }
  async openOrder(so) {
    if (!so || !so.id) return;
    await this.action.doAction({
      type: "ir.actions.act_window",
      res_model: "sale.order",
      res_id: so.id,
      target: "current",
      views: [[false, "form"]],
    });
  }
}

DesignDashboard.template = "dac_erp.DesignDashboard";
registry.category("actions").add("dac_design_dashboard", DesignDashboard);
