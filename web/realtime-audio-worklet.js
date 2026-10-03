// Continuous mono capture. Integrate samples to 16 kHz and emit 20 ms PCM16 frames.
class ShulianMicrophone extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(320);
    this.index = 0;
    this.weight = 0;
    this.sum = 0;
    this.ratio = sampleRate / 16000;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (const sample of channel) {
      let remaining = 1;
      while (remaining > 1e-8) {
        const take = Math.min(remaining, this.ratio - this.weight);
        this.sum += sample * take;
        this.weight += take;
        remaining -= take;
        if (this.weight >= this.ratio - 1e-8) {
          const value = Math.max(-1, Math.min(1, this.sum / this.ratio));
          this.frame[this.index++] = Math.round(value * (value < 0 ? 32768 : 32767));
          this.weight = 0;
          this.sum = 0;
          if (this.index === 320) {
            this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
            this.frame = new Int16Array(320);
            this.index = 0;
          }
        }
      }
    }
    return true;
  }
}
registerProcessor('shulian-microphone', ShulianMicrophone);
