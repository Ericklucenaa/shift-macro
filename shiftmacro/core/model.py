"""Modelo de dados de uma macro: independente da interface e do motor."""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any

FORMAT_VERSION = 1


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Command:
    """Uma etapa da macro. `type` aponta para um CommandSpec do registro."""

    type: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    name: str = ""
    comment: str = ""
    delay_ms: int = 0  # espera depois de executar a etapa
    id: str = field(default_factory=new_id)

    def clone(self) -> "Command":
        c = copy.deepcopy(self)
        c.id = new_id()
        return c

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "params": self.params,
            "enabled": self.enabled,
            "name": self.name,
            "comment": self.comment,
            "delay_ms": self.delay_ms,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Command":
        return cls(
            type=str(d["type"]),
            params=dict(d.get("params") or {}),
            enabled=bool(d.get("enabled", True)),
            name=str(d.get("name") or ""),
            comment=str(d.get("comment") or ""),
            delay_ms=int(d.get("delay_ms") or 0),
            id=str(d.get("id") or new_id()),
        )


REPEAT_MODES = ("once", "count", "duration", "infinite")


@dataclass
class RunSettings:
    repeat_mode: str = "once"  # once | count | duration | infinite
    repeat_count: int = 1
    repeat_minutes: float = 1.0
    speed: float = 1.0  # 2.0 = duas vezes mais rápido
    minimize_on_run: bool = False
    shutdown_when_done: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "RunSettings":
        s = cls()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                setattr(s, k, type(getattr(s, k))(v))
        if s.repeat_mode not in REPEAT_MODES:
            s.repeat_mode = "once"
        s.speed = min(max(s.speed, 0.1), 10.0)
        return s


@dataclass
class Macro:
    name: str = "Nova macro"
    description: str = ""
    commands: list[Command] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)  # valores iniciais
    settings: RunSettings = field(default_factory=RunSettings)
    hotkeys: dict[str, str] = field(default_factory=dict)  # sobrescreve os atalhos globais
    images: dict[str, bytes] = field(default_factory=dict)  # nome -> PNG

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "shiftmacro",
            "version": FORMAT_VERSION,
            "name": self.name,
            "description": self.description,
            "commands": [c.to_dict() for c in self.commands],
            "variables": self.variables,
            "settings": self.settings.to_dict(),
            "hotkeys": self.hotkeys,
            "images": sorted(self.images),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], images: dict[str, bytes] | None = None) -> "Macro":
        return cls(
            name=str(d.get("name") or "Macro"),
            description=str(d.get("description") or ""),
            commands=[Command.from_dict(c) for c in d.get("commands") or []],
            variables=dict(d.get("variables") or {}),
            settings=RunSettings.from_dict(d.get("settings")),
            hotkeys={str(k): str(v) for k, v in (d.get("hotkeys") or {}).items()},
            images=dict(images or {}),
        )

    def unique_image_name(self, base: str = "imagem") -> str:
        i = 1
        while f"{base}{i}" in self.images:
            i += 1
        return f"{base}{i}"

    def used_images(self) -> set[str]:
        used = set()
        for c in self.commands:
            for key in ("image",):
                v = c.params.get(key)
                if v:
                    used.add(str(v))
            cond = c.params.get("condition")
            if isinstance(cond, dict) and cond.get("image"):
                used.add(str(cond["image"]))
        return used
