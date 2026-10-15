/*
 * Command injection with the built-in C rules: `main`'s argv and `getenv`
 * into `system`, `popen` and the exec family, directly, through assignments
 * and pointer arithmetic, loops and branches, a helper's parameter and a
 * returned value; and the flows that are killed or never start: constants,
 * a reassignment on every path, argc.
 */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static void run(const char *command) {
    // ruleid: c-command-injection
    system(command);
}

static const char *editor(void) {
    const char *name = getenv("EDITOR");
    return name;
}

int main(int argc, char *argv[]) {
    // ruleid: c-command-injection
    system(argv[1]);

    char *command = argv[2];
    char *rest = command + 1;
    // ruleid: c-command-injection
    popen(rest, "r");

    for (int i = 1; i < argc; i++) {
        // ruleid: c-command-injection
        execlp("echo", "echo", argv[i], NULL);
    }

    const char *chosen = "true";
    if (argc > 3) {
        chosen = argv[3];
    }
    // ruleid: c-command-injection
    system(chosen);

    run(argv[4]);

    // ruleid: c-command-injection
    system(editor());

    const char *fixed = argv[5];
    fixed = "ls";
    // ok: c-command-injection
    system(fixed);

    // ok: c-command-injection
    system("ls -l");

    // ok: c-command-injection
    system(argc > 1 ? "true" : "false");
    return 0;
}
