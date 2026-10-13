export const MEDIA = {
  videoWidth: 1280,
  videoHeight: 720,
  videoFps: 30,
  videoBitrate: 2000000,
  keyframeSecs: 2,
  h264Codec: 'avc1.42E01E',
  petFit: 0.13,
  // 编码器排队超过这个数就丢帧（背压）
  encMaxQueue: 2,
  // WS 发送积压超过这个字节数就丢帧（约 0.4s 的量）
  sendBudget: 250000
};

export function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
  return proto + location.host + '/ws';
}
