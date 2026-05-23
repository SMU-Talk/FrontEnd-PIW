
## 실행

```powershell
python app.py
```

브라우저에서 `http://127.0.0.1:8000`으로 접속합니다.

## 운영 참고

개발 기본 비밀키는 `SMU_CHAT_SECRET` 환경 변수로 바꿀 수 있습니다.

```powershell
$env:SMU_CHAT_SECRET="긴-랜덤-문자열"
python app.py
```

포트 변경은 `SMU_CHAT_PORT`로 지정합니다.

```powershell
$env:SMU_CHAT_PORT="8080"
python app.py
```
