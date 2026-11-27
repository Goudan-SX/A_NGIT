/* ==========================================================================
   反诈卫士 · 运行日志页
   ========================================================================== */
(function () {
  'use strict';

  var API = window.AntiFraudAPI;
  var state = { page: 1, size: 30, pages: 1, total: 0, timer: null };

  function $(id) { return document.getElementById(id); }
  function setText(id, value) {
    var el = $(id);
    if (el) el.textContent = value == null ? '' : String(value);
  }
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  function toast(message, type) {
    var el = $('toast');
    if (!el) return;
    el.textContent = message;
    el.className = 'toast' + (type ? ' toast--' + type : '');
    el.classList.remove('is-hidden');
    window.clearTimeout(toast._timer);
    toast._timer = window.setTimeout(function () { el.classList.add('is-hidden'); }, 3600);
  }

  function loadStats() {
    API.get('/api/logs/stats').then(function (data) {
      setText('log-total', data.total);
      setText('log-warning', data.levels ? data.levels.warning : 0);
      setText('log-success', data.levels ? data.levels.success : 0);
      setText('log-error', data.levels ? data.levels.error : 0);
    }).catch(function () {
      toast('日志统计加载失败，请确认后端已启动', 'error');
    });
  }

  function loadLogs() {
    var level = $('level-filter') ? $('level-filter').value : '';
    var event = $('event-filter') ? $('event-filter').value : '';
    var params = new URLSearchParams({
      page: String(state.page),
      size: String(state.size),
      level: level,
      event: event
    });
    API.get('/api/logs?' + params.toString()).then(function (data) {
      state.pages = data.pages || 1;
      state.total = data.total || 0;
      renderLogs(data.items || []);
      setText('page-meta', '第 ' + state.page + ' / ' + state.pages + ' 页 · 共 ' + state.total + ' 条');
      var prev = $('prev-page');
      var next = $('next-page');
      if (prev) prev.disabled = state.page <= 1;
      if (next) next.disabled = state.page >= state.pages;
    }).catch(function (error) {
      var list = $('log-list');
      if (list) {
        list.innerHTML = '<div class="empty-state"><strong>读取失败</strong><span>' +
          escapeHtml(error.message) + '</span></div>';
      }
      toast('日志加载失败：' + error.message, 'error');
    });
  }

  function renderLogs(items) {
    var list = $('log-list');
    if (!list) return;
    if (!items.length) {
      list.innerHTML = '<div class="empty-state"><strong>暂无日志</strong><span>完成一次检测或举报后，这里会记录操作审计。</span></div>';
      return;
    }
    list.innerHTML = items.map(function (item) {
      var meta = '';
      try {
        meta = item.meta && Object.keys(item.meta).length ? JSON.stringify(item.meta) : '';
      } catch (error) {
        meta = '';
      }
      return '<div class="log-item" title="' + escapeHtml(meta) + '">' +
        '<span class="log-item__time">' + escapeHtml(API.formatTime(item.created_at)) + '</span>' +
        '<span class="log-level log-level--' + escapeHtml(item.level) + '">' + escapeHtml(item.level) + '</span>' +
        '<span class="log-item__message"><strong>' + escapeHtml(item.event) + '</strong> · ' + escapeHtml(item.message) + '</span>' +
        '<span class="log-item__duration">' + (item.duration_ms != null ? item.duration_ms + ' ms' : '') + '</span>' +
        '</div>';
    }).join('');
  }

  function bind() {
    var refresh = $('refresh-btn');
    if (refresh) {
      refresh.addEventListener('click', function () {
        loadStats();
        loadLogs();
        toast('日志已刷新', 'success');
      });
    }
    var level = $('level-filter');
    if (level) level.addEventListener('change', function () { state.page = 1; loadLogs(); });
    var event = $('event-filter');
    if (event) event.addEventListener('change', function () { state.page = 1; loadLogs(); });
    var prev = $('prev-page');
    if (prev) prev.addEventListener('click', function () {
      if (state.page > 1) { state.page -= 1; loadLogs(); }
    });
    var next = $('next-page');
    if (next) next.addEventListener('click', function () {
      if (state.page < state.pages) { state.page += 1; loadLogs(); }
    });

    var auto = $('auto-refresh');
    if (auto) {
      auto.addEventListener('change', function () {
        window.clearInterval(state.timer);
        if (auto.checked) {
          state.timer = window.setInterval(function () {
            loadStats();
            loadLogs();
          }, 10000);
        }
      });
    }
  }

  bind();
  loadStats();
  loadLogs();
})();
