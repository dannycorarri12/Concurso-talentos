from fastapi import (
    FastAPI, HTTPException, Depends, status, 
    UploadFile, File, Header, Request, Form 
)
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
import redis
import json
from typing import Optional
import os
import traceback
import socketio 
import shutil

from modelos import (
    LoginRequest, LoginResponse, VoteRequest, 
    Contestant, ContestantPublicView, ContestantAdminView, DashboardStats
)
from repositorios import (
    MongoContestantRepository, MongoVoteRepository, RedisRankingRepository, MongoUserRepository
)
from servicios import VotingService, AdminService, AuthService
from socket_manager import sio 

MONGO_URI = "mongodb://localhost:27017"
REDIS_HOST = "localhost"
REDIS_PORT = 6379

fastapi_app = FastAPI(
    title="Concurso de talentos",
    description="Backend para el Proyecto #2 TI4601. Gestiona votaciones usando Mongo y Redis.",
    version="1.4.0"
)

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@fastapi_app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = str(exc)
    tb = traceback.format_exc()
    print(f"🔥 ERROR 500 FATAL EN {request.url.path}:\n{tb}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error_message": error_msg}
    )

if not os.path.exists("static"):
    os.makedirs("static")
fastapi_app.mount("/static", StaticFiles(directory="static"), name="static")

try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_client.server_info()
    mongo_db = mongo_client["talent_competition_db"]
    print(f"✅ MongoDB conectado a {MONGO_URI}")
except Exception as e:
    print(f"❌ ERROR CRÍTICO: No se pudo conectar a MongoDB: {e}")

try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    redis_client.ping()
    print(f"✅ Redis conectado a {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    print(f"❌ ERROR CRÍTICO: No se pudo conectar a Redis: {e}")

contestant_repo = MongoContestantRepository(mongo_db)
vote_repo = MongoVoteRepository(mongo_db)
ranking_repo = RedisRankingRepository(redis_client)
user_repo = MongoUserRepository(mongo_db)

voting_service = VotingService(contestant_repo, vote_repo, ranking_repo)
admin_service = AdminService(contestant_repo, ranking_repo, vote_repo)
auth_service = AuthService(user_repo)

async def require_admin(x_user_id: Optional[str] = Header(None, alias="X-User-ID")):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Header de autenticación faltante")
    user = user_repo.get_user_by_username(x_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no válido")
    if user.role != 'admin':
        raise HTTPException(status_code=403, detail="No tienes permisos de administrador")
    return user


@fastapi_app.get("/")
def health_check():
    return {"status": "online", "db_mongo": "connected", "db_redis": "connected", "socket_io": "enabled"}

@fastapi_app.post("/api/login", response_model=LoginResponse, tags=["Auth"])
def login(request: LoginRequest):
    user = auth_service.login(request.username)
    return LoginResponse(user_id=user.username, username=user.username, role=user.role)

@fastapi_app.get("/api/public/contestants", response_model=list[ContestantPublicView], tags=["Public"])
def get_public_contestants():
    return voting_service.get_contestants_for_public()

@fastapi_app.post("/api/public/vote", tags=["Public"])
async def cast_vote(vote: VoteRequest):
    success = await voting_service.cast_vote(vote.user_id, vote.contestant_id)
    if not success:
        raise HTTPException(status_code=409, detail="Ya has votado por este participante.")
    return {"message": "Voto registrado correctamente"}

@fastapi_app.post("/api/admin/load-initial-data", tags=["Admin"], dependencies=[Depends(require_admin)])
async def load_initial_data(file: UploadFile = File(...)):
    try:
        content = await file.read()
        json_data = json.loads(content)
        admin_service.initialize_database(json_data)
        return {"message": f"Base de datos inicializada con {len(json_data)} participantes."}
    except Exception as e:
        print(f"Error detallado carga JSON: {e}") 
        raise HTTPException(status_code=400, detail=f"Error cargando JSON: {str(e)}")

@fastapi_app.post("/api/admin/contestants", tags=["Admin"], dependencies=[Depends(require_admin)])
async def add_contestant(
    nombre: str = Form(...), 
    categoria: str = Form(...), 
    file: UploadFile = File(...)
):
    """
    Agregar participante con subida de imagen.
    Guarda la imagen en /static y crea el registro en BD.
    """
    try:
        file_location = f"static/{file.filename}"
        
        with open(file_location, "wb+") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        new_contestant = Contestant(
            nombre=nombre,
            categoria=categoria,
            foto=file.filename 
        )

        new_id = admin_service.add_contestant(new_contestant)
        return {"message": "Participante agregado correctamente", "id": new_id, "foto": file.filename}
    
    except Exception as e:
        print(f"Error subiendo archivo: {e}")
        raise HTTPException(status_code=500, detail="Error al guardar el concursante o la imagen")

@fastapi_app.get("/api/admin/dashboard", response_model=list[ContestantAdminView], tags=["Admin Real-time"], dependencies=[Depends(require_admin)])
def get_admin_dashboard():
    return admin_service.get_realtime_dashboard()

@fastapi_app.get("/api/admin/stats", response_model=DashboardStats, tags=["Admin Real-time"], dependencies=[Depends(require_admin)])
def get_system_stats():
    return admin_service.get_system_stats()

@fastapi_app.get("/api/admin/reports/top3", response_model=list[ContestantAdminView], tags=["Admin Reports"], dependencies=[Depends(require_admin)])
def get_top_3_report():
    return admin_service.get_top_3()

@fastapi_app.get("/api/admin/reports/zeros", response_model=list[ContestantAdminView], tags=["Admin Reports"], dependencies=[Depends(require_admin)])
def get_zero_votes_report():
    return admin_service.get_contestants_with_zero_votes()

app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)