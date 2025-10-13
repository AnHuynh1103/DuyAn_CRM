/** @odoo-module **/

// ===================================================================
// DAC ERP - Conversation Widget & Sale Order Form JavaScript
// File: conversation_widget.js
// Description: Tổng hợp JavaScript cho Conversation Widget và Sale Order Form
// ===================================================================

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

// Responsive handling for conversation widget
function handleResponsiveConversationWidget() {
  const conversationWidget = document.querySelector(
    ".conversation-widget-container"
  );

  if (!conversationWidget) return;

  if (window.innerWidth <= 768) {
    // Mobile: move to bottom of sheet
    const sheet = document.querySelector(".sheet");
    if (sheet && conversationWidget.parentNode !== sheet) {
      sheet.appendChild(conversationWidget);
    }
  } else {
    // Desktop: move back to fixed position
    const form = document.querySelector(".dac-sale-form");
    if (form && conversationWidget.parentNode !== form) {
      form.appendChild(conversationWidget);
    }
  }
}

// Luôn gắn lại event khi widget xuất hiện (dùng MutationObserver)
function observeWidget() {
  const target = document.body;
  const observer = new MutationObserver(() => {
    setupToggle(); // Gắn lại event mỗi khi DOM thay đổi
    handleResponsiveConversationWidget(); // Handle responsive
  });
  observer.observe(target, { childList: true, subtree: true });
}

// Handle window resize for responsive design
function setupResponsiveHandling() {
  window.addEventListener("resize", handleResponsiveConversationWidget);
  // Initial check
  handleResponsiveConversationWidget();
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  setupToggle();
  setupResponsiveHandling();
  observeWidget(); // Bắt đầu observe DOM changes
});

// Also try when page changes (for Odoo SPA navigation)
if (typeof window !== "undefined") {
  window.addEventListener("load", () => {
    setTimeout(() => {
      setupToggle();
      setupResponsiveHandling();
    }, 500);
  });

  // Listen for Odoo action changes
  window.addEventListener("hashchange", () => {
    setTimeout(() => {
      setupToggle();
      setupResponsiveHandling();
    }, 1000);
  });
}
