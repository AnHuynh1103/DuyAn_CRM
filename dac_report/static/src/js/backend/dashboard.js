/** @odoo-module **/
import {
  Component,
  useState,
  onWillStart,
  onMounted,
  onWillUnmount,
} from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

class DacSaleDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.state = useState({ loading: true, data: null, error: null });

    onWillStart(async () => {
      try {
        this.state.data = await this.orm.call(
          "dac.sale.dashboard.api",
          "get_data",
          []
        );
      } catch (e) {
        this.state.error = (e && e.message) || String(e);
      } finally {
        this.state.loading = false;
      }
    });

    this._applyViewportTweaks = this._applyViewportTweaks.bind(this);
    this._ensureViewportReady = this._ensureViewportReady.bind(this);
    this._restoreViewportTweaks = this._restoreViewportTweaks.bind(this);
  }

  //--------------------------------------------------------------------
  // Lifecycle
  //--------------------------------------------------------------------
  mounted() {
    document.body.classList.add("dac-dashboard-open", "dac-compact");
    const act =
      this.el?.closest?.(".o_action") || document.querySelector(".o_action");
    if (act) {
      this._hostAction = act;
      act.classList.add("dac-host");
    }
    this._raf1 = requestAnimationFrame(this._ensureViewportReady);
  }

  willUnmount() {
    if (this._raf1) cancelAnimationFrame(this._raf1);
    if (this._raf2) cancelAnimationFrame(this._raf2);
    if (this._retryTimer) clearTimeout(this._retryTimer);
    window.removeEventListener("resize", this._applyViewportTweaks);
    if (this._hostAction) this._hostAction.classList.remove("dac-host");
    document.body.classList.remove("dac-dashboard-open", "dac-compact");
    this._restoreViewportTweaks();
  }

  //--------------------------------------------------------------------
  // Viewport helpers
  //--------------------------------------------------------------------
  _ensureViewportReady() {
    // Root component chính là .dac-viewport
    let v = this.el?.classList?.contains("dac-viewport")
      ? this.el
      : document.querySelector(".dac-viewport");
    if (!v) {
      this._retryTimer = setTimeout(this._ensureViewportReady, 0);
      return;
    }
    this._viewport = v;

    // Ép style 2 lần để chắc ăn
    this._applyViewportTweaks();
    this._raf2 = requestAnimationFrame(this._applyViewportTweaks);
    window.addEventListener("resize", this._applyViewportTweaks, {
      passive: true,
    });
  }

  _applyViewportTweaks() {
    const v = this._viewport || document.querySelector(".dac-viewport");
    if (!v) return;

    // utility: set inline style + backup để restore
    this._bak = this._bak || new Map();
    const setImp = (node, prop, value) => {
      if (!node) return;
      if (!this._bak.has(node)) this._bak.set(node, {});
      const rec = this._bak.get(node);
      if (!(prop in rec)) rec[prop] = node.style.getPropertyValue(prop);
      node.style.setProperty(prop, value, "important");
    };

    const act = v.closest?.(".o_action") || document.querySelector(".o_action");
    const content = act?.querySelector(".o_content");
    if (content) {
      setImp(content, "padding", "0");
      setImp(content, "overflow", "hidden"); // tránh scroll lồng nhau của Odoo
    }
    const ctrl = act?.querySelector(
      ".o_controller_with_control_panel, .o_view_controller"
    );
    if (ctrl) setImp(ctrl, "padding", "0");

    // Viewport full-bleed – KHÔNG đè lên navbar vì vẫn nằm trong .o_action
    setImp(v, "position", "absolute");
    setImp(v, "top", "0");
    setImp(v, "right", "0");
    setImp(v, "bottom", "0");
    setImp(v, "left", "0");
    setImp(v, "overflow-x", "auto");
    setImp(v, "overflow-y", "auto");
    setImp(v, "-webkit-overflow-scrolling", "touch");

    // container-xxl: bỏ bó chiều rộng để có thể tràn ngang khi cần
    const cx = v.querySelector(".container-xxl");
    if (cx) {
      setImp(cx, "padding-left", "0");
      setImp(cx, "padding-right", "0");
      setImp(cx, "max-width", "none");
      setImp(cx, "width", "auto");
      setImp(cx, "margin-left", "0");
      setImp(cx, "margin-right", "0");
    }
  }

  _restoreViewportTweaks() {
    if (!this._bak) return;
    this._bak.forEach((styles, node) => {
      if (!node) return;
      Object.entries(styles).forEach(([prop, value]) => {
        if (value) node.style.setProperty(prop, value);
        else node.style.removeProperty(prop);
      });
    });
    this._bak.clear();
  }

  //--------------------------------------------------------------------
  // Actions
  //--------------------------------------------------------------------
  openForm(model, id) {
    return this.action.doAction({
      type: "ir.actions.act_window",
      res_model: model,
      res_id: id,
      views: [[false, "form"]],
      target: "current",
    });
  }
}
DacSaleDashboard.template = "dac_sale_dashboard.Dashboard";
registry.category("actions").add("dac_sale_dashboard", DacSaleDashboard);
