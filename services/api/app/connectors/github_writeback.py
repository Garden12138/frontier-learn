"""Single-file, deterministic branch/PR writes. No default-branch update API exists here."""

import base64
import binascii
import json
import re
from typing import Protocol
from urllib.parse import quote, urlencode

from pydantic import SecretStr

from app.connectors.github import repository_ref
from app.core.errors import Problem
from app.ingestion.http_reader import ReadResponse


class WriteTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        max_bytes: int,
        content: bytes = b"",
    ) -> ReadResponse: ...


def sha(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{40}", value):
        raise Problem(502, "GITHUB_INVALID_RESPONSE", "仓库版本数据无效。")
    return value


def note_path(value: str) -> str:
    parts = value.split("/")
    if (
        not value.endswith((".md", ".markdown"))
        or len(value) > 200
        or any(
            not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", p) or p in {".", ".."} for p in parts
        )
        or any(p.lower() in {"node_modules", "vendor"} for p in parts)
    ):
        raise Problem(
            400, "WRITE_PATH", "笔记路径仅支持普通 Markdown 文件，请避开隐藏目录和特殊字符。"
        )
    return value


class GitHubWriteback:
    def __init__(self, repository: str, token: SecretStr, transport: WriteTransport) -> None:
        self.repository = repository_ref(repository)
        self.token, self.transport, self.requests = token, transport, 0

    async def call(
        self,
        method: str,
        suffix: str = "",
        data: dict[str, object] | None = None,
        *,
        missing: bool = False,
    ) -> object:
        if method not in {"GET", "POST"}:
            raise Problem(400, "WRITE_METHOD", "禁止更新已有分支或远端文件。")
        self.requests += 1
        if self.requests > 24:
            raise Problem(413, "WRITE_REQUEST_LIMIT", "本次写回已达到网络请求上限。")
        response = await self.transport.request(
            method,
            f"https://api.github.com/repos/{self.repository}{suffix}",
            headers={
                "Authorization": f"Bearer {self.token.get_secret_value()}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            max_bytes=300000,
            content=json.dumps(data, ensure_ascii=False).encode() if data else b"",
        )
        if missing and response.status == 404:
            return None
        if response.status in {401, 403, 404}:
            raise Problem(403, "WRITE_PERMISSION", "仓库写入授权不足或已失效；草稿已保留。")
        if response.status in {409, 422}:
            raise Problem(409, "WRITE_CONFLICT", "仓库或分支已变化，请核对后重试；草稿已保留。")
        if response.status not in {200, 201}:
            raise Problem(
                503, "WRITE_UNAVAILABLE", "写回暂时失败；可重试，系统会先核对既有分支和 PR。"
            )
        try:
            return json.loads(response.body)
        except (ValueError, UnicodeError):
            raise Problem(502, "GITHUB_INVALID_RESPONSE", "仓库响应无效。") from None

    async def obj(
        self, method: str, suffix: str = "", data: dict[str, object] | None = None
    ) -> dict[str, object]:
        value = await self.call(method, suffix, data)
        if not isinstance(value, dict):
            raise Problem(502, "GITHUB_INVALID_RESPONSE", "仓库响应结构无效。")
        return value

    async def head(self, branch: str) -> str:
        obj = await self.obj("GET", "/git/ref/heads/" + quote(branch, safe=""))
        ref = obj.get("object")
        return sha(ref.get("sha") if isinstance(ref, dict) else None)

    async def file(self, path: str, ref: str) -> tuple[str | None, str]:
        obj = await self.call(
            "GET",
            "/contents/" + quote(note_path(path), safe="/") + "?" + urlencode({"ref": ref}),
            missing=True,
        )
        if obj is None:
            return None, ""
        if (
            not isinstance(obj, dict)
            or obj.get("type") != "file"
            or obj.get("encoding") != "base64"
            or not isinstance(obj.get("content"), str)
        ):
            raise Problem(400, "WRITE_FILE_TYPE", "目标不是可编辑的普通文本文件。")
        try:
            raw = base64.b64decode(str(obj["content"]).replace("\n", ""), validate=True)
            if len(raw) > 50000:
                raise ValueError
            return sha(obj.get("sha")), raw.decode("utf-8")
        except (ValueError, UnicodeError, binascii.Error):
            raise Problem(413, "WRITE_FILE_LIMIT", "目标文件过大或无法解码，请手工整理。") from None

    async def existing_pull(self, branch: str, base: str, marker: str) -> dict[str, object] | None:
        pulls = await self.call(
            "GET",
            "/pulls?"
            + urlencode(
                {
                    "state": "all",
                    "head": self.repository.split("/")[0] + ":" + branch,
                    "base": base,
                    "per_page": 100,
                    "sort": "created",
                    "direction": "asc",
                }
            ),
        )
        if not isinstance(pulls, list):
            raise Problem(502, "GITHUB_INVALID_RESPONSE", "PR 列表结构无效。")
        for pull in pulls:
            if (
                isinstance(pull, dict)
                and marker in str(pull.get("body", ""))
                and isinstance(pull.get("head"), dict)
                and pull["head"].get("ref") == branch
                and isinstance(pull.get("base"), dict)
                and pull["base"].get("ref") == base
            ):
                return pull
        if len(pulls) >= 100:
            raise Problem(409, "PR_LIST_LIMIT", "专用分支 PR 记录过多，请手工核对。")
        return None

    async def create_pr(
        self,
        *,
        branch: str,
        base: str,
        base_sha: str,
        path: str,
        file_sha: str | None,
        markdown: str,
        marker: str,
    ) -> dict[str, object]:
        existing = await self.existing_pull(branch, base, marker)
        if existing is not None:
            return existing
        repository = await self.obj("GET")
        if (
            branch == base
            or repository.get("default_branch") != base
            or await self.head(base) != base_sha
        ):
            raise Problem(409, "WRITE_BASE_CONFLICT", "默认分支已变化，请保留草稿并重新预览 Diff。")
        base_commit = await self.obj("GET", "/git/commits/" + base_sha)
        base_tree = base_commit.get("tree")
        tree_sha = sha(base_tree.get("sha") if isinstance(base_tree, dict) else None)
        tree = await self.obj("GET", "/git/trees/" + tree_sha + "?recursive=1")
        entries = tree.get("tree")
        if tree.get("truncated") is not False or not isinstance(entries, list):
            raise Problem(413, "WRITE_TREE_LIMIT", "仓库树不完整，请缩小仓库或下载后手工整理。")
        target = None
        ancestors = {"/".join(path.split("/")[:index]) for index in range(1, len(path.split("/")))}
        for entry in entries:
            if not isinstance(entry, dict):
                raise Problem(502, "GITHUB_INVALID_RESPONSE", "仓库树结构无效。")
            if entry.get("path") in ancestors and entry.get("mode") != "040000":
                raise Problem(409, "WRITE_FILE_TYPE", "目标目录包含符号链接或子模块，不能写回。")
            if entry.get("path") == path:
                target = entry
        if (
            (target is None) != (file_sha is None)
            or target is not None
            and (target.get("mode") != "100644" or target.get("sha") != file_sha)
        ):
            raise Problem(409, "WRITE_FILE_TYPE", "目标文件类型或版本与审核时不同。")
        # Git objects are unreferenced until a new ref is created. Never update an existing ref.
        new_tree = await self.obj(
            "POST",
            "/git/trees",
            {
                "base_tree": tree_sha,
                "tree": [{"path": path, "mode": "100644", "type": "blob", "content": markdown}],
            },
        )
        expected_tree = sha(new_tree.get("sha"))
        remote = await self.call("GET", "/git/ref/heads/" + quote(branch, safe=""), missing=True)
        if remote is None:
            commit = await self.obj(
                "POST",
                "/git/commits",
                {"message": marker, "tree": expected_tree, "parents": [base_sha]},
            )
            await self.obj(
                "POST", "/git/refs", {"ref": "refs/heads/" + branch, "sha": sha(commit.get("sha"))}
            )
        else:
            obj = remote.get("object") if isinstance(remote, dict) else None
            branch_sha = sha(obj.get("sha") if isinstance(obj, dict) else None)
            commit = await self.obj("GET", "/git/commits/" + branch_sha)
            parents, commit_tree = commit.get("parents"), commit.get("tree")
            if (
                commit.get("message") != marker
                or not isinstance(parents, list)
                or len(parents) != 1
                or not isinstance(parents[0], dict)
                or parents[0].get("sha") != base_sha
                or not isinstance(commit_tree, dict)
                or commit_tree.get("sha") != expected_tree
            ):
                raise Problem(
                    409, "WRITE_BRANCH_CONFLICT", "专用分支存在其他更改，不会覆盖或提交未审核变更。"
                )
        return await self.obj(
            "POST",
            "/pulls",
            {
                "title": "FrontierLearn: reviewed learning note",
                "head": branch,
                "base": base,
                "body": marker + "\nUser reviewed this draft. Please review before merging.",
            },
        )
