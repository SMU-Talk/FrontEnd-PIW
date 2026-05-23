from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "chatbot.sqlite3"
SESSION_COOKIE = "smu_chat_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
SECRET_KEY = os.environ.get("SMU_CHAT_SECRET", "dev-secret-change-me")


def now() -> int:
    return int(time.time())


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                guest_name TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            """
        )


def password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        180_000,
    ).hex()


def sign(value: str) -> str:
    digest = hmac.new(SECRET_KEY.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}.{digest}"


def unsign(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    session_id, signature = value.rsplit(".", 1)
    expected = sign(session_id).rsplit(".", 1)[1]
    if not hmac.compare_digest(signature, expected):
        return None
    return session_id


def clean_expired_sessions() -> None:
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))


def create_session(user_id: int | None = None, guest_name: str | None = None) -> str:
    session_id = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, user_id, guest_name, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, user_id, guest_name, now(), now() + SESSION_TTL_SECONDS),
        )
    return session_id


def get_session(session_id: str | None) -> sqlite3.Row | None:
    if not session_id:
        return None
    clean_expired_sessions()
    with db() as conn:
        return conn.execute(
            """
            SELECT sessions.*, users.username, users.display_name
            FROM sessions
            LEFT JOIN users ON users.id = sessions.user_id
            WHERE sessions.id = ?
            """,
            (session_id,),
        ).fetchone()


FAQS = [
    {
        "keywords": ["입학", "수시", "정시", "전형", "모집"],
        "answer": "입학 관련 질문은 모집 시기, 전형 유형, 제출 서류가 핵심입니다. 실제 일정과 요강은 매년 바뀌므로 상명대학교 입학처 공지사항을 기준으로 확인하는 것이 가장 안전합니다.",
    },
    {
        "keywords": ["등록금", "장학", "장학금", "국가장학"],
        "answer": "등록금과 장학금은 학과, 학년, 장학 유형에 따라 달라집니다. 성적장학, 국가장학, 교내외 장학을 함께 확인하고, 신청 기간을 놓치지 않는 것이 중요합니다.",
    },
    {
        "keywords": ["학사", "수강", "수강신청", "휴학", "복학", "졸업"],
        "answer": "학사 업무는 학사 일정과 포털 공지가 우선입니다. 수강신청, 휴학, 복학, 졸업 요건은 소속 캠퍼스와 학과 기준이 다를 수 있어 학사 공지와 학과 사무실 안내를 함께 확인해 주세요.",
    },
    {
        "keywords": ["캠퍼스", "서울", "천안", "위치", "교통"],
        "answer": "상명대학교는 서울캠퍼스와 천안캠퍼스가 있습니다. 방문 목적에 따라 캠퍼스를 먼저 확인하고, 대중교통 또는 셔틀 안내를 함께 확인하면 이동 계획을 세우기 좋습니다.",
    },
    {
        "keywords": ["도서관", "열람실", "자료", "논문"],
        "answer": "도서관 이용은 자료 검색, 열람실, 전자자료, 논문 DB 이용으로 나눠 볼 수 있습니다. 로그인 권한이 필요한 서비스는 학교 계정 또는 도서관 인증 절차가 필요할 수 있습니다.",
    },
    {
        "keywords": ["포털", "샘물", "계정", "비밀번호", "로그인"],
        "answer": "학교 포털이나 샘물 시스템 로그인 문제는 계정 상태, 비밀번호, 브라우저 환경을 먼저 확인해 보세요. 해결되지 않으면 학교 IT 또는 행정 지원 창구로 문의하는 것이 빠릅니다.",
    },
]


def make_bot_reply(user_message: str, session: sqlite3.Row | None) -> str:
    text = user_message.strip()
    lowered = text.lower()
    display_name = "게스트"
    if session:
        display_name = session["display_name"] or session["guest_name"] or "게스트"

    if not text:
        return "질문을 입력해 주시면 상명대학교 생활, 입학, 학사, 장학, 캠퍼스 정보를 중심으로 도와드릴게요."

    if any(word in lowered for word in ["안녕", "hello", "hi"]):
        return f"안녕하세요, {display_name}님. SMU Talk입니다. 입학, 학사, 장학, 캠퍼스, 도서관, 포털 관련 질문을 편하게 입력해 주세요."

    for item in FAQS:
        if any(keyword in lowered for keyword in item["keywords"]):
            return item["answer"]

    return (
        "제가 바로 확정 답변을 드리기 어려운 질문입니다. "
        "질문을 '입학', '학사', '장학금', '캠퍼스', '도서관', '포털'처럼 주제와 함께 다시 적어주시면 더 정확히 안내할 수 있어요. "
        "공식 일정이나 규정은 최신 공지를 반드시 확인해 주세요."
    )


class AppHandler(SimpleHTTPRequestHandler):
    server_version = "SMUChatbot/1.0"

    def translate_path(self, path: str) -> str:
        if path == "/":
            return str(STATIC_DIR / "index.html")
        return str(STATIC_DIR / path.lstrip("/"))

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/api/me"):
            self.handle_me()
            return
        if self.path.startswith("/api/history"):
            self.handle_history()
            return
        super().do_GET()

    def do_POST(self) -> None:
        routes = {
            "/api/register": self.handle_register,
            "/api/login": self.handle_login,
            "/api/guest": self.handle_guest,
            "/api/logout": self.handle_logout,
            "/api/chat": self.handle_chat,
            "/api/clear": self.handle_clear,
        }
        handler = routes.get(self.path)
        if not handler:
            self.json_response({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        handler()

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def json_response(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        cookies: list[str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookies:
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def current_session(self) -> sqlite3.Row | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        signed = cookie.get(SESSION_COOKIE)
        session_id = unsign(signed.value if signed else None)
        return get_session(session_id)

    def auth_cookie(self, session_id: str, max_age: int = SESSION_TTL_SECONDS) -> str:
        return (
            f"{SESSION_COOKIE}={sign(session_id)}; "
            f"Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"
        )

    def handle_me(self) -> None:
        session = self.current_session()
        if not session:
            self.json_response({"authenticated": False, "mode": None, "name": None})
            return
        mode = "user" if session["user_id"] else "guest"
        name = session["display_name"] if session["user_id"] else session["guest_name"]
        self.json_response({"authenticated": True, "mode": mode, "name": name})

    def handle_history(self) -> None:
        session = self.current_session()
        if not session:
            self.json_response({"messages": []})
            return
        with db() as conn:
            rows = conn.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                LIMIT 100
                """,
                (session["id"],),
            ).fetchall()
        self.json_response({"messages": [dict(row) for row in rows]})

    def handle_register(self) -> None:
        payload = self.read_json()
        username = str(payload.get("username", "")).strip().lower()
        password = str(payload.get("password", ""))
        display_name = str(payload.get("displayName", "")).strip() or username

        if len(username) < 3 or len(password) < 6:
            self.json_response(
                {"error": "아이디는 3자 이상, 비밀번호는 6자 이상이어야 합니다."},
                HTTPStatus.BAD_REQUEST,
            )
            return

        salt = secrets.token_hex(16)
        try:
            with db() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO users (username, password_hash, salt, display_name, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (username, password_hash(password, salt), salt, display_name, now()),
                )
                user_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            self.json_response({"error": "이미 사용 중인 아이디입니다."}, HTTPStatus.CONFLICT)
            return

        session_id = create_session(user_id=user_id)
        self.json_response(
            {"ok": True, "name": display_name, "mode": "user"},
            cookies=[self.auth_cookie(session_id)],
        )

    def handle_login(self) -> None:
        payload = self.read_json()
        username = str(payload.get("username", "")).strip().lower()
        password = str(payload.get("password", ""))

        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if not user or not hmac.compare_digest(user["password_hash"], password_hash(password, user["salt"])):
            self.json_response({"error": "아이디 또는 비밀번호를 확인해 주세요."}, HTTPStatus.UNAUTHORIZED)
            return

        session_id = create_session(user_id=user["id"])
        self.json_response(
            {"ok": True, "name": user["display_name"], "mode": "user"},
            cookies=[self.auth_cookie(session_id)],
        )

    def handle_guest(self) -> None:
        payload = self.read_json()
        guest_name = str(payload.get("guestName", "")).strip()[:30] or "게스트"
        session_id = create_session(guest_name=guest_name)
        self.json_response(
            {"ok": True, "name": guest_name, "mode": "guest"},
            cookies=[self.auth_cookie(session_id)],
        )

    def handle_logout(self) -> None:
        session = self.current_session()
        if session:
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (session["id"],))
        expired = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        self.json_response({"ok": True}, cookies=[expired])

    def handle_clear(self) -> None:
        session = self.current_session()
        if session:
            with db() as conn:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session["id"],))
        self.json_response({"ok": True})

    def handle_chat(self) -> None:
        session = self.current_session()
        if not session:
            self.json_response({"error": "로그인 또는 게스트 모드로 입장해 주세요."}, HTTPStatus.UNAUTHORIZED)
            return

        payload = self.read_json()
        message = str(payload.get("message", "")).strip()
        if not message:
            self.json_response({"error": "메시지를 입력해 주세요."}, HTTPStatus.BAD_REQUEST)
            return

        reply = make_bot_reply(message, session)
        with db() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (session["id"], message, now()),
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
                (session["id"], reply, now()),
            )
        self.json_response({"reply": reply})


def run() -> None:
    init_db()
    host = os.environ.get("SMU_CHAT_HOST", "127.0.0.1")
    port = int(os.environ.get("SMU_CHAT_PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), AppHandler)
    print(f"SMU chatbot is running at http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run()
