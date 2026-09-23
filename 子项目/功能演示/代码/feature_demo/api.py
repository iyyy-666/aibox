from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles

from .manager import ModuleConflictError, ModuleManager
from .registry import MODULES, get_module


def _module_or_404(module_id: str):
    try:
        return get_module(module_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="功能不存在。") from exc


def _result_payload(result) -> dict:
    return jsonable_encoder(asdict(result))


def create_app(manager: ModuleManager) -> FastAPI:
    app = FastAPI(title="功能演示")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/modules")
    def list_modules() -> dict:
        return {"modules": jsonable_encoder(MODULES)}

    @app.get("/api/modules/active")
    def active_module() -> dict:
        return _result_payload(manager.snapshot())

    @app.post("/api/modules/{module_id}/start")
    def start_module(module_id: str) -> dict:
        _module_or_404(module_id)
        try:
            return _result_payload(manager.start_module(module_id))
        except ModuleConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/modules/{module_id}/stop")
    def stop_module(module_id: str) -> dict:
        _module_or_404(module_id)
        try:
            return _result_payload(manager.stop_module(module_id))
        except ModuleConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/modules/{module_id}/commands/{command}")
    def send_command(module_id: str, command: str, payload: dict | None = None) -> dict:
        _module_or_404(module_id)
        try:
            return manager.command(module_id, command, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ModuleConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/modules/{module_id}/status")
    def module_status(module_id: str) -> dict:
        _module_or_404(module_id)
        snapshot = manager.snapshot()
        if snapshot.module_id != module_id:
            raise HTTPException(status_code=409, detail="该功能当前未运行。")
        return _result_payload(snapshot)

    @app.get("/api/modules/{module_id}/frame")
    def module_frame(module_id: str) -> Response:
        _module_or_404(module_id)
        snapshot = manager.snapshot()
        if snapshot.module_id != module_id:
            raise HTTPException(status_code=409, detail="该功能当前未运行。")
        encoded_frame = (snapshot.details or {}).get("frame_jpeg_base64")
        if not encoded_frame:
            return Response(status_code=204)
        try:
            content = base64.b64decode(encoded_frame, validate=True)
        except (ValueError, TypeError):
            raise HTTPException(status_code=500, detail="画面数据无法读取。")
        frame_sequence = (snapshot.details or {}).get("frame_sequence", 0)
        return Response(
            content=content,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-store",
                "X-Frame-Sequence": str(frame_sequence),
            },
        )

    @app.websocket("/ws/modules/{module_id}")
    async def module_events(websocket: WebSocket, module_id: str) -> None:
        try:
            _module_or_404(module_id)
        except HTTPException:
            await websocket.close(code=4404, reason="功能不存在。")
            return
        await websocket.accept()
        try:
            while True:
                snapshot = manager.snapshot()
                if snapshot.module_id != module_id:
                    await websocket.close(code=4409, reason="该功能当前未运行。")
                    return
                await websocket.send_json(_result_payload(snapshot))
                await asyncio.sleep(0.5)
        except (WebSocketDisconnect, RuntimeError):
            return

    web_dir = Path(__file__).with_name("web")
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app
