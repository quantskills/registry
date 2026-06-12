#!/usr/bin/env python3
"""validate_skill.py — quantskills asset 仓库确定性健康检查器(脚本层)。

只做事实判断,不做语义判断。语义判断(标签准确性、敏感内容、文档漂移)交给 AI 层,见 AGENT.md。

用法:
    python scripts/validate_skill.py /path/to/cloned/repo [--json] [--org-repos a,b,c]

退出码: 0 = pass, 1 = warning, 2 = quarantined(含致命问题)
"""
from __future__ import annotations

import argparse
import json
import py_compile
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("缺少依赖: pip install pyyaml")

# ---------------- 配置 ----------------
DECLARATION_BY_TYPE = {"skill": "SKILL.md", "agent": "AGENT.md"}
ASSET_TYPES = {"skill", "agent"}
CATEGORIES = {
    "trader-research",
    "factor",
    "data-api",
    "replication",
    "monitor",
    "analyst",
    "tooling",
    "research-agent",
    "workflow-agent",
    "review-agent",
    "data-agent",
    "automation-agent",
}
STATUSES = {"draft", "stable", "deprecated"}
PLATFORMS = {"claude-code", "codex", "openclaw", "cursor", "workbuddy"}
VALIDATION_LEVELS = {"listed", "runnable", "verified"}
MAINTAINER_TYPES = {"official", "community"}
REQUIRED_FM_FIELDS = [
    "project_type",
    "category",
    "tags",
    "platforms",
    "status",
    "validation_level",
    "maintainer_type",
    "summary_zh",
    "summary_en",
]

MAX_FILE_WARN = 2 * 1024 * 1024      # >2MB warning
MAX_FILE_FAIL = 10 * 1024 * 1024     # >10MB quarantine(违反 Git 卫生)
DATA_EXT_WATCHLIST = {".csv", ".parquet", ".json", ".jsonl", ".xlsx", ".db", ".sqlite", ".zip", ".gz"}

# trader-research 类目硬门槛:两类声明缺一即 quarantine
DISCLAIMER_PATTERNS = [r"不构成任何投资建议", r"not\s+(?:constitute\s+)?investment\s+advice"]
AFFILIATION_PATTERNS = [r"不代表|非官方|不隶属", r"not\s+affiliated"]

# 轻量泄密正则(重型扫描由 workflow 里的 gitleaks 负责)
SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub PAT"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "API secret key 形态字符串"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
]

# markdown 里的相对路径引用:链接、图片、以及反引号里的 scripts/references/collectors/validation 路径
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)\)")
BACKTICK_PATH_RE = re.compile(r"`((?:\.\./)+[\w./\-]+|(?:scripts|references|collectors|validation|agents)/[\w./\-]+)`")


class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, level: str, check: str, detail: str) -> None:
        self.items.append({"level": level, "check": check, "detail": detail})

    @property
    def health(self) -> str:
        levels = {i["level"] for i in self.items}
        if "fail" in levels:
            return "quarantined"
        if "warn" in levels:
            return "warning"
        return "healthy"


def declaration_info(repo: Path) -> tuple[str | None, str | None]:
    """Return expected asset type and declaration filename for a repo/template."""
    name = repo.name
    if name.startswith("agent-"):
        return "agent", DECLARATION_BY_TYPE["agent"]
    if name.startswith("skill-"):
        return "skill", DECLARATION_BY_TYPE["skill"]
    if (repo / "AGENT.md").is_file() and not (repo / "SKILL.md").is_file():
        return "agent", DECLARATION_BY_TYPE["agent"]
    if (repo / "SKILL.md").is_file():
        return "skill", DECLARATION_BY_TYPE["skill"]
    return None, None


def parse_frontmatter(declaration_md: Path) -> dict | None:
    text = declaration_md.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None


def check_required_files(repo: Path, declaration_file: str | None, rep: Report) -> None:
    required_files = [name for name in (declaration_file, "README.md", "LICENSE") if name]
    if not declaration_file:
        rep.add("fail", "required-files", "缺少声明文件 SKILL.md 或 AGENT.md")
    for name in required_files:
        if not (repo / name).is_file():
            rep.add("fail", "required-files", f"缺少必备文件 {name}")


def check_frontmatter(repo: Path, asset_type: str | None, declaration_file: str | None, rep: Report) -> dict:
    if not declaration_file:
        return {}
    declaration_md = repo / declaration_file
    if not declaration_md.is_file():
        return {}
    fm = parse_frontmatter(declaration_md)
    if fm is None:
        rep.add("fail", "frontmatter", f"{declaration_file} 缺少 YAML frontmatter 或解析失败")
        return {}
    if not fm.get("name"):
        rep.add("fail", "frontmatter", "frontmatter 缺少 name")
    desc = fm.get("description") or ""
    if len(str(desc)) < 60 or "use when" not in str(desc).lower():
        rep.add("warn", "frontmatter", "description 过短或缺少 'Use when ...' 触发场景描述(影响 agent 选用)")
    qs = fm.get("quantSkills") or {}
    for field in REQUIRED_FM_FIELDS:
        if field not in qs:
            rep.add("warn", "frontmatter", f"quantSkills.{field} 缺失")
    if qs.get("project_type") and qs["project_type"] not in ASSET_TYPES:
        rep.add("warn", "frontmatter", f"project_type '{qs['project_type']}' 不在枚举 {sorted(ASSET_TYPES)}")
    if asset_type and qs.get("project_type") and qs["project_type"] != asset_type:
        rep.add("warn", "frontmatter", f"project_type '{qs['project_type']}' 与仓库声明类型 '{asset_type}' 不一致")
    if qs.get("category") and qs["category"] not in CATEGORIES:
        rep.add("warn", "frontmatter", f"category '{qs['category']}' 不在枚举 {sorted(CATEGORIES)}")
    if qs.get("status") and qs["status"] not in STATUSES:
        rep.add("warn", "frontmatter", f"status '{qs['status']}' 不在枚举 {sorted(STATUSES)}")
    if qs.get("validation_level") and qs["validation_level"] not in VALIDATION_LEVELS:
        rep.add("warn", "frontmatter", f"validation_level '{qs['validation_level']}' 不在枚举 {sorted(VALIDATION_LEVELS)}")
    if qs.get("maintainer_type") and qs["maintainer_type"] not in MAINTAINER_TYPES:
        rep.add("warn", "frontmatter", f"maintainer_type '{qs['maintainer_type']}' 不在枚举 {sorted(MAINTAINER_TYPES)}")
    for p in qs.get("platforms") or []:
        if p not in PLATFORMS:
            rep.add("warn", "frontmatter", f"platform '{p}' 不在枚举 {sorted(PLATFORMS)}")
    return fm


def check_path_references(repo: Path, rep: Report) -> None:
    """提到的文件必须真实存在 —— 死链 / 幽灵路径检查。"""
    for md in repo.rglob("*.md"):
        if ".git" in md.parts:
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        refs: dict[str, str] = {}  # path -> "link"(markdown 链接,缺失即 fail) / "mention"(反引号提及,缺失为 warn)
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            refs[target] = "link"
        for target in BACKTICK_PATH_RE.findall(text):
            refs.setdefault(target, "mention")
        for ref, kind in sorted(refs.items()):
            clean = ref.split("#", 1)[0].strip()
            if not clean:
                continue
            resolved = (md.parent / clean).resolve()
            if not resolved.exists():
                root_try = (repo / clean).resolve()
                if root_try.exists():
                    resolved = root_try
            try:
                resolved.relative_to(repo.resolve())
                inside = True
            except ValueError:
                inside = False
            where = md.relative_to(repo)
            if not inside:
                rep.add("warn", "path-refs", f"{where} 引用了仓库外路径(请改为仓库内路径或删除): {ref}")
            elif not resolved.exists():
                level = "fail" if kind == "link" else "warn"
                hint = "链接目标不存在" if kind == "link" else "提及的路径不存在(若为示例/生成物可忽略,建议改写避免歧义)"
                rep.add(level, "path-refs", f"{where} {hint}: {ref}")


def check_git_hygiene(repo: Path, rep: Report) -> None:
    for f in repo.rglob("*"):
        if ".git" in f.parts or not f.is_file():
            continue
        size = f.stat().st_size
        rel = f.relative_to(repo)
        if size > MAX_FILE_FAIL:
            rep.add("fail", "git-hygiene", f"{rel} 大小 {size//1024//1024}MB 超过 10MB 上限")
        elif size > MAX_FILE_WARN and f.suffix.lower() in DATA_EXT_WATCHLIST:
            rep.add("warn", "git-hygiene", f"{rel} 是 >2MB 的数据文件,确认是否应入库")


def check_secrets(repo: Path, rep: Report) -> None:
    for f in repo.rglob("*"):
        if ".git" in f.parts or not f.is_file() or f.stat().st_size > MAX_FILE_WARN:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                rep.add("fail", "secrets", f"{f.relative_to(repo)} 疑似包含 {label}")


def check_trader_disclaimers(repo: Path, fm: dict, declaration_file: str | None, rep: Report) -> None:
    """实名 trader 仓库硬门槛:免责 + 非隶属声明,缺失即 quarantine。"""
    qs = (fm or {}).get("quantSkills") or {}
    if qs.get("category") != "trader-research":
        return
    corpus = ""
    for name in ("README.md", "README.en.md", declaration_file):
        if not name:
            continue
        p = repo / name
        if p.is_file():
            corpus += p.read_text(encoding="utf-8", errors="replace")
    if not any(re.search(pat, corpus, re.IGNORECASE) for pat in DISCLAIMER_PATTERNS):
        rep.add("fail", "trader-disclaimer", "trader-research 仓库缺少『不构成投资建议』免责声明")
    if not any(re.search(pat, corpus, re.IGNORECASE) for pat in AFFILIATION_PATTERNS):
        rep.add("fail", "trader-disclaimer", "trader-research 仓库缺少『非官方/不隶属』声明")


def check_python_syntax(repo: Path, rep: Report) -> None:
    for f in repo.rglob("*.py"):
        if ".git" in f.parts:
            continue
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            rep.add("fail", "python-syntax", f"{f.relative_to(repo)} 语法错误: {e.msg.splitlines()[0]}")


def check_requires(fm: dict, org_repos: set[str], rep: Report) -> None:
    if not org_repos:
        return
    for dep in ((fm or {}).get("quantSkills") or {}).get("requires") or []:
        if dep not in org_repos:
            rep.add("warn", "requires", f"requires 指向的仓库 '{dep}' 在组织中不存在")


def validate(repo: Path, org_repos: set[str]) -> Report:
    rep = Report()
    asset_type, declaration_file = declaration_info(repo)
    check_required_files(repo, declaration_file, rep)
    fm = check_frontmatter(repo, asset_type, declaration_file, rep)
    check_path_references(repo, rep)
    check_git_hygiene(repo, rep)
    check_secrets(repo, rep)
    check_trader_disclaimers(repo, fm, declaration_file, rep)
    check_python_syntax(repo, rep)
    check_requires(fm, org_repos, rep)
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--org-repos", default="", help="逗号分隔的组织仓库名清单,用于校验 requires")
    args = ap.parse_args()

    repo = Path(args.repo)
    if not repo.is_dir():
        sys.exit(f"目录不存在: {repo}")
    org_repos = {r.strip() for r in args.org_repos.split(",") if r.strip()}
    rep = validate(repo, org_repos)

    if args.json:
        print(json.dumps({"health": rep.health, "items": rep.items}, ensure_ascii=False, indent=2))
    else:
        print(f"health: {rep.health}")
        for item in rep.items:
            print(f"  [{item['level']:4}] {item['check']}: {item['detail']}")
    sys.exit({"healthy": 0, "warning": 1, "quarantined": 2}[rep.health])


if __name__ == "__main__":
    main()
