from typing import List, Dict
from modelos import Contestant, VoteRecord, ContestantPublicView, ContestantAdminView, DashboardStats, User
from repositorios import IContestantRepository, IVoteRepository, IRankingRepository, IUserRepository
from datetime import datetime
from socket_manager import sio 
import json

class VotingService:
    """
    Maneja la lógica de votación pública.
    Orquesta Mongo (para persistencia detallada) 
    y Redis (para contadores rápidos).
    """
    def __init__(self, contestant_repo: IContestantRepository, vote_repo: IVoteRepository, ranking_repo: IRankingRepository):
        self.contestant_repo = contestant_repo
        self.vote_repo = vote_repo
        self.ranking_repo = ranking_repo

    def get_contestants_for_public(self) -> List[ContestantPublicView]:
        contestants = self.contestant_repo.get_all()
        return [
            ContestantPublicView(
                id=c.id, nombre=c.nombre, categoria=c.categoria, foto=c.foto
            ) for c in contestants
        ]

    async def cast_vote(self, user_id: str, contestant_id: str) -> bool:
        # 1. Validar
        if self.vote_repo.has_user_voted_for(user_id, contestant_id):
            return False

        # 2. Registrar en Mongo
        vote_record = VoteRecord(user_id=user_id, contestant_id=contestant_id)
        success_mongo = self.vote_repo.register_vote_document(vote_record)

        if success_mongo:
            new_contestant_total = self.ranking_repo.increment_vote(contestant_id)
            
            system_total = self.ranking_repo.get_system_total_votes()
            
            await sio.emit('VOTE_UPDATE', {
                "type": "VOTE_UPDATE",
                "contestant_id": contestant_id,
                "new_total_votes": new_contestant_total,
                "system_total": system_total
            })
            
            return True
        return False

class AdminService:
    """
    Maneja la gestión y las consultas avanzadas para el administrador.
    """
    def __init__(self, contestant_repo: IContestantRepository, ranking_repo: IRankingRepository, vote_repo: IVoteRepository):
        self.contestant_repo = contestant_repo
        self.ranking_repo = ranking_repo
        self.vote_repo = vote_repo

    def initialize_database(self, json_data: List[dict]):
        self.contestant_repo.clear_all()
        self.ranking_repo.clear_all()
        self.vote_repo.clear_all()
        
        print(f"DEBUG: Iniciando carga de {len(json_data)} items.")
        for i, item in enumerate(json_data):
             nombre = item.get("nombre") or item.get("name")
             categoria = item.get("categoria") or item.get("category")
             foto = item.get("foto") or item.get("photo_url") or item.get("photo")

             if not nombre or not categoria:
                 continue 

             c = Contestant(
                 nombre=nombre,
                 categoria=categoria,
                 foto=foto or "default.png"
             )
             c_id = self.contestant_repo.add_contestant(c)
             self.ranking_repo.redis.set(f"contestant:{c_id}:votes", 0)
        
        self.ranking_repo.redis.set(self.ranking_repo.TOTAL_SYSTEM_VOTES_KEY, 0)
        print("DEBUG: Carga inicial finalizada.")

    def add_contestant(self, contestant: Contestant) -> str:
        new_id = self.contestant_repo.add_contestant(contestant)
        self.ranking_repo.redis.set(f"contestant:{new_id}:votes", 0)
        return new_id

    def get_realtime_dashboard(self) -> List[ContestantAdminView]:
        contestants = self.contestant_repo.get_all()
        dashboard_data = []
        for c in contestants:
            votes = self.ranking_repo.get_total_votes(c.id)
            dashboard_data.append(ContestantAdminView(
                id=c.id, nombre=c.nombre, categoria=c.categoria, foto=c.foto, total_votes=votes
            ))
        return dashboard_data

    def get_top_3(self) -> List[ContestantAdminView]:
        full_data = self.get_realtime_dashboard()
        full_data.sort(key=lambda x: x.total_votes, reverse=True)
        return full_data[:3]

    def get_contestants_with_zero_votes(self) -> List[ContestantAdminView]:
        full_data = self.get_realtime_dashboard()
        return [c for c in full_data if c.total_votes == 0]

    def get_votes_by_category(self) -> Dict[str, int]:
        full_data = self.get_realtime_dashboard()
        category_totals = {}
        for c in full_data:
            category_totals[c.categoria] = category_totals.get(c.categoria, 0) + c.total_votes
        return category_totals

    def get_system_stats(self) -> DashboardStats:
        return DashboardStats(
            total_votes_system=self.ranking_repo.get_system_total_votes(),
            votes_by_category=self.get_votes_by_category()
        )

class AuthService:
    def __init__(self, user_repo: IUserRepository):
        self.user_repo = user_repo

    def login(self, username: str) -> User:
        role = 'admin' if username.lower() == 'admin' else 'public'
        user = User(username=username, role=role)
        self.user_repo.create_user(user)
        return user