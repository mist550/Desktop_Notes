"""Compatible JSON storage with validation, atomic writes and local backups."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


class DataError(ValueError):
    pass


def normalize_data(data):
    """Preserve unknown fields; migrate legacy notes without discarding content."""
    if not isinstance(data, dict) or not ({"categories", "notes"} & data.keys()):
        raise DataError("数据文件缺少 categories / notes，已停止读取以保护原文件。")
    result = copy.deepcopy(data)
    categories = result.get("categories") if "categories" in result else [
        {"id": 1, "name": "默认分类", "tags": result["notes"]}
    ]
    if not isinstance(categories, list):
        raise DataError("分类格式无效。")
    category_ids, tag_ids = set(), set()

    def assign_id(item, used):
        value = item.get("id")
        if type(value) is not int or value < 1 or value in used:
            value = max(used, default=0) + 1
            item["id"] = value
        used.add(value)

    for category in categories:
        if not isinstance(category, dict):
            raise DataError("分类格式无效。")
        assign_id(category, category_ids)
        category.setdefault("name", "分类")
        if not isinstance(category["name"], str):
            raise DataError("分类名称必须为文本。")
        tags = category.get("tags", category.get("notes", []))
        if not isinstance(tags, list):
            raise DataError("标签列表格式无效。")
        normalized_tags = []
        for tag in tags:
            if not isinstance(tag, dict):
                if tag is not None and not isinstance(tag, (str, int, float, bool)):
                    raise DataError("标签格式无效。")
                tag = {"title": str(tag) if tag is not None else "未命名", "content": ""}
            assign_id(tag, tag_ids)
            tag.setdefault("title", tag.get("name", "未命名"))
            tag.setdefault("content", "")
            if not isinstance(tag["title"], str) or not isinstance(tag["content"], str):
                raise DataError("标签标题和内容必须为文本。")
            normalized_tags.append(tag)
        category["tags"] = normalized_tags
    result["categories"] = categories
    for key, used in (("next_category_id", category_ids), ("next_tag_id", tag_ids)):
        value = result.get(key, 1)
        result[key] = max(value if type(value) is int else 1, max(used, default=0) + 1)
    settings = result.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise DataError("设置格式无效。")
    return result


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class NotesStore:
    def __init__(self, path):
        self.path = Path(path)
        self.backup_dir = self.path.parent / "backups"
        self._lock = None
        self._loaded = False
        self._revision = None

    def acquire(self):
        """An OS lock prevents two application instances overwriting each other."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(self.path.parent / "notes.lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if not stream.tell():
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise OSError("便签已在运行，请从系统托盘打开；若是旧版本，请先退出旧版本。") from exc
        self._lock = stream

    def close(self):
        if self._lock:
            self._lock.close()
            self._lock = None

    def load(self):
        raw = self.path.read_bytes() if self.path.exists() else None
        data = normalize_data(json.loads(raw.decode("utf-8-sig"))) if raw is not None else {
            "categories": [], "next_category_id": 1, "next_tag_id": 1, "settings": {}
        }
        self._revision = hashlib.sha256(raw).digest() if raw is not None else None
        self._loaded = True
        return data

    def save(self, data):
        # Validate first. Neither bad input nor an unreadable original may replace the file.
        data = normalize_data(data)
        content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        previous = self.path.read_bytes() if self.path.exists() else None
        if previous is not None:
            normalize_data(json.loads(previous.decode("utf-8-sig")))
        revision = hashlib.sha256(previous).digest() if previous is not None else None
        if self._loaded and revision != self._revision:
            raise OSError("数据文件已被其他程序修改或移除，已阻止覆盖。请先导出当前内容，退出其他便签进程，再重新打开。")
        if previous == content:
            return
        if previous is not None:
            self.backup_dir.mkdir(exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            atomic_write(self.backup_dir / f"notes-{stamp}-{time.time_ns()}.json", previous)
        atomic_write(self.path, content)
        self._revision = hashlib.sha256(content).digest()
        self._loaded = True
        # Backup cleanup failure must not turn a successful save into an error.
        try:
            for backup in sorted(self.backup_dir.glob("notes-*.json"), reverse=True)[30:]:
                backup.unlink()
        except OSError:
            pass
