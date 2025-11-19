import socketio

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

@sio.event
async def connect(sid, environ):
    print(f"✅ Cliente Socket.IO conectado: {sid}")

@sio.event
async def disconnect(sid):
    print(f"❌ Cliente Socket.IO desconectado: {sid}")