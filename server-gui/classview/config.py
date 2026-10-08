"""Настройки приложения: ~/.config/classview/config.json (права 600)."""
import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "classview"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "classview"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    school_id: str = ""            # номер школы в hostname (пусто = любая)
    rtsp_port: int = 8554
    rtsp_user: str = "viewer"
    rtsp_password: str = ""
    view_path: str = "cam"          # путь просмотра на панели
    record_path: str = "cam"        # устарело: запись идёт по пути просмотра (cam)
    recordings_dir: str = str(Path.home() / "Записи" / "classview")
    directory_url: str = ""         # справочник filedrop, напр. http://10.0.0.5:8080
    directory_token: str = ""
    retention_days: int = 30        # 0 = хранить вечно
    status_interval_sec: int = 30

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                known = {f.name: f.type for f in fields(cls)}
                for k, v in data.items():
                    if k in known:
                        setattr(cfg, k, v)
            except (OSError, ValueError):
                pass
        return cfg

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
