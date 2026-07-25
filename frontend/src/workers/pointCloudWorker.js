import { decodePointCloudMessage } from '../utils/pointCloudDecoder.js'

self.onmessage = (event) => {
  const { topic, generation, message, sampleStep } = event.data || {}
  try {
    const decoded = decodePointCloudMessage(message, { sampleStep })
    self.postMessage(
      { topic, generation, decoded },
      [decoded.positions.buffer]
    )
  } catch (error) {
    self.postMessage({
      topic,
      generation,
      decoded: {
        error: error instanceof Error ? error.message : String(error),
        pointCount: 0,
        totalPoints: 0,
        positions: new Float32Array(),
        bounds: null
      }
    })
  }
}
