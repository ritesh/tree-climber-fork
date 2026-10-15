"""
Flows through calls, which the #44 prototype missed: arguments into
parameters (positional, keyword, defaults, `*args`), return values back to
the caller, methods and `self`, nested helpers, closures, `global`, and
calls the analysis does not know, which pass their arguments' taint on.
"""

import os
import shlex


def run(command):
    # ruleid: python-command-injection
    os.system(command)


def caller():
    run(input())


def run_keyword(prefix, command="true"):
    # ruleid: python-command-injection
    os.system(prefix + command)


def keyword_caller():
    run_keyword("nice ", command=input())


def run_all(*commands):
    for command in commands:
        # ruleid: python-command-injection
        os.system(command)


def star_caller():
    run_all("true", input())


def read_name():
    return input().strip()


def returned():
    name = read_name()
    # ruleid: python-command-injection
    os.system("id " + name)


def make_command(name):
    return "id " + name


def through_a_helper():
    # ruleid: python-command-injection
    os.system(make_command(input()))


class Runner:
    def __init__(self, command):
        self.command = command

    def start(self):
        # ruleid: python-command-injection
        os.system(self.command)


def method_caller():
    Runner(input()).start()


def closure():
    command = input()

    def inner():
        # ruleid: python-command-injection
        os.system(command)

    inner()


current = "true"


def set_current():
    global current
    current = input()


def use_current():
    # ruleid: python-command-injection
    os.system(current)


def unknown_calls():
    name = input()
    # ruleid: python-command-injection
    os.system(name.strip().lower())
    # ruleid: python-command-injection
    os.system(str(name))


def sanitized_at_the_call():
    name = input()
    # ok: python-command-injection
    os.system(shlex.quote(name))
    # ok: python-command-injection
    os.system("ls " + shlex.quote(name))


def escape(value):
    return value.replace(";", "")


def code_eval():
    expression = input()
    # ruleid: python-code-injection
    eval(escape(expression))
    # ok: python-code-injection
    eval("1 + 1")
