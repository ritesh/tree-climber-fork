"""
Flows through assignments and string building, the first cases of the #44
prototype: a source straight into a sink, through a chain of names,
concatenation, f-strings, `%`, `str.format`, `join`, augmented assignment and
tuple unpacking; and the flows that are killed: a reassignment on every path,
and constants.
"""

import os
import subprocess


def direct():
    # ruleid: python-command-injection
    os.system(input())


def chain():
    a = input()
    b = a
    c = b
    # ruleid: python-command-injection
    os.system(c)


def string_building():
    name = input()
    # ruleid: python-command-injection
    os.system("ls " + name)
    # ruleid: python-command-injection
    os.system(f"ls {name}")
    # ruleid: python-command-injection
    os.system("ls %s" % name)
    # ruleid: python-command-injection
    os.system("ls {}".format(name))
    # ruleid: python-command-injection
    os.system(" ".join(["ls", name]))


def augmented():
    command = "ls "
    command += input()
    # ruleid: python-command-injection
    os.system(command)


def unpacking():
    host, port = input(), "22"
    # ruleid: python-command-injection
    subprocess.call("ssh " + host, shell=True)
    # todook: python-command-injection -- every name a statement defines takes its taint, unless a call is assigned to it alone
    os.system("echo " + port)


def reassigned():
    command = input()
    command = "ls"
    # ok: python-command-injection
    os.system(command)


def reassigned_on_one_path(flag):
    command = input()
    if flag:
        command = "ls"
    # ruleid: python-command-injection
    os.system(command)


def constant():
    # ok: python-command-injection
    os.system("ls -l")
