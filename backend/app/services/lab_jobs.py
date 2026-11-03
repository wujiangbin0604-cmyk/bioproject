"""有界现场实验进程管理。持久化记录与历史正式results指针相互独立。"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

import psutil

from backend.app.lab_config import PROJECT, TASK_ROOT, TERMINAL, ExperimentRequest, atomic_json, limits, read_json
from backend.app.services.lab_resources import available_memory_bytes


class TaskConflict(ValueError):
    pass


class LabJobs:
    def __init__(self, root: Path = TASK_ROOT):
        self.root = root
        self.lock = threading.RLock()
        self.processes = {}

    def directory(self, task_id):
        if not re.fullmatch(r"[0-9a-f]{32}", task_id):
            raise FileNotFoundError("无效任务ID")
        path = self.root / task_id
        if not (path / "state.json").is_file():
            raise FileNotFoundError("任务不存在")
        return path

    def get(self, task_id):
        state = read_json(self.directory(task_id) / "state.json")
        if state["status"] not in TERMINAL and task_id not in self.processes:
            pid = state.get("owner_pid")
            try:
                alive = bool(pid and psutil.Process(pid).create_time() == state.get("owner_started"))
            except psutil.NoSuchProcess:
                alive = False
            if not alive:
                state.update(status="interrupted", message="服务或工作进程已停止；保留已完成结果，不自动重训", revision=state["revision"]+1)
                atomic_json(self.directory(task_id) / "state.json", state)
        if state["status"] not in TERMINAL:
            state["elapsed_seconds"] = (datetime.now(timezone.utc)-datetime.fromisoformat(state["created_at"])).total_seconds()
        return state

    def list(self):
        if not self.root.exists():
            return []
        items = []
        for directory in self.root.iterdir():
            if directory.is_dir() and re.fullmatch(r"[0-9a-f]{32}", directory.name) and (directory / "state.json").is_file():
                state = self.get(directory.name)
                items.append({k: v for k, v in state.items() if k not in {"folds", "rounds", "summary"}})
        return sorted(items, key=lambda row: row["created_at"], reverse=True)

    def _acquire(self):
        self.root.mkdir(parents=True, exist_ok=True)
        handle = (self.root / ".runner.lock").open("a+b")
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0"); handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise TaskConflict("已有现场实验运行；单任务并发限制为1") from exc
        return handle

    def start(self, request: ExperimentRequest):
        with self.lock:
            if len(self.list()) >= limits()["max_saved_tasks"]:
                raise TaskConflict("已达到100条运行记录上限，请管理员归档后再提交")
            guard = self._acquire()
            try:
                minimum = limits()["minimum_available_memory_mb"]
                if available_memory_bytes() < minimum * 1024**2:
                    raise TaskConflict(f"当前主机/容器可用内存不足{minimum} MiB，暂不启动实验")
                if psutil.disk_usage(str(self.root)).free < 1024**3:
                    raise TaskConflict("现场结果目录可用磁盘不足1 GiB，暂不启动实验")
                task_id = uuid4().hex
                directory = self.root / task_id
                directory.mkdir()
                state = {"task_id": task_id, "source": "live_exploratory_development_cv", "status": "queued", "revision": 0,
                         "created_at": datetime.now(timezone.utc).isoformat(), "configuration": request.model_dump(),
                         "owner_pid": os.getpid(), "owner_started": psutil.Process().create_time(),
                         "completed_folds": 0, "total_folds": 100 if request.cv_mode == "repeated" else 5,
                         "folds": [], "rounds": [], "elapsed_seconds": 0, "error": None, "message": "任务已创建", "limits": limits()}
                atomic_json(directory / "state.json", state)
                atomic_json(directory / "configuration.json", state)
                env = os.environ.copy()
                for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
                    env[variable] = "1"
                env["PYTHONUTF8"] = "1"
                output = (directory / "worker.log").open("w", encoding="utf-8")
                try:
                    process = subprocess.Popen([sys.executable, "-m", "backend.app.lab_worker", str(directory)],
                                               cwd=PROJECT, env=env, stdout=output, stderr=subprocess.STDOUT,
                                               creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == "nt" else 0)
                finally:
                    output.close()
                state["worker_pid"] = process.pid
                # worker本身记录PID；不覆盖它可能已写入的运行状态。
                self.processes[task_id] = process
                threading.Thread(target=self._monitor, args=(task_id, process, guard), daemon=True).start()
                return state
            except Exception:
                guard.close()
                raise

    def _stop(self, process):
        try:
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in children:
                child.terminate()
            parent.terminate()
            _, alive = psutil.wait_procs([parent, *children], timeout=3)
            for child in alive:
                child.kill()
            process.wait(timeout=3)
        except (psutil.NoSuchProcess, ProcessLookupError):
            pass

    def _finish(self, task_id, status, message):
        path = self.directory(task_id) / "state.json"
        state = read_json(path)
        if state["status"] in TERMINAL:
            return state
        state.update(status=status, message=message, error=message if status == "failed" else None, revision=state["revision"]+1)
        state["elapsed_seconds"] = (datetime.now(timezone.utc)-datetime.fromisoformat(state["created_at"])).total_seconds()
        atomic_json(path, state)
        return state

    def _monitor(self, task_id, process, guard):
        start = time.monotonic()
        cap = limits()
        peak_rss = 0
        try:
            while process.poll() is None:
                try:
                    parent = psutil.Process(process.pid)
                    rss = sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)] if p.is_running())
                    peak_rss = max(peak_rss, rss)
                    reason = ("任务超出运行时间上限" if time.monotonic()-start > cap["timeout_seconds"] else
                              "任务超出内存上限" if rss > cap["memory_limit_mb"]*1024**2 else None)
                    if reason:
                        with self.lock:
                            self._stop(process)
                            self._finish(task_id, "failed", reason)
                        break
                except psutil.NoSuchProcess:
                    break
                except (psutil.Error, OSError) as exc:
                    with self.lock:
                        self._stop(process)
                        self._finish(task_id, "failed", f"资源监控失败，已停止工作进程：{type(exc).__name__}")
                    break
                time.sleep(.5)
            with self.lock:
                self._finish(task_id, "failed", f"工作进程结束但未完成（退出码{process.poll()}）")
        finally:
            with self.lock:
                atomic_json(self.directory(task_id) / "resource_usage.json", {
                    "peak_sampled_rss_mb": peak_rss/1024**2, "monitor_seconds": time.monotonic()-start,
                    "exit_code": process.poll(), "sample_interval_seconds": .5,
                    "memory_limit_mb": cap["memory_limit_mb"], "timeout_seconds": cap["timeout_seconds"],
                    "enforcement": "subprocess_tree_termination_on_sampled_limit_exceeded"})
                self.processes.pop(task_id, None)
                guard.close()

    def cancel(self, task_id):
        with self.lock:
            state = self.get(task_id)
            if state["status"] in TERMINAL:
                return state
            process = self.processes.get(task_id)
            if process is None:
                raise TaskConflict("任务不属于当前API进程；请在创建任务的单worker服务取消")
            self._stop(process)
            return self._finish(task_id, "cancelled", "用户取消任务；已完成折的结果已保留")

    def shutdown(self):
        with self.lock:
            for task_id, process in list(self.processes.items()):
                self._stop(process)
                self._finish(task_id, "interrupted", "API服务关闭，现场工作进程停止；已完成折已保存")
