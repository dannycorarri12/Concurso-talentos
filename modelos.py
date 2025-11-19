from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone

class Contestant(BaseModel):
    id: Optional[str] = Field(None, alias='_id') 
    nombre: str
    categoria: str
    foto: str

class VoteRecord(BaseModel):
    user_id: str
    contestant_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class User(BaseModel):
    username: str
    role: str 

class LoginRequest(BaseModel):
    username: str

class LoginResponse(BaseModel):
    user_id: str
    username: str
    role: str

class VoteRequest(BaseModel):
    user_id: str
    contestant_id: str

class ContestantPublicView(BaseModel):
    id: str
    nombre: str
    categoria: str
    foto: str

class ContestantAdminView(ContestantPublicView):
    total_votes: int

class DashboardStats(BaseModel):
    total_votes_system: int
    votes_by_category: dict[str, int]