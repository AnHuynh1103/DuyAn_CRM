/** @odoo-module **/
import { WebClient } from "@web/webclient/webclient";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { onWillStart } from "@odoo/owl";

function hasDebugParam() {
  const sp = new URLSearchParams(window.location.search);
  return sp.has("debug") || sp.has("debugMode");
}

function clearDebugCookies() {
  const past = "Thu, 01 Jan 1970 00:00:00 GMT";
  for (const n of ["debug", "odoo-debug", "debugMode"]) {
    document.cookie = `${n}=; expires=${past}; path=/`;
  }
}

function stripDebugFromUrl() {
  const url = new URL(window.location.href);
  url.searchParams.delete("debug");
  url.searchParams.delete("debugMode");
  window.history.replaceState(
    null,
    "",
    url.pathname + (url.search ? url.searchParams.toString() : "") + url.hash
  );
}

//  FIXED: Odoo 18 patch syntax - không dùng patch name
patch(WebClient.prototype, {
  setup() {
    super.setup(); //  FIXED: Dùng super.setup() thay vì this._super()

    onWillStart(async () => {
      const isAdmin = await user.hasGroup("base.group_system");
      if (isAdmin) return;

      const cookieHasDebug = document.cookie
        .split(";")
        .some((c) => /^(debug|odoo-debug)=/.test(c.trim()));

      if (hasDebugParam() || cookieHasDebug) {
        clearDebugCookies();
        stripDebugFromUrl();
        // Optional: Reload trang để đảm bảo
        window.location.reload();
      }
    });
  },
});
