import asyncio
import logging
from typing import Dict, Any, Callable
from ka9q.types import Encoding
from ka9q.control import RadiodControl
from ka9q.monitor import ChannelMonitor
from ka9q.addressing import generate_multicast_ip

logger = logging.getLogger(__name__)

class RadioController:
    def __init__(self, radiod_host: str = "airspy-status.local"):
        self.radiod_host = radiod_host
        self.control = None
        self.active_channels = {} # SSRC -> Activity Status Dict
        self.squelch_threshold = 10.0 # dB Default
        self.on_activity_change: Callable[[int, bool, float], None] = None
        self._listener_task = None
        self.channel_monitor = None
        
    async def connect(self):
        """Initializes testing connection to radiod."""
        try:
            # RadiodControl blockingly connects and discovers defaults.
            self.control = RadiodControl(self.radiod_host)
            from ka9q.monitor import ChannelMonitor
            self.channel_monitor = ChannelMonitor(self.control, check_interval=5.0)
            self.channel_monitor.start()
            logger.info(f"Connected to radiod at {self.radiod_host}")
        except Exception as e:
            logger.error(f"Failed to connect to radiod: {e}")
            raise
            
    async def start_listener(self):
        """Starts asynchronous status packet listener."""
        self._listener_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        """Polling alternative since RadiodControl is synchronous"""
        # A true asyncio replacement for discover_channels_native would be better,
        # but for simplicity we will just call a non-blocking recv cycle periodically
        
        from ka9q.discovery import _create_status_listener_socket, resolve_multicast_address
        import socket
        import select
        
        try:
            multicast_addr = resolve_multicast_address(self.radiod_host, timeout=2.0)
            status_sock = _create_status_listener_socket(multicast_addr)
            status_sock.settimeout(0.0) # non-blocking
        except Exception as e:
            logger.error(f"Failed to setup status listener: {e}")
            return

        logger.info("Started background status listener.")
        
        while True:
            ready = select.select([status_sock], [], [], 0.5)
            if ready[0]:
                while True:
                    try:
                        buffer, addr = status_sock.recvfrom(8192)
                        if len(buffer) > 0 and buffer[0] == 0:
                            # It's a STATUS packet wrapper
                            status = self.control._decode_status_response(buffer)
                            ssrc = status.get('ssrc')
                            if ssrc in self.active_channels:
                                snr = status.get('snr', float('-inf'))
                                is_active = snr >= self.squelch_threshold
                                
                                prev_active = self.active_channels[ssrc].get('is_active', False)
                                
                                if is_active != prev_active:
                                    self.active_channels[ssrc]['is_active'] = is_active
                                    if self.on_activity_change:
                                        # Use the tracker to convert SSRC to Frequency
                                        freq_hz = self.active_channels[ssrc]['freq_hz']
                                        self.on_activity_change(freq_hz, is_active, snr)
                                        
                    except BlockingIOError:
                        break # Emptied the buffer
                    except Exception as e:
                        logger.debug(f"Error reading status packet: {e}")
                        break
            
            await asyncio.sleep(0.1)

    def set_squelch(self, threshold_db: float):
        self.squelch_threshold = threshold_db
        logger.info(f"Squelch threshold set to {self.squelch_threshold} dB")

    def tune_band(self, center_freq_hz: float):
        """Tunes the AirspyR2 frontend receiver Center Frequency"""
        if not self.control:
            return
            
        try:
            from ka9q.types import CMD, StatusType
            from ka9q.control import encode_double, encode_int, encode_eol
            import secrets
            
            # Build TLV command packet directly to set global LO frequency (SSRC 0)
            cmdbuffer = bytearray()
            cmdbuffer.append(CMD)  # Command packet type
            
            encode_double(cmdbuffer, StatusType.RADIO_FREQUENCY, center_freq_hz)
            encode_int(cmdbuffer, StatusType.OUTPUT_SSRC, 0) # Apply to frontend/global LO
            encode_int(cmdbuffer, StatusType.COMMAND_TAG, secrets.randbits(31))
            encode_eol(cmdbuffer)

            self.control.send_command(cmdbuffer)
            logger.info(f"Tuned frontend radio center frequency to {center_freq_hz / 1e6} MHz")
        except Exception as e:
            logger.error(f"Failed to tune band: {e}")

    def monitor_repeaters(self, repeaters: list):
        """
        Takes a list of repeaters in the 5MHz block.
        Tears down old channels and spins up new ones.
        """
        if not self.control:
            return

        # Clear existing
        for ssrc in list(self.active_channels.keys()):
            try:
                if self.channel_monitor:
                    self.channel_monitor.unmonitor_channel(ssrc)
                self.control.set_frequency(ssrc, 0)
            except Exception as e:
                pass
        self.active_channels.clear()

        # Create new channels
        for rep in repeaters:
            try:
                freq_hz = float(rep.get("Downlink", rep.get("freq", 0))) * 1e6
                
                # monitor_channel returns the auto-allocated SSRC
                ssrc = self.channel_monitor.monitor_channel(
                    frequency_hz=freq_hz,
                    preset="nfm", # Narrow FM for repeaters
                    sample_rate=12000,
                    encoding=Encoding.OPUS, # efficient over websockets
                    destination=generate_multicast_ip(str(freq_hz))
                )
                
                # Keep SSRC internal only
                self.active_channels[ssrc] = {
                    "freq_hz": freq_hz,
                    "is_active": False
                }
                logger.info(f"Created channel for {freq_hz/1e6} MHz")
            except Exception as e:
                logger.error(f"Failed to create channel for repeater {rep}: {e}")

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
        if self.channel_monitor:
            self.channel_monitor.stop()
        if self.control:
            # Tear down all managed channels
            for ssrc in self.active_channels:
                try:
                    if self.channel_monitor:
                        self.channel_monitor.unmonitor_channel(ssrc)
                    self.control.set_frequency(ssrc, 0)
                except:
                    pass
            self.control.close()
