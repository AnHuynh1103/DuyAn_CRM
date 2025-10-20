/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

class ProductionDashboard extends Component {
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
      const data = await this.orm.call(
        "sale.order",
        "dac_get_dashboard_production",
        []
      );
      // Backend đã trả đúng cấu trúc { lists: { manufacturing }, user_name }
      this.state.data = data || {
        lists: { manufacturing: [] },
        user_name: null,
      };
    } catch (e) {
      this.state.error = (e && e.message) || String(e);
      console.error(e);
    } finally {
      this.state.loading = false;
    }
  }

  async openOrderList() {
    // Production user → action production
    await this.action.doAction("dac_erp.dac_sale_order_action_production_only");
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

ProductionDashboard.template = "dac_erp.ProductionDashboard";
registry
  .category("actions")
  .add("dac_production_dashboard", ProductionDashboard);
