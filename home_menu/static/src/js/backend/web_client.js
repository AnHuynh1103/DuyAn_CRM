/** @odoo-module **/
import { WebClient } from "@web/webclient/webclient";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { onWillStart, useState, onMounted } from "@odoo/owl";
patch(WebClient.prototype, {
  setup() {
    super.setup();
  },

  async _loadDefaultApp() {
    // Selects the first root menu if any
    // let root;
    // let firstApp;
    if (await user.hasGroup("base.group_system"))
      return super._loadDefaultApp();

    // if (await user.hasGroup("investor_vnpay_odoo.seller")) {
    //   const filteredArray = this.menuService
    //     .getApps()
    //     .filter(
    //       (item) => item.xmlid === "investor_vnpay_odoo.menu_seller_root"
    //     );
    //   root = filteredArray[0];
    //   firstApp = root?.appID;
    // } else {
    //   const filteredArray = this.menuService
    //     .getApps()
    //     .filter((item) => item.xmlid === "home_menu.home_root");
    //   root = filteredArray[0];
    //   firstApp = root?.appID;
    // }
    const filteredArray = this.menuService
      .getApps()
      .filter((item) => item.xmlid === "home_menu.home_root");
    const root = filteredArray[0];
    const firstApp = root?.appID;
    if (firstApp) {
      return this.menuService.selectMenu(firstApp);
    }
  },
});
