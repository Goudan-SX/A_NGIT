/* Guardian-AI 单人聊天测试页：本地模拟对方回复，供浏览器插件抓取。 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var messages = [];
  var timer = null;

  var SCENARIOS = {
    normal: {
      replies: [
        '在的，怎么啦？',
        '周末有空吗，一起去打球？',
        '好呀，到时候再约时间。'
      ]
    },
    game: {
      replies: [
        '我这边有免费游戏皮肤，加我 QQ 就能领。',
        '你先把屏幕共享打开，我教你操作，不然领不了。',
        '你把验证码告诉我，我帮你解冻账号，马上就要过期了。'
      ]
    },
    sidejob: {
      replies: [
        '刷单返利了解一下，动动手指日赚 300，时间自由。',
        '先垫付一单，完成后本金和佣金马上返给你。',
        '下载会议 App，我远程指导你操作，别告诉家里人。'
      ]
    },
    police: {
      replies: [
        '我是公安局民警，你的账户涉嫌洗钱，需要配合调查。',
        '不要挂电话，也不要告诉任何人，先把钱转到安全账户。',
        '出示警官证给你看，马上把验证码发过来，否则上门抓人。'
      ]
    }
  };

  function pad(value) { return String(value).padStart(2, '0'); }

  function timestamp() {
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
      + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

  function addMessage(role, text, extra) {
    var item = { role: role, text: text || '', timestamp: timestamp() };
    if (extra) {
      Object.keys(extra).forEach(function (key) { item[key] = extra[key]; });
    }
    messages.push(item);
    render();
  }

  function notifyMainImage(file, dataUrl) {
    var payload = {
      type: 'chat-image',
      id: 'chat-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8),
      dataUrl: dataUrl,
      name: file.name || '聊天图片.png',
      timestamp: timestamp()
    };
    try {
      localStorage.setItem('guardian_pending_chat_image', JSON.stringify(payload));
    } catch (error) {
      /* ignore storage quota */
    }
    if ('BroadcastChannel' in window) {
      try {
        var channel = new BroadcastChannel('guardian-ai-media');
        channel.postMessage(payload);
        channel.close();
      } catch (error) {
        /* ignore */
      }
    }
    var alive = Number(localStorage.getItem('guardian_main_alive') || 0);
    if (Date.now() - alive > 6000) {
      window.open('/', '_blank');
    }
  }

  function sendImage(file) {
    if (!file || file.type.indexOf('image/') !== 0) {
      alert('请选择图片文件');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      alert('图片不能超过 10 MB');
      return;
    }
    var reader = new FileReader();
    reader.onload = function () {
      var dataUrl = String(reader.result || '');
      addMessage('self', '', { type: 'image', dataUrl: dataUrl, name: file.name || '聊天图片.png' });
      notifyMainImage(file, dataUrl);
      scheduleReply();
    };
    reader.readAsDataURL(file);
  }

  function render() {
    var log = $('single-chat-log');
    log.innerHTML = '';
    messages.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'chat-row' + (item.role === 'self' ? ' chat-row--self' : '');
      var meta = document.createElement('div');
      meta.className = 'chat-row__meta';
      meta.textContent = (item.role === 'self' ? '你' : '对方') + ' · ' + item.timestamp;
      var bubble = document.createElement('div');
      bubble.className = 'chat-bubble';
      if (item.type === 'image' && item.dataUrl) {
        bubble.classList.add('chat-bubble--image');
        var image = document.createElement('img');
        image.className = 'chat-image';
        image.src = item.dataUrl;
        image.alt = item.name || '聊天图片';
        bubble.appendChild(image);
      } else {
        bubble.textContent = item.text;
      }
      row.appendChild(meta);
      row.appendChild(bubble);
      log.appendChild(row);
    });
    log.scrollTop = log.scrollHeight;
  }

  function send() {
    var input = $('single-chat-input');
    var text = input.value.trim();
    if (!text) return;
    addMessage('self', text);
    input.value = '';
    input.focus();
    scheduleReply();
  }

  function scheduleReply() {
    clearTimeout(timer);
    var scenario = SCENARIOS[$('scenario-select').value] || SCENARIOS.normal;
    var reply = scenario.replies[Math.floor(Math.random() * scenario.replies.length)];
    timer = setTimeout(function () { addMessage('peer', reply); }, 850);
  }

  function runDemo() {
    var scenario = SCENARIOS[$('scenario-select').value] || SCENARIOS.normal;
    clearTimeout(timer);
    scenario.replies.forEach(function (text, index) {
      setTimeout(function () { addMessage('peer', text); }, index * 900);
    });
  }

  function reset() {
    clearTimeout(timer);
    messages = [];
    render();
    setTimeout(function () { addMessage('peer', '你好，我是模拟聊天对象。'); }, 250);
  }

  function bind() {
    $('single-chat-send').addEventListener('click', send);
    $('single-chat-input').addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        send();
      }
    });
    $('demo-btn').addEventListener('click', runDemo);
    $('reset-btn').addEventListener('click', reset);
    var imageBtn = $('single-chat-image-btn');
    var imageInput = $('single-chat-image-input');
    if (imageBtn && imageInput) {
      imageBtn.addEventListener('click', function () { imageInput.click(); });
      imageInput.addEventListener('change', function () {
        if (imageInput.files && imageInput.files[0]) sendImage(imageInput.files[0]);
        imageInput.value = '';
      });
    }
    $('scenario-select').addEventListener('change', function () {
      addMessage('peer', '场景已切换，可以发送消息测试。');
    });
    reset();
  }

  bind();
})();
