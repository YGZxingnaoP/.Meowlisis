// .phone 手机界面逻辑
// 功能：按住说话（录音 -> 16k mono int16 PCM -> /api/audio/send）
//       文字对话（/api/chat）、轮询 AI 回复（/api/chatreply）

(function () {
  'use strict';

  // 手机用户昵称（可自行修改）
  var USERNAME = '手机用户';

  var chatBox = document.getElementById('chatBox');
  var holdBtn = document.getElementById('holdBtn');
  var textInput = document.getElementById('textInput');
  var sendBtn = document.getElementById('sendBtn');

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

  // ---------------- TTS 音频播放 ----------------
  var audioPlayer = null;
  function playTts(text) {
    if (!text) return;
    fetch('/api/tts?text=' + encodeURIComponent(text))
      .then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.blob();
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        if (audioPlayer) { audioPlayer.pause(); }
        audioPlayer = new Audio(url);
        audioPlayer.play();
        audioPlayer.onended = function () { URL.revokeObjectURL(url); };
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
    textInput.value = '';
    addMsg('user', text);
    fetch('/api/chat?text=' + encodeURIComponent(text) + '&username=' + encodeURIComponent(USERNAME))
      .then(function () {})
      .catch(function () {
        addMsg('sys', '发送失败：请确认电脑端 api.py 已启动');
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
      return fetch('/api/audio/send', { method: 'POST', body: buf })
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

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      addMsg('sys', '当前浏览器不支持麦克风，请用文字输入');
      recording = false;
      return;
    }

    navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    }).then(function (s) {
      if (!recording) {
        s.getTracks().forEach(function (t) { t.stop(); });
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
      addMsg('sys', '无法使用麦克风：' + (err && err.message ? err.message : err));
      addMsg('sys', '提示：需用 https 访问本页，并在浏览器中允许麦克风权限');
    });
  }

  function stopRecord() {
    if (!recording) return;
    recording = false;
    holdBtn.classList.remove('recording');
    holdBtn.textContent = '按住说话';
    try {
      if (processor) { processor.disconnect(); processor = null; }
      if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
      if (audioContext) { audioContext.close(); audioContext = null; }
    } catch (e) {}
    addMsg('sys', '🎤 语音已发送');
  }

  // 用 pointer 事件统一触屏与鼠标
  holdBtn.addEventListener('pointerdown', function (e) {
    e.preventDefault();
    startRecord();
  });
  holdBtn.addEventListener('pointerup', stopRecord);
  holdBtn.addEventListener('pointercancel', stopRecord);
})();
