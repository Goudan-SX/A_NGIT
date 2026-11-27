/* Guardian-AI · 局域网模拟聊天 + 实时检测 */
(function () {
  'use strict';

  var API = window.AntiFraudAPI;
  var $ = function (id) { return document.getElementById(id); };
  var params = new URLSearchParams(window.location.search);
  var room = (params.get('room') || 'demo').slice(0, 64);
  var name = (params.get('name') || '访客').slice(0, 32);
  var clientId = '';
  try {
    clientId = localStorage.getItem('guardian_chat_client_id') || '';
    if (!clientId) {
      clientId = 'chat-' + (window.crypto && crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36));
      localStorage.setItem('guardian_chat_client_id', clientId);
    }
  } catch (error) {
    clientId = 'chat-' + Date.now().toString(36);
  }

  var messages = [];
  var socket = null;
  var analyzeTimer = null;
  var deepResult = null;

  function setText(id, value) {
    var el = $(id);
    if (el) el.textContent = value == null ? '' : String(value);
  }

  function toast(message, type) {
    var el = $('toast');
    if (!el) return;
    el.textContent = message;
    el.className = 'toast' + (type ? ' toast--' + type : '');
    el.classList.remove('is-hidden');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(function () { el.classList.add('is-hidden'); }, 3200);
  }

  function setStatus(text, ok) {
    setText('chat-status', text);
    var el = document.querySelector('.guard-status');
    if (!el) return;
    el.style.color = ok ? '' : 'var(--amber-600)';
  }

  function connect() {
    var protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    var url = protocol + '://' + window.location.host + '/ws/chat/' + encodeURIComponent(room)
      + '?client_id=' + encodeURIComponent(clientId) + '&name=' + encodeURIComponent(name);
    socket = new WebSocket(url);
    socket.addEventListener('open', function () {
      setStatus('已连接', true);
      setText('chat-client-name', '你是：' + name);
    });
    socket.addEventListener('message', function (event) {
      var payload = JSON.parse(event.data);
      if (payload.type === 'message') {
        messages.push(payload);
        renderMessages();
        scheduleAnalyze();
      }
    });
    socket.addEventListener('close', function () {
      setStatus('连接断开，正在重连…', false);
      setTimeout(connect, 2500);
    });
    socket.addEventListener('error', function () {
      setStatus('连接失败', false);
    });
  }

  function renderMessages() {
    var log = $('chat-log');
    if (!log) return;
    if (!messages.length) {
      log.innerHTML = '<div class="chat-empty" id="chat-empty"><strong>还没有聊天记录</strong><span>发送第一句话开始模拟；Guardian-AI 只分析当前聊天内容。</span></div>';
      return;
    }
    log.innerHTML = '';
    messages.slice(-80).forEach(function (item) {
      var self = item.client_id === clientId;
      var row = document.createElement('div');
      row.className = 'chat-row' + (self ? ' chat-row--self' : '');
      var meta = document.createElement('div');
      meta.className = 'chat-row__meta';
      meta.textContent = (self ? '你' : '对方') + ' · ' + item.timestamp;
      var bubble = document.createElement('div');
      bubble.className = 'chat-bubble';
      bubble.textContent = item.text;
      row.appendChild(meta);
      row.appendChild(bubble);
      log.appendChild(row);
    });
    log.scrollTop = log.scrollHeight;
  }

  function currentTranscript() {
    return messages.slice(-30).map(function (item) {
      return '[' + item.timestamp + '] ' + (item.client_id === clientId ? '你' : '对方') + '：' + item.text;
    }).join('\n');
  }

  function scheduleAnalyze() {
    clearTimeout(analyzeTimer);
    analyzeTimer = setTimeout(function () { analyze(false); }, 700);
  }

  function analyze(deep) {
    var text = currentTranscript();
    if (!text.trim()) {
      resetAnalysis();
      return;
    }
    setText('chat-engine', deep ? 'AI 复核中…' : '实时判定中…');
    API.analyzeText(text, false, !deep).then(function (data) {
      deepResult = data.analysis;
      renderAnalysis(deepResult);
      setText('chat-engine', deep ? 'Guardian-AI · 深度复核' : 'Guardian-AI · 实时');
    }).catch(function (error) {
      setText('chat-engine', '检测服务离线');
      toast('Guardian-AI 检测失败：' + error.message, 'error');
    });
  }

  function resetAnalysis() {
    var ring = $('chat-risk-ring');
    if (ring) {
      ring.className = 'risk-ring risk-ring--low';
      ring.style.setProperty('--score', 0);
    }
    var score = $('chat-risk-score');
    if (score) score.innerHTML = '0<span>%</span>';
    setText('chat-risk-level-text', '等待聊天内容');
    setText('chat-risk-title', '发送消息后开始实时检测');
    setText('chat-risk-desc', 'Guardian-AI 只分析当前会话的聊天记录。');
    setText('chat-keyword-count', '0 项');
    setText('chat-suggestion-count', '0 条');
    $('chat-keyword-list').innerHTML = '<li class="empty-inline">等待检测</li>';
    $('chat-suggestion-list').innerHTML = '<li class="empty-inline">暂无建议</li>';
    $('chat-dimension-list').innerHTML = '<li class="dimension"><span class="dimension__name">等待检测</span><span class="dimension__bar"><i style="width:0%"></i></span><span class="dimension__score">0</span></li>';
  }

  function renderAnalysis(result) {
    var meta = API.riskMeta(result.risk_level);
    var score = Number(result.risk_score || 0);
    var ring = $('chat-risk-ring');
    var scoreEl = $('chat-risk-score');
    if (scoreEl) {
      scoreEl.innerHTML = score + '<span>%</span>';
      scoreEl.style.color = meta.color;
    }
    if (ring) {
      ring.className = 'risk-ring risk-ring--' + meta.key;
      ring.style.setProperty('--score', score);
      ring.setAttribute('aria-label', '当前聊天诈骗风险 ' + score + '%');
    }
    var level = $('chat-risk-level');
    if (level) {
      level.className = 'risk-summary__level risk-summary__level--' + meta.key;
      level.style.color = meta.color;
    }
    setText('chat-risk-level-text', (result.risk_label || meta.label) + ' · ' + (result.risk_hint || ''));
    setText('chat-risk-title', result.scam_type && result.scam_type.indexOf('暂无') === -1
      ? '疑似「' + result.scam_type + '」诈骗' : '暂未识别到典型诈骗话术');
    setText('chat-risk-desc', result.summary || '');

    var components = (result.guardian && result.guardian.components) || result.dimensions || [];
    var list = $('chat-dimension-list');
    list.innerHTML = '';
    components.forEach(function (item) {
      var percent = item.max ? Math.round(item.score / item.max * 100) : 0;
      var li = document.createElement('li');
      li.className = 'dimension' + (percent >= 80 ? ' dimension--danger' : (percent >= 45 ? ' dimension--warn' : ''));
      li.innerHTML = '<span class="dimension__name">' + item.name + '</span><span class="dimension__bar"><i style="width:' + Math.min(100, percent) + '%"></i></span><span class="dimension__score">' + item.score + '/' + item.max + '</span>';
      list.appendChild(li);
    });

    var keywords = result.matched_keywords || [];
    var keywordList = $('chat-keyword-list');
    keywordList.innerHTML = '';
    keywords.slice(0, 12).forEach(function (word) {
      var li = document.createElement('li');
      li.className = 'tag ' + (result.risk_level === 'low' ? 'tag--neutral' : 'tag--danger');
      li.textContent = word;
      keywordList.appendChild(li);
    });
    if (!keywords.length) keywordList.innerHTML = '<li class="empty-inline">暂未命中</li>';
    setText('chat-keyword-count', keywords.length + ' 项');

    var suggestions = result.suggestions || [];
    var suggestionList = $('chat-suggestion-list');
    suggestionList.innerHTML = '';
    suggestions.forEach(function (text) {
      var li = document.createElement('li');
      li.textContent = text;
      suggestionList.appendChild(li);
    });
    if (!suggestions.length) suggestionList.innerHTML = '<li class="empty-inline">暂无建议</li>';
    setText('chat-suggestion-count', suggestions.length + ' 条');
  }

  function send() {
    var input = $('chat-input');
    if (!input || !socket || socket.readyState !== WebSocket.OPEN) {
      toast('聊天连接尚未建立', 'error');
      return;
    }
    var text = input.value.trim();
    if (!text) return;
    socket.send(JSON.stringify({ type: 'message', text: text }));
    input.value = '';
    input.focus();
  }

  function bind() {
    setText('room-name', room);
    setText('chat-client-name', '你是：' + name);
    var input = $('chat-input');
    var sendBtn = $('chat-send');
    if (sendBtn) sendBtn.addEventListener('click', send);
    if (input) {
      input.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          send();
        }
      });
    }
    var copy = $('copy-room-btn');
    if (copy) {
      copy.addEventListener('click', function () {
        var link = window.location.origin + window.location.pathname + '?room=' + encodeURIComponent(room);
        navigator.clipboard.writeText(link).then(function () {
          toast('邀请链接已复制', 'success');
        }).catch(function () {
          toast('复制失败，请手动复制地址栏链接', 'error');
        });
      });
    }
    var deep = $('chat-deep-check');
    if (deep) deep.addEventListener('click', function () { analyze(true); });
    renderMessages();
    connect();
  }

  bind();
})();
