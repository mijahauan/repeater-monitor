import asyncio
import logging
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect
from ka9q import ManagedStream

logger = logging.getLogger(__name__)

class AudioStreamer:
    def __init__(self):
        self.active_streams = {} # freq_hz -> ManagedStream
        self.listeners = {} # freq_hz -> List[WebSocket]

    async def add_listener(self, freq_hz: float, websocket: WebSocket, control):
        """Adds a websocket listener for a specific channel's raw audio packets."""
        if freq_hz not in self.listeners:
            self.listeners[freq_hz] = []
        
        self.listeners[freq_hz].append(websocket)
        logger.info(f"Added listener for frequency {freq_hz}. Total listeners: {len(self.listeners[freq_hz])}")
        
        # Start a stream if not already running for this frequency
        if freq_hz not in self.active_streams:
            if not control:
                logger.error(f"Cannot stream {freq_hz}: RadiodControl instance missing.")
                try:
                    await websocket.close(code=1011, reason="Radio control missing")
                except:
                    pass
                return
            
            # Capture the event loop from the main thread
            loop = asyncio.get_running_loop()
            
            def handle_samples(samples: np.ndarray, quality):
                """Callback invoked by ManagedStream on the background thread"""
                if loop is None or loop.is_closed():
                    return
                # Convert float32 numpy array to raw bytes to send to frontend
                payload = samples.tobytes()
                asyncio.run_coroutine_threadsafe(self.broadcast(freq_hz, payload), loop)

            # Auto-healing ManagedStream abstracts away network interfaces and SSRCs
            stream = ManagedStream(
                control=control,
                frequency_hz=freq_hz,
                preset="nfm",
                sample_rate=12000,
                on_samples=handle_samples,
                deliver_interval_packets=5 # deliver every ~100ms
            )
            stream.start()
            
            self.active_streams[freq_hz] = stream
            logger.info(f"Started ManagedStream for {freq_hz} Hz")

    async def remove_listener(self, freq_hz: float, websocket: WebSocket):
        if freq_hz in self.listeners and websocket in self.listeners[freq_hz]:
            self.listeners[freq_hz].remove(websocket)
            logger.info(f"Removed listener for {freq_hz}. Total listeners: {len(self.listeners[freq_hz])}")
            
            if len(self.listeners[freq_hz]) == 0:
                self.stop_stream(freq_hz)

    async def broadcast(self, freq_hz: float, payload: bytes):
        """Sends the raw audio byte payload to all listening websockets for this frequency."""
        if freq_hz not in self.listeners:
            return
            
        dead_sockets = []
        for ws in self.listeners[freq_hz]:
            try:
                await ws.send_bytes(payload)
            except Exception as e:
                dead_sockets.append(ws)
                
        for ws in dead_sockets:
            await self.remove_listener(freq_hz, ws)

    def stop_stream(self, freq_hz: float):
        """Stops and cleans up the ManagedStream for a frequency."""
        if freq_hz in self.active_streams:
            stream = self.active_streams[freq_hz]
            stream.stop()
            del self.active_streams[freq_hz]
            logger.info(f"Stopped ManagedStream for {freq_hz} Hz")

    def close_all(self):
        for freq_hz in list(self.active_streams.keys()):
            self.stop_stream(freq_hz)
            
streamer = AudioStreamer()

