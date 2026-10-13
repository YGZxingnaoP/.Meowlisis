class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this._size = 2048;
    this._buf = new Float32Array(this._size);
    this._n = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const chans = input.length;
    const len = input[0].length;
    for (let i = 0; i < len; i++) {
      let v = 0;
      for (let c = 0; c < chans; c++) v += input[c][i];
      this._buf[this._n++] = v / chans;
      if (this._n >= this._size) {
        const out = this._buf.slice(0);
        this.port.postMessage(out, [out.buffer]);
        this._n = 0;
      }
    }
    return true;
  }
}

registerProcessor('pcm-capture', PcmCapture);
