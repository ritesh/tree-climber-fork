"""
Flows through control flow, from the #44 prototype: `for` and `while` loops
(including a value carried around the loop), both and one branch of an `if`,
`try`/`except`/`else`/`finally` (an exception before a definition means it did
not happen), `with`, `match`, comprehensions and lambdas.
Branching on a tainted value is in implicit_flows.py and limitations.py.
"""

import os


def loop_over_input():
    for word in input().split():
        # ruleid: python-command-injection
        os.system(word)


def carried_around_a_loop(count):
    command = "ls"
    previous = ""
    for _ in range(count):
        command = previous
        previous = input()
    # ruleid: python-command-injection
    os.system(command)


def while_loop():
    line = input()
    while line:
        # ruleid: python-command-injection
        os.system(line)
        line = input()


def one_branch(flag):
    command = "ls"
    if flag:
        command = input()
    # ruleid: python-command-injection
    os.system(command)


def both_branches_clean(flag):
    command = input()
    if flag:
        command = "ls"
    else:
        command = "pwd"
    # ok: python-command-injection
    os.system(command)


def try_except():
    try:
        command = input()
    except EOFError:
        command = "true"
    else:
        # ruleid: python-command-injection
        os.system(command)
    finally:
        pass
    # ruleid: python-command-injection
    os.system(command)


def raised_before_the_definition():
    command = "true"
    try:
        check()
        command = input()
    except ValueError:
        # ok: python-command-injection
        os.system(command)


def with_block():
    with open("commands.txt") as handle:
        command = input()
    # ruleid: python-command-injection
    os.system(command)


def with_target():
    with lock(input()) as command:
        # ruleid: python-command-injection
        os.system(command)


def match_case():
    match input().split():
        case [verb, target]:
            # todoruleid: python-command-injection -- the names a case pattern binds are defined by a node that reads nothing, so they do not take the subject's taint (#76)
            os.system(verb + " " + target)
        case _:
            # ok: python-command-injection
            os.system("true")


def comprehension():
    words = [w.strip() for w in input().split(",")]
    # ruleid: python-command-injection
    os.system(" ".join(words))


def lambda_result():
    shout = lambda text: text.upper()
    # ruleid: python-command-injection
    os.system(shout(input()))
