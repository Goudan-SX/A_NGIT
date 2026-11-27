/* Guardian-AI 浏览器悬浮窗：只在聊天页面检测当前可见聊天内容。 */
(function () {
  'use strict';

  var API_BASE = 'http://127.0.0.1:8000';
  var APP_URL = 'http://127.0.0.1:8000/';
  var badge = null;
  var lastText = '';
  var lastScore = null;
  var timer = null;
  var drag = { active: false, moved: false, startX: 0, startY: 0, left: 0, top: 0 };

  function createBadge() {
    if (document.getElementById('guardian-ai-badge')) return;
    badge = document.createElement('div');
    badge.id = 'guardian-ai-badge';
    badge.setAttribute('role', 'button');
    badge.setAttribute('aria-label', 'Guardian-AI 反诈检测');
    badge.title = 'Guardian-AI：等待聊天页面';
    badge.innerHTML =
      '<span class="guardian-letter">G</span>' +
      '<span class="guardian-score"><span class="guardian-score__value">0</span>' +
      '<span class="guardian-score__unit">%</span></span>';
    document.documentElement.appendChild(badge);
    badge.addEventListener('click', function () {
      if (!drag.moved) window.open(APP_URL, '_blank', 'noopener');
    });
    badge.addEventListener('mousedown', function (event) {
      drag.active = true;
      drag.moved = false;
      drag.startX = event.clientX;
      drag.startY = event.clientY;
      var rect = badge.getBoundingClientRect();
      drag.left = rect.left;
      drag.top = rect.top;
      event.preventDefault();
    });
    document.addEventListener('mousemove', function (event) {
      if (!drag.active) return;
      var dx = event.clientX - drag.startX;
      var dy = event.clientY - drag.startY;
      if (Math.abs(dx) + Math.abs(dy) > 5) drag.moved = true;
      if (!drag.moved) return;
      var left = Math.max(4, Math.min(window.innerWidth - 48, drag.left + dx));
      var top = Math.max(4, Math.min(window.innerHeight - 48, drag.top + dy));
      badge.style.left = left + 'px';
      badge.style.top = top + 'px';
      badge.style.right = 'auto';
    });
    document.addEventListener('mouseup', function () {
      drag.active = false;
      setTimeout(function () { drag.moved = false; }, 0);
    });
  }

  function isChatPage() {
    var url = (location.hostname + location.pathname + location.search).toLowerCase();
    if (/wx\.qq\.com|web\.wechat\.com|wechat|whatsapp|telegram|discord|messenger|slack|teams|dingtalk|feishu|lark|weibo|chat|message|im\//.test(url)) return true;
    var selectors = [
      '#chatArea', '.chat_bd', '.chat-scroll', '[role="log"]',
      '[data-testid*="message" i]', '[data-pre-plain-text]',
      '.message-in', '.message-out',
      '[class*="chat"]', '[class*="message" i]', '[class*="msg"]'
    ];
    return selectors.some(function (selector) {
      try {
        return document.querySelectorAll(selector).length > 0;
      } catch (error) {
        return false;
      }
    });
  }

  function visible(node) {
    if (!node || !node.innerText) return false;
    var style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    var rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function collectMessages() {
    var selectors = [
      '.chat_bd .js_message',
      '.chat_bd .bubble_cont',
      '.chat_bd [class*="message"]',
      '[class*="message-list"] [class*="message" i]',
      '[class*="chat"] [class*="message" i]',
      '[class*="chat"] [class*="msg"]',
      '[role="log"] li',
      '[data-message-id]',
      '[data-testid*="message" i]',
      '[data-pre-plain-text]',
      '[id^="message-content-"]',
      '.message-in',
      '.message-out',
      '.bubble',
      '.chat-bubble',
      '.msg-content'
    ];
    var nodes = [];
    selectors.some(function (selector) {
      try {
        var found = Array.prototype.slice.call(document.querySelectorAll(selector));
        if (found.length) {
          nodes = found;
          return true;
        }
      } catch (error) {
        return false;
      }
      return false;
    });
    if (!nodes.length) {
      var box = document.querySelector('.chat_bd, #chatArea, [role="log"], [class*="chat-scroll"]');
      if (box) {
        var containerText = String(box.innerText || '').trim();
        if (/还没有聊天记录|暂无案例|正在读取/.test(containerText)) return '';
        return containerText.length > 4 ? containerText.slice(-6000) : '';
      }
      return '';
    }
    var texts = [];
    nodes.slice(-40).forEach(function (node) {
      if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') return;
      if (node.querySelector && node.querySelector('input, textarea, [type="password"]')) return;
      if (!visible(node)) return;
      var text = String(node.innerText || '').trim();
      if (!text || text.length > 2000) return;
      if (texts.indexOf(text) === -1) texts.push(text);
    });
    return texts.join('\n').slice(-6000);
  }

  function setBadge(score) {
    if (!badge) return;
    badge.classList.remove('guardian-green', 'guardian-yellow', 'guardian-orange', 'guardian-red', 'guardian-offline');
    if (score === null || score === undefined || isNaN(score)) {
      badge.classList.remove('guardian-active');
      badge.title = 'Guardian-AI：等待聊天内容';
      return;
    }
    badge.classList.add('guardian-active');
    var value = Math.max(0, Math.min(100, Math.round(score)));
    badge.querySelector('.guardian-score__value').textContent = value;
    if (value < 30) badge.classList.add('guardian-green');
    else if (value < 50) badge.classList.add('guardian-yellow');
    else if (value < 70) badge.classList.add('guardian-orange');
    else badge.classList.add('guardian-red');
    badge.title = 'Guardian-AI 当前风险：' + value + '%（点击查看详情）';
    lastScore = value;
  }

  function idleBadge(onChatPage) {
    if (!badge) return;
    badge.classList.remove('guardian-active', 'guardian-green', 'guardian-yellow', 'guardian-orange', 'guardian-red', 'guardian-offline');
    badge.title = onChatPage ? 'Guardian-AI：已进入聊天页面，等待消息' : 'Guardian-AI：未进入聊天页面';
    lastScore = null;
  }

  function analyze(text) {
    if (!text || text === lastText) return;
    lastText = text;
    fetch(API_BASE + '/api/analyze/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: text,
        save: false,
        fast: true,
        client_id: 'guardian-extension'
      })
    }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    }).then(function (data) {
      if (data && data.analysis) {
        setBadge(Number(data.analysis.risk_score || 0));
      }
    }).catch(function () {
      if (badge) {
        badge.classList.remove('guardian-active', 'guardian-green', 'guardian-yellow', 'guardian-orange', 'guardian-red');
        badge.classList.add('guardian-offline');
        badge.title = 'Guardian-AI 未连接：请先运行本地检测服务';
      }
    });
  }

  function tick() {
    if (!isChatPage()) {
      idleBadge(false);
      return;
    }
    var text = collectMessages();
    if (!text || text.length < 4) {
      idleBadge(true);
      return;
    }
    analyze(text);
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(tick, 1200);
  }

  function start() {
    createBadge();
    tick();
    var observer = new MutationObserver(schedule);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true
    });
    setInterval(tick, 3500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
