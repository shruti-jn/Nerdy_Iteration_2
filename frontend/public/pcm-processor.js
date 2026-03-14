/**
 * AudioWorklet processor: converts float32 input samples to PCM Int16 and
 * posts them as transferable ArrayBuffer chunks back to the main thread.
 *
 * Target: 16 kHz mono (browser resamples via AudioContext.sampleRate config).
 * Chunk size: 4096 samples ≈ 256 ms at 16 kHz — small enough for low latency,
 * large enough to avoid excessive WebSocket frame overhead.
 */
class PcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Int16Array(4096);
    this._offset = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const samples = input[0]; // Float32Array, mono channel
    for (let i = 0; i < samples.length; i++) {
      // Clamp to [-1, 1] then scale to Int16 range
      const s = Math.max(-1, Math.min(1, samples[i]));
      this._buffer[this._offset++] = s < 0 ? s * 0x8000 : s * 0x7fff;

      if (this._offset >= this._buffer.length) {
        // Transfer the buffer to avoid a copy
        const out = this._buffer.buffer.slice(0);
        this.port.postMessage(out, [out]);
        this._buffer = new Int16Array(4096);
        this._offset = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-processor", PcmProcessor);
