/** @odoo-module **/

// Simple toggle functionality for conversation widget
let isCollapsed = true; // Mặc định thu gọn

// Setup toggle functionality
function setupToggle() {
  const toggleIcon = document.querySelector(".conversation-toggle");
  const content = document.querySelector(".conversation-content");

  if (!toggleIcon || !content) {
    return false;
  }

  // Remove any existing event listeners
  toggleIcon.removeEventListener("click", handleToggle);

  // Add click event listener
  toggleIcon.addEventListener("click", handleToggle);

  // Đảm bảo trạng thái ban đầu đúng
  if (isCollapsed) {
    content.style.display = "none";
    toggleIcon.style.transform = "rotate(180deg)";
  } else {
    content.style.display = "block";
    toggleIcon.style.transform = "rotate(0deg)";
  }

  console.log("Conversation Widget toggle initialized");
  return true;
}

// Handle toggle click
function handleToggle(e) {
  e.preventDefault();
  e.stopPropagation();

  const content = document.querySelector(".conversation-content");
  const toggleIcon = document.querySelector(".conversation-toggle");

  if (!content || !toggleIcon) return;

  isCollapsed = !isCollapsed;

  if (isCollapsed) {
    // Thu gọn
    content.style.display = "none";
    toggleIcon.style.transform = "rotate(180deg)";
  } else {
    // Mở rộng
    content.style.display = "block";
    toggleIcon.style.transform = "rotate(0deg)";
  }
}

// Luôn gắn lại event khi widget xuất hiện (dùng MutationObserver)
function observeWidget() {
  const target = document.body;
  const observer = new MutationObserver(() => {
    setupToggle(); // Gắn lại event mỗi khi DOM thay đổi
  });
  observer.observe(target, { childList: true, subtree: true });
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  setupToggle();
  observeWidget(); // Bắt đầu observe DOM changes
});

// Also try when page changes (for Odoo SPA navigation)
if (typeof window !== "undefined") {
  window.addEventListener("load", () => {
    setTimeout(setupToggle, 500);
  });

  // Listen for Odoo action changes
  window.addEventListener("hashchange", () => {
    setTimeout(setupToggle, 1000);
  });
}
