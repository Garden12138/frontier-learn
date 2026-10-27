import base64
import hashlib
import json
from urllib.parse import parse_qs, unquote, urlsplit

from app.ingestion.http_reader import ReadResponse


class WriteFixture:
    def __init__(self, repository: str = "sample/notes") -> None:
        self.repository = repository
        self.base = "a" * 40
        self.default_branch = "main"
        self.trees: dict[str, dict[str, str]] = {}
        self.refs: dict[str, str] = {"main": self.base}
        self.files: dict[tuple[str, str], str] = {}
        self.commits: dict[str, dict[str, object]] = {}
        self.pulls: list[dict[str, object]] = []
        self.calls: list[tuple[str, str]] = []
        self.lose_pr_response = False
        self.lose_ref_response = False
        self.denied = False

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        max_bytes: int,
        content: bytes = b"",
    ) -> ReadResponse:
        parsed = urlsplit(url)
        path = unquote(parsed.path.removeprefix("/repos/" + self.repository))
        query = parse_qs(parsed.query)
        self.calls.append((method, path))
        data = json.loads(content) if content else {}
        status = 200
        result: dict[str, object] = {}
        if self.denied:
            return ReadResponse(403, {}, b"{}")
        if path == "":
            result = {"default_branch": self.default_branch}
        elif path.startswith("/git/ref/heads/"):
            branch = path.removeprefix("/git/ref/heads/")
            if branch not in self.refs:
                status = 404
            else:
                result = {"object": {"sha": self.refs[branch]}}
        elif path == "/git/refs":
            assert method == "POST"
            branch = data["ref"].removeprefix("refs/heads/")
            if branch in self.refs:
                return ReadResponse(422, {}, b"{}")
            self.refs[branch] = data["sha"]
            status, result = 201, {"object": {"sha": data["sha"]}}
            if self.lose_ref_response:
                self.lose_ref_response = False
                status = 503
        elif path.startswith("/contents/"):
            assert method == "GET", "No remote file update API is authorized"
            file = path.removeprefix("/contents/")
            ref = query["ref"][0]
            ref = self.refs.get(ref, ref)
            text = self.files.get((ref, file))
            if text is None:
                status = 404
            else:
                result = {
                    "type": "file",
                    "encoding": "base64",
                    "sha": hashlib.sha1(text.encode()).hexdigest(),
                    "content": base64.b64encode(text.encode()).decode(),
                }
        elif path == "/git/trees":
            assert data["base_tree"] in self.trees
            files = {**self.trees[data["base_tree"]]}
            for entry in data["tree"]:
                files[entry["path"]] = entry["content"]
            tree_sha = hashlib.sha1(json.dumps(files, sort_keys=True).encode()).hexdigest()
            self.trees[tree_sha] = files
            status, result = 201, {"sha": tree_sha}
        elif path.startswith("/git/trees/"):
            tree_sha = path.removeprefix("/git/trees/")
            result = {
                "truncated": False,
                "tree": [
                    {
                        "path": file,
                        "mode": "100644",
                        "type": "blob",
                        "sha": hashlib.sha1(text.encode()).hexdigest(),
                    }
                    for file, text in self.trees[tree_sha].items()
                ],
            }
        elif path == "/git/commits":
            commit_sha = hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()
            self.commits[commit_sha] = {
                "message": data["message"],
                "parents": [{"sha": data["parents"][0]}],
                "tree": {"sha": data["tree"]},
            }
            for file, text in self.trees[data["tree"]].items():
                self.files[(commit_sha, file)] = text
            status, result = 201, {"sha": commit_sha}
        elif path.startswith("/git/commits/"):
            commit_sha = path.removeprefix("/git/commits/")
            if commit_sha not in self.commits:
                files = {
                    file: text for (ref, file), text in self.files.items() if ref == commit_sha
                }
                tree_sha = hashlib.sha1(json.dumps(files, sort_keys=True).encode()).hexdigest()
                self.trees[tree_sha] = files
                result = {"tree": {"sha": tree_sha}}
            else:
                result = self.commits[commit_sha]
        elif path == "/pulls":
            if method == "GET":
                return ReadResponse(200, {}, json.dumps(self.pulls).encode())
            status = 201
            result = {
                "number": len(self.pulls) + 1,
                "body": data["body"],
                "merged": False,
                "head": {
                    "ref": data["head"],
                    "sha": self.refs[data["head"]],
                    "repo": {"full_name": self.repository},
                },
                "base": {"ref": data["base"], "repo": {"full_name": self.repository}},
            }
            self.pulls.append(result)
            if self.lose_pr_response:
                self.lose_pr_response = False
                status = 503
        elif path.startswith("/pulls/"):
            result = self.pulls[int(path.rsplit("/", 1)[1]) - 1]
        else:
            raise AssertionError(f"Unexpected fixture operation: {method} {path}")
        return ReadResponse(status, {}, json.dumps(result).encode())
