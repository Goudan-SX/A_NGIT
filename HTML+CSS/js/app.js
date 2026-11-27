/* ==========================================================================
   反诈卫士 · 主页面交互
   负责：文本/图片/语音检测、结果渲染、举报材料、每日案例、反诈问答、知识宣传
   ========================================================================== */
(function () {
  'use strict';

  var API = window.AntiFraudAPI;

  var state = {
    analysis: null,
    analysisId: null,
    saved: false,
    files: [],
    fileSeq: 1,
    analyzing: false,
    analyzeSeq: 0,
    fullResultSeq: 0,
    autoTimer: null,
    pendingAuto: false,
    recorder: null,
    recordChunks: [],
    report: null
  };

  function $(id) {
    return document.getElementById(id);
  }

  function setText(el, value) {
    if (el) el.textContent = value == null ? '' : String(value);
  }

  function show(el) {
    if (el) el.classList.remove('is-hidden');
  }

  function hide(el) {
    if (el) el.classList.add('is-hidden');
  }

  function toast(message, type) {
    var el = $('toast');
    if (!el) return;
    el.textContent = message;
    el.className = 'toast' + (type ? ' toast--' + type : '');
    show(el);
    window.clearTimeout(toast._timer);
    toast._timer = window.setTimeout(function () {
      hide(el);
    }, 3600);
  }

  function riskMeta(level) {
    return API.riskMeta(level);
  }

  function cleanScamType(value) {
    var parts = String(value || '').split(' + ').map(function (item) {
      return item.trim();
    }).filter(Boolean);
    var unique = [];
    parts.forEach(function (item) {
      if (unique.indexOf(item) === -1) unique.push(item);
    });
    return unique.join(' + ');
  }

  function dimensionName(key) {
    var map = {
      script: '话术操控',
      financial: '资金诱导',
      info: '信息窃取',
      channel: '渠道异常',
      identity: '身份伪装'
    };
    return map[key] || key;
  }

  function countChat(text) {
    var lines = String(text || '').split('\n').filter(function (line) {
      return line.trim().length > 0;
    });
    var chars = String(text || '').replace(/\s/g, '').length;
    return { messages: lines.length, chars: chars };
  }

  function updateChatStats() {
    var input = $('chat-text');
    if (!input) return;
    var stats = countChat(input.value);
    setText($('chat-stats'), stats.messages + ' 条消息 · 约 ' + stats.chars + ' 字');
  }

  function setGuard(text, ok) {
    var el = $('guard-status');
    var label = $('guard-status-text');
    if (label) label.textContent = text;
    if (el) {
      el.style.color = ok ? '' : 'var(--amber-600)';
      el.style.backgroundColor = ok ? '' : 'var(--amber-50)';
      el.style.borderColor = ok ? '' : 'rgba(217, 119, 6, 0.18)';
    }
  }

  function engineLabel(result) {
    var engine = (result && result.engine) || {};
    if (engine.name === 'guardian-rule' || engine.name === 'guardian-rule-v1') return 'Guardian-AI · 规则';
    if (String(engine.name || '').indexOf('multi-image') !== -1) return 'Guardian-AI · 多图联合';
    if (String(engine.name || '').indexOf('database') !== -1) return 'Guardian-AI · 案例+AI';
    if (String(engine.name || '').indexOf('image-cache') !== -1) return 'Guardian-AI · 图片缓存';
    if (String(engine.name || '').indexOf('ocr') !== -1) return 'Guardian-AI · OCR';
    if (engine.provider === 'deepseek') return 'Guardian-AI · DeepSeek';
    if (engine.ai) return 'Guardian-AI · Qwen';
    if (engine.provider === 'database') return 'Guardian-AI · 数据库';
    return 'Guardian-AI';
  }

  function setEngine(text, note) {
    setText($('engine-chip-text'), text);
    var chip = $('engine-chip');
    if (chip) chip.title = note || text;
  }

  function setAnalyzing(active) {
    state.analyzing = active;
    var btn = $('analyze-btn');
    if (!btn) return;
    btn.disabled = active;
    btn.style.opacity = active ? '0.7' : '';
    if (active) {
      setEngine('分析中…', '正在调用检测服务');
    }
  }

  function setButtonEnabled(id, enabled) {
    var el = $(id);
    if (el) el.disabled = !enabled;
  }

  /* ------------------------------------------------------------------------
   * 一、检测与结果渲染
   * ---------------------------------------------------------------------- */
  function analyze(save, includeFiles) {
    if (state.analyzing && !save) {
      state.pendingAuto = true;
      return Promise.resolve(null);
    }
    var input = $('chat-text');
    var text = input ? input.value : '';
    var files = includeFiles ? state.files : [];
    var seq = ++state.analyzeSeq;
    var hasInput = text.trim().length > 0 || files.length > 0;
    if (!hasInput) {
      renderEmpty();
      return Promise.resolve(null);
    }

    // 文本先用本地规则/数据库快速出结果，DeepSeek 复核返回后再覆盖，提升感知速度。
    if (!save && !includeFiles && text.trim().length >= 2) {
      API.previewText(text).then(function (data) {
        if (seq !== state.analyzeSeq || state.fullResultSeq === seq) return;
        state.analysis = data.analysis;
        renderAnalysis(data.analysis);
        setEngine('Guardian-AI · 快速预判', '正在等待 DeepSeek V4.1 复核…');
      }).catch(function () {
        /* 快速预览失败不阻断正式分析 */
      });
    }

    setAnalyzing(true);
    setGuard('正在分析…', false);

    var promise;
    if (files.length > 0) {
      promise = API.analyzeMultimodal(text, files.map(function (item) {
        return { file: item.file };
      }), save);
    } else {
      promise = API.analyzeText(text, save);
    }

    return promise.then(function (data) {
      if (seq !== state.analyzeSeq) return null;
      var result = data.analysis;
      state.fullResultSeq = seq;
      state.analysis = result;
      state.analysisId = data.id || null;
      state.saved = Boolean(data.saved && data.id);
      if (result.modalities && result.modalities.length && files.length) {
        result.modalities.forEach(function (modality, index) {
          var item = files[index];
          if (!item) return;
          item.status = 'done';
          item.score = modality.score;
          item.summary = modality.summary;
          item.ocrText = modality.text || '';
          item.modalityType = modality.type;
        });
      }
      renderAnalysis(result);
      renderMedia();
      captureAnalyzedImages(result);
      setEngine(engineLabel(result),
        (result.engine && result.engine.note) || '本地规则引擎 + Qwen 适配');
      setGuard('防护已就绪', true);
      if (data.errors && data.errors.length) {
        toast(data.errors.join('；'), 'error');
      }
      return result;
    }).catch(function (error) {
      if (seq !== state.analyzeSeq) return null;
      setGuard('检测服务未连接', false);
      setEngine('离线演示', '请启动 backend/run.py 后刷新页面');
      toast('检测失败：' + error.message, 'error');
      renderFallback(text);
      return null;
    }).finally(function () {
      if (seq === state.analyzeSeq) {
        setAnalyzing(false);
        var auto = $('auto-analyze');
        if (state.pendingAuto && auto && auto.checked) {
          state.pendingAuto = false;
          scheduleAutoAnalyze();
        }
      }
    });
  }

  function renderAnalysis(result) {
    if (!result) {
      renderEmpty();
      return;
    }
    var level = riskMeta(result.risk_level);
    var score = Number(result.risk_score || 0);
    var ring = $('risk-ring');
    var scoreEl = $('risk-score');
    if (scoreEl) {
      scoreEl.innerHTML = score + '<span>%</span>';
      scoreEl.style.color = level.color;
    }
    if (ring) {
      ring.classList.remove('risk-ring--low', 'risk-ring--medium', 'risk-ring--high', 'risk-ring--critical');
      ring.classList.add('risk-ring--' + level.key);
      ring.style.setProperty('--score', score);
      ring.setAttribute('aria-label', '综合诈骗风险 ' + score + '%，' + (result.risk_label || level.label));
    }

    var levelEl = $('risk-level');
    if (levelEl) {
      levelEl.classList.remove('risk-summary__level--low', 'risk-summary__level--medium',
        'risk-summary__level--high', 'risk-summary__level--critical');
      levelEl.classList.add('risk-summary__level--' + level.key);
      levelEl.style.color = level.color;
    }
    setText($('risk-level-text'), (result.risk_label || level.label) + ' · ' + (result.risk_hint || ''));

    var scamType = cleanScamType(result.scam_type);
    var title = scamType && scamType.indexOf('暂无') === -1
      ? '疑似「' + scamType + '」诈骗'
      : '暂未识别到典型诈骗话术';
    setText($('risk-title'), title);
    setText($('risk-desc'), result.summary || '');
    renderMatch(result.match, result);
    renderCrossImage(result.cross_image);

    var dimensions = (result.guardian && result.guardian.components)
      ? result.guardian.components
      : (result.dimensions || []);
    renderDimensions(dimensions);
    var dimensionNote = $('dimension-note');
    if (dimensionNote) {
      var notes = [];
      if (result.guardian && result.guardian.modality_score) {
        notes.push('综合风险含图像视觉评分：' + result.guardian.modality_score + '%');
      }
      if (result.keyword_frequency >= 3 && result.keyword_frequency_boost) {
        notes.push('关键词重复 ' + result.keyword_frequency + ' 次，频率加成 +' + result.keyword_frequency_boost);
      }
      if (notes.length) {
        dimensionNote.textContent = notes.join(' · ');
        show(dimensionNote);
      } else {
        hide(dimensionNote);
      }
    }
    renderKeywords(result.matched_keywords || [], result.signals || []);
    renderEvidence(result.signals || []);
    renderContract(result);
    renderPii(result.pii || []);
    renderLinks(result.links || []);
    renderSuggestions(result.suggestions || []);
    renderRiskMedia();

    setButtonEnabled('report-btn', true);
    setButtonEnabled('export-btn', true);
    setButtonEnabled('copy-btn', true);
    setButtonEnabled('feedback-btn', true);

    var engine = result.engine || {};
    setEngine(engineLabel(result), engine.note || '');
  }


  function contractHits(result) {
    if (result && Array.isArray(result.hits)) return result.hits;
    return ((result && result.signals) || []).filter(function (item) {
      return String(item.source || 'rule') !== 'ai';
    });
  }

  function contractInferences(result) {
    if (result && Array.isArray(result.inferences)) return result.inferences;
    return ((result && result.signals) || []).filter(function (item) {
      return String(item.source || 'rule') === 'ai';
    });
  }

  function renderContract(result) {
    var raw = $('chat-text') ? $('chat-text').value : '';
    var hits = contractHits(result);
    var inferences = contractInferences(result);
    var filter = $('contract-filter') ? $('contract-filter').value : 'all';
    var hide = $('hide-markers') ? $('hide-markers').checked : false;
    var spans = [];
    if (!hide && filter !== 'ai') {
      hits.forEach(function (item, index) {
        if (typeof item.start === 'number' && item.end > item.start) {
          spans.push({ start: item.start, end: item.end, kind: 'rule', index: index, label: item.label || '' });
        }
      });
    }
    if (!hide && filter !== 'rule') {
      inferences.forEach(function (item, index) {
        if (typeof item.start === 'number' && item.end > item.start) {
          spans.push({ start: item.start, end: item.end, kind: 'ai', index: index, label: item.label || '' });
        }
      });
    }
    spans.sort(function (a, b) { return a.start - b.start || b.end - a.end; });
    var container = $('raw-text');
    if (container) {
      container.innerHTML = '';
      var cursor = 0;
      spans.forEach(function (span) {
        if (span.start < cursor || span.end > raw.length) return;
        container.appendChild(document.createTextNode(raw.slice(cursor, span.start)));
        var mark = document.createElement('mark');
        mark.className = span.kind === 'ai' ? 'inference-ai' : 'hit-rule';
        mark.textContent = raw.slice(span.start, span.end);
        mark.dataset.contractKind = span.kind;
        mark.dataset.contractIndex = String(span.index);
        mark.addEventListener('click', function () {
          var card = document.querySelector('.contract-item[data-contract-kind="' + span.kind + '"][data-contract-index="' + span.index + '"]');
          if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
        container.appendChild(mark);
        cursor = span.end;
      });
      container.appendChild(document.createTextNode(raw.slice(cursor)));
    }
    renderContractList(hits, 'hit-list', 'rule', filter);
    renderContractList(inferences, 'inference-list', 'ai', filter);
  }

  function renderContractList(items, id, kind, filter) {
    var list = $(id);
    if (!list) return;
    list.innerHTML = '';
    if (filter !== 'all' && filter !== kind) return;
    if (!items.length) {
      var empty = document.createElement('li');
      empty.className = 'empty-inline';
      empty.textContent = kind === 'ai' ? '暂无主观推断' : '暂无客观命中';
      list.appendChild(empty);
      return;
    }
    items.forEach(function (item, index) {
      var row = document.createElement('li');
      row.className = 'contract-item' + (kind === 'ai' ? ' contract-item--inference' : '');
      row.dataset.contractKind = kind;
      row.dataset.contractIndex = String(index);
      var title = document.createElement('strong');
      title.textContent = item.label || '风险特征';
      var detail = document.createElement('span');
      detail.textContent = item.evidence || '';
      row.appendChild(title);
      row.appendChild(detail);
      if (kind === 'ai') {
        var meta = document.createElement('small');
        meta.textContent = '推断，非事实' + (item.confidence ? ' · 置信度 ' + Math.round(item.confidence * 100) + '%' : '');
        row.appendChild(meta);
        if (item.confidence) {
          var bar = document.createElement('span');
          bar.className = 'confidence-bar';
          var fill = document.createElement('i');
          fill.style.width = Math.round(item.confidence * 100) + '%';
          bar.appendChild(fill);
          row.appendChild(bar);
        }
      }
      row.addEventListener('click', function () {
        var mark = document.querySelector('mark[data-contract-kind="' + kind + '"][data-contract-index="' + index + '"]');
        if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      list.appendChild(row);
    });
  }


  var lastMonitorId = '';

  function applyMonitorItem(item) {
    if (!item) return;
    var result = item.result || {};
    var score = Number(result.risk_score || 0);
    var text = $('monitor-sync-text');
    if (text) {
      text.textContent = (item.window || '前台窗口') + ' · ' + score + '% · ' + (item.updated_at || '');
    }
    var toggle = $('monitor-sync-toggle');
    if (!toggle || !toggle.checked) return;
    if (document.activeElement === $('chat-text')) return;
    if (item.id && item.id === lastMonitorId) return;
    lastMonitorId = item.id || '';
    var input = $('chat-text');
    if (input) {
      // 只展示可疑片段；无可疑时保留当前内容不清空
      if (item.text) {
        input.value = item.text;
        updateChatStats();
      }
    }
    // 托盘结果优先：让当前在途的手动分析失效，避免旧请求把 89% 覆盖成“—”。
    state.analyzeSeq += 1;
    state.monitorAt = Date.now();
    state.analysis = result;
    state.analysisId = null;
    state.saved = false;
    setAnalyzing(false);
    renderAnalysis(result);
    updateScienceByScore(Number(result.risk_score || 0), result.risk_label || '', (result.risk_types || []).join(','));
    setEngine('本地托盘', '来自桌面托盘的前台窗口监测');
    setGuard('托盘监测中', true);
  }

  function pollMonitor() {
    if (document.hidden) return;
    API.get('/api/monitor/latest').then(function (data) {
      if (data && data.item) applyMonitorItem(data.item);
    }).catch(function () { /* 托盘未启动或令牌失效时静默 */ });
  }

  function bindMonitorSync() {
    var toggle = $('monitor-sync-toggle');
    if (toggle) {
      toggle.addEventListener('change', function () {
        if (toggle.checked) {
          lastMonitorId = '';
          pollMonitor();
        }
      });
    }
    pollMonitor();
    setInterval(pollMonitor, 2500);
  }

  function bindContractControls() {
    var filter = $('contract-filter');
    var hide = $('hide-markers');
    if (filter) filter.addEventListener('change', function () { renderContract(state.analysis); });
    if (hide) hide.addEventListener('change', function () { renderContract(state.analysis); });
  }

  function renderEmpty() {
    state.analysis = null;
    renderContract(null);
    state.analysisId = null;
    state.saved = false;
    setText($('risk-score'), '0');
    var scoreEl = $('risk-score');
    if (scoreEl) scoreEl.innerHTML = '0<span>%</span>';
    var ring = $('risk-ring');
    if (ring) {
      ring.style.setProperty('--score', 0);
      ring.classList.remove('risk-ring--medium', 'risk-ring--high', 'risk-ring--critical');
      ring.classList.add('risk-ring--low');
    }
    setText($('risk-level-text'), '等待检测');
    setText($('risk-title'), '粘贴可疑内容后开始检测');
    setText($('risk-desc'), '系统会从话术操控、资金诱导、信息窃取、渠道异常、身份伪装五个维度给出可解释评分。');
    hide($('match-badge'));
    hide($('cross-image-section'));
    hide($('dimension-note'));
    setText($('keyword-count'), '0 项命中');
    setText($('evidence-count'), '0 条');
    setText($('image-count'), '0 项');
    setText($('suggestion-count'), '0 条');
    var list = $('keyword-list');
    if (list) list.innerHTML = '<li class="empty-inline">暂未命中高危词汇</li>';
    var evidence = $('evidence-list');
    if (evidence) evidence.innerHTML = '<li class="empty-inline">检测后在这里展示命中原文与风险权重</li>';
    var suggestions = $('suggestion-list');
    if (suggestions) suggestions.innerHTML = '<li class="empty-inline">检测后给出针对性处置建议</li>';
    renderDimensions([]);
    renderPii([]);
    renderLinks([]);
    hide($('pii-section'));
    hide($('link-section'));
    ['report-btn', 'export-btn', 'copy-btn', 'feedback-btn'].forEach(function (id) {
      setButtonEnabled(id, false);
    });
  }

  function renderFallback() {
    // 后端不可用时只展示明确错误态，不伪造分数、命中或证据。
    if (state.monitorAt && Date.now() - state.monitorAt < 10000 && state.analysis) return;
    state.analysis = null;
    state.analysisId = null;
    state.saved = false;
    setText($('risk-score'), '—');
    var scoreEl = $('risk-score');
    if (scoreEl) scoreEl.innerHTML = '—';
    var ring = $('risk-ring');
    if (ring) {
      ring.style.setProperty('--score', 0);
      ring.classList.remove('risk-ring--medium', 'risk-ring--high', 'risk-ring--critical');
      ring.classList.add('risk-ring--low');
    }
    setText($('risk-level-text'), '检测服务未连接');
    setText($('risk-title'), '暂时无法完成研判');
    setText($('risk-desc'), '请先启动本地后端服务，再重新检测。页面不会展示伪造分数或证据。');
    setText($('chat-stats'), '检测服务离线');
    hide($('match-badge'));
    renderContract(null);
    renderKeywords([], []);
    renderEvidence([]);
    renderPii([]);
    renderLinks([]);
    renderSuggestions(['启动 backend/run.py 或 run.bat 后重试。']);
    setEngine('离线', '本地服务未连接');
    setGuard('检测服务未连接', false);
  }

  function renderMatch(match, result) {
    var badge = $('match-badge');
    var label = $('match-badge-text');
    if (!badge || !label) return;
    if (!match || typeof match.hit !== 'boolean') {
      hide(badge);
      return;
    }
    badge.classList.remove('match-badge--hit', 'match-badge--ai');
    if (match.hit) {
      badge.classList.add('match-badge--hit');
      var similarity = Math.round((match.similarity || 0) * 100);
      var review = match.reviewed_by_ai
        ? (match.review_cached ? 'AI 已复核 · 缓存' : 'AI 已复核')
        : 'AI 复核不可用';
      label.textContent = '数据库命中 #' + match.case_id + ' · ' + (match.title || '历史案例') +
        ' · 相似度 ' + similarity + '% · ' + review;
    } else {
      badge.classList.add('match-badge--ai');
      var engine = (result && result.engine) || {};
      var engineName = engine.provider === 'deepseek' ? 'DeepSeek V4.1' :
        (engine.ai ? 'Qwen' : '本地规则');
      label.textContent = '数据库未命中 · ' + engineName + ' 分析' +
        (match.stored_as_case ? ' · 已收录为新案例' : '');
      if (match.nearest && match.nearest.similarity) {
        label.textContent += ' · 最相近案例 ' + Math.round(match.nearest.similarity * 100) + '%';
      }
    }
    show(badge);
  }

  function renderCrossImage(cross) {
    var section = $('cross-image-section');
    var summary = $('cross-image-summary');
    var list = $('cross-image-list');
    if (!section || !summary || !list) return;
    if (!cross || !cross.count || cross.count < 2) {
      hide(section);
      return;
    }
    show(section);
    setText($('cross-image-count'), cross.count + ' 张');
    var text = cross.summary || '已完成多图并行分析，正在比对图片之间的关联。';
    if (cross.error) text += '（多图联合分析暂不可用，已返回单图结果）';
    setText(summary, text);
    list.innerHTML = '';
    var relationships = cross.relationships || [];
    if (!relationships.length && cross.image_findings) {
      cross.image_findings.forEach(function (item) {
        var role = item && item.role ? item.role : '';
        if (role) relationships.push('图片 ' + (item.index || '') + '：' + role);
      });
    }
    relationships.forEach(function (item) {
      var li = document.createElement('li');
      li.textContent = typeof item === 'string' ? item : JSON.stringify(item);
      list.appendChild(li);
    });
    if (!relationships.length) {
      var li = document.createElement('li');
      li.textContent = cross.count + ' 张图片已同步分析，未发现明显的跨图矛盾或关联线索。';
      list.appendChild(li);
    }
  }

  function renderDimensions(items) {
    var list = $('dimension-list');
    if (!list) return;
    list.innerHTML = '';
    if (!items.length) {
      var li = document.createElement('li');
      li.className = 'dimension';
      li.innerHTML = '<span class="dimension__name">等待检测</span>' +
        '<span class="dimension__bar"><i style="width:0%"></i></span><span class="dimension__score">0</span>';
      list.appendChild(li);
      return;
    }
    items.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'dimension';
      var percent = item.max ? Math.round((item.score / item.max) * 100) : 0;
      if (percent >= 80) li.classList.add('dimension--danger');
      else if (percent >= 45) li.classList.add('dimension--warn');

      var name = document.createElement('span');
      name.className = 'dimension__name';
      name.textContent = item.name;
      name.title = item.desc || '';

      var bar = document.createElement('span');
      bar.className = 'dimension__bar';
      var fill = document.createElement('i');
      fill.style.width = Math.min(100, percent) + '%';
      bar.appendChild(fill);

      var score = document.createElement('span');
      score.className = 'dimension__score';
      score.textContent = item.score + '/' + item.max;
      score.title = item.desc || '';

      li.appendChild(name);
      li.appendChild(bar);
      li.appendChild(score);
      list.appendChild(li);
    });
  }

  function renderKeywords(keywords, signals) {
    var list = $('keyword-list');
    if (!list) return;
    list.innerHTML = '';
    var severity = {};
    signals.forEach(function (item) {
      if (item.label) severity[item.label] = item.severity || 'medium';
    });
    keywords.forEach(function (word) {
      var li = document.createElement('li');
      var level = severity[word];
      var cls = 'tag--danger';
      if (level === 'low') cls = 'tag--warn';
      if (level === 'medium') cls = 'tag--warn';
      li.className = 'tag ' + cls;
      li.textContent = word;
      list.appendChild(li);
    });
    if (!keywords.length) {
      list.innerHTML = '<li class="empty-inline">暂未命中高危词汇</li>';
    }
    setText($('keyword-count'), keywords.length + ' 项命中');
  }

  function renderEvidence(signals) {
    var list = $('evidence-list');
    if (!list) return;
    list.innerHTML = '';
    signals.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'evidence' + (item.severity === 'critical' || item.severity === 'high' ? ' evidence--danger' : '') +
        (item.protective ? ' evidence--protective' : '');

      var head = document.createElement('div');
      head.className = 'evidence__head';
      var label = document.createElement('span');
      label.className = 'evidence__label';
      label.textContent = item.label + (item.protective ? '（科普语境）' : '');
      var weight = document.createElement('span');
      weight.className = 'evidence__weight';
      weight.textContent = '+' + item.weight;
      head.appendChild(label);
      head.appendChild(weight);

      var text = document.createElement('p');
      text.className = 'evidence__text';
      text.textContent = item.evidence || '—';
      text.title = item.evidence || '';

      var meta = document.createElement('p');
      meta.className = 'evidence__meta';
      meta.textContent = dimensionName(item.dim) + ' · 命中 ' + (item.count || 1) + ' 次' +
        (item.source === 'qwen' ? ' · Qwen 语义识别' : '');

      li.appendChild(head);
      li.appendChild(text);
      li.appendChild(meta);
      list.appendChild(li);
    });
    if (!signals.length) {
      list.innerHTML = '<li class="empty-inline">未命中明显风险特征</li>';
    }
    setText($('evidence-count'), signals.length + ' 条');
  }

  function renderPii(items) {
    var section = $('pii-section');
    var list = $('pii-list');
    if (!section || !list) return;
    list.innerHTML = '';
    if (!items.length) {
      hide(section);
      setText($('pii-count'), '0 处');
      return;
    }
    show(section);
    var total = 0;
    items.forEach(function (item) {
      total += item.count || 1;
      var li = document.createElement('li');
      li.className = 'pii-item';
      var main = document.createElement('span');
      main.className = 'pii-item__main';
      var label = document.createElement('span');
      label.className = 'pii-item__label';
      label.textContent = item.label;
      var value = document.createElement('span');
      value.className = 'pii-item__value';
      value.textContent = item.value;
      main.appendChild(label);
      main.appendChild(value);
      var count = document.createElement('span');
      count.className = 'pii-item__count';
      count.textContent = '×' + (item.count || 1);
      li.appendChild(main);
      li.appendChild(count);
      li.title = item.advice || '';
      list.appendChild(li);
    });
    setText($('pii-count'), total + ' 处');
  }

  function renderLinks(items) {
    var section = $('link-section');
    var list = $('link-list');
    if (!section || !list) return;
    list.innerHTML = '';
    if (!items.length) {
      hide(section);
      setText($('link-count'), '0 条');
      return;
    }
    show(section);
    items.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'link-item';
      var url = document.createElement('span');
      url.className = 'link-item__url';
      url.textContent = item.url;
      url.title = item.url;
      var reason = document.createElement('p');
      reason.className = 'link-item__reasons';
      reason.textContent = '风险 ' + item.risk + '% · ' + (item.reasons || []).join('；');
      li.appendChild(url);
      li.appendChild(reason);
      list.appendChild(li);
    });
    setText($('link-count'), items.length + ' 条');
  }

  function renderSuggestions(items) {
    var list = $('suggestion-list');
    if (!list) return;
    list.innerHTML = '';
    items.forEach(function (text) {
      var li = document.createElement('li');
      li.textContent = text;
      list.appendChild(li);
    });
    if (!items.length) {
      list.innerHTML = '<li class="empty-inline">暂无处置建议</li>';
    }
    setText($('suggestion-count'), items.length + ' 条');
  }

  function renderRiskMedia() {
    var list = $('risk-media');
    if (!list) return;
    list.innerHTML = '';
    var items = state.files.filter(function (item) {
      return item.status === 'done' && typeof item.score === 'number';
    });
    items.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'risk-media__item';

      var preview = document.createElement('span');
      preview.className = 'risk-media__preview ' + (item.kind === 'image'
        ? 'risk-media__preview--image' : 'risk-media__preview--audio');
      if (item.kind === 'image') {
        preview.style.backgroundImage = 'url(' + item.url + ')';
        preview.style.backgroundSize = 'cover';
        preview.style.backgroundPosition = 'center';
        preview.style.cursor = 'zoom-in';
        preview.title = '点击放大查看';
        preview.addEventListener('click', function () {
          openImageModal(item.url, item.name);
        });
      } else {
        preview.textContent = '声';
      }

      var info = document.createElement('span');
      info.className = 'risk-media__info';
      var name = document.createElement('strong');
      name.textContent = item.name;
      var desc = document.createElement('small');
      desc.textContent = item.summary || (item.ocrText ? item.ocrText.slice(0, 60) : '多模态检测完成');
      info.appendChild(name);
      info.appendChild(desc);

      var score = document.createElement('span');
      score.className = 'risk-media__score';
      score.textContent = item.score + '%';

      li.appendChild(preview);
      li.appendChild(info);
      li.appendChild(score);
      list.appendChild(li);
    });
    if (!items.length) {
      list.innerHTML = '<li class="empty-inline">上传文件后展示多模态研判结果</li>';
    }
    setText($('image-count'), items.length + ' 项');
  }

  /* ------------------------------------------------------------------------
   * 二、文本交互
   * ---------------------------------------------------------------------- */
  function scheduleAutoAnalyze() {
    updateChatStats();
    var auto = $('auto-analyze');
    if (!auto || !auto.checked) return;
    window.clearTimeout(state.autoTimer);
    state.autoTimer = window.setTimeout(function () {
      var input = $('chat-text');
      if (input && input.value.trim().length >= 2) {
        analyze(false, false);
      } else if (!state.files.length) {
        renderEmpty();
      }
    }, 1200);
  }

  function bindTextEvents() {
    var input = $('chat-text');
    if (input) {
      input.addEventListener('input', scheduleAutoAnalyze);
    }

    var analyzeBtn = $('analyze-btn');
    if (analyzeBtn) {
      analyzeBtn.addEventListener('click', function () {
        analyze(true, true);
      });
    }

    var clearBtn = $('clear-btn');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        if (input) input.value = '';
        state.files.forEach(function (item) { URL.revokeObjectURL(item.url); });
        state.files = [];
        renderMedia();
        updateChatStats();
        renderEmpty();
        setEngine('规则引擎 v1', '');
      });
    }

    var demoBtn = $('demo-btn');
    if (demoBtn) {
      demoBtn.addEventListener('click', function () {
        if (input) {
          input.value = '[11:42] 陌生好友：亲，动动手指日赚 300，刷单返利，先垫付后返还。\n' +
            '[11:43] 陌生好友：你的账户被冻结了，把验证码发给我就能解冻。\n' +
            '[11:44] 陌生好友：下载会议 App 并开启屏幕共享，我远程指导你操作。';
          updateChatStats();
          analyze(false, true);
        }
      });
    }

    var maskBtn = $('mask-btn');
    if (maskBtn) {
      maskBtn.addEventListener('click', applyMask);
    }

    var auto = $('auto-analyze');
    if (auto) {
      auto.addEventListener('change', function () {
        if (auto.checked) scheduleAutoAnalyze();
      });
    }
    updateChatStats();
  }

  function applyMask() {
    var input = $('chat-text');
    var analysis = state.analysis;
    if (!input || !analysis || !analysis.pii || !analysis.pii.length) {
      toast('当前没有检测到需要脱敏的信息', 'error');
      return;
    }
    var text = input.value;
    var replacements = [];
    analysis.pii.forEach(function (item) {
      if (item.source === 'media') return;
      (item.positions || []).forEach(function (pos) {
        if (pos.start >= 0 && pos.end <= text.length && pos.end > pos.start) {
          replacements.push({ start: pos.start, end: pos.end, label: item.label });
        }
      });
    });
    if (!replacements.length) {
      toast('敏感信息可能来自图片或语音，请在原文中手动删除', 'error');
      return;
    }
    replacements.sort(function (a, b) { return b.start - a.start; });
    replacements.forEach(function (item) {
      text = text.slice(0, item.start) + '[' + item.label + '已隐藏]' + text.slice(item.end);
    });
    input.value = text;
    updateChatStats();
    toast('已替换 ' + replacements.length + ' 处敏感信息', 'success');
    analyze(false, true);
  }

  /* ------------------------------------------------------------------------
   * 三、文件上传 / 录音
   * ---------------------------------------------------------------------- */
  function renderMedia() {
    var grid = $('media-grid');
    if (!grid) return;
    grid.innerHTML = '';
    state.files.forEach(function (item) {
      var figure = document.createElement('figure');
      figure.className = 'media-card';

      var preview = document.createElement('div');
      preview.className = 'media-card__preview media-card__preview--' + item.kind;
      if (item.kind === 'image') {
        preview.style.backgroundImage = 'url(' + item.url + ')';
        preview.style.backgroundSize = 'cover';
        preview.style.backgroundPosition = 'center';
      } else {
        var icon = document.createElement('strong');
        icon.textContent = '🎙';
        var hint = document.createElement('small');
        hint.textContent = (item.file.type.indexOf('audio') !== -1 ? '语音文件' : '音频');
        preview.appendChild(icon);
        preview.appendChild(hint);
      }

      var status = document.createElement('span');
      status.className = 'media-card__status';
      if (item.status === 'analyzing') {
        status.classList.add('media-card__status--analyzing');
        status.textContent = '分析中';
      } else if (item.status === 'done') {
        status.classList.add('media-card__status--done');
        status.textContent = '已检测';
      } else if (item.status === 'error') {
        status.classList.add('media-card__status--error');
        status.textContent = '失败';
      } else {
        status.textContent = '待检测';
      }

      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'media-card__remove';
      remove.setAttribute('aria-label', '移除文件');
      remove.textContent = '×';
      remove.addEventListener('click', function (event) {
        event.stopPropagation();
        removeFile(item.id);
      });

      var caption = document.createElement('figcaption');
      caption.className = 'media-card__caption';
      var name = document.createElement('span');
      name.className = 'media-card__name';
      name.textContent = item.name;
      name.title = item.name;
      var tag = document.createElement('span');
      var level = typeof item.score === 'number' ? (item.score >= 50 ? 'danger' : 'neutral') : 'neutral';
      tag.className = 'tag tag--' + level;
      tag.textContent = typeof item.score === 'number' ? item.score + '%' : '待检测';
      caption.appendChild(name);
      caption.appendChild(tag);

      if (item.kind === 'image') {
        preview.style.cursor = 'zoom-in';
        preview.title = '点击放大查看';
        preview.addEventListener('click', function () {
          openImageModal(item.url, item.name);
        });
      }
      preview.appendChild(status);
      preview.appendChild(remove);
      figure.appendChild(preview);
      figure.appendChild(caption);
      grid.appendChild(figure);
    });
  }

  function addFiles(fileList) {
    var accepted = [];
    Array.prototype.forEach.call(fileList || [], function (file) {
      var isImage = file.type.indexOf('image/') === 0 || /\.(png|jpe?g|webp|gif|bmp)$/i.test(file.name);
      var isAudio = file.type.indexOf('audio/') === 0 || /\.(mp3|wav|m4a|aac|ogg|webm|flac|amr)$/i.test(file.name);
      if (!isImage && !isAudio) {
        toast('仅支持图片或语音文件：' + file.name, 'error');
        return;
      }
      var limit = isImage ? 10 * 1024 * 1024 : 25 * 1024 * 1024;
      if (file.size > limit) {
        toast((isImage ? '图片' : '语音') + '不能超过 ' + (isImage ? '10' : '25') + ' MB', 'error');
        return;
      }
      var item = {
        id: state.fileSeq++,
        file: file,
        url: URL.createObjectURL(file),
        kind: isImage ? 'image' : 'audio',
        name: file.name,
        status: 'analyzing',
        score: null,
        summary: ''
      };
      state.files.push(item);
      accepted.push(item);
    });
    if (!accepted.length) return;
    renderMedia();
    toast(accepted.length > 1
      ? '已加入 ' + accepted.length + ' 个文件，正在同步分析并做多图关联'
      : '已加入 ' + accepted.length + ' 个文件，开始多模态检测', 'success');
    analyze(false, true);
  }

  function removeFile(id) {
    var item = state.files.find(function (entry) { return entry.id === id; });
    if (!item) return;
    URL.revokeObjectURL(item.url);
    state.files = state.files.filter(function (entry) { return entry.id !== id; });
    renderMedia();
    renderRiskMedia();
    if (state.files.length) {
      analyze(false, true);
    } else {
      analyze(false, false);
    }
  }


  /* ------------------------------------------------------------------------
   * 图片采集：分析完成后暂存、删除、清空
   * ---------------------------------------------------------------------- */
  var IMAGE_CAPTURE_KEY = 'guardian_image_captures_v1';
  var PENDING_CHAT_IMAGE_KEY = 'guardian_pending_chat_image';
  var incomingMediaIds = {};

  function loadImageCaptures() {
    try {
      return JSON.parse(localStorage.getItem(IMAGE_CAPTURE_KEY) || '[]');
    } catch (error) {
      return [];
    }
  }

  function saveImageCaptures(items) {
    var list = items.slice(0, 24);
    if (!list.length) {
      localStorage.removeItem(IMAGE_CAPTURE_KEY);
      return true;
    }
    while (list.length) {
      try {
        localStorage.setItem(IMAGE_CAPTURE_KEY, JSON.stringify(list));
        return true;
      } catch (error) {
        if (list.length === 1) {
          list[0].thumbnail = '';
          try {
            localStorage.setItem(IMAGE_CAPTURE_KEY, JSON.stringify(list));
            return true;
          } catch (inner) {
            return false;
          }
        }
        list.pop();
      }
    }
    return false;
  }

  function makeThumbnail(url) {
    return new Promise(function (resolve) {
      var image = new Image();
      image.onload = function () {
        try {
          var maxWidth = 360;
          var scale = Math.min(1, maxWidth / image.width);
          var canvas = document.createElement('canvas');
          canvas.width = Math.max(1, Math.round(image.width * scale));
          canvas.height = Math.max(1, Math.round(image.height * scale));
          canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
          resolve(canvas.toDataURL('image/jpeg', 0.72));
        } catch (error) {
          resolve('');
        }
      };
      image.onerror = function () { resolve(''); };
      image.src = url;
    });
  }

  function captureAnalyzedImages(result) {
    var images = state.files.filter(function (item) {
      return item.kind === 'image' && item.status === 'done';
    });
    if (!images.length) return;
    var captures = loadImageCaptures();
    images.forEach(function (item) {
      var captureId = item.captureId || ('cap-' + Date.now() + '-' + item.id);
      item.captureId = captureId;
      var existing = captures.find(function (entry) { return entry.id === captureId; });
      var record = existing || {
        id: captureId,
        name: item.name,
        time: new Date().toLocaleString('zh-CN', { hour12: false }),
        thumbnail: ''
      };
      record.score = typeof item.score === 'number' ? Math.round(item.score) : (result.risk_score || 0);
      record.level = record.score >= 90 ? 'critical' : record.score >= 50 ? 'high' : record.score >= 20 ? 'medium' : 'low';
      record.label = API.riskMeta(record.level).label;
      record.summary = item.summary || result.summary || '';
      record.ocrText = item.ocrText || '';
      record.scamType = result.scam_type || '';
      record.source = item.source || 'upload';
      record.components = result.guardian && result.guardian.components ? result.guardian.components : [];
      if (!existing) captures.unshift(record);
      if (!record.thumbnail) {
        makeThumbnail(item.url).then(function (thumb) {
          record.thumbnail = thumb;
          saveImageCaptures(captures);
          renderImageCaptures();
        });
      }
    });
    saveImageCaptures(captures);
    renderImageCaptures();
  }

  function renderImageCaptures() {
    var grid = $('image-capture-grid');
    if (!grid) return;
    var items = loadImageCaptures();
    var empty = $('image-capture-empty');
    grid.innerHTML = '';
    if (!items.length) {
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    items.forEach(function (item) {
      var card = document.createElement('article');
      card.className = 'image-capture-card';

      var thumb = document.createElement('div');
      thumb.className = 'image-capture-card__thumb';
      if (item.thumbnail) {
        thumb.style.backgroundImage = 'url(' + item.thumbnail + ')';
        thumb.title = '点击放大';
        thumb.addEventListener('click', function () {
          openImageModal(item.thumbnail, item.name || '采集图片');
        });
      }

      var body = document.createElement('div');
      body.className = 'image-capture-card__body';

      var head = document.createElement('div');
      head.className = 'image-capture-card__head';
      var name = document.createElement('span');
      name.className = 'image-capture-card__name';
      name.textContent = item.name || '聊天图片';
      var score = document.createElement('span');
      score.className = 'tag ' + (item.score >= 50 ? 'tag--danger' : 'tag--neutral');
      score.textContent = (item.score || 0) + '%';
      head.appendChild(name);
      head.appendChild(score);

      var time = document.createElement('span');
      time.className = 'image-capture-card__time';
      time.textContent = item.time || '';

      var summary = document.createElement('p');
      summary.className = 'image-capture-card__summary';
      summary.textContent = item.summary || '暂无摘要';

      var footer = document.createElement('div');
      footer.className = 'image-capture-card__footer';
      var level = document.createElement('span');
      level.className = 'tag ' + (item.level === 'high' || item.level === 'critical' ? 'tag--danger' : 'tag--neutral');
      level.textContent = item.label || '风险';
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'image-capture-card__delete';
      remove.textContent = '删除';
      remove.addEventListener('click', function () {
        deleteImageCapture(item.id);
      });
      footer.appendChild(level);
      footer.appendChild(remove);

      body.appendChild(head);
      body.appendChild(time);
      body.appendChild(summary);
      body.appendChild(footer);
      card.appendChild(thumb);
      card.appendChild(body);
      grid.appendChild(card);
    });
  }

  function deleteImageCapture(id) {
    var items = loadImageCaptures().filter(function (item) { return item.id !== id; });
    saveImageCaptures(items);
    renderImageCaptures();
    toast('已删除该图片采集', 'success');
  }

  function clearImageCaptures() {
    if (!loadImageCaptures().length) return;
    if (!window.confirm('确定清空所有图片采集吗？')) return;
    localStorage.removeItem(IMAGE_CAPTURE_KEY);
    renderImageCaptures();
    toast('已清空图片采集', 'success');
  }

  function dataUrlToFile(dataUrl, name) {
    var parts = String(dataUrl).split(',');
    var mime = (parts[0].match(/data:([^;]+)/) || [])[1] || 'image/png';
    var binary = atob(parts[1] || '');
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new File([bytes], name || 'chat-image.png', { type: mime });
  }

  function handleIncomingChatImage(payload) {
    if (!payload || payload.type !== 'chat-image' || !payload.dataUrl) return;
    var id = payload.id || payload.timestamp || String(Date.now());
    if (incomingMediaIds[id]) return;
    incomingMediaIds[id] = true;
    try {
      var file = dataUrlToFile(payload.dataUrl, payload.name || '聊天图片.png');
      addFiles([file]);
      localStorage.removeItem(PENDING_CHAT_IMAGE_KEY);
      toast('已接收聊天图片，正在主页面分析', 'success');
    } catch (error) {
      toast('聊天图片接收失败：' + error.message, 'error');
    }
  }

  function initIncomingMedia() {
    localStorage.setItem('guardian_main_alive', String(Date.now()));
    setInterval(function () {
      localStorage.setItem('guardian_main_alive', String(Date.now()));
    }, 2500);

    try {
      var pending = JSON.parse(localStorage.getItem(PENDING_CHAT_IMAGE_KEY) || 'null');
      if (pending) handleIncomingChatImage(pending);
    } catch (error) {
      localStorage.removeItem(PENDING_CHAT_IMAGE_KEY);
    }

    window.addEventListener('storage', function (event) {
      if (event.key !== PENDING_CHAT_IMAGE_KEY || !event.newValue) return;
      try {
        handleIncomingChatImage(JSON.parse(event.newValue));
      } catch (error) {
        /* ignore malformed payload */
      }
    });

    if ('BroadcastChannel' in window) {
      var channel = new BroadcastChannel('guardian-ai-media');
      channel.onmessage = function (event) {
        handleIncomingChatImage(event.data);
      };
    }
  }

  function bindUploader() {
    var uploader = $('uploader');
    var fileInput = $('file-input');
    if (!uploader || !fileInput) return;

    uploader.addEventListener('click', function () {
      fileInput.click();
    });
    uploader.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        fileInput.click();
      }
    });
    fileInput.addEventListener('click', function (event) {
      event.stopPropagation();
    });
    fileInput.addEventListener('change', function () {
      addFiles(fileInput.files);
      fileInput.value = '';
    });
    uploader.addEventListener('dragover', function (event) {
      event.preventDefault();
      uploader.classList.add('is-dragover');
    });
    uploader.addEventListener('dragleave', function () {
      uploader.classList.remove('is-dragover');
    });
    uploader.addEventListener('drop', function (event) {
      event.preventDefault();
      uploader.classList.remove('is-dragover');
      addFiles(event.dataTransfer.files);
    });
    document.addEventListener('paste', function (event) {
      var items = event.clipboardData && event.clipboardData.items;
      if (!items) return;
      var files = [];
      Array.prototype.forEach.call(items, function (item) {
        if (item.type.indexOf('image/') === 0) {
          var file = item.getAsFile();
          if (file) files.push(file);
        }
      });
      if (files.length) {
        event.preventDefault();
        addFiles(files);
      }
    });
  }

  function bindRecorder() {
    var button = $('record-btn');
    var tip = $('record-tip');
    var row = button ? button.parentNode : null;
    if (!button) return;
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      button.disabled = true;
      setText(tip, '当前浏览器不支持录音，请直接上传语音文件');
      return;
    }

    button.addEventListener('click', function () {
      if (state.recorder && state.recorder.state === 'recording') {
        state.recorder.stop();
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        var recorder = new MediaRecorder(stream);
        state.recorder = recorder;
        state.recordChunks = [];
        recorder.addEventListener('dataavailable', function (event) {
          if (event.data && event.data.size > 0) state.recordChunks.push(event.data);
        });
        recorder.addEventListener('stop', function () {
          stream.getTracks().forEach(function (track) { track.stop(); });
          var blob = new Blob(state.recordChunks, { type: recorder.mimeType || 'audio/webm' });
          var stamp = new Date().toISOString().replace(/[:.]/g, '-');
          var file = new File([blob], '录音-' + stamp + '.webm', { type: blob.type });
          state.recorder = null;
          if (row) row.classList.remove('is-recording');
          button.textContent = '浏览器录音检测';
          setText(tip, '录音完成，已加入待检测文件');
          addFiles([file]);
        });
        recorder.start();
        if (row) row.classList.add('is-recording');
        button.textContent = '停止录音';
        setText(tip, '正在录音，请描述你遇到的可疑情况…');
      }).catch(function (error) {
        toast('无法访问麦克风：' + error.message, 'error');
      });
    });
  }

  /* ------------------------------------------------------------------------
   * 四、举报 / 导出 / 反馈
   * ---------------------------------------------------------------------- */
  function ensureSaved() {
    if (state.analysisId && state.saved) {
      return Promise.resolve(state.analysisId);
    }
    return analyze(true, true).then(function () {
      return state.analysisId;
    });
  }

  function openModal(id) {
    var modal = $(id);
    if (modal) modal.classList.remove('is-hidden');
  }

  function openImageModal(url, name) {
    var image = $('image-modal-img');
    var title = $('image-modal-title');
    if (!image) return;
    image.src = url || '';
    image.alt = name || '上传图片放大预览';
    if (title) title.textContent = name || '上传图片';
    openModal('image-modal');
  }

  function closeModal(id) {
    var modal = $(id);
    if (modal) modal.classList.add('is-hidden');
  }

  function bindModals() {
    document.querySelectorAll('[data-close]').forEach(function (element) {
      element.addEventListener('click', function () {
        closeModal(element.getAttribute('data-close'));
      });
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        document.querySelectorAll('.modal').forEach(function (modal) {
          modal.classList.add('is-hidden');
        });
      }
    });
  }

  function bindActions() {
    var reportBtn = $('report-btn');
    if (reportBtn) {
      reportBtn.addEventListener('click', function () {
        state.report = null;
        hide($('report-result'));
        openModal('report-modal');
      });
    }

    var submit = $('submit-report-btn');
    if (submit) {
      submit.addEventListener('click', function () {
        submit.disabled = true;
        ensureSaved().then(function (id) {
          if (!id) throw new Error('请先完成一次检测');
          var channel = $('report-channel') ? $('report-channel').value : '12321';
          var note = $('report-note') ? $('report-note').value.trim() : '';
          return API.postJson('/api/reports', {
            analysis_id: id,
            channel: channel,
            note: note
          });
        }).then(function (data) {
          state.report = data.report;
          setText($('report-result-meta'), data.report.report_no + ' · ' + data.report.channel);
          setText($('report-result-content'), data.report.content);
          var download = $('download-report-btn');
          if (download) download.href = API.downloadUrl(data.download_url);
          show($('report-result'));
          toast('举报材料已生成，可复制或下载', 'success');
        }).catch(function (error) {
          toast(error.message, 'error');
        }).finally(function () {
          submit.disabled = false;
        });
      });
    }

    var copyReport = $('copy-report-btn');
    if (copyReport) {
      copyReport.addEventListener('click', function () {
        if (!state.report) return;
        copyText(state.report.content, '举报材料已复制');
      });
    }

    var exportBtn = $('export-btn');
    if (exportBtn) {
      exportBtn.addEventListener('click', function () {
        ensureSaved().then(function (id) {
          if (!id) throw new Error('请先完成一次检测');
          window.open(API.downloadUrl('/api/history/' + id + '/export'), '_blank');
        }).catch(function (error) {
          toast(error.message, 'error');
        });
      });
    }

    var copyBtn = $('copy-btn');
    if (copyBtn) {
      copyBtn.addEventListener('click', function () {
        var analysis = state.analysis;
        if (!analysis) return;
        var text = '反诈卫士检测结论\n风险：' + analysis.risk_label + ' ' + analysis.risk_score + '%\n' +
          '类型：' + analysis.scam_type + '\n结论：' + analysis.summary + '\n建议：\n' +
          (analysis.suggestions || []).map(function (item, index) {
            return (index + 1) + '. ' + item;
          }).join('\n');
        copyText(text, '结论已复制');
      });
    }

    var feedbackBtn = $('feedback-btn');
    if (feedbackBtn) {
      feedbackBtn.addEventListener('click', function () {
        ensureSaved().then(function (id) {
          if (!id) throw new Error('请先完成一次检测');
          return API.postJson('/api/history/' + id + '/feedback', {
            is_false_positive: true,
            note: '用户在前端标记为误报'
          });
        }).then(function () {
          toast('已标记为误报，感谢反馈', 'success');
        }).catch(function (error) {
          toast(error.message, 'error');
        });
      });
    }
  }

  function copyText(text, successMessage) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () {
        toast(successMessage, 'success');
      }).catch(function () {
        fallbackCopy(text, successMessage);
      });
    } else {
      fallbackCopy(text, successMessage);
    }
  }

  function fallbackCopy(text, successMessage) {
    var area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand('copy');
      toast(successMessage, 'success');
    } catch (error) {
      toast('复制失败，请手动选择文本', 'error');
    }
    document.body.removeChild(area);
  }

  /* ------------------------------------------------------------------------
   * 五、知识宣传
   * ---------------------------------------------------------------------- */
  var FALLBACK_KNOWLEDGE = [
    {
      category: '刷单返利',
      title: '所有“先垫付后返利”都是诈骗',
      content: '刷单返利诈骗通常以“动动手指日赚几百”开场，先用小额返利建立信任，再以“连单任务”“操作失误”“账户冻结”为由要求持续垫付。正规兼职不会要求你先垫钱。',
      tags: '刷单,返利,垫付,兼职'
    },
    {
      category: '冒充客服',
      title: '退款理赔不会让你开屏幕共享',
      content: '冒充电商或物流客服，以“订单异常、商品质量问题、理赔退款”为由，诱导你下载会议软件并开启屏幕共享，进而窥屏获取验证码、银行卡密码。真正的客服不会要求屏幕共享。',
      tags: '客服,退款,屏幕共享,验证码'
    },
    {
      category: '信息保护',
      title: '验证码是你的最后一道门',
      content: '短信验证码等于账户钥匙。任何人以任何理由索要验证码，都应立即拒绝。不要向陌生人发送身份证、银行卡正反面照片，不要开启屏幕共享。',
      tags: '验证码,身份证,银行卡,密码'
    },
    {
      category: '冒充公检法',
      title: '公检法不会电话办案，更没有“安全账户”',
      content: '骗子冒充公安、检察院、法院，以“涉嫌洗钱、护照异常、涉案账户”制造恐惧，要求你保密、单独沟通，并把钱转入所谓“安全账户”。公检法绝不会通过电话、社交软件办案。',
      tags: '公检法,安全账户,洗钱,恐吓'
    },
    {
      category: '虚假投资',
      title: '稳赚不赔的投资，只存在于骗局里',
      content: '虚假投资理财通过“导师带单、内部渠道、稳赚不赔”吸引你进入伪造平台，先让你小赚提现，再诱导加大投入。平台数据可随意修改，一旦大额入金便无法提现。',
      tags: '投资,理财,导师,提现'
    },
    {
      category: '网络贷款',
      title: '放款前先收费的，一定是诈骗',
      content: '正规贷款不会在放款前收取保证金、解冻费、工本费、认证费。凡是要求先转账“刷流水”“包装征信”的，都是诈骗。征信无法通过转账修复。',
      tags: '贷款,征信,保证金,校园贷'
    }
  ];

  var knowledgeItems = FALLBACK_KNOWLEDGE;

  function renderKnowledge(items) {
    var grid = $('knowledge-grid');
    if (!grid) return;
    grid.innerHTML = '';
    items.forEach(function (card, index) {
      var article = document.createElement('article');
      article.className = 'know-card';
      article.tabIndex = 0;
      article.setAttribute('role', 'button');

      var number = document.createElement('span');
      number.className = 'know-card__index';
      number.textContent = String(index + 1).padStart(2, '0');

      var title = document.createElement('h3');
      title.className = 'know-card__title';
      title.textContent = card.title;

      var group = document.createElement('p');
      group.className = 'know-card__group';
      group.textContent = card.category;

      var text = document.createElement('p');
      text.className = 'know-card__text';
      text.textContent = card.content;

      var tip = document.createElement('p');
      tip.className = 'know-card__tip';
      var strong = document.createElement('strong');
      strong.textContent = '关键词：';
      tip.appendChild(strong);
      tip.appendChild(document.createTextNode(card.tags || ''));

      article.appendChild(number);
      article.appendChild(title);
      article.appendChild(group);
      article.appendChild(text);
      article.appendChild(tip);

      function openDetail() {
        setText($('knowledge-modal-category'), card.category);
        setText($('knowledge-modal-title'), card.title);
        setText($('knowledge-modal-content'), card.content + (card.tags ? '\n\n关键词：' + card.tags : ''));
        openModal('knowledge-modal');
      }
      article.addEventListener('click', openDetail);
      article.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          openDetail();
        }
      });
      grid.appendChild(article);
    });
  }

  function loadProvinceCases(province) {
    var list = $('province-case-list');
    if (!list) return;
    var params = new URLSearchParams({ province: province || '', limit: '6' });
    API.get('/api/guardian/cases?' + params.toString()).then(function (data) {
      list.innerHTML = '';
      var items = data.items || [];
      if (!items.length) {
        list.innerHTML = '<p class="empty-inline">该省份暂无案例</p>';
        return;
      }
      items.forEach(function (item) {
        var card = document.createElement('article');
        card.className = 'province-case';
        var meta = document.createElement('p');
        meta.className = 'province-case__meta';
        meta.textContent = [item.province, item.category, item.code].filter(Boolean).join(' · ');
        var title = document.createElement('h4');
        title.className = 'province-case__title';
        title.textContent = item.scam_type || item.subtype || '反诈案例';
        var method = document.createElement('p');
        method.className = 'province-case__method';
        method.textContent = item.method || '';
        var tip = document.createElement('p');
        tip.className = 'province-case__tip';
        tip.textContent = '防范：' + (item.tips || '保持警惕，不转账、不透露验证码');
        card.appendChild(meta);
        card.appendChild(title);
        card.appendChild(method);
        card.appendChild(tip);
        list.appendChild(card);
      });
    }).catch(function () {
      list.innerHTML = '<p class="empty-inline">分省案例加载失败</p>';
    });
  }

  function initProvinceCases() {
    var select = $('province-select');
    if (!select) return;
    API.get('/api/guardian/provinces').then(function (data) {
      (data.items || []).forEach(function (item) {
        var option = document.createElement('option');
        option.value = item.province;
        option.textContent = item.province + '（' + item.count + '）';
        select.appendChild(option);
      });
      select.addEventListener('change', function () {
        loadProvinceCases(select.value);
      });
      loadProvinceCases('');
    }).catch(function () {
      loadProvinceCases('');
    });
  }

  function loadKnowledge() {
    API.get('/api/knowledge').then(function (data) {
      var baseItems = (data.items && data.items.length) ? data.items : FALLBACK_KNOWLEDGE;
      knowledgeItems = baseItems.slice();
      // 拓展：从案例库加载各类型科普，合并为知识卡片
      API.get('/api/case-library/categories').then(function (catData) {
        var cats = (catData.items || []).slice(0, 8);
        var pending = cats.length;
        if (!pending) { renderKnowledge(knowledgeItems); return; }
        cats.forEach(function (cat) {
          API.get('/api/case-library/science?category=' + encodeURIComponent(cat.name)).then(function (s) {
            var sc = s.item || {};
            if (sc.overview) {
              knowledgeItems.push({
                title: cat.name + '（' + cat.count + ' 例真实案例）',
                category: cat.name,
                content: sc.overview,
                tags: (sc.prevention || []).join('；')
              });
            }
            pending--;
            if (pending <= 0) renderKnowledge(knowledgeItems);
          }).catch(function () { pending--; if (pending <= 0) renderKnowledge(knowledgeItems); });
        });
      }).catch(function () { renderKnowledge(knowledgeItems); });
    }).catch(function () {
      renderKnowledge(FALLBACK_KNOWLEDGE);
    });
  }

  /* ------------------------------------------------------------------------
   * 六、每日一反诈
   * ---------------------------------------------------------------------- */
  var DAILY_CASES = [
    {
      region: '本地预警',
      type: '机票退改签理赔诈骗',
      date: '近期通报',
      title: '冒充航司客服理赔，屏幕共享后资金被分三次转走',
      story: '翟某接到自称航空公司客服的电话，称所购机票因飞机故障延误，可改签并承诺给其和家人每人理赔 300 元。对方引导下载聊天/会议软件，以“理赔过程需要录制”为由要求开启屏幕共享，随后让其逐个打开手机银行并输入验证码，卡内资金被分 3 次转走。',
      steps: [
        '非法获取购票等个人信息，准确说出姓名、证件、航班信息以骗取信任。',
        '以改签、退票、保险理赔为诱饵，引导点击短信链接或下载涉诈会议软件。',
        '要求开启屏幕共享/远程控制，实时看到手机操作界面，套取账户密码与验证码后转走资金。'
      ],
      tips: '退票理赔只通过航空公司官方 APP 或官方客服电话核实；凡是要求屏幕共享、远程指导操作的“理赔”都是诈骗；短信验证码绝不告诉任何人。'
    },
    {
      region: '全国通报 · 本地转发提醒',
      type: '冒充客服 + 涉诈 APP',
      date: '2025-02 预警',
      title: '“银联会议”APP 是诈骗软件，冒充客服取消会员扣费',
      story: '骗子冒充某短视频平台客服，称事主开通了“直播会员”，若不取消将每月自动扣费。随后添加事主微信、QQ，诱导下载名为“银联会议”的 APP，要求开启屏幕共享或远程控制，配合登录手机银行、输入密码和验证码，将卡内资金转走。中国银联已声明：该 APP 非中国银联产品。',
      steps: [
        '虚构“会员扣费、影响征信”等理由制造恐慌，冒充客服取得信任。',
        '诱导下载会议类涉诈 APP，躲避正规应用商店监管。',
        '通过屏幕共享暴露操作界面，套取密码、验证码后转账或远程操控手机。'
      ],
      tips: '自称客服要求取消“会员、百万保障、保险”业务的，基本都是诈骗；不下载来源不明的 APP；不共享屏幕；接到 96110 预警电话务必接听。'
    },
    {
      region: '学生群体高发',
      type: '刷单返利诈骗',
      date: '暑期高发预警',
      title: '兼职群“日赚 300”，小额返利后连单垫资无法提现',
      story: '在校学生在 QQ 群看到“足不出户、日赚数百”的兼职信息，扫码联系“客服”后接了几单小额任务并收到返利。随后被要求充值做大单、连续做单，对方以“任务未完成、系统卡单”为由不断要求追加垫付，最终本金无法提现，被对方拉黑。',
      steps: [
        '通过招聘群、短视频发布虚假兼职广告，以小额返利骗取信任。',
        '诱导下载涉诈 APP 或进入专用群聊接单。',
        '以连单、卡单、保证金、解冻费等名义要求持续垫资。',
        '大额投入后以各种理由拒绝提现，随即拉黑失联。'
      ],
      tips: '刷单本身属于违规行为，所有“刷单返利”都是诈骗；学生兼职先核实单位资质，不垫付、不充值、不向陌生账户转账。'
    }
  ];

  var dailyIndex = 0;

  /* ------------------------------------------------------------------------
   * 六-B、IP 省份选择 / 本地速览滚动 / 反诈科普板块
   * ---------------------------------------------------------------------- */
  var currentProvince = '';
  var briefTimer = null;
  var briefTick = 0;
  var briefTips = [];
  var briefProvinceCases = [];

  function initRegionPicker() {
    var input = $('region-select');
    var list = $('province-list');
    var badge = $('region-badge');
    var badgeText = $('region-badge-text');
    if (!input || !list) return;
    API.get('/api/case-library/provinces').then(function (data) {
      (data.items || []).forEach(function (p) {
        var opt = document.createElement('option');
        opt.value = p.name;
        list.appendChild(opt);
      });
    }).catch(function () {});
    function showBadge(province) {
      currentProvince = province;
      input.classList.add('is-hidden');
      if (badge && badgeText) {
        badgeText.textContent = province;
        badge.classList.remove('is-hidden');
      }
    }
    function showInput() {
      if (badge) badge.classList.add('is-hidden');
      input.classList.remove('is-hidden');
      input.value = '';
      currentProvince = '';
      localStorage.removeItem('guardian_province');
      briefTick = 0;
      loadBriefData();
      updateScienceByScore(0, '', '');
      input.focus();
    }
    var saved = localStorage.getItem('guardian_province');
    if (saved) { showBadge(saved); }
    input.addEventListener('change', function () {
      var val = input.value.trim();
      if (val) {
        localStorage.setItem('guardian_province', val);
        showBadge(val);
        briefTick = 0;
        loadBriefData();
        updateScienceByScore(0, '', '');
      }
    });
    if (badge) badge.addEventListener('click', showInput);
  }

  function loadBriefData() {
    API.get('/api/case-library/tips').then(function (data) {
      briefTips = data.items || [];
    }).catch(function () { briefTips = []; });
    if (currentProvince) {
      API.get('/api/case-library/cases?province=' + encodeURIComponent(currentProvince) + '&limit=20').then(function (data) {
        briefProvinceCases = data.items || [];
      }).catch(function () { briefProvinceCases = []; });
    } else {
      briefProvinceCases = [];
    }
  }

  function rotateBrief() {
    briefTick++;
    var title = $('local-brief-title');
    var content = $('local-brief-content');
    if (!title || !content) return;
    if (currentProvince && briefProvinceCases.length && briefTick % 2 === 0) {
      var c = briefProvinceCases[Math.floor(Math.random() * briefProvinceCases.length)];
      title.textContent = currentProvince + ' · 真实案例';
      content.innerHTML = '<strong>' + (c.scam_type || c.category || '') + '</strong>：' +
        (c.method || '').slice(0, 80) + ' <em>来源：' + (c.source || '').slice(0, 30) + '</em>';
    } else if (briefTips.length) {
      var tip = briefTips[Math.floor(Math.random() * briefTips.length)];
      title.textContent = '反诈小知识';
      content.textContent = tip;
    } else {
      title.textContent = '反诈小知识';
      content.textContent = '验证码是最后一道防线，任何索要验证码的人都是骗子。';
    }
  }

  function initLocalBrief() {
    loadBriefData();
    rotateBrief();
    if (briefTimer) clearInterval(briefTimer);
    briefTimer = setInterval(rotateBrief, 6000);
  }

  function renderScience(item) {
    var overview = $('science-overview');
    var cases = $('science-cases');
    var count = $('science-count');
    if (!overview || !cases) return;
    if (item) {
      setText(count, item.category + ' · ' + item.case_count + ' 例');
      overview.innerHTML = '<strong>' + item.category + '</strong>：' + item.overview;
      var html = '';
      (item.prevention || []).forEach(function (p) {
        html += '<p class="science-block__tip">· ' + p + '</p>';
      });
      (item.cases || []).forEach(function (c) {
        html += '<div class="science-block__case"><strong>' + (c.scam_type || '') +
          '</strong>（' + (c.region || '') + '）<p>' + (c.method || '').slice(0, 120) +
          '</p><p class="science-block__source">损失：' + (c.loss || '未明') +
          ' · 来源：' + (c.source || '').slice(0, 40) + '</p></div>';
      });
      cases.innerHTML = html;
    } else {
      setText(count, '案例库');
      overview.textContent = '未检测时随机展示真实案例；检测到疑似诈骗（≥70%）时展示对应类型科普与案例。';
      cases.innerHTML = '';
    }
  }

  function updateScienceByScore(score, riskLabel, scamType) {
    if (score >= 70) {
      var url = '/api/case-library/science/match?score=' + score +
        '&risk_label=' + encodeURIComponent(riskLabel || '') +
        '&scam_type=' + encodeURIComponent(scamType || '');
      API.get(url).then(function (data) {
        renderScience(data.item);
      }).catch(function () {});
    } else {
      API.get('/api/case-library/random').then(function (data) {
        if (data.item && data.item.category) {
          API.get('/api/case-library/science?category=' + encodeURIComponent(data.item.category)).then(function (s) {
            renderScience(s.item);
          }).catch(function () {});
        }
      }).catch(function () {});
    }
  }

  function initScienceBlock() {
    updateScienceByScore(0, '', '');
  }

  /* ------------------------------------------------------------------------
   * 七、反诈问答
   * ---------------------------------------------------------------------- */
  var _FALLBACK_QUESTIONS = [
    {
      q: '陌生来电自称客服，说你开通了“直播会员 / 百万保障”，不取消就会自动扣费，并让你下载会议软件、开启屏幕共享。正确做法是？',
      options: ['按对方指引下载软件并共享屏幕，尽快取消业务', '挂断电话，通过官方客服渠道核实，绝不开启屏幕共享', '添加对方微信，按提示一步步操作'],
      answer: 1,
      explain: '凡是自称客服要求取消“会员 / 保障”、并引导下载会议软件或共享屏幕的，都是典型诈骗；业务核实只走官方渠道。'
    },
    {
      q: '兼职群里发布“刷单返利、日赚 300”，先返了几元小额佣金，随后让你垫付做大单。你应该？',
      options: ['这是正规兼职，佣金高可以加大投入', '立即退出并拉黑，刷单返利本身就是诈骗', '先垫付小额试试，能提现再继续'],
      answer: 1,
      explain: '小额返利是诱饵，目的是骗取信任后诱导大额垫资；刷单违规，后续会以卡单、连单为由拒绝提现。'
    },
    {
      q: '网恋对象带你在某 App 上“投资理财、刷流水”，说平台稳赚不赔、有内部导师。这属于？',
      options: ['可靠的理财渠道，可以跟着投钱', '“杀猪盘”或虚假投资理财诈骗，应停止联系并举报', '先投少量，盈利后再追加'],
      answer: 1,
      explain: '陌生交友引流到虚假投资平台是杀猪盘典型套路，前期小额盈利是为了诱导大额投入，最终无法提现。'
    },
    {
      q: '接到“公检法”电话，称你涉嫌洗钱，要求把钱转到“安全账户”配合审查。正确的是？',
      options: ['配合转账，自证清白', '公检法不会电话办案，也不存在“安全账户”，挂断后拨打 110 核实', '按对方要求到宾馆开房接电话、下载软件'],
      answer: 1,
      explain: '公检法机关不会通过电话、QQ 微信办案，更没有所谓“安全账户”；要求转账验资的一律是诈骗。'
    },
    {
      q: '针对老年人的骗局中，对方自称是子女朋友或亲属，急用钱让你先转账。稳妥做法是？',
      options: ['电话里听着急就先转过去', '通过子女本人电话或当面核实身份后再决定，不轻信', '按对方给的账号汇款'],
      answer: 1,
      explain: '冒充亲属借钱常利用孝心和紧迫感；转账前务必通过已知联系方式或当面核实，必要时联系社区民警。'
    }
  ];

  var quizQuestions = _FALLBACK_QUESTIONS;
  var quizAnswers = new Array(quizQuestions.length).fill(null);

  function loadQuiz() {
    API.get('/api/case-library/quiz?count=5').then(function (data) {
      quizQuestions = (data.items || []).map(function (q) {
        return { q: q.question, options: q.options, answer: q.answer, explain: q.explanation };
      });
      if (!quizQuestions.length) quizQuestions = _FALLBACK_QUESTIONS;
      quizAnswers = new Array(quizQuestions.length).fill(null);
      var result = $('quiz-result');
      if (result) result.hidden = true;
      renderQuiz();
    }).catch(function () {});
  }

  function answeredCount() {
    return quizAnswers.filter(function (item) { return item !== null; }).length;
  }

  function renderQuiz() {
    var list = $('quiz-list');
    var result = $('quiz-result');
    var progress = $('quiz-progress');
    if (!list) return;
    list.innerHTML = '';
    if (result) result.hidden = true;

    quizQuestions.forEach(function (item, qi) {
      var block = document.createElement('div');
      block.className = 'quiz-question';

      var title = document.createElement('p');
      title.className = 'quiz-question__title';
      title.textContent = (qi + 1) + '. ' + item.q;
      block.appendChild(title);

      var options = document.createElement('div');
      options.className = 'quiz-options';
      item.options.forEach(function (text, oi) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'quiz-option';
        var mark = document.createElement('span');
        mark.className = 'quiz-option__mark';
        mark.textContent = 'ABCD'[oi];
        var content = document.createElement('span');
        content.textContent = text;
        btn.appendChild(mark);
        btn.appendChild(content);

        if (quizAnswers[qi] !== null) {
          btn.disabled = true;
          if (oi === item.answer) btn.classList.add('quiz-option--correct');
          else if (oi === quizAnswers[qi]) btn.classList.add('quiz-option--wrong');
        } else {
          btn.addEventListener('click', function () {
            if (quizAnswers[qi] !== null) return;
            quizAnswers[qi] = oi;
            renderQuiz();
            checkQuizDone();
          });
        }
        options.appendChild(btn);
      });
      block.appendChild(options);

      var feedback = document.createElement('p');
      feedback.className = 'quiz-feedback';
      if (quizAnswers[qi] !== null) {
        var ok = quizAnswers[qi] === item.answer;
        feedback.classList.add('quiz-feedback--show', ok ? 'quiz-feedback--ok' : 'quiz-feedback--no');
        feedback.textContent = (ok ? '回答正确。' : '回答不正确。') + item.explain;
      }
      block.appendChild(feedback);
      list.appendChild(block);
    });
    setText(progress, '已答 ' + answeredCount() + ' / ' + quizQuestions.length + ' 题');
  }

  function checkQuizDone() {
    if (answeredCount() !== quizQuestions.length) return;
    var correct = quizAnswers.filter(function (answer, index) {
      return answer === quizQuestions[index].answer;
    }).length;
    var percent = Math.round((correct / quizQuestions.length) * 100);
    setText($('quiz-score'), correct + ' / ' + quizQuestions.length + ' 题 · ' + percent + ' 分');
    if (correct === quizQuestions.length) {
      setText($('quiz-level'), '反诈达人');
      setText($('quiz-desc'), '全部答对，防骗意识很强！继续保持，也把这些要点分享给家人和同学。');
    } else if (correct >= 3) {
      setText($('quiz-level'), '基本掌握');
      setText($('quiz-desc'), '大部分题目答对了，可以再看一遍知识宣传里的骗局类型，巩固薄弱环节。');
    } else {
      setText($('quiz-level'), '还需加强');
      setText($('quiz-desc'), '还有不少套路需要了解，建议先阅读“知识宣传”板块，再回来重新作答。');
    }
    var result = $('quiz-result');
    if (result) result.hidden = false;
  }

  function bindQuiz() {
    var restart = $('quiz-restart');
    if (restart) {
      restart.addEventListener('click', function () {
        loadQuiz();
      });
    }
    loadQuiz();
  }

  /* ------------------------------------------------------------------------
   * 八、视图切换与初始化
   * ---------------------------------------------------------------------- */

  function renderContacts(items) {
    var grid = $('contact-list');
    var empty = $('contact-empty');
    var select = $('contact-select');
    if (select) {
      select.innerHTML = '<option value="">选择更新到的用户</option>';
      (items || []).forEach(function (item) {
        var score = Number(item.risk_score || 0);
        var option = document.createElement('option');
        option.value = item.contact_id;
        option.textContent = (score >= 70 ? '⚠ ' : '') + (item.contact_name || item.contact_id) + ' · ' + score + '%';
        select.appendChild(option);
      });
    }
    if (!grid) return;
    grid.innerHTML = '';
    if (!items || !items.length) {
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    items.forEach(function (item) {
      var score = Number(item.risk_score || 0);
      var card = document.createElement('article');
      card.className = 'contact-card' + (score >= 90 ? ' contact-card--critical' : (score >= 70 ? ' contact-card--high' : ''));
      var head = document.createElement('div');
      head.className = 'contact-card__head';
      var name = document.createElement('strong');
      name.className = 'contact-card__name' + (score >= 90 ? ' contact-card__name--critical' : (score >= 70 ? ' contact-card__name--high' : ''));
      name.textContent = item.contact_name || item.contact_id;
      var scoreEl = document.createElement('span');
      scoreEl.className = 'contact-card__score';
      scoreEl.textContent = score + '%';
      head.appendChild(name);
      head.appendChild(scoreEl);
      var summary = document.createElement('p');
      summary.className = 'contact-card__summary';
      summary.textContent = item.summary || '暂无摘要';
      var meta = document.createElement('p');
      meta.className = 'contact-card__meta';
      meta.textContent = (item.risk_label || '') + ' · 更新 ' + (item.updated_at || '') + ' · 过期 ' + (item.expires_at || '');
      var actions = document.createElement('div');
      actions.className = 'contact-card__actions';
      var load = document.createElement('button');
      load.className = 'btn btn--primary btn--sm';
      load.type = 'button';
      load.textContent = '载入检测';
      load.addEventListener('click', function () { loadContact(item.contact_id); });
      var del = document.createElement('button');
      del.className = 'btn btn--ghost btn--sm';
      del.type = 'button';
      del.textContent = '删除记录';
      del.addEventListener('click', function () { deleteContact(item.contact_id); });
      actions.appendChild(load);
      actions.appendChild(del);
      card.appendChild(head);
      card.appendChild(summary);
      card.appendChild(meta);
      card.appendChild(actions);
      grid.appendChild(card);
    });
  }

  function loadContacts() {
    API.get('/api/conversations').then(function (data) {
      renderContacts(data.items || []);
    }).catch(function () {
      renderContacts([]);
    });
  }

  function loadContact(contactId) {
    API.get('/api/conversations/' + encodeURIComponent(contactId)).then(function (data) {
      var item = data.item;
      if (!item) return;
      switchView('monitor');
      var input = $('chat-text');
      if (input) {
        input.value = item.text || '（该对话未检测到可疑话术）';
        updateChatStats();
      }
      state.analysis = item.result || {};
      state.analysisId = null;
      state.saved = false;
      state.monitorAt = 0;
      renderAnalysis(item.result || {});
      setEngine('对话记录', '按对方 ID 隔离的临时记录');
      setGuard('记录已载入', true);
    }).catch(function (error) {
      toast('对话记录载入失败：' + error.message, 'error');
    });
  }

  function deleteContact(contactId) {
    if (!window.confirm('确定删除这个对话记录？')) return;
    API.remove('/api/conversations/' + encodeURIComponent(contactId)).then(function () {
      toast('对话记录已删除', 'success');
      loadContacts();
    }).catch(function (error) {
      toast('删除失败：' + error.message, 'error');
    });
  }

  function bindContacts() {
    var refresh = $('refresh-contacts');
    if (refresh) refresh.addEventListener('click', loadContacts);
    var select = $('contact-select');
    if (select) {
      select.addEventListener('change', function () {
        if (select.value) loadContact(select.value);
      });
    }
  }

  function switchView(name) {
    document.querySelectorAll('.view').forEach(function (view) {
      view.classList.toggle('is-active', view.id === 'view-' + name);
    });
    if (name === 'images') renderImageCaptures();
    if (name === 'contacts') loadContacts();
    document.querySelectorAll('[data-view-link]').forEach(function (link) {
      var active = link.getAttribute('data-view-link') === name;
      link.classList.toggle('site-nav__link--active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function bindViews() {
    document.querySelectorAll('[data-view-link]').forEach(function (link) {
      link.addEventListener('click', function (event) {
        var name = link.getAttribute('data-view-link');
        if (!document.getElementById('view-' + name)) return;
        event.preventDefault();
        switchView(name);
        history.replaceState(null, '', '#' + name);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });
    var hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById('view-' + hash)) {
      switchView(hash);
    }
  }

  function loadConfig() {
    API.get('/api/config').then(function (data) {
      if (data.ai && data.ai.enabled) {
        setEngine('Guardian-AI', data.ai.note);
      } else {
        setEngine('Guardian-AI', data.ai ? data.ai.note : '本地规则引擎');
      }
      setGuard('防护已就绪', true);
    }).catch(function () {
      setGuard('本地演示模式', false);
    });
  }

  function init() {
    bindViews();
    bindContacts();
    bindTextEvents();
    bindUploader();
    bindRecorder();
    bindActions();
    bindModals();
    bindContractControls();
    bindMonitorSync();
    initRegionPicker();
    initLocalBrief();
    initScienceBlock();
    bindQuiz();
    renderKnowledge(FALLBACK_KNOWLEDGE);
    loadKnowledge();
    initProvinceCases();
    loadConfig();
    var clearCaptures = $('clear-image-captures');
    if (clearCaptures) clearCaptures.addEventListener('click', clearImageCaptures);
    renderImageCaptures();
    initIncomingMedia();
    renderMedia();
    setButtonEnabled('report-btn', false);
    setButtonEnabled('export-btn', false);
    setButtonEnabled('copy-btn', false);
    setButtonEnabled('feedback-btn', false);
    analyze(false, false);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
