/* ==========================================================================
   Guardian-AI · 用户中心 + OpenAI 兼容 API 配置
   - 邮箱登录 / 自动注册（未注册即注册登录）
   - 每用户 API 配置保存、自动同步、登录时连通性检测
   - 连接异常时顶部 API 导航闪烁粉色
   ========================================================================== */
(function () {
  'use strict';

  var API = window.AntiFraudAPI;
  var auth = { user: null, mode: 'login', busy: false };
  var autoSync = { timer: null, pending: false, saving: false };

  function $(id) {
    return document.getElementById(id);
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
    toast._timer = window.setTimeout(function () { hide(el); }, 3800);
  }

  function formatTime(value) {
    if (!value) return '—';
    return String(value).replace('T', ' ').slice(0, 19);
  }

  function apiLabel(cfg) {
    if (!cfg || !cfg.configured) return '未配置';
    if (cfg.status === 'ok') return '连接正常';
    if (cfg.status === 'error') return '连接异常';
    return '待检测';
  }

  function displayName(user) {
    if (!user) return '';
    return user.role === 'root' ? '管理员' : user.username;
  }

  function setNavAlert(on) {
    var nav = $('nav-api');
    if (nav) nav.classList.toggle('is-api-alert', Boolean(on));
  }

  function updateAccount(cfg) {
    var user = auth.user;
    if (!user) return;
    var account = $('auth-account');
    if (!account) return;
    var name = $('auth-account-name');
    var role = $('auth-account-role');
    var idEl = $('auth-account-id');
    var keyEl = $('auth-account-key');
    var apiEl = $('auth-account-api');
    var quotaEl = $('auth-account-quota');
    var lastEl = $('auth-account-last');
    var avatar = $('auth-account-avatar');
    if (name) name.textContent = displayName(user);
    if (role) role.textContent = user.role === 'root' ? '管理员' : '普通用户';
    if (idEl) idEl.textContent = '#' + user.id;
    if (keyEl) keyEl.textContent = user.role === 'root'
      ? '受保护'
      : (user.user_key || ('u' + user.id + ':' + String(user.username).toLowerCase()));
    if (apiEl) {
      apiEl.textContent = cfg && cfg.configured
        ? (cfg.status === 'error' ? '连接异常（请到 API 页检查）' : apiLabel(cfg))
        : '未配置';
      apiEl.classList.toggle('is-error', Boolean(cfg && cfg.configured && cfg.status === 'error'));
    }
    if (quotaEl) quotaEl.textContent = user.role === 'root' ? '不限额' : (quotaEl.dataset.text || '读取中…');
    if (lastEl) lastEl.textContent = formatTime(user.last_login_at);
    if (avatar) avatar.textContent = user.role === 'root' ? 'A' : (user.username || 'G').slice(0, 1).toUpperCase();
  }

  function renderApiStatus(cfg, check) {
    var pill = $('api-status-pill');
    var provider = $('api-status-provider');
    var model = $('api-status-model');
    var time = $('api-status-time');
    var latency = $('api-status-latency');
    var message = $('api-status-message');
    var badge = $('api-state-badge');
    var badgeText = $('api-state-text');
    var configured = Boolean(cfg && cfg.configured);
    var ok = Boolean(check && check.ok) || (configured && cfg.status === 'ok' && !check);
    var failed = Boolean(check && !check.ok) || (configured && cfg.status === 'error');

    if (pill) {
      pill.textContent = failed ? '连接失败' : (ok ? '连接正常' : (configured ? '待检测' : '未测试'));
      pill.className = 'api-status-pill' +
        (failed ? ' api-status-pill--error' : (ok ? ' api-status-pill--ok' : ''));
    }
    if (badge) {
      badge.className = 'api-state ' +
        (failed ? 'api-state--error' : (ok ? 'api-state--ok' : 'api-state--idle'));
    }
    if (badgeText) badgeText.textContent = failed ? '连接异常' : (ok ? '已连接' : (auth.user ? '未配置' : '未登录'));
    if (provider) provider.textContent = configured ? cfg.base_url : '本地规则 / .env';
    if (model) model.textContent = configured ? cfg.model : '—';
    if (time) time.textContent = check ? '刚刚' : formatTime(cfg && cfg.checked_at);
    if (latency) latency.textContent = check ? (check.latency_ms || 0) + ' ms' : '—';
    if (message) {
      if (check) {
        message.textContent = check.message || (check.ok ? '连接成功' : '连接失败');
      } else if (!auth.user) {
        message.textContent = '登录后可保存并检测你的 OpenAI 兼容接口。';
      } else if (!configured) {
        message.textContent = '尚未保存 API 配置，当前使用 .env 中的默认 AI 接口或本地规则。';
      } else if (failed) {
        message.textContent = '该用户的 API 连接异常，顶部 API 导航正在闪烁提醒，请检查地址、Key 与模型。';
      } else if (ok) {
        message.textContent = '上次检测连接正常，该配置已应用到当前程序。';
      } else {
        message.textContent = '配置已保存，等待测试连接。';
      }
      message.classList.toggle('is-error', failed);
    }
    setNavAlert(configured && failed && Boolean(auth.user));
    updateAccount(cfg);
  }

  function renderApiGate() {
    var gate = $('api-gate');
    var form = $('api-form');
    if (!gate || !form) return;
    if (auth.user) {
      hide(gate);
      show(form);
    } else {
      show(gate);
      hide(form);
    }
  }

  function fillApiForm(cfg) {
    var base = $('api-base-url');
    var key = $('api-key');
    var model = $('api-model');
    var vision = $('api-vision-model');
    var tip = $('api-key-tip');
    cfg = cfg || {};
    if (base) base.value = cfg.base_url || '';
    if (key) {
      key.value = '';
      key.placeholder = cfg.has_key ? ('已保存 ' + (cfg.key_masked || '••••') + '（留空则不修改）') : 'sk-...';
    }
    if (model) model.value = cfg.model || '';
    if (vision) vision.value = cfg.vision_model || '';
    if (tip) {
      tip.textContent = cfg.has_key
        ? '已保存 Key（' + (cfg.key_masked || '••••') + '）。留空提交会保留原 Key。'
        : 'Key 仅保存在本机数据库，不会回显到页面。';
    }
  }

  function renderUser(user) {
    auth.user = user || null;
    var dataKey = user && user.user_key ? user.user_key : 'u1001:root';
    window.GuardianUserKey = dataKey;
    if (window.GuardianSetUserKey) window.GuardianSetUserKey(dataKey);
    var guest = $('user-guest');
    var chip = $('user-chip');
    if (user) {
      hide(guest);
      show(chip);
      var name = $('user-name');
      var meta = $('user-meta');
      var avatar = $('user-avatar');
      if (name) name.textContent = displayName(user);
      if (meta) meta.textContent = user.role === 'root' ? '管理员账号' : '用户 #' + user.id;
      if (avatar) avatar.textContent = user.role === 'root' ? 'A' : (user.username || 'G').slice(0, 1).toUpperCase();
      fillApiForm(user.api);
    } else {
      show(guest);
      hide(chip);
      fillApiForm({});
    }
    renderApiGate();
    renderApiStatus(user && user.api, null);
    loadQuota(user);
  }

  function loadQuota(user) {
    var el = $('auth-account-quota');
    if (!el) return;
    if (!user) {
      el.textContent = '—';
      delete el.dataset.text;
      return;
    }
    if (user.role === 'root') {
      el.textContent = '不限额';
      return;
    }
    el.textContent = '读取中…';
    API.get('/api/auth/quota').then(function (data) {
      var text = API.formatBytes(data.used_bytes) + ' / ' + API.formatBytes(data.limit_bytes);
      el.dataset.text = text;
      el.textContent = text;
    }).catch(function () {
      el.textContent = '—';
    });
  }

  /* ------------------------------------------------------------------ 登录 */

  function setAuthMode(mode) {
    auth.mode = mode === 'register' ? 'register' : 'login';
    document.querySelectorAll('[data-auth-mode]').forEach(function (tab) {
      tab.classList.toggle('is-active', tab.getAttribute('data-auth-mode') === auth.mode);
    });
    var title = $('auth-title');
    var submit = $('auth-submit');
    var hint = $('auth-hint');
    if (title) title.textContent = auth.mode === 'register' ? '注册账号' : '账号登录';
    if (submit) submit.textContent = auth.mode === 'register' ? '注册并登录' : '登录';
    if (hint) {
      hint.textContent = auth.mode === 'register'
        ? '普通用户使用邮箱注册，必须填写访问密钥；若邮箱已存在，将校验密码并登录。'
        : '普通用户登录需填写访问密钥；如果数据库中没有该邮箱，将自动注册并登录。';
    }
    setAuthMessage('');
  }

  function setAuthMessage(text, type) {
    var el = $('auth-message');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'auth-message' + (text ? '' : ' is-hidden') + (type ? ' auth-message--' + type : '');
  }

  function openAuth(mode) {
    var modal = $('auth-modal');
    if (!modal) return;
    show(modal);
    var account = $('auth-account');
    var form = $('auth-form');
    if (auth.user) {
      if (form) hide(form);
      if (account) show(account);
      var accountTitle = $('auth-title');
      if (accountTitle) accountTitle.textContent = '个人信息';
      updateAccount(auth.user.api);
      return;
    }
    if (account) hide(account);
    if (form) show(form);
    setAuthMode(mode || 'login');
    setAuthMessage('');
    window.setTimeout(function () {
      var username = $('auth-username');
      if (username) username.focus();
    }, 60);
  }

  function closeAuth() {
    var modal = $('auth-modal');
    if (modal) hide(modal);
  }

  function submitAuth(event) {
    if (event) event.preventDefault();
    if (auth.busy) return;
    var username = ($('auth-username') || {}).value || '';
    var password = ($('auth-password') || {}).value || '';
    var accessKey = ($('auth-access-key') || {}).value || '';
    var privacy = $('auth-privacy');
    username = username.trim();
    if (!username) return setAuthMessage('请输入邮箱地址');
    if (!password || password.length < 6) return setAuthMessage('密码至少 6 位');
    if (privacy && !privacy.checked) return setAuthMessage('请先勾选同意隐私政策');
    auth.busy = true;
    var submit = $('auth-submit');
    if (submit) { submit.disabled = true; submit.textContent = '处理中…'; }
    setAuthMessage('');
    API.postJson('/api/auth/login', {
      username: username, password: password, access_key: accessKey.trim()
    }).then(function (data) {
      auth.busy = false;
      if (submit) { submit.disabled = false; submit.textContent = auth.mode === 'register' ? '注册并登录' : '登录'; }
      var user = data.user;
      renderUser(user);
      closeAuth();
      var passwordEl = $('auth-password');
      if (passwordEl) passwordEl.value = '';
      var keyEl = $('auth-access-key');
      if (keyEl) keyEl.value = '';
      if (data.created) toast('账号已创建并登录：' + displayName(user), 'success');
      else toast('登录成功：' + displayName(user), 'success');
      if (data.api_check && !data.api_check.ok) {
        toast('API 连接异常，请在 API 页检查配置', 'error');
      } else if (user.api && user.api.configured && user.api.status === 'ok') {
        toast('已自动应用你的 API 配置', 'success');
      }
    }).catch(function (error) {
      auth.busy = false;
      if (submit) { submit.disabled = false; submit.textContent = auth.mode === 'register' ? '注册并登录' : '登录'; }
      setAuthMessage(error.message || '登录失败，请稍后重试', 'error');
    });
  }

  function logout() {
    API.postJson('/api/auth/logout', {}).then(function () {
      renderUser(null);
      closeAuth();
      toast('已退出登录', 'success');
    }).catch(function (error) {
      toast(error.message || '退出失败', 'error');
    });
  }

  /* --------------------------------------------------------------- API 配置 */

  function collectApi() {
    return {
      base_url: (($('api-base-url') || {}).value || '').trim(),
      api_key: (($('api-key') || {}).value || '').trim(),
      model: (($('api-model') || {}).value || '').trim(),
      vision_model: (($('api-vision-model') || {}).value || '').trim()
    };
  }

  function canAutoSync() {
    var cfg = collectApi();
    var hasKey = cfg.api_key || (auth.user && auth.user.api && auth.user.api.has_key);
    return Boolean(auth.user && cfg.base_url && cfg.model && hasKey);
  }

  function setAutoSync(text, state) {
    var el = $('api-autosync');
    if (!el) return;
    el.className = 'api-autosync' + (state ? ' api-autosync--' + state : '');
    el.textContent = '';
    var dot = document.createElement('span');
    dot.className = 'api-autosync__dot';
    el.appendChild(dot);
    el.appendChild(document.createTextNode(text));
  }

  function applySaved(data, silent) {
    var check = data.api_check;
    if (data.user) {
      auth.user = data.user;
      renderUser(data.user);
    }
    renderApiStatus(auth.user && auth.user.api, check);
    if (check && check.ok) {
      setAutoSync('已同步 · ' + (check.latency_ms || 0) + ' ms · ' + (auth.user.api.model || ''), 'ok');
      if (!silent) toast('API 已同步并连接成功', 'success');
    } else if (check && !check.ok) {
      setAutoSync('已同步但连接失败', 'error');
      if (!silent) toast(check.message || 'API 连接失败', 'error');
    } else {
      setAutoSync('输入完成后自动同步', '');
    }
  }

  function saveApi(silent) {
    if (!auth.user) {
      openAuth('login');
      return Promise.resolve();
    }
    if (autoSync.saving) {
      autoSync.pending = true;
      return Promise.resolve();
    }
    var cfg = collectApi();
    var hasKey = cfg.api_key || (auth.user.api && auth.user.api.has_key);
    if (!cfg.base_url || !cfg.model) {
      setAutoSync('请填写 API 地址与文本模型', 'error');
      return Promise.resolve();
    }
    if (!hasKey) {
      setAutoSync('请填写 API Key', 'error');
      return Promise.resolve();
    }
    autoSync.saving = true;
    autoSync.pending = false;
    setAutoSync('正在同步并测试连接…', 'loading');
    var saveBtn = $('api-save-btn');
    if (saveBtn) saveBtn.disabled = true;
    return API.putJson('/api/auth/api-config', cfg).then(function (data) {
      applySaved(data, silent);
      var keyEl = $('api-key');
      if (keyEl) keyEl.value = '';
    }).catch(function (error) {
      setAutoSync('同步失败：' + (error.message || '未知错误'), 'error');
      if (!silent) toast(error.message || '保存失败', 'error');
    }).then(function () {
      autoSync.saving = false;
      if (saveBtn) saveBtn.disabled = false;
      if (autoSync.pending) {
        autoSync.pending = false;
        saveApi(true);
      }
    });
  }

  function testApi() {
    if (!auth.user) { openAuth('login'); return; }
    var testBtn = $('api-test-btn');
    if (testBtn) testBtn.disabled = true;
    setAutoSync('正在测试连接…', 'loading');
    API.postJson('/api/auth/api-test', {}).then(function (data) {
      applySaved(data, false);
    }).catch(function (error) {
      setAutoSync('测试失败：' + (error.message || '未知错误'), 'error');
      toast(error.message || '测试失败', 'error');
    }).then(function () {
      if (testBtn) testBtn.disabled = false;
    });
  }

  function clearApi() {
    if (!auth.user) { openAuth('login'); return; }
    if (!window.confirm('确定清空当前账号保存的 API 配置吗？')) return;
    API.putJson('/api/auth/api-config', { clear: true }).then(function (data) {
      fillApiForm({});
      applySaved(data, false);
      setAutoSync('已重置，输入完成后自动同步', '');
      toast('API 配置已重置', 'success');
    }).catch(function (error) {
      toast(error.message || '重置失败', 'error');
    });
  }

  function scheduleAutoSync() {
    if (!auth.user) return;
    window.clearTimeout(autoSync.timer);
    if (!canAutoSync()) {
      setAutoSync('填写 API 地址、Key、模型后自动同步', '');
      return;
    }
    setAutoSync('等待输入完成…', 'loading');
    autoSync.timer = window.setTimeout(function () { saveApi(true); }, 1100);
  }

  function bindApi() {
    var form = $('api-form');
    if (form) form.addEventListener('submit', function (e) { e.preventDefault(); saveApi(false); });
    ['api-base-url', 'api-key', 'api-model', 'api-vision-model'].forEach(function (id) {
      var el = $(id);
      if (el) el.addEventListener('input', scheduleAutoSync);
    });
    var saveBtn = $('api-save-btn');
    if (saveBtn) saveBtn.addEventListener('click', function () { saveApi(false); });
    var testBtn = $('api-test-btn');
    if (testBtn) testBtn.addEventListener('click', testApi);
    var clearBtn = $('api-clear-btn');
    if (clearBtn) clearBtn.addEventListener('click', clearApi);
    var keyToggle = $('api-key-toggle');
    if (keyToggle) keyToggle.addEventListener('click', function () {
      var key = $('api-key');
      if (!key) return;
      var visible = key.type === 'text';
      key.type = visible ? 'password' : 'text';
      keyToggle.textContent = visible ? '显示' : '隐藏';
    });
    var gateLogin = $('api-gate-login');
    if (gateLogin) gateLogin.addEventListener('click', function () { openAuth('login'); });
  }

  function bindAuth() {
    document.querySelectorAll('[data-auth-open]').forEach(function (el) {
      el.addEventListener('click', function (event) {
        event.preventDefault();
        openAuth(el.getAttribute('data-auth-open'));
      });
      el.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          openAuth(el.getAttribute('data-auth-open'));
        }
      });
    });
    var chip = $('user-chip');
    if (chip) chip.addEventListener('click', function () { openAuth('login'); });
    document.querySelectorAll('[data-auth-mode]').forEach(function (tab) {
      tab.addEventListener('click', function () { setAuthMode(tab.getAttribute('data-auth-mode')); });
    });
    var form = $('auth-form');
    if (form) form.addEventListener('submit', submitAuth);
    var logoutBtn = $('auth-logout');
    if (logoutBtn) logoutBtn.addEventListener('click', logout);
    var gotoApi = $('auth-goto-api');
    if (gotoApi) gotoApi.addEventListener('click', function () {
      closeAuth();
      var link = document.querySelector('[data-view-link="api"]');
      if (link) link.click();
    });
    var passwordToggle = $('auth-password-toggle');
    if (passwordToggle) passwordToggle.addEventListener('click', function () {
      var password = $('auth-password');
      if (!password) return;
      var visible = password.type === 'text';
      password.type = visible ? 'password' : 'text';
      passwordToggle.textContent = visible ? '显示' : '隐藏';
    });
    var privacyLink = $('auth-privacy-link');
    if (privacyLink) privacyLink.addEventListener('click', function (event) {
      event.preventDefault();
      toast('演示版隐私政策：账号与 API 配置仅保存在本机 SQL Server [user] 库，不跨用户查询。', 'success');
    });
  }

  function loadAuth() {
    renderApiStatus(null, null);
    API.get('/api/auth/me').then(function (data) {
      renderUser(data.user || null);
    }).catch(function () {
      renderUser(null);
    });
  }

  function init() {
    bindAuth();
    bindApi();
    loadAuth();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
