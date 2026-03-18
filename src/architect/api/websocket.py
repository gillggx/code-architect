"""
WebSocket handlers for Code Architect API

Provides real-time progress updates and bi-directional communication.

Version: 1.0
"""

import asyncio
import json
from typing import Dict, Set, Optional
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
import logging


logger = logging.getLogger(__name__)


class WebSocketMessage:
    """WebSocket message structure
    
    Attributes:
        type: Message type (progress, result, error, etc.)
        job_id: Associated job ID (optional)
        data: Message payload
        timestamp: Message timestamp
    """
    
    def __init__(
        self,
        type: str,
        data: Dict = None,
        job_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ):
        """Initialize WebSocket message
        
        Args:
            type: Message type
            data: Message payload
            job_id: Associated job ID
            timestamp: Message timestamp
        """
        self.type = type
        self.data = data or {}
        self.job_id = job_id
        self.timestamp = timestamp or datetime.utcnow()
    
    def to_json(self) -> str:
        """Convert to JSON string
        
        Returns:
            JSON string representation
        """
        return json.dumps({
            "type": self.type,
            "job_id": self.job_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        })
    
    @classmethod
    def from_json(cls, data: str) -> "WebSocketMessage":
        """Parse from JSON string
        
        Args:
            data: JSON string
        
        Returns:
            WebSocketMessage instance
        """
        parsed = json.loads(data)
        return cls(
            type=parsed.get("type", "unknown"),
            data=parsed.get("data", {}),
            job_id=parsed.get("job_id"),
        )


class WebSocketConnectionManager:
    """Manages WebSocket connections and broadcasting

    Handles multiple client connections and allows broadcasting
    messages to all connected clients or specific jobs.
    Buffers events per job so late-connecting clients get a full replay.
    """

    def __init__(self):
        """Initialize connection manager"""
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.job_connections: Dict[str, Set[str]] = {}  # job_id -> client_ids
        self.job_event_buffer: Dict[str, list] = {}     # job_id -> [msg_json, ...]
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """Accept new WebSocket connection
        
        Args:
            websocket: WebSocket connection
            client_id: Unique client identifier
        """
        await websocket.accept()
        
        async with self._lock:
            if client_id not in self.active_connections:
                self.active_connections[client_id] = set()
            self.active_connections[client_id].add(websocket)
        
        logger.info(f"Client {client_id} connected")
    
    async def disconnect(self, client_id: str, websocket: WebSocket) -> None:
        """Handle client disconnection
        
        Args:
            client_id: Client identifier
            websocket: WebSocket connection
        """
        async with self._lock:
            if client_id in self.active_connections:
                self.active_connections[client_id].discard(websocket)
                if not self.active_connections[client_id]:
                    del self.active_connections[client_id]
        
        logger.info(f"Client {client_id} disconnected")
    
    async def init_job_buffer(self, job_id: str) -> None:
        """Create event buffer for a new job (call when job is created)."""
        async with self._lock:
            if job_id not in self.job_event_buffer:
                self.job_event_buffer[job_id] = []

    async def register_job(
        self,
        job_id: str,
        client_id: str,
    ) -> None:
        """Register client for job updates and replay buffered events.

        Args:
            job_id: Job identifier
            client_id: Client identifier
        """
        async with self._lock:
            if job_id not in self.job_connections:
                self.job_connections[job_id] = set()
            self.job_connections[job_id].add(client_id)
            buffered = list(self.job_event_buffer.get(job_id, []))

        logger.info(f"Registered {client_id} for job {job_id} ({len(buffered)} buffered events to replay)")

        # Replay missed events immediately
        if buffered:
            async with self._lock:
                connections = self.active_connections.get(client_id, set()).copy()
            for ws in connections:
                for msg_json in buffered:
                    try:
                        await ws.send_text(msg_json)
                    except Exception as e:
                        logger.error(f"Error replaying event to {client_id}: {e}")
    
    async def unregister_job(
        self,
        job_id: str,
        client_id: str,
    ) -> None:
        """Unregister client from job updates
        
        Args:
            job_id: Job identifier
            client_id: Client identifier
        """
        async with self._lock:
            if job_id in self.job_connections:
                self.job_connections[job_id].discard(client_id)
                if not self.job_connections[job_id]:
                    del self.job_connections[job_id]
    
    async def broadcast(self, message: WebSocketMessage) -> None:
        """Broadcast message to all connected clients
        
        Args:
            message: Message to broadcast
        """
        async with self._lock:
            connections = [
                ws for client_connections in self.active_connections.values()
                for ws in client_connections
            ]
        
        for connection in connections:
            try:
                await connection.send_text(message.to_json())
            except Exception as e:
                logger.error(f"Error sending broadcast: {e}")
    
    async def broadcast_to_job(
        self,
        job_id: str,
        message: WebSocketMessage,
    ) -> None:
        """Broadcast message to clients watching specific job.
        Always buffers the event so late-connecting clients get a replay.

        Args:
            job_id: Job identifier
            message: Message to send
        """
        msg_json = message.to_json()

        async with self._lock:
            # Buffer every event for this job
            if job_id not in self.job_event_buffer:
                self.job_event_buffer[job_id] = []
            self.job_event_buffer[job_id].append(msg_json)
            client_ids = self.job_connections.get(job_id, set()).copy()

        for client_id in client_ids:
            await self.send_to_client(client_id, message)
    
    async def send_to_client(
        self,
        client_id: str,
        message: WebSocketMessage,
    ) -> None:
        """Send message to specific client
        
        Args:
            client_id: Client identifier
            message: Message to send
        """
        async with self._lock:
            connections = self.active_connections.get(client_id, set()).copy()
        
        for connection in connections:
            try:
                await connection.send_text(message.to_json())
            except Exception as e:
                logger.error(f"Error sending to {client_id}: {e}")
    
    async def receive_messages(
        self,
        websocket: WebSocket,
        client_id: str,
        on_message=None,
    ) -> None:
        """Receive and process messages from client
        
        Args:
            websocket: WebSocket connection
            client_id: Client identifier
            on_message: Callback for received messages
        """
        try:
            while True:
                data = await websocket.receive_text()
                message = WebSocketMessage.from_json(data)
                
                logger.debug(f"Received {message.type} from {client_id}")
                
                if on_message:
                    await on_message(client_id, message)
        
        except WebSocketDisconnect:
            await self.disconnect(client_id, websocket)
        except Exception as e:
            logger.error(f"Error in receive_messages: {e}")
            await self.disconnect(client_id, websocket)
    
    def get_stats(self) -> Dict:
        """Get connection statistics
        
        Returns:
            Stats dictionary
        """
        return {
            "active_clients": len(self.active_connections),
            "active_jobs": len(self.job_connections),
            "total_connections": sum(
                len(conns)
                for conns in self.active_connections.values()
            ),
        }


# Global connection manager instance
_manager: Optional[WebSocketConnectionManager] = None


def get_connection_manager() -> WebSocketConnectionManager:
    """Get global WebSocket connection manager
    
    Returns:
        WebSocketConnectionManager instance
    """
    global _manager
    if _manager is None:
        _manager = WebSocketConnectionManager()
    return _manager


class ProgressNotifier:
    """Helper class to send progress updates
    
    Simplifies sending progress messages during analysis.
    """
    
    def __init__(self, job_id: str, manager: WebSocketConnectionManager):
        """Initialize progress notifier
        
        Args:
            job_id: Job identifier
            manager: WebSocket connection manager
        """
        self.job_id = job_id
        self.manager = manager
    
    async def notify(
        self,
        status: str,
        progress_percent: int,
        files_processed: int,
        files_total: int,
        current_step: str,
        eta_seconds: Optional[float] = None,
    ) -> None:
        """Send progress update
        
        Args:
            status: Current status
            progress_percent: Progress percentage
            files_processed: Files processed
            files_total: Total files
            current_step: Current processing step
            eta_seconds: Estimated time remaining
        """
        message = WebSocketMessage(
            type="progress",
            job_id=self.job_id,
            data={
                "status": status,
                "progress_percent": progress_percent,
                "files_processed": files_processed,
                "files_total": files_total,
                "current_step": current_step,
                "eta_seconds": eta_seconds,
            },
        )
        await self.manager.broadcast_to_job(self.job_id, message)
    
    async def notify_error(self, error_message: str) -> None:
        """Send error notification
        
        Args:
            error_message: Error message
        """
        message = WebSocketMessage(
            type="error",
            job_id=self.job_id,
            data={"error": error_message},
        )
        await self.manager.broadcast_to_job(self.job_id, message)
    
    async def notify_complete(self, result_summary: Dict) -> None:
        """Send completion notification
        
        Args:
            result_summary: Summary of analysis results
        """
        message = WebSocketMessage(
            type="complete",
            job_id=self.job_id,
            data=result_summary,
        )
        await self.manager.broadcast_to_job(self.job_id, message)
