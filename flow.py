import sys
from os import path
from typing import *
import re
import time
import os
import subprocess
import sqlite3
import datetime

#
#
# Shared code:
#
#

db_path = path.join(path.dirname(sys.argv[0]), "_db/flow.db")
dt_fmt_str_readable = "YYYY/MM/DD HH:MM:SS"
dt_fmt_str_readable_eg = "1999/02/04 00:15:00"
dt_fmt_str = "%Y-%m-%d %H:%M:%S"
dt_fmt_str_re = r"(\d\d\d\d)-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)"
task_name_re_readable = "{chunk ::= [a-zA-Z_\\-0-9]+; task_name ::= chunk | task_name '.' chunk;}"
task_name_re_readable_eg = "ucla.f19.cs35l.task-1"
task_name_validator_re = r"[a-zA-Z_\-0-9]+(\.([a-zA-Z_\-0-9]+))+"


#
# Results
#

class Result(object):
    def __init__(self, ok):
        super().__init__()
        self.ok = ok

    def __bool__(self):
        return self.ok


class ResultOk(Result):
    def __init__(self, data=None):
        super().__init__(ok=True)
        if data:
            self.data = data


class ResultFail(Result):
    def __init__(self, msg):
        super().__init__(ok=False)
        self.msg = msg


def round_sec_to_int(sec):
    return int(round(sec, 0))


def sec_to_hms(sec):
    sec_int = round_sec_to_int(sec)
    min_int = sec_int // 60
    hr_int = min_int // 60
    print_sec = sec_int % 60
    print_min = min_int % 60
    print_hr = hr_int % 60
    return print_hr, print_min, print_sec


def hms_to_str(h, m, s):
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"


def sec_to_hms_str(sec):
    h, m, s = sec_to_hms(sec)
    return hms_to_str(h, m, s)


def sql_sanitize_str_content(s):
    return "".join(map(lambda ch: ch if ch != "'" else "''", s))


def dt_to_str(dt):
    return dt.strftime(dt_fmt_str)


def str_to_dt(s):
    return datetime.datetime.strptime(s, dt_fmt_str)


#
# Validators:
#

def default_validator(s):
    return ResultOk()


def non_empty_validator(s):
    if s:
        return ResultOk()
    else:
        return ResultFail("The string cannot be empty.")


def date_time_validator(s):
    if re.match(dt_fmt_str_re, s):
        return ResultOk()
    else:
        return ResultFail(
            "The date-string entered is of an incorrect format.\n"
            f"The expected format is: {dt_fmt_str_readable}\n"
            f"Here's an example:      {dt_fmt_str_readable_eg}\n"
        )


def int_validator(s):
    if re.match(r"([0-9_]+)", s):
        return ResultOk()
    else:
        return ResultFail("The string entered is not a valid integer.")


def task_name_validator(task_name):
    if re.match(task_name_validator_re, task_name):
        return ResultOk()
    else:
        return ResultFail("The string entered is not a correctly formatted task name.\n"
                          f"The expected format is: {task_name_re_readable}\n"
                          f"Here's an example:      {task_name_re_readable_eg}")


def new_task_name_validator(new_task_name, cursor):
    res = task_name_validator(new_task_name)
    if not res:
        return res

    cursor.execute("SELECT COUNT(*) FROM task WHERE name=?", (new_task_name,))
    if cursor.fetchone()[0] == 0:
        return ResultOk()
    else:
        return ResultFail(f"A task named {repr(new_task_name)} already exists!")


def file_path_validator(file_path):
    file_path = file_path.strip()
    if not file_path:
        return ResultFail("The provided file-path cannot be empty.")

    dir_path, file_name = path.split(file_path)
    if not path.exists(dir_path):
        return ResultFail(f"The directory '{dir_path}' does not exist.\n"
                          f"Absolute path: '{path.abspath(dir_path)}'")
    if path.exists(file_path):
        abs_file_path = path.abspath(file_path)
        if confirm(f"Are you sure you want to overwrite the existing file {file_name}?\n"
                   f"Absolute path: '{abs_file_path}'"):
            return ResultOk()
        else:
            return ResultFail(f"You chose not to overwrite the existing file at '{abs_file_path}'.")
    return ResultOk()


#
# We use a custom 'record' writing model. It's quite simple.
#

def new_record_append_str(date_time, record_name, message):
    return f"\n[{dt_to_str(date_time)} {record_name}] {repr(message)}"


#
#
# Model code:
#
#

# NOTE: Volatile, standard in the DB. Do not change.
IN_PROGRESS_TASK_STATUS = 0
COMPLETE_TASK_STATUS = 1
ABANDONED_TASK_STATUS = 2


def connect():
    return sqlite3.connect(db_path)


class Note(object):
    def __init__(self, id_, create_dt, task_id, opt_work_id, user_text, flow_text):
        super().__init__()
        self.id = id_
        self.create_dt = create_dt
        self.task_id = task_id
        self.opt_work_id = opt_work_id
        self.user_text = user_text
        self.flow_text = flow_text

    @staticmethod
    def new(task_id, opt_work_id, opt_dt, user_text, flow_text, cursor):
        if opt_dt:
            create_dt = opt_dt
        else:
            create_dt = datetime.datetime.now()

        assert isinstance(task_id, (type(None), int))
        assert isinstance(user_text, str)
        assert isinstance(flow_text, str)
        cursor.execute("INSERT INTO note (timestamp, task_id, opt_work_id, user_text, flow_text) VALUES (?,?,?,?,?)",
                       (dt_to_str(create_dt), task_id, opt_work_id, user_text, flow_text))
        note_id = cursor.lastrowid

        return Note(note_id, create_dt, task_id, opt_work_id, user_text, flow_text)


class Task(object):
    html_beg = """
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <title>Project Report</title>

            <style>
                sys {
                    font-family: "Lucida Console", Monaco, monospace;
                    font-size: 0.8em;
                }
            </style>
        </head>
        <body>
    """

    html_end = "</body></html>"

    def __init__(self, id_, name, beg_dt, status):
        super().__init__()
        self.id = id_
        self.name = name
        self.beg_dt = beg_dt
        self.status = status

    @staticmethod
    def new(name, first_msg, cursor):
        assert isinstance(name, str)
        assert isinstance(first_msg, str)

        beg_dt = datetime.datetime.now()
        status = IN_PROGRESS_TASK_STATUS

        # Inserting the new task:
        beg_dt_str = dt_to_str(beg_dt)
        cursor.execute("INSERT INTO task (name, cache_beg_dt, cache_status_code) VALUES (?,?,?)",
                       (name, beg_dt_str, status))
        task_id = cursor.lastrowid
        assert task_id is not None

        # Adding a note to indicate task creation:
        Note.new(task_id, None, beg_dt, first_msg, "new-task,open-task", cursor)

        return Task(task_id, name, beg_dt, status)

    @staticmethod
    def name_search(search_str, only_open, cursor):
        san_str_content = sql_sanitize_str_content(search_str)
        sql = f"SELECT id, name, cache_beg_dt, cache_status_code FROM task WHERE (name LIKE '%{san_str_content}%')"

        if only_open:
            sql += f" AND (cache_status_code = {IN_PROGRESS_TASK_STATUS})"

        cursor.execute(sql)

        for sql_tuple in cursor.fetchall():
            id_, name, beg_dt_str, status = sql_tuple
            beg_dt = str_to_dt(beg_dt_str)
            yield Task(id_, name, beg_dt, status)

    def set_status(self, new_status, completion_msg, cursor):
        # Adding a completion note:
        now = datetime.datetime.now()
        if new_status == COMPLETE_TASK_STATUS:
            flow_text = "complete-task,close-task"
        elif new_status == ABANDONED_TASK_STATUS:
            flow_text = "abandon-task,close-task"
        elif new_status == IN_PROGRESS_TASK_STATUS:
            flow_text = "open-task"
        else:
            raise NotImplementedError

        # Adding a note:
        note = Note.new(self.id, None, now, completion_msg, flow_text, cursor)
        assert note.id

        # Changing the task's completion status:
        cursor.execute("UPDATE task SET cache_status_code=? WHERE id=?", (new_status, self.id))

    def print_to_html(self, file_path, cursor):
        with open(file_path, "w") as f:
            def f_print(*args, **kwargs):
                assert "file" not in kwargs
                return print(*args, **kwargs, file=f)

            f_print(Task.html_beg)
            f_print(f"<h1>{self.name}</h1>")

            if self.status == IN_PROGRESS_TASK_STATUS:
                status_str = f"IN_PROGRESS ({self.status})"
            elif self.status == COMPLETE_TASK_STATUS:
                status_str = f"COMPLETE ({self.status})"
            elif self.status == ABANDONED_TASK_STATUS:
                status_str = f"ABANDONED ({self.status})"
            else:
                status_str = f"UNKNOWN ({self.status})"
            f_print(f"<p><sys>Status: {status_str}</sys></p>")

            row = cursor.execute("SELECT SUM(cache_duration_sec) FROM work WHERE task_id=?", (self.id,))
            net_duration_sec = row.fetchone()[0]
            row = cursor.execute("SELECT COUNT(*), sum(duration_sec) FROM break WHERE task_id=?", (self.id,))
            num_breaks, raw_break_duration_sec = row.fetchone()
            if raw_break_duration_sec is None:
                break_duration_sec = 0
            else:
                break_duration_sec = round_sec_to_int(raw_break_duration_sec)

            work_duration_sec = net_duration_sec - break_duration_sec
            f_print(f"<p>You have spent {sec_to_hms_str(work_duration_sec)} working on this task so far. "
                    f"That's a total of "
                    f"{sec_to_hms_str(net_duration_sec)} with "
                    f"{sec_to_hms_str(break_duration_sec)} spent on {num_breaks} breaks.")

            f_print("<hr/>")

            rows = cursor.execute("SELECT id, timestamp, opt_work_id, user_text, flow_text FROM note "
                                  "WHERE task_id=? "
                                  "ORDER BY timestamp",
                                  (self.id,)).fetchall()
            f_print("<h2><sys>Notes:<sys></h2>")
            f_print("<ul>")
            for note_id, timestamp, opt_work_id, user_text, flow_text in rows:
                user_text = user_text
                flow_text = flow_text
                f_print("<li>")
                f_print(f"<sys>[{timestamp}]</sys><br/>")
                f_print(f"{user_text}<br/>")
                f_print(f"<sys>{flow_text}</sys><br/>")
                f_print(f"<sys>Note ID: {note_id}</sys><br/>")
                f_print(f"<sys>Work ID: {opt_work_id}</p>")
                f_print("</li>")
            f_print("</ul>")

            f_print("<hr/>")

            f_print("<h2><sys>Work and Breaks:</sys></h2>")
            f_print("<ul>")
            res = cursor.execute("SELECT id, cache_beg_dt, cache_duration_sec FROM work WHERE task_id=?", (self.id,))
            for work_id, beg_dt, duration_sec in res:
                f_print("<li>")

                f_print(f"<sys>[{beg_dt}]</sys><br/>")
                f_print(f"<sys>Net duration: {sec_to_hms_str(duration_sec)}</sys><br/>")

                agg_res = cursor.execute("SELECT COUNT(*), SUM(duration_sec) FROM break WHERE work_id=?", (work_id,))
                num_breaks, total_break_duration = agg_res.fetchone()
                f_print(f"<sys>Breaks: {num_breaks} for {total_break_duration}</sys><br/>")

                f_print("<ol>")
                break_res = cursor.execute("SELECT id, beg_dt, duration_sec FROM break WHERE work_id=?", (work_id,))
                for break_id, break_beg_dt, break_duration_sec in break_res:
                    f_print("<li><sys>")
                    f_print(f"Break ({break_id}) at [{break_beg_dt}] for {sec_to_hms_str(break_duration_sec)}")
                    f_print("</sys></li>")
                f_print("</ol>")

            f_print(Task.html_end)

    def __str__(self):
        id_str = str(self.id) if self.id else "<husk>"
        return f"Task(id={id_str},name={repr(self.name)},create_dt={repr(dt_to_str(self.create_dt))})"


class Work(object):
    def __init__(self, id_, task_id, beg_py_dt, end_py_dt, duration_sec):
        super().__init__()
        self.id = id_
        self.task_id = task_id
        self.beg_dt = beg_py_dt
        self.end_dt = end_py_dt
        self.duration_sec = duration_sec

    @staticmethod
    def new(task_id, start_dt, cursor):
        end_dt = start_dt
        start_dt_text = dt_to_str(start_dt)
        cursor.execute(
            "INSERT INTO work (task_id, cache_beg_dt, cache_end_dt, cache_duration_sec) VALUES (?,?,?,?)",
            (task_id, start_dt_text, start_dt_text, 0)
        )
        id_ = cursor.lastrowid
        return Work(id_, task_id, start_dt, end_dt, 0)

    @staticmethod
    def get(id_, cursor):
        row = cursor.execute("SELECT id, task_id, cache_beg_dt, cache_end_dt, cache_duration_sec FROM work "
                             "WHERE id=? "
                             "ORDER BY cache_beg_dt", (id_,)).fetchone()
        if row:
            id_, task_id, beg_dt_text, end_dt_text, duration_sec = row
            beg_dt = str_to_dt(beg_dt_text)
            end_dt = str_to_dt(end_dt_text)
            return Work(id_, task_id, beg_dt, end_dt, duration_sec)
        else:
            return None

    def save(self, save_dt, cursor):
        self.end_dt = save_dt
        self.duration_sec = round_sec_to_int((save_dt - self.beg_dt).total_seconds())
        cursor.execute("UPDATE work SET cache_end_dt=?, cache_duration_sec=? WHERE id=?",
                       (dt_to_str(self.end_dt), self.duration_sec, self.id))

    @staticmethod
    def add_break(task_id, work_id, break_start_time, break_end_time, break_duration_sec, cursor):
        assert task_id
        assert work_id
        cursor.execute(
            "INSERT INTO break (task_id, work_id, beg_dt, end_dt, duration_sec) VALUES (?,?,?,?,?)",
            (task_id, work_id, dt_to_str(break_start_time), dt_to_str(break_end_time), break_duration_sec)
        )


#
# UI - Shared
#


# TODO: Write curses functions to support wipe, print, richer input, [and async stuff if possible!]


def wipe():
    # FIXME: Hacky
    subprocess.run("clear")


def wipe_print(*args, **kwargs):
    wipe()
    print(*args, **kwargs)


def line_input_text(prompt, validator=default_validator):
    if validator is None:
        def validator(x): return True

    text = input(prompt).strip()
    validation = validator(text)
    assert isinstance(validation, Result)
    if validation.ok:
        return text
    else:
        assert isinstance(validation, ResultFail)
        print(validation.msg)
        return line_input_text(prompt, validator=validator)


def combo_input(title, option_tuples, default_key=None):
    assert option_tuples

    invalid_selection_msg = "Invalid selection. Please try again."

    num_options = len(option_tuples)
    prompt_list, key_list = zip(*option_tuples)

    # Breaking the option list into pages:
    choice_chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    page_length = len(choice_chars)
    num_pages = (num_options // page_length) + bool(num_options % page_length)

    # Single page-output:
    if num_pages == 1:
        choice_chars = choice_chars[:len(key_list)]

        # Pre-computing the input text from the default provided:
        if default_key is not None:
            default_index = key_list.index(default_key)
            input_text = f"Your choice (default: {choice_chars[default_index]}): "
        else:
            assert default_key is None
            input_text = f"Your choice: "

        while True:
            print(title)
            for choice_char, page in zip(choice_chars, prompt_list):
                print(f"Enter [{choice_char}] to {page}")
            print(f"Enter [~] to Repaint.")

            choice_str = input(input_text).strip()
            if not choice_str:
                # Returning the 'default key' specified and printed, which, by default, is None (indicating 'no choice')
                return default_key
            else:
                choice_char = choice_str[0]
                if choice_char == '~':
                    wipe()
                else:
                    try:
                        choice_int = choice_chars.index(choice_char)
                    except ValueError:
                        print(invalid_selection_msg)
                        continue

                    # Looking up the chosen key:
                    if choice_int >= 0:
                        return key_list[choice_int]
                    else:
                        print(invalid_selection_msg)
                        continue

    # Multi-page output:
    else:
        # TODO: paginated output; switching to curses.
        assert num_pages > 1
        pages = []
        for i_page in range(num_pages):
            page_beg_index = i_page * page_length
            page_end_index = (i_page * page_length) + page_length
            pages.append(prompt_list[page_beg_index:page_end_index])

        raise NotImplementedError


def date_time_input(title):
    full_title = f"{title}\n(NOTE: Please enter your text in the format {dt_fmt_str}, or {dt_fmt_str_re})"
    text = line_input_text(full_title, validator=date_time_validator)
    return str_to_dt(text)


def int_input(title):
    int_text = line_input_text(title, validator=int_validator)
    return int(int_text)


def notify(message=None):
    if message:
        print(message)
    input("Hit [Return] to continue...")


def confirm(message, default: "Union[str, bool]" = True):
    default_char = 'Y' if default else 'N'
    other_char = 'n' if default else 'y'
    input_text = input(f"{message} [{default_char}/{other_char}]: ").strip()
    if input_text:
        return input_text[0] in ('y', 'Y')
    else:
        return default


def task_select(desc, only_open=False):
    with connect() as connection:
        cursor = connection.cursor()
        while True:
            wipe_print(desc)
            search_str = line_input_text("= TASK SEARCH =\nEnter a task-name search string fragment: ")
            result_task_list = list(Task.name_search(search_str, only_open, cursor))
            if not result_task_list:
                cb = confirm("No results found! Continue searching? ", default=True)
                if not cb:
                    # In these cases, we want to pop to the previous menu.
                    return None
            else:
                result_tuples_iter = map(lambda p: (p.name, p), result_task_list)
                result_tuples = list((*result_tuples_iter, ("return to the previous menu.", "return")))
                task_input = combo_input("= SEARCH RESULTS =\nSelect a task to work on [default = continue searching]:",
                                         result_tuples)
                if task_input is None:
                    return None
                elif task_input == "return":
                    return "return"
                else:
                    assert isinstance(task_input, Task)
                    return task_input


#
# UI - Work
#

def work_main():
    while True:
        wipe_print("Work")
        selected_task = task_select("Select an *OPEN* task to start working on:", only_open=True)
        if selected_task is None:
            continue
        elif selected_task == "return":
            break
        elif selected_task:
            assert isinstance(selected_task, Task)
            if confirm(f"Selected task: '{selected_task.name}'\nStart working?"):
                work_screen(selected_task)
                break


def work_screen(task):
    auto_save_msg = ""

    cum_break_sec = 0
    auto_save_interval_sec = 30
    net_elapsed_sec_when_next_auto_save = auto_save_interval_sec
    work_start_time = datetime.datetime.now()

    with connect() as connection:
        cursor = connection.cursor()
        new_work = Work.new(task.id, work_start_time, cursor)

    while True:
        try:
            # Auto-saving:
            raw_net_elapsed_sec = (datetime.datetime.now() - work_start_time).total_seconds()
            net_elapsed_sec = round_sec_to_int(raw_net_elapsed_sec) - cum_break_sec
            if net_elapsed_sec > net_elapsed_sec_when_next_auto_save:
                net_elapsed_sec_when_next_auto_save = net_elapsed_sec + auto_save_interval_sec
                with connect() as connection:
                    cursor = connection.cursor()
                    now_dt = datetime.datetime.now()
                    new_work.save(now_dt, cursor)

                    auto_save_dt_text = new_work.end_dt.strftime(dt_fmt_str)
                    auto_save_msg = f"[Last auto-saved at {auto_save_dt_text}]"

            time_str = sec_to_hms_str(net_elapsed_sec)
            print(
                f"\rWorking on {repr(task.name)} for... {time_str} [Ctrl+C to pause] "
                f"{auto_save_msg}", end=" ")
            time.sleep(1)

        except KeyboardInterrupt:
            work_end_time = datetime.datetime.now()
            break_start_time = work_end_time

            options = [
                ("Add Note", "an"),
                ("Continue Work.", "c"),
                ("Stop Work.", "s")
            ]
            choice = combo_input(f"Working on {repr(task.name)}: PAUSED", options, default_key='c')
            with connect() as connection:
                cursor = connection.cursor()
                if choice == "an":
                    note_text = line_input_text("Enter a note to add: ", non_empty_validator)
                    dt = datetime.datetime.now()
                    new_note = Note.new(task.id, new_work.id, dt, note_text, "work-note", cursor)
                    assert new_note.id
                    notify("Note added successfully!")
                if choice == 'c':
                    break_end_time = datetime.datetime.now()
                    raw_break_duration_sec = (break_end_time - break_start_time).total_seconds()
                    break_duration_sec = round_sec_to_int(raw_break_duration_sec)
                    cum_break_sec += break_duration_sec
                    Work.add_break(task.id, new_work.id, break_start_time, break_end_time, break_duration_sec, cursor)
                    continue
                elif choice == 's':
                    if confirm("Are you sure you want to end this session?"):
                        break

    user_note = line_input_text("Enter a short note to commemorate this work session: ")

    with connect() as connection:
        cursor = connection.cursor()
        Note.new(task.id, new_work.id, work_end_time, user_note, "end-work", cursor)
        new_work.save(work_end_time, cursor)

    time_str = sec_to_hms_str(new_work.duration_sec)
    notify(message=f"{time_str} of work has been saved under the task {repr(task.name)}")


#
# UI - Tasks
#

def search_task_main():
    while True:
        selected_task = task_select("Search for a task to edit:")
        if selected_task is None:
            continue
        elif selected_task == "return":
            break
        else:
            assert isinstance(selected_task, Task)
            # TODO: Add a 'modify deadline' option if the task's deadline is mutable.
            view_task_main(selected_task)


def view_task_main(selected_task):
    while True:
        option_tuple = [
            ("Print Record [HTML]", "pf")
        ]
        info = None
        if selected_task.status == IN_PROGRESS_TASK_STATUS:
            info = "This task is in progress. You may complete or abandon it."
            option_tuple.append(("Complete Task", "tc"))
            option_tuple.append(("Add Note", "an"))
        elif selected_task.status == COMPLETE_TASK_STATUS:
            info = "This task is already complete. You may re-open it to add notes and further information."
            option_tuple.append(("Re-open Task", "tro"))
        elif selected_task.status == ABANDONED_TASK_STATUS:
            info = "This task was abandoned. You may re-open it to add notes and further information."
            option_tuple.append(("Re-open Task", "tro"))

        option_tuple.append(("Return...", "return"))

        if info:
            info_str = f"{info}\n"
        else:
            info_str = ""

        choice = combo_input(f"{info_str}Choose an action to apply to this task:", option_tuple, default_key="return")
        if choice == "return":
            return

        with connect() as connection:
            cursor = connection.cursor()
            if choice == "pf":
                file_path = line_input_text("Enter a file-path for the generated HTML info file: ",
                                            validator=file_path_validator)
                selected_task.print_to_html(file_path, cursor)
            elif choice == "tc":
                if confirm(f"Are you sure you want to mark '{selected_task.name}' as complete?"):
                    complete_msg = line_input_text("Enter a completion note (why? how? when? future?): ",
                                                   non_empty_validator)
                    selected_task.set_status(COMPLETE_TASK_STATUS, complete_msg, cursor)
                    notify(message=f"Marked task '{selected_task.name}' as complete.")
            elif choice == "tro":
                if confirm(f"Are you sure you want to re-open '{selected_task.name}'?"):
                    reopen_msg = line_input_text("Enter a reopening note (why? how? when? future?): ",
                                                 non_empty_validator)
                    selected_task.set_status(IN_PROGRESS_TASK_STATUS, reopen_msg, cursor)
                    notify(message=f"Marked task '{selected_task.name}' as in-progress again.")
            elif choice == "an":
                wipe_print("Add Note")
                print("Enter [Ctrl+C] any time to exit:")
                while True:
                    try:
                        note = line_input_text("Enter your time-stamped note:\n", default_validator)
                        time_stamp = datetime.datetime.now()
                    except KeyboardInterrupt:
                        break

                    print(f"Note: {repr(note)}")
                    print(f"Time: {dt_to_str(time_stamp)}")
                    if confirm("Add note?"):
                        selected_task.add_note()
                        break


def create_task_main():
    with connect() as connection:
        cursor = connection.cursor()
        print("Enter [Ctrl + C] at any time to cancel this form.")
        try:
            create_dt = datetime.datetime.now()
            new_task_name = line_input_text("Enter the new task's name: ",
                                            validator=lambda s: new_task_name_validator(s, cursor))
            first_msg = line_input_text("Enter the first note you would like to add to this project: ",
                                        validator=non_empty_validator)

            # TODO: Implement deadlines and work budgets.
            # if confirm("Does this task have a deadline?", default=False):
            #     p.info["deadline"] = date_time_input("Enter the new task's deadline").strftime(dt_fmt_str)
            #     p.info["deadline_mut"] = confirm("Allow me to change this deadline in the future?")

            # budget_hours = int_input("How many hours of work do you think this task will take to complete? ")
            if confirm("Are you sure you want to add the above task?"):
                task = Task.new(new_task_name, first_msg, cursor)
                notify(f"Task '{new_task_name}' successfully added with ID {task.id}.")

        except KeyboardInterrupt:
            return


def data_main():
    wipe_print("Data main")
    print("Bye bye!")


#
# UI - Main
#

def main():
    try:
        while True:
            wipe_print("Welcome to Flow!")
            choice_tuple = (
                ("Work", 'w'),
                ("View Tasks", 'vt'),
                ("Create a Task", "tc"),
                ("Quit", 'q')
            )
            choice_id = combo_input("Select a context to navigate to:", choice_tuple, default_key='w')
            if choice_id == 'w':
                work_main()
            elif choice_id == 'vt':
                search_task_main()
            elif choice_id == 'tc':
                create_task_main()
            else:
                assert choice_id == 'q'
                print("Bye-bye!")
                return

    except KeyboardInterrupt:
        print("\nBye-bye~")
        return


if __name__ == "__main__":
    main()

# Commands:
# flow
# flow -h
# flow p[roject] ["task-id-prefix"]
# flow w[ork] "task-id-prefix"
# flow w h[elp]

# Next:
# View comments.
# Write notes that link back into the DB.
