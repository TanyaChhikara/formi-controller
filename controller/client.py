"""Thin HTTP client for the simulator. Retries transport errors and 5xx; 4xx are returned to the caller,
because a 4xx is information (stale base, duplicate id, policy refusal), not a glitch."""
from __future__ import annotations

import time

import httpx


class SimError(Exception):
    def __init__(self, status, body):
        super().__init__(f"{status}: {body}")
        self.status, self.body = status, body
        self.code = body.get("error") if isinstance(body, dict) else None


class Sim:
    def __init__(self, url: str):
        self.c = httpx.Client(base_url=url, timeout=300)

    def _req(self, method, path, **kw):
        delay = 0.5
        for attempt in range(8):
            try:
                r = self.c.request(method, path, **kw)
            except httpx.TransportError:
                if attempt == 7:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 10)
                continue
            if r.status_code >= 500 and attempt < 7:
                time.sleep(delay)
                delay = min(delay * 2, 10)
                continue
            if r.status_code >= 400:
                try:
                    body = r.json()
                except ValueError:
                    body = {"error": r.text}
                raise SimError(r.status_code, body)
            return r

    def get(self, path, **params):
        return self._req("GET", path, params=params).json()

    def post(self, path, body):
        return self._req("POST", path, json=body).json()

    def put(self, path, body):
        return self._req("PUT", path, json=body).json()

    def chunk_lines(self, n):
        return self._req("GET", f"/events/chunks/{n}").content.splitlines()

    def wait_ready(self, timeout=600):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if self.c.get("/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(1)
        raise RuntimeError("simulator not reachable")

