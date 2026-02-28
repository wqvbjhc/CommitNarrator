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

# 限制最大输出字符数，防止 Token 爆炸
MAX_OUTPUT_CHARS = 50000

def get_default_author():
    try:
        email = subprocess.check_output(['git', 'config', 'user.email'], stderr=subprocess.DEVNULL).decode('utf-8', errors='replace').strip()
        if email: return email
        name = subprocess.check_output(['git', 'config', 'user.name'], stderr=subprocess.DEVNULL).decode('utf-8', errors='replace').strip()
        return name
    except:
        return ""

def calculate_date_range(period):
    """
    依赖宿主机时间计算，解决 LLM 日期幻觉
    """
    today = datetime.date.today()
    
    if period == "today":
        return today, today
    elif period == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif period == "this_week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end
    elif period == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return start, end
    elif period == "this_month":
        start = today.replace(day=1)
        _, last_day = calendar.monthrange(today.year, today.month)
        end = today.replace(day=last_day)
        return start, end
    elif period == "this_year":
        start = today.replace(month=1, day=1)
        end = today.replace(month=12, day=31)
        return start, end
    else:
        # 默认 fallback 到本周
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end

def get_git_log(author, since, until):
    # 1. 获取详细日志 (Subject, Body, Stat)
    cmd = [
        "git", "log",
        f"--since={since} 00:00:00",
        f"--until={until} 23:59:59",
        "--stat",           # 显示文件变更统计
        "--no-merges",      # 排除合并提交
        "--date=short",     # 简化日期
        # 格式：哈希 | 作者 | 日期 | 标题 | 内容
        "--pretty=format:---COMMIT_START---%nHash: %h%nAuthor: %an%nDate: %ad%nSubject: %s%nBody: %b%n" 
    ]

    # 兼容 author="all" 模式
    if author and author.lower() not in ["all", "team", "everyone"]:
        cmd.insert(2, f"--author={author}")
    
    # 路径过滤：剔除干扰文件
    cmd.extend([
        "--", ".", 
        ":(exclude)package-lock.json", ":(exclude)yarn.lock", ":(exclude)pnpm-lock.yaml",
        ":(exclude)*.lock", ":(exclude)dist", ":(exclude)build", ":(exclude)node_modules",
        ":(exclude)*.min.js", ":(exclude)*.map", ":(exclude)*.svg", ":(exclude)assets/*"
    ])
    
    try:
        log_output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode('utf-8', errors='replace')
    except subprocess.CalledProcessError as e:
        return f"Error executing git command: {e.output.decode('utf-8', errors='replace')}", 0, 0, 0

    # 2. 计算总统计数据 (通过 git log --shortstat 快速获取汇总)
    # 这是一个独立的命令，用来给 Agent 提供宏观数据
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
        # 解析类似 "3 files changed, 10 insertions(+), 5 deletions(-)"
        for line in stat_output.split('\n'):
            if line.strip():
                total_commits += 1
                insert_match = re.search(r'(\d+) insertion', line)
                delete_match = re.search(r'(\d+) deletion', line)
                if insert_match: total_insertions += int(insert_match.group(1))
                if delete_match: total_deletions += int(delete_match.group(1))
    except:
        pass

    return log_output, total_commits, total_insertions, total_deletions

def main():
    parser = argparse.ArgumentParser(description="Extract Git logs for Agent Report.")
    parser.add_argument("--author", type=str, default="", help="Author name/email or 'all'")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--period", type=str, choices=["today", "yesterday", "this_week", "last_week", "this_month", "this_year"], help="Relative time period")
    parser.add_argument("--since", type=str, help="YYYY-MM-DD")
    parser.add_argument("--until", type=str, help="YYYY-MM-DD")
    
    args = parser.parse_args()

    if not os.path.isdir(".git"):
        print("Error: Current directory is not a Git repository.")
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
            print("Error: Date format must be YYYY-MM-DD")
            sys.exit(1)
    else:
        start_date, end_date = calculate_date_range("this_week")

    log_data, commits, insertions, deletions = get_git_log(target_author, start_date, end_date)
    
    if not log_data.strip():
        print(f"No commits found for {target_author} from {start_date} to {end_date}.")
        return

    # 安全截断
    is_truncated = False
    if len(log_data) > MAX_OUTPUT_CHARS:
        log_data = log_data[:MAX_OUTPUT_CHARS]
        is_truncated = True

    # 构建结构化输出给 LLM
    output_header = (
        f"=== GIT REPORT SUMMARY ===\n"
        f"Target: {target_author}\n"
        f"Period: {start_date} ~ {end_date}\n"
        f"Stats: {commits} commits, +{insertions} lines, -{deletions} lines\n"
        f"Truncated: {'YES' if is_truncated else 'NO'}\n"
        f"==========================\n\n"
    )

    print(output_header + log_data)

    if is_truncated:
        print("\n\n[WARNING] Output truncated due to length limit.")

if __name__ == "__main__":
    main()