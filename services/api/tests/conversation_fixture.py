"""Synthetic share fixtures. Never imported by the production app or worker."""

from app.ingestion.http_reader import ReadResponse

SHARE_URL = "https://chatgpt.com/share/11111111-1111-4111-8111-111111111111"
DENIED_URL = "https://chatgpt.com/share/22222222-2222-4222-8222-222222222222"
UNPARSEABLE_URL = "https://chatgpt.com/share/33333333-3333-4333-8333-333333333333"
SHARE_HTML = """<!doctype html><html><head><title>合成对话：BPE 与验证</title></head><body>
<main><article data-message-author-role="user">
<p>BPE 的合并规则有什么适用条件？请给出可核实的依据。</p></article>
<article data-message-author-role="assistant">
<p>BPE merges frequent token pairs. This answer is unverified.</p>
<pre><code>example = 'illustration only'\n# Do not execute imported code.</code></pre>
<p hidden>HIDDEN_SECRET</p><form><p>FORM_SECRET</p></form>
<script>INJECTION_SECRET</script></article>
<article data-message-author-role="user"><p>如何用一个反例检查刚才的解释？</p></article>
</main></body></html>"""
PASTED_TEXT = """用户：BPE 的合并规则有什么适用条件？请给出可核实的依据。
助手：BPE merges frequent token pairs. This is an unverified answer.
```python
example = 'illustration only'
User: this is code text, not a new message
```
用户：如何用一个反例检查刚才的解释？
"""


class ShareFixtureReader:
    def __init__(self, body: str = SHARE_HTML, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.calls: list[str] = []

    async def get(self, url: str, *, headers: dict[str, str], max_bytes: int) -> ReadResponse:
        self.calls.append(url)
        assert "Authorization" not in headers and "Cookie" not in headers
        status = 403 if url == DENIED_URL else self.status
        body = "<main>Login or dynamic page only</main>" if url == UNPARSEABLE_URL else self.body
        return ReadResponse(status, {"content-type": "text/html; charset=utf-8"}, body.encode())
