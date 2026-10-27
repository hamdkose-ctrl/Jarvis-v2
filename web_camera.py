"""Remote camera device bridge methods for the authenticated web profile."""
from __future__ import annotations

import base64


class WebCamera:
    def _camera_owner(self) -> str:
        return self._runtime._p().slug

    def camera_local_enable(self, device_id: str) -> dict:
        from modules import camera_bridge
        return camera_bridge.local_enable(self._camera_owner(), device_id)

    def camera_local_disable(self, device_id: str) -> dict:
        from modules import camera_bridge
        return camera_bridge.local_disable(self._camera_owner(), device_id)

    def camera_status(self, device_id: str) -> dict:
        from modules import camera_bridge
        return camera_bridge.status(self._camera_owner(), device_id)

    def camera_viewer_join(self, device_id: str, viewer_id: str) -> dict:
        from modules import camera_bridge
        count = camera_bridge.viewer_join(self._camera_owner(), device_id, viewer_id)
        return {"ok": True, "viewers": count}

    def camera_viewer_leave(self, device_id: str, viewer_id: str) -> dict:
        from modules import camera_bridge
        count = camera_bridge.viewer_leave(self._camera_owner(), device_id, viewer_id)
        return {"ok": True, "viewers": count}

    def camera_frame(self, device_id: str, frame_b64: str, transport: str, width: int, height: int) -> dict:
        from modules import camera_bridge
        try:
            raw = base64.b64decode(str(frame_b64), validate=True)
        except Exception as exc:
            raise ValueError("Kamera karesi base64 olarak çözülemedi.") from exc
        return camera_bridge.submit_frame(
            self._camera_owner(), device_id, raw,
            transport=str(transport), width=int(width), height=int(height),
        )
