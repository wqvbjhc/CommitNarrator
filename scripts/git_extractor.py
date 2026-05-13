#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import argparse
import datetime
from datetime import timedelta
import calendar
import sys
import os
import re

MAX_OUTPUT_CHARS = 50000
COMMIT_DELIMITER = "---COMMIT_START---"

def get_default_author():
    try:
        email = subprocess.check_output(['git', 'config', 'user.email'], stderr=subprocess.DEVNULL).decode('utf-8', errors='replace').strip()
        if email: return email
        name = subprocess.check_output(['git', 'config', 'user.name'], stderr=subprocess.DEVNULL).decode('utf-8', errors='replace').strip()
        return name
    except Exception:
        return ""

def calculate_date_range(period):
    today = datetime.date.today()

    if period == "today":
        return today, today
    elif period == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    elif period == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    elif period == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6)
    elif period == "this_month":
        start = today.replace(day=1)
        _, last_day = calendar.monthrange(today.year, today.month)
        return start, today.replace(day=last_day)
    elif period == "last_month":
        first_of_this_month = today.replace(day=1)
        last_of_prev = first_of_this_month - timedelta(days=1)
        return last_of_prev.replace(day=1), last_of_prev
    elif period == "this_quarter":
        q_start_month = (today.month - 1) // 3 * 3 + 1
        return today.replace(month=q_start_month, day=1), today
    elif period == "last_quarter":
        q_start_month = (today.month - 1) // 3 * 3 + 1
        last_q_end = today.replace(month=q_start_month, day=1) - timedelta(days=1)
        last_q_start_month = (last_q_end.month - 1) // 3 * 3 + 1
        return last_q_end.replace(month=last_q_start_month, day=1), last_q_end
    elif period == "this_year":
        return today.replace(month=1, day=1), today
    else:
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)

def get_git_log(author, since, until):
    cmd = [
        "git", "log",
        f"--since={since} 00:00:00",
        f"--until={until} 23:59:59",
        "--stat",
        "--no-merges",
        "--date=short",
        "--pretty=format:---COMMIT_START---%nHash: %h%nAuthor: %an%nDate: %ad%nSubject: %s%n%(trailers:key=Body,valueonly)%b%n"
    ]

    if author and author.lower() not in ["all", "team", "everyone"]:
        cmd.insert(2, f"--author={author}")

    cmd.extend([
        "--", ".",
        ":(exclude)package-lock.json", ":(exclude)yarn.lock", ":(exclude)pnpm-lock.yaml",
        ":(exclude)*.lock", ":(exclude)dist", ":(exclude)build", ":(exclude)node_modules",
        ":(exclude)*.min.js", ":(exclude)*.map", ":(exclude)*.svg",
        ":(exclude)*.png", ":(exclude)*.jpg", ":(exclude)*.gif", ":(exclude)*.ico",
        ":(exclude)coverage", ":(exclude).next", ":(exclude).cache",
    ])

    try:
        log_output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode('utf-8', errors='replace')
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git command failed: {e.output.decode('utf-8', errors='replace')}")

    stat_cmd = [
        "git", "log",
        f"--since={since} 00:00:00",
        f"--until={until} 23:59:59",
        "--shortstat",
        "--no-merges"
    ]
    if author and author.lower() not in ["all", "team", "everyone"]:
        stat_cmd.insert(2, f"--author={author}")

    total_commits = 0
    total_insertions = 0
    total_deletions = 0

    try:
        stat_output = subprocess.check_output(stat_cmd, stderr=subprocess.DEVNULL).decode('utf-8', errors='replace')
        for line in stat_output.split('\n'):
            if 'changed' in line:
                total_commits += 1
                insert_match = re.search(r'(\d+) insertion', line)
                delete_match = re.search(r'(\d+) deletion', line)
                if insert_match: total_insertions += int(insert_match.group(1))
                if delete_match: total_deletions += int(delete_match.group(1))
    except Exception:
        pass

    return log_output, total_commits, total_insertions, total_deletions

def truncate_at_commit_boundary(log_data, max_chars):
    if len(log_data) <= max_chars:
        return log_data, False

    commits = log_data.split(COMMIT_DELIMITER)
    result = ""
    for i, chunk in enumerate(commits):
        candidate = COMMIT_DELIMITER.join(commits[:i+1]) if i > 0 else commits[0]
        if len(candidate) > max_chars and i > 0:
            result = COMMIT_DELIMITER.join(commits[:i])
            break
    else:
        result = log_data[:max_chars]

    return result, True

def main():
    parser = argparse.ArgumentParser(description="Extract Git logs for Agent Report.")
    parser.add_argument("--author", type=str, default="", help="Author name/email or 'all'")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--period", type=str,
        choices=["today", "yesterday", "this_week", "last_week",
                 "this_month", "last_month", "this_quarter", "last_quarter", "this_year"],
        help="Relative time period")
    parser.add_argument("--since", type=str, help="YYYY-MM-DD")
    parser.add_argument("--until", type=str, help="YYYY-MM-DD")

    args = parser.parse_args()

    if not os.path.isdir(".git"):
        print("Error: Current directory is not a Git repository.", file=sys.stderr)
        sys.exit(1)

    target_author = args.author if args.author else get_default_author()
    if not target_author: target_author = "all"

    if args.period:
        start_date, end_date = calculate_date_range(args.period)
    elif args.since and args.until:
        try:
            start_date = args.since
            end_date = args.until
            datetime.datetime.strptime(start_date, "%Y-%m-%d")
            datetime.datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            print("Error: Date format must be YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    else:
        start_date, end_date = calculate_date_range("this_week")

    try:
        log_data, commits, insertions, deletions = get_git_log(target_author, start_date, end_date)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if not log_data.strip():
        print(f"No commits found for {target_author} from {start_date} to {end_date}.")
        return

    log_data, is_truncated = truncate_at_commit_boundary(log_data, MAX_OUTPUT_CHARS)
    shown_commits = log_data.count(COMMIT_DELIMITER)

    stats_line = f"Stats: {commits} commits, +{insertions} lines, -{deletions} lines"
    if is_truncated:
        stats_line += f" (showing {shown_commits} of {commits} commits due to length limit)"

    output_header = (
        f"=== GIT REPORT SUMMARY ===\n"
        f"Target: {target_author}\n"
        f"Period: {start_date} ~ {end_date}\n"
        f"{stats_line}\n"
        f"==========================\n\n"
    )

    print(output_header + log_data)

    if is_truncated:
        print("\n\n[WARNING] Output truncated due to length limit.")

if __name__ == "__main__":
    main()
