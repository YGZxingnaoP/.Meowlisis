// .phone 手机界面逻辑
// 功能：按住说话（录音 -> 16k mono int16 PCM -> /api/audio/send）
//       文字对话（/api/chat）、轮询 AI 回复（/api/chatreply）

(function () {
  'use strict';

  // ---------------- 用户昵称（localStorage 记忆，可随时点击修改） ----------------
  var NAME_KEY = 'phone_username';
  var USERNAME = localStorage.getItem(NAME_KEY) || '手机用户';
  var nameFirstRun = !localStorage.getItem(NAME_KEY);

  // 清洗并保存昵称：去首尾空白、压多余空格、限长 20，空名不保存返回 false
  function setUsername(name) {
    name = String(name || '').trim().replace(/\s+/g, ' ').slice(0, 20);
    if (!name) return false;
    USERNAME = name;
    try { localStorage.setItem(NAME_KEY, name); } catch (e) {}
    return true;
  }

  var chatBox = document.getElementById('chatBox');
  var holdBtn = document.getElementById('holdBtn');
  var textInput = document.getElementById('textInput');
  var sendBtn = document.getElementById('sendBtn');

  // 对话区折叠相关 DOM
  var chatZone = document.getElementById('chatZone');
  var chatToggle = document.getElementById('chatToggle');
  var ctArrow = document.getElementById('ctArrow');
  var ctText = document.getElementById('ctText');
  var CHAT_KEY = 'phone_chat_collapsed';

  // 昵称/缩放控件 DOM
  var nameTag = document.getElementById('nameTag');
  var nameValue = document.getElementById('nameValue');
  var nameInput = document.getElementById('nameInput');
  var zoomIn = document.getElementById('zoomIn');
  var zoomOut = document.getElementById('zoomOut');
  var zoomReset = document.getElementById('zoomReset');

  // ---------------- 消息显示 ----------------
  function addMsg(who, text) {
    if (!text) return;
    var div = document.createElement('div');
    div.className = 'msg ' + who;
    div.textContent = String(text);
    if (who === 'ai') {
      var btn = document.createElement('button');
      btn.className = 'msg-play-btn';
      btn.textContent = '🔊';
      btn.title = '播放语音';
      btn.addEventListener('click', function () {
        playTts(String(text));
      });
      div.appendChild(btn);
    }
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
  }

  // ---------------- 昵称显示与编辑 ----------------
  var lastExitTs = 0; // 上次退出编辑的时间戳（防 blur→click 重开编辑）

  function renderName() {
    if (nameValue) nameValue.textContent = USERNAME;
  }

  function enterEdit() {
    if (!nameTag) return;
    nameTag.classList.add('editing');
    nameInput.value = '';
    nameInput.placeholder = '输入昵称（当前：' + USERNAME + '），回车确认';
    nameInput.focus();
  }

  function exitEdit(save) {
    if (!nameTag) return;
    if (!nameTag.classList.contains('editing')) return; // 已退出，避免 pointerdown+blur 重复触发
    nameTag.classList.remove('editing');
    lastExitTs = Date.now();
    if (save && setUsername(nameInput.value)) {
      renderName();
      addMsg('sys', '✅ 已切换身份：' + USERNAME);
    }
  }

  function initNameUi() {
    // 点击页面其它区域时结束昵称编辑（保存）
    document.addEventListener('pointerdown', function (e) {
      if (nameTag && nameTag.classList.contains('editing') && !nameTag.contains(e.target)) {
        exitEdit(true);
      }
    });
    if (nameTag) {
      nameTag.addEventListener('click', function () {
        if (nameTag.classList.contains('editing')) return;
        // 刚因 blur 退出时紧跟的 click 不再立即重开编辑
        if (Date.now() - lastExitTs < 350) return;
        enterEdit();
      });
    }
    if (nameInput) {
      nameInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.keyCode === 13) exitEdit(true);
        else if (e.key === 'Escape' || e.keyCode === 27) exitEdit(false);
      });
      nameInput.addEventListener('blur', function () { exitEdit(true); });
      // 编辑态内点击不冒泡到 nameTag，避免重复切换
      nameInput.addEventListener('click', function (e) { e.stopPropagation(); });
    }
    renderName();
  }

  // ---------------- 对话区折叠 / 展开 ----------------
  function setChatCollapsed(collapsed) {
    if (!chatZone) return;
    chatZone.classList.toggle('collapsed', !!collapsed);
    if (ctText) ctText.textContent = collapsed ? '展开对话' : '收起对话';
    if (ctArrow) ctArrow.textContent = collapsed ? '▴' : '▾';
    try { localStorage.setItem(CHAT_KEY, collapsed ? '1' : '0'); } catch (e) {}
  }

  function initChatToggle() {
    var saved = false;
    try { saved = localStorage.getItem(CHAT_KEY) === '1'; } catch (e) {}
    setChatCollapsed(saved);
    if (chatToggle) {
      chatToggle.addEventListener('click', function () {
        setChatCollapsed(!chatZone.classList.contains('collapsed'));
      });
    }
  }

  // ---------------- 桌宠缩放（postMessage 控制 iframe 内桌宠） ----------------
  function petPost(msg) {
    var f = document.getElementById('petFrame');
    if (f && f.contentWindow) {
      msg.source = 'meow-phone';
      try { f.contentWindow.postMessage(msg, '*'); } catch (e) {}
    }
  }

  function initZoomUi() {
    if (zoomIn) zoomIn.addEventListener('click', function () { petPost({ type: 'pet-zoom', dir: 'in' }); });
    if (zoomOut) zoomOut.addEventListener('click', function () { petPost({ type: 'pet-zoom', dir: 'out' }); });
    if (zoomReset) zoomReset.addEventListener('click', function () { petPost({ type: 'pet-reset' }); });
  }

  // ============ 常驻播放器：<audio> 元素 + 用户点击激活（iOS 系统"正在播放"识别方式） ============
  // 声音由 WebAudio 合成 → MediaStreamDestination 流 → 常驻 <audio>.srcObject 播放。
  // 点「🔊 开启播放器」= 在用户手势里 audio.play() → iOS 把该 <audio> 当成系统播放器：
  // 控制中心/锁屏出现"正在播放"，且一直保持（流内恒有数据，不会空闲收起）。
  var player = {
    ctx: null,      // 声音合成上下文（WebAudio）
    dest: null,     // MediaStreamDestination：所有声音的唯一输出口
    audio: null,    // 常驻 <audio id="phoneAudio">：播放 dest 的流
    on: false,      // 是否已开启
    _until: 0,      // 🔊 整句试听排队时间游标
    _idleSrc: null,
    keepTimer: null,
    boot: function () {            // 必须在按钮点击（用户手势）里调用
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) { addMsg('sys', '浏览器不支持 AudioContext'); return false; }
      try {
        if (!this.ctx) this.ctx = new AC();
        if (!this.dest) this.dest = this.ctx.createMediaStreamDestination();
        if (!this.audio) this.audio = document.getElementById('phoneAudio');
        if (!this.audio) { this.audio = new Audio(); document.body.appendChild(this.audio); }
        if (this.audio.srcObject !== this.dest.stream) this.audio.srcObject = this.dest.stream;
        // 手势内 play()：iOS 把该 <audio> 识别为系统"正在播放"的媒体
        var p = this.audio.play();
        if (p && p.catch) p.catch(function () { addMsg('sys', '播放器启动失败，请再点一次'); });
        this._idle();              // 流内永远有数据，防止 iOS 判定空闲收起播放器
        try {                      // 控制中心/锁屏显示播放器信息（尽力而为）
          if (navigator.mediaSession && window.MediaMetadata) {
            navigator.mediaSession.metadata =
              new MediaMetadata({ title: 'Meowlisis 手机端', artist: 'AI 语音' });
          }
        } catch (e) {}
        if (this.ctx.state === 'suspended') this.ctx.resume();
        this.on = true;
        this.startKeepAlive();
        return true;
      } catch (e) {
        addMsg('sys', '开启播放器失败：' + e.message);
        return false;
      }
    },
    _idle: function () {           // 0.25s 循环静音源挂在流上（听不见，仅保持媒体流活跃）
      if (this._idleSrc) return;
      try {
        var ctx = this.ctx;
        var buf = ctx.createBuffer(1, Math.max(1, Math.floor(ctx.sampleRate * 0.25)), ctx.sampleRate);
        var src = ctx.createBufferSource();
        src.buffer = buf;
        src.loop = true;
        src.connect(this.dest);
        src.start(0);
        this._idleSrc = src;
      } catch (e) {}
    },
    out: function () {             // 所有声音的接线口：WebAudio 声源连这里进流
      return this.dest;
    },
    playBuffer: function (audioBuf) {  // 🔊 整句试听（已解码 AudioBuffer）
      var ctx = this.ctx, dest = this.dest;
      if (!ctx || !dest || !audioBuf) return;
      try {
        var src = ctx.createBufferSource();
        src.buffer = audioBuf;
        src.connect(dest);
        var t = Math.max(this._until, ctx.currentTime + 0.02);
        if (t < ctx.currentTime - 0.2) t = ctx.currentTime + 0.02;
        src.start(t);
        this._until = t + audioBuf.duration;
      } catch (e) {}
    },
    startKeepAlive: function () {  // 每 10s：context 被挂起就恢复；audio 被系统暂停就续播
      var self = this;
      if (this.keepTimer) return;
      this.keepTimer = setInterval(function () {
        if (self.ctx && self.ctx.state === 'suspended') {
          try { self.ctx.resume(); } catch (e) {}
        }
        if (self.audio && self.audio.paused) {
          var p = self.audio.play();
          if (p && p.catch) p.catch(function () {});
        }
      }, 10000);
    }
  };

  // ---------------- TTS 整句试听（🔊 按钮）→ 走常驻播放器 ----------------
  function playTts(text) {
    if (!text) return;
    if (!player.on) {
      addMsg('sys', '请先点「🔊 开启播放器」再试听');
      return;
    }
    fetch('/api/tts?text=' + encodeURIComponent(text))
      .then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.arrayBuffer();
      })
      .then(function (ab) {
        if (player.ctx && typeof player.ctx.decodeAudioData === 'function') {
          return player.ctx.decodeAudioData(ab);
        }
        throw new Error('播放器未就绪');
      })
      .then(function (audioBuf) {
        player.playBuffer(audioBuf);
      })
      .catch(function (err) {
        addMsg('sys', '语音合成失败：' + err.message);
      });
  }

  // ---------------- 解析主程序返回的 "({...})" ----------------
  function parseReply(s) {
    if (!s) return null;
    s = String(s).trim();
    if (s.charAt(0) === '(') s = s.slice(1);
    if (s.charAt(s.length - 1) === ')') s = s.slice(0, -1);
    try {
      return JSON.parse(s);
    } catch (e) {
      return null;
    }
  }

  // ---------------- 文字对话 ----------------
  function sendText() {
    var text = textInput.value.trim();
    if (!text) return;
    // 对话若处于折叠态，发消息时自动展开（便于看到自己的消息与 AI 回复）
    if (chatZone && chatZone.classList.contains('collapsed')) setChatCollapsed(false);

    textInput.value = '';
    addMsg('user', text);
    // source=phone：手机消息标记来源（回复语音不本地播放、推回手机）
    fetch('/api/chat?text=' + encodeURIComponent(text)
          + '&username=' + encodeURIComponent(USERNAME)
          + '&source=phone')
      .then(function (resp) {
        if (resp.ok) return;
        // 代理失败（主程序未启动等）：回读错误信息给用户可见提示
        return resp.text().then(function (body) {
          var msg = '发送失败（HTTP ' + resp.status + '）';
          try {
            var d = JSON.parse(body);
            if (d && d.message) msg = d.message;
          } catch (e) {}
          throw new Error(msg);
        });
      })
      .catch(function (err) {
        addMsg('sys', '发送失败：' + (err && err.message ? err.message : '网络异常，请重试'));
      });
  }

  sendBtn.addEventListener('click', sendText);
  textInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.keyCode === 13) sendText();
  });

  // ---------------- 轮询 AI 回复文字 ----------------
  setInterval(function () {
    fetch('/api/chatreply')
      .then(function (r) { return r.text(); })
      .then(function (raw) {
        var data = parseReply(raw);
        if (data && data.content) {
          addMsg('ai', String(data.content).replace(/<br\s*\/?>/gi, '\n'));
        }
      })
      .catch(function () {});
  }, 1000);

  // ---------------- 手机实时语音播放（AI 回复流）→ 全部走常驻播放器 player.ctx ----------------
  var phoneTts = {
    nextStart: 0,
    lastSeq: -1,
    metaText: '',
    sr: 32000,
    timer: null,
    start: function () {
      var self = this;
      if (this.timer) return;
      this.timer = setInterval(function () { self.poll(); }, 200);
    },
    poll: function () {
      var self = this;
      fetch('/api/tts/pending?seq=' + self.lastSeq)
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var meta = d.meta || {};
          var blocks = d.blocks || [];
          if (meta.text) {
            // 有活动句（含刚结束的保留期）：播新块
            if (meta.text !== self.metaText) {
              self.metaText = meta.text;
              if (meta.sample_rate) { self.sr = meta.sample_rate; }
              // 播放器已开启且本地积压明显时软对齐，避免滞后连播
              if (player.ctx && self.nextStart > player.ctx.currentTime + 0.3) {
                self.nextStart = player.ctx.currentTime + 0.05;
              }
            }
            for (var i = 0; i < blocks.length; i++) {
              var b = blocks[i];
              if (b.seq > self.lastSeq) { self.schedule(b.pcm); self.lastSeq = b.seq; }
            }
          } else {
            // 无活动句：丢弃历史残留块（防进入页面播旧音频），只推进游标
            self.metaText = '';
            if (blocks.length) { self.lastSeq = blocks[blocks.length - 1].seq; }
          }
        })
        .catch(function () {});
    },
    schedule: function (pcmB64) {
      var ctx = player.ctx;
      if (!ctx || !player.dest || !pcmB64) return;   // 播放器未开启：跳过（开启后从新句开始播）
      try {
        if (ctx.state === 'suspended') { ctx.resume(); }
        var bin = atob(pcmB64);
        var n = bin.length / 2;
        var f = new Float32Array(n);
        for (var i = 0; i < n; i++) {
          var s = bin.charCodeAt(i * 2) | (bin.charCodeAt(i * 2 + 1) << 8);
          if (s > 32767) s -= 65536;
          f[i] = s / 32768;
        }
        var buf = ctx.createBuffer(1, n, this.sr || 32000);
        buf.copyToChannel(f, 0);
        var src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(player.out());   // 接入常驻播放器流（MediaStream → <audio>）
        var t = Math.max(this.nextStart, ctx.currentTime + 0.02);
        // 落后过多（如切后台回来）：丢弃迟到内容，避免追赶爆音
        if (t < ctx.currentTime - 0.2) {
          this.nextStart = ctx.currentTime + 0.02;
          t = this.nextStart;
        }
        src.start(t);
        this.nextStart = t + n / (this.sr || 32000);
      } catch (e) {}
    },
    pause: function () { var c = player.ctx; if (c && c.state === 'running') c.suspend(); },
    resume: function () { var c = player.ctx; if (c && c.state === 'suspended') c.resume(); }
  };
  phoneTts.start();

  // 语音识别回显：手机按住说话的内容，从主项目用户字幕轮询显示
  setInterval(function () {
    fetch('/api/phone/audio')
      .then(function (r) { return r.text(); })
      .then(function (raw) {
        var data = parseReply(raw);
        if (data && data.text) {
          addMsg('user', String(data.text));
        }
      })
      .catch(function () {});
  }, 500);

  // ---------------- 录音：getUserMedia -> PCM -> /api/audio/send ----------------
  var recording = false;
  var audioContext = null;
  var stream = null;
  var processor = null;
  var sendChain = Promise.resolve();
  var audioErrShown = false;

  function floatTo16(f32) {
    var pcm = new Int16Array(f32.length);
    for (var i = 0; i < f32.length; i++) {
      var s = Math.max(-1, Math.min(1, f32[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return pcm.buffer;
  }

  // 线性插值重采样到 16k
  function resample(f32, fromRate, toRate) {
    if (fromRate === toRate) return f32;
    var ratio = fromRate / toRate;
    var out = new Float32Array(Math.round(f32.length / ratio));
    for (var i = 0; i < out.length; i++) {
      var idx = i * ratio;
      var i0 = Math.floor(idx);
      var i1 = Math.min(i0 + 1, f32.length - 1);
      var frac = idx - i0;
      out[i] = f32[i0] * (1 - frac) + f32[i1] * frac;
    }
    return out;
  }

  function doSend(buf) {
    sendChain = sendChain.then(function () {
      return fetch('/api/audio/send?username=' + encodeURIComponent(USERNAME),
                   { method: 'POST', body: buf })
        .then(function (r) {
          if (!r.ok && !audioErrShown) {
            audioErrShown = true;
            addMsg('sys', '语音识别未就绪（SenseVoice 未启动），请改用文字输入');
          }
        })
        .catch(function () {
          if (!audioErrShown) {
            audioErrShown = true;
            addMsg('sys', '语音发送失败，请确认电脑端 api.py 已启动');
          }
        });
    });
  }

  function sendPcmChunk(f32) {
    doSend(floatTo16(f32));
  }

  function startRecord() {
    if (recording) return;
    recording = true;
    phoneTts.pause();   // 说话期间暂停播放器（松开会自动恢复）

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      addMsg('sys', '当前浏览器不支持麦克风，请用文字输入');
      recording = false;
      phoneTts.resume();
      return;
    }

    navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    }).then(function (s) {
      if (!recording) {
        s.getTracks().forEach(function (t) { t.stop(); });
        phoneTts.resume();
        return;
      }
      stream = s;
      var AC = window.AudioContext || window.webkitAudioContext;
      audioContext = new AC();
      var source = audioContext.createMediaStreamSource(stream);
      processor = audioContext.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = function (e) {
        var input = e.inputBuffer.getChannelData(0);
        var sr = audioContext.sampleRate;
        var f32 = (sr === 16000) ? input : resample(input, sr, 16000);
        sendPcmChunk(f32);
      };
      // 连到静音节点，保证 onaudioprocess 被触发且不产生回声
      var mute = audioContext.createGain();
      mute.gain.value = 0;
      source.connect(processor);
      processor.connect(mute);
      mute.connect(audioContext.destination);

      holdBtn.classList.add('recording');
      holdBtn.textContent = '松开结束';
    }).catch(function (err) {
      recording = false;
      phoneTts.resume();
      addMsg('sys', '无法使用麦克风：' + (err && err.message ? err.message : err));
      addMsg('sys', '提示：需用 https 访问本页，并在浏览器中允许麦克风权限');
    });
  }

  function stopRecord() {
    if (!recording) return;
    recording = false;
    phoneTts.resume();  // 松开恢复手机 AI 语音播放
    holdBtn.classList.remove('recording');
    holdBtn.textContent = '按住说话';
    try {
      if (processor) { processor.disconnect(); processor = null; }
      if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
      if (audioContext) { audioContext.close(); audioContext = null; }
    } catch (e) {}
    // 结束信号排在音频块之后发送：先收齐整句，服务端再执行 flush+判停
    sendChain = sendChain.then(function () {
      return fetch('/api/audio/end', { method: 'POST' }).catch(function () {});
    });
    addMsg('sys', '🎤 语音已发送');
  }

  // 用 pointer 事件统一触屏与鼠标
  holdBtn.addEventListener('pointerdown', function (e) {
    e.preventDefault();
    startRecord();
  });
  holdBtn.addEventListener('pointerup', stopRecord);
  holdBtn.addEventListener('pointercancel', stopRecord);

  // ---------------- 常驻播放器按钮（注册一次，一直开着） ----------------
  var playerBtn = document.getElementById('playerBtn');
  if (playerBtn) {
    playerBtn.addEventListener('click', function () {
      if (player.boot()) {
        playerBtn.classList.add('on');
        playerBtn.textContent = '🔊 播放器已开启';
        player.startKeepAlive();
        addMsg('sys', '🔊 播放器已开启，AI 语音将持续播放');
      }
    });
  }

  // ---------------- 初始化 ----------------
  initNameUi();
  initZoomUi();
  initChatToggle();

  // 首次访问：仅文字引导点击昵称改名。不再自动弹出昵称编辑框，
  // 避免焦点落在昵称框导致"打字/回车进了昵称框、消息发不出去"的误操作。
  if (nameFirstRun) {
    setTimeout(function () {
      addMsg('sys', '💬 首次使用：点上方「我是 手机用户」即可改昵称');
    }, 600);
  }
})();
