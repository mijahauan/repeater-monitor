import asyncio
import logging
from typing import Dict, Any, Callable
from ka9q.types import Encoding
from ka9q.control import RadiodControl

logger = logging.getLogger(__name__)

class RadioController:
    def __init__(self, radiod_host: str = "airspy-status.local"):
        self.radiod_host = radiod_host
        self.control = None
        self.active_channels = {} # SSRC -> {freq_hz, is_active}
        self.squelch_threshold = 10.0 # dB Default
        self.on_activity_change: Callable[[int, bool, float], None] = None
        
    async def connect(self):
        """Connects to radiod via its status multicast address."""
        try:
            self.control = RadiodControl(self.radiod_host)
            self.control.parent = self # Link back for state access
            logger.info(f"Connected to radiod at {self.radiod_host}")
        except Exception as e:
            logger.error(f"Failed to connect to radiod: {e}")
            raise

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
            
            cmdbuffer = bytearray()
            cmdbuffer.append(CMD)
            
            encode_double(cmdbuffer, StatusType.RADIO_FREQUENCY, center_freq_hz)
            encode_int(cmdbuffer, StatusType.OUTPUT_SSRC, 0)
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

        # Clear existing channels
        for ssrc in list(self.active_channels.keys()):
            try:
                self.control.set_frequency(ssrc, 0)
            except Exception:
                pass
        self.active_channels.clear()

        # Create new channels — fire-and-forget, ka9q-python manages the rest
        for rep in repeaters:
            try:
                freq_hz = float(rep.get("Downlink", rep.get("freq", 0))) * 1e6
                
                ssrc = self.control.create_channel(
                    frequency_hz=freq_hz,
                    preset="nfm",
                    sample_rate=12000,
                    encoding=Encoding.OPUS
                )
                
                self.active_channels[ssrc] = {
                    "freq_hz": freq_hz,
                    "is_active": False
                }
                logger.info(f"Created channel SSRC {ssrc} for {freq_hz/1e6} MHz")
            except Exception as e:
                logger.error(f"Failed to create channel for repeater {rep}: {e}")

    async def close(self):
        if self.control:
            for ssrc in self.active_channels:
                try:
                    self.control.set_frequency(ssrc, 0)
                except:
                    pass
            self.control.close()
