/* ==========================================================================
   反诈卫士 · API 客户端
   页面既可通过 FastAPI 访问（相对路径），也可用 Live Server 打开（回退 8000 端口）。
   ========================================================================== */
(function () {
  'use strict';

  var API_BASE = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';

  function buildUrl(path) {
    return API_BASE + path;
  }

  async function parseResponse(response) {
    var contentType = response.headers.get('content-type') || '';
    var payload = null;
    if (contentType.indexOf('application/json') !== -1) {
      payload = await response.json();
    } else {
      var text = await response.text();
      payload = { detail: text };
    }
    if (!response.ok) {
      var message = payload && payload.detail ? payload.detail : '请求失败（' + response.status + '）';
      throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
    }
    return payload;
  }

  async function get(path) {
    var response = await fetch(buildUrl(path), { headers: { Accept: 'application/json' } });
    return parseResponse(response);
  }

  async function postJson(path, body) {
    var response = await fetch(buildUrl(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body)
    });
    return parseResponse(response);
  }

  async function postForm(path, formData) {
    var response = await fetch(buildUrl(path), {
      method: 'POST',
      body: formData,
      headers: { Accept: 'application/json' }
    });
    return parseResponse(response);
  }

  async function remove(path) {
    var response = await fetch(buildUrl(path), { method: 'DELETE', headers: { Accept: 'application/json' } });
    return parseResponse(response);
  }

  function analyzeMultimodal(text, files, save) {
    var form = new FormData();
    form.append('text', text || '');
    form.append('note', '');
    form.append('save', save ? 'true' : 'false');
    (files || []).forEach(function (item) {
      form.append('files', item.file, item.file.name);
    });
    return postForm('/api/analyze', form);
  }

  function analyzeText(text, save) {
    return postJson('/api/analyze/text', { text: text || '', save: Boolean(save) });
  }

  function downloadUrl(path) {
    return buildUrl(path);
  }

  function riskMeta(level) {
    var map = {
      low: { key: 'low', label: '低风险', color: '#16a34a' },
      medium: { key: 'medium', label: '中风险', color: '#d97706' },
      high: { key: 'high', label: '高风险', color: '#dc2626' },
      critical: { key: 'critical', label: '极高风险', color: '#dc2626' }
    };
    return map[level] || map.low;
  }

  function formatTime(value) {
    if (!value) return '';
    return String(value).replace('T', ' ').slice(0, 19);
  }

  function formatBytes(bytes) {
    if (!bytes) return '0 B';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  }

  window.AntiFraudAPI = {
    base: API_BASE,
    get: get,
    postJson: postJson,
    postForm: postForm,
    remove: remove,
    analyzeMultimodal: analyzeMultimodal,
    analyzeText: analyzeText,
    downloadUrl: downloadUrl,
    riskMeta: riskMeta,
    formatTime: formatTime,
    formatBytes: formatBytes
  };
})();
