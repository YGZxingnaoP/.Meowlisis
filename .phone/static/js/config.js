export const MEDIA = {
  videoWidth: 1280,
  videoHeight: 720,
  videoFps: 30,
  videoBitrate: 2000000,
  keyframeSecs: 2,
  h264Codec: 'avc1.42E01E',
  petFit: 0.13
};

export function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
  return proto + location.host + '/ws';
}
