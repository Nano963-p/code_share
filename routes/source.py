"""Read-only, bounded previews. Archive members are never extracted or executed."""
from pathlib import PurePosixPath
import stat
import zipfile
import zlib

import bleach
import markdown
from markupsafe import Markup
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_for_filename, TextLexer
from pygments.util import ClassNotFound
from flask import abort, current_app, render_template, request

from db import fetchone, fetchall
from utils import current_user, login_required, require_project_role, resolve_upload_path
import os

MAX_PREVIEW = 1024 * 1024
MAX_ENTRIES = 5000
FORMATTER = HtmlFormatter(cssclass="source-code", linenos="inline")
TEXT_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".json",
    ".xml", ".sql", ".txt", ".md", ".markdown", ".java", ".c", ".cpp", ".h", ".go",
    ".rs", ".rb", ".php", ".sh", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".csv"}


def safe_member(name):
    parts = name.rstrip("/").split("/")
    return bool(name) and not name.startswith("/") and "\\" not in name and ":" not in name and all(
        part not in {"", ".", ".."} for part in parts)


def zip_index(archive):
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ValueError("This archive has too many entries to browse. Download it instead.")
    index = {}
    for info in infos:
        if not safe_member(info.filename) or stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError("This archive contains unsafe paths or symbolic links and cannot be previewed.")
        if info.filename in index:
            raise ValueError("This archive contains duplicate paths and cannot be previewed.")
        index[info.filename] = info
    return index


def render_preview(name, content):
    if len(content) > MAX_PREVIEW:
        raise ValueError("This file is too large to preview (limit: 1 MB). Download it instead.")
    if PurePosixPath(name).suffix.lower() not in TEXT_EXTENSIONS and PurePosixPath(name).name.lower() not in {"readme", "license", "dockerfile", "makefile", ".gitignore"}:
        raise ValueError("Preview is unavailable for this file type. Use Download to open it locally.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Preview supports UTF-8 text files. Download this file to view it.") from exc
    if "\x00" in text:
        raise ValueError("Binary files cannot be previewed.")
    if PurePosixPath(name).suffix.lower() in {".md", ".markdown"}:
        html = markdown.markdown(text, extensions=["fenced_code", "tables", "sane_lists"])
        clean = bleach.clean(html, tags={"p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
            "blockquote", "pre", "code", "strong", "em", "del", "ul", "ol", "li", "a",
            "table", "thead", "tbody", "tr", "th", "td"},
            attributes={"a": ["href", "title"]}, protocols={"https", "http", "mailto"}, strip=True)
        return Markup(clean), "markdown"
    try:
        lexer = get_lexer_for_filename(name)
    except ClassNotFound:
        lexer = TextLexer()
    return Markup(highlight(text, lexer, FORMATTER)), "code"


def read_member(archive, info):
    if info.flag_bits & 1:
        raise ValueError("Encrypted files cannot be previewed.")
    if info.file_size > MAX_PREVIEW or info.file_size > max(info.compress_size, 1) * 200:
        raise ValueError("This archive entry exceeds the preview size or compression limit.")
    with archive.open(info) as stream:
        return stream.read(MAX_PREVIEW + 1)


def directory_entries(index, folder):
    prefix = folder.rstrip("/") + "/" if folder else ""
    found = {}
    for name, info in index.items():
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if not rest:
            continue
        leaf = rest.split("/")[0]
        is_dir = "/" in rest or info.is_dir()
        found[leaf] = {"name": leaf, "path": prefix + leaf + ("/" if is_dir else ""),
                       "is_dir": is_dir, "size": None if is_dir else info.file_size}
    return sorted(found.values(), key=lambda item: (not item["is_dir"], item["name"].lower()))


@login_required
def source_browser(pid):
    user = current_user()
    project = fetchone("SELECT id,title,is_private FROM projects WHERE id=%s", (pid,))
    if not project:
        abort(404)
    if project["is_private"]:
        require_project_role(pid, "member")
    files = fetchall("SELECT id,filename,filesize FROM files WHERE project_id=%s ORDER BY filename,id", (pid,))
    file_id = request.args.get("file", type=int)
    if "file" in request.args and file_id is None:
        abort(400)
    if file_id is None:
        readme = next((f for f in files if f["filename"].lower() in {"readme.md", "readme.markdown"}), None)
        file_id = readme["id"] if readme else None
    selected, preview, mode, error, entries, display_name = None, None, None, None, [], None
    member = request.args.get("path", "")
    parent = ""
    if file_id is not None:
        selected = fetchone("SELECT id,filename,filepath,filesize FROM files WHERE id=%s AND project_id=%s", (file_id, pid))
        if not selected:
            abort(404)
        path = resolve_upload_path(os.path.join(current_app.root_path, selected["filepath"]))
        display_name = selected["filename"]
        try:
            if selected["filename"].lower().endswith(".zip"):
                if os.path.getsize(path) > current_app.config["MAX_CONTENT_LENGTH"]:
                    raise ValueError("This archive is too large to browse.")
                if member and not safe_member(member):
                    abort(400)
                with zipfile.ZipFile(path) as archive:
                    index = zip_index(archive)
                    folder = member if member.endswith("/") else member.rpartition("/")[0]
                    if folder:
                        folder = folder.rstrip("/") + "/"
                    entries = directory_entries(index, folder)
                    if member and not entries and member not in index:
                        abort(404)
                    parent = folder.rstrip("/").rpartition("/")[0]
                    if parent:
                        parent += "/"
                    selected_member = member if member and not member.endswith("/") else None
                    if not selected_member:
                        selected_member = next((e["path"] for e in entries if not e["is_dir"] and e["name"].lower() in {"readme.md", "readme.markdown"}), None)
                    if selected_member:
                        if selected_member not in index:
                            abort(404)
                        display_name = selected_member
                        preview, mode = render_preview(selected_member, read_member(archive, index[selected_member]))
            else:
                if member:
                    abort(400)
                with open(path, "rb") as stream:
                    preview, mode = render_preview(selected["filename"], stream.read(MAX_PREVIEW + 1))
        except (ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, zlib.error) as exc:
            error = str(exc) if isinstance(exc, ValueError) else "This file could not be previewed. Try downloading it."
    response = current_app.make_response(render_template("source_browser.html", user=user, project=project,
        files=files, selected=selected, preview=preview, mode=mode, error=error, entries=entries,
        member=member, parent=parent, display_name=display_name))
    response.headers["Cache-Control"] = "private, no-store"
    return response
