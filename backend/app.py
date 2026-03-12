import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from backend.repeater_data import load_local_data, get_coordinates_from_input, get_repeaters_in_range
from backend.radio_controller import RadioController
from backend.audio_streamer import streamer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

controller = RadioController()
active_websockets = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application startup...")
    load_local_data()
    await controller.connect()
    
    # Setup activity callback from radio_controller
    def broadcast_activity(freq_hz: float, is_active: bool, snr: float):
        msg = {
            "type": "activity",
            "freq": freq_hz,
            "isActive": is_active,
            "snr": snr
        }
        # Run in event loop
        try:
            loop = asyncio.get_running_loop()
            for ws in active_websockets:
                 asyncio.run_coroutine_threadsafe(ws.send_json(msg), loop)
        except RuntimeError:
            pass

    controller.on_activity_change = broadcast_activity
    await controller.start_listener()
    
    yield
    
    # Shutdown
    logger.info("Application shutdown...")
    streamer.close_all()
    await controller.close()

app = FastAPI(lifespan=lifespan)

# Mount frontend directory for static files (HTML/JS/CSS)
app.mount("/static", StaticFiles(directory="/home/mjh/git/repeater-monitor/frontend"), name="static")

@app.get("/")
async def get_index():
    with open("/home/mjh/git/repeater-monitor/frontend/index.html", "r") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws/control")
async def websocket_control(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "search":
                # Handle Grid Square / Location Search
                loc = data.get("location")
                band = data.get("band", "2m") # 2m, 1.25m, 70cm
                squelch_db = float(data.get("squelch", 10.0))
                radius_km = float(data.get("radius", 150.0))
                radiod_host = data.get("radiod_host", "airspy-status.local")
                
                if controller.radiod_host != radiod_host:
                    logger.info(f"Reconnecting radio controller to new host: {radiod_host}")
                    await controller.close()
                    controller.radiod_host = radiod_host
                    streamer.radiod_host = radiod_host
                    await controller.connect()
                    await controller.start_listener()
                
                lat, lon = get_coordinates_from_input(loc)
                if lat is None or lon is None:
                    await websocket.send_json({"type": "error", "message": "Invalid Grid Square or Lat,Lon format"})
                    continue
                
                # Default 5 MHz band segments based on US allocations
                band_ranges = {
                    "2m": (144.0, 148.0),       # 2m
                    "1.25m": (222.0, 225.0),    # 1.25m
                    "70cm_1": (420.0, 425.0),
                    "70cm_2": (425.0, 430.0),
                    "70cm_3": (430.0, 435.0),
                    "70cm_4": (435.0, 440.0),
                    "70cm_5": (440.0, 445.0),
                    "70cm_6": (445.0, 450.0),
                }
                segment = band_ranges.get(band, band_ranges["2m"])
                center_freq_hz = ((segment[0] + segment[1]) / 2.0) * 1e6
                
                controller.set_squelch(squelch_db)
                controller.tune_band(center_freq_hz)

                # Fetch and filter repeaters
                all_reps = load_local_data()
                filtered = get_repeaters_in_range(all_reps, lat, lon, radius_km=radius_km, band_segment=segment)
                
                # Reply to frontend instantly so the map populates
                await websocket.send_json({
                    "type": "results",
                    "repeaters": filtered,
                    "lat": lat,
                    "lon": lon
                })
                
                # Start Monitoring in a completely detached background task
                asyncio.create_task(asyncio.to_thread(controller.monitor_repeaters, filtered))
                
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in active_websockets:
            active_websockets.remove(websocket)

@app.websocket("/ws/audio/{freq_hz}")
async def websocket_audio(websocket: WebSocket, freq_hz: float):
    """WebSocket endpoint explicitly for streaming binary audio frames to the browser"""
    await websocket.accept()
    await streamer.add_listener(freq_hz, websocket, controller.control)
    try:
        # Keep connection open until client disconnects
        while True:
            await websocket.receive_text() # Client won't send anything usually, but keeps loop alive
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Audio WS error: {e}")
    finally:
        await streamer.remove_listener(freq_hz, websocket)

if __name__ == "__main__":
    import uvicorn
    # Add project root to path before running if executing directly
    uvicorn.run(
        "backend.app:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        ssl_keyfile="/home/mjh/git/repeater-monitor/certs/key.pem",
        ssl_certfile="/home/mjh/git/repeater-monitor/certs/cert.pem"
    )
