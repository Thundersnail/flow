import re
import time
import os
import subprocess
import json
import sqlite3
import datetime
import argparse
from collections import OrderedDict

#
# Model code:
#

dt_fmt_str = "%Y-%m-%d %H:%M:%S"
dt_fmt_str_re = r"(\d\d\d\d)-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)"
project_name_validator_re = r"[a-zA-Z_\-0-9]+(\.([a-zA-Z_\-0-9]+))+"


def sec_to_hms(sec):
    sec_int = int(round(sec, 0))
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


def connect():
    return sqlite3.connect("./flow.db")


def project_name_validator(project_name):
    return bool(re.match(project_name_validator_re, project_name))


def new_project_name_validator(new_project_name, cursor):
    if not project_name_validator(new_project_name):
        return False
    cursor.execute("SELECT count(*) FROM project WHERE name=?",
                   (new_project_name,))
    return not cursor.fetchone()[0]


def date_time_validator(s):
    return bool(re.match(dt_fmt_str_re, s))


def int_validator(s):
    return bool(re.match(r"([0-9_]+)", s))


class Project(object):
    def __init__(self, id_, name, create_dt_text, info_json_text):
        super().__init__()
        
        if create_dt_text:
            create_py_dt = datetime.datetime.strptime(create_dt_text, dt_fmt_str)
        else:
            create_py_dt = None
        
        if info_json_text:
            info_json_map = json.loads(info_json_text)
        else:
            info_json_map = None

        self.id = id_
        self.name = name
        self.create_dt = create_py_dt
        self.info = info_json_map

    @staticmethod
    def search(search_str, cursor):
        san_str_content = sql_sanitize_str_content(search_str)
        cursor.execute(
            "SELECT id, name, create_dt, info_json FROM project "
            f"WHERE name LIKE '%{san_str_content}%'"
        )
        for sql_tuple in cursor.fetchall():
            id_, name, create_dt_text, info_json_raw = sql_tuple
            yield Project(id_, name, create_dt_text, info_json_raw)

    @staticmethod
    def create_husk_to_insert(name, create_dt):
        project = Project(None, name, None, None)
        project.info = {"complete": False}
        project.create_dt = create_dt
        return project

    def insert(self, cursor):    
        assert new_project_name_validator(self.name, cursor)
        create_dt_text = self.create_dt.strftime(dt_fmt_str)
        json_text = json.dumps(self.info)
        cursor.execute(
            "INSERT INTO project (name, create_dt, info_json) VALUES (?,?,?)",
            (self.name, create_dt_text, json_text)
        )

    def __str__(self):
        return f"Project(id={self.id},name={repr(self.name)},desc={repr(self.desc)}," + \
               f"create_dt={repr(self.create_dt.strftime(dt_fmt_str))})"


class Work(object):
    def __init__(self, id_, project_id, beg_py_dt, end_py_dt, duration_sec, note, info_json):
        super().__init__()
        self.id = id_
        self.project_id = project_id
        self.beg_dt = beg_py_dt
        self.end_dt = end_py_dt
        self.duration_sec = duration_sec
        self.note = note
        self.info_json_raw = info_json
        info = json.loads(self.info_json_raw)
        self.dirty = info["dirty"]

    @staticmethod
    def new(project_id, start_dt, cursor):
        start_dt_text = start_dt.strftime(dt_fmt_str)
        end_dt = start_dt
        end_dt_text = start_dt_text
        duration_sec = 0
        note = None
        info_json = json.dumps({"dirty": True})
        cursor.execute(
            "INSERT INTO work (project_id, beg_dt, end_dt, duration_sec, note, info_json) VALUES (?,?,?,?,?,?)",
            (project_id, start_dt_text, end_dt_text, duration_sec, note, info_json))
        id_ = cursor.lastrowid
        return Work(id_, project_id, start_dt, end_dt, duration_sec, note, info_json)

    def save(self, new_end_dt, cursor):
        self.end_dt = new_end_dt
        self.duration_sec = round(
            (self.end_dt - self.beg_dt).total_seconds(), 0)

        end_dt_str = self.end_dt
        if not self.dirty:
            cursor.execute("SELECT info_json FROM work WHERE id=?", (self.id,))
            row = cursor.fetchone()
            assert row
            info = json.loads(row[0])

            info["dirty"] = False
            self.info_json = json.dumps(info)

            cursor.execute(
                "UPDATE work SET note=?,info_json=?,end_dt=?,duration_sec=? WHERE id=?",
                (self.note,
                 self.info_json,
                 end_dt_str,
                 self.duration_sec,
                 self.id))
        else:
            cursor.execute(
                "UPDATE work SET end_dt=?,duration_sec=? WHERE id=?",
                (end_dt_str, self.duration_sec, self.id)
            )


#
# UI - Shared
#

def wipe():
    subprocess.run("clear")


def wipe_print(*args, **kwargs):
    # FIXME: Hacky
    wipe()
    print(*args, **kwargs)


def str_non_empty_validator(s):
    return bool(s)


def line_input_text(prompt, validator=str_non_empty_validator, 
                    validation_msg="The input you provided was empty. Try again."):
    if validator is None:
        def validator(x): return True

    text = input(prompt).strip()
    if validator(text):
        return text
    else:
        print(validation_msg)
        return line_input_text(
            prompt,
            validator=validator,
            validation_msg=validation_msg)


def combo_input(title, option_tuples, default=None):
    assert option_tuples

    option_map = OrderedDict(option_tuples)
    key_list = list(option_map.keys())

    # Breaking the option list into pages:
    choice_chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    page_length = len(choice_chars)
    num_pages = (len(option_map) // page_length) + \
        (1 if len(key_list) % page_length else 0)
    if num_pages == 1:
        choice_chars = choice_chars[:len(key_list)]
        valid = False
        while not valid:
            print(title)
            for choice_char, page in zip(choice_chars, key_list):
                print(f"Enter [{choice_char}] to {page}")

            if default is not None:
                default_index = list(option_map.values()).index(default)
                choice_str = input(
                    f"Your choice (default: {choice_chars[default_index]}): ").strip()
            else:
                assert default is None
                print(f"Enter [Return] to cancel.")
                choice_str = input(f"Your choice: ").strip()

            if not choice_str:
                return default

            try:
                choice_int = - \
                    1 if not choice_str else choice_chars.index(choice_str[0])
                valid = choice_int >= 0
            except ValueError:
                valid = False

            if valid:
                option_key = key_list[choice_int]
                return option_map[option_key]
            else:
                print("Invalid selection. Please try again.")
    else:
        assert num_pages > 1
        pages = []
        for i_page in range(num_pages):
            page_beg_index = i_page * page_length
            page_end_index = (i_page * page_length) + page_length
            pages.append(key_list[page_beg_index:page_end_index])

        raise NotImplementedError


def date_time_input(title):
    full_title = f"{title}\n(NOTE: Please enter your text in the format {dt_fmt_str}, or {dt_fmt_str_re})"
    text = line_input_text(
        full_title, 
        validator=date_time_validator, 
        validation_msg="The date-time you selected was invalid. Try again."
    )
    return datetime.strptime(text, dt_fmt_str)


def int_input(title):
    int_text = line_input_text(
        title, 
        validator=int_validator, 
        validation_msg="The input you provided was not a valid integer. Try again."
    )
    return int(int_text)


def notify(message):
    input(f"{message}\nHit [Return] to continue...")


def confirm(message, default=True):
    default_char = 'Y' if default else 'N'
    other_char = 'n' if default else 'y'
    input_text = input(f"{message} [{default_char}/{other_char}]: ").strip()
    if input_text:
        return input_text[0] in ('y', 'Y')
    else:
        return bool(default)


def project_print(project):
    print("Creating the following project:")
    print(f"- Name: {repr(project.name)}")
    print(f"- Creation timestamp: {project.create_dt.strftime(dt_fmt_str)}")
    if "desc" in project.info:
        print(f"- Notes:")
        for time_stamp, text in project.info["desc"]:
            print(f"  - {time_stamp}\n    {text}")
    if "deadline" in project.info:
        print(f"- Deadline: True")
        print(f"- Deadline date-time: {project.info['deadline'].strftime(dt_fmt_str)}")
        print(f"- Allow me to change my deadline later: {project.info['deadline_mut']}")
    else:
        print(f"- Deadline: False")
    print(f"- Complete: {project.info['complete']}")
    print(f"- Budgeted work hours: {project.info['budget']}")
    
    print(f"Project name: {repr(project.name)}")
    print(f"Creation timestamp: {project.create_dt.strftime(dt_fmt_str)}")
    for k, v in project.info.items():
        if k == "deadline":
            print(f"Deadline: {v.strftime(dt_fmt_str)}")
    
    if project.id:
        print(f"Project ID: {project.id}")


def project_select(title):
    with connect() as connection:
        cursor = connection.cursor()
        while True:
            wipe()
            search_str = line_input_text(
                "= SEARCH BAR =\nEnter a project-name search string fragment: ",
                validator=None)
            result_project_list = list(Project.search(search_str, cursor))
            if not result_project_list:
                if confirm("No results found! Return to the previous menu?"):
                    break
            result_tuples_iter = map(lambda p: (p.name, p), result_project_list)
            result_tuples = list((*result_tuples_iter, ("return to the previous menu.", "return")))
            project_input = combo_input("= SEARCH RESULTS =\nSelect a project to work on:", result_tuples)
            if project_input == "return":
                return "return"
            elif project_input:
                return project_input
            else:
                    return None


#
# UI - Work
#

def create_work_main():
    while True:
        wipe_print("Work")
        selected_project = project_select(
            "Select a project to start working on:")
        if selected_project == "return":
            return
        elif selected_project:
            print("Selected project:")
            project_print(selected_project)
            if confirm(f"Start working?"):
                work_value = work_screen(selected_project)


def work_screen(project):
    auto_save_msg = ""

    update_sec_interval = 30
    next_update_sec = update_sec_interval
    work_start_time = datetime.datetime.now()

    with connect() as connection:
        cursor = connection.cursor()
        new_work = Work.new(project.id, work_start_time, cursor)

    while True:
        try:
            net_elapsed_sec = (
                datetime.datetime.now() -
                work_start_time).total_seconds()
            if net_elapsed_sec > next_update_sec:
                next_update_sec += update_sec_interval
                with connect() as connection:
                    cursor = connection.cursor()
                    new_work.save(datetime.datetime.now(), cursor)
                    auto_save_dt_text = new_work.end_dt.strftime(dt_fmt_str)
                    auto_save_msg = f"[Last auto-saved at {auto_save_dt_text}]"

            time_str = sec_to_hms_str(net_elapsed_sec)
            print(
                f"\rWorking on {repr(project.name)} for... {time_str} [Ctrl+C to pause] "
                f"{auto_save_msg}", end=" ")
            time.sleep(1)

        except KeyboardInterrupt:
            work_end_time = datetime.datetime.now()
            options = [
                ("continue.", "c"),
                ("stop.", "s")
            ]
            choice = combo_input(
                f"Working on {repr(project.name)}: PAUSED",
                options,
                default='c')
            if choice == 'c':
                continue
            elif choice == 's':
                if confirm("Are you sure you want to end this session?"):
                    break

    new_work.note = line_input_text(
        "Enter a short note to commemorate this work session: ")
    new_work.dirty = False
    with connect() as connection:
        cursor = connection.cursor()
        new_work.save(work_end_time, cursor)

    time_str = sec_to_hms_str(new_work.duration_sec)
    notify(f"{time_str} of work has been saved under the project {repr(project.name)}")


def manage_work_main():
    pass


#
# UI - Projects
#

def manage_project_main():
    selected_project = project_select("Search for a project to edit:")
    if selected_project == "return":
        return

    if selected_project:
        project_print(selected_project)
        option_tuple = [
            ("Mark as complete", "c"),
            ("Amend description", "m")
        ]
        # TODO: Add a 'modify deadline' option if the project's deadline is mutable.


def create_project_main():
    with connect() as connection:
        cursor = connection.cursor()
        print("Hit Ctrl+C at any time to cancel this form.")
        try:
            create_dt = datetime.datetime.now()
            info = {}

            new_project_name = line_input_text(
                "Enter the new project's name: ", 
                validator=lambda s: new_project_name_validator(s, cursor),
                validation_msg=(
                    f"Invalid project name!\n"
                    "Must:\n"
                    f"- Satisfy the regular expression {repr(project_name_validator_re)}\n"
                    "  Eg: flow_extra.examples.eg-1\n"
                    "- Not already exist"
                )
            )
            
            p = Project.create_husk_to_insert(new_project_name, create_dt)

            new_project_desc = line_input_text(
                "Enter the new project's description: ", 
                validator=None
            )
            if new_project_desc:
                p.info["desc"] = [(create_dt.strftime(dt_fmt_str), new_project_desc)]
            else:
                print("Empty description ignored.")

            if confirm("Does this project have a deadline?", default=False):
                p.info["deadline"] = date_time_input("Enter the new project's deadline").strftime(dt_fmt_str)
                p.info["deadline_mut"] = confirm("Allow me to change this deadline in the future?")
            
            p.info["budget"] = int_input("How many hours of work do you think this project will take to complete? ")

            project_print(p)
            if confirm("Is this okay?"):
                p.insert(cursor)

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
                ("clock work hours in.", 'wn'),
                ("search for a project to edit.", 'ps'),
                ("create a new project.", "pn"),
                ("manage past work.", 'wm'),
                ("quit", 'q')
            )
            choice_id = combo_input(
                "Select a context to navigate to:",
                choice_tuple,
                default='wn')
            if choice_id is None:
                print("Bye-bye!")
            elif choice_id == 'wn':
                create_work_main()
            elif choice_id == 'ps':
                manage_project_main()
            elif choice_id == 'pn':
                create_project_main()
            elif choice_id == 'wm':
                manage_work_main()
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
# flow p[roject] ["project-id-prefix"]
# flow w[ork] "project-id-prefix"
# flow w h[elp]
