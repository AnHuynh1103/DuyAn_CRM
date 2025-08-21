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
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

class DacSaleDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.notification = useService("notification");
    this.state = useState({ loading: true, data: null, error: null });

    onWillStart(async () => {
      await this._load();
    });

    this._applyViewportTweaks = this._applyViewportTweaks.bind(this);
    this._ensureViewportReady = this._ensureViewportReady.bind(this);
    this._restoreViewportTweaks = this._restoreViewportTweaks.bind(this);
  }

  //--------------------------------------------------------------------
  // Data Loading
  //--------------------------------------------------------------------
  async _load() {
    this.state.loading = true;
    try {
      const data = await this.orm.call("sale.order", "dac_get_dashboard", []);
      this.state.data = data || {};
    } catch (e) {
      this.state.error = (e && e.message) || String(e);
      console.error(e);
    } finally {
      this.state.loading = false;
    }
  }

  async refresh() {
    await this._load();
  }

  //--------------------------------------------------------------------
  // UI Helpers
  //--------------------------------------------------------------------
  // Helpers: đọc dữ liệu linh hoạt theo nhiều key khác nhau
  getTitle(it) {
    return (
      it.partner_name ||
      it.customer_name ||
      it.name ||
      it.title ||
      it.display_name ||
      "—"
    );
  }

  getSnippet(it) {
    // Ưu tiên: note (suggestion từ AI/n8n) > snippet (tin nhắn cuối) > các field khác
    return (
      it.note || it.suggestion_note || it.last_message_snippet || it.snippet || it.last_message || ""
    );
  }

  getExternalUrl(it) {
    return it.external_url || it.pancake_url || it.url || null;
  }

  getStatusKey(it) {
    // ưu tiên trường server tính sẵn
    if (it.status_state) return it.status_state; // 'new' | 'recontact' | 'waiting' | 'done' ...
    // suy luận đơn giản nếu không có:
    if (it.is_unread_fm || it.is_unread) return "new";
    if (it.checklist_ok) return "done";
    return ""; // không add class trạng thái
  }

  getStatusClass(item) {
    const st = item.status_state || item.care_status || item.consult_status;
    if (st === "new" || st === "recontact" || st === "red")
      return "badge bg-danger";
    if (st === "waiting" || st === "pending" || st === "yellow")
      return "badge bg-warning text-dark";
    return "badge bg-success";
  }

  //--------------------------------------------------------------------
  // Actions
  //--------------------------------------------------------------------

  // Text trạng thái hiển thị một dòng (đỏ/vàng/xanh)
  getStateText(it) {
    // 1) quyết định theo trạng thái tính được
    const st = this.getStatusKey(it); // 'new' | 'waiting' | 'done' | ...
    if (st === "new") return "Có tin nhắn mới";
    if (st === "recontact") return "Chăm lại khách";
    if (st === "waiting") return "Cần liên hệ lại";
    if (st === "done") return "Đã xử lý";
    // 2) nếu không suy ra được thì mới dùng label server gửi
    return it.status_label || "";
  }

  // Mở form cuộc hội thoại trong Odoo
  openConversation(item, ev) {
    ev && ev.stopPropagation();
    return this.openForm("page.fm.conversation", item.id);
  }

  // Mở record bất kỳ (method generic)
  async openRecord(model, resId, ev) {
    if (ev) ev.stopPropagation();
    return this.action.doAction({
      type: "ir.actions.act_window",
      res_model: model,
      res_id: resId,
      target: "current",
      views: [[false, "form"]],
    });
  }

  // Mở Pancake trên tab mới (không chặn click vào card)
  openPancake(item, ev) {
    ev && ev.stopPropagation();
    const url = this.getExternalUrl(item);
    if (url) window.open(url, "_blank", "noopener");
  }

  // Toggle checklist -> server set 'done' + mark read
  async toggleChecklist(item, ev) {
    ev && ev.stopPropagation();
    try {
      const res = await this.orm.call(
        "page.fm.conversation",
        "action_toggle_checklist_ok",
        [item.id]
      );
      Object.assign(item, res);
      // đảm bảo UI đổi trạng thái ngay
      if (item.checklist_ok) {
        item.status_state = "done";
        item.is_unread_fm = false;
        item.status_label = "Đã xử lý";
        item.require_processing = false;
      }
      this.render();
    } catch (err) {
      console.error("toggleChecklist failed:", err);
      this.notification.add(_t("Không cập nhật được Checklist."), {
        type: "danger",
      });
    }
  }

  openForm(model, id) {
    return this.action.doAction({
      type: "ir.actions.act_window",
      res_model: model,
      res_id: id,
      views: [[false, "form"]],
      target: "current",
    });
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
    let v = this.el?.classList?.contains("dac-viewport")
      ? this.el
      : document.querySelector(".dac-viewport");
    if (!v) {
      this._retryTimer = setTimeout(this._ensureViewportReady, 0);
      return;
    }
    this._viewport = v;

    this._applyViewportTweaks();
    this._raf2 = requestAnimationFrame(this._applyViewportTweaks);
    window.addEventListener("resize", this._applyViewportTweaks, {
      passive: true,
    });
  }

  _applyViewportTweaks() {
    const v = this._viewport || document.querySelector(".dac-viewport");
    if (!v) return;

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
      setImp(content, "overflow", "hidden");
    }
    const ctrl = act?.querySelector(
      ".o_controller_with_control_panel, .o_view_controller"
    );
    if (ctrl) setImp(ctrl, "padding", "0");

    setImp(v, "position", "absolute");
    setImp(v, "top", "0");
    setImp(v, "right", "0");
    setImp(v, "bottom", "0");
    setImp(v, "left", "0");
    setImp(v, "overflow-x", "auto");
    setImp(v, "overflow-y", "auto");
    setImp(v, "-webkit-overflow-scrolling", "touch");

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
}

DacSaleDashboard.template = "dac_sale_dashboard.Dashboard";
registry.category("actions").add("dac_sale_dashboard", DacSaleDashboard);
