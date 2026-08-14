from __future__ import annotations

import cgi
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


HOST = "127.0.0.1"
PORT = 8765
TOOL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
RUNS_ROOT = TOOL_ROOT / "results" / "docling" / "ui_runs"
OUTPUT_FILES = (
    "source_document_clean.md",
    "source_document.md",
    "ocr_review_alternatives.md",
    "manifest.json",
)
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
ACTIVE_JOB: str | None = None


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("._")
    return cleaned or "pdf_source"


def form_items(form: cgi.FieldStorage, key: str) -> list[Any]:
    if key not in form:
        return []
    value = form[key]
    return value if isinstance(value, list) else [value]


def save_uploaded_pdf(item: Any, role: str, index: int) -> dict[str, str]:
    original_name = str(getattr(item, "filename", "") or "")
    if not original_name:
        raise ValueError("未收到 PDF 檔名。")
    documents_root = RUNS_ROOT / "document_runs"
    documents_root.mkdir(parents=True, exist_ok=True)
    temporary = RUNS_ROOT / f"upload_{time.time_ns()}_{index}.pdf"
    with temporary.open("wb") as handle:
        shutil.copyfileobj(item.file, handle)
    with temporary.open("rb") as handle:
        signature = handle.read(5)
    if signature != b"%PDF-":
        temporary.unlink(missing_ok=True)
        raise ValueError(f"{original_name} 不是有效 PDF。")
    digest = sha256_file(temporary)
    document_id = f"{role}-{digest[:16]}"
    output = documents_root / f"{safe_stem(original_name)}-{digest[:16]}"
    output.mkdir(parents=True, exist_ok=True)
    source = output / "source.pdf"
    if source.exists() and sha256_file(source) == digest:
        temporary.unlink()
    else:
        temporary.replace(source)
    return {
        "id": document_id,
        "role": role,
        "original_name": original_name,
        "sha256": digest,
        "source": str(source),
        "output": str(output),
    }


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_progress(path: Path) -> tuple[int, int, int, int]:
    if not path.exists():
        return 0, 0, 0, 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    pages = list(payload.get("pages", {}).values())
    complete = sum(item.get("pdf_aware_status") == "complete" for item in pages)
    review = sum(item.get("full_page_status") == "complete" for item in pages)
    failures = sum(bool(item.get("error")) for item in pages)
    total = int(payload.get("source_total_pages") or 0)
    return complete, total, review, failures


def documents_progress(documents: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    progress = [manifest_progress(Path(item["output"]) / "manifest.json") for item in documents]
    return tuple(sum(values) for values in zip(*progress, strict=False))  # type: ignore[return-value]


def public_job(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise KeyError(job_id)
        snapshot = {
            "id": job_id,
            "name": job["name"],
            "state": job["state"],
            "message": job["message"],
            "log": list(job["log"]),
            "files": [],
        }
        output = Path(job["output"])
        documents = list(job["documents"])
    done, total, review, failures = documents_progress(documents)
    snapshot.update(
        {
            "done": done,
            "total": total,
            "review": review,
            "failures": failures,
            "percent": round(done / total * 100, 1) if total else 0,
            "files": [name for name in OUTPUT_FILES if (output / name).is_file()],
        }
    )
    return snapshot


def append_log(job_id: str, line: str) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id]["log"].append(line.rstrip())


def set_job(job_id: str, *, state: str | None = None, message: str | None = None) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        if state is not None:
            job["state"] = state
        if message is not None:
            job["message"] = message


def run_process(job_id: str, command: list[str]) -> int:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["DOCLING_INFERENCE_COMPILE_TORCH_MODELS"] = "false"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=creationflags,
    )
    with JOBS_LOCK:
        JOBS[job_id]["process"] = process
    assert process.stdout is not None
    for line in process.stdout:
        append_log(job_id, line)
    return process.wait()


def command(script: str, *arguments: str) -> list[str]:
    return [sys.executable, str(SCRIPT_DIR / script), *arguments]


def process_job(job_id: str) -> None:
    global ACTIVE_JOB
    with JOBS_LOCK:
        job = JOBS[job_id]
        output = Path(job["output"])
        documents = list(job["documents"])
    try:
        set_job(job_id, state="running", message="正在逐份轉換來源文件；可關閉頁面，稍後重新開啟查看。")
        for index, document in enumerate(documents, start=1):
            source = Path(document["source"])
            document_output = Path(document["output"])
            append_log(
                job_id,
                f"[{index}/{len(documents)}] {document['role']}: {document['original_name']}",
            )
            code = run_process(
                job_id,
                command(
                    "run_pipeline.py",
                    "--input",
                    str(source),
                    "--output",
                    str(document_output),
                ),
            )
            if code != 0:
                raise RuntimeError(f"PDF 轉換失敗：{document['original_name']}，結束碼 {code}")
            set_job(job_id, message=f"正在建立第 {index}/{len(documents)} 份文件的唯一正式來源。")
            code = run_process(
                job_id,
                command(
                    "build_source_document.py",
                    "--run-dir",
                    str(document_output),
                    "--output",
                    str(document_output / "source_document.md"),
                    "--review-output",
                    str(document_output / "ocr_review_alternatives.md"),
                    "--clean-output",
                    str(document_output / "source_document_clean.md"),
                ),
            )
            if code != 0:
                raise RuntimeError(f"Markdown 建置失敗：{document['original_name']}，結束碼 {code}")
            manifest = json.loads((document_output / "manifest.json").read_text(encoding="utf-8"))
            total = str(manifest["source_total_pages"])
            code = run_process(
                job_id,
                command(
                    "validate_run.py",
                    "--run-dir",
                    str(document_output),
                    "--source-document",
                    str(document_output / "source_document_clean.md"),
                    "--review-document",
                    str(document_output / "ocr_review_alternatives.md"),
                    "--expect-page-start",
                    "1",
                    "--expect-page-end",
                    total,
                ),
            )
            if code != 0:
                raise RuntimeError(f"來源檔驗證未通過：{document['original_name']}")
        set_job(job_id, message="正在合併主需求書與審查文件，並保留各自文件名稱及頁碼。")
        plan_path = output / "package_plan.json"
        plan_path.write_text(
            json.dumps({"documents": documents}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        code = run_process(
            job_id,
            command(
                "build_source_package.py",
                "--package-dir",
                str(output),
                "--plan",
                str(plan_path),
            ),
        )
        if code != 0:
            raise RuntimeError("來源文件合併失敗，請查看處理紀錄。")
        set_job(
            job_id,
            state="complete",
            message="完成：請將合併後的 source_document_clean.md 上傳 GPTS；它已保留每份文件的角色、名稱與獨立頁碼。",
        )
    except Exception as exc:
        with JOBS_LOCK:
            stopped = JOBS[job_id]["state"] == "stopped"
        if not stopped:
            append_log(job_id, f"ERROR: {exc}")
            set_job(job_id, state="failed", message=str(exc))
    finally:
        with JOBS_LOCK:
            JOBS[job_id]["process"] = None
            if ACTIVE_JOB == job_id:
                ACTIVE_JOB = None


PAGE = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Docling PDF 來源轉換器</title>
<style>
:root{font-family:"Microsoft JhengHei UI",system-ui,sans-serif;color:#172033;background:#f4f7fb}*{box-sizing:border-box}
body{margin:0}.wrap{max-width:940px;margin:36px auto;padding:0 20px}h1{margin:0;font-size:28px}.sub{color:#607089;margin:8px 0 24px}
.card{background:#fff;border:1px solid #dbe4ef;border-radius:14px;padding:20px;margin:14px 0;box-shadow:0 6px 24px rgba(21,40,70,.06)}
.step{font-size:14px;font-weight:800;color:#2357b8;margin-bottom:12px}.drop{border:2px dashed #b7c7dd;border-radius:12px;padding:24px;text-align:center}
input[type=file]{max-width:100%}button,.filelink{border:0;border-radius:9px;padding:10px 16px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}
button.primary{background:#2463eb;color:white}button.secondary,.filelink{background:#edf3ff;color:#17489c}button:disabled{opacity:.5;cursor:not-allowed}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.progress{height:14px;background:#e9eef5;border-radius:999px;overflow:hidden;margin:14px 0 8px}.bar{height:100%;width:0;background:#2463eb;transition:width .3s}
.meta{font-size:14px;color:#52647c}.status{font-weight:800;margin-top:10px}.files{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
pre{height:210px;overflow:auto;background:#101827;color:#d7e2f4;border-radius:10px;padding:14px;white-space:pre-wrap;font:12px/1.5 Consolas,monospace}
.note{font-size:13px;color:#69798f}.ok{color:#08794d}.bad{color:#b42318}
</style></head><body><main class="wrap">
<h1>Docling PDF 來源轉換器</h1><p class="sub">把主需求書與可選的審查文件轉成 GPT 易讀的單一正式來源；每份文件仍保留獨立名稱與頁碼。所有處理都在本機執行。</p>
<section class="card"><div class="step">1　選擇來源 PDF</div><div class="drop"><label><strong>主需求書（必選）</strong><br><input id="pdf" type="file" accept="application/pdf,.pdf"></label><p class="note">統包需求書、需求計畫書或本案主要規範文件。</p><label><strong>審查意見／補充文件（選填，可多選）</strong><br><input id="reviews" type="file" accept="application/pdf,.pdf" multiple></label><p class="note">可加入審查意見書、會議紀錄或回覆文件；系統會逐份轉換後合成一個 MD，不會混用頁碼。同一組文件再次執行會沿用各檔 checkpoint。</p></div><div class="row" style="margin-top:14px"><button id="start" class="primary">開始／續跑</button><button id="stop" class="secondary" disabled>停止</button></div></section>
<section class="card"><div class="step">2　處理進度</div><div id="status" class="status">尚未開始。</div><div class="progress"><div id="bar" class="bar"></div></div><div id="meta" class="meta">0 / 0 頁｜OCR 0｜錯誤 0</div><pre id="log">等待工作紀錄…</pre></section>
<section class="card"><div class="step">3　下載來源檔</div><p class="note"><strong>正常分析只上傳合併後的 source_document_clean.md。</strong>它同時包含主需求書與選填文件，並標記文件角色、原檔名及各自頁碼；其他三檔只供追溯。</p><div id="files" class="files"><span class="note">完成驗證後會顯示下載連結。</span></div></section>
</main><script>
let jobId=null,timer=null;const $=id=>document.getElementById(id);
async function refresh(){if(!jobId)return;const r=await fetch('/api/status?id='+encodeURIComponent(jobId));if(!r.ok)return;const s=await r.json();
$('status').textContent=s.message;$('status').className='status '+(s.state==='complete'?'ok':s.state==='failed'?'bad':'');$('bar').style.width=s.percent+'%';$('meta').textContent=`${s.done} / ${s.total} 頁｜OCR ${s.review}｜錯誤 ${s.failures}`;$('log').textContent=s.log.join('\n')||'等待工作紀錄…';$('log').scrollTop=$('log').scrollHeight;
$('stop').disabled=s.state!=='running';$('start').disabled=s.state==='running';$('files').innerHTML=s.files.length?s.files.map(n=>`<a class="filelink" href="/api/file?id=${encodeURIComponent(jobId)}&name=${encodeURIComponent(n)}">下載 ${n}</a>`).join(''):'<span class="note">完成驗證後會顯示下載連結。</span>';if(s.state==='complete'||s.state==='failed'){clearInterval(timer);timer=null}}
$('start').onclick=async()=>{const f=$('pdf').files[0];if(!f){alert('請先選擇主需求書 PDF。');return}const data=new FormData();data.append('pdf',f);for(const review of $('reviews').files)data.append('reviews',review);$('start').disabled=true;$('status').textContent='正在上傳到本機處理程序…';const r=await fetch('/api/start',{method:'POST',body:data});const j=await r.json();if(!r.ok){alert(j.error||'無法開始');$('start').disabled=false;return}jobId=j.id;if(timer)clearInterval(timer);timer=setInterval(refresh,1000);refresh()};
$('stop').onclick=async()=>{if(!jobId)return;await fetch('/api/stop?id='+encodeURIComponent(jobId),{method:'POST'});refresh()};
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "DoclingLocalUI/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: Any, status: int = 200) -> None:
        self.send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            self.send_bytes(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/status":
            job_id = query.get("id", [""])[0]
            try:
                self.send_json(public_job(job_id))
            except KeyError:
                self.send_json({"error": "找不到工作。"}, HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/file":
            job_id = query.get("id", [""])[0]
            name = query.get("name", [""])[0]
            if name not in OUTPUT_FILES:
                self.send_json({"error": "不允許的檔案。"}, HTTPStatus.BAD_REQUEST)
                return
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                path = Path(job["output"]) / name if job else None
            if not path or not path.is_file():
                self.send_json({"error": "檔案尚未建立。"}, HTTPStatus.NOT_FOUND)
                return
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_json({"error": "找不到頁面。"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        global ACTIVE_JOB
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/stop":
            job_id = query.get("id", [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                process = job.get("process") if job else None
            if process and process.poll() is None:
                process.terminate()
                set_job(job_id, state="stopped", message="已停止；重新上傳同一 PDF 即可續跑。")
            self.send_json({"ok": True})
            return
        if parsed.path != "/api/start":
            self.send_json({"error": "找不到操作。"}, HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self.send_json({"error": "PDF 大小不合法或超過 1 GB。"}, HTTPStatus.BAD_REQUEST)
            return
        with JOBS_LOCK:
            if ACTIVE_JOB and JOBS.get(ACTIVE_JOB, {}).get("state") == "running":
                self.send_json({"error": "已有一組文件正在處理。"}, HTTPStatus.CONFLICT)
                return
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")},
        )
        primary_items = form_items(form, "pdf")
        if len(primary_items) != 1 or not getattr(primary_items[0], "filename", ""):
            self.send_json({"error": "請提供一份主需求書 PDF。"}, HTTPStatus.BAD_REQUEST)
            return
        RUNS_ROOT.mkdir(parents=True, exist_ok=True)
        upload_items = [(primary_items[0], "primary_requirements")]
        upload_items.extend((item, "review_comments") for item in form_items(form, "reviews"))
        try:
            documents = [
                save_uploaded_pdf(item, role, index)
                for index, (item, role) in enumerate(upload_items, start=1)
            ]
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        package_hash = hashlib.sha256()
        for document in documents:
            package_hash.update(document["role"].encode("utf-8"))
            package_hash.update(document["sha256"].encode("ascii"))
        job_id = package_hash.hexdigest()[:16]
        output = RUNS_ROOT / "packages" / f"{safe_stem(documents[0]['original_name'])}-{job_id}"
        output.mkdir(parents=True, exist_ok=True)
        with JOBS_LOCK:
            JOBS[job_id] = {
                "name": documents[0]["original_name"],
                "output": str(output),
                "documents": documents,
                "state": "queued",
                "message": f"準備啟動 Docling，共 {len(documents)} 份文件。",
                "log": deque(maxlen=240),
                "process": None,
            }
            ACTIVE_JOB = job_id
        threading.Thread(target=process_job, args=(job_id,), daemon=True).start()
        self.send_json({"id": job_id})


def main() -> int:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        webbrowser.open(f"http://{HOST}:{PORT}/")
        return 0
    threading.Timer(0.8, lambda: webbrowser.open(f"http://{HOST}:{PORT}/")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
