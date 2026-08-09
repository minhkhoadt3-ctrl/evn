// Config Modal Logic
// ĐẢM BẢO: Không gọi showConfigModal() khi load trang!
// Chỉ gán onclick cho nút Config:

function showMsg(msg, error) {
  const el = document.getElementById('msg');
  if (el) {
    el.textContent = msg;
    el.className = 'msg' + (error ? ' error' : '');
  }
}

// Lấy base URL cho Ingress (Home Assistant)
function getBaseUrl() {
  const match = window.location.pathname.match(/\/api\/hassio_ingress\/[^\/]+/);
  return match ? match[0] : '';
}

async function loadConfig() {
  try {
    // Load Header Title from localStorage
    const savedTitle = localStorage.getItem('headerTitle');
    const headerTitleEl = document.getElementById('header_title');
    if (headerTitleEl) {
      headerTitleEl.value = savedTitle || 'EVN MONITOR';
    }
  } catch (e) {
    showMsg('Lỗi load cấu hình: ' + e.message, true);
  }
}

const configForm = document.getElementById('configForm');
if (configForm) {
  configForm.onsubmit = async function (e) {
    e.preventDefault();

    // Save Header Title
    const headerTitleInput = document.getElementById('header_title');
    const header_title = headerTitleInput ? (headerTitleInput.value.trim() || 'EVN MONITOR') : 'EVN MONITOR';

    try {
      localStorage.setItem('headerTitle', header_title);

      // Update UI immediately (find h1 inside .content)
      const headerH1 = document.querySelector('.content h1');
      if (headerH1) headerH1.textContent = header_title;

      showMsg('Đã lưu cấu hình thành công!');
    } catch (e) {
      showMsg('Lỗi khi lưu: ' + e.message, true);
    }
  };
}

// Khi mở modal thì load config
function showConfigModal() {
  const modal = document.getElementById('configModal');
  if (modal) modal.classList.remove('hidden');
  loadConfig();
}

// Khi đóng modal
function closeConfigModal() {
  const modal = document.getElementById('configModal');
  if (modal) modal.classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', function () {
  const openConfigBtn = document.getElementById('configBtn');
  const closeConfigModalBtn = document.getElementById('closeConfigModal');

  if (openConfigBtn) {
    openConfigBtn.addEventListener('click', showConfigModal);
  }

  if (closeConfigModalBtn) {
    closeConfigModalBtn.addEventListener('click', closeConfigModal);
  }
});