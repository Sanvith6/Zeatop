import asyncio
import json
import logging
from typing import List
from fastapi import WebSocket, WebSocketDisconnect
from app.db.redis import redis_client

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manages active WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client disconnected. Remaining clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return
            
        data = json.dumps(message)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except Exception:
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

async def redis_pubsub_listener():
    """Background task to listen for incident updates in Redis and broadcast them."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("incidents:updates")
    logger.info("Started Redis Pub/Sub listener for 'incidents:updates'")
    
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    payload = json.loads(message["data"])
                    await manager.broadcast(payload)
                except Exception as e:
                    logger.error(f"Error broadcasting message: {e}")
    finally:
        await pubsub.unsubscribe("incidents:updates")
