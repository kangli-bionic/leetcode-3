#!/usr/bin/env python3

import functools
import os
import re
import requests
import collections
import datetime
import urllib
import sys
import json

README_FILENAME = "README.md"
ONLINE_MAP = {}
LOCAL_MAP = collections.defaultdict(list)
NOT_BACKFILLED = set()
ATTEMPTED = {354, 564, 741, 805, 878, 891, 931, 964,
             974, 1000, 1004, 1199, 1234, 1397, 1655}
STARRED = {321, 913}

NOT_BACKFILLED = {str(item) for item in NOT_BACKFILLED}
ATTEMPTED = {str(item) for item in ATTEMPTED}
STARRED = set(map(str, STARRED))


def get_root_path():
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# ======== Modeling ========


class Question:

    """
    A class modeling online questions fetched from API
    """

    US_QUESTION_URL_PATTERN = "https://leetcode.com/problems/%s"
    CN_QUESTION_URL_PATTERN = "https://leetcode-cn.com/problems/%s"
    DIFFICULTIES = ["Easy", "Medium", "Hard"]

    def __init__(self, dic):
        self._id = str(dic["stat"]["frontend_question_id"])
        self._title = dic["stat"]["question__title"]
        if self._id in ["1560", "1092"]:  # malformatted title from api
            self._title = " ".join(self._title.split())

        self._lock = dic["paid_only"]
        self._difficulty = dic["difficulty"]["level"]
        self._slug = dic["stat"]["question__title_slug"]

    def difficulty(self):
        return Question.DIFFICULTIES[self._difficulty - 1]

    def is_us(self):
        return self._id.isdigit()

    def cn_url(self):
        return Question.CN_QUESTION_URL_PATTERN % self._slug

    def us_url(self):
        return Question.US_QUESTION_URL_PATTERN % self._slug

    def id(self):
        return self._id

    def title(self):
        return self._title

    def lock(self):
        return self._lock

    def order(self):
        if self.is_us():
            return (-int(self.id()),)
        else:
            return (float("inf"), self.id())

    def __str__(self):
        return "%s, %s, %s" % (self.id(), self.title(), self.us_url())


class Solution:

    """
    A class modeling loca solution files"
    """

    FOLDER_SIZE = 500
    KNOWN_TYPES = {"c", "cpp", "java", "py",
                   "rb", "sh", "js", "sql", "php", "txt"}
    KNOWN_CN_GROUPS = [
        re.compile("^LCP \d{2}$"),
        re.compile("^剑指 Offer \d{2}(- I{1,3})?$"),
        re.compile("^面试题 \d{2}\.\d{2}$")
    ]
    ROOT_PATH = None
    moved_cnt = 0

    def __init__(self, abs_path):
        if not Solution.ROOT_PATH:
            Solution.ROOT_PATH = get_root_path()
        self._abs_path = abs_path
        self._abs_folder, self._basename = os.path.split(abs_path)
        self._parse_basename()

    def is_in_root(self):
        return self._abs_folder == Solution.ROOT_PATH

    def type(self):
        return self._basename.split(".")[-1]

    def id(self):
        if self.is_us():
            return str(int(self._id))
        else:
            return self._id

    def _parse_basename(self):
        # id.title[.version][.hint].typ
        splited = self._basename.split(".")
        if len(splited) > 2 and re.match("^面试题 \d{2}$", splited[0]) and re.match("^\d{2}$", splited[1]):
            splited[0] += "." + splited[1]
            splited.pop(1)
        if len(splited) > 5:
            raise ValueError("Unable to parse basename %s" % self._basename)
        for i in range(len(splited)):
            splited[i] = splited[i].strip()
            if not splited[i]:
                raise ValueError("Empty piece in file %s" % self._basename)
        self._typ = splited[-1]
        if self._typ not in Solution.KNOWN_TYPES:
            raise ValueError("Unknown file type for %s" % self._basename)
        self._id = splited[0]
        self._desired_folder = self._calc_desired_folder()
        self._title = self._version = self._hint = None
        for piece in splited[1:-1]:
            if piece.isdigit():
                if self._version is not None:
                    raise ValueError(
                        "Found multiple versions from basename %s" % self._basename)
                self._version = piece
            elif piece[0] == "(" and piece[-1] == ")":
                if self._hint is not None:
                    raise ValueError(
                        "Found multiple hints from basename %s" % self._basename)
                self._hint = piece[1:-1]
                if not self._hint:
                    raise ValueError(
                        "The hint in basename cannot be empty for %s" % self._basename)
            else:
                if self._title is not None:
                    raise ValueError(
                        "Found multiple titles from basename %s" % self._basename)
                self._title = piece.strip()
        question = ONLINE_MAP.get(self.id())
        if question is None:
            raise ValueError(
                "Unable to auto-detect title from online source, for the basename %s", self._basename)
        if self._title is None:
            # tring to fill the title from online source
            print("[WARN] Solution %s name defaults to %s" %
                  (self.id(), question.title()))
            self._title = question.title()
        else:
            if self._title != question.title():
                raise ValueError("file name doesn't match online question title: (online: %s, local: %s, basename: %s)" % (
                    question.title(), self._title, self._basename))

    def is_us(self):
        return self._id.isdigit()

    def desired_folder(self):
        return self._desired_folder

    def _calc_desired_folder(self):
        if self.is_us():
            num = int(self._id)
            start = (num - 1) // Solution.FOLDER_SIZE * \
                Solution.FOLDER_SIZE + 1
            end = start + Solution.FOLDER_SIZE - 1
            return "{:04d}-{:04d}".format(start, end)
        elif any(matcher.match(self._id) for matcher in Solution.KNOWN_CN_GROUPS):
            folders = ["LCP", "剑指 Offer", "面试题"]
            for folder in folders:
                if self._id.startswith(folder):
                    return folder
            else:
                raise Error("fail to assign a folder")
        else:
            raise ValueError("Unknown question id %s" % self._id)

    def desired_abs_path(self):
        return os.path.join(Solution.ROOT_PATH, self.desired_folder(), self.desired_basename())

    def is_misplaced(self):
        return self._abs_path != self.desired_abs_path()

    def correct_location(self):
        if os.path.exists(self.desired_abs_path()):
            raise Exception("Destination already exists: %s -> %s" %
                            (self._abs_path, self.desired_abs_path()))
        print("Moving %s -> %s" % (self._abs_path, self.desired_abs_path()))
        os.rename(self._abs_path, self.desired_abs_path())
        Solution.moved_cnt += 1

    def desired_basename(self):
        res = ["{:04d}".format(int(self._id)) if self.is_us() else self._id,
               self._title]
        if self._version is not None:
            res.append(self._version)
        if self._hint is not None:
            res.append("(" + self._hint + ")")
        res.append(self._typ)
        return ".".join(res)

    def __str__(self):
        return repr(self)

    def __repr__(self):
        return str({
            "id": self._id,
            "type": self._typ,
            "title": self._title,
            "version": self._version,
            "hint": self._hint,
            "abs_path": self._abs_path,
            "abs_folder": self._abs_folder,
            "desired_folder": self._desired_folder,
            "basename": self._basename,
            "is_in_root": self.is_in_root()
        })

# ======== readme ========


def update_file(relative_path, content):
    root_path = get_root_path()
    abs_path = os.path.join(root_path, relative_path)
    if not os.path.isfile(abs_path):
        raise Exception("Cannot find file: %s" % abs_path)
    with open(abs_path, "w") as out:
        out.write(content)

# ======== markdowne ========


def gen_markdown(questions, solutions, title):

    def gen_markdown_questions(questions):
        header = """
|Status|#|Question|My Solutions|Difficulty ([CN](https://leetcode-cn.com/problemset/all))|
|:---|:---|:---|:---|:---|
"""
        body = "\n".join(gen_markdown_question_row(question)
                         for question in questions)
        return header + body

    def gen_markdown_question_row(question):

        def get_status(question):
            qid = question.id()
            status = ""
            if LOCAL_MAP[qid] or qid in NOT_BACKFILLED:
                if qid in ATTEMPTED:
                    print(
                        "[WARN] question %s is in ATTEMPTED but it is believed to be solved" % qid)
                if LOCAL_MAP[qid] and qid in NOT_BACKFILLED:
                    print(
                        "[WARN] question %s is in NOT_BACKFILLED but a solution is found" % qid)
                status += "&check;"
            if qid in ATTEMPTED:
                status += "?"
            if question.lock():
                status += "&#x1f512;"
            if qid in STARRED:
                status += "&star;"
            return status

        def get_solution_links(question):
            res = []
            for sol in sorted(LOCAL_MAP[question.id()], key=lambda sol: sol.type()):
                relative_link = "/".join([urllib.parse.quote(sol.desired_folder()),
                                          urllib.parse.quote(sol.desired_basename())])
                res.append("[%s](%s)" % (sol.type(), relative_link))
            if not res and question.id() in NOT_BACKFILLED:
                return "(not uploaded yet)"
            return ", ".join(res)

        def get_question_link(question):
            if question.is_us():
                return "[%s](%s) ([CN](%s))" % (question.title(), question.us_url(), question.cn_url())
            else:
                return "[%s](%s)" % (question.title(), question.cn_url())

        row = [
            "",
            get_status(question),
            question.id(),
            get_question_link(question),
            get_solution_links(question),
            question.difficulty(),
            ""
        ]
        return "|".join(row)

    def gen_markdown_stats(questions, solutions):
        total = len(questions)
        solved = len({sol.id() for sol in solutions} | NOT_BACKFILLED)
        attempted = len(ATTEMPTED)
        unsolved_without_lock = len([q for q in questions if (
            not q.lock() and q.id() not in NOT_BACKFILLED and not LOCAL_MAP[q.id()])])
        unsynced = len(NOT_BACKFILLED)
        starred = len(STARRED)
        line1 = "|Total|Solved|Attempted|Unsolved without lock|"
        line2 = "|:---:|:---:|:---:|:---:|"
        line3 = "|%s|%s|%s|%s|"
        args = [total, solved, attempted, unsolved_without_lock]

        if unsynced:
            line1 += "Not synced to GitHub"
            line2 += ":---:|"
            line3 += "%s|"
            args.append(unsolved_without_lock)
        if starred:
            line1 += "Starred"
            line2 += ":---:|"
            line3 += "%s|"
            args.append(starred)
        return "\n".join(["", line1, line2, line3, ""]) % tuple(args)

    def gen_markdown_intro():

        def gen_markdown_site_links():
            return """
* LeetCode websites
  * [leetcode.com](https://leetcode.com/)
  * [leetcode-cn.com](https://leetcode-cn.com/)
"""

        def gen_markdown_self_link():
            rel_path = os.path.relpath(__file__, get_root_path())
            return "* This report is generated by [%s](%s)." % (os.path.basename(__file__), rel_path)

        def gen_markdown_today():
            return "* Last updat: " + datetime.date.today().strftime("%A, %B %d, %Y").replace(" 0", " ")

        res = ["# " + title,
               gen_markdown_site_links(),
               gen_markdown_self_link(),
               gen_markdown_today()]
        return "\n".join(res)

    def gen_markdown_language_stats(solutions):
        DO_NOT_STATS = {"txt", "sql", "sh"}
        cnt = collections.Counter(
            sol.type() for sol in solutions if sol.type() not in DO_NOT_STATS)
        sm = sum(cnt.values())
        if sm == 0:
            return ""
        line1 = line2 = line3 = "|"
        for lang, lan_cnt in cnt.most_common():
            line1 += lang + "|"
            line2 += ":---:|"
            line3 += "%.1f%%|" % (lan_cnt * 100 / float(sm))
        return "\n".join(["", line1, line2, line3, ""])

    res = [
        gen_markdown_intro(),
        gen_markdown_stats(questions, solutions),
        gen_markdown_language_stats(solutions),
        gen_markdown_questions(questions)
    ]
    return "\n".join(res)


# ======== load resources ========

def load_resources():

    def save_online_resource(json_dict, abs_path):
        with open(abs_path, "w") as out:
            json.dump(json_dict, out, indent=2)

    def get_online_problems():
        obj = requests.get("https://leetcode-cn.com/api/problems/all/").json()
        root_path = get_root_path()
        abs_file_path = os.path.join(root_path, "others", "api-cn.backup.json")
        save_online_resource(obj, abs_file_path)
        return obj

    def list_code_folders():
        folder_patterns = ["\d{4}-\d{4}", "LCP", "剑指 Offer", "面试题"]
        folder_pattern = "^((" + ")|(".join(folder_patterns) + "))$"
        folder_matcher = re.compile(folder_pattern)
        root_path = get_root_path()
        return [os.path.join(root_path, folder) for folder in os.listdir(root_path) if folder_matcher.match(folder)]

    def list_local_solutions():
        folders = list_code_folders()
        solutions = []
        for folder in folders:
            for file_name in os.listdir(folder):
                solutions.append(Solution(os.path.join(folder, file_name)))
        root_path = get_root_path()
        known_children_patterns = [
            "\d{4}-\d{4}", "LCP", "剑指 Offer", "面试题", ".git", ".gitignore", "others", README_FILENAME]
        known_children_pattern = "^((" + \
            ")|(".join(known_children_patterns) + "))$"
        known_children_matcher = re.compile(known_children_pattern)
        for file_name in os.listdir(root_path):
            if not known_children_matcher.match(file_name):
                solutions.append(Solution(os.path.join(root_path, file_name)))
        return solutions

    questions = list(sorted([Question(prob) for prob in get_online_problems()[
                     "stat_status_pairs"]], key=lambda q: q.order()))
    ONLINE_MAP.update({q.id(): q for q in questions})
    solutions = list_local_solutions()
    for sol in solutions:
        LOCAL_MAP[sol.id()].append(sol)
    return questions, solutions

# ======== correct local files ========


def correct_local_files(questions, solutions):
    try:
        for sol in solutions:
            if sol.is_misplaced():
                sol.correct_location()
    finally:
        print()
        print("%d file(s) moved." % Solution.moved_cnt)


# ======== search solutions ========
def search_local_solutions(qid):
    if qid.isdigit():
        qid = str(int(qid))
    if qid in ATTEMPTED:
        print(qid + " was attempted.")
    elif qid in NOT_BACKFILLED:
        print(qid + " was completed, but not submitted to GitHub.")
    elif LOCAL_MAP[qid]:
        for sol in LOCAL_MAP[qid]:
            print(sol.desired_abs_path())
    else:
        print("Not found")

# ======== generate subtables ========

def select_todo_without_lock(qid):
    if qid in NOT_BACKFILLED:
        return False
    if len(LOCAL_MAP[qid]):
        return False
    if ONLINE_MAP[qid].lock():
        return False
    return True

def filter_questions_and_solutions(questions, solutions, selector):
    rtn_questions = [question for question in questions if selector(question.id())]
    rtn_solutions = [solution for solution in solutions if selector(solution.id())]
    return rtn_questions, rtn_solutions


# ======== main ========

def main():
    questions, solutions = load_resources()
    if len(sys.argv) == 1:
        correct_local_files(questions, solutions)
        markdown = gen_markdown(questions, solutions, "My LeetCode solutions")
        update_file(README_FILENAME, markdown)
        
        todo_que, todo_sol = filter_questions_and_solutions(questions, solutions, select_todo_without_lock)
        markdown = gen_markdown(todo_que, todo_sol, "To do questions")
        update_file(os.path.join("others", "todo questions.md"), markdown)
    elif len(sys.argv) == 2:
        search_local_solutions(sys.argv[1])
    else:
        raise Exception("Too many arguments.")


if __name__ == "__main__":
    main()
