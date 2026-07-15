"""CLI for agents to read/push/pop the experiment queue.

Usage:
  expqueue list [--status queued|in_progress|done|dropped] [--json]
  expqueue push "<title>" [--notes "<notes>"]
  expqueue pop [--json]
  expqueue done <id>
  expqueue drop <id>
  expqueue start <id>
  expqueue rm <id>
"""

from __future__ import annotations

import argparse
import json
import sys

from expqueue.store import QueueStore, STATUSES, Task


def _print_task(t: Task) -> None:
    print(f"[{t.id}] ({t.status}) {t.title}")
    if t.notes:
        print(f"       {t.notes}")


def cmd_list(store: QueueStore, args: argparse.Namespace) -> None:
    tasks = store.list(status=args.status)
    if args.json:
        print(json.dumps([t.to_dict() for t in tasks], indent=2))
        return
    if not tasks:
        print("(empty)")
        return
    for t in tasks:
        _print_task(t)


def cmd_push(store: QueueStore, args: argparse.Namespace) -> None:
    task = store.push(args.title, notes=args.notes or "")
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="expqueue")
    sub = p.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list tasks")
    p_list.add_argument("--status", choices=STATUSES, default=None)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_push = sub.add_parser("push", help="push a new task")
    p_push.add_argument("title")
    p_push.add_argument("--notes", default="")
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

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = QueueStore()
    args.func(store, args)


if __name__ == "__main__":
    main()
