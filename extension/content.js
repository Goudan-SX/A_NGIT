/* Guardian-AI 浏览器悬浮窗：只在聊天页面检测当前可见聊天内容。 */
(function () {
  'use strict';
  if (window.__guardianAiBadgeLoaded) return;
  window.__guardianAiBadgeLoaded = true;

  var API_BASE = 'http://127.0.0.1:8000';
  var APP_URL = 'http://127.0.0.1:8000/';
  var badge = null;
  var lastText = '';
  var lastMediaKey = '';
  var analyzingMedia = false;
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
    badge.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647;' +
      'display:flex;align-items:center;justify-content:center;width:38px;height:38px;' +
      'box-sizing:border-box;background:#fff;border-width:3px;border-style:solid;' +
      'border-radius:50%;font-family:"Microsoft YaHei","微软雅黑",sans-serif;' +
      'cursor:pointer;user-select:none;';
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
      var left = Math.max(4, Math.min(window.innerWidth - 44, drag.left + dx));
      var top = Math.max(4, Math.min(window.innerHeight - 44, drag.top + dy));
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
    if (/wx\.qq\.com|web\.wechat\.com|wechat|whatsapp|telegram|discord|messenger|slack|teams|dingtalk|feishu|lark|weibo|mail\.qq\.com|mail\.163\.com|mail\.126\.com|gmail\.com|outlook\.live\.com|outlook\.office\.com|chat|message|im\//.test(url)) return true;
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

  function isMailPage() {
    var host = location.hostname.toLowerCase();
    return /mail\.qq\.com|mail\.163\.com|mail\.126\.com|gmail\.com|outlook\.live\.com|outlook\.office\.com|mail\.sina\.com\.cn/.test(host);
  }

  function collectFrameText() {
    var texts = [];
    try {
      Array.prototype.forEach.call(document.querySelectorAll('iframe'), function (frame) {
        try {
          var doc = frame.contentDocument;
          if (!doc || !doc.body) return;
          var text = String(doc.body.innerText || '').trim();
          if (text.length > 40) texts.push(text);
        } catch (error) {
          /* cross-origin frame */
        }
      });
    } catch (error) {
      /* ignore */
    }
    texts.sort(function (a, b) { return b.length - a.length; });
    return texts[0] || '';
  }

  function collectMailText() {
    var selectors = [
      '.mail-content', '.mailContent', '#mailContent', '#mailcontent',
      '.qm_editor', '.mail_body', '.mail-body', '.mail-detail',
      '.readmail', '.mail-read', '[class*="mail-detail"]',
      '[class*="mailDetail"]', '[class*="letter-content"]',
      '[class*="mail"] [class*="content"]'
    ];
    var best = '';
    selectors.some(function (selector) {
      try {
        var nodes = Array.prototype.slice.call(document.querySelectorAll(selector));
        nodes.forEach(function (node) {
          if (!visible(node)) return;
          var text = String(node.innerText || '').trim();
          if (text.length > best.length && text.length < 20000) best = text;
        });
      } catch (error) {
        /* ignore */
      }
      return false;
    });
    if (best.length > 20) return best.slice(-6000);
    var frameText = collectFrameText();
    if (frameText) return frameText.slice(-6000);
    // 兜底：邮件正文不在已知节点时，只取当前页面可见文本
    var bodyText = String(document.body.innerText || '').trim();
    if (bodyText && bodyText.length < 20000 && /在吗|发件人|收件人|回复|转发|邮件/.test(bodyText)) {
      return bodyText.slice(-6000);
    }
    return '';
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

  function collectChatImages() {
    var selectors = [
      '.chat-bubble img',
      '.chat-image',
      '[class*="message"] img',
      '[class*="msg"] img',
      '[role="log"] img',
      '.bubble img'
    ];
    var seen = {};
    var images = [];
    selectors.forEach(function (selector) {
      try {
        document.querySelectorAll(selector).forEach(function (image) {
          if (!image || !image.src || seen[image.src]) return;
          if (image.naturalWidth && image.naturalWidth < 80) return;
          if (image.naturalHeight && image.naturalHeight < 80) return;
          var rect = image.getBoundingClientRect();
          if (rect.width < 60 || rect.height < 50) return;
          seen[image.src] = true;
          images.push(image.src);
        });
      } catch (error) {
        /* selector may not be supported */
      }
    });
    return images.slice(-2);
  }

  function analyzeMedia(text, images) {
    if (!images.length) return;
    var key = text + '|' + images.join('|');
    if (key === lastMediaKey || analyzingMedia) return;
    lastMediaKey = key;
    analyzingMedia = true;
    if (badge) badge.title = 'Guardian-AI：正在分析聊天图片…';
    var form = new FormData();
    form.append('text', text || '');
    form.append('save', 'false');
    form.append('client_id', 'guardian-extension');
    var loaded = 0;
    Promise.all(images.map(function (src, index) {
      return fetch(src, { credentials: 'include' }).then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.blob();
      }).then(function (blob) {
        if (!blob || !blob.type || blob.type.indexOf('image/') !== 0) return null;
        loaded += 1;
        var ext = blob.type.split('/')[1] || 'png';
        form.append('files', new File([blob], 'page-image-' + index + '.' + ext, { type: blob.type }));
        return true;
      }).catch(function () { return null; });
    })).then(function () {
      if (!loaded) throw new Error('no readable image');
      return fetch(API_BASE + '/api/analyze', { method: 'POST', body: form });
    }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    }).then(function (data) {
      if (data && data.analysis) setBadge(Number(data.analysis.risk_score || 0));
    }).catch(function () {
      // 图片跨域读取失败时退回文本快检，不让悬浮球卡死
      analyze(text);
    }).finally(function () {
      analyzingMedia = false;
    });
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
    var text = isMailPage() ? collectMailText() : collectMessages();
    var images = collectChatImages();
    if ((!text || text.length < 4) && !images.length) {
      idleBadge(true);
      return;
    }
    if (images.length) {
      analyzeMedia(text, images);
    } else {
      analyze(text);
    }
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