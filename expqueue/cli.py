"""CLI for agents to read/push/pop the experiment queue.

Usage:
  expqueue list [--status queued|in_progress|done|dropped] [--project NAME] [--json]
  expqueue push "<title>" [--notes "<notes>"] [--project NAME]
  expqueue pop [--json]
  expqueue done <id>
  expqueue drop <id>
  expqueue start <id>
  expqueue rm <id>
  expqueue edit <id> [--title "<title>"] [--notes "<notes>"] [--project NAME]
  expqueue project add <name> <directory> [--repo <owner/name>] [--create-repo]
  expqueue project list [--json]
"""

from __future__ import annotations

import argparse
import json
import sys

from expqueue.projects import ProjectStore, ensure_gh_repo
from expqueue.store import QueueStore, STATUSES, Task


def _print_task(t: Task) -> None:
    project = f" project={t.project}" if t.project else ""
    print(f"[{t.id}] ({t.status}){project} {t.title}")
    if t.notes:
        print(f"       {t.notes}")


def cmd_list(store: QueueStore, args: argparse.Namespace) -> None:
    tasks = store.list(status=args.status)
    if args.project:
        tasks = [t for t in tasks if t.project == args.project]
    if args.json:
        print(json.dumps([t.to_dict() for t in tasks], indent=2))
        return
    if not tasks:
        print("(empty)")
        return
    for t in tasks:
        _print_task(t)


def cmd_push(store: QueueStore, args: argparse.Namespace) -> None:
    task = store.push(args.title, notes=args.notes or "", project=args.project)
    _print_task(task)


def cmd_pop(store: QueueStore, args: argparse.Namespace) -> None:
    task = store.pop()
    if task is None:
        if args.json:
            print("null")
        else:
            print("(queue empty)")
        return
    if args.json:
        print(json.dumps(task.to_dict(), indent=2))
    else:
        _print_task(task)


def cmd_set_status(status: str):
    def _cmd(store: QueueStore, args: argparse.Namespace) -> None:
        task = store.update_status(args.id, status)
        if task is None:
            print(f"no task with id {args.id}", file=sys.stderr)
            sys.exit(1)
        _print_task(task)

    return _cmd


def cmd_rm(store: QueueStore, args: argparse.Namespace) -> None:
    if not store.remove(args.id):
        print(f"no task with id {args.id}", file=sys.stderr)
        sys.exit(1)
    print(f"removed {args.id}")


def cmd_edit(store: QueueStore, args: argparse.Namespace) -> None:
    task = store.edit(args.id, title=args.title, notes=args.notes, project=args.project)
    if task is None:
        print(f"no task with id {args.id}", file=sys.stderr)
        sys.exit(1)
    _print_task(task)


def cmd_project_add(args: argparse.Namespace) -> None:
    pstore = ProjectStore()
    if args.create_repo and args.repo:
        try:
            created = ensure_gh_repo(args.repo)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        if created:
            print(f"created gh repo {args.repo}")
    try:
        project = pstore.add(args.name, args.directory, repo=args.repo)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"[{project.name}] dir={project.directory} repo={project.repo or '-'}")


def cmd_project_list(args: argparse.Namespace) -> None:
    pstore = ProjectStore()
    projects = pstore.list()
    if args.json:
        print(json.dumps([p.to_dict() for p in projects], indent=2))
        return
    if not projects:
        print("(no projects)")
        return
    for p in projects:
        print(f"[{p.name}] dir={p.directory} repo={p.repo or '-'}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="expqueue")
    sub = p.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list tasks")
    p_list.add_argument("--status", choices=STATUSES, default=None)
    p_list.add_argument("--project", default=None)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_push = sub.add_parser("push", help="push a new task")
    p_push.add_argument("title")
    p_push.add_argument("--notes", default="")
    p_push.add_argument("--project", default=None)
    p_push.set_defaults(func=cmd_push)

    p_pop = sub.add_parser("pop", help="pop the oldest queued task (marks in_progress)")
    p_pop.add_argument("--json", action="store_true")
    p_pop.set_defaults(func=cmd_pop)

    p_start = sub.add_parser("start", help="mark a task in_progress")
    p_start.add_argument("id")
    p_start.set_defaults(func=cmd_set_status("in_progress"))

    p_done = sub.add_parser("done", help="mark a task done")
    p_done.add_argument("id")
    p_done.set_defaults(func=cmd_set_status("done"))

    p_drop = sub.add_parser("drop", help="mark a task dropped")
    p_drop.add_argument("id")
    p_drop.set_defaults(func=cmd_set_status("dropped"))

    p_rm = sub.add_parser("rm", help="delete a task entirely")
    p_rm.add_argument("id")
    p_rm.set_defaults(func=cmd_rm)

    p_edit = sub.add_parser("edit", help="edit a task's title/notes/project")
    p_edit.add_argument("id")
    p_edit.add_argument("--title", default=None)
    p_edit.add_argument("--notes", default=None)
    p_edit.add_argument("--project", default=None)
    p_edit.set_defaults(func=cmd_edit)

    p_project = sub.add_parser("project", help="manage the project registry")
    project_sub = p_project.add_subparsers(dest="project_command", required=True)

    p_project_add = project_sub.add_parser("add", help="register a project")
    p_project_add.add_argument("name")
    p_project_add.add_argument("directory")
    p_project_add.add_argument("--repo", default=None, help="GitHub repo, e.g. owner/name")
    p_project_add.add_argument(
        "--create-repo",
        action="store_true",
        help="create the GitHub repo via `gh` if it doesn't exist",
    )
    p_project_add.set_defaults(func=lambda store, args: cmd_project_add(args))

    p_project_list = project_sub.add_parser("list", help="list registered projects")
    p_project_list.add_argument("--json", action="store_true")
    p_project_list.set_defaults(func=lambda store, args: cmd_project_list(args))

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = QueueStore()
    args.func(store, args)


if __name__ == "__main__":
    main()
