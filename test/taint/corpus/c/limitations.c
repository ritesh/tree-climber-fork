/*
 * Documented C approximations, as known false negatives (todoruleid) and
 * false positives (todook): output parameters (`snprintf`, `strcpy` into a
 * buffer), pointer aliasing, calls through function pointers, and an array
 * that is one value.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char *argv[]) {
    char command[256];
    snprintf(command, sizeof command, "ls %s", argv[1]);
    // todoruleid: c-command-injection -- snprintf writes command through a pointer, and output parameters are not followed
    system(command);

    char copy[256];
    strcpy(copy, argv[2]);
    // todoruleid: c-command-injection -- strcpy writes copy through a pointer, and output parameters are not followed
    system(copy);

    char buffer[256];
    char *alias = buffer;
    buffer[0] = argv[3][0];
    // todoruleid: c-command-injection -- alias and buffer name the same memory, and aliasing is not tracked
    system(alias);

    int (*runner)(const char *) = system;
    // todoruleid: c-command-injection -- calls through a function pointer are not resolved
    runner(argv[4]);

    const char *commands[2];
    commands[0] = argv[5];
    commands[1] = "true";
    // todook: c-command-injection -- an array is one value: its constant element is tainted too
    system(commands[1]);
    return 0;
}
