from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from modelos import Contestant, VoteRecord, User
from pymongo import MongoClient, DESCENDING
import redis
import json
from bson import ObjectId
from datetime import datetime, timezone 

class IContestantRepository(ABC):
    @abstractmethod
    def add_contestant(self, contestant: Contestant) -> str: pass
    @abstractmethod
    def get_all(self) -> List[Contestant]: pass
    @abstractmethod
    def get_by_id(self, contestant_id: str) -> Optional[Contestant]: pass
    @abstractmethod
    def clear_all(self): pass 

class IVoteRepository(ABC):
    @abstractmethod
    def register_vote_document(self, vote: VoteRecord) -> bool: pass
    @abstractmethod
    def has_user_voted_for(self, user_id: str, contestant_id: str) -> bool: pass
    @abstractmethod
    def clear_all(self): pass

class IRankingRepository(ABC):
    @abstractmethod
    def increment_vote(self, contestant_id: str) -> int: pass
    @abstractmethod
    def get_total_votes(self, contestant_id: str) -> int: pass
    @abstractmethod
    def get_all_votes(self) -> Dict[str, int]: pass
    @abstractmethod
    def get_system_total_votes(self) -> int: pass
    @abstractmethod
    def clear_all(self): pass

class IUserRepository(ABC):
    @abstractmethod
    def get_user_by_username(self, username: str) -> Optional[User]: pass
    @abstractmethod
    def create_user(self, user: User) -> str: pass

class MongoContestantRepository(IContestantRepository):
    def __init__(self, db):
        self.collection = db.contestants

    def add_contestant(self, contestant: Contestant) -> str:
        data = contestant.model_dump(exclude=['id'])
        data['initial_votes'] = 0 
        result = self.collection.insert_one(data)
        return str(result.inserted_id)

    def get_all(self) -> List[Contestant]:
        contestants = []
        for doc in self.collection.find():
            try:
                doc['_id'] = str(doc['_id'])
                contestants.append(Contestant(**doc))
            except Exception as e:
                print(f"⚠️ ADVERTENCIA: Se ignoró un documento corrupto o antiguo en Mongo (ID: {doc.get('_id')}). Error: {e}")
        return contestants

    def get_by_id(self, contestant_id: str) -> Optional[Contestant]:
        try:
            doc = self.collection.find_one({"_id": ObjectId(contestant_id)})
            if doc:
                doc['_id'] = str(doc['_id'])
                return Contestant(**doc)
        except:
            pass
        return None
    
    def clear_all(self):
        self.collection.delete_many({})

class MongoVoteRepository(IVoteRepository):
    def __init__(self, db):
        self.collection = db.votes
        self.collection.create_index([("user_id", 1), ("contestant_id", 1)], unique=True)

    def register_vote_document(self, vote: VoteRecord) -> bool:
        try:
            vote_data = vote.model_dump()
            
            vote_data['timestamp'] = datetime.now(timezone.utc)
            
            self.collection.insert_one(vote_data)
            return True
        except Exception as e:
            print(f"Error registrando voto en Mongo: {e}")
            return False

    def has_user_voted_for(self, user_id: str, contestant_id: str) -> bool:
        return self.collection.find_one({"user_id": user_id, "contestant_id": contestant_id}) is not None
    
    def clear_all(self):
        self.collection.delete_many({})

class RedisRankingRepository(IRankingRepository):
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.TOTAL_SYSTEM_VOTES_KEY = "system:total_votes"

    def increment_vote(self, contestant_id: str) -> int:
        pipe = self.redis.pipeline()
        pipe.incr(f"contestant:{contestant_id}:votes")
        pipe.incr(self.TOTAL_SYSTEM_VOTES_KEY)
        results = pipe.execute()
        return results[0] 

    def get_total_votes(self, contestant_id: str) -> int:
        votes = self.redis.get(f"contestant:{contestant_id}:votes")
        return int(votes) if votes else 0

    def get_all_votes(self) -> Dict[str, int]:
        keys = self.redis.keys("contestant:*:votes")
        result = {}
        for key in keys:
            parts = key.split(":")
            if len(parts) >= 2:
                 contestant_id = parts[1]
                 val = self.redis.get(key)
                 result[contestant_id] = int(val) if val else 0
        return result

    def get_system_total_votes(self) -> int:
        total = self.redis.get(self.TOTAL_SYSTEM_VOTES_KEY)
        return int(total) if total else 0
    
    def clear_all(self):
        self.redis.flushdb()

class MongoUserRepository(IUserRepository):
    def __init__(self, db):
        self.collection = db.users

    def get_user_by_username(self, username: str) -> Optional[User]:
        doc = self.collection.find_one({"username": username})
        if doc:
            return User(**doc)
        return None

    def create_user(self, user: User) -> str:
        res = self.collection.update_one(
            {"username": user.username}, 
            {"$set": user.model_dump()}, 
            upsert=True
        )
        return str(res.upserted_id) if res.upserted_id else "updated"