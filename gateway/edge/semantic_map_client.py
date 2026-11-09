"""语义地图查询客户端（消费 spatial-map-foundation 的语义瓦片服务）.

为什么需要它
------------
老师的 VLM 能力要传导到端侧学生，唯一通道是**语义瓦片**：
边侧把 RGB 理解写成地图上的语义标签，端侧策略消费同一张语义地图。
没有这个客户端，语义地图只存在于 C++ 进程里，边侧够不着。

版本一致性
----------
每次响应都带 ``map_version``。客户端主动校验，不匹配即抛
``SemanticMapVersionMismatch`` —— 拿 v45 的坐标去配 v42 的语义，
会产生看起来"合理"但完全错误的样本，是蒸馏最隐蔽的污染源。

坐标系
------
查询点的 ``lat/lon`` 是 **WGS84**（机器人位姿空间）。
瓦片索引空间是 GCJ-02（高德），服务端负责换算。客户端不要自己转。
"""
from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9881
DEFAULT_TIMEOUT_S = 3.0


class SemanticMapError(RuntimeError):
    """语义地图服务的通用错误."""


class SemanticMapVersionMismatch(SemanticMapError):
    """服务端 map_version 与预期不一致 —— 说明地图已更新，语义不可信."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"semantic map version mismatch: expected {expected}, got {actual}"
        )


@dataclass(frozen=True)
class SemanticTag:
    category: str
    confidence: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SemanticTag":
        return cls(str(d.get("cat", "unknown")), int(d.get("conf", 0)))


@dataclass(frozen=True)
class SemanticTile:
    z: int
    x: int
    y: int
    tags: tuple[SemanticTag, ...] = ()
    dist_m: Optional[float] = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SemanticTile":
        dist = d.get("dist_m")
        return cls(
            z=int(d.get("z", 0)),
            x=int(d.get("x", 0)),
            y=int(d.get("y", 0)),
            tags=tuple(SemanticTag.from_dict(t) for t in (d.get("tags") or [])),
            dist_m=float(dist) if dist is not None else None,
        )

    def best_confidence(self, category: str) -> int:
        """某类别的最高置信度；无该类别返回 0."""
        return max((t.confidence for t in self.tags if t.category == category), default=0)

    def categories(self) -> tuple[str, ...]:
        return tuple(t.category for t in self.tags)


@dataclass
class MapInfo:
    map_version: int
    zoom: int
    tile_count: int
    anchor_lat: float = 0.0
    anchor_lon: float = 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MapInfo":
        anchor = d.get("anchor") or {}
        return cls(
            map_version=int(d.get("map_version", 0)),
            zoom=int(d.get("zoom", 0)),
            tile_count=int(d.get("tile_count", 0)),
            anchor_lat=float(anchor.get("lat", 0.0)),
            anchor_lon=float(anchor.get("lon", 0.0)),
        )


@dataclass
class QueryResult:
    map_version: int
    tiles: list[SemanticTile] = field(default_factory=list)
    truncated: bool = False

    def __len__(self) -> int:
        return len(self.tiles)

    def categories_present(self) -> set[str]:
        out: set[str] = set()
        for t in self.tiles:
            out.update(t.categories())
        return out

    def nearest_with(self, category: str, min_confidence: int = 0) -> Optional[SemanticTile]:
        """最近的某类别瓦片；没有则 None.

        注意必须要求 confidence > 0：``best_confidence`` 对**不存在**的
        类别也返回 0，若只写 ``>= min_confidence``（默认 0），会把任意
        瓦片误判为命中。
        """
        for t in self.tiles:                      # 服务端已按距离升序
            conf = t.best_confidence(category)
            if conf > 0 and conf >= min_confidence:
                return t
        return None


class SemanticMapClient:
    """长连接语义地图客户端. 未连接时所有查询抛 SemanticMapError."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        *,
        expected_version: Optional[int] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.expected_version = expected_version
        self._sock: Optional[socket.socket] = None
        self._buf = b""

    # ---------- 连接管理 ----------

    def connect(self) -> None:
        self.close()
        self._sock = socket.create_connection((self.host, self.port), self.timeout_s)
        self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._buf = b""

    def __enter__(self) -> "SemanticMapClient":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # ---------- 协议 ----------

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._sock is None:
            raise SemanticMapError("not connected")

        line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            self._sock.sendall(line.encode("utf-8"))
            while b"\n" not in self._buf:
                chunk = self._sock.recv(8192)
                if not chunk:
                    raise SemanticMapError("connection closed by service")
                self._buf += chunk
            raw, self._buf = self._buf.split(b"\n", 1)
        except OSError as exc:
            self.close()
            raise SemanticMapError(f"transport error: {exc}") from exc

        try:
            resp = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SemanticMapError(f"bad response: {exc}") from exc

        if not resp.get("ok"):
            raise SemanticMapError(f"service error: {resp.get('error', 'unknown')}")

        self._check_version(int(resp.get("map_version", 0)))
        return resp

    def _check_version(self, actual: int) -> None:
        if self.expected_version is None:
            return
        if actual != self.expected_version:
            raise SemanticMapVersionMismatch(self.expected_version, actual)

    # ---------- 查询 ----------

    def info(self) -> MapInfo:
        return MapInfo.from_dict(self._request({"cmd": "info"}))

    def tiles(
        self,
        *,
        categories: Optional[list[str]] = None,
        min_confidence: int = 0,
    ) -> QueryResult:
        payload: dict[str, Any] = {"cmd": "tiles", "min_confidence": int(min_confidence)}
        if categories:
            payload["categories"] = list(categories)
        resp = self._request(payload)
        return QueryResult(
            map_version=int(resp.get("map_version", 0)),
            tiles=[SemanticTile.from_dict(t) for t in (resp.get("tiles") or [])],
            truncated=bool(resp.get("truncated", False)),
        )

    def query(
        self,
        lat: float,
        lon: float,
        radius_m: float = 500.0,
        *,
        categories: Optional[list[str]] = None,
        min_confidence: int = 0,
    ) -> QueryResult:
        """半径查询. lat/lon 为 WGS84（机器人位姿空间）."""
        payload: dict[str, Any] = {
            "cmd": "query",
            "lat": float(lat),
            "lon": float(lon),
            "radius_m": float(radius_m),
            "min_confidence": int(min_confidence),
        }
        if categories:
            payload["categories"] = list(categories)
        resp = self._request(payload)
        return QueryResult(
            map_version=int(resp.get("map_version", 0)),
            tiles=[SemanticTile.from_dict(t) for t in (resp.get("tiles") or [])],
            truncated=bool(resp.get("truncated", False)),
        )


def describe_for_prompt(result: QueryResult, *, limit: int = 8) -> str:
    """把查询结果压成一段给 VLM 的自然语言描述.

    用途：把语义地图作为老师的额外上下文，让 VLM 的 frontier 选择
    能结合"这个方向通向什么房间"，而不只看 RGB 单帧。
    紧凑输出，避免撑爆 prompt。
    """
    if not result.tiles:
        return "语义地图：附近未标注任何房间。"

    parts: list[str] = []
    for t in result.tiles[:limit]:
        cats = ", ".join(
            f"{tag.category}({tag.confidence})" for tag in
            sorted(t.tags, key=lambda x: -x.confidence)
        )
        dist = f"{t.dist_m:.0f}m" if t.dist_m is not None else "-"
        parts.append(f"{cats} @ {dist}")
    suffix = "（已截断）" if len(result.tiles) > limit else ""
    return f"语义地图 v{result.map_version}，附近 {len(result.tiles)} 个已标注瓦片{suffix}：" + "；".join(parts)
