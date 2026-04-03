/* ═══════════════════════════════════════════
  Revenue AI — script.js
  ═══════════════════════════════════════════ */

// ── Authentication ─────────────────────────
function checkAuthentication() {
  // No authentication required - app is public
  return true;
}

function handleLogout() {
  // Clear tokens and user data
  localStorage.removeItem('accessToken');
  localStorage.removeItem('refreshToken');
  localStorage.removeItem('user');
  
  // Redirect to login
  window.location.href = '/auth/';
}

// Check auth on page load
document.addEventListener('DOMContentLoaded', checkAuthentication);

// ══════════════════════════════════════════════════════════════
// CHAT HISTORY API INTEGRATION
// ══════════════════════════════════════════════════════════════

async function loadChatHistoryFromAPI() {
  /**Load chat sessions from API and update sidebar.*/
  const token = localStorage.getItem('accessToken');
  if (!token) return [];
  
  try {
    const response = await fetch('/api/chatbot/chat-history/', {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    });
    
    if (response.status === 401) {
      handleLogout();
      return [];
    }
    
    if (!response.ok) {
      console.warn('Failed to load chat history:', response.status);
      return [];
    }
    
    const sessions = await response.json();
    return sessions || [];
  } catch (error) {
    console.error('Error loading chat history from API:', error);
    return [];
  }
}

async function loadChatSessionMessagesFromAPI(sessionId) {
  /**Load messages for a specific chat session from API.*/
  const token = localStorage.getItem('accessToken');
  if (!token) return null;
  
  try {
    const response = await fetch(`/api/chatbot/chat-history/${sessionId}/`, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    });
    
    if (response.status === 401) {
      handleLogout();
      return null;
    }
    
    if (!response.ok) {
      console.warn('Failed to load chat session:', response.status);
      return null;
    }
    
    return await response.json();
  } catch (error) {
    console.error('Error loading chat session from API:', error);
    return null;
  }
}

async function deleteChatSessionFromAPI(sessionId) {
  /**Delete a chat session from API.*/
  const token = localStorage.getItem('accessToken');
  if (!token) return false;
  
  try {
    const response = await fetch(`/api/chatbot/chat-history/${sessionId}/delete/`, {
      method: 'DELETE',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    });
    
    if (response.status === 401) {
      handleLogout();
      return false;
    }
    
    return response.ok;
  } catch (error) {
    console.error('Error deleting chat session:', error);
    return false;
  }
}

// ── State ──────────────────────────────────
let inChatMode   = false;
let isWaiting    = false;
let sidebarOpen  = true;

// ── Chat history ────────────────────────────
let currentChatId   = null;
let currentMessages = []; // [{role, html, text}]
let apiChatSessions = []; // Chat sessions from API

// ── Pending file attachment ──────────────────
let pendingFiles = []; // [{name, rows, cols, info}]

function _genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}
function _getHistory() {
  try { return JSON.parse(localStorage.getItem('revenueAI_history') || '[]'); }
  catch { return []; }
}
function _saveHistory(list) {
  localStorage.setItem('revenueAI_history', JSON.stringify(list.slice(0, 40)));
}

function startNewChatSession() {
  currentChatId   = _genId();
  currentMessages = [];
}

function saveCurrentChat() {
  if (!currentChatId || currentMessages.length === 0) return;
  const firstUser = currentMessages.find(m => m.role === 'user');
  if (!firstUser) return;
  const raw   = firstUser.text || firstUser.html || '';
  const title = raw.length > 52 ? raw.slice(0, 49) + '...' : raw;
  const list  = _getHistory().filter(h => h.id !== currentChatId);
  list.unshift({ id: currentChatId, title, ts: Date.now(), messages: currentMessages });
  _saveHistory(list);
  // Always track the active chat ID so it can be restored on F5
  localStorage.setItem('revenueAI_lastChatId', currentChatId);
  renderHistory();
}

function renderHistory() {
  const container = document.getElementById('recentChats');
  if (!container) return;
  const list = _getHistory();
  if (list.length === 0) {
    container.innerHTML = '<div class="sidebar-empty">Chưa có phân tích nào</div>';
    return;
  }
  const sorted = [...list].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
  container.innerHTML = sorted.map(h => {
    const d   = new Date(h.ts);
    const ts  = d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
    const act = h.id === currentChatId ? ' history-active' : '';
    const iconSvg = h.pinned
      ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V6h1a2 2 0 000-4H8a2 2 0 000 4h1v4.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V17z"/></svg>`
      : `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`;
    return `<div class="history-item-wrap">
      <div class="sidebar-item${act}" onclick="loadChat('${h.id}')" title="${escHtml(h.title)}">
        <div class="sidebar-item-icon ${h.pinned ? 'amber' : 'blue'}">${iconSvg}</div>
        <span class="history-title">${escHtml(h.title)}</span>
        <span class="history-ts">${ts}</span>
      </div>
      <button class="history-menu-btn" data-id="${h.id}" onclick="toggleHistoryMenu(event,'${h.id}')" title="Tùy chọn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>
      </button>
    </div>`;
  }).join('');
}

async function renderHistoryFromAPI() {
  /**Render chat history from API data into sidebar.*/
  const container = document.getElementById('recentChats');
  if (!container) return;
  
  apiChatSessions = await loadChatHistoryFromAPI();
  
  if (apiChatSessions.length === 0) {
    // Fallback: show localStorage history for anonymous users
    renderHistory();
    return;
  }
  
  const sorted = [...apiChatSessions].sort((a, b) => {
    const aTime = new Date(a.updated_at).getTime();
    const bTime = new Date(b.updated_at).getTime();
    return bTime - aTime;
  });
  
  container.innerHTML = sorted.map(h => {
    const d   = new Date(h.updated_at);
    const ts  = d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
    const act = h.id === currentChatId ? ' history-active' : '';
    const iconSvg = h.pinned
      ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V6h1a2 2 0 000-4H8a2 2 0 000 4h1v4.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V17z"/></svg>`
      : `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`;
    
    return `<div class="history-item-wrap">
      <div class="sidebar-item${act}" onclick="loadChatFromAPI('${h.id}')" title="${escHtml(h.title)}">
        <div class="sidebar-item-icon ${h.pinned ? 'amber' : 'blue'}">${iconSvg}</div>
        <span class="history-title">${escHtml(h.title)}</span>
        <span class="history-ts">${ts}</span>
      </div>
      <button class="history-menu-btn" data-id="${h.id}" onclick="toggleHistoryMenuAPI(event,'${h.id}')" title="Tùy chọn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>
      </button>
    </div>`;
  }).join('');
}

let _openHistoryMenuId = null;

function toggleHistoryMenu(e, id) {
  e.stopPropagation();
  if (_openHistoryMenuId === id) { closeAllHistoryMenus(); return; }
  closeAllHistoryMenus();
  _openHistoryMenuId = id;
  const btn  = e.currentTarget;
  const wrap = btn.closest('.history-item-wrap');
  const rect = btn.getBoundingClientRect();
  const list = _getHistory();
  const chat = list.find(h => h.id === id);
  if (!chat) return;

  let menu = document.getElementById('_historyMenuFloat');
  if (!menu) {
    menu = document.createElement('div');
    menu.id = '_historyMenuFloat';
    menu.className = 'history-dropdown';
    document.body.appendChild(menu);
  }
  menu.innerHTML = `
    <button class="history-dd-item" onclick="shareChat('${id}')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
      Chia sẻ cuộc trò chuyện
    </button>
    <button class="history-dd-item" onclick="pinChat('${id}')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V6h1a2 2 0 000-4H8a2 2 0 000 4h1v4.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V17z"/></svg>
      ${chat.pinned ? 'Bỏ ghim' : 'Ghim'}
    </button>
    <button class="history-dd-item" onclick="renameChat('${id}')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
      Đổi tên
    </button>
    <div class="history-dd-divider"></div>
    <button class="history-dd-item danger" onclick="deleteChat('${id}')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>
      Xoá
    </button>`;
  btn.classList.add('open');
  if (wrap) wrap.classList.add('menu-open');

  menu.style.left = Math.min(rect.right + 8, window.innerWidth - 236) + 'px';
  menu.style.top  = Math.min(rect.top,       window.innerHeight - 210) + 'px';
  menu.classList.add('open');
}

function closeAllHistoryMenus() {
  const menu = document.getElementById('_historyMenuFloat');
  if (menu) menu.classList.remove('open');
  document.querySelectorAll('.history-menu-btn.open').forEach(el => el.classList.remove('open'));
  document.querySelectorAll('.history-item-wrap.menu-open').forEach(el => el.classList.remove('menu-open'));
  _openHistoryMenuId = null;
}

function shareChat(id) {
  closeAllHistoryMenus();
  const list = _getHistory();
  const chat = list.find(h => h.id === id);
  if (!chat) return;
  const text = chat.messages.map(m => {
    const prefix  = m.role === 'user' ? 'Bạn: ' : 'Revenue AI: ';
    const content = m.html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    return prefix + content;
  }).join('\n\n');
  navigator.clipboard.writeText(`=== ${chat.title} ===\n\n${text}`)
    .then(()  => showToast('✓ Đã sao chép vào clipboard'))
    .catch(() => showToast('Không thể sao chép'));
}

async function shareChatAPI(id) {
  /**Share a chat session (copy to clipboard).*/
  closeAllHistoryMenus();
  const sessionData = await loadChatSessionMessagesFromAPI(id);
  if (!sessionData) return;
  
  const text = sessionData.messages.map(m => {
    const prefix = m.role === 'user' ? 'Bạn: ' : 'Revenue AI: ';
    const content = (m.html || m.text).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    return prefix + content;
  }).join('\n\n');
  
  navigator.clipboard.writeText(`=== ${sessionData.title} ===\n\n${text}`)
    .then(() => showToast('✓ Đã sao chép vào clipboard'))
    .catch(() => showToast('❌ Không thể sao chép'));
}

function toggleHistoryMenuAPI(e, id) {
  /**Show menu for API-based chat session.*/
  e.stopPropagation();
  if (_openHistoryMenuId === id) {
    closeAllHistoryMenus();
    return;
  }
  closeAllHistoryMenus();
  _openHistoryMenuId = id;
  const btn  = e.currentTarget;
  const wrap = btn.closest('.history-item-wrap');
  const rect = btn.getBoundingClientRect();
  const chat = apiChatSessions.find(h => h.id === parseInt(id));
  if (!chat) return;
  
  let menu = document.getElementById('_historyMenuFloat');
  if (!menu) {
    menu = document.createElement('div');
    menu.id = '_historyMenuFloat';
    menu.className = 'history-dropdown';
    document.body.appendChild(menu);
  }
  menu.innerHTML = `
    <button class="history-dd-item" onclick="shareChatAPI('${id}')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
      Chia sẻ cuộc trò chuyện
    </button>
    <div class="history-dd-divider"></div>
    <button class="history-dd-item danger" onclick="deleteChatAPI('${id}')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>
      Xoá
    </button>`;
  btn.classList.add('open');
  if (wrap) wrap.classList.add('menu-open');
  
  menu.style.left = Math.min(rect.right + 8, window.innerWidth - 236) + 'px';
  menu.style.top  = Math.min(rect.top, window.innerHeight - 140) + 'px';
  menu.classList.add('open');
}

function pinChat(id) {
  closeAllHistoryMenus();
  const list = _getHistory();
  const chat = list.find(h => h.id === id);
  if (!chat) return;
  chat.pinned = !chat.pinned;
  _saveHistory(list);
  renderHistory();
  showToast(chat.pinned ? '📌 Đã ghim' : 'Đã bỏ ghim');
}

function renameChat(id) {
  closeAllHistoryMenus();
  const wrap = document.querySelector(`.history-menu-btn[data-id="${id}"]`)?.closest('.history-item-wrap');
  if (!wrap) return;
  const titleEl = wrap.querySelector('.history-title');
  if (!titleEl) return;
  const list = _getHistory();
  const chat = list.find(h => h.id === id);
  if (!chat) return;
  const oldTitle = chat.title;
  const input = document.createElement('input');
  input.className = 'history-rename-input';
  input.value = oldTitle;
  titleEl.replaceWith(input);
  input.focus(); input.select();
  const commit = () => {
    const newTitle = input.value.trim() || oldTitle;
    chat.title = newTitle;
    _saveHistory(list);
    renderHistory();
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.value = oldTitle; input.blur(); }
  });
}

function deleteChat(id) {
  closeAllHistoryMenus();
  const list = _getHistory().filter(h => h.id !== id);
  _saveHistory(list);
  if (currentChatId === id) {
    currentChatId = null; currentMessages = [];
    startNewChatSession();
    inChatMode = false; isWaiting = false;
    chatScreen().classList.remove('active');
    chatInputArea().classList.remove('active');
    welcomeScreen().style.display = 'flex';
    chatMessages().innerHTML = '<div class="date-divider"><span id="todayDate"></span></div>';
    setTodayDate(); clearFile();
  }
  renderHistory();
  showToast('Đã xoá cuộc trò chuyện');
}

async function deleteChatAPI(id) {
  /**Delete a chat session via API.*/
  closeAllHistoryMenus();
  
  const success = await deleteChatSessionFromAPI(id);
  if (!success) {
    showToast('❌ Không thể xoá cuộc trò chuyện');
    return;
  }
  
  if (currentChatId === id) {
    currentChatId = null; currentMessages = [];
    startNewChatSession();
    inChatMode = false; isWaiting = false;
    chatScreen().classList.remove('active');
    chatInputArea().classList.remove('active');
    welcomeScreen().style.display = 'flex';
    chatMessages().innerHTML = '<div class="date-divider"><span id="todayDate"></span></div>';
    setTodayDate();
    clearFile();
  }
  
  await renderHistoryFromAPI();
  showToast('✓ Đã xoá cuộc trò chuyện');
}

function showToast(msg) {
  let t = document.getElementById('_toast');
  if (!t) { t = document.createElement('div'); t.id = '_toast'; document.body.appendChild(t); }
  t.textContent = msg;
  t.className = 'toast toast-show';
  clearTimeout(t._tmr);
  t._tmr = setTimeout(() => t.classList.remove('toast-show'), 2500);
}

function loadChat(id) {
  const list = _getHistory();
  const chat = list.find(h => h.id === id);
  if (!chat) return;
  saveCurrentChat();
  currentChatId   = chat.id;
  currentMessages = chat.messages.map(m => ({ ...m }));

  const msgs = chatMessages();
  msgs.innerHTML = '<div class="date-divider"><span id="todayDate"></span></div>';
  setTodayDate();

  chat.messages.forEach(m => {
    const row = document.createElement('div');
    row.className = 'msg-wrap ' + (m.role === 'user' ? 'user' : 'bot');

    const av = document.createElement('div');
    av.className = 'msg-avatar';
    if (m.role === 'bot') {
      av.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><rect x="2" y="12" width="4" height="10" rx="1.5" fill="white" opacity=".7"/><rect x="8" y="7" width="4" height="15" rx="1.5" fill="white" opacity=".85"/><rect x="14" y="3" width="4" height="19" rx="1.5" fill="white"/><polyline points="2,15 8,9 14,11 22,5" stroke="#fde68a" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>';
    } else {
      av.textContent = 'U';
    }
    row.appendChild(av);

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.innerHTML = m.html;
    row.appendChild(bubble);
    msgs.appendChild(row);
  });

  inChatMode = true;
  welcomeScreen().style.display = 'none';
  chatScreen().classList.add('active');
  chatInputArea().classList.add('active');
  msgs.scrollTop = msgs.scrollHeight;
  chatInput2().focus();
  renderHistory();
}

async function loadChatFromAPI(sessionId) {
  /**Load and display a chat session from API.*/
  saveCurrentChat(); // Save current chat before loading new one
  
  const sessionData = await loadChatSessionMessagesFromAPI(sessionId);
  if (!sessionData) {
    showToast('❌ Không thể tải cuộc trò chuyện');
    return;
  }
  
  currentChatId = sessionData.id;
  currentMessages = sessionData.messages.map(m => ({
    role: m.role,
    html: m.html || m.text,
    text: m.text
  }));
  
  const msgs = chatMessages();
  msgs.innerHTML = '<div class="date-divider"><span id="todayDate"></span></div>';
  setTodayDate();
  
  sessionData.messages.forEach(m => {
    const row = document.createElement('div');
    row.className = 'msg-wrap ' + (m.role === 'user' ? 'user' : 'bot');
    
    const av = document.createElement('div');
    av.className = 'msg-avatar';
    if (m.role === 'bot') {
      av.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><rect x="2" y="12" width="4" height="10" rx="1.5" fill="white" opacity=".7"/><rect x="8" y="7" width="4" height="15" rx="1.5" fill="white" opacity=".85"/><rect x="14" y="3" width="4" height="19" rx="1.5" fill="white"/><polyline points="2,15 8,9 14,11 22,5" stroke="#fde68a" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>';
    } else {
      av.textContent = 'U';
    }
    row.appendChild(av);
    
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.innerHTML = m.html || m.text;
    row.appendChild(bubble);
    msgs.appendChild(row);
  });
  
  inChatMode = true;
  welcomeScreen().style.display = 'none';
  chatScreen().classList.add('active');
  chatInputArea().classList.add('active');
  msgs.scrollTop = msgs.scrollHeight;
  chatInput2().focus();
  await renderHistoryFromAPI();
}

// ── DOM refs ───────────────────────────────
const welcomeScreen  = () => document.getElementById('welcomeScreen');
const chatScreen     = () => document.getElementById('chatScreen');
const chatInputArea  = () => document.getElementById('chatInputArea');
const chatMessages   = () => document.getElementById('chatMessages');
const typingEl       = () => document.getElementById('typingIndicator');

// Welcome input
const chatInput  = () => document.getElementById('chatInput');
const sendBtn    = () => document.getElementById('sendBtn');

// Chat-mode input
const chatInput2 = () => document.getElementById('chatInput2');
const sendBtn2   = () => document.getElementById('sendBtn2');

// ── Init ───────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setTodayDate();
  startClock();
  renderHistoryFromAPI(); // Load chat history from API
  loadSummaryBar();
  setInterval(loadSummaryBar, 60000);
  document.querySelectorAll('.tool-item-hint').forEach(el => el.remove());

  // Restore last active chat session after page reload (F5)
  const lastChatId = localStorage.getItem('revenueAI_lastChatId');
  if (lastChatId) {
    const list = _getHistory();
    const chat = list.find(h => h.id === lastChatId);
    if (chat && chat.messages && chat.messages.length > 0) {
      loadChat(lastChatId);
    } else {
      localStorage.removeItem('revenueAI_lastChatId');
    }
  }

  // Restore uploaded file banner after F5
  try {
    const savedFiles = JSON.parse(localStorage.getItem('revenueAI_lastFiles') || 'null');
    if (savedFiles && savedFiles.length > 0) {
      pendingFiles = savedFiles;
      showFileBanner(pendingFiles);
    }
  } catch (e) { localStorage.removeItem('revenueAI_lastFiles'); }

  // enable/disable send buttons
  chatInput().addEventListener('input',  () => { syncSendBtn(chatInput(), sendBtn()); });
  chatInput2().addEventListener('input', () => { syncSendBtn(chatInput2(), sendBtn2()); });

  // close tool menus on outside click
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#toolAddBtn')  && !e.target.closest('#toolMenu') && !e.target.closest('#toolAddBtn + .tool-trigger-btn'))  closeToolMenu();
    if (!e.target.closest('#toolAddBtn2') && !e.target.closest('#toolMenu2') && !e.target.closest('#toolAddBtn2 + .tool-trigger-btn')) closeToolMenu2();
    if (!e.target.closest('.history-menu-btn') && !e.target.closest('#_historyMenuFloat')) closeAllHistoryMenus();
    if (!e.target.closest('#settingsMenuWrap')) closeSettingsMenu();
  });

  // Save active chat ID before page unload (F5 / navigate away)
  window.addEventListener('beforeunload', () => {
    if (currentChatId && currentMessages.length > 0) {
      saveCurrentChat();
      localStorage.setItem('revenueAI_lastChatId', currentChatId);
    }
  });
});

function syncSendBtn(input, btn) {
  btn.disabled = input.value.trim() === '';
}

function setTodayDate() {
  const el = document.getElementById('todayDate');
  if (!el) return;
  const d = new Date();
  el.textContent = d.toLocaleDateString('vi-VN', { weekday:'long', day:'2-digit', month:'2-digit', year:'numeric' });
}

// ── Real-time clock ────────────────────────
function startClock() {
  function tick() {
    const clkEl = document.getElementById('topbarClock');
    const dateEl = document.getElementById('topbarDate');
    if (!clkEl) return;
    const now = new Date();
    clkEl.textContent = now.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    if (dateEl) dateEl.textContent = now.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }
  tick();
  setInterval(tick, 1000);
}

// ── Dark mode for full screen ────────────
function toggleMainAreaDarkMode() {
  const isDark = document.body.classList.toggle('dark-mode');
  localStorage.setItem('revenueAI_darkMode', isDark ? 'true' : 'false');
  const btn = document.getElementById('topbarDarkToggle');
  if (btn) btn.classList.toggle('active', isDark);
}

(function initDarkMode() {
  const saved = localStorage.getItem('revenueAI_darkMode');
  if (saved === 'true') {
    document.body.classList.add('dark-mode');
    const btn = document.getElementById('topbarDarkToggle');
    if (btn) btn.classList.add('active');
  }
})();

// ── Sidebar ────────────────────────────────
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  sidebarOpen = !sidebarOpen;
  if (sidebarOpen) sb.classList.remove('collapsed');
  else             sb.classList.add('collapsed');
}

// ── Transition welcome → chat ───────────────
function switchToChatMode() {
  if (inChatMode) return;
  inChatMode = true;
  if (!currentChatId) startNewChatSession();
  welcomeScreen().style.display = 'none';
  chatScreen().classList.add('active');
  chatInputArea().classList.add('active');
  chatInput2().focus();
}

// ── New chat ───────────────────────────────
function newChat() {
  saveCurrentChat();
  startNewChatSession();
  inChatMode = false;
  isWaiting  = false;
  clearFile();

  chatScreen().classList.remove('active');
  chatInputArea().classList.remove('active');
  welcomeScreen().style.display = 'flex';
  welcomeScreen().style.flexDirection = 'column';
  welcomeScreen().style.alignItems = 'center';
  welcomeScreen().style.justifyContent = 'center';

  chatMessages().innerHTML = '<div class="date-divider"><span id="todayDate"></span></div>';
  setTodayDate();
  chatInput().value  = '';
  chatInput2().value = '';
  syncSendBtn(chatInput(),  sendBtn());
  syncSendBtn(chatInput2(), sendBtn2());
  closeToolMenu();
  closeToolMenu2();
}

// ── Enter key handlers ─────────────────────
function handleKey(e)  { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }
function handleKey2(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage2(); } }

// ── Send (welcome mode) ────────────────────
function sendMessage() {
  const val = chatInput().value.trim();
  if (!val || isWaiting) return;
  switchToChatMode();
  doSend(val);
  chatInput().value = '';
  syncSendBtn(chatInput(), sendBtn());
}

// ── Send (chat mode) ───────────────────────
function sendMessage2() {
  const val = chatInput2().value.trim();
  if (!val || isWaiting) return;
  doSend(val);
  chatInput2().value = '';
  syncSendBtn(chatInput2(), sendBtn2());
}

// ── Quick send (chips / sidebar items) ─────
function sendQuick(text) {
  if (!text || isWaiting) return;
  switchToChatMode();
  doSend(text);
}

// ── Core send logic ────────────────────────
function doSend(text) {
  // build user bubble: text + optional file chips
  const fileChips = pendingFiles.length > 0
    ? pendingFiles.map(pf => `<div class="msg-file-chip">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        <span class="msg-file-chip-name">${escHtml(pf.name)}</span>
        <span class="msg-file-chip-info">${escHtml(pf.info)}</span>
       </div>`).join('')
    : '';
  addMessage('user', escHtml(text), fileChips);
  clearFile();  // Remove file banner after sending
  _fetchChat(text);
}

function _fetchChat(text, attempt) {
  showTyping();
  isWaiting = true;

  const apiUrl = (window.DJANGO_API_BASE || '/api/chatbot/public') + '/send-message/';
  
  // Get CSRF token from DOM
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  
  // Get JWT token from localStorage
  const jwtToken = localStorage.getItem('accessToken');
  
  const headers = { 'Content-Type': 'application/json' };
  if (csrfToken) {
    headers['X-CSRFToken'] = csrfToken;
  }
  if (jwtToken) {
    headers['Authorization'] = 'Bearer ' + jwtToken;
  }
  
  fetch(apiUrl, {
    method: 'POST',
    headers: headers,
    body: JSON.stringify({ text: text, session_key: currentChatId || 'default' })
  })
  .then(r => {
    console.log('Response status:', r.status);
    if (r.status === 401) {
      // Unauthorized - redirect to login
      localStorage.removeItem('accessToken');
      localStorage.removeItem('refreshToken');
      localStorage.removeItem('user');
      window.location.href = '/auth/';
      return;
    }
    if (r.status === 429) {
      return r.json().then(d => { throw { rateLimited: true, retryAfter: d.retry_after || 20 }; });
    }
    if (!r.ok) {
      throw new Error(`HTTP ${r.status}: ${r.statusText}`);
    }
    return r.json();
  })
  .then(data => {
    console.log('Response data:', data);
    hideTyping();
    isWaiting = false;
    
    if (!data) {
      throw new Error('Empty response from server');
    }
    
    const reply = data.bot_response || data.reply || data.html || data.response || data.error || 'Không có phản hồi.';
    if (!reply) {
      throw new Error('No reply found in response');
    }
    
    addMessage('bot', reply);
  })
  .catch(err => {
    console.error('Error in _fetchChat:', err);
    if (err && err.rateLimited) {
      startRateLimitCountdown(err.retryAfter, text);
    } else {
      hideTyping();
      isWaiting = false;
      const errorMsg = err?.message || 'Lỗi không xác định';
      console.error('Final error:', errorMsg);
      addMessage('bot', `<div style="color:#f28b82">Lỗi: ${errorMsg}</div>`);
    }
  });
}

let _countdownTimer = null;

function startRateLimitCountdown(seconds, originalText) {
  let remaining = seconds;
  // update typing indicator label to show countdown
  const label = typingEl().querySelector('.typing-label');
  const updateLabel = () => {
    if (label) label.textContent = `Gemini đang bận, thử lại sau ${remaining}s...`;
  };
  updateLabel();

  clearInterval(_countdownTimer);
  _countdownTimer = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      clearInterval(_countdownTimer);
      if (label) label.textContent = 'Revenue AI đang phân tích...';
      _fetchChat(originalText); // auto retry
    } else {
      updateLabel();
    }
  }, 1000);
}

// ── Add message bubble ─────────────────────
// fileChipHtml is optional; only used for user rows
function addMessage(role, html, fileChipHtml = '') {
  const msgs = chatMessages();

  const row = document.createElement('div');
  row.className = 'msg-wrap ' + (role === 'user' ? 'user' : 'bot');

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  if (role === 'bot') {
    avatar.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><rect x="2" y="12" width="4" height="10" rx="1.5" fill="white" opacity=".7"/><rect x="8" y="7" width="4" height="15" rx="1.5" fill="white" opacity=".85"/><rect x="14" y="3" width="4" height="19" rx="1.5" fill="white"/><polyline points="2,15 8,9 14,11 22,5" stroke="#fde68a" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>';
  } else {
    avatar.textContent = 'U';
  }
  row.appendChild(avatar);

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  const displayHtml = role === 'bot' ? _enrichBotHtml(html) : html;
  if (fileChipHtml) {
    bubble.innerHTML = fileChipHtml + '<div class="msg-text">' + displayHtml + '</div>';
  } else {
    bubble.innerHTML = displayHtml;
  }
  row.appendChild(bubble);

  msgs.appendChild(row);
  msgs.scrollTop = msgs.scrollHeight;

  // persist to current session
  if (currentChatId) {
    const text = role === 'user' ? html : '';
    const fullHtml = fileChipHtml ? fileChipHtml + '<div class="msg-text">' + displayHtml + '</div>' : displayHtml;
    currentMessages.push({ role, html: fullHtml, text });
    saveCurrentChat(); // Save after every message (user AND bot)
  }
}

// ── Typing indicator ───────────────────────
function showTyping() { typingEl().classList.add('active'); chatMessages().scrollTop = chatMessages().scrollHeight; }
function hideTyping() { typingEl().classList.remove('active'); }

// ── Tool menus ─────────────────────────────
function toggleToolMenu() {
  const m = document.getElementById('toolMenu');
  const b = document.getElementById('toolAddBtn');
  const t = b?.nextElementSibling;
  const isOpen = m.classList.toggle('open');
  b.classList.toggle('active', isOpen);
  t?.classList.toggle('active', isOpen);
  if (isOpen) {
    document.getElementById('toolMenu2')?.classList.remove('open');
    document.getElementById('toolAddBtn2')?.classList.remove('active');
    document.getElementById('toolAddBtn2')?.nextElementSibling?.classList.remove('active');
  }
}
function closeToolMenu() {
  document.getElementById('toolMenu')?.classList.remove('open');
  document.getElementById('toolAddBtn')?.classList.remove('active');
  document.getElementById('toolAddBtn')?.nextElementSibling?.classList.remove('active');
}
function toggleToolMenu2() {
  const m = document.getElementById('toolMenu2');
  const b = document.getElementById('toolAddBtn2');
  const t = b?.nextElementSibling;
  const isOpen = m.classList.toggle('open');
  b.classList.toggle('active', isOpen);
  t?.classList.toggle('active', isOpen);
  if (isOpen) {
    document.getElementById('toolMenu')?.classList.remove('open');
    document.getElementById('toolAddBtn')?.classList.remove('active');
    document.getElementById('toolAddBtn')?.nextElementSibling?.classList.remove('active');
  }
}
function closeToolMenu2() {
  document.getElementById('toolMenu2')?.classList.remove('open');
  document.getElementById('toolAddBtn2')?.classList.remove('active');
  document.getElementById('toolAddBtn2')?.nextElementSibling?.classList.remove('active');
}

// ── File upload ────────────────────────────
function triggerUpload() {
  closeToolMenu();
  closeToolMenu2();
  document.getElementById('fileUploadInput').click();
}

function handleFileUpload(input) {
  const files = Array.from(input.files);
  if (!files.length) return;

  const label = files.length === 1 ? files[0].name : `${files.length} tệp`;
  showUploadProgress(label);

  const fd = new FormData();
  files.forEach(f => fd.append('files', f));

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/upload');

  xhr.upload.addEventListener('progress', e => {
    if (e.lengthComputable) updateUploadProgress(Math.round(e.loaded / e.total * 100));
  });

  xhr.addEventListener('load', () => {
    hideUploadProgress();
    try {
      const data = JSON.parse(xhr.responseText);
      if (data.status === 'success' && data.files) {
        pendingFiles = data.files; // [{name, rows, cols, info}]
        showFileBanner(pendingFiles);
        // Persist file info so it survives F5
        localStorage.setItem('revenueAI_lastFiles', JSON.stringify(pendingFiles));
        const names = pendingFiles.map(f => f.name).join(', ');
        showToast(`✓ Đã tải ${pendingFiles.length} tệp: ${names}`);
        loadSummaryBar();
        setTimeout(() => (inChatMode ? chatInput2() : chatInput()).focus(), 100);
      } else if (data.error) {
        if (!inChatMode) switchToChatMode();
        addMessage('bot', `<div style="color:#f28b82">⚠️ ${escHtml(data.error)}</div>`);
      }
    } catch (e) {
      console.error('Parse error:', e);
      showToast('Lỗi xử lý phản hồi server.');
    }
  });

  xhr.addEventListener('error', () => {
    hideUploadProgress();
    console.error('Upload error');
    showToast('Lỗi tải file. Vui lòng thử lại.');
  });

  xhr.send(fd);
  input.value = '';
}

function showUploadProgress(filename) {
  let el = document.getElementById('_uploadProgress');
  if (!el) {
    el = document.createElement('div');
    el.id = '_uploadProgress';
    el.className = 'upload-progress-toast';
    document.body.appendChild(el);
  }
  el.innerHTML = `
    <div class="upt-icon">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
    </div>
    <div class="upt-info">
      <div class="upt-name">${escHtml(filename)}</div>
      <div class="upt-bar-wrap"><div class="upt-bar" id="_uptBar"></div></div>
      <div class="upt-pct" id="_uptPct">0%</div>
    </div>`;
  el.classList.add('show');
}
function updateUploadProgress(pct) {
  const bar = document.getElementById('_uptBar');
  const txt = document.getElementById('_uptPct');
  if (bar) bar.style.width = pct + '%';
  if (txt) txt.textContent  = pct + '%';
}
function hideUploadProgress() {
  const el = document.getElementById('_uploadProgress');
  if (el) { el.classList.remove('show'); }
}

function showFileBanner(files) {
  if (!files || files.length === 0) return;

  ['fileBanner','fileBanner2'].forEach((id, i) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('active');
    el.classList.add('has-file');
    const nameEl = document.getElementById(i === 0 ? 'fileBannerName' : 'fileBannerName2');
    const infoEl = document.getElementById(i === 0 ? 'fileBannerInfo' : 'fileBannerInfo2');
    if (files.length === 1) {
      nameEl.textContent = files[0].name;
      infoEl.textContent = _buildFileTypeLabel(files[0].name, files[0].info);
    } else {
      nameEl.textContent = `${files.length} tệp đã tải`;
      infoEl.textContent = files.map(f => f.name).join(' · ');
    }
  });
}

function clearFile() {
  pendingFiles = [];
  localStorage.removeItem('revenueAI_lastFiles');
  ['fileBanner','fileBanner2'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('has-file');
  });
}

function _buildFileTypeLabel(name, info) {
  const ext = name.split('.').pop().toLowerCase();
  return (ext === 'csv') ? 'CSV · ' + info : (ext === 'xlsx' || ext === 'xls') ? 'Excel · ' + info : info;
}

// Display file as message in chat area
function addFileMessageToChat(filename, info) {
  const fileChip = `<div class="msg-file-chip">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
    <span class="msg-file-chip-name">${escHtml(filename)}</span>
    <span class="msg-file-chip-info">${escHtml(info)}</span>
  </div>`;
  addMessage('user', fileChip);
}

// ── Chart modal ────────────────────────────
function openChartModal(title, chartHtml) {
  document.getElementById('chartModalTitle').textContent = title;
  document.getElementById('chartModalBody').innerHTML = chartHtml;
  document.getElementById('chartModal').classList.add('open');
}
function closeChartModal() {
  document.getElementById('chartModal').classList.remove('open');
}

// ── Util ───────────────────────────────────
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ═══════════════════════════════════════════
//  CHART PANEL
// ═══════════════════════════════════════════
const CHART_META = {
  overview: { title:'Tổng quan doanh thu', sub:'Doanh thu theo tháng', askText:'Phân tích tổng quan doanh thu cho tôi' },
  decline:  { title:'Nguyên nhân sụt giảm', sub:'Số lượng & doanh thu theo tháng', askText:'Doanh thu đang giảm do nguyên nhân gì?' },
  product:  { title:'Doanh thu theo sản phẩm', sub:'So sánh từng mặt hàng', askText:'Sản phẩm nào đang bán chạy nhất?' },
  region:   { title:'Phân tích khu vực', sub:'Tỷ trọng doanh thu theo vùng', askText:'Khu vực nào doanh thu kém nhất?' },
  forecast: { title:'Dự báo xu hướng', sub:'Dự báo 3 tháng tiếp theo', askText:'Dự báo doanh thu tháng sau' },
};

let _activeChart = null;

function openChart(type) {
  const meta = CHART_META[type];
  if (!meta) return;

  document.getElementById('chartPanelTitle').textContent = meta.title;
  document.getElementById('chartPanelSub').textContent   = meta.sub;
  document.getElementById('chartPanelBody').innerHTML    =
    '<div class="chart-loading"><div class="dot"></div><div class="dot"></div><div class="dot"></div><span>Đang tải dữ liệu...</span></div>';

  document.getElementById('chartPanel').classList.add('open');
  document.getElementById('chartPanelOverlay').classList.add('open');

  if (_activeChart) { _activeChart.destroy(); _activeChart = null; }

  fetch('/api/chart-data/?type=' + type)
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        document.getElementById('chartPanelBody').innerHTML =
          '<div style="padding:48px;text-align:center;color:var(--red)">⚠️ ' + escHtml(data.error) + '</div>';
        return;
      }
      _renderChartPanel(type, data, meta);
    })
    .catch(() => {
      document.getElementById('chartPanelBody').innerHTML =
        '<div style="padding:48px;text-align:center;color:var(--red)">Lỗi kết nối server</div>';
    });
}

function closeChartPanel() {
  document.getElementById('chartPanel').classList.remove('open');
  document.getElementById('chartPanelOverlay').classList.remove('open');
  if (_activeChart) { _activeChart.destroy(); _activeChart = null; }
}

function _fmtRev(v) {
  if (v >= 1e9)  return (v / 1e9).toFixed(1)  + 'B';
  if (v >= 1e6)  return (v / 1e6).toFixed(1)  + 'M';
  if (v >= 1e3)  return (v / 1e3).toFixed(0)  + 'K';
  return String(v);
}

function _renderChartPanel(type, data, meta) {
  const body = document.getElementById('chartPanelBody');
  let statsHtml = '';

  if (type === 'overview' && data.data.length > 0) {
    const total  = data.data.reduce((a, b) => a + b, 0);
    const avg    = Math.round(total / data.data.length);
    const last   = data.data[data.data.length - 1] || 0;
    const prev   = data.data[data.data.length - 2] || last || 1;
    const chg    = Math.round((last - prev) / prev * 100);
    statsHtml = `<div class="chart-stats-row">
      <div class="chart-stat-card"><div class="chart-stat-value green">${_fmtRev(total)}</div><div class="chart-stat-label">Tổng DT</div></div>
      <div class="chart-stat-card"><div class="chart-stat-value blue">${_fmtRev(avg)}</div><div class="chart-stat-label">TB/Tháng</div></div>
      <div class="chart-stat-card"><div class="chart-stat-value ${chg >= 0 ? 'green' : 'red'}">${chg >= 0 ? '+' : ''}${chg}%</div><div class="chart-stat-label">Tháng cuối</div></div>
    </div>`;
  }

  const heights = { overview:220, product:300, region:260, decline:240, forecast:230 };
  body.innerHTML = statsHtml
    + `<div class="chart-canvas-wrap"><canvas id="_mainChart" height="${heights[type] || 240}"></canvas></div>`
    + `<button class="chart-ask-btn" onclick="askAIFromChart('${escHtml(meta.askText)}')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
        Hỏi AI phân tích sâu hơn
       </button>`;

  const canvas = document.getElementById('_mainChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  Chart.defaults.color        = '#6b7280';
  Chart.defaults.borderColor  = 'rgba(124,58,237,.08)';
  Chart.defaults.font.family  = "'Inter', sans-serif";

  const colors6 = ['#7c3aed','#a855f7','#ec4899','#f59e0b','#3b82f6','#0d9488','#fb923c','#f43f5e'];

  if (type === 'overview') {
    _activeChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.labels,
        datasets: [{ label: 'Doanh thu', data: data.data, borderColor: '#7c3aed',
          backgroundColor: 'rgba(124,58,237,.08)', borderWidth: 2.5,
          pointBackgroundColor: '#7c3aed', pointRadius: 4, pointHoverRadius: 7,
          tension: .4, fill: true }]
      },
      options: { responsive:true, plugins:{ legend:{display:false},
        tooltip:{callbacks:{label: c => ' ' + _fmtRev(c.raw)}} },
        scales:{ x:{grid:{color:'rgba(124,58,237,.07)'}, ticks:{maxTicksLimit:8}},
                 y:{grid:{color:'rgba(124,58,237,.07)'}, ticks:{callback: v => _fmtRev(v)}} } }
    });
  } else if (type === 'product') {
    _activeChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.labels,
        datasets: [{ label: 'Doanh thu', data: data.data,
          backgroundColor: data.labels.map((_, i) => colors6[i % colors6.length] + 'cc'),
          borderRadius: 6, borderSkipped: false }]
      },
      options: { indexAxis:'y', responsive:true,
        plugins:{ legend:{display:false}, tooltip:{callbacks:{label: c => ' ' + _fmtRev(c.raw)}} },
        scales:{ x:{grid:{color:'rgba(124,58,237,.07)'}, ticks:{callback: v => _fmtRev(v)}},
                 y:{grid:{display:false}} } }
    });
  } else if (type === 'region') {
    _activeChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: data.labels,
        datasets: [{ data: data.data, backgroundColor: colors6,
          borderColor: '#ffffff', borderWidth: 3, hoverOffset: 10 }]
      },
      options: { responsive:true, cutout:'62%',
        plugins:{ legend:{position:'bottom', labels:{padding:16, font:{size:12}}},
          tooltip:{callbacks:{label: c => ' ' + c.label + ': ' + _fmtRev(c.raw)}} } }
    });
  } else if (type === 'decline') {
    _activeChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.labels,
        datasets: [
          { label: 'Doanh thu', data: data.revenue, backgroundColor: 'rgba(124,58,237,.75)', borderRadius: 5 },
          { label: 'Số lượng (×1K)', data: data.quantity.map(v => v * 1000), backgroundColor: 'rgba(236,72,153,.65)', borderRadius: 5 }
        ]
      },
      options: { responsive:true,
        plugins:{ legend:{position:'bottom', labels:{padding:14}},
          tooltip:{callbacks:{label: c => c.datasetIndex===0 ? ' DT: '+_fmtRev(c.raw) : ' SL: '+Math.round(c.raw/1000)+' sp'}} },
        scales:{ x:{grid:{color:'rgba(124,58,237,.07)'}}, y:{grid:{color:'rgba(124,58,237,.07)'}} } }
    });
  } else if (type === 'forecast') {
    const allLabels = [...data.labels, ...data.forecast_labels];
    _activeChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: allLabels,
        datasets: [
          { label:'Thực tế', data:[...data.actual, ...Array(data.forecast_labels.length).fill(null)],
            borderColor:'#7c3aed', backgroundColor:'rgba(124,58,237,.07)', borderWidth:2.5,
            pointRadius:3, tension:.4, fill:true },
          { label:'Dự báo', data:[...Array(data.actual.length-1).fill(null), data.actual[data.actual.length-1], ...data.forecast],
            borderColor:'#ec4899', backgroundColor:'rgba(236,72,153,.06)', borderWidth:2,
            borderDash:[7,4], pointRadius:5, pointBackgroundColor:'#ec4899', tension:.4, fill:true }
        ]
      },
      options:{ responsive:true,
        plugins:{ legend:{position:'bottom', labels:{padding:14}},
          tooltip:{callbacks:{label: c => c.raw!=null ? ' '+c.dataset.label+': '+_fmtRev(c.raw) : ''}} },
        scales:{ x:{grid:{color:'rgba(124,58,237,.07)'}, ticks:{maxTicksLimit:8}},
                 y:{grid:{color:'rgba(124,58,237,.07)'}, ticks:{callback: v => _fmtRev(v)}} } }
    });
  }
}

function askAIFromChart(text) {
  closeChartPanel();
  sendQuick(text);
}

// ═════════════════════════════════════════
//  BOT RESPONSE ENRICHMENT
// ═════════════════════════════════════════

function _enrichBotHtml(rawHtml) {
  // Skip if already enriched
  if (rawHtml.includes('pct-tag') || rawHtml.includes('num-val')) return rawHtml;

  const tmp = document.createElement('div');
  tmp.innerHTML = rawHtml;

  // Walk all text nodes, skip code/pre blocks
  const SKIP = new Set(['CODE', 'PRE', 'SCRIPT', 'STYLE']);
  const walker = document.createTreeWalker(tmp, NodeFilter.SHOW_TEXT, null, false);
  const nodes = [];
  let n;
  while ((n = walker.nextNode())) {
    let el = n.parentElement; let skip = false;
    while (el) { if (SKIP.has(el.tagName)) { skip = true; break; } el = el.parentElement; }
    if (!skip) nodes.push(n);
  }

  nodes.forEach(node => {
    const raw = node.textContent;
    if (!/\d/.test(raw)) return;
    // Escape then replace — order: specific patterns first
    let h = raw.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    h = h.replace(/(giảm\s+\d+(?:[.,]\d+)?%)/gi,  '<span class="pct-tag pct-neg">$1</span>');
    h = h.replace(/(tăng\s+\d+(?:[.,]\d+)?%)/gi,  '<span class="pct-tag pct-pos">$1</span>');
    h = h.replace(/((?:^|[\s(])-\d+(?:[.,]\d+)?%)/g, '<span class="pct-tag pct-neg">$1</span>');
    h = h.replace(/((?:^|[\s(])\+\d+(?:[.,]\d+)?%)/g,'<span class="pct-tag pct-pos">$1</span>');
    h = h.replace(/(\d+(?:[.,]\d+)?%)/g,               '<span class="pct-tag">$1</span>');
    // Big currency values
    h = h.replace(/(\d[\d,.]*\s*(?:tỷ đồng|tỷ|triệu đồng|triệu))/gi, '<span class="num-val">$1</span>');
    const escaped = raw.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    if (h !== escaped) {
      const wrap = document.createElement('span');
      wrap.innerHTML = h;
      node.parentNode.replaceChild(wrap, node);
    }
  });

  // Wrap key insight paragraphs in highlighted card
  const KEY = ['nguyên nhân chính','nguyên nhân chủ yếu','nguyên nhân số','yếu tố chính','điểm mấu chốt'];
  tmp.querySelectorAll('p, li').forEach(el => {
    if (el.closest('.insight-card')) return;
    const t = el.textContent.toLowerCase();
    if (KEY.some(k => t.includes(k)) && el.textContent.trim().length > 10) {
      const card = document.createElement('div');
      card.className = 'insight-card';
      el.replaceWith(card);
      card.appendChild(el);
    }
  });

  return tmp.innerHTML;
}

// ═════════════════════════════════════════
//  SUMMARY BAR
// ═════════════════════════════════════════

function loadSummaryBar() {
  fetch('/api/summary/')
    .then(r => r.json())
    .then(data => {
      const bar = document.getElementById('summaryBar');
      if (!bar) return;
      if (!data.has_data) {
        bar.classList.remove('sb-visible');
        return;
      }

      const fmtRevenue = v => {
        const n = Number(v || 0);
        if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1).replace(/\.0$/, '') + ' tỷ';
        if (n >= 1_000_000)     return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + ' tr';
        if (n >= 1_000)         return (n / 1_000).toFixed(0) + 'K';
        return Math.round(n).toLocaleString('vi-VN');
      };
      const fmtCount = v => Number(v || 0).toLocaleString('vi-VN');
      const fmtPct = v => {
        const n = Number(v || 0);
        const txt = n.toFixed(1).replace(/\.0$/, '');
        return `${n > 0 ? '+' : ''}${txt}%`;
      };
      const shareTag = (v, weak = false) => {
        const n = Number(v || 0);
        const txt = n.toFixed(1).replace(/\.0$/, '');
        return `<span class="pct-tag ${weak ? 'pct-neg' : 'pct-pos'}">${txt}%</span>`;
      };
      const safeName = v => escHtml(String(v || '—'));

      const chg = Number(data.rev_change || 0);
      const chgCls = chg >= 0 ? 'sb-pos' : 'sb-neg';
      const delta = Number(data.rev_change_amount || 0);
      const deltaTxt = `${delta >= 0 ? '+' : '-'}${fmtRevenue(Math.abs(delta))}`;

      const set = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };

      set('sbTotalRevValue',   `<span class="num-val">${fmtRevenue(data.total_revenue)}</span>`);
      set('sbRevValue',        `<span class="${chgCls}">${fmtPct(chg)}</span>`);
      set('sbCurrentMonthValue', `<span class="num-val">${fmtRevenue(data.current_month_revenue)}</span><span class="sb-sub">${safeName(data.current_month_label)}</span>`);
      set('sbPrevMonthValue', `<span class="num-val">${fmtRevenue(data.previous_month_revenue)}</span><span class="sb-sub">${safeName(data.previous_month_label)}</span>`);
      set('sbDeltaMonthValue', `<span class="${delta >= 0 ? 'sb-pos' : 'sb-neg'}">${deltaTxt}</span>`);
      set('sbAvgOrderValue', `<span class="num-val">${fmtRevenue(data.avg_order_value)}</span>`);
      set('sbTotalRowsValue',  `<span class="num-val">${fmtCount(data.total_rows)}</span>`);
      set('sbBestProductValue', `${safeName(data.best_product)} ${shareTag(data.best_product_share_pct)}`);
      set('sbProductValue', `${safeName(data.worst_product)} ${shareTag(data.worst_product_share_pct, true)}`);
      set('sbBestChannelValue', `${safeName(data.best_channel)} ${shareTag(data.best_channel_share_pct)}`);
      set('sbChannelValue', `${safeName(data.worst_channel)} ${shareTag(data.worst_channel_share_pct, true)}`);
      set('sbBestRegionValue', `${safeName(data.best_region)} ${shareTag(data.best_region_share_pct)}`);
      set('sbWorstRegionValue', `${safeName(data.worst_region)} ${shareTag(data.worst_region_share_pct, true)}`);
      set('sbUpdatedAt', new Date().toLocaleTimeString('vi-VN', { hour:'2-digit', minute:'2-digit', second:'2-digit' }));

      bar.classList.add('sb-visible');
    })
    .catch(() => {}); // silent fail
}

// ── Settings & Help menu ───────────────────────────────────────────────
function toggleSettingsMenu() {
  const popup = document.getElementById('settingsPopup');
  if (!popup) return;
  const isOpen = popup.classList.contains('open');
  closeSettingsMenu();
  if (!isOpen) popup.classList.add('open');
}

function closeSettingsMenu() {
  const popup = document.getElementById('settingsPopup');
  if (popup) popup.classList.remove('open');
  document.getElementById('themeSubMenu')?.classList.remove('open');
  document.getElementById('helpSubMenu')?.classList.remove('open');
}

function toggleThemeMenu(e) {
  e.stopPropagation();
  const m = document.getElementById('themeSubMenu');
  const h = document.getElementById('helpSubMenu');
  h?.classList.remove('open');
  m?.classList.toggle('open');
}

function toggleHelpMenu(e) {
  e.stopPropagation();
  const h = document.getElementById('helpSubMenu');
  const m = document.getElementById('themeSubMenu');
  m?.classList.remove('open');
  h?.classList.toggle('open');
}

function setTheme(mode) {
  const root = document.documentElement;
  if (mode === 'dark') {
    root.style.setProperty('--bg', '#0f0f13');
    root.style.setProperty('--surface', '#18181f');
    root.style.setProperty('--sidebar-bg', '#111118');
    root.style.setProperty('--text', '#f1f0ff');
    root.style.setProperty('--text-muted', '#8b8a9e');
    root.style.setProperty('--border', 'rgba(255,255,255,.08)');
    root.style.setProperty('--border2', 'rgba(255,255,255,.12)');
  } else if (mode === 'light') {
    root.style.removeProperty('--bg');
    root.style.removeProperty('--surface');
    root.style.removeProperty('--sidebar-bg');
    root.style.removeProperty('--text');
    root.style.removeProperty('--text-muted');
    root.style.removeProperty('--border');
    root.style.removeProperty('--border2');
  } else {
    // system
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    setTheme(dark ? 'dark' : 'light');
    return;
  }
  localStorage.setItem('revenueAI_theme', mode);
  closeSettingsMenu();
  showToast(`✓ Đã đổi giao diện: ${mode === 'dark' ? 'Tối' : 'Sáng'}`);
}

function clearAllHistory() {
  if (!confirm('Xóa toàn bộ lịch sử phân tích?')) return;
  localStorage.removeItem('revenueAI_history');
  currentChatId = null;
  currentMessages = [];
  renderHistory();
  closeSettingsMenu();
  showToast('✓ Đã xóa toàn bộ lịch sử');
}

function openActivityLog() {
  closeSettingsMenu();
  const list = _getHistory();
  if (list.length === 0) { showToast('Chưa có hoạt động nào'); return; }
  const lines = list.slice(0, 10).map((h, i) => {
    const d = new Date(h.ts).toLocaleString('vi-VN', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
    return `${i + 1}. [${d}] ${h.title}`;
  }).join('\n');
  alert('Lịch sử hoạt động gần đây:\n\n' + lines);
}

function openDataSources() {
  closeSettingsMenu();
  showToast('Kéo & thả file Excel / CSV vào ô nhập để tải dữ liệu mới');
}

function openExportSettings() {
  closeSettingsMenu();
  showToast('Tính năng xuất báo cáo đang phát triển — sắp ra mắt!');
}

function sendFeedback() {
  closeSettingsMenu();
  const msg = prompt('Gửi phản hồi đến Revenue AI:');
  if (msg && msg.trim()) showToast('✓ Cảm ơn! Phản hồi của bạn đã được ghi nhận.');
}

function showShortcutsHelp() {
  closeSettingsMenu();
  alert('Phím tắt:\n\nEnter — Gửi tin nhắn\nCtrl+Shift+R — Tải lại trang\nEsc — Đóng menu');
}

function showFormatHelp() {
  closeSettingsMenu();
  alert('Định dạng file hỗ trợ:\n\n• Excel (.xlsx, .xls)\n• CSV (.csv)\n\nFile cần có các cột: date, product, channel, region, quantity, unit_price, revenue');
}

function showAbout() {
  closeSettingsMenu();
  alert('Revenue AI v1.0\n\nTrợ lý phân tích doanh thu thông minh\nPowered by Gemini 2.5 Flash · Django · Pandas\n\n© 2026 Revenue AI');
}

// Apply saved theme on load
(function() {
  const saved = localStorage.getItem('revenueAI_theme');
  if (saved) setTheme(saved);
})();

