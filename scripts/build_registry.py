#!/usr/bin/env python3
"""build_registry.py — 只读扫描组织 → 校验 → 生成注册表与人工复核报告。

产物(全部自动生成,人不手工编辑):
  registry.json                  机器可读公开资产注册表(展示层事实源)
  INDEX.md                       人类可读目录(按 project_type + category 分组)
  llms.txt                       agent 可读站点索引(部署到 quantskills.ai 根目录)
  .claude-plugin/marketplace.json  Claude Code 插件市场清单

可选本地审计产物(--audit-dir):
  scan-YYYYMMDD.json             完整扫描审计报告(含 health_items)
  human-review-YYYYMMDD.md       人类复核清单

增量策略: HEAD sha 与上次 registry 记录一致的仓库跳过(--full 强制全量)。
安全边界: 本脚本不修改任何 skill / agent 仓库,不开 PR,不改 topics,不写跨仓库 issue。

环境变量: GITHUB_TOKEN(contents:read), QS_ORG(默认 quantskills)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from validate_skill import declaration_info, parse_frontmatter, validate  # noqa: E402

ORG = os.environ.get("QS_ORG", "quantskills")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"} if TOKEN else {}
ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_REPOS = {"skill-template", "agent-template"}
CATEGORY_LABELS = {
    "analyst": "分析类 / Analyst",
    "data-api": "数据类 / Data API",
    "factor": "因子库 / Factor Library",
    "monitor": "监控类 / Monitor",
    "replication": "复现类 / Replication",
    "tooling": "工具流程类 / Tooling",
    "trader-research": "交易者研究类 / Trader Research",
    "research-agent": "研究 Agent / Research Agent",
    "workflow-agent": "工作流 Agent / Workflow Agent",
    "review-agent": "审核 Agent / Review Agent",
    "data-agent": "数据 Agent / Data Agent",
    "automation-agent": "自动化 Agent / Automation Agent",
    "uncategorized": "未分类 / Uncategorized",
}
CATEGORY_ORDER = {
    "analyst": 10,
    "data-api": 20,
    "factor": 30,
    "monitor": 40,
    "replication": 50,
    "tooling": 60,
    "trader-research": 70,
    "research-agent": 110,
    "workflow-agent": 120,
    "review-agent": 130,
    "data-agent": 140,
    "automation-agent": 150,
    "uncategorized": 999,
}
PROJECT_TYPE_LABELS = {
    "skill": "Skills",
    "agent": "Agents",
}
SNAPSHOT_START = "<!-- registry-snapshot:start -->"
SNAPSHOT_END = "<!-- registry-snapshot:end -->"
VALIDATION_LEVEL_ORDER = (
    ("verified", "L3"),
    ("runnable", "L2"),
    ("listed", "L1"),
)
PUBLIC_ENTRY_KEYS = (
    "name",
    "url",
    "description",
    "project_type",
    "declaration_file",
    "category",
    "tags",
    "platforms",
    "status",
    "requires",
    "summary_zh",
    "summary_en",
    "license",
    "validation_level",
    "maintainer_type",
    "last_validated",
)


def gh(method: str, url: str, **kw):
    r = requests.request(method, url, headers=HEADERS, timeout=30, **kw)
    r.raise_for_status()
    return r.json() if r.text else {}


def list_asset_repos() -> list[dict]:
    repos, page = [], 1
    while True:
        batch = gh("GET", f"{API}/orgs/{ORG}/repos", params={"per_page": 100, "page": page})
        if not batch:
            break
        repos += [
            r
            for r in batch
            if r["name"].startswith(("skill-", "agent-")) and r["name"] not in EXCLUDED_REPOS and not r["archived"]
            and not r.get("private")
        ]
        page += 1
    return repos


def head_sha(repo: dict) -> str:
    ref = gh("GET", f"{API}/repos/{ORG}/{repo['name']}/commits/{repo['default_branch']}")
    return ref["sha"]


def shallow_clone(name: str, dest: Path) -> None:
    url = f"https://github.com/{ORG}/{name}.git"
    last_error = None
    for attempt in range(1, 4):
        proc = subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, str(dest)], text=True, capture_output=True)
        if proc.returncode == 0:
            return
        last_error = (proc.stderr or proc.stdout or "unknown git clone failure").strip()
        if attempt < 3:
            time.sleep(2 * attempt)
    raise RuntimeError(f"failed to clone {ORG}/{name}: {last_error}")


def build_entry(name: str, repo_dir: Path, sha: str, report) -> dict:
    detected_type, declaration_file = declaration_info(repo_dir)
    declaration_path = repo_dir / declaration_file if declaration_file else None
    fm = parse_frontmatter(declaration_path) if declaration_path and declaration_path.is_file() else {}
    fm = fm or {}
    qs = fm.get("quantSkills") or {}
    project_type = qs.get("project_type") or detected_type or ("agent" if name.startswith("agent-") else "skill")
    return {
        "name": name,
        "url": f"https://github.com/{ORG}/{name}",
        "description": fm.get("description", ""),
        "project_type": project_type,
        "declaration_file": declaration_file or ("AGENT.md" if project_type == "agent" else "SKILL.md"),
        "category": qs.get("category", "uncategorized"),
        "tags": qs.get("tags", []),
        "platforms": qs.get("platforms", []),
        "status": qs.get("status", "draft"),
        "requires": qs.get("requires", []),
        "summary_zh": qs.get("summary_zh", ""),
        "summary_en": qs.get("summary_en", ""),
        "license": qs.get("license", "GPL-3.0"),
        "validation_level": qs.get("validation_level", "listed"),
        "maintainer_type": qs.get("maintainer_type", "community"),
        "health": report.health,
        "health_items": report.items,
        "commit_sha": sha,
        "last_validated": dt.date.today().isoformat(),
    }


def public_entry(entry: dict) -> dict:
    out = {key: entry.get(key) for key in PUBLIC_ENTRY_KEYS}
    if not out.get("summary_zh"):
        out["summary_zh"] = compact_summary(entry.get("description") or "", 160)
    if not out.get("summary_en"):
        out["summary_en"] = compact_summary(entry.get("description") or "", 220)
    return out


def compact_summary(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sentence_end = max(cut.rfind(mark) for mark in ("。", ".", "!", "?", "；", ";"))
    if sentence_end >= max(40, limit // 2):
        return cut[: sentence_end + 1]
    space = cut.rfind(" ")
    if space >= max(40, limit // 2):
        return cut[:space].rstrip() + "..."
    return cut.rstrip() + "..."


# ---------------- 产物生成 ----------------

def write_index(entries: list[dict]) -> None:
    by_type_cat: dict[tuple[str, str], list[dict]] = {}
    for e in entries:
        by_type_cat.setdefault((e.get("project_type", "skill"), e["category"]), []).append(e)
    lines = ["# quantskills 资产目录 / Asset Directory\n", "> 本文件由 build_registry.py 自动生成,请勿手工编辑。\n"]
    for project_type, cat in sorted(by_type_cat, key=lambda item: (item[0], CATEGORY_ORDER.get(item[1], 500), item[1])):
        category_label = CATEGORY_LABELS.get(cat, f"{cat} / {cat}")
        lines.append(f"\n## {PROJECT_TYPE_LABELS.get(project_type, project_type)} / {category_label}\n")
        lines.append("| Asset | 简介 | 验证级别 | 状态 | 标签 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for e in sorted(by_type_cat[(project_type, cat)], key=lambda x: x["name"]):
            tags = " ".join(f"`{t}`" for t in e["tags"][:5])
            lvl = {"listed": "L1 Listed", "runnable": "L2 Runnable", "verified": "L3 Verified"}.get(e.get("validation_level", "listed"))
            summary = e.get("summary_zh") or e.get("description", "")
            lines.append(f"| [{e['name']}]({e['url']}) | {summary} | {lvl} | {e['status']} | {tags} |")
    (ROOT / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_llms_txt(entries: list[dict]) -> None:
    lines = [
        "# quantskills",
        "> Open-source quant skills and agents for research, analytics, strategy workflows, validation, and tooling.",
        "",
        "## Skills",
    ]
    for e in sorted(entries, key=lambda x: (x.get("project_type", "skill"), x["category"], x["name"])):
        if e.get("project_type", "skill") != "skill":
            continue
        lines.append(f"- [{e['name']}]({e['url']}): {e['summary_en'] or e['summary_zh']}")
    lines += ["", "## Agents"]
    for e in sorted(entries, key=lambda x: (x.get("project_type", "skill"), x["category"], x["name"])):
        if e.get("project_type") != "agent":
            continue
        lines.append(f"- [{e['name']}]({e['url']}): {e['summary_en'] or e['summary_zh']}")
    lines += ["", "## Registry", f"- [registry.json](https://quantskills.ai/registry.json): machine-readable index of all assets"]
    (ROOT / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_marketplace(entries: list[dict]) -> None:
    plugins = [
        {
            "name": e["name"].removeprefix("skill-").removeprefix("agent-"),
            "source": {"source": "github", "repo": f"{ORG}/{e['name']}"},
            "description": e["summary_en"] or e["description"][:200],
            "type": e.get("project_type", "skill"),
            "category": e["category"],
        }
        for e in entries
    ]
    payload = {
        "name": "quantskills",
        "owner": {"name": "quantskills", "url": f"https://github.com/{ORG}"},
        "plugins": plugins,
    }
    out = ROOT / ".claude-plugin" / "marketplace.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def category_label(category: str, language: str) -> str:
    label = CATEGORY_LABELS.get(category, f"{category} / {category}")
    if " / " not in label:
        return label
    zh, en = label.split(" / ", 1)
    return zh if language == "zh" else en


def category_snapshot(entries: list[dict], language: str) -> str:
    counts: dict[str, int] = {}
    for entry in entries:
        category = entry.get("category", "uncategorized")
        counts[category] = counts.get(category, 0) + 1
    parts = []
    for category, count in sorted(counts.items(), key=lambda item: (-item[1], CATEGORY_ORDER.get(item[0], 500), item[0])):
        parts.append(f"`{category_label(category, language)} / {category}` {count}")
    return " · ".join(parts)


def validation_snapshot(entries: list[dict]) -> str:
    counts: dict[str, int] = {}
    for entry in entries:
        level = entry.get("validation_level", "listed")
        counts[level] = counts.get(level, 0) + 1
    parts = [f"{label} ×{counts.get(level, 0)}" for level, label in VALIDATION_LEVEL_ORDER]
    known_levels = {level for level, _ in VALIDATION_LEVEL_ORDER}
    for level in sorted(set(counts) - known_levels):
        parts.append(f"{level} ×{counts[level]}")
    return " · ".join(parts)


def snapshot_date(entries: list[dict]) -> str:
    dates = [entry.get("last_validated") for entry in entries if entry.get("last_validated")]
    return max(dates) if dates else dt.date.today().isoformat()


def replace_snapshot_block(path: Path, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    if SNAPSHOT_START not in text or SNAPSHOT_END not in text:
        raise RuntimeError(f"missing registry snapshot markers in {path}")
    before, rest = text.split(SNAPSHOT_START, 1)
    _, after = rest.split(SNAPSHOT_END, 1)
    path.write_text(f"{before}{SNAPSHOT_START}\n{body}\n{SNAPSHOT_END}{after}", encoding="utf-8")


def write_readme_snapshots(entries: list[dict]) -> None:
    type_counts: dict[str, int] = {}
    for entry in entries:
        project_type = entry.get("project_type", "skill")
        type_counts[project_type] = type_counts.get(project_type, 0) + 1

    date = snapshot_date(entries)
    skill_count = type_counts.get("skill", 0)
    agent_count = type_counts.get("agent", 0)
    validation = validation_snapshot(entries)

    replace_snapshot_block(
        ROOT / "README.md",
        (
            f"截至 {date}：**{skill_count} 个 skill / {agent_count} 个 agent**。"
            f"分类分布：{category_snapshot(entries, 'zh')}；验证级别 {validation}。"
        ),
    )
    replace_snapshot_block(
        ROOT / "README.en.md",
        (
            f"As of {date}: **{skill_count} skills / {agent_count} agents**. "
            f"Categories: {category_snapshot(entries, 'en')}; validation levels {validation}."
        ),
    )


def write_human_review(entries: list[dict], reports_dir: Path, stamp: str) -> None:
    unhealthy = [e for e in entries if e["health"] != "healthy"]
    counts = {health: sum(1 for e in entries if e["health"] == health) for health in ("healthy", "warning", "quarantined")}
    lines = [
        f"# quantskills 人工复核清单 {stamp}",
        "",
        "> 本文件由只读审计流水线生成。流水线不会修改 skill / agent 仓库,不会开 PR,不会改 topics,不会开/关 issue。",
        "",
        f"- 扫描仓库数: {len(entries)}",
        f"- skill: {sum(1 for e in entries if e.get('project_type', 'skill') == 'skill')}",
        f"- agent: {sum(1 for e in entries if e.get('project_type') == 'agent')}",
        f"- healthy: {counts['healthy']}",
        f"- warning: {counts['warning']}",
        f"- quarantined: {counts['quarantined']}",
        "",
    ]
    if not unhealthy:
        lines.append("所有仓库通过本轮确定性检查。")
    else:
        lines.append("## 待人工处理")
        lines.append("")
        for entry in unhealthy:
            lines += [
                f"### {entry['name']} - {entry['health']}",
                "",
                f"- URL: {entry['url']}",
                f"- Project type: `{entry.get('project_type', 'skill')}`",
                f"- Declaration: `{entry.get('declaration_file', 'SKILL.md')}`",
                f"- Commit: `{entry['commit_sha']}`",
                f"- Validation level: `{entry.get('validation_level', 'listed')}`",
                f"- Maintainer type: `{entry.get('maintainer_type', 'community')}`",
                "",
            ]
            for item in entry["health_items"]:
                lines.append(f"- [{item['level']}] `{item['check']}`: {item['detail']}")
            lines.append("")
    (reports_dir / f"human-review-{stamp}.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="忽略增量,全量重新校验")
    ap.add_argument("--audit-dir", default="", help="写入完整本地审计报告的目录;不传则不生成详细报告")
    ap.add_argument("--skip-public-artifacts", action="store_true", help="只生成 audit-dir 中的本地审计报告")
    args = ap.parse_args()

    registry_path = ROOT / "registry.json"
    previous = {e["name"]: e for e in json.loads(registry_path.read_text(encoding="utf-8"))} if registry_path.exists() else {}

    repos = list_asset_repos()
    org_repo_names = {r["name"] for r in repos}
    entries: list[dict] = []

    for repo in repos:
        name = repo["name"]
        sha = head_sha(repo)
        prev = previous.get(name)
        if prev and prev.get("commit_sha") == sha and not args.full:
            entries.append(prev)
            print(f"skip (unchanged): {name}")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / name
            shallow_clone(name, dest)
            report = validate(dest, org_repo_names)
            entry = build_entry(name, dest, sha, report)
        entries.append(entry)
        print(f"validated: {name} -> {entry['health']}")

    entries.sort(key=lambda e: e["name"])
    public_entries = [public_entry(e) for e in entries if e["health"] != "quarantined"]

    if not args.skip_public_artifacts:
        registry_path.write_text(json.dumps(public_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_index(public_entries)
        write_llms_txt(public_entries)
        write_marketplace(public_entries)
        write_readme_snapshots(public_entries)

    stamp = dt.date.today().strftime("%Y%m%d")
    if args.audit_dir:
        reports_dir = Path(args.audit_dir)
        if not reports_dir.is_absolute():
            reports_dir = ROOT / reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_rows = [
            {
                k: e[k]
                for k in (
                    "name",
                    "project_type",
                    "declaration_file",
                    "health",
                    "health_items",
                    "commit_sha",
                    "validation_level",
                    "maintainer_type",
                )
            }
            for e in entries
        ]
        (reports_dir / f"scan-{stamp}.json").write_text(
            json.dumps(report_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_human_review(entries, reports_dir, stamp)
    unhealthy = [e["name"] for e in entries if e["health"] != "healthy"]
    print(f"\ndone: {len(entries)} repos, unhealthy: {unhealthy or 'none'}")


if __name__ == "__main__":
    main()
