/* ==========================================================================
   反诈卫士 · 历史记录页
   ========================================================================== */
(function () {
  'use strict';

  var API = window.AntiFraudAPI;
  var state = { page: 1, size: 12, pages: 1, total: 0, current: null };

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
  function sourceLabel(source) {
    return { text: '纯文本', image: '图片', audio: '语音', mixed: '多模态' }[source] || source || '—';
  }
  function levelBadge(level, label) {
    var meta = API.riskMeta(level);
    return '<span class="level-badge level-badge--' + meta.key + '">' +
      escapeHtml(label || meta.label) + '</span>';
  }
  function riskColor(level) {
    return API.riskMeta(level).color;
  }

  function loadStats() {
    API.get('/api/stats').then(function (data) {
      setText('stat-total', data.total);
      setText('stat-high', data.high_risk);
      setText('stat-pii', data.pii_exposed);
      setText('stat-reports', data.reports);
    }).catch(function () {
      toast('统计数据加载失败，请确认后端已启动', 'error');
    });
  }

  function loadHistory() {
    var keyword = $('keyword') ? $('keyword').value.trim() : '';
    var level = $('level-filter') ? $('level-filter').value : '';
    var source = $('source-filter') ? $('source-filter').value : '';
    var params = new URLSearchParams({
      page: String(state.page),
      size: String(state.size),
      keyword: keyword,
      level: level,
      source: source
    });
    API.get('/api/history?' + params.toString()).then(function (data) {
      state.pages = data.pages || 1;
      state.total = data.total || 0;
      renderRows(data.items || []);
      setText('page-meta', '第 ' + state.page + ' / ' + state.pages + ' 页 · 共 ' + state.total + ' 条');
      var prev = $('prev-page');
      var next = $('next-page');
      if (prev) prev.disabled = state.page <= 1;
      if (next) next.disabled = state.page >= state.pages;
    }).catch(function (error) {
      var body = $('history-body');
      if (body) {
        body.innerHTML = '<tr><td colspan="6" class="empty-state">' +
          '<strong>读取失败</strong><span>' + escapeHtml(error.message) + '</span></td></tr>';
      }
      toast('历史记录加载失败：' + error.message, 'error');
    });
  }

  function renderRows(items) {
    var body = $('history-body');
    if (!body) return;
    if (!items.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty-state">' +
        '<strong>暂无检测记录</strong><span>回到 AI 管家完成一次检测后，记录会自动保存在 SQL Server。</span></td></tr>';
      return;
    }
    body.innerHTML = items.map(function (item) {
      var summary = item.summary || '';
      var preview = item.input_preview || '';
      return '<tr>' +
        '<td>' + escapeHtml(API.formatTime(item.created_at)) + '</td>' +
        '<td><span class="score-text" style="color:' + riskColor(item.risk_level) + '">' + item.risk_score + '%</span><br>' +
        levelBadge(item.risk_level, item.risk_level === 'critical' ? '极高风险' : null) + '</td>' +
        '<td>' + escapeHtml(item.scam_type || '—') + '</td>' +
        '<td><div class="data-table__summary" title="' + escapeHtml(preview || summary) + '">' +
        escapeHtml(preview || summary || '—') + '</div></td>' +
        '<td>' + escapeHtml(sourceLabel(item.source)) + '</td>' +
        '<td><div class="data-table__actions">' +
        '<button class="link-btn" data-action="detail" data-id="' + item.id + '" type="button">详情</button>' +
        '<a class="link-btn" href="' + API.downloadUrl('/api/history/' + item.id + '/export') + '" target="_blank" rel="noopener">导出</a>' +
        '<button class="link-btn link-btn--danger" data-action="delete" data-id="' + item.id + '" type="button">删除</button>' +
        '</div></td>' +
        '</tr>';
    }).join('');
  }

  function openDetail(id) {
    API.get('/api/history/' + id).then(function (data) {
      state.current = data.analysis;
      renderDetail(data.analysis);
      $('detail-modal').classList.remove('is-hidden');
      var exportLink = $('detail-export');
      var reportLink = $('detail-report');
      if (exportLink) exportLink.href = API.downloadUrl('/api/history/' + id + '/export');
      if (reportLink) reportLink.href = API.downloadUrl('/api/history/' + id + '/report.txt');
    }).catch(function (error) {
      toast('详情加载失败：' + error.message, 'error');
    });
  }

  function renderDetail(analysis) {
    var rawType = analysis.scam_type || '';
    var typeParts = [];
    rawType.split(' + ').forEach(function (item) {
      var value = item.trim();
      if (value && typeParts.indexOf(value) === -1) typeParts.push(value);
    });
    setText('detail-title', typeParts.join(' + ') || '风险研判');
    var meta = API.riskMeta(analysis.risk_level);
    var dimensions = (analysis.dimensions || []).map(function (item) {
      var percent = item.max ? Math.round((item.score / item.max) * 100) : 0;
      var cls = percent >= 80 ? 'dimension--danger' : (percent >= 45 ? 'dimension--warn' : '');
      return '<li class="dimension ' + cls + '">' +
        '<span class="dimension__name">' + escapeHtml(item.name) + '</span>' +
        '<span class="dimension__bar"><i style="width:' + Math.min(100, percent) + '%"></i></span>' +
        '<span class="dimension__score">' + item.score + '/' + item.max + '</span>' +
        '</li>';
    }).join('');

    var signals = (analysis.signals || []).map(function (item) {
      return '<li class="evidence ' + (item.severity === 'critical' || item.severity === 'high' ? 'evidence--danger' : '') + '">' +
        '<div class="evidence__head"><span class="evidence__label">' + escapeHtml(item.label) + '</span>' +
        '<span class="evidence__weight">+' + item.weight + '</span></div>' +
        '<p class="evidence__text">' + escapeHtml(item.evidence || '') + '</p>' +
        '<p class="evidence__meta">' + escapeHtml(item.dim) + ' · 命中 ' + (item.count || 1) + ' 次</p>' +
        '</li>';
    }).join('') || '<li class="empty-inline">未命中明显风险特征</li>';

    var pii = (analysis.pii || []).map(function (item) {
      return '<li class="pii-item"><span class="pii-item__main">' +
        '<span class="pii-item__label">' + escapeHtml(item.label) + '</span>' +
        '<span class="pii-item__value">' + escapeHtml(item.value) + '</span></span>' +
        '<span class="pii-item__count">×' + (item.count || 1) + '</span></li>';
    }).join('');

    var suggestions = (analysis.suggestions || []).map(function (text) {
      return '<li>' + escapeHtml(text) + '</li>';
    }).join('') || '<li class="empty-inline">暂无建议</li>';

    var modalities = (analysis.modalities || []).map(function (item) {
      return '<li class="risk-media__item">' +
        '<span class="risk-media__preview">' + (item.type === 'image' ? '图' : '声') + '</span>' +
        '<span class="risk-media__info"><strong>' + escapeHtml(item.filename || item.type) + '</strong>' +
        '<small>' + escapeHtml(item.summary || '') + '</small></span>' +
        '<span class="risk-media__score">' + (item.score || 0) + '%</span></li>';
    }).join('');

    var reports = (analysis.reports || []).map(function (item) {
      return '<li class="pii-item"><span class="pii-item__main">' +
        '<span class="pii-item__label">' + escapeHtml(item.channel) + '</span>' +
        '<span class="pii-item__value">' + escapeHtml(item.report_no) + '</span></span>' +
        '<a class="link-btn" href="' + API.downloadUrl('/api/reports/' + item.id + '/download') + '" target="_blank" rel="noopener">下载</a></li>';
    }).join('');

    var cross = analysis.cross_image;
    var crossHtml = '';
    if (cross && cross.count >= 2) {
      crossHtml = '<section class="detail-section"><h3 class="detail-section__title">多图关联分析（' + cross.count + ' 张）</h3>' +
        '<p class="detail-text">' + escapeHtml(cross.summary || '') + '</p>' +
        ((cross.relationships || []).length
          ? '<ul class="cross-image-list">' + cross.relationships.map(function (item) {
              return '<li>' + escapeHtml(item) + '</li>';
            }).join('') + '</ul>'
          : '') +
        '</section>';
    }

    var images = (analysis.images || []).map(function (item) {
      var url = item.thumb_name ? API.downloadUrl('/thumbnails/' + item.thumb_name) : API.downloadUrl('/uploads/' + item.stored_name);
      return '<a class="tag tag--neutral" href="' + url + '" target="_blank" rel="noopener" style="text-decoration:none">' +
        escapeHtml(item.original_name) + ' · ' + (item.risk_score || 0) + '%</a>';
    }).join(' ');

    var body = $('detail-body');
    if (!body) return;
    body.innerHTML =
      '<div class="detail-grid">' +
      '<div class="detail-item"><div class="detail-item__label">风险评分</div><div class="detail-item__value" style="color:' + meta.color + '">' + analysis.risk_score + '% · ' + escapeHtml(meta.label) + '</div></div>' +
      '<div class="detail-item"><div class="detail-item__label">检测来源</div><div class="detail-item__value">' + escapeHtml(sourceLabel(analysis.source)) + '</div></div>' +
      '<div class="detail-item"><div class="detail-item__label">检测时间</div><div class="detail-item__value">' + escapeHtml(API.formatTime(analysis.created_at)) + '</div></div>' +
      '<div class="detail-item"><div class="detail-item__label">引擎</div><div class="detail-item__value">' + escapeHtml((analysis.engine && analysis.engine.name) || '规则引擎') + '</div></div>' +
      (analysis.match ? '<div class="detail-item"><div class="detail-item__label">库匹配</div><div class="detail-item__value">' +
        (analysis.match.hit
          ? '命中 #' + analysis.match.case_id + ' · ' + Math.round((analysis.match.similarity || 0) * 100) + '% · ' +
            (analysis.match.reviewed_by_ai ? 'AI 已复核' : 'AI 未复核')
          : '未命中' + (analysis.match.stored_as_case ? ' · 已收录' : '')) +
        '</div></div>' : '') +
      '</div>' +
      '<section class="detail-section"><h3 class="detail-section__title">结论摘要</h3><p class="detail-text">' + escapeHtml(analysis.summary || '') + '</p></section>' +
      '<section class="detail-section"><h3 class="detail-section__title">原始内容</h3><p class="detail-text">' + escapeHtml(analysis.input_text || '（无文本内容）') + '</p></section>' +
      (dimensions ? '<section class="detail-section"><h3 class="detail-section__title">评分维度</h3><ul class="dimension-list">' + dimensions + '</ul></section>' : '') +
      '<section class="detail-section"><h3 class="detail-section__title">风险证据</h3><ul class="evidence-list">' + signals + '</ul></section>' +
      (pii ? '<section class="detail-section"><h3 class="detail-section__title">个人信息暴露</h3><ul class="pii-list">' + pii + '</ul></section>' : '') +
      '<section class="detail-section"><h3 class="detail-section__title">处置建议</h3><ol class="suggestion-list">' + suggestions + '</ol></section>' +
      crossHtml +
      (modalities ? '<section class="detail-section"><h3 class="detail-section__title">多模态结果</h3><ul class="risk-media">' + modalities + '</ul></section>' : '') +
      (images ? '<section class="detail-section"><h3 class="detail-section__title">文件证据</h3><div>' + images + '</div></section>' : '') +
      (reports ? '<section class="detail-section"><h3 class="detail-section__title">举报材料</h3><ul class="pii-list">' + reports + '</ul></section>' : '') +
      (analysis.is_false_positive ? '<p class="privacy-alert"><strong>已标记误报</strong><span>' + escapeHtml(analysis.feedback_note || '') + '</span></p>' : '');
  }

  function deleteRecord(id) {
    if (!window.confirm('确定删除这条检测记录吗？关联的文件和举报材料也会一并删除。')) return;
    API.remove('/api/history/' + id).then(function () {
      toast('记录已删除', 'success');
      closeModal();
      loadHistory();
      loadStats();
    }).catch(function (error) {
      toast('删除失败：' + error.message, 'error');
    });
  }

  function closeModal() {
    var modal = $('detail-modal');
    if (modal) modal.classList.add('is-hidden');
  }

  function bind() {
    var search = $('search-btn');
    if (search) {
      search.addEventListener('click', function () {
        state.page = 1;
        loadHistory();
      });
    }
    var keyword = $('keyword');
    if (keyword) {
      keyword.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
          state.page = 1;
          loadHistory();
        }
      });
    }
    var level = $('level-filter');
    if (level) level.addEventListener('change', function () { state.page = 1; loadHistory(); });
    var source = $('source-filter');
    if (source) source.addEventListener('change', function () { state.page = 1; loadHistory(); });
    var reset = $('reset-btn');
    if (reset) {
      reset.addEventListener('click', function () {
        if (keyword) keyword.value = '';
        if (level) level.value = '';
        if (source) source.value = '';
        state.page = 1;
        loadHistory();
      });
    }
    var prev = $('prev-page');
    if (prev) prev.addEventListener('click', function () {
      if (state.page > 1) { state.page -= 1; loadHistory(); }
    });
    var next = $('next-page');
    if (next) next.addEventListener('click', function () {
      if (state.page < state.pages) { state.page += 1; loadHistory(); }
    });

    var body = $('history-body');
    if (body) {
      body.addEventListener('click', function (event) {
        var button = event.target.closest('button[data-action]');
        if (!button) return;
        var id = Number(button.getAttribute('data-id'));
        var action = button.getAttribute('data-action');
        if (action === 'detail') openDetail(id);
        if (action === 'delete') deleteRecord(id);
      });
    }

    document.querySelectorAll('[data-close]').forEach(function (element) {
      element.addEventListener('click', closeModal);
    });

    var feedback = $('detail-feedback');
    if (feedback) {
      feedback.addEventListener('click', function () {
        if (!state.current) return;
        API.postJson('/api/history/' + state.current.id + '/feedback', {
          is_false_positive: true,
          note: '历史记录页标记为误报'
        }).then(function () {
          toast('已标记为误报', 'success');
          openDetail(state.current.id);
        }).catch(function (error) {
          toast('标记失败：' + error.message, 'error');
        });
      });
    }

    var del = $('detail-delete');
    if (del) {
      del.addEventListener('click', function () {
        if (state.current) deleteRecord(state.current.id);
      });
    }
  }

  bind();
  loadStats();
  loadHistory();
})();
